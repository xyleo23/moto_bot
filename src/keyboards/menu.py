"""Main menu keyboards — inline + persistent reply."""
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def get_main_menu_kb() -> InlineKeyboardMarkup:
    """Inline keyboard for main menu messages."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚨 SOS", callback_data="menu_sos")],
        [InlineKeyboardButton(text="🏍 Мотопара", callback_data="menu_motopair")],
        [InlineKeyboardButton(text="📇 Полезные контакты", callback_data="menu_contacts")],
        [InlineKeyboardButton(text="📅 Мероприятия", callback_data="menu_events")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu_about")],
    ])


def get_persistent_kb() -> ReplyKeyboardMarkup:
    """
    Persistent bottom keyboard always visible.
    Quick access to key sections without needing to open menus.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🆘 SOS"),
                KeyboardButton(text="🏍 Мотопара"),
                KeyboardButton(text="📅 Мероприятия"),
            ],
            [
                KeyboardButton(text="📞 Контакты"),
                KeyboardButton(text="👤 Профиль"),
                KeyboardButton(text="ℹ️ О нас"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def get_city_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Екатеринбург", callback_data="city_ekb")],
    ])


def get_role_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Я Пилот", callback_data="role_pilot")],
        [InlineKeyboardButton(text="Я Двойка", callback_data="role_passenger")],
    ])


def get_back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
    ])
