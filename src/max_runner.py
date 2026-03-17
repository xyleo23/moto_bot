"""MAX bot runner — dispatches updates to handlers (with full registration FSM)."""
import re
import uuid
import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from src.config import get_settings
from src.platforms.max_adapter import MaxAdapter
from src.platforms.max_parser import parse_updates
from src.platforms.base import (
    Button,
    ButtonType,
    IncomingMessage,
    IncomingCallback,
    IncomingContact,
    IncomingLocation,
    IncomingPhoto,
    KeyboardRow,
)
from src.services.user import get_or_create_user, has_profile
from src.services import max_registration_state as reg_state
from src.services.registration_service import (
    finish_pilot_registration,
    finish_passenger_registration,
)
from src.models.user import User, UserRole, Platform
from src.models.base import get_session_factory
from sqlalchemy import select
from src.keyboards.shared import (
    get_main_menu_rows,
    get_city_select_rows,
    get_role_select_rows,
    get_back_to_menu_rows,
    get_contact_button_row,
    get_location_button_row,
    get_contacts_menu_rows,
    get_contacts_page_rows,
    get_motopair_profile_rows,
    get_events_menu_rows,
    get_event_list_rows,
    get_event_detail_rows,
)
from src.utils.progress import progress_prefix
from src import texts

# ── Step counts ───────────────────────────────────────────────────────────────
PILOT_TOTAL_STEPS = 11
PASSENGER_TOTAL_STEPS = 9

# ── Registration date parser (same logic as registration.py) ──────────────────
RUSSIAN_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def _parse_russian_date(text: str):
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


def _parse_date(text: str):
    text = (text or "").strip()
    m_year = re.match(r"^(\d{4})$", text)
    if m_year:
        y = int(m_year.group(1))
        if 1970 <= y <= 2030:
            return datetime(y, 1, 1).date()
    m_my = re.match(r"^(\d{1,2})[./](\d{4})$", text)
    if m_my:
        month, year = int(m_my.group(1)), int(m_my.group(2))
        if 1 <= month <= 12 and 1970 <= year <= 2030:
            try:
                return datetime(year, month, 1).date()
            except ValueError:
                pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(f"{text[:2]}.{text[2:4]}.{text[4:]}", "%d.%m.%Y").date()
        except ValueError:
            pass
    return _parse_russian_date(text)


# ── Keyboard builders for registration ───────────────────────────────────────

def _pilot_gender_kb() -> list[KeyboardRow]:
    return [[
        Button("Муж", payload="max_reg_gender_male"),
        Button("Жен", payload="max_reg_gender_female"),
        Button("Другое", payload="max_reg_gender_other"),
    ]]


def _pilot_style_kb() -> list[KeyboardRow]:
    return [
        [Button("Спокойный", payload="max_reg_style_calm")],
        [Button("Агрессивный", payload="max_reg_style_aggressive")],
        [Button("Смешанный", payload="max_reg_style_mixed")],
    ]


def _pilot_photo_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_skip_photo")]]


def _pilot_about_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_skip_about")]]


def _pilot_preview_kb() -> list[KeyboardRow]:
    return [
        [Button(texts.PROFILE_BTN_SAVE, payload="max_reg_preview_save")],
        [Button(texts.PROFILE_BTN_EDIT, payload="max_reg_preview_edit")],
    ]


def _pax_gender_kb() -> list[KeyboardRow]:
    return [[
        Button("Муж", payload="max_reg_pax_gender_male"),
        Button("Жен", payload="max_reg_pax_gender_female"),
        Button("Другое", payload="max_reg_pax_gender_other"),
    ]]


def _pax_style_kb() -> list[KeyboardRow]:
    return [
        [Button("Спокойный", payload="max_reg_pax_style_calm")],
        [Button("Динамичный", payload="max_reg_pax_style_dynamic")],
        [Button("Смешанный", payload="max_reg_pax_style_mixed")],
    ]


def _pax_photo_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_pax_skip_photo")]]


def _pax_about_kb() -> list[KeyboardRow]:
    return [[Button(texts.BTN_SKIP, payload="max_reg_pax_skip_about")]]


def _pax_preview_kb() -> list[KeyboardRow]:
    return [
        [Button(texts.PROFILE_BTN_SAVE, payload="max_reg_pax_preview_save")],
        [Button(texts.PROFILE_BTN_EDIT, payload="max_reg_pax_preview_edit")],
    ]


def _cancel_kb() -> list[KeyboardRow]:
    return [[Button("❌ Отменить", payload="max_reg_cancel")]]


# ── Preview text builders ─────────────────────────────────────────────────────

def _build_pilot_preview(data: dict) -> str:
    style_labels = {"calm": "Спокойный", "aggressive": "Агрессивный", "mixed": "Смешанный"}
    gender_labels = {"male": "Муж", "female": "Жен", "other": "Другое"}
    return (
        texts.PROFILE_PREVIEW_HEADER
        + f"🏍 <b>{data.get('name')}</b>\n"
        + f"Возраст: {data.get('age')} лет\n"
        + f"Пол: {gender_labels.get(str(data.get('gender', '')), '—')}\n"
        + f"Мотоцикл: {data.get('bike_brand')} {data.get('bike_model')}, {data.get('engine_cc')} см³\n"
        + f"Стаж с: {data.get('driving_since') or '—'}\n"
        + f"Стиль: {style_labels.get(str(data.get('driving_style', '')), '—')}\n"
        + f"О себе: {data.get('about') or '—'}\n\n"
        + texts.PROFILE_PREVIEW_CONFIRM
    )


