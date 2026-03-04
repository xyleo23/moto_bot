"""Webhook HTTP server for YooKassa notifications."""
import asyncio
import json
import uuid

from loguru import logger

from src.config import get_settings
from src.services.subscription import activate_subscription
from src.models.base import get_session_factory
from src.models.subscription import Subscription
from sqlalchemy import select


async def handle_yookassa_webhook(request) -> tuple[int, dict]:
    """Handle YooKassa notification. Returns (status_code, body)."""
    try:
        body = await request.read()
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return 400, {"error": "Invalid JSON"}

    event = data.get("event")
    obj = data.get("object", {})

    if event != "payment.succeeded":
        return 200, {"status": "ignored"}

    payment_id = obj.get("id")
    metadata = obj.get("metadata") or {}
    if not payment_id:
        return 200, {"status": "no_id"}

    pay_type = metadata.get("type")
    if pay_type != "subscription":
        return 200, {"status": "ignored", "type": pay_type}

    user_id_str = metadata.get("user_id")
    period = metadata.get("period")
    if not user_id_str or period not in ("monthly", "season"):
        logger.warning("YooKassa webhook: missing user_id or period in metadata")
        return 200, {"status": "bad_metadata"}

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        return 200, {"status": "invalid_user_id"}

    session_factory = get_session_factory()
    # Idempotency: skip if already processed
    async with session_factory() as session:
        existing = await session.execute(
            select(Subscription).where(Subscription.payment_id == payment_id)
        )
        if existing.scalar_one_or_none():
            return 200, {"status": "already_processed"}

    ok = await activate_subscription(user_id, period, payment_id)
    if not ok:
        logger.error("YooKassa webhook: activate_subscription failed for %s", user_id)
        return 200, {"status": "activate_failed"}

    # Notify user via bot (inject bot from app)
    bot = getattr(handle_yookassa_webhook, "_bot", None)
    if bot:
        from src.models.user import User
        ses = get_session_factory()
        async with ses() as session:
            r = await session.execute(select(User).where(User.id == user_id))
            u = r.scalar_one_or_none()
            if u and u.platform_user_id:
                try:
                    period_label = "1 месяц" if period == "monthly" else "Сезон"
                    await bot.send_message(
                        u.platform_user_id,
                        f"✅ Подписка на {period_label} активирована! Спасибо за поддержку.",
                    )
                except Exception as e:
                    logger.warning("Cannot notify user %s: %s", u.platform_user_id, e)

    return 200, {"status": "ok"}


def set_webhook_bot(bot):
    """Inject bot instance for sending notifications."""
    handle_yookassa_webhook._bot = bot


async def run_webhook_server(bot=None):
    """Run aiohttp server for YooKassa webhooks."""
    from aiohttp import web

    settings = get_settings()
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        logger.info("YooKassa not configured, webhook server skipped")
        return

    if bot:
        set_webhook_bot(bot)

    async def handler(request):
        status, body = await handle_yookassa_webhook(request)
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_post("/webhook/yookassa", handler)
    app.router.add_get("/webhook/yookassa", lambda r: web.Response(text="OK", status=200))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    logger.info("Webhook server listening on port %s", settings.webhook_port)
    # Keep running (server is now accepting connections)
    await asyncio.Event().wait()
