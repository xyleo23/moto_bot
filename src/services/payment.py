"""YooKassa payment service."""
import asyncio
from loguru import logger
from src.config import get_settings


def _configure_yookassa():
    """Configure YooKassa SDK with credentials from settings."""
    settings = get_settings()
    if settings.yookassa_shop_id and settings.yookassa_secret_key:
        from yookassa import Configuration
        Configuration.configure(settings.yookassa_shop_id, settings.yookassa_secret_key)


async def create_payment(
    amount_kopecks: int,
    description: str,
    metadata: dict,
    return_url: str | None = None,
) -> dict | None:
    """Create YooKassa payment. Returns payment with confirmation_url or None."""
    settings = get_settings()
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        return None

    _configure_yookassa()

    def _create():
        from yookassa import Payment
        return Payment.create({
            "amount": {"value": f"{amount_kopecks / 100:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url or "https://t.me"},
            "capture": True,
            "description": description[:250],
            "metadata": metadata,
        })

    try:
        payment = await asyncio.to_thread(_create)
        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": payment.confirmation.confirmation_url if payment.confirmation else None,
        }
    except Exception as e:
        logger.exception("YooKassa create_payment failed: %s", e)
        return None


async def check_payment_status(payment_id: str) -> str | None:
    """Get payment status: pending, waiting_for_capture, succeeded, canceled."""
    settings = get_settings()
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        return None

    _configure_yookassa()

    def _find():
        from yookassa import Payment
        return Payment.find_one(payment_id)

    try:
        payment = await asyncio.to_thread(_find)
        return payment.status
    except Exception as e:
        logger.exception("YooKassa check_payment_status failed: %s", e)
        return None