def _build_passenger_preview(data: dict) -> str:
    style_labels = {"calm": "Спокойный", "dynamic": "Динамичный", "mixed": "Смешанный"}
    gender_labels = {"male": "Муж", "female": "Жен", "other": "Другое"}
    return (
        texts.PROFILE_PREVIEW_HEADER
        + f"👤 <b>{data.get('name')}</b>\n"
        + f"Возраст: {data.get('age')} лет\n"
        + f"Пол: {gender_labels.get(str(data.get('gender', '')), '—')}\n"
        + f"Вес: {data.get('weight')} кг, Рост: {data.get('height')} см\n"
        + f"Стиль: {style_labels.get(str(data.get('preferred_style', '')), '—')}\n"
        + f"О себе: {data.get('about') or '—'}\n\n"
        + texts.PROFILE_PREVIEW_CONFIRM
    )


# ── Profile formatter ─────────────────────────────────────────────────────────

def _format_profile_max(profile) -> str:
    if hasattr(profile, "bike_brand"):
        return (
            f"🏍 <b>{profile.name}</b>\n"
            f"Возраст: {profile.age}\n"
            f"Мотоцикл: {profile.bike_brand} {profile.bike_model}, {profile.engine_cc} см³\n"
            f"О себе: {profile.about or '—'}"
        )
    return (
        f"👤 <b>{profile.name}</b>\n"
        f"Возраст: {profile.age}, Рост: {profile.height} см, Вес: {profile.weight} кг\n"
        f"О себе: {profile.about or '—'}"
    )


# ── Registration FSM — step handlers ─────────────────────────────────────────

async def _start_pilot_registration(
    adapter: MaxAdapter, chat_id: str, user_id: int
) -> None:
    """Begin pilot registration — ask for name (step 1)."""
    await reg_state.set_state(user_id, "pilot:name", {})
    logger.info("MAX reg: user_id=%s state=pilot:name", user_id)
    await adapter.send_message(
        chat_id,
        progress_prefix(1, PILOT_TOTAL_STEPS) + texts.REG_ASK_NAME,
        _cancel_kb(),
    )


