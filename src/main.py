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
        legal,
        admin,
    )
    from src.handlers.middleware import BlockCheckMiddleware, BotInjectMiddleware

    settings = get_settings()
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required for Telegram platform")

    try:
        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
        storage = RedisStorage(redis=redis)
        _redis = redis
        # Inject Redis client into SOS service for rate limiting
        from src.services.sos_service import set_redis_client
        set_redis_client(redis)
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), using MemoryStorage")
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        _redis = None

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Сразу снимаем webhook — иначе polling не получит обновления
    for attempt in range(3):
        try:
            wh = await bot.get_webhook_info()
            if wh.url:
                logger.warning(f"Webhook установлен: {wh.url} — снимаю (попытка {attempt + 1})")
            await bot.delete_webhook(drop_pending_updates=True)
            # Проверка что webhook снят
            wh_after = await bot.get_webhook_info()
            if wh_after.url:
                logger.error(f"Webhook всё ещё установлен после delete! URL: {wh_after.url}")
            else:
                logger.info("Webhook снят, polling готов")
            break
        except Exception as e:
            logger.warning(f"Снятие webhook (попытка {attempt + 1}) не удалось: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
            else:
                logger.error(
                    "НЕ УДАЛОСЬ СНЯТЬ WEBHOOK после 3 попыток! "
                    "Бот не получит обновления. Выполни на сервере: ./deploy/check-telegram.sh"
                )
    dp = Dispatcher(storage=storage)

    async def log_updates(handler, event, data):
        if hasattr(event, "text") and event.text:
            logger.info(f"INCOMING: user={getattr(event.from_user, 'id', None)} text={event.text[:80]!r}")
        elif hasattr(event, "data") and event.data:
            logger.info(f"INCOMING: callback user={getattr(event.from_user, 'id', None)} data={event.data[:80]!r}")
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
    dp.include_router(legal.router)
    dp.include_router(admin.router)
    from src.handlers import admin_contacts, subscription
    dp.include_router(admin_contacts.router)
    dp.include_router(subscription.router)

    @dp.errors()
    async def errors_handler(event):
        logger.exception(f"Update {event.update} caused error: {event.exception}")

    from src.services.notification_templates import ensure_default_templates
    await ensure_default_templates()
    from src.services.bot_settings_service import get_bot_settings
    await get_bot_settings()

    from src.webhooks import run_webhook_server
    from src.services.scheduler import run_scheduler

    webhook_task = asyncio.create_task(run_webhook_server(bot))
    scheduler_task = asyncio.create_task(run_scheduler(bot))

    # Команды для всех пользователей
    from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat
    user_commands = [
        BotCommand(command="start",    description="🏠 Главное меню"),
        BotCommand(command="admin",    description="⚙️ Панель администратора"),
        BotCommand(command="cancel",   description="❌ Отменить текущее действие"),
        BotCommand(command="sos",      description="🚨 Экстренный SOS"),
        BotCommand(command="profile",  description="👤 Мой профиль"),
        BotCommand(command="motopair", description="🏍 Поиск мотопары"),
        BotCommand(command="events",   description="📅 Мероприятия"),
        BotCommand(command="contacts", description="📞 Полезные контакты"),
        BotCommand(command="about",    description="ℹ️ О нас"),
        BotCommand(command="privacy",  description="🔒 Политика конфиденциальности"),
        BotCommand(command="consent",  description="✅ Согласие на обработку ПД"),
        BotCommand(command="delete_data", description="🗑 Удалить мои данные"),
        BotCommand(command="support",  description="📞 Поддержка"),
    ]
    await bot.set_my_commands(commands=user_commands, scope=BotCommandScopeDefault())

    # Суперадмины получают те же команды (admin уже в общем списке для всех)
    admin_commands = user_commands
    for sa_id in settings.superadmin_ids:
        try:
            await bot.set_my_commands(
                commands=admin_commands,
                scope=BotCommandScopeChat(chat_id=sa_id),
            )
        except Exception as e:
            logger.warning(f"Cannot set admin commands for {sa_id}: {e}")

    logger.info("Bot commands registered")

    sa_count = len(settings.superadmin_ids)
    logger.info(f"Starting Telegram bot... (superadmins: {sa_count})")
    if sa_count == 0:
        logger.warning(
            "SUPERADMIN_IDS is empty in .env — никто не получит админ-панель. "
            "Добавь свой Telegram user_id (например через @userinfobot)"
        )
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

    adapter = MaxAdapter()

    # Connection diagnostics
    try:
        me = await adapter.get_me()
        logger.info(f"MAX bot connected: {me}")
    except Exception as e1:
        try:
            await adapter.poll_updates(marker=None, timeout=1)
            logger.info("MAX bot connected (API reachable via /updates)")
        except Exception as e2:
            logger.warning(f"MAX bot CANNOT connect: {e1}")
            # Continue in retry mode

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
                logger.exception(f"MAX poll error: {e}")
                await asyncio.sleep(5)
    finally:
        await adapter.close()


def main():
    setup_logging()
    settings = get_settings()
    platform = settings.platform.lower()

    if platform == "telegram":
        async def _telegram_only():
            init_db()
            await ensure_cities()
            await ensure_subscription_settings()
            await run_telegram()
        asyncio.run(_telegram_only())
    elif platform == "max":
        async def _max_only():
            init_db()
            await ensure_cities()
            await ensure_subscription_settings()
            await run_max()
        asyncio.run(_max_only())
    elif platform == "both":
        async def run_both():
            # Init DB and shared state ONCE before starting both bots concurrently
            init_db()
            await ensure_cities()
            await ensure_subscription_settings()
            await asyncio.gather(run_telegram(), run_max())
        asyncio.run(run_both())
    else:
        raise ValueError(f"Unknown platform: {platform}")


if __name__ == "__main__":
    main()
