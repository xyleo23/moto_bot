"""Notification templates (global_texts). Placeholders: {profile}, {period}."""

from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.global_text import GlobalText


# (default_text, description) for admin UI
TEMPLATE_KEYS = {
    "template_mutual_like_self": (
        "🎉 <b>Взаимный лайк!</b>\n\n{profile}",
        "Инициатору взаимного лайка. Плейсхолдеры: {profile}",
    ),
    "template_mutual_like_target": (
        "🎉 <b>Взаимный лайк!</b>\n\n{profile}\n\nВы понравились друг другу — напишите первым!",
        "Получателю взаимного лайка. Плейсхолдеры: {profile}",
    ),
    "template_mutual_like_reply": (
        "🎉 <b>Взаимный лайк!</b>\n\n{profile}\n\nОни ответили на твой лайк — напиши первым!",
        "При ответе на лайк. Плейсхолдеры: {profile}",
    ),
    "template_like_received": (
        "💌 <b>Кто-то лайкнул твою анкету!</b>\n\n{profile}",
        "Уведомление о новом лайке. Плейсхолдеры: {profile}",
    ),
    "template_subscription_activated": (
        "✅ Подписка на {period} активирована! Спасибо за поддержку.",
        "После активации подписки. Плейсхолдеры: {period}",
    ),
}

DEFAULT_TEMPLATES = {k: v[0] for k, v in TEMPLATE_KEYS.items()}


async def get_template(key: str, **placeholders) -> str:
    """Get template from DB, apply placeholders {profile}, {period}. Falls back to default if missing."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(GlobalText).where(GlobalText.key == key))
        g = r.scalar_one_or_none()
        text = g.value if g else DEFAULT_TEMPLATES.get(key, "")
    try:
        return text.format(**placeholders)
    except KeyError:
        return text


async def ensure_default_templates() -> None:
    """Insert default templates into global_texts if keys don't exist."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        for key, default in DEFAULT_TEMPLATES.items():
            r = await session.execute(select(GlobalText).where(GlobalText.key == key))
            if r.scalar_one_or_none() is None:
                session.add(GlobalText(key=key, value=default))
        await session.commit()
