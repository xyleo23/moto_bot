"""Profile service."""
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.models.subscription import Subscription
from src.models.user import User, UserRole


async def get_profile_text(user) -> str:
    if not user:
        return "Профиль не найден."
    session_factory = get_session_factory()
    async with session_factory() as session:
        if user.role == UserRole.PILOT:
            result = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == user.id))
            p = result.scalar_one_or_none()
        else:
            result = await session.execute(select(ProfilePassenger).where(ProfilePassenger.user_id == user.id))
            p = result.scalar_one_or_none()

        if not p:
            return "Анкета не заполнена."

        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.is_active.is_(True),
            ).order_by(Subscription.expires_at.desc()).limit(1)
        )
        sub = sub_result.scalar_one_or_none()
        sub_text = (f"\n\nПодписка до {sub.expires_at}" if sub else "\n\nПодписка не активна")

        if user.role == UserRole.PILOT:
            return f"👤 {p.name}\nВозраст: {p.age}\n{p.bike_brand} {p.bike_model}, {p.engine_cc} см³{sub_text}"
        return f"👤 {p.name}\nВозраст: {p.age}, Рост: {p.height} см, Вес: {p.weight} кг{sub_text}"
