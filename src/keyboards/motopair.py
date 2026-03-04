"""MotoPair keyboards."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_profile_view_kb(profile_id, role: str, offset: int, has_more: bool):
    rows = [
        [
            InlineKeyboardButton(text="👍 Лайк", callback_data=f"like_{profile_id}_{role}"),
            InlineKeyboardButton(text="👎 Дизлайк", callback_data=f"dislike_{profile_id}_{role}"),
        ],
    ]
    if has_more:
        rows.append([InlineKeyboardButton(text="Следующая анкета", callback_data=f"motopair_next_{role}_{offset+1}")])
    rows.append([InlineKeyboardButton(text="« В меню", callback_data="menu_motopair")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
