"""Платформонезависимая валидация полей профиля (только stdlib)."""

import re

_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z\s\-]{2,40}$")
_MOTO_RE = re.compile(r"^[А-Яа-яЁёA-Za-z0-9\s\-]{1,60}$")

_ERR_NAME = (
    "Имя может содержать только буквы, пробел и дефис (2–40 символов). Попробуй ещё раз:"
)
_ERR_AGE = "Укажи возраст числом от 18 до 80. Попробуй ещё раз:"
_ERR_ABOUT = (
    "Текст не должен содержать ссылки или спецсимволы < > &, максимум 500 символов. "
    "Попробуй ещё раз:"
)
_ERR_MOTO = (
    "Допустимы только буквы, цифры, пробел и дефис (до 60 символов). Попробуй ещё раз:"
)
_ERR_UNKNOWN = "Неизвестное поле для валидации."


def validate_profile_field(field: str, value: str) -> tuple[bool, str]:
    """
    Проверка одного поля профиля.

    Возвращает (True, "") при успехе, (False, текст_ошибки) при отказе.

    Примеры:
        validate_profile_field("name", "Иван") -> (True, "")
        validate_profile_field("name", "A") -> (False, сообщение об имени)
        validate_profile_field("age", "25") -> (True, "")
        validate_profile_field("age", "17") -> (False, сообщение о возрасте)
        validate_profile_field("about", "Привет") -> (True, "")
        validate_profile_field("about", "см. https://spam.com") -> (False, сообщение об about)
    """
    if value is None:
        value = ""
    if field == "name":
        s = value.strip()
        if _NAME_RE.match(s):
            return True, ""
        return False, _ERR_NAME

    if field == "age":
        s = value.strip()
        if not s.isdigit():
            return False, _ERR_AGE
        n = int(s)
        if 18 <= n <= 80:
            return True, ""
        return False, _ERR_AGE

    if field == "about":
        s = value.strip()
        if len(s) > 500:
            return False, _ERR_ABOUT
        if any(ch in s for ch in "<>&"):
            return False, _ERR_ABOUT
        low = s.lower()
        if "http://" in low or "https://" in low:
            return False, _ERR_ABOUT
        return True, ""

    if field in ("moto_brand", "moto_model"):
        s = value.strip()
        if _MOTO_RE.match(s):
            return True, ""
        return False, _ERR_MOTO

    return False, _ERR_UNKNOWN
