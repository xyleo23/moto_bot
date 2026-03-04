"""MotoPair keyboards."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_profile_view_kb(profile_id: str, role: str, offset: int, has_more: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👍 Лайк", callback_data=f"like_{profile_id}_{role}"),
            InlineKeyboardButton(text="👎 Дизлайк", callback_data=f"dislike_{profile_id}_{role}"),
        ],
    ]
    if has_more:
        rows.append([InlineKeyboardButton(text="Следующая ➡", callback_data=f"motopair_next_{role}_{offset + 1}")])
    rows.append([InlineKeyboardButton(text="« В меню", callback_data="menu_motopair")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_like_notification_kb(from_user_internal_id: str) -> InlineKeyboardMarkup:
    """Keyboard for the person who received a like — reply like or skip."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💚 Взаимно!", callback_data=f"reply_like_{from_user_internal_id}"),
            InlineKeyboardButton(text="👎 Пропустить", callback_data=f"reply_skip_{from_user_internal_id}"),
        ],
    ])


def get_match_kb(telegram_username: str | None, telegram_id: int | None) -> InlineKeyboardMarkup:
    """Keyboard shown after mutual like — link to chat if username available."""
    rows = []
    if telegram_username:
        rows.append([InlineKeyboardButton(text="💬 Написать", url=f"https://t.me/{telegram_username}")])
    elif telegram_id:
        rows.append([InlineKeyboardButton(text="💬 Написать", url=f"tg://user?id={telegram_id}")])
    rows.append([InlineKeyboardButton(text="« В меню", callback_data="menu_motopair")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
