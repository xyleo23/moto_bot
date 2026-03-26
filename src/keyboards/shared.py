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
        [Button("📄 Документы", payload="menu_documents")],
    ]


def get_city_select_rows() -> list[KeyboardRow]:
    return [[Button("Екатеринбург", payload="city_ekb")]]


def get_welcome_city_rows_for_cities(cities: list) -> list[KeyboardRow]:
    """Города + юридические кнопки (как в Telegram welcome_with_city)."""
    rows: list[KeyboardRow] = [[Button(c.name, payload=f"city_{c.id}")] for c in cities]
    rows.append([
        Button("🔒 Политика", payload="doc_privacy"),
        Button("📄 Соглашение", payload="doc_agreement"),
    ])
    rows.append([Button("✅ Согласие на ПД", payload="doc_consent")])
    return rows


def get_welcome_role_rows() -> list[KeyboardRow]:
    """Роль + юридические кнопки."""
    return [
        [
            Button("Я Пилот", payload="role_pilot"),
            Button("Я Двойка", payload="role_passenger"),
        ],
        [
            Button("🔒 Политика", payload="doc_privacy"),
            Button("📄 Соглашение", payload="doc_agreement"),
        ],
        [Button("✅ Согласие на ПД", payload="doc_consent")],
    ]


def get_max_documents_menu_rows() -> list[KeyboardRow]:
    return [
        [Button("🔒 Политика", payload="doc_privacy")],
        [Button("📄 Пользовательское соглашение", payload="doc_agreement")],
        [Button("✅ Согласие на обработку ПД", payload="doc_consent")],
        [Button("🗑 Удалить мои данные", payload="doc_delete")],
        [Button("📞 Поддержка", payload="doc_support")],
        [Button("« Назад в меню", payload="menu_main")],
    ]


def get_max_delete_confirm_rows() -> list[KeyboardRow]:
    return [
        [Button("✅ Да, удалить", payload="confirm_delete_data")],
        [Button("❌ Отмена", payload="menu_documents")],
    ]


def get_match_max_rows(telegram_username: str | None) -> list[KeyboardRow]:
    """Кнопка «Написать» для MAX после взаимного лайка (только t.me)."""
    rows: list[KeyboardRow] = []
    if telegram_username:
        rows.append([
            Button(
                "💬 Написать в Telegram",
                type=ButtonType.URL,
                url=f"https://t.me/{telegram_username}",
            ),
        ])
    rows.append([Button("« В меню", payload="menu_motopair")])
    return rows


def get_like_notification_max_rows(from_user_internal_id: str) -> list[KeyboardRow]:
    return [
        [
            Button("💚 Взаимно!", payload=f"reply_like_{from_user_internal_id}"),
            Button("👎 Пропустить", payload=f"reply_skip_{from_user_internal_id}"),
        ],
    ]


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
            Button("❤️ Лайк", payload=f"like_{profile_id}_{role}_{offset}"),
            Button("👎 Пропустить", payload=f"dislike_{profile_id}_{role}_{offset}"),
        ],
    ]
    if has_more:
        rows.append([Button("➡️ Следующая", payload=f"motopair_next_{role}_{offset + 1}")])
    rows.append([Button("🚩 Пожаловаться", payload=f"motopair_report_{profile_id}_{role}")])
    rows.append([Button("« В меню", payload="menu_motopair")])
    return rows


def get_events_menu_rows() -> list[KeyboardRow]:
    return [
        [Button("Список мероприятий", payload="event_list")],
        [Button("📋 Мои мероприятия", payload="event_my")],
        [Button("« Назад", payload="menu_main")],
    ]


def get_max_my_event_detail_rows(event_id: str, telegram_edit_url: str | None) -> list[KeyboardRow]:
    """Карточка «моё мероприятие» в MAX: отмена + ссылка на редактирование в Telegram."""
    rows: list[KeyboardRow] = []
    if telegram_edit_url:
        rows.append([
            Button(
                "✏️ Редактировать в Telegram",
                type=ButtonType.URL,
                url=telegram_edit_url,
            ),
        ])
    rows.append([Button("❌ Отменить мероприятие", payload=f"event_cancel_{event_id}")])
    rows.append([Button("« Мои мероприятия", payload="event_my")])
    return rows


def get_event_list_rows() -> list[KeyboardRow]:
    """Event list keyboard with filter buttons (как в Telegram: все типы)."""
    return [
        [
            Button("Все", payload="event_list_all"),
            Button("Масштабное", payload="event_list_large"),
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
