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

# Module-level Telegram bot reference for cross-platform SOS broadcasts.
# Injected at startup via set_tg_bot() when platform=both or platform=telegram.
_tg_bot = None


def set_tg_bot(bot) -> None:
    """Inject the Telegram bot instance for cross-platform SOS broadcasts."""
    global _tg_bot
    _tg_bot = bot


def _get_tg_bot():
    return _tg_bot
from src.services.user import get_or_create_user, has_profile
from src.services import max_registration_state as reg_state
from src.services.registration_service import (
    finish_pilot_registration,
    finish_passenger_registration,
)
from src.models.user import User, UserRole, Platform, effective_user_id
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

    # ── SOS comment step ──────────────────────────────────────────────────────
    if state == "sos:comment":
        user = await get_or_create_user(platform="max", platform_user_id=user_id)
        if user:
            await _handle_sos_send(adapter, chat_id, user, comment=text.strip() if text else None)
        return

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
            progress_prefix(2, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHONE_MAX,
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "pilot:phone":
        # Accept manual phone number as fallback text input
        if text and len(text.strip()) >= 5:
            phone = text.strip()
            if not phone.startswith("+"):
                phone = "+" + phone
            data["phone"] = phone
            await reg_state.set_state(user_id, "pilot:age", data)
            logger.info("MAX reg: user_id=%s state=pilot:age (manual phone)", user_id)
            await adapter.send_message(
                chat_id,
                progress_prefix(3, PILOT_TOTAL_STEPS) + texts.REG_ASK_AGE,
                _cancel_kb(),
            )
        else:
            await adapter.send_message(
                chat_id,
                "Нажми кнопку «Отправить мой номер» или введи номер вручную (например: +79001234567):",
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
            progress_prefix(2, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHONE_MAX,
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

    if state == "passenger:phone":
        if text and len(text.strip()) >= 5:
            phone = text.strip()
            if not phone.startswith("+"):
                phone = "+" + phone
            data["phone"] = phone
            await reg_state.set_state(user_id, "passenger:age", data)
            logger.info("MAX reg: user_id=%s state=passenger:age (manual phone)", user_id)
            await adapter.send_message(
                chat_id,
                progress_prefix(3, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_AGE,
                _cancel_kb(),
            )
        else:
            await adapter.send_message(
                chat_id,
                "Нажми кнопку «Отправить мой номер» или введи номер вручную (например: +79001234567):",
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

    # ── Event create FSM steps ────────────────────────────────────────────────
    if state == "event_create:title":
        title = text.strip() if text else None
        if title and title.lower() in ("пропустить", "skip", "-"):
            ev_type = data.get("event_type", "")
            if ev_type == "large":
                await adapter.send_message(chat_id, "Для масштабного мероприятия название обязательно. Введи название:", _cancel_kb())
                return
            title = None
        data["title"] = title
        await reg_state.set_state(user_id, "event_create:date", data)
        await adapter.send_message(chat_id, "Дата начала (ДД.ММ.ГГГГ):", _cancel_kb())
        return

    if state == "event_create:date":
        dt = _parse_date(text)
        if not dt:
            await adapter.send_message(chat_id, "Формат: ДД.ММ.ГГГГ (например 15.06.2025)", _cancel_kb())
            return
        data["start_date"] = dt.strftime("%d.%m.%Y")
        await reg_state.set_state(user_id, "event_create:time", data)
        await adapter.send_message(chat_id, "Время начала (ЧЧ:ММ):", _cancel_kb())
        return

    if state == "event_create:time":
        import re as _re
        if not _re.match(r"^\d{1,2}:\d{2}$", text.strip()):
            await adapter.send_message(chat_id, "Формат: ЧЧ:ММ (например 10:00)", _cancel_kb())
            return
        data["start_time"] = text.strip()
        await reg_state.set_state(user_id, "event_create:point_start", data)
        await adapter.send_message(chat_id, "Точка старта — введи адрес:", _cancel_kb())
        return

    if state == "event_create:point_start":
        if not text:
            await adapter.send_message(chat_id, "Введи адрес старта:", _cancel_kb())
            return
        data["point_start"] = text.strip()[:500]
        await reg_state.set_state(user_id, "event_create:point_end", data)
        await adapter.send_message(
            chat_id,
            "Точка финиша — введи адрес или «Пропустить»:",
            [[Button("Пропустить", payload="max_evcreate_skip_end")], _cancel_kb()[0]],
        )
        return

    if state == "event_create:point_end":
        val = text.strip() if text else None
        if val and val.lower() in ("пропустить", "skip", "-"):
            val = None
        data["point_end"] = val[:500] if val else None
        await reg_state.set_state(user_id, "event_create:description", data)
        await adapter.send_message(
            chat_id,
            "Описание мероприятия (или «Пропустить»):",
            [[Button("Пропустить", payload="max_evcreate_skip_desc")], _cancel_kb()[0]],
        )
        return

    if state == "event_create:description":
        val = text.strip() if text else None
        if val and val.lower() in ("пропустить", "skip", "-"):
            val = None
        data["description"] = val[:1000] if val else None
        await _do_create_event(adapter, chat_id, user_id, data)
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

    if len(phone) < 5:
        # Phone couldn't be extracted automatically — ask for manual entry
        logger.warning("MAX reg: user_id=%s empty/invalid phone from contact attachment", user_id)
        await adapter.send_message(
            chat_id,
            "Не удалось получить номер телефона автоматически. "
            "Введи номер вручную (например: +79001234567):",
            [get_contact_button_row(), _cancel_kb()[0]],
        )
        return

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
    # Cancel — handle first, fsm may be empty if state expired
    if cb_data == "max_reg_cancel":
        await reg_state.clear_state(user_id)
        logger.info("MAX reg: user_id=%s cancelled", user_id)
        await adapter.send_message(chat_id, texts.FSM_CANCEL_TEXT, get_main_menu_rows())
        return True

    state = fsm.get("state")
    data = fsm.get("data", {})
    if not state:
        return False

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

    # ── Event create skip buttons ─────────────────────────────────────────────
    if cb_data == "max_evcreate_skip_end" and state == "event_create:point_end":
        data["point_end"] = None
        await reg_state.set_state(user_id, "event_create:description", data)
        await adapter.send_message(
            chat_id,
            "Описание мероприятия (или «Пропустить»):",
            [[Button("Пропустить", payload="max_evcreate_skip_desc")], _cancel_kb()[0]],
        )
        return True

    if cb_data == "max_evcreate_skip_desc" and state == "event_create:description":
        data["description"] = None
        await _do_create_event(adapter, chat_id, user_id, data)
        return True

    return False


async def _do_create_event(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict
) -> None:
    """Commit event to DB after all FSM steps collected."""
    from src.services.event_service import create_event
    from src.models.base import get_session_factory
    from src.models.user import User, Platform
    from sqlalchemy import select

    await reg_state.clear_state(user_id)

    # Resolve city_id for this user
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(User.platform_user_id == user_id, User.platform == Platform.MAX)
        )
        u = r.scalar_one_or_none()

    if not u or not u.city_id:
        await adapter.send_message(chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows())
        return

    # Parse datetime
    try:
        from datetime import datetime as _dt
        start_at = _dt.strptime(
            f"{data['start_date']} {data['start_time']}", "%d.%m.%Y %H:%M"
        )
    except (KeyError, ValueError):
        await adapter.send_message(chat_id, "Ошибка даты/времени. Создание отменено.", get_back_to_menu_rows())
        return

    ev = await create_event(
        city_id=u.city_id,
        creator_id=u.id,
        event_type=data.get("event_type", "run"),
        title=data.get("title"),
        start_at=start_at,
        point_start=data.get("point_start", ""),
        point_end=data.get("point_end"),
        ride_type=None,
        avg_speed=None,
        description=data.get("description"),
    )
    if ev:
        from src.services.event_service import TYPE_LABELS
        title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
        await adapter.send_message(
            chat_id,
            f"✅ Мероприятие создано!\n\n<b>{title}</b>\n📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n📍 {ev.point_start or '—'}",
            get_back_to_menu_rows(),
        )
    else:
        await adapter.send_message(chat_id, "Ошибка при создании мероприятия.", get_back_to_menu_rows())


async def _do_finish_pilot(
    adapter: MaxAdapter, chat_id: str, user_id: int, data: dict
) -> None:
    """Commit pilot profile to DB and send confirmation."""
    err = await finish_pilot_registration(Platform.MAX, user_id, data)
    if err == "user_not_found":
        await adapter.send_message(chat_id, texts.REG_ERROR_USER_NOT_FOUND, get_main_menu_rows())
        return
    if err:
        logger.warning("MAX reg: pilot finish error=%s user_id=%s", err, user_id)
        await adapter.send_message(
            chat_id,
            texts.REG_ERROR_SAVE,
            get_back_to_menu_rows(),
        )
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
        await adapter.send_message(
            chat_id,
            texts.REG_ERROR_SAVE,
            get_back_to_menu_rows(),
        )
        return
    await reg_state.clear_state(user_id)
    logger.info("MAX reg: user_id=%s passenger registration done", user_id)
    await adapter.send_message(chat_id, texts.REG_DONE, get_main_menu_rows())


# ── Top-level event handlers ──────────────────────────────────────────────────

def _max_use_chat_id(ev) -> bool:
    """True when event target is recipient.chat_id (use chat_id param for POST /messages)."""
    return bool(getattr(ev, "raw", None) and ev.raw.get("_max_use_chat_id"))


async def process_max_update(adapter: MaxAdapter, raw: dict) -> None:
    """Process one MAX update."""
    from src.platforms.max_adapter import set_max_use_chat_id

    events = parse_updates({"updates": [raw]})
    for ev in events:
        try:
            set_max_use_chat_id(_max_use_chat_id(ev))
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
        "pilot:phone": (2, PILOT_TOTAL_STEPS, texts.REG_ASK_PHONE_MAX, [get_contact_button_row(), _cancel_kb()[0]]),
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
        "passenger:phone": (2, PASSENGER_TOTAL_STEPS, texts.REG_ASK_PHONE_MAX, [get_contact_button_row(), _cancel_kb()[0]]),
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
    # Acknowledge the button press immediately (removes loading state in MAX UI)
    cb_id = (ev.raw.get("callback") or {}).get("callback_id") or ""
    if cb_id:
        await adapter.answer_callback(cb_id)

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
        cb_user = (ev.raw.get("callback") or {}).get("user") or {}
        session_factory = get_session_factory()
        async with session_factory() as session:
            r = await session.execute(select(City).where(City.name == "Екатеринбург"))
            city = r.scalar_one_or_none()
            if city:
                user = await get_or_create_user(
                    platform="max",
                    platform_user_id=ev.user_id,
                    username=cb_user.get("username"),
                    first_name=cb_user.get("first_name") or cb_user.get("name"),
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
        await _handle_sos_menu(adapter, chat_id, user)
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

    # ── SOS callbacks ─────────────────────────────────────────────────────────
    if data in ("sos_accident", "sos_broken", "sos_ran_out", "sos_other"):
        await _handle_sos_type_selected(adapter, chat_id, ev.user_id, data)
        return
    if data == "sos_skip_comment":
        await _handle_sos_send(adapter, chat_id, user, comment=None)
        return
    if data == "sos_check_ready":
        await _handle_sos_check_ready(adapter, chat_id, ev.user_id)
        return
    if data == "sos_all_clear":
        await _handle_sos_all_clear(adapter, chat_id, user)
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

    if data.startswith("max_event_report_"):
        eid = data.replace("max_event_report_", "")
        await handle_event_report(adapter, chat_id, user, eid)
        return

    # ── Payment callbacks ─────────────────────────────────────────────────────
    if (
        data.startswith("max_pay_")
        or data.startswith("max_profile_")
        or data.startswith("max_donate")
        or data.startswith("max_evcreate_")
        or data == "max_event_create"
    ):
        consumed = await _handle_payment_callback(adapter, chat_id, user, data)
        if consumed:
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
    """Handle location — used for SOS flow."""
    user = await get_or_create_user(platform="max", platform_user_id=ev.user_id)
    if not user or user.is_blocked:
        return

    fsm = await reg_state.get_state(ev.user_id)
    if fsm and fsm.get("state") == "sos:location":
        # Save location data and transition to comment step
        data = fsm.get("data", {})
        data["lat"] = ev.latitude
        data["lon"] = ev.longitude
        await reg_state.set_state(ev.user_id, "sos:comment", data)
        skip_kb = [[Button(texts.BTN_SKIP, payload="sos_skip_comment")]]
        await adapter.send_message(
            ev.chat_id,
            "📍 Локация получена!\n\nДобавь комментарий или нажми «Пропустить»:",
            skip_kb,
        )
    else:
        await adapter.send_message(
            ev.chat_id,
            f"Геолокация получена ({ev.latitude:.5f}, {ev.longitude:.5f}).",
            get_back_to_menu_rows(),
        )


# ── SOS handlers for MAX ─────────────────────────────────────────────────────

def _sos_type_kb() -> list[KeyboardRow]:
    return [
        [Button("ДТП", payload="sos_accident"), Button("Сломался", payload="sos_broken")],
        [Button("Обсох", payload="sos_ran_out"), Button("Другое", payload="sos_other")],
        [Button("« Назад", payload="menu_main")],
    ]


async def _handle_sos_menu(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Show SOS type selection and set FSM state."""
    if not user.city_id:
        await adapter.send_message(chat_id, "Город не выбран. Нажми /start", get_back_to_menu_rows())
        return

    from src.services.sos_service import check_sos_cooldown
    remaining = await check_sos_cooldown(user.id)
    if remaining > 0:
        mins, secs = remaining // 60, remaining % 60
        kb = [[Button(texts.SOS_CHECK_READY, payload="sos_check_ready")], [Button("« Назад", payload="menu_main")]]
        await adapter.send_message(
            chat_id,
            texts.SOS_READY_WAIT.format(mins=mins, secs=secs),
            kb,
        )
        return

    await reg_state.set_state(user.platform_user_id, "sos:choose_type", {})
    await adapter.send_message(chat_id, texts.SOS_CHOOSE_TYPE, _sos_type_kb())


async def _handle_sos_type_selected(
    adapter: MaxAdapter, chat_id: str, user_id: int, sos_type: str
) -> None:
    """User selected SOS type — ask for location."""
    fsm = await reg_state.get_state(user_id)
    data = fsm.get("data", {}) if fsm else {}
    data["sos_type"] = sos_type
    await reg_state.set_state(user_id, "sos:location", data)
    kb = [[get_location_button_row()[0]], [Button("❌ Отменить", payload="max_reg_cancel")]]
    await adapter.send_message(
        chat_id,
        texts.SOS_SEND_LOCATION,
        kb,
    )


async def _handle_sos_send(
    adapter: MaxAdapter, chat_id: str, user, comment: str | None
) -> None:
    """Create and broadcast SOS alert from MAX."""
    from src.services.sos_service import (
        create_sos_alert,
        get_city_telegram_user_ids,
        get_city_max_user_ids,
    )
    from src.services.broadcast import broadcast_max_background, get_max_adapter
    from src.services.user import get_user_profile_display
    from src.config import get_settings

    fsm = await reg_state.get_state(user.platform_user_id)
    data = fsm.get("data", {}) if fsm else {}
    await reg_state.clear_state(user.platform_user_id)

    required = ("sos_type", "lat", "lon")
    if not all(k in data for k in required):
        await adapter.send_message(
            chat_id,
            "Данные SOS устарели. Начни заново — нажми кнопку 🆘 SOS.",
            get_back_to_menu_rows(),
        )
        return

    if not user.city_id:
        await adapter.send_message(chat_id, texts.SOS_NO_CITY, get_back_to_menu_rows())
        return

    ok, remaining = await create_sos_alert(
        user_id=user.id,
        city_id=user.city_id,
        sos_type=data["sos_type"],
        lat=data["lat"],
        lon=data["lon"],
        comment=comment,
    )
    if not ok:
        mins, secs = remaining // 60, remaining % 60
        kb = [[Button(texts.SOS_CHECK_READY, payload="sos_check_ready")], [Button("« Назад", payload="menu_main")]]
        await adapter.send_message(chat_id, texts.SOS_READY_WAIT.format(mins=mins, secs=secs), kb)
        return

    type_labels = {
        "sos_accident": "ДТП",
        "sos_broken": "Сломался",
        "sos_ran_out": "Обсох",
        "sos_other": "Другое",
    }
    settings = get_settings()
    profile = await get_user_profile_display(user)

    broadcast_text = texts.SOS_BROADCAST_TYPE.format(
        type_label=type_labels.get(data["sos_type"], "Другое"),
        profile=profile,
    )
    if comment:
        broadcast_text += texts.SOS_BROADCAST_COMMENT.format(comment=comment)
    broadcast_text += texts.SOS_BROADCAST_MAP.format(lon=data["lon"], lat=data["lat"])

    # Build keyboard for MAX recipients
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger
    from src.models.base import get_session_factory as _gsf
    from sqlalchemy import select as _sel
    phone = None
    _sf = _gsf()
    async with _sf() as _sess:
        if user.role.value == "pilot":
            r = await _sess.execute(_sel(ProfilePilot.phone).where(ProfilePilot.user_id == user.id))
        else:
            r = await _sess.execute(_sel(ProfilePassenger.phone).where(ProfilePassenger.user_id == user.id))
        phone = r.scalar_one_or_none()

    max_kb = []
    if phone:
        max_kb.append([Button(text=texts.SOS_BTN_CALL, type=ButtonType.URL, url=f"tel:{phone}")])

    # Broadcast to MAX users in the city
    max_user_ids = await get_city_max_user_ids(user.city_id)
    if max_user_ids:
        broadcast_max_background(
            adapter, max_user_ids, broadcast_text,
            exclude_id=user.platform_user_id,
            kb_rows=max_kb if max_kb else None,
        )

    # Cross-platform: also broadcast to Telegram users in the city
    from src.services.broadcast import broadcast_background
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    tg_user_ids = await get_city_telegram_user_ids(user.city_id)
    if tg_user_ids:
        # Build Telegram keyboard with phone and "write in Telegram" button
        # Note: MAX user doesn't have a Telegram profile link, so only phone button
        tg_kb_rows = []
        if phone:
            tg_kb_rows.append([InlineKeyboardButton(text=texts.SOS_BTN_CALL, url=f"tel:{phone}")])
        tg_kb = InlineKeyboardMarkup(inline_keyboard=tg_kb_rows) if tg_kb_rows else None
        tg_bot_instance = _get_tg_bot()
        if tg_bot_instance:
            broadcast_background(tg_bot_instance, tg_user_ids, broadcast_text, reply_markup=tg_kb)

    cooldown_mins = settings.sos_cooldown_minutes
    kb = [
        [Button(texts.SOS_CHECK_READY, payload="sos_check_ready")],
        [Button(texts.SOS_ALL_CLEAR_BTN, payload="sos_all_clear")],
        [Button("« Назад в меню", payload="menu_main")],
    ]
    await adapter.send_message(chat_id, texts.SOS_SENT.format(cooldown=cooldown_mins), kb)


async def _handle_sos_check_ready(adapter: MaxAdapter, chat_id: str, user_id: int) -> None:
    """Show current cooldown status."""
    from src.services.sos_service import check_sos_cooldown

    user = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not user:
        return
    remaining = await check_sos_cooldown(user.id)
    if remaining <= 0:
        kb = [[Button("🚨 Отправить SOS", payload="menu_sos")], [Button("« Главное меню", payload="menu_main")]]
        await adapter.send_message(chat_id, texts.SOS_READY_NOW, kb)
    else:
        mins, secs = remaining // 60, remaining % 60
        kb = [[Button(texts.SOS_CHECK_READY, payload="sos_check_ready")], [Button("« Назад", payload="menu_main")]]
        await adapter.send_message(chat_id, texts.SOS_READY_WAIT.format(mins=mins, secs=secs), kb)


async def _handle_sos_all_clear(adapter: MaxAdapter, chat_id: str, user) -> None:
    """Broadcast 'all clear' from MAX user."""
    from src.services.sos_service import get_city_telegram_user_ids, get_city_max_user_ids
    from src.services.broadcast import broadcast_max_background, broadcast_background
    from src.services.user import get_user_profile_display

    if not user or not user.city_id:
        await adapter.send_message(chat_id, texts.SOS_NO_CITY, get_back_to_menu_rows())
        return

    name = user.platform_first_name or user.platform_username or "Участник"
    clear_text = texts.SOS_ALL_CLEAR_BROADCAST.format(name=name)

    # Broadcast to MAX users
    max_user_ids = await get_city_max_user_ids(user.city_id)
    if max_user_ids:
        broadcast_max_background(adapter, max_user_ids, clear_text, exclude_id=user.platform_user_id)

    # Cross-platform: broadcast to Telegram users
    tg_user_ids = await get_city_telegram_user_ids(user.city_id)
    if tg_user_ids:
        tg_bot_instance = _get_tg_bot()
        if tg_bot_instance:
            broadcast_background(tg_bot_instance, tg_user_ids, clear_text)

    await adapter.send_message(chat_id, "✅ Рады, что всё хорошо! Отбой разослан.", get_back_to_menu_rows())


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

    profile, has_more = await get_next_profile(effective_user_id(user), role, offset=offset)
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
    eff_from = effective_user_id(user)
    target_user = to_user_id  # variable renamed for clarity below
    result = await process_like(eff_from, target_user.id, is_like)

    if is_like and result.get("matched"):
        from src.services.motopair_service import get_profile_info_text
        from src.services.notification_templates import get_template
        from src.services.activity_log_service import log_event
        from src.models.activity_log import ActivityEventType

        await log_event(
            ActivityEventType.MUTUAL_LIKE,
            user_id=eff_from,
            data={"target_user_id": str(target_user.id), "from_user_id": str(eff_from)},
        )

        # Show target's contact info to current (MAX) user
        from_text, _ = await get_profile_info_text(target_user.id)
        match_kb = []
        if target_user.platform_username:
            match_kb.append([Button(
                "💬 Написать",
                type=ButtonType.URL,
                url=f"https://t.me/{target_user.platform_username}",
            )])
        msg_self = await get_template("template_mutual_like_self", profile=from_text)
        await adapter.send_message(ev.chat_id, msg_self, match_kb if match_kb else get_back_to_menu_rows())

        # Notify the target user on their platform
        to_text, _ = await get_profile_info_text(eff_from)
        if result.get("target_platform_user_id"):
            target_platform = result.get("target_platform")
            msg_target = await get_template("template_mutual_like_target", profile=to_text)
            if target_platform and target_platform.value == "max":
                # Notify on MAX
                max_match_kb = []
                if user.platform_username:
                    max_match_kb.append([Button(
                        "💬 Написать",
                        type=ButtonType.URL,
                        url=f"https://t.me/{user.platform_username}",
                    )])
                try:
                    await adapter.send_message(
                        str(result["target_platform_user_id"]), msg_target,
                        max_match_kb if max_match_kb else None
                    )
                except Exception as e:
                    logger.warning("MAX: cannot notify matched user %s: %s", result["target_platform_user_id"], e)
            else:
                # Notify on Telegram
                tg_bot_instance = _get_tg_bot()
                if tg_bot_instance:
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    tg_match_kb = []
                    if user.platform_username:
                        tg_match_kb.append([InlineKeyboardButton(
                            text="💬 Написать в MAX?",
                            url=f"https://t.me/{user.platform_username}",
                        )])
                    try:
                        await tg_bot_instance.send_message(
                            result["target_platform_user_id"],
                            msg_target,
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=tg_match_kb) if tg_match_kb else None,
                        )
                    except Exception as e:
                        logger.warning("TG: cannot notify matched user %s: %s", result["target_platform_user_id"], e)

    elif is_like:
        # Notify the liked user (like received)
        from src.services.motopair_service import get_profile_info_text
        from src.services.notification_templates import get_template
        from_text, _ = await get_profile_info_text(eff_from)
        if result.get("target_platform_user_id"):
            target_platform = result.get("target_platform")
            notify_text = await get_template("template_like_received", profile=from_text)
            if target_platform and target_platform.value == "max":
                try:
                    await adapter.send_message(
                        str(result["target_platform_user_id"]), notify_text
                    )
                except Exception as e:
                    logger.warning("MAX: cannot notify like user %s: %s", result["target_platform_user_id"], e)
            else:
                tg_bot_instance = _get_tg_bot()
                if tg_bot_instance:
                    try:
                        await tg_bot_instance.send_message(
                            result["target_platform_user_id"], notify_text
                        )
                    except Exception as e:
                        logger.warning("TG: cannot notify like user %s: %s", result["target_platform_user_id"], e)

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
    from src.services.subscription import check_subscription_required

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            "Для доступа к мероприятиям нужна подписка. Оформи в «Мой профиль».",
            [
                [Button("👤 Мой профиль", payload="menu_profile")],
                [Button("« Назад", payload="menu_main")],
            ],
        )
        return
    # Build events menu with create button
    kb = list(get_events_menu_rows())
    # Insert "Create event" before the last "Back" row
    create_row = [Button("➕ Создать мероприятие", payload="max_event_create")]
    if kb and kb[-1]:
        kb.insert(-1, create_row)
    else:
        kb.append(create_row)
    await adapter.send_message(chat_id, "📅 Мероприятия", kb)


async def handle_events_list(
    adapter: MaxAdapter, chat_id: str, user, event_type: str | None = None
) -> None:
    from src.services.event_service import get_events_list
    from src.services.subscription import check_subscription_required

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            "Для доступа к мероприятиям нужна подписка. Оформи в «Мой профиль».",
            [[Button("👤 Мой профиль", payload="menu_profile")], [Button("« Назад", payload="menu_main")]],
        )
        return
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
                EventRegistration.user_id == effective_user_id(user),
            )
        )
        is_reg = r.scalar_one_or_none() is not None
    can_report = ev.creator_id != effective_user_id(user)
    kb = get_event_detail_rows(event_id, is_reg, can_report=can_report)
    await adapter.send_message(chat_id, text, kb)


async def handle_event_register(
    adapter: MaxAdapter, chat_id: str, user, event_id: str, role: str
) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.event_service import register_for_event

    if await check_subscription_required(user):
        await adapter.send_message(
            chat_id,
            "Для записи на мероприятия нужна подписка. Оформи в «Мой профиль».",
            get_back_to_menu_rows(),
        )
        return
    ok, _ = await register_for_event(uuid.UUID(event_id), effective_user_id(user), role)
    if ok:
        await adapter.send_message(chat_id, "✅ Ты зарегистрирован!", get_back_to_menu_rows())
    else:
        await adapter.send_message(chat_id, "Ошибка регистрации.", get_back_to_menu_rows())


async def handle_event_report(adapter: MaxAdapter, chat_id: str, user, event_id: str) -> None:
    """Report an event from MAX. Notifies city admins and superadmins via Telegram."""
    from src.services.event_service import get_event_by_id, TYPE_LABELS
    from src.services.admin_service import get_city_admins
    from src.config import get_settings
    from src import texts

    try:
        ev_uuid = uuid.UUID(event_id)
    except ValueError:
        await adapter.send_message(chat_id, "Ошибка.", get_back_to_menu_rows())
        return

    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await adapter.send_message(chat_id, "Мероприятие не найдено.", get_back_to_menu_rows())
        return

    if ev.creator_id == effective_user_id(user):
        await adapter.send_message(chat_id, "Нельзя пожаловаться на своё мероприятие.", get_back_to_menu_rows())
        return

    ev_title = ev.title or TYPE_LABELS.get(ev.type.value, ev.type.value)
    reporter = f"@{user.platform_username}" if user.platform_username else str(user.platform_user_id)
    admin_text = texts.EVENT_REPORT_ADMIN_TEXT.format(
        reporter=reporter,
        event_title=ev_title,
        event_date=ev.start_at.strftime("%d.%m.%Y %H:%M"),
        event_type=TYPE_LABELS.get(ev.type.value, ev.type.value),
    )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.EVENT_REPORT_BTN_ACCEPT, callback_data=f"admin_evreport_accept_{event_id}")],
        [InlineKeyboardButton(text=texts.EVENT_REPORT_BTN_REJECT, callback_data=f"admin_evreport_reject_{event_id}")],
    ])

    tg_bot = _get_tg_bot()
    settings = get_settings()

    if ev.city_id:
        admins = await get_city_admins(ev.city_id)
        for _, admin_user in admins:
            try:
                if tg_bot:
                    await tg_bot.send_message(admin_user.platform_user_id, admin_text, reply_markup=admin_kb)
            except Exception as e:
                logger.warning("Cannot notify city admin %s: %s", admin_user.platform_user_id, e)

    if tg_bot:
        for admin_id in settings.superadmin_ids:
            try:
                await tg_bot.send_message(admin_id, admin_text, reply_markup=admin_kb)
            except Exception as e:
                logger.warning("Cannot notify superadmin %s: %s", admin_id, e)

    await adapter.send_message(chat_id, texts.EVENT_REPORT_SENT, get_back_to_menu_rows())


async def handle_profile(adapter: MaxAdapter, chat_id: str, user) -> None:
    from src.services.subscription import check_subscription_required
    from src.services.admin_service import get_subscription_settings
    from src.services.payment import create_payment
    from src.models.subscription import Subscription

    sub_settings = await get_subscription_settings()
    monthly_price = (sub_settings.monthly_price_kopecks if sub_settings and sub_settings.monthly_price_kopecks else 29900)
    season_price = (sub_settings.season_price_kopecks if sub_settings and sub_settings.season_price_kopecks else 79900)

    sub_required = await check_subscription_required(user)
    if sub_required:
        # Offer both monthly and season subscription options
        monthly_payment = await create_payment(
            amount_kopecks=monthly_price,
            description="Подписка на 1 месяц — мото-бот",
            metadata={"type": "subscription", "user_id": str(effective_user_id(user)), "period": "monthly", "platform": "max"},
            return_url="https://max.ru/",
        )
        season_payment = await create_payment(
            amount_kopecks=season_price,
            description="Подписка на сезон — мото-бот",
            metadata={"type": "subscription", "user_id": str(effective_user_id(user)), "period": "season", "platform": "max"},
            return_url="https://max.ru/",
        )

        text = (
            "👤 Мой профиль\n\n"
            "Для доступа к функциям бота нужна подписка.\n\n"
            "Подписка открывает:\n"
            "• Анкеты, лайки и контакты при совпадении\n"
            "• Просмотр и запись на мероприятия\n"
            "• Прохваты — без ограничений\n"
            "• Мотопробеги — 2 бесплатно в месяц\n\n"
            f"• 1 месяц — {monthly_price // 100} ₽\n"
            f"• Сезон — {season_price // 100} ₽\n\n"
            "Выбери тариф и оплати по ссылке. После оплаты нажми «Я оплатил — проверить»."
        )
        kb = []
        if monthly_payment and monthly_payment.get("confirmation_url"):
            kb.append([Button(f"💳 1 месяц — {monthly_price // 100} ₽", type=ButtonType.URL, url=monthly_payment["confirmation_url"])])
            # Store monthly payment_id in FSM for check
            await reg_state.set_state(
                user.platform_user_id,
                "pay:subscription",
                {"payment_id": monthly_payment["id"], "period": "monthly"},
            )
        if season_payment and season_payment.get("confirmation_url"):
            kb.append([Button(f"💳 Сезон — {season_price // 100} ₽", type=ButtonType.URL, url=season_payment["confirmation_url"])])
        if kb:
            kb.append([Button("✅ Я оплатил — проверить", payload="max_pay_sub_check")])
        kb.append([Button("« Назад", payload="menu_main")])
        await adapter.send_message(chat_id, text, kb)
    else:
        # Subscription active — show profile menu
        from src.services.profile_service import get_profile_text
        from src.services.admin_service import get_subscription_settings as _get_sub_settings

        try:
            profile_text = await get_profile_text(user)
        except Exception:
            profile_text = "👤 Мой профиль\n\nПодписка активна."

        sub_settings2 = await _get_sub_settings()
        raise_enabled = sub_settings2 and sub_settings2.raise_profile_enabled if sub_settings2 else False
        raise_price = (sub_settings2.raise_profile_price_kopecks if sub_settings2 and sub_settings2.raise_profile_price_kopecks else 0)

        kb = [[Button("🔄 Продлить подписку", payload="max_profile_renew_sub")]]
        if raise_enabled:
            label = f"⬆️ Поднять анкету — {raise_price // 100} ₽" if raise_price > 0 else "⬆️ Поднять анкету (бесплатно)"
            kb.append([Button(label, payload="max_profile_raise")])
        kb.append([Button("« Назад", payload="menu_main")])
        await adapter.send_message(chat_id, profile_text, kb)


async def handle_about(adapter: MaxAdapter, chat_id: str) -> None:
    from src.services.admin_service import get_global_text

    text_db = await get_global_text("about_us")
    default = "Бот мото-сообщества Екатеринбурга."
    text = (text_db or default).strip()
    s = get_settings()
    text += f"\n\n📧 {s.support_email}\n👤 @{s.support_username}"
    kb = [
        [Button("❤️ Поддержать проект", payload="max_donate")],
        [Button("« Назад", payload="menu_main")],
    ]
    await adapter.send_message(chat_id, text, kb)


# ── MAX payment FSM helpers ────────────────────────────────────────────────────

_PAY_KEY_PREFIX = "max_pay:"
_PAY_TTL = 3600


async def _pay_set(user_id: int, data: dict) -> None:
    """Store payment pending state for MAX user (reuses reg_state Redis/memory)."""
    key = f"{_PAY_KEY_PREFIX}{user_id}"
    import json
    payload = json.dumps(data, ensure_ascii=False)
    from src.services import max_registration_state as _rs
    if _rs._redis_client is not None:
        try:
            await _rs._redis_client.set(key, payload, ex=_PAY_TTL)
            return
        except Exception as exc:
            logger.warning("max_pay set Redis error: %s", exc)
    _rs._memory_store[f"pay_{user_id}"] = data


async def _pay_get(user_id: int) -> dict | None:
    """Get payment pending state for MAX user."""
    import json
    from src.services import max_registration_state as _rs
    key = f"{_PAY_KEY_PREFIX}{user_id}"
    if _rs._redis_client is not None:
        try:
            val = await _rs._redis_client.get(key)
            if val:
                return json.loads(val)
            return None
        except Exception as exc:
            logger.warning("max_pay get Redis error: %s", exc)
    return _rs._memory_store.get(f"pay_{user_id}")


async def _pay_clear(user_id: int) -> None:
    """Clear payment pending state for MAX user."""
    from src.services import max_registration_state as _rs
    key = f"{_PAY_KEY_PREFIX}{user_id}"
    if _rs._redis_client is not None:
        try:
            await _rs._redis_client.delete(key)
            return
        except Exception as exc:
            logger.warning("max_pay clear Redis error: %s", exc)
    _rs._memory_store.pop(f"pay_{user_id}", None)


# ── MAX payment callback handlers ─────────────────────────────────────────────

async def _handle_payment_callback(
    adapter: MaxAdapter, chat_id: str, user, data: str
) -> bool:
    """Handle all max_pay_* callbacks. Returns True if consumed."""

    # ── Subscription check ────────────────────────────────────────────────────
    if data == "max_pay_sub_check":
        pay_data = await _pay_get(user.platform_user_id)
        if not pay_data or pay_data.get("type") not in ("subscription", None) and "payment_id" not in pay_data:
            # Try to check via FSM state (set in handle_profile)
            fsm = await reg_state.get_state(user.platform_user_id)
            if fsm and fsm.get("state") == "pay:subscription":
                pay_data = fsm.get("data", {})
            else:
                await adapter.send_message(
                    chat_id,
                    "Платёж не найден. Вернись в профиль и начни оплату заново.",
                    get_back_to_menu_rows(),
                )
                return True

        payment_id = pay_data.get("payment_id")
        period = pay_data.get("period", "monthly")
        if not payment_id:
            await adapter.send_message(chat_id, "Платёж не найден.", get_back_to_menu_rows())
            return True

        from src.services.payment import check_payment_status
        status = await check_payment_status(payment_id)
        if status == "succeeded":
            from src.services.subscription import activate_subscription
            ok = await activate_subscription(user.id, period, payment_id)
            await reg_state.clear_state(user.platform_user_id)
            await _pay_clear(user.platform_user_id)
            if ok:
                period_label = "1 месяц" if period == "monthly" else "Сезон"
                await adapter.send_message(
                    chat_id,
                    f"✅ Подписка активирована на {period_label}! Добро пожаловать.",
                    get_main_menu_rows(),
                )
            else:
                await adapter.send_message(
                    chat_id,
                    "Оплата прошла, но подписка не активировалась. Обратись в поддержку.",
                    get_back_to_menu_rows(),
                )
        elif status == "canceled":
            await reg_state.clear_state(user.platform_user_id)
            await _pay_clear(user.platform_user_id)
            await adapter.send_message(chat_id, "❌ Платёж отменён.", get_back_to_menu_rows())
        else:
            await adapter.send_message(
                chat_id,
                "Платёж ещё не обработан. Подожди несколько секунд и нажми «Я оплатил — проверить» снова.",
                [[Button("✅ Я оплатил — проверить", payload="max_pay_sub_check")],
                 [Button("« Назад", payload="menu_main")]],
            )
        return True

    # ── Renew subscription ────────────────────────────────────────────────────
    if data == "max_profile_renew_sub":
        from src.services.admin_service import get_subscription_settings
        from src.services.payment import create_payment

        sub_settings = await get_subscription_settings()
        monthly_price = (sub_settings.monthly_price_kopecks if sub_settings and sub_settings.monthly_price_kopecks else 29900)
        season_price = (sub_settings.season_price_kopecks if sub_settings and sub_settings.season_price_kopecks else 79900)

        monthly_payment = await create_payment(
            amount_kopecks=monthly_price,
            description="Продление подписки на 1 месяц — мото-бот",
            metadata={"type": "subscription", "user_id": str(effective_user_id(user)), "period": "monthly", "platform": "max"},
            return_url="https://max.ru/",
        )
        season_payment = await create_payment(
            amount_kopecks=season_price,
            description="Продление подписки на сезон — мото-бот",
            metadata={"type": "subscription", "user_id": str(effective_user_id(user)), "period": "season", "platform": "max"},
            return_url="https://max.ru/",
        )

        text = (
            "Продление подписки:\n\n"
            f"• 1 месяц — {monthly_price // 100} ₽\n"
            f"• Сезон — {season_price // 100} ₽\n\n"
            "Оплати по ссылке и нажми «Я оплатил — проверить»."
        )
        kb = []
        if monthly_payment and monthly_payment.get("confirmation_url"):
            kb.append([Button(f"💳 1 месяц — {monthly_price // 100} ₽", type=ButtonType.URL, url=monthly_payment["confirmation_url"])])
            await reg_state.set_state(
                user.platform_user_id,
                "pay:subscription",
                {"payment_id": monthly_payment["id"], "period": "monthly"},
            )
        if season_payment and season_payment.get("confirmation_url"):
            kb.append([Button(f"💳 Сезон — {season_price // 100} ₽", type=ButtonType.URL, url=season_payment["confirmation_url"])])
        if kb:
            kb.append([Button("✅ Я оплатил — проверить", payload="max_pay_sub_check")])
        kb.append([Button("« Назад", payload="menu_profile")])
        await adapter.send_message(chat_id, text, kb)
        return True

    # ── Profile raise ─────────────────────────────────────────────────────────
    if data == "max_profile_raise":
        from src.services.admin_service import get_subscription_settings
        from src.services.payment import create_payment
        from src.models.user import UserRole

        sub_settings = await get_subscription_settings()
        if not sub_settings or not sub_settings.raise_profile_enabled:
            await adapter.send_message(chat_id, "Поднятие анкеты сейчас недоступно.", get_back_to_menu_rows())
            return True

        price = sub_settings.raise_profile_price_kopecks or 0
        role = "pilot" if user.role == UserRole.PILOT else "passenger"

        if price <= 0:
            from src.services.motopair_service import raise_profile
            ok = await raise_profile(user.id, role)
            if ok:
                await adapter.send_message(chat_id, "✅ Анкета поднята! Тебя будут видеть выше в поиске.", get_back_to_menu_rows())
            else:
                await adapter.send_message(chat_id, "Ошибка при поднятии анкеты.", get_back_to_menu_rows())
            return True

        payment = await create_payment(
            amount_kopecks=price,
            description="Поднятие анкеты — мото-бот",
            metadata={"type": "raise_profile", "user_id": str(effective_user_id(user)), "role": role, "platform": "max"},
            return_url="https://max.ru/",
        )
        if not payment or not payment.get("confirmation_url"):
            await adapter.send_message(chat_id, "Платёжный сервис временно недоступен. Попробуй позже.", get_back_to_menu_rows())
            return True

        await _pay_set(user.platform_user_id, {
            "type": "raise_profile",
            "payment_id": payment["id"],
            "role": role,
        })
        kb = [
            [Button(f"💳 Оплатить — {price // 100} ₽", type=ButtonType.URL, url=payment["confirmation_url"])],
            [Button("✅ Я оплатил — проверить", payload="max_pay_raise_check")],
            [Button("« Назад", payload="menu_profile")],
        ]
        await adapter.send_message(
            chat_id,
            f"⬆️ Поднятие анкеты — <b>{price // 100} ₽</b>\n\nОплати и нажми «Я оплатил — проверить».",
            kb,
        )
        return True

    # ── Profile raise check ───────────────────────────────────────────────────
    if data == "max_pay_raise_check":
        pay_data = await _pay_get(user.platform_user_id)
        if not pay_data or pay_data.get("type") != "raise_profile":
            await adapter.send_message(chat_id, "Платёж не найден. Начни поднятие анкеты заново.", get_back_to_menu_rows())
            return True

        from src.services.payment import check_payment_status
        from src.services.motopair_service import raise_profile

        payment_id = pay_data.get("payment_id")
        role = pay_data.get("role", "pilot")
        status = await check_payment_status(payment_id)

        if status == "succeeded":
            await _pay_clear(user.platform_user_id)
            ok = await raise_profile(user.id, role)
            if ok:
                await adapter.send_message(chat_id, "✅ Оплата прошла! Анкета поднята — тебя увидят первым.", get_back_to_menu_rows())
            else:
                await adapter.send_message(chat_id, "Оплата прошла, но поднять анкету не удалось. Обратись в поддержку.", get_back_to_menu_rows())
        elif status == "canceled":
            await _pay_clear(user.platform_user_id)
            await adapter.send_message(chat_id, "❌ Платёж отменён.", get_back_to_menu_rows())
        else:
            await adapter.send_message(
                chat_id,
                "Платёж ещё не обработан. Подожди и попробуй снова.",
                [[Button("✅ Я оплатил — проверить", payload="max_pay_raise_check")],
                 [Button("« Назад", payload="menu_profile")]],
            )
        return True

    # ── Donate ────────────────────────────────────────────────────────────────
    if data == "max_donate":
        DONATE_AMOUNTS = [(10000, "100 ₽"), (30000, "300 ₽"), (50000, "500 ₽"), (100000, "1000 ₽")]
        kb = [[Button(label, payload=f"max_donate_amount_{kop}")] for kop, label in DONATE_AMOUNTS]
        kb.append([Button("« Назад", payload="menu_about")])
        await adapter.send_message(chat_id, "❤️ Поддержать проект — выбери сумму:", kb)
        return True

    if data.startswith("max_donate_amount_"):
        amount_str = data.replace("max_donate_amount_", "")
        try:
            amount_kop = int(amount_str)
        except ValueError:
            await adapter.send_message(chat_id, "Ошибка суммы.", get_back_to_menu_rows())
            return True

        from src.services.payment import create_payment
        payment = await create_payment(
            amount_kopecks=amount_kop,
            description="Донат — поддержка бота мото-сообщества",
            metadata={"type": "donate", "user_id": str(effective_user_id(user)), "platform": "max"},
            return_url="https://max.ru/",
        )
        if not payment or not payment.get("confirmation_url"):
            await adapter.send_message(chat_id, "Не удалось создать платёж. Попробуй позже.", get_back_to_menu_rows())
            return True

        kb = [
            [Button(f"💳 Оплатить — {amount_kop // 100} ₽", type=ButtonType.URL, url=payment["confirmation_url"])],
            [Button("« Назад", payload="menu_about")],
        ]
        await adapter.send_message(chat_id, "Спасибо за поддержку! Перейди по ссылке для оплаты:", kb)
        return True

    # ── Event create (MAX) ────────────────────────────────────────────────────
    if data == "max_event_create":
        from src.services.subscription import check_subscription_required
        if await check_subscription_required(user):
            await adapter.send_message(
                chat_id,
                "Для создания мероприятий нужна подписка. Оформи в «Мой профиль».",
                [[Button("👤 Мой профиль", payload="menu_profile")], [Button("« Назад", payload="menu_events")]],
            )
            return True
        if not user.city_id:
            await adapter.send_message(chat_id, "Сначала выбери город в /start.", get_back_to_menu_rows())
            return True
        kb = [
            [Button("Масштабное", payload="max_evcreate_type_large")],
            [Button("Мотопробег", payload="max_evcreate_type_motorcade")],
            [Button("Прохват", payload="max_evcreate_type_run")],
            [Button("« Отмена", payload="menu_events")],
        ]
        await adapter.send_message(chat_id, "Тип мероприятия:", kb)
        return True

    if data.startswith("max_evcreate_type_"):
        ev_type = data.replace("max_evcreate_type_", "")
        if ev_type not in ("large", "motorcade", "run"):
            return True

        from src.services.admin_service import get_subscription_settings
        from src.services.payment import create_payment
        from src.services.event_service import event_creation_payment_required

        sub_settings = await get_subscription_settings()
        needs_payment, price = await event_creation_payment_required(
            user.id, user.platform_user_id, user.city_id, ev_type, sub_settings
        )

        if needs_payment and price and price > 0:
            payment = await create_payment(
                amount_kopecks=price,
                description="Создание мероприятия — мото-бот",
                metadata={"type": "event_creation", "user_id": str(effective_user_id(user)), "event_type": ev_type, "platform": "max"},
                return_url="https://max.ru/",
            )
            if not payment or not payment.get("confirmation_url"):
                await adapter.send_message(chat_id, "Платёжный сервис временно недоступен.", get_back_to_menu_rows())
                return True

            await _pay_set(user.platform_user_id, {
                "type": "event_creation",
                "payment_id": payment["id"],
                "event_type": ev_type,
            })
            kb = [
                [Button(f"💳 Оплатить — {price // 100} ₽", type=ButtonType.URL, url=payment["confirmation_url"])],
                [Button("✅ Я оплатил — проверить", payload="max_pay_event_check")],
                [Button("« Отмена", payload="menu_events")],
            ]
            await adapter.send_message(
                chat_id,
                f"💳 Создание мероприятия платное: <b>{price // 100} ₽</b>\n\nОплати и нажми «Я оплатил — проверить».",
                kb,
            )
            return True

        # No payment needed — start FSM for event creation
        await reg_state.set_state(user.platform_user_id, "event_create:title", {"event_type": ev_type})
        await adapter.send_message(chat_id, "Введи название мероприятия (или «Пропустить»):", _cancel_kb())
        return True

    if data == "max_pay_event_check":
        pay_data = await _pay_get(user.platform_user_id)
        if not pay_data or pay_data.get("type") != "event_creation":
            await adapter.send_message(chat_id, "Платёж не найден. Начни создание мероприятия заново.", get_back_to_menu_rows())
            return True

        from src.services.payment import check_payment_status
        payment_id = pay_data.get("payment_id")
        ev_type = pay_data.get("event_type", "run")
        status = await check_payment_status(payment_id)

        if status == "succeeded":
            await _pay_clear(user.platform_user_id)
            await reg_state.set_state(user.platform_user_id, "event_create:title", {"event_type": ev_type})
            await adapter.send_message(chat_id, "✅ Оплата прошла! Введи название мероприятия (или «Пропустить»):", _cancel_kb())
        elif status == "canceled":
            await _pay_clear(user.platform_user_id)
            await adapter.send_message(chat_id, "❌ Платёж отменён.", get_back_to_menu_rows())
        else:
            await adapter.send_message(
                chat_id,
                "Платёж ещё не обработан. Подожди и попробуй снова.",
                [[Button("✅ Я оплатил — проверить", payload="max_pay_event_check")],
                 [Button("« Отмена", payload="menu_events")]],
            )
        return True

    return False
