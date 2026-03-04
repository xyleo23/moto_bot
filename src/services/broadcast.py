"""
Background broadcast service.

Broadcasts are executed as asyncio background tasks (non-blocking) with a
50ms inter-message delay to respect Telegram's rate limits (~20 msg/s global).
"""
import asyncio

from loguru import logger

# 50 ms between messages — stays well under Telegram's 30 msg/s per bot limit
_SEND_DELAY = 0.05


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
            kwargs = {"text": text}
            if reply_markup is not None:
                kwargs["reply_markup"] = reply_markup
            await bot.send_message(uid, **kwargs)
            sent += 1
        except Exception as e:
            logger.debug("broadcast: could not send to %s: %s", uid, e)
            failed += 1
        await asyncio.sleep(_SEND_DELAY)

    logger.info("broadcast done: sent=%d failed=%d", sent, failed)
    return sent, failed


def broadcast_background(
    bot,
    user_ids: list[int],
    text: str,
    exclude_id: int | None = None,
    reply_markup=None,
) -> asyncio.Task:
    """
    Schedule a broadcast as a fire-and-forget background task.

    The task is not awaited — it runs independently of the current handler,
    preventing the event loop from blocking on large recipient lists.

    Returns the asyncio.Task for optional monitoring.
    """
    task = asyncio.create_task(
        _do_broadcast(bot, user_ids, text, exclude_id=exclude_id, reply_markup=reply_markup)
    )
    task.add_done_callback(
        lambda t: logger.warning("broadcast task error: %s", t.exception())
        if not t.cancelled() and t.exception()
        else None
    )
    return task
