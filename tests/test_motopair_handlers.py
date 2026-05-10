"""Unit checks for motopair feed helpers (offset parsing, keyboard when list exhausted)."""

from src.handlers.motopair import _parse_motopair_cb, _profile_kb_with_report
from src import texts


def test_parse_motopair_list_pilot():
    role, off = _parse_motopair_cb("motopair_list_pilot")
    assert role == "pilot" and off == 0


def test_parse_motopair_next_passenger_offset():
    role, off = _parse_motopair_cb("motopair_next_passenger_3")
    assert role == "passenger" and off == 3


def test_parse_motopair_next_pilot_offset():
    role, off = _parse_motopair_cb("motopair_next_pilot_0")
    assert role == "pilot" and off == 0


def test_next_button_hidden_when_no_more_profiles():
    """Соответствует ветке get_next_profile: len(rows) <= 1 → has_more False."""
    kb = _profile_kb_with_report("00000000-0000-4000-8000-000000000001", "pilot", 0, False)
    data_flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert not any(d and d.startswith("motopair_next_") for d in data_flat)


def test_next_button_present_when_more_profiles():
    kb = _profile_kb_with_report("00000000-0000-4000-8000-000000000001", "pilot", 2, True)
    data_flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert any(d == "motopair_next_pilot_3" for d in data_flat)


def test_empty_state_text_constant_exists():
    assert "просмотрел" in texts.MOTOPAIR_NO_PROFILES


def test_end_of_feed_button_replaces_next_row_when_no_more():
    """Баг В: на последней анкете «Пожаловаться» НЕ должна занимать ряд «Следующей».

    Ожидание: при has_more=False ряд под индексом 1 (после Like/Dislike)
    содержит безопасную кнопку завершения ленты, а не «Пожаловаться».
    """
    kb = _profile_kb_with_report("00000000-0000-4000-8000-000000000001", "pilot", 0, False)
    rows = kb.inline_keyboard

    # Ряд 1 — кнопка завершения ленты, ведёт в меню мотопары.
    assert len(rows[1]) == 1
    btn = rows[1][0]
    assert btn.callback_data == "menu_motopair"
    assert btn.text == texts.MOTOPAIR_END_OF_FEED_BTN

    # «Пожаловаться» — отдельным рядом ниже, не на месте «Следующей».
    report_row_idx = next(
        i for i, row in enumerate(rows)
        if any((b.callback_data or "").startswith("motopair_report_") for b in row)
    )
    assert report_row_idx > 1


def test_report_button_row_position_stable_across_has_more():
    """«Пожаловаться» должна стоять на одинаковой геометрической позиции
    в обоих случаях (has_more True/False), чтобы не было случайных нажатий."""
    kb_more = _profile_kb_with_report("00000000-0000-4000-8000-000000000001", "pilot", 0, True)
    kb_last = _profile_kb_with_report("00000000-0000-4000-8000-000000000001", "pilot", 0, False)

    def report_row(kb):
        for i, row in enumerate(kb.inline_keyboard):
            if any((b.callback_data or "").startswith("motopair_report_") for b in row):
                return i
        return -1

    assert report_row(kb_more) == report_row(kb_last)
