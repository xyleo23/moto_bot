"""YooKassa webhook idempotency.

Пакет 15 000 ₽, пункт Д: общая защита от повторного начисления при retry
webhook'а ЮKassa. Каждый payment_id записывается ровно один раз;
вторая попытка обработать тот же payment_id вернёт False.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from src.models.base import get_session_factory
from src.models.processed_payment import ProcessedPayment


async def mark_payment_processed(payment_id: str, payment_type: str) -> bool:
    """Атомарно зафиксировать факт обработки платежа.

    Returns:
        True — это первая обработка, продолжайте бизнес-логику.
        False — payment_id уже обрабатывался ранее, действие игнорируется.
    """
    if not payment_id:
        return False
    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(ProcessedPayment(payment_id=payment_id, payment_type=payment_type))
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False
