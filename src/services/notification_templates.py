"""Editable notification templates (global_texts). Placeholders: {name}, {profile}, {period}, etc."""
from src.services.admin_service import get_global_text, set_global_text

# Keys in global_texts table. Defaults used when key is missing.
TEMPLATE_KEYS = {
    "template_mutual_like_self": (
        "🎉 <b>Взаимный лайк!</b>\n\n{profile}",
        "Сообщение инициатору лайка. Плейсхолдеры: {profile}",
    ),
    "template_mutual_like_target": (
        "🎉 <b>Взаимный лайк!</b>\n\n{profile}\n\nВы понравились друг другу — напишите первым!",
        "Сообщение получателю. Плейсхолдеры: {profile}",
    ),
    "template_mutual_like_reply": (
        "🎉 <b>Взаимный лайк!</b>\n\n{profile}\n\nОни ответили на твой лайк — напиши первым!",
        "Когда кто-то ответил на твой лайк. Плейсхолдеры: {profile}",
    ),
    "template_like_received": (
        "💌 <b>Кто-то лайкнул твою анкету!</b>\n\n{profile}",
        "Уведомление о лайке. Плейсхолдеры: {profile}",
    ),
    "template_subscription_activated": (
        "✅ Подписка на {period} активирована! Спасибо за поддержку.",
        "После успешной оплаты подписки. Плейсхолдеры: {period}",
    ),
}


async def get_template(key: str, **placeholders) -> str:
    """Get template text, apply placeholders. Falls back to default if missing."""
    default = TEMPLATE_KEYS.get(key, ("", ""))[0]
    text = await get_global_text(key)
    if not text:
        text = default
    try:
        return text.format(**placeholders)
    except KeyError:
        return text


async def ensure_default_templates() -> None:
    """Insert default templates into global_texts if keys don't exist."""
    for key, (default, _) in TEMPLATE_KEYS.items():
        existing = await get_global_text(key)
        if not existing:
            await set_global_text(key, default)
