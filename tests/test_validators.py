"""Тесты validate_profile_field."""

from src.utils.validators import validate_profile_field


def test_name_valid():
    ok, err = validate_profile_field("name", "Иван Петров")
    assert ok is True
    assert err == ""


def test_name_rejects_html():
    ok, err = validate_profile_field("name", "<script>")
    assert ok is False
    assert err


def test_name_too_short():
    ok, err = validate_profile_field("name", "А")
    assert ok is False
    assert err


def test_name_too_long():
    value = "а" * 41
    ok, err = validate_profile_field("name", value)
    assert ok is False
    assert err


def test_age_valid():
    ok, err = validate_profile_field("age", "25")
    assert ok is True
    assert err == ""


def test_age_too_young():
    ok, err = validate_profile_field("age", "17")
    assert ok is False
    assert err


def test_age_too_old():
    ok, err = validate_profile_field("age", "81")
    assert ok is False
    assert err


def test_age_not_number():
    ok, err = validate_profile_field("age", "abc")
    assert ok is False
    assert err


def test_about_valid():
    text = "Обычный текст без ссылок и спецсимволов, " * 5
    assert len(text) <= 500
    ok, err = validate_profile_field("about", text)
    assert ok is True
    assert err == ""


def test_about_rejects_url():
    ok, err = validate_profile_field("about", "смотри https://t.me/spam")
    assert ok is False
    assert err


def test_about_rejects_html_chars():
    ok, err = validate_profile_field("about", "текст с < тегом")
    assert ok is False
    assert err


def test_about_too_long():
    value = "x" * 501
    ok, err = validate_profile_field("about", value)
    assert ok is False
    assert err


def test_moto_valid():
    ok, err = validate_profile_field("moto_brand", "Kawasaki Z900")
    assert ok is True
    assert err == ""


def test_moto_rejects_special():
    ok, err = validate_profile_field("moto_model", "Kawasaki<Z900>")
    assert ok is False
    assert err
