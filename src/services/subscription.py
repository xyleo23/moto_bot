"""Subscription service."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models.base import get_session_factory
from src.models.subscription import Subscription, SubscriptionSettings, SubscriptionType
from src.models.user import User, effective_user_id


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


async def activate_subscription(user_id, period: str, payment_id: str) -> bool:
    """Activate subscription after successful payment."""
    session_factory = get_session_factory()
    today = date.today()
    if period == "monthly":
        expires = today + timedelta(days=30)
        sub_type = SubscriptionType.MONTHLY
    else:
        # season | year — годовая подписка 365 дней (тип в БД SEASON)
        expires = today + timedelta(days=365)
        sub_type = SubscriptionType.SEASON

    async with session_factory() as session:
        # Idempotency: if this payment was already processed, treat as success.
        existing = await session.execute(
            select(Subscription).where(Subscription.payment_id == payment_id).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return True

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
