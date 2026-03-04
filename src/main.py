"""Main entry point for the bot."""
import asyncio
import sys

from loguru import logger

from src.config import get_settings
from src.models.base import init_db
from src.models import City


async def ensure_cities():
    """Ensure Yekaterinburg city exists."""
    from src.models.base import get_session_factory
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(City).where(City.name == "Екатеринбург"))
        city = result.scalar_one_or_none()
        if not city:
            city = City(name="Екатеринбург")
            session.add(city)
            await session.commit()
            logger.info("Created city: Екатеринбург")


async def ensure_subscription_settings():
    """Ensure subscription_settings has a row."""
    from src.models.base import get_session_factory
    from sqlalchemy import select
    from src.models.subscription import SubscriptionSettings

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(SubscriptionSettings).limit(1))
        if not result.scalar_one_or_none():
            s = SubscriptionSettings()
            session.add(s)
            await session.commit()
            logger.info("Created subscription_settings")


def setup_logging():
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="INFO",
    )


async def run_telegram():
    """Run Telegram bot with aiogram."""
    from aiogram import Bot, Dispatcher
    from aiogram.fsm.storage.redis import RedisStorage
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from redis.asyncio import Redis

    from src.handlers import (
        start,
        registration,
        sos,
        motopair,
        events,
        contacts,
        profile,
        profile_edit,
        about,
        admin,
    )
    from src.handlers.middleware import BlockCheckMiddleware, BotInjectMiddleware

    settings = get_settings()
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required for Telegram platform")

    init_db()

    try:
        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
        storage = RedisStorage(redis=redis)
        _redis = redis
        # Inject Redis client into SOS service for rate limiting
        from src.services.sos_service import set_redis_client
        set_redis_client(redis)
    except Exception as e:
        logger.warning("Redis unavailable (%s), using MemoryStorage", e)
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        _redis = None

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    dp.message.middleware(BotInjectMiddleware(bot))
    dp.callback_query.middleware(BotInjectMiddleware(bot))
    dp.message.middleware(BlockCheckMiddleware())
    dp.callback_query.middleware(BlockCheckMiddleware())

    dp.include_router(start.router)
    dp.include_router(registration.router)
    dp.include_router(sos.router)
    dp.include_router(motopair.router)
    dp.include_router(events.router)
    dp.include_router(contacts.router)
    dp.include_router(profile.router)
    dp.include_router(profile_edit.router)
    dp.include_router(about.router)
    dp.include_router(admin.router)
    from src.handlers import admin_contacts, subscription
    dp.include_router(admin_contacts.router)
    dp.include_router(subscription.router)

    await ensure_cities()
    await ensure_subscription_settings()
    # Ensure bot_settings row exists (creates with defaults if absent)
    from src.services.bot_settings_service import get_bot_settings
    await get_bot_settings()

    from src.webhooks import run_webhook_server
    from src.services.scheduler import run_scheduler

    webhook_task = asyncio.create_task(run_webhook_server(bot))
    scheduler_task = asyncio.create_task(run_scheduler(bot))

    logger.info("Starting Telegram bot...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        webhook_task.cancel()
        scheduler_task.cancel()
        for task in (webhook_task, scheduler_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        await bot.session.close()
        if _redis:
            await _redis.close()


async def run_max():
    """Run MAX bot (long polling)."""
    from src.platforms.max_adapter import MaxAdapter
    from src.max_runner import process_max_update

    settings = get_settings()
    if not settings.max_bot_token:
        raise ValueError("MAX_BOT_TOKEN is required for MAX platform")

    init_db()
    await ensure_cities()
    await ensure_subscription_settings()

    adapter = MaxAdapter()
    logger.info("Starting MAX bot (long polling)...")

    marker = None
    try:
        while True:
            try:
                result = await adapter.poll_updates(marker=marker, timeout=30)
                marker = result.get("marker")
                for upd in result.get("updates", []):
                    if isinstance(upd, dict):
                        await process_max_update(adapter, upd)
            except Exception as e:
                logger.exception("MAX poll error: %s", e)
                await asyncio.sleep(5)
    finally:
        await adapter.close()


def main():
    setup_logging()
    settings = get_settings()
    platform = settings.platform.lower()

    if platform == "telegram":
        asyncio.run(run_telegram())
    elif platform == "max":
        asyncio.run(run_max())
    elif platform == "both":
        # Run both in parallel
        async def run_both():
            await asyncio.gather(run_telegram(), run_max())
        asyncio.run(run_both())
    else:
        raise ValueError(f"Unknown platform: {platform}")


if __name__ == "__main__":
    main()
