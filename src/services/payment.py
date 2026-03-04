"""YooKassa payment service."""
from src.config import get_settings


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

    try:
        from yookassa import Payment
        payment = Payment.create({
            "amount": {"value": f"{amount_kopecks / 100:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url or "https://t.me"},
            "capture": True,
            "description": description[:250],
            "metadata": metadata,
        })
        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": payment.confirmation.confirmation_url if payment.confirmation else None,
        }
    except Exception:
        return None


async def check_payment_status(payment_id: str) -> str | None:
    """Get payment status: pending, waiting_for_capture, succeeded, canceled."""
    try:
        from yookassa import Payment
        payment = Payment.find_one(payment_id)
        return payment.status
    except Exception:
        return None
