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
