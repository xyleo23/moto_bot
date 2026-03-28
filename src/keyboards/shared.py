"""Platform-agnostic keyboard builders (for MAX and future platforms)."""

import uuid

from src.platforms.base import Button, ButtonType, KeyboardRow
from src.ui_copy import (
    EVENT_REGISTER_PASSENGER,
    EVENT_REGISTER_PILOT,
    EVENT_SEEK_PAIR,
    ROLE_PASSENGER_BTN,
    ROLE_PILOT_BTN,
    SEEK_CONFIRM_PASSENGER,
    SEEK_CONFIRM_PILOT,
    SEEK_DECLINE,
)
from src.utils.callback_short import put_pair_callback


def get_main_menu_rows(*, show_admin: bool = False) -> list[KeyboardRow]:
    """MAX: use message-buttons so taps send text to the bot (always available under last bot message)."""
    rows: list[KeyboardRow] = [
        [Button("🚨 SOS", type=ButtonType.MESSAGE)],
        [Button("🏍 Мотопара", type=ButtonType.MESSAGE)],
        [Button("📇 Полезные контакты", type=ButtonType.MESSAGE)],
        [Button("📅 Мероприятия", type=ButtonType.MESSAGE)],
        [Button("👤 Мой профиль", type=ButtonType.MESSAGE)],
        [Button("ℹ️ О нас", type=ButtonType.MESSAGE)],
        [Button("📄 Документы", payload="menu_documents")],
    ]
    if show_admin:
        rows.append([Button("⚙️ Админ-панель", payload="menu_admin")])
    return rows


def get_city_select_rows() -> list[KeyboardRow]:
    return [[Button("Екатеринбург", payload="city_ekb")]]


def get_welcome_city_rows_for_cities(cities: list) -> list[KeyboardRow]:
    """Города + юридические кнопки (как в Telegram welcome_with_city)."""
    rows: list[KeyboardRow] = [[Button(c.name, payload=f"city_{c.id}")] for c in cities]
    rows.append(
        [
            Button("🔒 Политика", payload="doc_privacy"),
            Button("📄 Соглашение", payload="doc_agreement"),
        ]
    )
    rows.append([Button("✅ Согласие на ПД", payload="doc_consent")])
    return rows


def get_welcome_role_rows() -> list[KeyboardRow]:
    """Роль + юридические кнопки."""
    return [
        [
            Button(ROLE_PILOT_BTN, payload="role_pilot"),
            Button(ROLE_PASSENGER_BTN, payload="role_passenger"),
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
        [Button("🏠 Главное меню", payload="menu_main")],
    ]


def get_max_delete_confirm_rows() -> list[KeyboardRow]:
    return [
        [Button("✅ Да, удалить", payload="confirm_delete_data")],
        [Button("❌ Отмена", payload="menu_documents")],
    ]


def get_back_to_menu_rows() -> list[KeyboardRow]:
    """В MAX нет системной menu-button — явный выход в корень."""
    return [[Button("🏠 Главное меню", payload="menu_main")]]


def get_main_menu_shortcut_row() -> KeyboardRow:
    """Одна строка для добавления к вложенным клавиатурам."""
    return [Button("🏠 Главное меню", payload="menu_main")]


def get_match_max_rows(telegram_username: str | None) -> list[KeyboardRow]:
    """Кнопка «Написать» для MAX после взаимного лайка (только t.me)."""
    rows: list[KeyboardRow] = []
    if telegram_username:
        rows.append(
            [
                Button(
                    "💬 Написать в Telegram",
                    type=ButtonType.URL,
                    url=f"https://t.me/{telegram_username}",
                ),
            ]
        )
    rows.append([Button("« Мотопара", payload="menu_motopair")])
    rows.append(get_main_menu_shortcut_row())
    return rows


def get_like_notification_max_rows(from_user_internal_id: str) -> list[KeyboardRow]:
    return [
        [
            Button("💚 Взаимно!", payload=f"reply_like_{from_user_internal_id}"),
            Button("👎 Пропустить", payload=f"reply_skip_{from_user_internal_id}"),
        ],
        [Button("« Мотопара", payload="menu_motopair")],
        get_main_menu_shortcut_row(),
    ]


def get_role_select_rows() -> list[KeyboardRow]:
    return [
        [
            Button(ROLE_PILOT_BTN, payload="role_pilot"),
            Button(ROLE_PASSENGER_BTN, payload="role_passenger"),
        ],
    ]


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
        get_main_menu_shortcut_row(),
    ]


def get_contacts_page_rows(category: str, offset: int, has_more: bool) -> list[KeyboardRow]:
    rows = []
    if offset > 0:
        prev_off = max(0, offset - 5)
        rows.append([Button("◀ Пред", payload=f"contacts_page_{category}_{prev_off}")])
    if has_more:
        rows.append([Button("След ▶", payload=f"contacts_page_{category}_{offset + 5}")])
    rows.append([Button("« К категориям", payload="menu_contacts")])
    rows.append(get_main_menu_shortcut_row())
    return rows


