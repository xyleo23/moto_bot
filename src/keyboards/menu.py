"""Main menu keyboards — inline + persistent reply."""
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def get_main_menu_kb(platform_user_id: int | None = None) -> InlineKeyboardMarkup:
    """Inline keyboard for main menu. Superadmins see extra «Админ-панель» button."""
    from src.config import get_settings

    rows = [
        [InlineKeyboardButton(text="🚨 SOS", callback_data="menu_sos")],
        [InlineKeyboardButton(text="🏍 Мотопара", callback_data="menu_motopair")],
        [InlineKeyboardButton(text="📇 Полезные контакты", callback_data="menu_contacts")],
        [InlineKeyboardButton(text="📅 Мероприятия", callback_data="menu_events")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu_about")],
    ]
    if platform_user_id is not None and platform_user_id in get_settings().superadmin_ids:
        rows.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def get_city_select_kb(cities: list | None = None) -> InlineKeyboardMarkup:
    """Dynamic city list. Pass list of City from get_cities(). Backward compat: None = Екатеринбург."""
    if cities:
        rows = [[InlineKeyboardButton(text=c.name, callback_data=f"city_{c.id}")] for c in cities]
    else:
        rows = [[InlineKeyboardButton(text="Екатеринбург", callback_data="city_ekb")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_role_select_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Я Пилот", callback_data="role_pilot")],
        [InlineKeyboardButton(text="Я Двойка", callback_data="role_passenger")],
    ])


def get_back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
    ])


def get_admin_superadmin_kb() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура суперадмина (как в референсном проекте)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="👥 Пользователи"),
            ],
            [
                KeyboardButton(text="🏙 Админы городов"),
                KeyboardButton(text="📅 Мероприятия"),
            ],
            [
                KeyboardButton(text="⚙️ Настройки"),
                KeyboardButton(text="📢 Рассылка"),
            ],
            [
                KeyboardButton(text="📇 Контакты"),
                KeyboardButton(text="📝 О нас"),
            ],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def get_admin_city_kb() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура админа города."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Мероприятия"),
                KeyboardButton(text="📇 Контакты"),
            ],
            [KeyboardButton(text="🏠 Главное меню")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
