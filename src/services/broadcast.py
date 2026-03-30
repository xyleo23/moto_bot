"""
Background broadcast service.

Broadcasts are executed as asyncio background tasks (non-blocking) with a
50ms inter-message delay to respect Telegram's rate limits (~20 msg/s global).

MAX broadcasts use the MAX adapter's send_message API.
"""

import asyncio
import html
import re
from collections.abc import Iterable

from loguru import logger

from src.platforms.max_adapter import (
    max_message_query_params,
    pop_max_messages_use_chat_id_param,
    pop_max_outbound_by_user_id,
    push_max_messages_use_chat_id_param,
    push_max_outbound_by_user_id,
)
from src.services.max_peer_chat import get_dialog_chat_id


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


def _max_broadcast_exclude_set(
    exclude_id: int | None, exclude_ids: Iterable[int] | None
) -> set[int]:
    s: set[int] = set()
    if exclude_id is not None:
        s.add(int(exclude_id))
    if exclude_ids:
        s.update(int(x) for x in exclude_ids)
    return s


async def _do_max_broadcast(
    adapter,
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    exclude_ids: Iterable[int] | None = None,
    kb_rows=None,
) -> tuple[int, int]:
    """Send `text` to MAX users via the adapter.

    Сначала пробуем POST /messages?chat_id=… из последнего диалога (max_peer_chat),
    иначе ?user_id=… — в MAX они не всегда эквивалентны для доставки в чат.
    """
    _token = push_max_outbound_by_user_id()
    sent = 0
    failed = 0
    excl = _max_broadcast_exclude_set(exclude_id, exclude_ids)
    try:
        target_uids = [u for u in user_ids if u not in excl]
        sample_uid = target_uids[0] if target_uids else None
        if sample_uid is not None:
            logger.info(
                "max_broadcast start: in_city_max={} exclude={} will_send_to={} "
                "sample_user_id_query_params={}",
                len(user_ids),
                sorted(excl),
                target_uids,
                max_message_query_params(str(sample_uid)),
            )
        else:
            logger.info(
                "max_broadcast start: in_city_max={} exclude={} will_send_to=[] (nobody to notify)",
                len(user_ids),
                sorted(excl),
            )
        for uid in user_ids:
            if uid in excl:
                continue
            peer = await get_dialog_chat_id(uid)
            routes: list[tuple[str, str]] = []
            if peer and peer != str(uid):
                routes.append(("chat_id", peer))
            routes.append(("user_id", str(uid)))

            delivered = False
            for via, addr in routes:
                ctk = None
                if via == "chat_id":
                    ctk = push_max_messages_use_chat_id_param()
                try:
                    try:
                        await adapter.send_message(addr, text, kb_rows)
                    except Exception as e:
                        logger.warning(
                            "max_broadcast: HTML failed uid={} via={} addr={}: {}",
                            uid,
                            via,
                            addr,
                            e,
                        )
                        plain = _max_broadcast_plain_fallback(text)
                        await adapter.send_message(
                            addr, plain or "(SOS)", kb_rows, parse_mode=None
                        )
                    sent += 1
                    delivered = True
                    logger.info("max_broadcast: ok uid={} via={}", uid, via)
                    break
                except Exception as e2:
                    logger.warning(
                        "max_broadcast: send failed uid={} via={} addr={}: {}",
                        uid,
                        via,
                        addr,
                        e2,
                    )
                finally:
                    if ctk is not None:
                        pop_max_messages_use_chat_id_param(ctk)

            if not delivered:
                failed += 1
            await asyncio.sleep(_SEND_DELAY)
    finally:
        pop_max_outbound_by_user_id(_token)

    logger.info("max_broadcast done: sent={} failed={}", sent, failed)
    return sent, failed


def broadcast_max_background(
    adapter,
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    exclude_ids: Iterable[int] | None = None,
    kb_rows=None,
) -> asyncio.Task:
    """Schedule a MAX broadcast as a fire-and-forget background task."""
    task = asyncio.create_task(
        _do_max_broadcast(
            adapter,
            user_ids,
            text,
            exclude_id=exclude_id,
            exclude_ids=exclude_ids,
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
