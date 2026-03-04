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

    # #region agent log
    import json
    import time
    try:
        with open(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"ca1ad6","location":"main.py:run_telegram","message":"run_telegram starting","data":{},"timestamp":int(time.time()*1000),"hypothesisId":"H1,H5"}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion
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

    async def log_updates(handler, event, data):
        # #region agent log
        import json
        import time
        text = getattr(event, "text", None) or ""
        if "/start" in (text or ""):
            try:
                with open(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"ca1ad6","location":"main.py:log_updates","message":"INCOMING /start","data":{"user_id":getattr(event.from_user,"id",None),"text":text[:50]},"timestamp":int(time.time()*1000),"hypothesisId":"H2"}, ensure_ascii=False) + "\n")
            except Exception:
                pass
        # #endregion
        if hasattr(event, "text") and event.text:
            logger.info("INCOMING: user=%s text=%r", getattr(event.from_user, "id", None), event.text[:80])
        elif hasattr(event, "data") and event.data:
            logger.info("INCOMING: callback user=%s data=%r", getattr(event.from_user, "id", None), event.data[:80])
        return await handler(event, data)

    dp.message.middleware(log_updates)
    dp.callback_query.middleware(log_updates)
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

    @dp.errors()
    async def errors_handler(event):
        logger.exception("Update %s caused error: %s", event.update, event.exception)

    await ensure_cities()
    await ensure_subscription_settings()
    # Ensure bot_settings row exists (creates with defaults if absent)
    from src.services.bot_settings_service import get_bot_settings
    await get_bot_settings()

    from src.webhooks import run_webhook_server
    from src.services.scheduler import run_scheduler

    webhook_task = asyncio.create_task(run_webhook_server(bot))
    scheduler_task = asyncio.create_task(run_scheduler(bot))

    sa_count = len(settings.superadmin_ids)
    logger.info(
        "Starting Telegram bot... (superadmins: %d)",
        sa_count,
    )
    if sa_count == 0:
        logger.warning(
            "SUPERADMIN_IDS is empty in .env — никто не получит админ-панель. "
            "Добавь свой Telegram user_id (например через @userinfobot)"
        )
    # Удаляем webhook — при polling Telegram отправляет обновления только в getUpdates.
    # Если webhook установлен, polling не получает обновления.
    try:
        wh = await bot.get_webhook_info()
        # #region agent log
        import json
        import time
        try:
            with open(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"ca1ad6","location":"main.py:webhook","message":"Webhook info","data":{"webhook_url":wh.url or "(none)"},"timestamp":int(time.time()*1000),"hypothesisId":"H5"}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # #endregion
        if wh.url:
            logger.warning("Webhook was set: %s — removing for polling", wh.url)
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook removed, polling ready")
    except Exception as e:
        logger.error("Webhook check/delete failed: %s — bot may not receive updates!", e)
    try:
        await dp.start_polling(bot)
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

    # #region agent log
    import json
    import time
    try:
        with open(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"ca1ad6","location":"main.py:main","message":"Platform selected","data":{"platform":platform,"has_telegram_token":bool(settings.telegram_bot_token)},"timestamp":int(time.time()*1000),"hypothesisId":"H1"}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

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
