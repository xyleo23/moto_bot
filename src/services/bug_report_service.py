"""Форматирование и отправка баг-репортов суперадминам (TG и MAX по записям User, fallback в Telegram по sid)."""

from __future__ import annotations

import uuid
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.models.user import Platform, User, effective_user_id
from src.services.admin_multichannel_notify import notify_superadmins_multichannel


def bug_report_admin_reply_markup(target_canonical_id: uuid.UUID) -> InlineKeyboardMarkup:
    """Кнопка «Ответить» для суперадмина (тот же callback_data в TG и MAX)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить пользователю",
                    callback_data=f"admin_bugreply_{target_canonical_id}",
                )
            ],
        ]
    )


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
    """Текст всем суперадминам по их платформам; при наличии фото — вторым сообщением скрин."""
    canon = effective_user_id(user)
    reply_kb = bug_report_admin_reply_markup(canon)
    html = format_bug_report_html(user, description)
    await notify_superadmins_multichannel(
        html,
        telegram_markup=reply_kb,
        telegram_bot=telegram_bot,
        max_adapter=max_adapter,
        telegram_parse_mode="HTML",
    )
    if photo_file_id:
        cap = (
            f"🖼 <b>Скриншот</b> к репорту выше\n"
            f"<b>Платформа:</b> {escape(platform_label_ru(user.platform))}\n"
            f"<b>ID:</b> <code>{user.platform_user_id}</code>"
        )
        await notify_superadmins_multichannel(
            cap,
            telegram_markup=reply_kb,
            telegram_bot=telegram_bot,
            max_adapter=max_adapter,
            telegram_parse_mode="HTML",
            photo_file_id=photo_file_id,
        )
