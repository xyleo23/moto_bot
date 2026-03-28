"""Список мероприятий: пагинация и клавиатуры (Telegram + MAX)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8

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
                    text=f"{e['title']} — {e['date']} (П:{e['pilots']} Д:{e['passengers']})",
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
