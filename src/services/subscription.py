"""Subscription service."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.base import get_session_factory
from src.models.subscription import Subscription, SubscriptionSettings, SubscriptionType
from src.models.user import User, effective_user_id

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext


async def check_subscription_required(user: User) -> bool:
    """True if subscription is required and user doesn't have active one.

    Uses the effective (canonical) user ID so a subscription purchased on
    Telegram is also valid when the same person uses MAX.
    """
    uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(SubscriptionSettings).limit(1))
        settings = result.scalar_one_or_none()
        if not settings or not settings.subscription_enabled:
            return False

        result = await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == uid,
                Subscription.is_active.is_(True),
                Subscription.expires_at >= date.today(),
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        sub = result.scalar_one_or_none()
        return sub is None


async def reconcile_telegram_subscription_checkout(state: "FSMContext", user) -> bool:
    """Перед сбросом FSM: если ждём оплату подписки в TG — проверить ЮKassa и активировать.

    Нужно при «Назад» из экрана оплаты и при /start: иначе `state.clear()` теряет
    payment_id, а вебхук мог не дойти.
    """
    if user is None:
        return False
    from src.handlers.subscription import SubscriptionPayStates
    from src.services.payment import check_payment_status

    if await state.get_state() != SubscriptionPayStates.awaiting.state:
        return False

    data = await state.get_data()
    payment_id = data.get("sub_payment_id")
    period = data.get("sub_period")
    if not payment_id or not period:
        return False

    status = await check_payment_status(payment_id)
    if status != "succeeded":
        logger.info(
            "TG subscription reconcile: payment %s status=%s (skip activation)",
            payment_id,
            status,
        )
        return False

    period_arg = period if period == "monthly" else "season"
    uid = effective_user_id(user)
    ok = await activate_subscription(uid, period_arg, payment_id)
    if ok:
        logger.info("TG subscription reconcile: activated payment %s", payment_id)
    return ok


async def activate_subscription(user_id, period: str, payment_id: str) -> bool:
    """Activate subscription after successful payment.

    New period is added on top of the latest active subscription end date
    (or from today if there is no active subscription), so renewals stack.
    """
    session_factory = get_session_factory()
    today = date.today()
    if period == "monthly":
        add_days = 30
        sub_type = SubscriptionType.MONTHLY
    else:
        # season | year — годовая подписка 365 дней (тип в БД SEASON)
        add_days = 365
        sub_type = SubscriptionType.SEASON

    async with session_factory() as session:
        # Idempotency: if this payment was already processed, treat as success.
        existing = await session.execute(
            select(Subscription).where(Subscription.payment_id == payment_id).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return True

        result = await session.execute(
            select(Subscription.expires_at)
            .where(
                Subscription.user_id == user_id,
                Subscription.is_active.is_(True),
                Subscription.expires_at >= today,
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        current_end = result.scalar_one_or_none()
        base = max(today, current_end) if current_end else today
        expires = base + timedelta(days=add_days)

        sub = Subscription(
            user_id=user_id,
            type=sub_type,
            expires_at=expires,
            payment_id=payment_id,
        )
        session.add(sub)
        try:
            await session.commit()
        except IntegrityError:
            # Concurrent duplicate activation for the same payment_id.
            await session.rollback()
            dup = await session.execute(
                select(Subscription).where(Subscription.payment_id == payment_id).limit(1)
            )
            if dup.scalar_one_or_none() is not None:
                return True
            return False

    from src.services.activity_log_service import log_event
    from src.models.activity_log import ActivityEventType

    await log_event(
        ActivityEventType.SUBSCRIPTION,
        user_id=user_id,
        data={"period": period, "expires": str(expires), "payment_id": payment_id},
    )
    return True