async def _start_passenger_registration(
    adapter: MaxAdapter, chat_id: str, user_id: int
) -> None:
    """Begin passenger registration — ask for name (step 1)."""
    await reg_state.set_state(user_id, "passenger:name", {})
    logger.info("MAX reg: user_id=%s state=passenger:name", user_id)
    await adapter.send_message(
        chat_id,
        progress_prefix(1, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_NAME,
        _cancel_kb(),
    )


async def _handle_fsm_message(
    adapter: MaxAdapter, chat_id: str, user_id: int, text: str, fsm: dict
) -> None:
    """Route incoming text to the correct FSM step handler."""
    state = fsm["state"]
    data = fsm["data"]

    # ── PILOT steps ──────────────────────────────────────────────────────────
    if state == "pilot:name":
        if not text:
            await adapter.send_message(chat_id, "Введи имя текстом.", _cancel_kb())
            return
        data["name"] = text.strip()
        await reg_state.set_state(user_id, "pilot:phone", data)
        logger.info("MAX reg: user_id=%s state=pilot:phone", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(2, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHONE,
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "pilot:phone":
        # Text in phone step — remind about contact button
        await adapter.send_message(
            chat_id,
            "Нажми кнопку «Отправить мой номер» для передачи контакта.",
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "pilot:age":
        try:
            age = int(text.strip())
            if 18 <= age <= 80:
                data["age"] = age
                await reg_state.set_state(user_id, "pilot:gender", data)
                logger.info("MAX reg: user_id=%s state=pilot:gender", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(4, PILOT_TOTAL_STEPS) + texts.REG_ASK_GENDER,
                    _pilot_gender_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_AGE, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "pilot:bike_brand":
        if not text:
            await adapter.send_message(chat_id, "Введи марку мотоцикла текстом.", _cancel_kb())
            return
        data["bike_brand"] = text.strip()
        await reg_state.set_state(user_id, "pilot:bike_model", data)
        logger.info("MAX reg: user_id=%s state=pilot:bike_model", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(6, PILOT_TOTAL_STEPS) + texts.REG_ASK_BIKE_MODEL,
            _cancel_kb(),
        )
        return

    if state == "pilot:bike_model":
        if not text:
            await adapter.send_message(chat_id, "Введи модель мотоцикла текстом.", _cancel_kb())
            return
        data["bike_model"] = text.strip()
        await reg_state.set_state(user_id, "pilot:engine_cc", data)
        logger.info("MAX reg: user_id=%s state=pilot:engine_cc", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(7, PILOT_TOTAL_STEPS) + texts.REG_ASK_ENGINE_CC,
            _cancel_kb(),
        )
        return

    if state == "pilot:engine_cc":
        try:
            cc = int(text.strip())
            if 50 <= cc <= 3000:
                data["engine_cc"] = cc
                await reg_state.set_state(user_id, "pilot:driving_since", data)
                logger.info("MAX reg: user_id=%s state=pilot:driving_since", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(8, PILOT_TOTAL_STEPS) + texts.REG_ASK_DRIVING_SINCE,
                    _cancel_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_ENGINE_CC, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "pilot:driving_since":
        dt = _parse_date(text)
        if dt:
            data["driving_since"] = dt.isoformat()
            await reg_state.set_state(user_id, "pilot:driving_style", data)
            logger.info("MAX reg: user_id=%s state=pilot:driving_style", user_id)
            await adapter.send_message(
                chat_id,
                progress_prefix(9, PILOT_TOTAL_STEPS) + texts.REG_ASK_STYLE,
                _pilot_style_kb(),
            )
        else:
            await adapter.send_message(chat_id, texts.REG_ERROR_DATE_FORMAT, _cancel_kb())
        return

    if state == "pilot:photo":
        # Text in photo step — remind to send photo or skip
        await adapter.send_message(
            chat_id,
            "Отправь фото или нажми «Пропустить».",
            _pilot_photo_kb(),
        )
        return

    if state == "pilot:about":
        about = text.strip() if text else None
        if about and about.lower() in ("пропустить", "skip"):
            about = None
        if about:
            max_len = get_settings().about_text_max_length
            if len(about) > max_len:
                await adapter.send_message(
                    chat_id,
                    texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len),
                    _pilot_about_kb(),
                )
                return
        data["about"] = about
        await reg_state.set_state(user_id, "pilot:preview", data)
        logger.info("MAX reg: user_id=%s state=pilot:preview", user_id)
        await adapter.send_message(
            chat_id,
            _build_pilot_preview(data),
            _pilot_preview_kb(),
        )
        return

    if state == "pilot:preview":
        await adapter.send_message(
            chat_id,
            "Нажми «Сохранить» или «Редактировать».",
            _pilot_preview_kb(),
        )
        return

    # ── PASSENGER steps ──────────────────────────────────────────────────────
    if state == "passenger:name":
        if not text:
            await adapter.send_message(chat_id, "Введи имя текстом.", _cancel_kb())
            return
        data["name"] = text.strip()
        await reg_state.set_state(user_id, "passenger:phone", data)
        logger.info("MAX reg: user_id=%s state=passenger:phone", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(2, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHONE,
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "passenger:phone":
        await adapter.send_message(
            chat_id,
            "Нажми кнопку «Отправить мой номер».",
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "passenger:age":
        try:
            age = int(text.strip())
            if 18 <= age <= 80:
                data["age"] = age
                await reg_state.set_state(user_id, "passenger:gender", data)
                logger.info("MAX reg: user_id=%s state=passenger:gender", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(4, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_GENDER,
                    _pax_gender_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_AGE, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "passenger:weight":
        try:
            w = int(text.strip())
            if 30 <= w <= 200:
                data["weight"] = w
                await reg_state.set_state(user_id, "passenger:height", data)
                logger.info("MAX reg: user_id=%s state=passenger:height", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(6, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_HEIGHT,
                    _cancel_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_WEIGHT, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "passenger:height":
        try:
            h = int(text.strip())
            if 120 <= h <= 220:
                data["height"] = h
                await reg_state.set_state(user_id, "passenger:preferred_style", data)
                logger.info("MAX reg: user_id=%s state=passenger:preferred_style", user_id)
                await adapter.send_message(
                    chat_id,
                    progress_prefix(7, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PREFERRED_STYLE,
                    _pax_style_kb(),
                )
            else:
                await adapter.send_message(chat_id, texts.REG_ERROR_HEIGHT, _cancel_kb())
        except ValueError:
            await adapter.send_message(chat_id, texts.REG_ERROR_NOT_NUMBER, _cancel_kb())
        return

    if state == "passenger:photo":
        await adapter.send_message(
            chat_id,
            "Отправь фото или нажми «Пропустить».",
            _pax_photo_kb(),
        )
        return

    if state == "passenger:about":
        about = text.strip() if text else None
        if about and about.lower() in ("пропустить", "skip"):
            about = None
        if about:
            max_len = get_settings().about_text_max_length
            if len(about) > max_len:
                await adapter.send_message(
                    chat_id,
                    texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len),
                    _pax_about_kb(),
                )
                return
        data["about"] = about
        await reg_state.set_state(user_id, "passenger:preview", data)
        logger.info("MAX reg: user_id=%s state=passenger:preview", user_id)
        await adapter.send_message(
            chat_id,
            _build_passenger_preview(data),
            _pax_preview_kb(),
        )
        return

    if state == "passenger:preview":
        await adapter.send_message(
            chat_id,
            "Нажми «Сохранить» или «Редактировать».",
            _pax_preview_kb(),
        )
        return

    # Unknown state — clear and show menu
    logger.warning("MAX reg: unknown state=%s for user_id=%s — clearing", state, user_id)
    await reg_state.clear_state(user_id)
    await adapter.send_message(chat_id, "Что-то пошло не так. Начни заново.", get_main_menu_rows())


async def _handle_fsm_contact(
    adapter: MaxAdapter, chat_id: str, user_id: int, phone_number: str, fsm: dict
) -> None:
    """Handle contact during phone step of pilot or passenger registration."""
    state = fsm["state"]
    data = fsm["data"]

    if state not in ("pilot:phone", "passenger:phone"):
        await adapter.send_message(
            chat_id,
            "Сейчас ожидается другой ввод.",
            get_main_menu_rows(),
        )
        return

    phone = phone_number.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    data["phone"] = phone
    is_pilot = state.startswith("pilot")

    if is_pilot:
        next_state = "pilot:age"
        step = 3
        total = PILOT_TOTAL_STEPS
        ask_text = texts.REG_ASK_AGE
    else:
        next_state = "passenger:age"
        step = 3
        total = PASSENGER_TOTAL_STEPS
        ask_text = texts.REG_ASK_AGE

    await reg_state.set_state(user_id, next_state, data)
    logger.info("MAX reg: user_id=%s state=%s", user_id, next_state)
    await adapter.send_message(
        chat_id,
        progress_prefix(step, total) + ask_text,
        _cancel_kb(),
    )


async def _handle_fsm_photo(
    adapter: MaxAdapter, chat_id: str, user_id: int, file_id: str, fsm: dict
) -> None:
    """Handle photo upload during photo step."""
    state = fsm["state"]
    data = fsm["data"]

    if state == "pilot:photo":
        data["photo_file_id"] = file_id
        await reg_state.set_state(user_id, "pilot:about", data)
        logger.info("MAX reg: user_id=%s state=pilot:about (photo saved)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(11, PILOT_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pilot_about_kb(),
        )
    elif state == "passenger:photo":
        data["photo_file_id"] = file_id
        await reg_state.set_state(user_id, "passenger:about", data)
        logger.info("MAX reg: user_id=%s state=passenger:about (photo saved)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(9, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pax_about_kb(),
        )
    else:
        # Photo received outside photo step — ignore
        pass


async def _handle_fsm_callback(
    adapter: MaxAdapter, chat_id: str, user_id: int, cb_data: str, fsm: dict
) -> bool:
    """Handle FSM callback. Returns True if callback was consumed."""
    state = fsm["state"]
    data = fsm["data"]

    # Cancel
    if cb_data == "max_reg_cancel":
        await reg_state.clear_state(user_id)
        logger.info("MAX reg: user_id=%s cancelled", user_id)
        await adapter.send_message(chat_id, texts.FSM_CANCEL_TEXT, get_main_menu_rows())
        return True

    # ── Pilot gender ─────────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_gender_") and state == "pilot:gender":
        gender = cb_data.replace("max_reg_gender_", "")
        data["gender"] = gender
        await reg_state.set_state(user_id, "pilot:bike_brand", data)
        logger.info("MAX reg: user_id=%s state=pilot:bike_brand", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(5, PILOT_TOTAL_STEPS) + texts.REG_ASK_BIKE_BRAND,
            _cancel_kb(),
        )
        return True

    # ── Pilot style ───────────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_style_") and state == "pilot:driving_style":
        style = cb_data.replace("max_reg_style_", "")
        data["driving_style"] = style
        await reg_state.set_state(user_id, "pilot:photo", data)
        logger.info("MAX reg: user_id=%s state=pilot:photo", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(10, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHOTO,
            _pilot_photo_kb(),
        )
        return True

    # ── Pilot skip photo ──────────────────────────────────────────────────────
    if cb_data == "max_reg_skip_photo" and state == "pilot:photo":
        data["photo_file_id"] = None
        await reg_state.set_state(user_id, "pilot:about", data)
        logger.info("MAX reg: user_id=%s state=pilot:about (skip photo)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(11, PILOT_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pilot_about_kb(),
        )
        return True

    # ── Pilot skip about ──────────────────────────────────────────────────────
    if cb_data == "max_reg_skip_about" and state == "pilot:about":
        data["about"] = None
        await reg_state.set_state(user_id, "pilot:preview", data)
        logger.info("MAX reg: user_id=%s state=pilot:preview", user_id)
        await adapter.send_message(
            chat_id,
            _build_pilot_preview(data),
            _pilot_preview_kb(),
        )
        return True

    # ── Pilot preview save ────────────────────────────────────────────────────
    if cb_data == "max_reg_preview_save" and state == "pilot:preview":
        await _do_finish_pilot(adapter, chat_id, user_id, data)
        return True

    # ── Pilot preview edit ────────────────────────────────────────────────────
    if cb_data == "max_reg_preview_edit" and state == "pilot:preview":
        await reg_state.set_state(user_id, "pilot:name", {})
        logger.info("MAX reg: user_id=%s restarted (edit)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(1, PILOT_TOTAL_STEPS) + texts.REG_ASK_NAME,
            _cancel_kb(),
        )
        return True

    # ── Passenger gender ──────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_pax_gender_") and state == "passenger:gender":
        gender = cb_data.replace("max_reg_pax_gender_", "")
        data["gender"] = gender
        await reg_state.set_state(user_id, "passenger:weight", data)
        logger.info("MAX reg: user_id=%s state=passenger:weight", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(5, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_WEIGHT,
            _cancel_kb(),
        )
        return True

    # ── Passenger style ───────────────────────────────────────────────────────
    if cb_data.startswith("max_reg_pax_style_") and state == "passenger:preferred_style":
        style = cb_data.replace("max_reg_pax_style_", "")
        data["preferred_style"] = style
        await reg_state.set_state(user_id, "passenger:photo", data)
        logger.info("MAX reg: user_id=%s state=passenger:photo", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(8, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHOTO,
            _pax_photo_kb(),
        )
        return True

    # ── Passenger skip photo ──────────────────────────────────────────────────
    if cb_data == "max_reg_pax_skip_photo" and state == "passenger:photo":
        data["photo_file_id"] = None
        await reg_state.set_state(user_id, "passenger:about", data)
        logger.info("MAX reg: user_id=%s state=passenger:about (skip photo)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(9, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
            _pax_about_kb(),
        )
        return True

    # ── Passenger skip about ──────────────────────────────────────────────────
    if cb_data == "max_reg_pax_skip_about" and state == "passenger:about":
        data["about"] = None
        await reg_state.set_state(user_id, "passenger:preview", data)
        logger.info("MAX reg: user_id=%s state=passenger:preview", user_id)
        await adapter.send_message(
            chat_id,
            _build_passenger_preview(data),
            _pax_preview_kb(),
        )
        return True

    # ── Passenger preview save ────────────────────────────────────────────────
    if cb_data == "max_reg_pax_preview_save" and state == "passenger:preview":
        await _do_finish_passenger(adapter, chat_id, user_id, data)
        return True

    # ── Passenger preview edit ────────────────────────────────────────────────
    if cb_data == "max_reg_pax_preview_edit" and state == "passenger:preview":
        await reg_state.set_state(user_id, "passenger:name", {})
        logger.info("MAX reg: user_id=%s passenger restarted (edit)", user_id)
        await adapter.send_message(
            chat_id,
            progress_prefix(1, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_NAME,
            _cancel_kb(),
        )
        return True

    return False


async def _do_finish_pilot(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict
) -> None:
    """Commit pilot profile to DB and send confirmation."""
    err = await finish_pilot_registration(Platform.MAX, user_id, data)
    if err == "user_not_found":
        await adapter.send_message(chat_id, texts.REG_ERROR_USER_NOT_FOUND, get_main_menu_rows())
        return
    if err:
        # Keep state so user can retry
        logger.warning("MAX reg: pilot finish error=%s user_id=%s", err, user_id)
        await adapter.send_message(chat_id, texts.REG_ERROR_SAVE)
        return
    await reg_state.clear_state(user_id)
    logger.info("MAX reg: user_id=%s pilot registration done", user_id)
    await adapter.send_message(chat_id, texts.REG_DONE, get_main_menu_rows())


async def _do_finish_passenger(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict
) -> None:
    """Commit passenger profile to DB and send confirmation."""
    err = await finish_passenger_registration(Platform.MAX, user_id, data)
    if err == "user_not_found":
        await adapter.send_message(chat_id, texts.REG_ERROR_USER_NOT_FOUND, get_main_menu_rows())
        return
    if err:
        logger.warning("MAX reg: passenger finish error=%s user_id=%s", err, user_id)
        await adapter.send_message(chat_id, texts.REG_ERROR_SAVE)
        return
    await reg_state.clear_state(user_id)
    logger.info("MAX reg: user_id=%s passenger registration done", user_id)
    await adapter.send_message(chat_id, texts.REG_DONE, get_main_menu_rows())


# ── Top-level event handlers ──────────────────────────────────────────────────

async def process_max_update(adapter: MaxAdapter, raw: dict) -> None:
    """Process one MAX update."""
    events = parse_updates({"updates": [raw]})
    for ev in events:
        try:
            if isinstance(ev, IncomingCallback):
                await handle_callback(adapter, ev)
            elif isinstance(ev, IncomingMessage):
                await handle_message(adapter, ev)
            elif isinstance(ev, IncomingContact):
                await handle_contact(adapter, ev)
            elif isinstance(ev, IncomingPhoto):
                await handle_photo(adapter, ev)
            elif isinstance(ev, IncomingLocation):
                await handle_location(adapter, ev)
        except Exception as e:
            logger.exception("MAX handle error: %s", e)


async def handle_message(adapter: MaxAdapter, ev: IncomingMessage) -> None:
    """Handle text message or /start."""
    user = await get_or_create_user(
        platform="max",
        platform_user_id=ev.user_id,
        username=ev.username,
        first_name=ev.first_name,
    )
    if not user:
        return
    if user.is_blocked:
        await adapter.send_message(ev.chat_id, "Вы заблокированы. Обратитесь в поддержку.")
        return

    text = (ev.text or "").strip()

    # /cancel or «отмена»
    if text.lower() in ("/cancel", "отмена"):
        fsm = await reg_state.get_state(ev.user_id)
        if fsm:
            await reg_state.clear_state(ev.user_id)
            await adapter.send_message(ev.chat_id, texts.FSM_CANCEL_TEXT, get_main_menu_rows())
        else:
            await adapter.send_message(ev.chat_id, texts.FSM_CANCEL_TEXT, get_main_menu_rows())
        return

    if text.startswith("/start") or text.lower() == "start":
        await handle_start(adapter, ev.chat_id, user)
        return

    # Check active FSM
    fsm = await reg_state.get_state(ev.user_id)
    if fsm:
        await _handle_fsm_message(adapter, ev.chat_id, ev.user_id, text, fsm)
        return

    # Default
    await adapter.send_message(ev.chat_id, "Используй меню или /start", get_main_menu_rows())


async def handle_photo(adapter: MaxAdapter, ev: IncomingPhoto) -> None:
    """Handle photo message (registration photo step)."""
    user = await get_or_create_user(platform="max", platform_user_id=ev.user_id)
    if not user or user.is_blocked:
        return

    fsm = await reg_state.get_state(ev.user_id)
    if fsm and fsm["state"] in ("pilot:photo", "passenger:photo"):
        await _handle_fsm_photo(adapter, ev.chat_id, ev.user_id, ev.file_id, fsm)
    else:
        await adapter.send_message(ev.chat_id, "Используй меню или /start", get_main_menu_rows())


async def handle_start(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Handle /start flow — including resuming active FSM."""
    WELCOME = (
        "Привет! 👋\n"
        "Это бот мото‑сообщества Екатеринбурга.\n\n"
        "Здесь ты можешь:\n"
        "• 🚨 Отправить SOS в экстренной ситуации\n"
        "• 🏍 Найти мотопару\n"
        "• 📇 Узнать полезные контакты\n"
        "• 📅 Создавать и посещать мероприятия\n\n"
        "Для начала выбери город и свою роль."
    )

    if not user.city_id:
        await adapter.send_message(chat_id, WELCOME, get_city_select_rows())
        return

    if not await has_profile(user):
        if user.role in (UserRole.PILOT, UserRole.PASSENGER):
            # Check for active FSM — resume or start fresh
            fsm = await reg_state.get_state(user.platform_user_id)
            if fsm:
                state = fsm["state"]
                data = fsm["data"]
                await adapter.send_message(
                    chat_id,
                    "Продолжаем регистрацию...",
                )
                # Re-send the current step prompt
                await _resend_current_step(adapter, chat_id, user.platform_user_id, state, data)
            else:
                # Start registration
                if user.role == UserRole.PILOT:
                    await _start_pilot_registration(adapter, chat_id, user.platform_user_id)
                else:
                    await _start_passenger_registration(adapter, chat_id, user.platform_user_id)
            return
        else:
            await adapter.send_message(chat_id, WELCOME, get_role_select_rows())
            return

    await adapter.send_message(
        chat_id,
        "С возвращением! 👋\nГлавное меню:",
        get_main_menu_rows(),
    )


async def _resend_current_step(
    adapter: MaxAdapter, chat_id: str, user_id: int, state: str, data: dict
) -> None:
    """Re-send the prompt for the current FSM step (used when /start is called mid-flow)."""
    step_map = {
        "pilot:name": (1, PILOT_TOTAL_STEPS, texts.REG_ASK_NAME, _cancel_kb()),
        "pilot:phone": (2, PILOT_TOTAL_STEPS, texts.REG_ASK_PHONE, [get_contact_button_row(), _cancel_kb()[0]]),
        "pilot:age": (3, PILOT_TOTAL_STEPS, texts.REG_ASK_AGE, _cancel_kb()),
        "pilot:gender": (4, PILOT_TOTAL_STEPS, texts.REG_ASK_GENDER, _pilot_gender_kb()),
        "pilot:bike_brand": (5, PILOT_TOTAL_STEPS, texts.REG_ASK_BIKE_BRAND, _cancel_kb()),
        "pilot:bike_model": (6, PILOT_TOTAL_STEPS, texts.REG_ASK_BIKE_MODEL, _cancel_kb()),
        "pilot:engine_cc": (7, PILOT_TOTAL_STEPS, texts.REG_ASK_ENGINE_CC, _cancel_kb()),
        "pilot:driving_since": (8, PILOT_TOTAL_STEPS, texts.REG_ASK_DRIVING_SINCE, _cancel_kb()),
        "pilot:driving_style": (9, PILOT_TOTAL_STEPS, texts.REG_ASK_STYLE, _pilot_style_kb()),
        "pilot:photo": (10, PILOT_TOTAL_STEPS, texts.REG_ASK_PHOTO, _pilot_photo_kb()),
        "pilot:about": (11, PILOT_TOTAL_STEPS, texts.REG_ASK_ABOUT, _pilot_about_kb()),
        "passenger:name": (1, PASSENGER_TOTAL_STEPS, texts.REG_ASK_NAME, _cancel_kb()),
        "passenger:phone": (2, PASSENGER_TOTAL_STEPS, texts.REG_ASK_PHONE, [get_contact_button_row(), _cancel_kb()[0]]),
        "passenger:age": (3, PASSENGER_TOTAL_STEPS, texts.REG_ASK_AGE, _cancel_kb()),
        "passenger:gender": (4, PASSENGER_TOTAL_STEPS, texts.REG_ASK_GENDER, _pax_gender_kb()),
        "passenger:weight": (5, PASSENGER_TOTAL_STEPS, texts.REG_ASK_WEIGHT, _cancel_kb()),
        "passenger:height": (6, PASSENGER_TOTAL_STEPS, texts.REG_ASK_HEIGHT, _cancel_kb()),
        "passenger:preferred_style": (7, PASSENGER_TOTAL_STEPS, texts.REG_ASK_PREFERRED_STYLE, _pax_style_kb()),
        "passenger:photo": (8, PASSENGER_TOTAL_STEPS, texts.REG_ASK_PHOTO, _pax_photo_kb()),
        "passenger:about": (9, PASSENGER_TOTAL_STEPS, texts.REG_ASK_ABOUT, _pax_about_kb()),
    }

    if state in ("pilot:preview", "passenger:preview"):
        is_pilot = state.startswith("pilot")
        preview_text = _build_pilot_preview(data) if is_pilot else _build_passenger_preview(data)
        kb = _pilot_preview_kb() if is_pilot else _pax_preview_kb()
        await adapter.send_message(chat_id, preview_text, kb)
        return

    if state in step_map:
        step, total, ask_text, kb = step_map[state]
        await adapter.send_message(chat_id, progress_prefix(step, total) + ask_text, kb)
    else:
        await adapter.send_message(chat_id, "Начнём сначала.", get_main_menu_rows())


async def handle_callback(adapter: MaxAdapter, ev: IncomingCallback) -> None:
    """Handle callback button press."""
    user = await get_or_create_user(
        platform="max",
        platform_user_id=ev.user_id,
    )
    if not user:
        return
    if user.is_blocked:
        await adapter.send_message(ev.chat_id, "Вы заблокированы.")
        return

    data = ev.callback_data
    chat_id = ev.chat_id

    # ── FSM callbacks (highest priority) ─────────────────────────────────────
    fsm = await reg_state.get_state(ev.user_id)
    if fsm or data == "max_reg_cancel":
        if fsm is None:
            fsm = {}
        consumed = await _handle_fsm_callback(adapter, chat_id, ev.user_id, data, fsm)
        if consumed:
            return

    # ── City selection ────────────────────────────────────────────────────────
    if data == "city_ekb":
        from src.models.city import City
        cq = ev.raw.get("callback_query") or ev.raw.get("callback") or ev.raw
        from_obj = cq.get("from") or cq.get("user") or {}
        session_factory = get_session_factory()
        async with session_factory() as session:
            r = await session.execute(select(City).where(City.name == "Екатеринбург"))
            city = r.scalar_one_or_none()
            if city:
                user = await get_or_create_user(
                    platform="max",
                    platform_user_id=ev.user_id,
                    username=from_obj.get("username"),
                    first_name=from_obj.get("first_name"),
                    city_id=city.id,
                )
        await adapter.send_message(
            chat_id,
            "Отлично! Теперь выбери свою роль:",
            get_role_select_rows(),
        )
        return

    # ── Role selection → start registration ───────────────────────────────────
    if data in ("role_pilot", "role_passenger"):
        role = UserRole.PILOT if data == "role_pilot" else UserRole.PASSENGER
        session_factory = get_session_factory()
        async with session_factory() as session:
            r = await session.execute(
                select(User).where(
                    User.platform_user_id == ev.user_id,
                    User.platform == Platform.MAX,
                )
            )
            u = r.scalar_one_or_none()
            if u:
                u.role = role
                await session.commit()

        if role == UserRole.PILOT:
            await _start_pilot_registration(adapter, chat_id, ev.user_id)
        else:
            await _start_passenger_registration(adapter, chat_id, ev.user_id)
        return

    # ── Main menu ─────────────────────────────────────────────────────────────
    if data == "menu_main":
        await adapter.send_message(
            chat_id,
            "С возвращением! 👋\nГлавное меню:",
            get_main_menu_rows(),
        )
        return

    if data == "menu_sos":
        await adapter.request_location(
            chat_id,
            "Отправь свою геолокацию для SOS или напиши комментарий.",
        )
        return
    if data == "menu_motopair":
        await handle_motopair_menu(adapter, chat_id, user)
        return
    if data == "menu_contacts":
        await handle_contacts_menu(adapter, chat_id, user)
        return
    if data == "menu_events":
        await handle_events_menu(adapter, chat_id, user)
        return
    if data == "menu_profile":
        await handle_profile(adapter, chat_id, user)
        return
    if data == "menu_about":
        await handle_about(adapter, chat_id)
        return

    # ── MotoPair callbacks ────────────────────────────────────────────────────
    if data in ("motopair_pilots", "motopair_passengers"):
        role = "pilot" if data == "motopair_pilots" else "passenger"
        await handle_motopair_list(adapter, chat_id, user, role, offset=0)
        return
    if data.startswith("motopair_next_"):
        parts = data.replace("motopair_next_", "").split("_")
        role = parts[0] if parts else "pilot"
        offset = int(parts[1]) if len(parts) > 1 else 0
        await handle_motopair_list(adapter, chat_id, user, role, offset)
        return
    if data.startswith("like_"):
        parts = data.replace("like_", "").rsplit("_", 1)
        if len(parts) == 2:
            await handle_motopair_like(adapter, ev, user, parts[0], parts[1], is_like=True)
        return
    if data.startswith("dislike_"):
        parts = data.replace("dislike_", "").rsplit("_", 1)
        if len(parts) == 2:
            await handle_motopair_like(adapter, ev, user, parts[0], parts[1], is_like=False)
        return

    # ── Contacts callbacks ────────────────────────────────────────────────────
    if data.startswith("contacts_"):
        if data.startswith("contacts_page_"):
            p = data.replace("contacts_page_", "").split("_")
            if len(p) >= 2:
                await handle_contacts_list(adapter, chat_id, user, p[0], int(p[1]))
        else:
            cat = data.replace("contacts_", "")
            await handle_contacts_list(adapter, chat_id, user, cat, 0)
        return

    # ── Events callbacks ──────────────────────────────────────────────────────
    if data == "event_list" or data.startswith("event_list_"):
        ev_type = data.replace("event_list_", "") if "_" in data else None
        await handle_events_list(adapter, chat_id, user, ev_type)
        return
    if data.startswith("event_detail_"):
        eid = data.replace("event_detail_", "")
        await handle_event_detail(adapter, chat_id, user, eid)
        return
    if data.startswith("event_register_"):
        p = data.replace("event_register_", "").split("_")
        if len(p) >= 2:
            await handle_event_register(adapter, chat_id, user, p[0], p[1])
        return

    await adapter.send_message(chat_id, "Неизвестная команда.", get_main_menu_rows())


async def handle_contact(adapter: MaxAdapter, ev: IncomingContact) -> None:
    """Handle contact shared — used during registration phone step."""
    user = await get_or_create_user(platform="max", platform_user_id=ev.user_id)
    if not user or user.is_blocked:
        return

    fsm = await reg_state.get_state(ev.user_id)
    if fsm and fsm["state"] in ("pilot:phone", "passenger:phone"):
        await _handle_fsm_contact(adapter, ev.chat_id, ev.user_id, ev.phone_number, fsm)
    else:
        await adapter.send_message(
            ev.chat_id,
            f"Номер получен: {ev.phone_number}.",
            get_main_menu_rows(),
        )


async def handle_location(adapter: MaxAdapter, ev: IncomingLocation) -> None:
    """Handle location (e.g. SOS)."""
    await adapter.send_message(
        ev.chat_id,
        f"Геолокация получена: {ev.latitude:.5f}, {ev.longitude:.5f}. SOS в MAX — в разработке.",
        get_back_to_menu_rows(),
    )


# ── Feature handlers (unchanged from original) ────────────────────────────────

async def handle_motopair_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.subscription import check_subscription_required

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            "Для доступа к мотопаре нужна подписка. Оформи в «Мой профиль».",
            [[Button("👤 Мой профиль", payload="menu_profile")], [Button("« Назад", payload="menu_main")]],
        )
        return
    kb = [
        [Button("Анкеты пилотов", payload="motopair_pilots")],
        [Button("Анкеты двоек", payload="motopair_passengers")],
        [Button("« Назад", payload="menu_main")],
    ]
    await adapter.send_message(chat_id, "🏍 Мотопара\n\nВыбери категорию:", kb)


async def handle_motopair_list(
    adapter: MaxAdapter, chat_id: str, user, role: str, offset: int = 0
) -> None:
    from src.services.motopair_service import get_next_profile

    profile, has_more = await get_next_profile(user.id, role, offset=offset)
    if not profile:
        await adapter.send_message(
            chat_id, texts.MOTOPAIR_NO_PROFILES,
            [[Button("« В меню", payload="menu_motopair")]],
        )
        return
    text = _format_profile_max(profile)
    kb = get_motopair_profile_rows(str(profile.id), role, offset, has_more)
    await adapter.send_message(chat_id, text, kb)


async def handle_motopair_like(
    adapter: MaxAdapter, ev: IncomingCallback, user, profile_id_str: str, role: str, is_like: bool
) -> None:
    from src.services.motopair_service import get_user_for_profile, process_like

    try:
        to_user_id = await get_user_for_profile(uuid.UUID(profile_id_str), role)
    except (ValueError, TypeError):
        await adapter.send_message(ev.chat_id, "Ошибка.", get_back_to_menu_rows())
        return
    if not to_user_id:
        await adapter.send_message(ev.chat_id, "Профиль не найден.", get_back_to_menu_rows())
        return
    result = await process_like(user.id, to_user_id.id, is_like)
    if is_like and result.get("matched"):
        await adapter.send_message(
            ev.chat_id,
            "💚 Взаимный лайк! Контакты в Telegram-версии бота.",
            get_back_to_menu_rows(),
        )
    elif is_like:
        await adapter.send_message(ev.chat_id, "👍 Лайк отправлен!", get_back_to_menu_rows())
    else:
        await adapter.send_message(ev.chat_id, "👎 Дизлайк учтён.", get_back_to_menu_rows())
    await handle_motopair_list(adapter, ev.chat_id, user, role, 0)


async def handle_contacts_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    await adapter.send_message(chat_id, "📇 Полезные контакты\n\nВыбери категорию:", get_contacts_menu_rows())


async def handle_contacts_list(
    adapter: MaxAdapter, chat_id: str, user, category: str, offset: int = 0
) -> None:
    from src.services.useful_contacts_service import get_contacts_by_category, CAT_LABELS

    if not user.city_id:
        await adapter.send_message(chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows())
        return
    contacts, total, has_more = await get_contacts_by_category(user.city_id, category, offset=offset)
    label = CAT_LABELS.get(category, category)
    if not contacts:
        text = f"{label}\n\nКонтактов пока нет."
    else:
        lines = [f"<b>{label}</b>\n"]
        for c in contacts:
            line = f"• {c['name']}"
            if c.get("phone"):
                line += f" — {c['phone']}"
            if c.get("link"):
                line += f"\n  {c['link']}"
            lines.append(line)
        text = "\n".join(lines)
    kb = get_contacts_page_rows(category, offset, has_more)
    await adapter.send_message(chat_id, text, kb)


async def handle_events_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    await adapter.send_message(chat_id, "📅 Мероприятия", get_events_menu_rows())


async def handle_events_list(
    adapter: MaxAdapter, chat_id: str, user, event_type: str | None = None
) -> None:
    from src.services.event_service import get_events_list

    if not user.city_id:
        await adapter.send_message(chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows())
        return
    events = await get_events_list(user.city_id, event_type)
    if not events:
        await adapter.send_message(chat_id, "Мероприятий пока нет.", get_event_list_rows())
        return
    lines = ["<b>Список мероприятий</b>\n"]
    for e in events[:15]:
        lines.append(
            f"• {e['title']} — {e['date']}\n"
            f"  Пилотов: {e['pilots']}, двоек: {e['passengers']}"
        )
    text = "\n".join(lines)
    kb = get_event_list_rows()
    for e in events[:5]:
        kb.insert(-1, [Button(f"📅 {e['title'][:20]}", payload=f"event_detail_{e['id']}")])
    await adapter.send_message(chat_id, text[:4000], kb)


async def handle_event_detail(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    from src.services.event_service import get_event_by_id, TYPE_LABELS
    from src.models.event import EventRegistration

    ev = await get_event_by_id(uuid.UUID(event_id))
    if not ev:
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return
    title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
    text = (
        f"<b>{title}</b>\n"
        f"📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {ev.point_start or '—'}\n"
        f"{ev.description or ''}"
    )
    session_factory = get_session_factory()
    is_reg = False
    async with session_factory() as session:
        r = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == ev.id,
                EventRegistration.user_id == user.id,
            )
        )
        is_reg = r.scalar_one_or_none() is not None
    kb = get_event_detail_rows(event_id, is_reg)
    await adapter.send_message(chat_id, text, kb)


async def handle_event_register(
    adapter: MaxAdapter, chat_id: str, user, event_id: str, role: str
) -> None:
    from src.services.event_service import register_for_event

    ok, _ = await register_for_event(uuid.UUID(event_id), user.id, role)
    if ok:
        await adapter.send_message(chat_id, "✅ Ты зарегистрирован!", get_back_to_menu_rows())
    else:
        await adapter.send_message(chat_id, "Ошибка регистрации.", get_back_to_menu_rows())


async def handle_profile(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.admin_service import get_subscription_settings
    from src.services.payment import create_payment

    sub_required = await check_subscription_required(user)
    if sub_required:
        settings = await get_subscription_settings()
        text = (
            "Подписка нужна для доступа. Оформи через ссылку:\n"
            "Стоимость: месяц — {} ₽, сезон — {} ₽\n\n"
            "После оплаты нажми /start."
        ).format(
            (settings.monthly_price_kopecks or 29900) / 100,
            (settings.season_price_kopecks or 79900) / 100,
        )
        payment = await create_payment(
            amount_kopecks=settings.monthly_price_kopecks or 29900,
            description="Подписка на 1 месяц — мото-бот",
            metadata={"type": "subscription", "user_id": str(user.id), "period": "monthly"},
            return_url="https://max.ru/",
        )
        if payment and payment.get("confirmation_url"):
            text += f"\n\n💳 Оплатить: {payment['confirmation_url']}"
        await adapter.send_message(chat_id, text, get_back_to_menu_rows())
    else:
        await adapter.send_message(chat_id, "Мой профиль. Подписка активна.", get_back_to_menu_rows())


async def handle_about(adapter: MaxAdapter, chat_id: str) -> None:
    from src.services.admin_service import get_global_text

    text_db = await get_global_text("about_us")
    default = "Бот мото-сообщества Екатеринбурга."
    text = (text_db or default).strip()
    s = get_settings()
    text += f"\n\n📧 {s.support_email}\n👤 @{s.support_username}"
    await adapter.send_message(chat_id, text, get_back_to_menu_rows())
