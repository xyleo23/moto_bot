"""Platform-agnostic keyboard builders (for MAX and future platforms)."""
from src.platforms.base import Button, ButtonType, KeyboardRow


def get_main_menu_rows() -> list[KeyboardRow]:
    """MAX: use message-buttons so taps send text to the bot (always available under last bot message)."""
    return [
        [Button("🚨 SOS", type=ButtonType.MESSAGE)],
        [Button("🏍 Мотопара", type=ButtonType.MESSAGE)],
        [Button("📇 Полезные контакты", type=ButtonType.MESSAGE)],
        [Button("📅 Мероприятия", type=ButtonType.MESSAGE)],
        [Button("👤 Мой профиль", type=ButtonType.MESSAGE)],
        [Button("ℹ️ О нас", type=ButtonType.MESSAGE)],
    ]


def get_city_select_rows() -> list[KeyboardRow]:
    return [[Button("Екатеринбург", payload="city_ekb")]]


def get_role_select_rows() -> list[KeyboardRow]:
    return [
        [
            Button("Я Пилот", payload="role_pilot"),
            Button("Я Двойка", payload="role_passenger"),
        ],
    ]


def get_back_to_menu_rows() -> list[KeyboardRow]:
    return [[Button("« Назад в меню", payload="menu_main")]]


def get_contact_button_row() -> KeyboardRow:
    return [Button("Отправить мой номер", type=ButtonType.REQUEST_CONTACT)]


def get_location_button_row() -> KeyboardRow:
    return [Button("Отправить геолокацию", type=ButtonType.REQUEST_LOCATION)]


def get_contacts_menu_rows() -> list[KeyboardRow]:
    return [
        [Button("МотоМагазин", payload="contacts_motoshop")],
        [Button("МотоСервис", payload="contacts_motoservice")],
        [Button("МотоШкола", payload="contacts_motoschool")],
        [Button("МотоКлубы", payload="contacts_motoclubs")],
        [Button("МотоЭвакуатор", payload="contacts_motoevac")],
        [Button("Другое", payload="contacts_other")],
        [Button("« Назад", payload="menu_main")],
    ]


def get_contacts_page_rows(category: str, offset: int, has_more: bool) -> list[KeyboardRow]:
    rows = []
    if offset > 0:
        prev_off = max(0, offset - 5)
        rows.append([Button("◀ Пред", payload=f"contacts_page_{category}_{prev_off}")])
    if has_more:
        rows.append([Button("След ▶", payload=f"contacts_page_{category}_{offset + 5}")])
    rows.append([Button("« Назад", payload="menu_contacts")])
    return rows


def get_motopair_profile_rows(profile_id: str, role: str, offset: int, has_more: bool) -> list[KeyboardRow]:
    rows = [
        [
            Button("👍 Лайк", payload=f"like_{profile_id}_{role}"),
            Button("👎 Дизлайк", payload=f"dislike_{profile_id}_{role}"),
        ],
    ]
    if has_more:
        rows.append([Button("Следующая ➡", payload=f"motopair_next_{role}_{offset + 1}")])
    rows.append([Button("« В меню", payload="menu_motopair")])
    return rows


def get_events_menu_rows() -> list[KeyboardRow]:
    return [
        [Button("Список мероприятий", payload="event_list")],
        [Button("« Назад", payload="menu_main")],
    ]


def get_event_list_rows() -> list[KeyboardRow]:
    """Event list keyboard with filter buttons."""
    return [
        [
            Button("Все", payload="event_list_all"),
            Button("Мотопробег", payload="event_list_motorcade"),
            Button("Прохват", payload="event_list_run"),
        ],
        [Button("« Назад", payload="menu_events")],
    ]


def get_event_detail_rows(event_id: str, is_registered: bool, can_report: bool = True) -> list[KeyboardRow]:
    rows = []
    if not is_registered:
        rows.append([
            Button("Я Пилот", payload=f"event_register_{event_id}_pilot"),
            Button("Я Двойка", payload=f"event_register_{event_id}_passenger"),
        ])
    if can_report:
        rows.append([Button("🚩 Пожаловаться", payload=f"max_event_report_{event_id}")])
    rows.append([Button("« К списку", payload="event_list")])
    return rows
