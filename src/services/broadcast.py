"""
Background broadcast service.

Broadcasts are executed as asyncio background tasks (non-blocking) with a
50ms inter-message delay to respect Telegram's rate limits (~20 msg/s global).

MAX broadcasts use the MAX adapter's send_message API.
"""

import asyncio

from loguru import logger

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
    for uid in user_ids:
        if exclude_id is not None and uid == exclude_id:
            continue
        try:
            kwargs = {"text": text, "parse_mode": "HTML"}
            if reply_markup is not None:
                kwargs["reply_markup"] = reply_markup
            await bot.send_message(uid, **kwargs)
            sent += 1
        except Exception as e:
            logger.warning(f"broadcast: could not send to {uid}: {e}")
            failed += 1
        await asyncio.sleep(_SEND_DELAY)

    logger.info(f"broadcast done: sent={sent} failed={failed}")
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
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    kb_rows=None,
) -> tuple[int, int]:
    """Send `text` to MAX users via the adapter."""
    sent = 0
    failed = 0
    for uid in user_ids:
        if exclude_id is not None and uid == exclude_id:
            continue
        try:
            await adapter.send_message(str(uid), text, kb_rows)
            sent += 1
        except Exception as e:
            logger.warning(f"max_broadcast: could not send to {uid}: {e}")
            failed += 1
        await asyncio.sleep(_SEND_DELAY)

    logger.info(f"max_broadcast done: sent={sent} failed={failed}")
    return sent, failed


def broadcast_max_background(
    adapter,
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    kb_rows=None,
) -> asyncio.Task:
    """Schedule a MAX broadcast as a fire-and-forget background task."""
    task = asyncio.create_task(
        _do_max_broadcast(adapter, user_ids, text, exclude_id=exclude_id, kb_rows=kb_rows)
    )
    task.add_done_callback(
        lambda t: (
            logger.warning("max_broadcast task error: %s", t.exception())
            if not t.cancelled() and t.exception()
            else None
        )
    )
    return task
