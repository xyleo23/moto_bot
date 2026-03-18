"""Webhook HTTP server for YooKassa notifications."""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import uuid

from loguru import logger

from src.config import get_settings
from src.services.subscription import activate_subscription
from src.models.base import get_session_factory
from src.models.subscription import Subscription
from src.models.user import User, Platform
from sqlalchemy import select

# YooKassa official IP ranges for webhook sources.
# Requests from outside these ranges are rejected.
_YOOKASSA_IP_RANGES = [
    ipaddress.ip_network("185.71.76.0/27"),
    ipaddress.ip_network("185.71.77.0/27"),
    ipaddress.ip_network("77.75.153.0/25"),
    ipaddress.ip_network("77.75.154.128/25"),
    ipaddress.ip_network("2a02:5180::/32"),
]


def _is_yookassa_ip(remote_ip: str) -> bool:
    """Return True if remote_ip belongs to known YooKassa IP ranges."""
    try:
        addr = ipaddress.ip_address(remote_ip)
        return any(addr in net for net in _YOOKASSA_IP_RANGES)
    except ValueError:
        return False


def _verify_yookassa_signature(body: bytes, signature_header: str, secret_key: str) -> bool:
    """
    Verify YooKassa webhook HMAC-SHA256 signature.

    YooKassa signs the raw body with the shop's secret key using HMAC-SHA256
    and puts the hex digest in the 'X-Content-Signature' header.
    """
    if not signature_header or not secret_key:
        return False
    try:
        expected = hmac.new(
            secret_key.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        # compare_digest prevents timing attacks
        return hmac.compare_digest(expected, signature_header.lower())
    except Exception as e:
        logger.warning("Signature verification error: %s", e)
        return False


async def handle_yookassa_webhook(request) -> tuple[int, dict]:
    """
    Handle YooKassa notification.

    Security: requests are verified via EITHER:
    1. HMAC-SHA256 signature in X-Content-Signature header, OR
    2. Source IP belonging to known YooKassa IP ranges.

    Returns (status_code, body).
    """
    settings = get_settings()

    # ── Signature / IP verification ──────────────────────────────────────────
    body = await request.read()
    signature = request.headers.get("X-Content-Signature", "")
    remote_ip = request.remote or ""

    sig_valid = _verify_yookassa_signature(
        body, signature, settings.yookassa_secret_key or ""
    )
    ip_valid = _is_yookassa_ip(remote_ip)

    if not sig_valid and not ip_valid:
        logger.warning(
            "YooKassa webhook rejected: invalid signature and untrusted IP %s", remote_ip
        )
        return 401, {"error": "Unauthorized"}

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
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

    async def _notify_user(user_id_uuid: uuid.UUID, msg: str, source_platform: str | None = None) -> None:
        """Send notification to user via Telegram bot or MAX adapter.

        When source_platform='max', prefers to notify via the MAX account:
        either the user themselves (if they're a MAX user) or a linked MAX account.
        Falls back to the canonical user's platform if no MAX account is found.
        """
        async with get_session_factory()() as session:
            # If payment originated from MAX, try to find the MAX account to notify
            if source_platform == "max":
                r = await session.execute(
                    select(User).where(
                        User.platform == Platform.MAX,
                        (User.id == user_id_uuid) | (User.linked_user_id == user_id_uuid),
                    )
                )
                u = r.scalars().first()
            else:
                u = None

            if u is None:
                r = await session.execute(select(User).where(User.id == user_id_uuid))
                u = r.scalar_one_or_none()

        if not u or not u.platform_user_id:
            return
        chat_id = str(u.platform_user_id)
        if u.platform == Platform.MAX:
            try:
                from src.platforms.max_adapter import MaxAdapter
                adapter = MaxAdapter()
                await adapter.send_message(chat_id, msg)
            except Exception as e:
                logger.warning("Cannot notify MAX user %s: %s", chat_id, e)
        else:
            bot = getattr(handle_yookassa_webhook, "_bot", None)
            if bot:
                try:
                    await bot.send_message(u.platform_user_id, msg)
                except Exception as e:
                    logger.warning("Cannot notify TG user %s: %s", u.platform_user_id, e)

    src_platform = metadata.get("platform")

    if pay_type == "donate":
        user_id_str = metadata.get("user_id")
        if user_id_str:
            try:
                user_id = uuid.UUID(user_id_str)
                await _notify_user(user_id, "❤️ Спасибо за поддержку проекта!", src_platform)
            except (ValueError, TypeError) as e:
                logger.warning("donate webhook: malformed metadata user_id=%r: %s", user_id_str, e)
        return 200, {"status": "ok", "type": "donate"}

    if pay_type == "event_creation":
        user_id_str = metadata.get("user_id")
        if user_id_str:
            try:
                await _notify_user(
                    uuid.UUID(user_id_str),
                    "✅ Оплата создания мероприятия прошла! Вернись в бот и нажми «Я оплатил — проверить».",
                    src_platform,
                )
            except (ValueError, TypeError) as e:
                logger.warning("event_creation webhook: invalid user_id: %s", e)
        return 200, {"status": "ok", "type": "event_creation"}

    if pay_type == "raise_profile":
        user_id_str = metadata.get("user_id")
        if user_id_str:
            try:
                await _notify_user(
                    uuid.UUID(user_id_str),
                    "✅ Оплата поднятия анкеты прошла! Вернись в бот и нажми «Я оплатил — проверить».",
                    src_platform,
                )
            except (ValueError, TypeError) as e:
                logger.warning("raise_profile webhook: invalid user_id: %s", e)
        return 200, {"status": "ok", "type": "raise_profile"}

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

    # Notify user via Telegram or MAX
    from src.services.notification_templates import get_template
    period_label = "1 месяц" if period == "monthly" else "Сезон"
    msg = await get_template("template_subscription_activated", period=period_label)
    await _notify_user(user_id, msg, src_platform)

    return 200, {"status": "ok"}


def set_webhook_bot(bot):
    """Inject bot instance for sending notifications."""
    handle_yookassa_webhook._bot = bot


async def run_webhook_server(bot=None):
    """Run aiohttp server for /health and YooKassa webhooks.

    Health endpoint is always exposed. Webhook routes are added only when YooKassa is configured.
    """
    from aiohttp import web

    settings = get_settings()
    if bot:
        set_webhook_bot(bot)

    app = web.Application()

    async def health(request):
        """Health check for monitoring. Probes DB."""
        try:
            async with get_session_factory()() as session:
                await session.execute(select(1))  # DB ping
        except Exception as e:
            logger.warning("Health check DB failed: %s", e)
            return web.json_response({"status": "degraded", "db": "error"}, status=503)
        return web.json_response({"status": "ok"}, status=200)

    app.router.add_get("/health", health)

    if settings.yookassa_shop_id and settings.yookassa_secret_key:
        async def handler(request):
            status, body = await handle_yookassa_webhook(request)
            return web.json_response(body, status=status)

        app.router.add_post("/webhook/yookassa", handler)
        app.router.add_get("/webhook/yookassa", lambda r: web.Response(text="OK", status=200))
        logger.info("YooKassa webhook routes registered")
    else:
        logger.info("YooKassa not configured, webhook routes skipped")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()
    logger.info("HTTP server listening on port %s (GET /health)", settings.webhook_port)
    await asyncio.Event().wait()
