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


async def _check_expiring_subscriptions(bot) -> None:
    """Query subscriptions expiring within _EXPIRY_WARN_DAYS and send reminders."""
    from sqlalchemy import select, and_
    from src.models.base import get_session_factory
    from src.models.subscription import Subscription
    from src.models.user import User
    from src.keyboards.menu import get_back_to_menu_kb
    from src import texts
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

        for sub, user in rows:
            days_left = (sub.expires_at - now).days
            days_word = _days_word(days_left)
            text = texts.SUB_EXPIRY_REMINDER.format(days=days_left, days_word=days_word)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=texts.SUB_RENEW_BTN, callback_data="profile_subscribe")],
            ])
            try:
                await bot.send_message(user.platform_user_id, text, reply_markup=kb)
            except Exception as e:
                logger.debug("Cannot send expiry reminder to %s: %s", user.platform_user_id, e)

        logger.info(f"Subscription expiry check done: {len(rows)} users notified")
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
