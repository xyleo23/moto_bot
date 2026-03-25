"""Main menu keyboards — inline + persistent reply."""
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def get_main_menu_kb(
    platform_user_id: int | None = None,
    show_admin: bool | None = None,
) -> InlineKeyboardMarkup:
    """Inline keyboard for main menu. show_admin=True или суперадмин → кнопка «Админ-панель»."""
    from src.config import get_settings

    rows = [
        [InlineKeyboardButton(text="🚨 SOS", callback_data="menu_sos")],
        [InlineKeyboardButton(text="🏍 Мотопара", callback_data="menu_motopair")],
        [InlineKeyboardButton(text="📇 Полезные контакты", callback_data="menu_contacts")],
        [InlineKeyboardButton(text="📅 Мероприятия", callback_data="menu_events")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu_about")],
        [InlineKeyboardButton(text="📄 Документы", callback_data="menu_documents")],
    ]
    show = show_admin if show_admin is not None else (
        platform_user_id is not None and platform_user_id in get_settings().superadmin_ids
    )
    if show:
        rows.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def get_main_menu_kb_for_user(platform_user_id: int | None, user) -> InlineKeyboardMarkup:
    """Главное меню с учётом суперадмина и админа города."""
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, get_city_admin_city_id

    show_admin = False
    if platform_user_id is not None:
        if platform_user_id in get_settings().superadmin_ids:
            show_admin = True
        elif user and user.city_id and await is_city_admin(platform_user_id, user.city_id):
            show_admin = True
        elif await get_city_admin_city_id(platform_user_id) is not None:
            show_admin = True
    return get_main_menu_kb(platform_user_id=platform_user_id, show_admin=show_admin)


async def get_reply_keyboard_for_user(platform_user_id: int | None, user) -> ReplyKeyboardMarkup:
    """Нижняя reply-клавиатура: обычное меню или админская — как у inline-главного меню."""
    from src.config import get_settings
    from src.services.admin_service import is_city_admin, get_city_admin_city_id

    if platform_user_id is not None:
        if platform_user_id in get_settings().superadmin_ids:
            return get_admin_superadmin_kb()
        if user and user.city_id and await is_city_admin(platform_user_id, user.city_id):
            return get_admin_city_kb()
        if await get_city_admin_city_id(platform_user_id) is not None:
            return get_admin_city_kb()
    return get_persistent_kb()


def get_persistent_kb() -> ReplyKeyboardMarkup:
    """
    Persistent bottom keyboard always visible.
    SOS отдельной строкой — не теснить три кнопки в один ряд на узких экранах.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚨 SOS")],
            [
                KeyboardButton(text="🏍 Мотопара"),
                KeyboardButton(text="📅 Мероприятия"),
            ],
            [
                KeyboardButton(text="📞 Контакты"),
                KeyboardButton(text="👤 Профиль"),
            ],
            [KeyboardButton(text="ℹ️ О нас")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def get_welcome_legal_kb() -> InlineKeyboardMarkup:
    """Три кнопки документов в приветствии (как на Voditel66)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔒 Политика", callback_data="doc_privacy"),
            InlineKeyboardButton(text="📄 Соглашение", callback_data="doc_agreement"),
        ],
        [InlineKeyboardButton(text="✅ Согласие на обработку ПД", callback_data="doc_consent")],
    ])


def get_welcome_with_city_kb(cities: list) -> InlineKeyboardMarkup:
    """Город — основное действие сверху, юридические кнопки ниже."""
    rows = [[InlineKeyboardButton(text=c.name, callback_data=f"city_{c.id}")] for c in cities]
    rows.extend([
        [
            InlineKeyboardButton(text="🔒 Политика", callback_data="doc_privacy"),
            InlineKeyboardButton(text="📄 Соглашение", callback_data="doc_agreement"),
        ],
        [InlineKeyboardButton(text="✅ Согласие на обработку ПД", callback_data="doc_consent")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_welcome_with_role_kb() -> InlineKeyboardMarkup:
    """Роль — основное действие сверху, юридические кнопки ниже."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Я Пилот", callback_data="role_pilot")],
        [InlineKeyboardButton(text="Я Двойка", callback_data="role_passenger")],
        [
            InlineKeyboardButton(text="🔒 Политика", callback_data="doc_privacy"),
            InlineKeyboardButton(text="📄 Соглашение", callback_data="doc_agreement"),
        ],
        [InlineKeyboardButton(text="✅ Согласие на обработку ПД", callback_data="doc_consent")],
    ])


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
