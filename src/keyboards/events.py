"""Events keyboards."""

import uuid
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from src.ui_copy import (
    EVENT_REGISTER_PASSENGER,
    EVENT_REGISTER_PILOT,
    EVENT_SEEK_PAIR,
    SEEK_CONFIRM_PASSENGER,
    SEEK_CONFIRM_PILOT,
    SEEK_DECLINE,
)
from src.utils.callback_short import put_pair_callback


def get_events_menu_kb() -> InlineKeyboardMarkup:
    """Events menu: Create, List, My. Callbacks ≤64 bytes."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать мероприятие", callback_data="event_create")],
            [InlineKeyboardButton(text="Список", callback_data="event_list")],
            [InlineKeyboardButton(text="Мои", callback_data="event_my")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ]
    )


def get_event_list_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Все", callback_data="event_list_all"),
                InlineKeyboardButton(text="Масштабное", callback_data="event_list_large"),
                InlineKeyboardButton(text="Мотопробег", callback_data="event_list_motorcade"),
                InlineKeyboardButton(text="Прохват", callback_data="event_list_run"),
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_events")],
        ]
    )


def get_event_card_kb(
    event_id: str, is_registered: bool, user_role: str, can_report: bool = True
) -> InlineKeyboardMarkup:
    rows = []
    if not is_registered:
        rows.append(
            [
                InlineKeyboardButton(
                    text=EVENT_REGISTER_PILOT, callback_data=f"event_register_{event_id}_pilot"
                ),
                InlineKeyboardButton(
                    text=EVENT_REGISTER_PASSENGER,
                    callback_data=f"event_register_{event_id}_passenger",
                ),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text=EVENT_SEEK_PAIR, callback_data=f"event_seeking_{event_id}")]
        )
    share_row = [
        InlineKeyboardButton(text="📤 Поделиться", callback_data=f"event_share_{event_id}")
    ]
    if can_report:
        share_row.append(
            InlineKeyboardButton(text="🚩 Пожаловаться", callback_data=f"event_report_{event_id}")
        )
    rows.append(share_row)
    rows.append([InlineKeyboardButton(text="« К списку", callback_data="event_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_seeking_confirm_kb(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=SEEK_CONFIRM_PASSENGER,
                    callback_data=f"event_seek_yes_{event_id}_passenger",
                ),
                InlineKeyboardButton(
                    text=SEEK_CONFIRM_PILOT,
                    callback_data=f"event_seek_yes_{event_id}_pilot",
                ),
            ],
            [InlineKeyboardButton(text=SEEK_DECLINE, callback_data=f"event_seek_no_{event_id}")],
            [
                InlineKeyboardButton(
                    text="« К мероприятию", callback_data=f"event_detail_{event_id}"
                )
            ],
        ]
    )


def get_pair_request_kb(event_id: str, from_user_id: str) -> InlineKeyboardMarkup:
    """Short callbacks (≤64 bytes) to avoid BUTTON_DATA_INVALID."""
    eid = uuid.UUID(event_id)
    from_uid = uuid.UUID(from_user_id)
    code = put_pair_callback(eid, from_uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Принять", callback_data=f"epa{code}"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"epj{code}"),
            ],
        ]
    )


def get_my_events_kb(events: list) -> InlineKeyboardMarkup:
    rows = []
    for e in events[:10]:
        title = (e.title or e.type.value)[:25]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{title} ({e.start_at.strftime('%d.%m')})",
                    callback_data=f"event_my_detail_{e.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_events")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_my_event_detail_kb(event_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"event_edit_{event_id}")],
            [
                InlineKeyboardButton(
                    text="❌ Отменить мероприятие", callback_data=f"event_cancel_{event_id}"
                )
            ],
            [InlineKeyboardButton(text="« Мои мероприятия", callback_data="event_my")],
        ]
    )
