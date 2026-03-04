"""Events keyboards."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_events_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать мероприятие", callback_data="event_create")],
        [InlineKeyboardButton(text="Просмотреть мероприятия", callback_data="event_list")],
        [InlineKeyboardButton(text="Мои мероприятия", callback_data="event_my")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])


def get_event_list_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Все", callback_data="event_list_all"),
            InlineKeyboardButton(text="Масштабное", callback_data="event_list_large"),
            InlineKeyboardButton(text="Мотопробег", callback_data="event_list_motorcade"),
            InlineKeyboardButton(text="Прохват", callback_data="event_list_run"),
        ],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_events")],
    ])


def get_event_card_kb(event_id: str, is_registered: bool, user_role: str) -> InlineKeyboardMarkup:
    rows = []
    if not is_registered:
        rows.append([
            InlineKeyboardButton(text="Я Пилот", callback_data=f"event_register_{event_id}_pilot"),
            InlineKeyboardButton(text="Я Двойка", callback_data=f"event_register_{event_id}_passenger"),
        ])
    else:
        rows.append([InlineKeyboardButton(text="Ищу пару", callback_data=f"event_seeking_{event_id}")])
    # Share button — generates ready-to-forward plain text
    rows.append([InlineKeyboardButton(text="📤 Поделиться", callback_data=f"event_share_{event_id}")])
    rows.append([InlineKeyboardButton(text="« К списку", callback_data="event_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_seeking_confirm_kb(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да, ищу двойку", callback_data=f"event_seek_yes_{event_id}_passenger"),
            InlineKeyboardButton(text="Да, ищу пилота", callback_data=f"event_seek_yes_{event_id}_pilot"),
        ],
        [InlineKeyboardButton(text="Не ищу", callback_data=f"event_seek_no_{event_id}")],
        [InlineKeyboardButton(text="« К мероприятию", callback_data=f"event_detail_{event_id}")],
    ])


def get_seeking_list_kb(event_id: str, seekers: list, viewer_role: str) -> InlineKeyboardMarkup:
    """Viewer is pilot -> show passengers. Viewer is passenger -> show pilots."""
    rows = []
    for s in seekers[:8]:  # limit 8
        reg, user = s
        name = getattr(user, "platform_first_name", None) or "Участник"
        rows.append([InlineKeyboardButton(
            text=name,
            callback_data=f"event_pair_req_{event_id}_{user.id}",
        )])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"event_detail_{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_pair_request_kb(event_id: str, from_user_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Принять", callback_data=f"event_pair_accept_{event_id}_{from_user_id}"),
            InlineKeyboardButton(text="Отклонить", callback_data=f"event_pair_reject_{event_id}_{from_user_id}"),
        ],
    ])


def get_my_events_kb(events: list) -> InlineKeyboardMarkup:
    rows = []
    for e in events[:10]:
        title = (e.title or e.type.value)[:25]
        rows.append([InlineKeyboardButton(
            text=f"{title} ({e.start_at.strftime('%d.%m')})",
            callback_data=f"event_my_detail_{e.id}",
        )])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_events")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_my_event_detail_kb(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отменить мероприятие", callback_data=f"event_cancel_{event_id}")],
        [InlineKeyboardButton(text="« Мои мероприятия", callback_data="event_my")],
    ])
