"""
Background broadcast service.

Broadcasts are executed as asyncio background tasks (non-blocking) with a
50ms inter-message delay to respect Telegram's rate limits (~20 msg/s global).

MAX broadcasts use the MAX adapter's send_message API.
"""

import asyncio
import html
import re

from loguru import logger

from src.platforms.max_adapter import (
    max_message_query_params,
    pop_max_outbound_by_user_id,
    push_max_outbound_by_user_id,
)


def _max_broadcast_plain_fallback(html_text: str) -> str:
    """Strip HTML for MAX retry if API rejects formatted body."""
    t = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()

# 50 ms between messages — stays well under Telegram's 30 msg/s per bot limit
_SEND_DELAY = 0.05

# Module-level MAX adapter reference (injected at startup when platform includes MAX)
_max_adapter = None


def set_max_adapter(adapter) -> None:
    """Inject the shared MAX adapter from main.py startup."""
    global _max_adapter
    _max_adapter = adapter


def get_max_adapter():
    """Return the registered MAX adapter (None if MAX platform not running)."""
    return _max_adapter


async def _do_broadcast(
    bot,
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    reply_markup=None,
) -> tuple[int, int]:
    """
    Send `text` to all `user_ids`, skipping `exclude_id`.

    Returns:
        (sent_count, failed_count)
    """
    sent = 0
    failed = 0
    tg_targets = [u for u in user_ids if exclude_id is None or u != exclude_id]
    logger.info("tg_broadcast start: will_send_to={}", tg_targets)
    for uid in user_ids:
        if exclude_id is not None and uid == exclude_id:
            continue
        try:
            kwargs = {"text": text, "parse_mode": "HTML"}
            if reply_markup is not None:
                kwargs["reply_markup"] = reply_markup
            await bot.send_message(uid, **kwargs)
            sent += 1
            logger.info("tg_broadcast: ok uid={}", uid)
        except Exception as e:
            logger.warning(f"broadcast: could not send to {uid}: {e}")
            failed += 1
        await asyncio.sleep(_SEND_DELAY)

    logger.info(f"tg_broadcast done: sent={sent} failed={failed}")
    return sent, failed


def broadcast_background(
    bot,
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    reply_markup=None,
) -> asyncio.Task:
    """
    Schedule a Telegram broadcast as a fire-and-forget background task.

    The task is not awaited — it runs independently of the current handler,
    preventing the event loop from blocking on large recipient lists.

    Returns the asyncio.Task for optional monitoring.
    """
    task = asyncio.create_task(
        _do_broadcast(bot, user_ids, text, exclude_id=exclude_id, reply_markup=reply_markup)
    )
    task.add_done_callback(
        lambda t: (
            logger.warning("broadcast task error: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
    )
    return task


async def _do_max_broadcast(
    adapter,
    recipients: list[tuple[int, str, bool]],
    text: str,
    exclude_platform_user_id: int | None = None,
    kb_rows=None,
) -> tuple[int, int]:
    """Send `text` to MAX users.

    ``recipients``: (platform_user_id, api_target_str, use_chat_id_param) —
    см. get_city_max_broadcast_recipients: для лички нужен chat_id диалога.
    """
    _token = push_max_outbound_by_user_id()
    sent = 0
    failed = 0
    try:
        to_send = [
            (puid, target, use_chat)
            for puid, target, use_chat in recipients
            if exclude_platform_user_id is None or puid != exclude_platform_user_id
        ]
        if to_send:
            _p0, t0, c0 = to_send[0]
            logger.info(
                "max_broadcast start: rows={} exclude_platform_user_id={} will_send_to={} "
                "sample_query_params={}",
                len(recipients),
                exclude_platform_user_id,
                to_send,
                max_message_query_params(t0, use_chat_id_param=c0),
            )
        else:
            logger.info(
                "max_broadcast start: rows={} exclude_platform_user_id={} will_send_to=[]",
                len(recipients),
                exclude_platform_user_id,
            )
        for puid, target, use_chat in to_send:
            try:
                await adapter.send_message(
                    target, text, kb_rows, use_chat_id_param=use_chat
                )
                sent += 1
                logger.info(
                    "max_broadcast: ok platform_user_id={} target={} use_chat_id={}",
                    puid,
                    target,
                    use_chat,
                )
            except Exception as e:
                logger.warning(
                    "max_broadcast: HTML send failed platform_user_id={} target={}: {}",
                    puid,
                    target,
                    e,
                )
                try:
                    plain = _max_broadcast_plain_fallback(text)
                    await adapter.send_message(
                        target,
                        plain or "(SOS)",
                        kb_rows,
                        parse_mode=None,
                        use_chat_id_param=use_chat,
                    )
                    sent += 1
                    logger.info("max_broadcast: plain fallback ok platform_user_id={}", puid)
                except Exception as e2:
                    logger.warning(
                        "max_broadcast: plain send failed platform_user_id={}: {}",
                        puid,
                        e2,
                    )
                    failed += 1
            await asyncio.sleep(_SEND_DELAY)
    finally:
        pop_max_outbound_by_user_id(_token)

    logger.info("max_broadcast done: sent={} failed={}", sent, failed)
    return sent, failed


def broadcast_max_background(
    adapter,
    recipients: list[tuple[int, str, bool]],
    text: str,
    exclude_platform_user_id: int | None = None,
    kb_rows=None,
) -> asyncio.Task:
    """Schedule a MAX broadcast as a fire-and-forget background task."""
    task = asyncio.create_task(
        _do_max_broadcast(
            adapter,
            recipients,
            text,
            exclude_platform_user_id=exclude_platform_user_id,
            kb_rows=kb_rows,
        )
    )
    task.add_done_callback(
        lambda t: (
            logger.warning("max_broadcast task error: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
    )
    return task
