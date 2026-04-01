"""Profile service."""

from datetime import datetime
from html import escape
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.profile_pilot import ProfilePilot, DrivingStyle
from src.models.profile_passenger import ProfilePassenger, PreferredStyle
from src.models.subscription import Subscription
from src.models.user import effective_user_id
from src.config import get_settings

_DRIVING_STYLE_RU = {
    DrivingStyle.CALM: "Спокойный",
    DrivingStyle.AGGRESSIVE: "Динамичный",
    DrivingStyle.MIXED: "Смешанный",
}
_PREFERRED_STYLE_RU = {
    PreferredStyle.CALM: "Спокойный",
    PreferredStyle.DYNAMIC: "Динамичный",
    PreferredStyle.MIXED: "Смешанный",
}


async def get_profile_display(user) -> tuple[str, str | None]:
    """Текст экрана «Мой профиль» и идентификатор фото (Telegram file_id или MAX token).

    Строка — HTML (Telegram parse_mode=HTML, MAX format=html): поля анкеты экранируются,
    чтобы символы < > & в «О себе» и имени не ломали разметку и не показывались «сырые» теги.

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
            select(Subscription)
            .where(
                Subscription.user_id == uid,
                Subscription.is_active.is_(True),
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
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
            style_ru = _DRIVING_STYLE_RU.get(p.driving_style, str(p.driving_style.value))
            about_line = (p.about or "").strip()
            about_part = ""
            if about_line:
                lim = min(280, max(80, get_settings().about_text_max_length // 2))
                if len(about_line) > lim:
                    about_line = about_line[: lim - 1] + "…"
                about_part = f"\n<b>О себе:</b> {escape(about_line)}"
            text = (
                f"👤 <b>{escape(p.name)}</b>\n"
                f"<b>Возраст:</b> {p.age}\n"
                f"<b>Тел.:</b> {escape(p.phone)}\n"
                f"<b>Мотоцикл:</b> {escape(p.bike_brand)} {escape(p.bike_model)}, {p.engine_cc} см³\n"
                f"<b>Стиль вождения:</b> {escape(style_ru)}"
                f"{about_part}{sub_text}"
            )
        else:
            pref_ru = _PREFERRED_STYLE_RU.get(p.preferred_style, str(p.preferred_style.value))
            about_line = (p.about or "").strip()
            about_part = ""
            if about_line:
                lim = min(280, max(80, get_settings().about_text_max_length // 2))
                if len(about_line) > lim:
                    about_line = about_line[: lim - 1] + "…"
                about_part = f"\n<b>О себе:</b> {escape(about_line)}"
            text = (
                f"👤 <b>{escape(p.name)}</b>\n"
                f"<b>Возраст:</b> {p.age}, <b>Рост:</b> {p.height} см, <b>Вес:</b> {p.weight} кг\n"
                f"<b>Тел.:</b> {escape(p.phone)}\n"
                f"<b>Предпочитаемый стиль:</b> {escape(pref_ru)}"
                f"{about_part}{sub_text}"
            )
        return (text, p.photo_file_id)


async def get_profile_text(user) -> str:
    text, _ = await get_profile_display(user)
    return text
