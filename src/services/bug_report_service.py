"""Форматирование и отправка баг-репортов суперадминам на той же платформе, что и пользователь."""

from __future__ import annotations

from html import escape

from src.models.user import Platform, User
from src.services.admin_multichannel_notify import notify_superadmins_same_platform


def platform_label_ru(platform: Platform) -> str:
    return "Telegram" if platform == Platform.TELEGRAM else "MAX"


def format_bug_report_html(user: User, description: str) -> str:
    name = escape(user.platform_first_name or "—")
    un = f"@{escape(user.platform_username)}" if user.platform_username else "—"
    uid = user.platform_user_id
    body = escape((description or "").strip()[:8000])
    pl = platform_label_ru(user.platform)
    return (
        f"🐞 <b>Сообщение об ошибке</b> ({escape(pl)})\n\n"
        f"<b>От:</b> {name} {un}\n"
        f"<b>ID:</b> <code>{uid}</code>\n\n"
        f"{body}"
    )


async def send_bug_report_to_superadmins(
    user: User,
    description: str,
    *,
    photo_file_id: str | None = None,
    telegram_bot=None,
    max_adapter=None,
) -> None:
    """Текст админам; при наличии фото — вторым сообщением скрин (та же платформа)."""
    html = format_bug_report_html(user, description)
    await notify_superadmins_same_platform(
        html,
        user.platform,
        photo_file_id=None,
        telegram_bot=telegram_bot,
        max_adapter=max_adapter,
    )
    if photo_file_id:
        cap = (
            f"🖼 <b>Скриншот</b> к репорту выше\n"
            f"<b>Платформа:</b> {escape(platform_label_ru(user.platform))}\n"
            f"<b>ID:</b> <code>{user.platform_user_id}</code>"
        )
        await notify_superadmins_same_platform(
            cap,
            user.platform,
            photo_file_id=photo_file_id,
            telegram_bot=telegram_bot,
            max_adapter=max_adapter,
        )
