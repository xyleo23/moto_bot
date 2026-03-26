"""Profile service."""
from datetime import date, datetime
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.models.subscription import Subscription
from src.models.user import effective_user_id


async def get_profile_display(user) -> tuple[str, str | None]:
    """Текст экрана «Мой профиль» и идентификатор фото (Telegram file_id или MAX token).

    Профиль ищется по effective_user_id. Порядок строк — как в get_profile_info_text:
    сначала пилот, иначе пассажир (не только по user.role, иначе при рассинхроне
    теряется анкета и фото).
    """
    if not user:
        return ("Профиль не найден.", None)
    uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        pilot = (
            await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == uid))
        ).scalar_one_or_none()
        passenger = (
            await session.execute(select(ProfilePassenger).where(ProfilePassenger.user_id == uid))
        ).scalar_one_or_none()

        if pilot:
            p = pilot
            is_pilot = True
        elif passenger:
            p = passenger
            is_pilot = False
        else:
            return ("Анкета не заполнена.", None)

        sub_result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == uid,
                Subscription.is_active.is_(True),
            ).order_by(Subscription.expires_at.desc()).limit(1)
        )
        sub = sub_result.scalar_one_or_none()
        if sub and sub.expires_at:
            expires_fmt = sub.expires_at.strftime("%d.%m.%Y")
            today = datetime.utcnow().date()
            days_left = max(0, (sub.expires_at - today).days)
            sub_text = f"\n\n✅ Подписка активна до {expires_fmt} (осталось {days_left} дн.)"
        else:
            sub_text = "\n\n❌ Подписка не активна"

        if is_pilot:
            text = f"👤 {p.name}\nВозраст: {p.age}\n{p.bike_brand} {p.bike_model}, {p.engine_cc} см³{sub_text}"
        else:
            text = f"👤 {p.name}\nВозраст: {p.age}, Рост: {p.height} см, Вес: {p.weight} кг{sub_text}"
        return (text, p.photo_file_id)


async def get_profile_text(user) -> str:
    text, _ = await get_profile_display(user)
    return text
