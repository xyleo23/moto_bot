"""Список мероприятий: пагинация и клавиатуры (Telegram + MAX)."""

from __future__ import annotations

import re

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.utils.text_format import truncate_smart

PAGE_SIZE = 8

# Telegram inline-кнопка ~64 символа; счётчики в начале, чтобы не терялись при обрезке в клиенте.
TG_EVENT_LIST_BUTTON_MAX_LEN = 64


def _compact_event_list_date(date_str: str) -> str:
    """«04.04.2026 15:00» → «04.04 15:00» для экономии места на кнопке."""
    s = (date_str or "").strip()
    m = re.match(r"^(\d{2}\.\d{2})\.\d{4}\s+(\d{2}:\d{2})$", s)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return s


def format_telegram_event_list_button_text(
    title: str,
    date_str: str,
    pilots: int,
    passengers: int,
    *,
    max_len: int = TG_EVENT_LIST_BUTTON_MAX_LEN,
) -> str:
    """
    Подпись кнопки списка мероприятий: сначала (П: Д:), затем усечённое название, компактная дата.
    Так длинные названия не скрывают число записавшихся.
    """
    counts = f"(П:{pilots} Д:{passengers})"
    date_c = _compact_event_list_date(date_str)
    sep = " · "
    tail = f"{sep}{date_c}"
    head = counts + " "
    middle_budget = max_len - len(head) - len(tail)
    if middle_budget < 6:
        middle_budget = 6
    t = truncate_smart((title or "").strip(), middle_budget)
    return head + t + tail

_VALID_TYPES = frozenset({"all", "large", "motorcade", "run"})


def event_list_scope_label(ev_type: str | None) -> str:
    """Подпись фильтра для заголовка списка (TG + MAX)."""
    from src.services.event_service import TYPE_LABELS

    if ev_type is None:
        return "Все мероприятия"
    return TYPE_LABELS.get(ev_type, ev_type)


def format_event_list_header_plain(ev_type: str | None, offset: int) -> str:
    """Одна строка заголовка с номером страницы."""
    page = offset // PAGE_SIZE + 1
    return f"{event_list_scope_label(ev_type)} (стр. {page}):"


def parse_event_list_callback(data: str) -> tuple[str | None, int] | None:
    """
    event_list_<type> → offset 0; evtlp_<type>_<offset> → страница.
    type=all соответствует None в get_events_list.
    """
    if data.startswith("evtlp_"):
        rest = data[6:]
        if "_" not in rest:
            return None
        t, off_s = rest.rsplit("_", 1)
        if t not in _VALID_TYPES or not off_s.isdigit():
            return None
        ev_type = None if t == "all" else t
        return ev_type, int(off_s)
    if data.startswith("event_list_"):
        t = data.replace("event_list_", "").strip()
        if t not in _VALID_TYPES:
            return None
        ev_type = None if t == "all" else t
        return ev_type, 0
    return None


def _type_token(ev_type: str | None) -> str:
    return "all" if ev_type is None else ev_type


def build_telegram_event_list_markup(
    events: list[dict],
    ev_type: str | None,
    offset: int,
) -> InlineKeyboardMarkup:
    slice_e = events[offset : offset + PAGE_SIZE]
    rows = []
    for e in slice_e:
        rows.append(
            [
                InlineKeyboardButton(
                    text=format_telegram_event_list_button_text(
                        str(e.get("title") or ""),
                        str(e.get("date") or ""),
                        int(e.get("pilots") or 0),
                        int(e.get("passengers") or 0),
                    ),
                    callback_data=f"event_detail_{e['id']}",
                ),
            ]
        )
    tok = _type_token(ev_type)
    nav = []
    if offset > 0:
        prev = max(0, offset - PAGE_SIZE)
        nav.append(InlineKeyboardButton(text="◀️ Ранее", callback_data=f"evtlp_{tok}_{prev}"))
    if offset + PAGE_SIZE < len(events):
        nxt = offset + PAGE_SIZE
        nav.append(InlineKeyboardButton(text="Далее ▶️", callback_data=f"evtlp_{tok}_{nxt}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="« К фильтру", callback_data="event_list")])
    rows.append([InlineKeyboardButton(text="« Мероприятия", callback_data="menu_events")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_max_event_detail_rows(
    events: list[dict],
    ev_type: str | None,
    offset: int,
    *,
    event_button_label_fn,
) -> list:
    """Строки клавиатуры между фильтром и «Назад»: карточки + пагинация."""
    from src.platforms.base import Button

    slice_e = events[offset : offset + PAGE_SIZE]
    tok = _type_token(ev_type)
    rows: list = [
        [
            Button(
                event_button_label_fn(str(e.get("title") or "")),
                payload=f"event_detail_{e['id']}",
            )
        ]
        for e in slice_e
    ]
    nav_btns = []
    if offset > 0:
        prev = max(0, offset - PAGE_SIZE)
        nav_btns.append(Button("◀️ Ранее", payload=f"evtlp_{tok}_{prev}"))
    if offset + PAGE_SIZE < len(events):
        nxt = offset + PAGE_SIZE
        nav_btns.append(Button("Далее ▶️", payload=f"evtlp_{tok}_{nxt}"))
    if nav_btns:
        rows.append(nav_btns)
    return rows
