"""
Background scheduler for periodic tasks.

Runs as an asyncio task in the bot process. Current tasks:
- Daily check for subscriptions expiring within 3 days → push reminder
"""

import asyncio
from datetime import datetime, timedelta

from loguru import logger


# Check interval: once every 24 hours
_CHECK_INTERVAL_SECONDS = 24 * 60 * 60

# Warn when ≤ this many days remain
_EXPIRY_WARN_DAYS = 3

# Min interval between reminders to same user (seconds) — не спамить при перезапусках
_SUB_REMINDER_COOLDOWN_SECONDS = 24 * 60 * 60  # 24 часа

_SUB_REMINDER_KEY = "sub_expiry_reminder:{user_id}"


async def _check_expiring_subscriptions(bot) -> None:
    """Query subscriptions expiring within _EXPIRY_WARN_DAYS and send reminders."""
    from sqlalchemy import select
    from src.models.base import get_session_factory
    from src.models.subscription import Subscription
    from src.models.user import User
    from src import texts
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.sos_service import get_redis_client

    redis = get_redis_client()
    session_factory = get_session_factory()
    now = datetime.utcnow().date()
    warn_until = now + timedelta(days=_EXPIRY_WARN_DAYS)

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(Subscription, User)
                .join(User, Subscription.user_id == User.id)
                .where(
                    Subscription.is_active.is_(True),
                    Subscription.expires_at >= now,
                    Subscription.expires_at <= warn_until,
                )
            )
            rows = result.all()

        sent = 0
        for sub, user in rows:
            key = _SUB_REMINDER_KEY.format(user_id=user.platform_user_id)
            if redis:
                ttl = await redis.ttl(key)
                if ttl > 0:
                    continue  # уже отправляли недавно — пропускаем
            days_left = (sub.expires_at - now).days
            days_word = _days_word(days_left)
            text = texts.SUB_EXPIRY_REMINDER.format(days=days_left, days_word=days_word)
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=texts.SUB_RENEW_BTN, callback_data="profile_subscribe"
                        )
                    ],
                ]
            )
            try:
                await bot.send_message(user.platform_user_id, text, reply_markup=kb)
                sent += 1
                if redis:
                    await redis.setex(key, _SUB_REMINDER_COOLDOWN_SECONDS, "1")
            except Exception as e:
                logger.debug("Cannot send expiry reminder to %s: %s", user.platform_user_id, e)

        logger.info(f"Subscription expiry check done: {sent} users notified")
    except Exception as e:
        logger.exception("Error in _check_expiring_subscriptions: %s", e)


def _days_word(n: int) -> str:
    """Return correctly declined Russian word for 'day'."""
    if 11 <= n % 100 <= 14:
        return "дней"
    mod = n % 10
    if mod == 1:
        return "день"
    if 2 <= mod <= 4:
        return "дня"
    return "дней"


async def run_scheduler(bot) -> None:
    """
    Long-running background scheduler loop.

    Runs the subscription expiry check immediately on startup,
    then repeats every 24 hours.
    """
    logger.info("Scheduler started")
    while True:
        await _check_expiring_subscriptions(bot)
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
