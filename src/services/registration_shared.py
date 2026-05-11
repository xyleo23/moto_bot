"""Общая логика регистрации между Telegram и MAX (пакет 15 000 ₽, пункт О).

До этого `_parse_russian_date` и `_parse_date` буквально дублировались
в `handlers/registration.py` и `max_runner.py`. Расхождение в одном
файле приводило к разному поведению на платформах. Теперь обе используют
этот модуль.
"""

from __future__ import annotations

import re
from datetime import date, datetime


RUSSIAN_MONTHS: dict[str, int] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def parse_russian_date(text: str) -> date | None:
    """Дата в формате «DD месяц YYYY» (напр. «26 июня 2006»)."""
    text = (text or "").strip()
    m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{4})", text, re.IGNORECASE)
    if not m:
        return None
    day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
    month_num = RUSSIAN_MONTHS.get(month_name)
    if not month_num:
        return None
    try:
        return datetime(year, month_num, day).date()
    except ValueError:
        return None


def parse_registration_date(text: str) -> date | None:
    """Дата начала вождения: год, месяц.год, полная дата или «DD месяц YYYY».

    Используется и Telegram, и MAX-ботом при регистрации.
    """
    text = (text or "").strip()
    # Только год: ГГГГ (1970–2030)
    m_year = re.match(r"^(\d{4})$", text)
    if m_year:
        y = int(m_year.group(1))
        if 1970 <= y <= 2030:
            return datetime(y, 1, 1).date()
    # Месяц.год: ММ.ГГГГ или М/ГГГГ
    m_my = re.match(r"^(\d{1,2})[./](\d{4})$", text)
    if m_my:
        month, year = int(m_my.group(1)), int(m_my.group(2))
        if 1 <= month <= 12 and 1970 <= year <= 2030:
            try:
                return datetime(year, month, 1).date()
            except ValueError:
                pass
    # Полная дата
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d/%m/%y", "%d%m%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(f"{text[:2]}.{text[2:4]}.{text[4:]}", "%d.%m.%Y").date()
        except ValueError:
            pass
    parsed = parse_russian_date(text)
    if parsed:
        return parsed
    return None