def get_motopair_profile_rows(
    profile_id: str, role: str, offset: int, has_more: bool
) -> list[KeyboardRow]:
    rows = [
        [
            Button("❤️ Лайк", payload=f"like_{profile_id}_{role}_{offset}"),
            Button("👎 Пропустить", payload=f"dislike_{profile_id}_{role}_{offset}"),
        ],
    ]
    if has_more:
        rows.append([Button("➡️ Следующая", payload=f"motopair_next_{role}_{offset + 1}")])
    rows.append([Button("🚩 Пожаловаться", payload=f"motopair_report_{profile_id}_{role}")])
    rows.append([Button("« Мотопара", payload="menu_motopair")])
    rows.append(get_main_menu_shortcut_row())
    return rows


def get_events_menu_rows() -> list[KeyboardRow]:
    return [
        [Button("Список мероприятий", payload="event_list")],
        [Button("📋 Мои мероприятия", payload="event_my")],
        get_main_menu_shortcut_row(),
    ]


def get_max_my_event_detail_rows(event_id: str) -> list[KeyboardRow]:
    """Карточка «моё мероприятие» в MAX: редактирование, отмена."""
    return [
        [Button("✏️ Редактировать", payload=f"max_evedit_menu_{event_id}")],
        [Button("❌ Отменить мероприятие", payload=f"event_cancel_{event_id}")],
        [Button("« Мои мероприятия", payload="event_my")],
        get_main_menu_shortcut_row(),
    ]


def get_max_event_edit_menu_rows(event_id: str) -> list[KeyboardRow]:
    """Пошаговое редактирование полей мероприятия в MAX."""
    return [
        [Button("✏️ Название", payload=f"max_evedit_f_title_{event_id}")],
        [Button("📅 Дата", payload=f"max_evedit_f_date_{event_id}")],
        [Button("⏰ Время", payload=f"max_evedit_f_time_{event_id}")],
        [Button("📍 Старт", payload=f"max_evedit_f_pstart_{event_id}")],
        [Button("🏁 Финиш", payload=f"max_evedit_f_pend_{event_id}")],
        [Button("📝 Описание", payload=f"max_evedit_f_desc_{event_id}")],
        [Button("« Готово", payload=f"event_my_detail_{event_id}")],
        get_main_menu_shortcut_row(),
    ]


def get_event_list_rows() -> list[KeyboardRow]:
    """Event list keyboard with filter buttons (как в Telegram: все типы)."""
    return [
        [
            Button("Все", payload="event_list_all"),
            Button("Масштабное", payload="event_list_large"),
            Button("Мотопробег", payload="event_list_motorcade"),
            Button("Прохват", payload="event_list_run"),
        ],
        [Button("« Мероприятия", payload="menu_events")],
        get_main_menu_shortcut_row(),
    ]


def _event_id_hex(event_id: str) -> str:
    return uuid.UUID(event_id).hex


def get_max_seeking_confirm_rows(event_id: str) -> list[KeyboardRow]:
    """Подтверждение «ищу пару» в MAX; в payload только hex(id) без дефисов (короче и проще парсить)."""
    h = _event_id_hex(event_id)
    return [
        [
            Button(SEEK_CONFIRM_PASSENGER, payload=f"seeky_{h}_pax"),
            Button(SEEK_CONFIRM_PILOT, payload=f"seeky_{h}_plt"),
        ],
        [Button(SEEK_DECLINE, payload=f"seekn_{h}")],
        [Button("« К мероприятию", payload=f"event_detail_{event_id}")],
    ]


def get_pair_request_max_rows(event_id: str, from_user_id: str) -> list[KeyboardRow]:
    """Кнопки ответа на заявку «пара» в MAX (те же короткие коды, что и в Telegram)."""
    eid = uuid.UUID(event_id)
    from_uid = uuid.UUID(from_user_id)
    code = put_pair_callback(eid, from_uid)
    return [
        [
            Button("Принять", payload=f"epa{code}"),
            Button("Отклонить", payload=f"epj{code}"),
        ],
    ]


def get_event_detail_rows(
    event_id: str,
    is_registered: bool,
    can_report: bool = True,
    *,
    user_role: str | None = None,
) -> list[KeyboardRow]:
    rows = []
    if not is_registered:
        rows.append(
            [
                Button(EVENT_REGISTER_PILOT, payload=f"event_register_{event_id}_pilot"),
                Button(EVENT_REGISTER_PASSENGER, payload=f"event_register_{event_id}_passenger"),
            ]
        )
    elif user_role in ("pilot", "passenger"):
        rows.append([Button(EVENT_SEEK_PAIR, payload=f"max_evt_seek_{event_id}")])
    if can_report:
        rows.append([Button("🚩 Пожаловаться", payload=f"max_event_report_{event_id}")])
    rows.append([Button("« К списку", payload="event_list")])
    rows.append(get_main_menu_shortcut_row())
    return rows
