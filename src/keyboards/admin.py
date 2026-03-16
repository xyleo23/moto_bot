"""Admin panel keyboards."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [
            InlineKeyboardButton(text="🏙 Города", callback_data="admin_cities"),
            InlineKeyboardButton(text="👤 Админы городов", callback_data="admin_city_admins"),
        ],
        [InlineKeyboardButton(text="📅 Мероприятия", callback_data="admin_events")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton(text="📝 Текст «О нас»", callback_data="admin_text_about")],
        [InlineKeyboardButton(text="📧 Шаблоны уведомлений", callback_data="admin_templates")],
        [InlineKeyboardButton(text="📋 Логи активности", callback_data="admin_logs")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📇 Полезные контакты", callback_data="admin_contacts")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])


def get_admin_back_kb(target: str = "admin_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data=target)],
    ])


def get_user_action_kb(user_id: str, is_blocked: bool) -> InlineKeyboardMarkup:
    btn = InlineKeyboardButton(
        text="🔓 Разблокировать" if is_blocked else "🔒 Заблокировать",
        callback_data=f"admin_user_{'unblock' if is_blocked else 'block'}_{user_id}",
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn],
        [InlineKeyboardButton(text="📅 Подписка", callback_data=f"admin_sub_extend_{user_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_users")],
    ])


def get_cities_kb(prefix: str) -> InlineKeyboardMarkup:
    # Will be filled dynamically
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
    ])


def get_city_admins_kb(city_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data=f"admin_ca_add_{city_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")],
    ])


def get_admin_event_kb(
    event_id: str,
    can_edit: bool,
    is_recommended: bool = False,
    is_official: bool = False,
) -> InlineKeyboardMarkup:
    rows = []
    if can_edit:
        rows.append([InlineKeyboardButton(
            text=f"{'★ Убрать рекомендацию' if is_recommended else '⭐ Рекомендовать'}",
            callback_data=f"admin_ev_rec_{event_id}",
        )])
        rows.append([InlineKeyboardButton(
            text=f"{'🏛 Убрать «Официальное»' if is_official else '🏛 Отметить официальным'}",
            callback_data=f"admin_ev_official_{event_id}",
        )])
        rows.append([InlineKeyboardButton(text="❌ Отменить мероприятие", callback_data=f"admin_ev_cancel_{event_id}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_events")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_settings_kb(s: object) -> InlineKeyboardMarkup:
    """Subscription settings toggles."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"Подписка: {'✅ вкл' if s.subscription_enabled else '❌ выкл'}",
                callback_data="admin_set_sub_toggle",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Платное создание мероприятий: {'✅' if s.event_creation_enabled else '❌'}",
                callback_data="admin_set_ev_toggle",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"Платное поднятие анкеты: {'✅' if s.raise_profile_enabled else '❌'}",
                callback_data="admin_set_raise_toggle",
            )
        ],
        [InlineKeyboardButton(text="💵 Цена месяца (коп)", callback_data="admin_set_monthly")],
        [InlineKeyboardButton(text="💵 Цена сезона (коп)", callback_data="admin_set_season")],
        [InlineKeyboardButton(
            text="🏍 Мотопробегов/мес (с подпиской)",
            callback_data="admin_set_motorcade_limit",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
    ])


def get_broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="admin_bc_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast")],
    ])
