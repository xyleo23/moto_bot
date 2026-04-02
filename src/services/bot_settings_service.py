"""CRUD service for BotSettings — single-row settings table."""

from loguru import logger
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.bot_settings import BotSettings


async def get_bot_settings() -> BotSettings:
    """
    Fetch bot settings row, creating it with defaults if it doesn't exist.
    Always returns a valid BotSettings instance.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(BotSettings).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            row = BotSettings()
            session.add(row)
            await session.commit()
            await session.refresh(row)
            logger.info("Created default bot_settings row")
    return row


async def update_bot_settings(**kwargs) -> BotSettings:
    """
    Update one or more bot settings fields.

    Accepted keyword arguments (all optional):
        subscription_enabled, subscription_price_month, subscription_price_season,
        event_creation_paid, event_creation_price,
        profile_raise_paid, profile_raise_price,
        sos_cooldown_minutes, auto_block_reports_threshold, about_text
    """
    allowed = {
        "subscription_enabled",
        "subscription_price_month",
        "subscription_price_season",
        "event_creation_paid",
        "event_creation_price",
        "profile_raise_paid",
        "profile_raise_price",
        "sos_cooldown_minutes",
        "auto_block_reports_threshold",
        "about_text",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return await get_bot_settings()

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(BotSettings).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            row = BotSettings(**filtered)
            session.add(row)
        else:
            for key, value in filtered.items():
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
    return row
