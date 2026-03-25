"""Registration and profile filling with FSM."""
import uuid
from datetime import datetime

from loguru import logger
from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from src.models.user import UserRole, Platform
from src.services.registration_service import (
    MaxCrossLinkKind,
    apply_telegram_early_account_link,
    check_cross_platform_registration_link,
    mask_registration_phone_hint,
    user_role_display_ru,
)
from src.services.user import get_or_create_user
from src.keyboards.menu import get_main_menu_kb_for_user, get_reply_keyboard_for_user
from src.config import get_settings
from src.utils.progress import progress_prefix
from src import texts

router = Router()


def _strip_tg_cross_link_keys(data: dict) -> dict:
    return {k: v for k, v in data.items() if not str(k).startswith("cross_link_")}


async def _advance_telegram_reg_past_phone(
    message: Message,
    state: FSMContext,
    *,
    data: dict,
    is_pilot: bool,
) -> None:
    clean = _strip_tg_cross_link_keys(dict(data))
    await state.set_data(clean)
    if is_pilot:
        await state.set_state(PilotRegistration.age)
        await message.answer(
            progress_prefix(3, PILOT_TOTAL_STEPS) + texts.REG_ASK_AGE,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await state.set_state(PassengerRegistration.age)
        await message.answer(
            progress_prefix(3, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_AGE,
            reply_markup=ReplyKeyboardRemove(),
        )


async def _process_telegram_reg_after_phone(
    message: Message,
    state: FSMContext,
    *,
    is_pilot: bool,
) -> None:
    data = await state.get_data()
    phone = str(data.get("phone") or "")
    role = UserRole.PILOT if is_pilot else UserRole.PASSENGER
    chk = await check_cross_platform_registration_link(
        phone,
        platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
        registering_as=role,
    )
    if chk.kind == MaxCrossLinkKind.NONE:
        await _advance_telegram_reg_past_phone(
            message, state, data=data, is_pilot=is_pilot
        )
        return
    if chk.kind == MaxCrossLinkKind.ROLE_MISMATCH:
        clean = _strip_tg_cross_link_keys(dict(data))
        clean.pop("phone", None)
        await state.set_data(clean)
        await state.set_state(
            PilotRegistration.phone if is_pilot else PassengerRegistration.phone
        )
        await message.answer(
            texts.REG_CROSS_LINK_ROLE_MISMATCH.format(
                platform=chk.platform_label,
                existing_role=user_role_display_ru(chk.existing_role),
                registering_role=user_role_display_ru(role),
            ),
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        return
    assert chk.canonical_user_id is not None
    await state.update_data(
        cross_link_canonical_id=str(chk.canonical_user_id),
        cross_link_display_name=chk.display_name,
        cross_link_platform_label=chk.platform_label,
        cross_link_is_pilot=is_pilot,
    )
    await state.set_state(
        PilotRegistration.cross_link_confirm
        if is_pilot
        else PassengerRegistration.cross_link_confirm
    )
    phone_masked = mask_registration_phone_hint(phone)
    await message.answer(
        texts.REG_CROSS_LINK_ASK.format(
            phone_masked=phone_masked,
            platform=chk.platform_label,
            name=chk.display_name,
            role_label=user_role_display_ru(chk.existing_role),
        ),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Подтверди:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да, это я",
                        callback_data="tg_reg_cross_link_yes",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Нет, продолжить регистрацию",
                        callback_data="tg_reg_cross_link_no",
                    ),
                ],
            ],
        ),
    )


# ── Step counts for progress bar ──────────────────────────────────────────────
PILOT_TOTAL_STEPS = 11      # name, phone, age, gender, brand, model, cc, since, style, photo, about
PASSENGER_TOTAL_STEPS = 9   # name, phone, age, gender, weight, height, style, photo, about


class PilotRegistration(StatesGroup):
    name = State()
    phone = State()
    cross_link_confirm = State()
    age = State()
    gender = State()
    bike_brand = State()
    bike_model = State()
    engine_cc = State()
    driving_since = State()
    driving_style = State()
    photo = State()
    about = State()
    # Preview before saving
    preview = State()


class PassengerRegistration(StatesGroup):
    name = State()
    phone = State()
    cross_link_confirm = State()
    age = State()
    gender = State()
    weight = State()
    height = State()
    preferred_style = State()
    photo = State()
    about = State()
    # Preview before saving
    preview = State()


# ── /cancel handler — works in any FSM state ─────────────────────────────────

@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext, user=None):
    """Cancel current FSM flow and return to main menu."""
    current = await state.get_state()
    if current is not None:
        await state.clear()
    await message.answer(
        texts.FSM_CANCEL_TEXT,
        reply_markup=await get_reply_keyboard_for_user(message.from_user.id, user),
    )
    await message.answer(
        "Меню:",
        reply_markup=await get_main_menu_kb_for_user(message.from_user.id, user),
    )


# ── Entry point called from start.py ──────────────────────────────────────────

async def start_registration(message: Message, state: FSMContext, role: UserRole):
    """Start registration flow after role selection."""
    if role == UserRole.PILOT:
        await state.set_state(PilotRegistration.name)
        await message.answer(
            progress_prefix(1, PILOT_TOTAL_STEPS) + texts.REG_ASK_NAME
        )
    else:
        await state.set_state(PassengerRegistration.name)
        await message.answer(
            progress_prefix(1, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_NAME
        )


# ─────────────────────────────────────────────────────────────────────────────
# PILOT REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

@router.message(PilotRegistration.name, F.text)
async def pilot_name(message: Message, state: FSMContext, user=None):
    await state.update_data(name=message.text.strip())
    await state.set_state(PilotRegistration.phone)
    await message.answer(
        progress_prefix(2, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHONE,
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(PilotRegistration.name)
async def pilot_name_fallback(message: Message, state: FSMContext):
    await message.answer("Введи имя текстом.")


@router.message(PilotRegistration.phone, F.contact)
async def pilot_phone(message: Message, state: FSMContext, user=None):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await _process_telegram_reg_after_phone(message, state, is_pilot=True)


@router.message(PilotRegistration.phone)
async def pilot_phone_fallback(message: Message, state: FSMContext):
    await message.answer(
        "Нажми кнопку «Отправить мой номер» для передачи контакта.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.callback_query(
    F.data == "tg_reg_cross_link_yes",
    StateFilter(PilotRegistration.cross_link_confirm, PassengerRegistration.cross_link_confirm),
)
async def tg_reg_cross_link_yes(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    data = await state.get_data()
    raw = data.get("cross_link_canonical_id")
    try:
        canon = uuid.UUID(str(raw))
    except (ValueError, TypeError):
        await state.clear()
        await callback.message.answer(texts.REG_ERROR_SAVE)
        return
    pid = callback.from_user.id
    err = await apply_telegram_early_account_link(pid, canon)
    await state.clear()
    if err:
        logger.warning("tg_reg_cross_link_yes: apply failed uid=%s err=%s", pid, err)
        await callback.message.answer(texts.REG_ERROR_SAVE)
        return
    u = await get_or_create_user(
        platform="telegram",
        platform_user_id=pid,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
    )
    try:
        await callback.message.edit_text(texts.REG_CROSS_LINK_SUCCESS, parse_mode="HTML")
    except Exception as e:
        logger.warning("tg_reg_cross_link_yes: edit_text failed: %s", e)
        await callback.message.answer(texts.REG_CROSS_LINK_SUCCESS, parse_mode="HTML")
    await callback.message.answer(
        "✅",
        reply_markup=await get_reply_keyboard_for_user(pid, u),
    )
    await callback.message.answer(
        "Меню:",
        reply_markup=await get_main_menu_kb_for_user(pid, u),
    )


@router.callback_query(
    F.data == "tg_reg_cross_link_no",
    StateFilter(PilotRegistration.cross_link_confirm, PassengerRegistration.cross_link_confirm),
)
async def tg_reg_cross_link_no(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    data = await state.get_data()
    is_pilot = bool(data.get("cross_link_is_pilot", True))
    clean = _strip_tg_cross_link_keys(dict(data))
    await state.set_data(clean)
    try:
        await callback.message.edit_text("Хорошо, продолжим анкету.")
    except Exception as e:
        logger.warning("tg_reg_cross_link_no: edit failed: %s", e)
    await _advance_telegram_reg_past_phone(
        callback.message,
        state,
        data=clean,
        is_pilot=is_pilot,
    )


@router.message(PilotRegistration.age, F.text)
async def pilot_age(message: Message, state: FSMContext, user=None):
    try:
        age = int(message.text.strip())
        if 18 <= age <= 80:
            await state.update_data(age=age)
            await state.set_state(PilotRegistration.gender)
            await message.answer(
                progress_prefix(4, PILOT_TOTAL_STEPS) + texts.REG_ASK_GENDER,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Муж", callback_data="gender_male"),
                    InlineKeyboardButton(text="Жен", callback_data="gender_female"),
                ]]),
            )
        else:
            await message.answer(texts.REG_ERROR_AGE)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.message(PilotRegistration.age)
async def pilot_age_fallback(message: Message, state: FSMContext):
    await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data.startswith("gender_"), PilotRegistration.gender)
async def pilot_gender(callback: CallbackQuery, state: FSMContext, user=None):
    g = callback.data.replace("gender_", "")
    await state.update_data(gender=g)
    await state.set_state(PilotRegistration.bike_brand)
    await callback.message.edit_text(
        progress_prefix(5, PILOT_TOTAL_STEPS) + texts.REG_ASK_BIKE_BRAND
    )
    await callback.answer()


@router.message(PilotRegistration.bike_brand, F.text)
async def pilot_bike_brand(message: Message, state: FSMContext):
    await state.update_data(bike_brand=message.text.strip())
    await state.set_state(PilotRegistration.bike_model)
    await message.answer(progress_prefix(6, PILOT_TOTAL_STEPS) + texts.REG_ASK_BIKE_MODEL)


@router.message(PilotRegistration.bike_brand)
async def pilot_bike_brand_fallback(message: Message, state: FSMContext):
    await message.answer("Введи марку мотоцикла текстом.")


@router.message(PilotRegistration.bike_model, F.text)
async def pilot_bike_model(message: Message, state: FSMContext):
    await state.update_data(bike_model=message.text.strip())
    await state.set_state(PilotRegistration.engine_cc)
    await message.answer(progress_prefix(7, PILOT_TOTAL_STEPS) + texts.REG_ASK_ENGINE_CC)


@router.message(PilotRegistration.bike_model)
async def pilot_bike_model_fallback(message: Message, state: FSMContext):
    await message.answer("Введи модель мотоцикла текстом.")


@router.message(PilotRegistration.engine_cc, F.text)
async def pilot_engine_cc(message: Message, state: FSMContext):
    try:
        cc = int(message.text.strip())
        if 50 <= cc <= 3000:
            await state.update_data(engine_cc=cc)
            await state.set_state(PilotRegistration.driving_since)
            await message.answer(
                progress_prefix(8, PILOT_TOTAL_STEPS) + texts.REG_ASK_DRIVING_SINCE
            )
        else:
            await message.answer(texts.REG_ERROR_ENGINE_CC)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.message(PilotRegistration.engine_cc)
async def pilot_engine_cc_fallback(message: Message, state: FSMContext):
    await message.answer(texts.REG_ERROR_NOT_NUMBER)


RUSSIAN_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


def _parse_russian_date(text: str):
    """Parse date in format 'DD месяц YYYY' (e.g. '26 июня 2006'). Returns date or None."""
    import re
    text = (text or "").strip()
    # Match: число (1-31) + месяц + год (4 digits)
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
    """Parse date from year, month/year, or full date. Returns date or None."""
    import re
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
    # Полная дата (для совместимости)
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
    parsed = _parse_russian_date(text)
    if parsed:
        return parsed
    return None


@router.message(PilotRegistration.driving_since)
async def pilot_driving_since(message: Message, state: FSMContext):
    if not message.text or not message.text.strip():
        await message.answer(texts.REG_ERROR_DATE_FORMAT)
        return

    logger.info("pilot_driving_since: user=%s text=%r", message.from_user.id, message.text)
    try:
        dt = _parse_date(message.text.strip())
        if dt:
            await state.update_data(driving_since=dt.isoformat())
            await state.set_state(PilotRegistration.driving_style)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Спокойный", callback_data="style_calm")],
                [InlineKeyboardButton(text="Динамичный", callback_data="style_aggressive")],
                [InlineKeyboardButton(text="Смешанный", callback_data="style_mixed")],
            ])
            await message.answer(
                progress_prefix(9, PILOT_TOTAL_STEPS) + texts.REG_ASK_STYLE,
                reply_markup=kb,
            )
        else:
            await message.answer(texts.REG_ERROR_DATE_FORMAT)
    except Exception as e:
        logger.exception("pilot_driving_since error: %s", e)
        await message.answer(texts.REG_ERROR_DATE_FORMAT)


@router.callback_query(F.data.startswith("style_"), PilotRegistration.driving_style)
async def pilot_driving_style(callback: CallbackQuery, state: FSMContext):
    await state.update_data(driving_style=callback.data.replace("style_", ""))
    await state.set_state(PilotRegistration.photo)
    await callback.message.edit_text(
        progress_prefix(10, PILOT_TOTAL_STEPS) + texts.REG_ASK_PHOTO,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="skip_photo")],
        ]),
    )
    await callback.answer()


@router.message(PilotRegistration.photo, F.photo)
async def pilot_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=file_id)
    await state.set_state(PilotRegistration.about)
    await message.answer(
        progress_prefix(11, PILOT_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="skip_about")],
        ]),
    )


@router.message(PilotRegistration.photo)
async def pilot_photo_fallback(message: Message, state: FSMContext):
    await message.answer(
        "Отправь фото или нажми «Пропустить».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="skip_photo")],
        ]),
    )


@router.callback_query(F.data == "skip_photo", PilotRegistration.photo)
async def pilot_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await state.set_state(PilotRegistration.about)
    await callback.message.edit_text(
        progress_prefix(11, PILOT_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="skip_about")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "skip_about", PilotRegistration.about)
async def pilot_skip_about(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    await state.update_data(about=None)
    await state.set_state(PilotRegistration.preview)
    await _show_pilot_preview(callback.message, state)


@router.message(PilotRegistration.about, F.text)
async def pilot_about(message: Message, state: FSMContext, user=None):
    about = message.text.strip()
    if about.lower() in ("пропустить", "skip"):
        about = None
    else:
        max_len = get_settings().about_text_max_length
        if len(about) > max_len:
            await message.answer(texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len))
            return
    await state.update_data(about=about)
    await state.set_state(PilotRegistration.preview)
    await _show_pilot_preview(message, state)


@router.message(PilotRegistration.about)
async def pilot_about_fallback(message: Message, state: FSMContext):
    await message.answer(
        texts.REG_ERROR_NOT_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="skip_about")],
        ]),
    )


async def _show_pilot_preview(message: Message, state: FSMContext):
    """Show profile preview card before saving."""
    data = await state.get_data()
    style_labels = {"calm": "Спокойный", "aggressive": "Динамичный", "mixed": "Смешанный"}
    gender_labels = {"male": "Муж", "female": "Жен", "other": "Другое"}

    text = (
        texts.PROFILE_PREVIEW_HEADER
        + f"🏍 <b>{data.get('name')}</b>\n"
        + f"Возраст: {data.get('age')} лет\n"
        + f"Пол: {gender_labels.get(str(data.get('gender', '')), '—')}\n"
        + f"Мотоцикл: {data.get('bike_brand')} {data.get('bike_model')}, {data.get('engine_cc')} см³\n"
        + f"Стиль: {style_labels.get(str(data.get('driving_style', '')), '—')}\n"
        + f"О себе: {data.get('about') or '—'}\n\n"
        + texts.PROFILE_PREVIEW_CONFIRM
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.PROFILE_BTN_SAVE, callback_data="pilot_preview_save")],
        [InlineKeyboardButton(text=texts.PROFILE_BTN_EDIT, callback_data="pilot_preview_edit")],
    ])
    if data.get("photo_file_id"):
        try:
            await message.answer_photo(
                photo=data["photo_file_id"],
                caption=text,
                reply_markup=kb,
            )
            return
        except Exception as e:
            logger.warning("pilot_preview_show: answer_photo failed, falling back to text: %s", e)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "pilot_preview_save", PilotRegistration.preview)
async def pilot_preview_save(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    try:
        await _finish_pilot_registration(callback.message, state, user, platform_user_id=callback.from_user.id)
    except Exception as e:
        logger.exception("_finish_pilot_registration error: %s", e)
        try:
            await callback.message.answer(texts.REG_ERROR_SAVE)
        except Exception as e2:
            logger.debug("pilot_preview_save: failed to deliver REG_ERROR_SAVE to user: %s", e2)


@router.callback_query(F.data == "pilot_preview_edit", PilotRegistration.preview)
async def pilot_preview_edit(callback: CallbackQuery, state: FSMContext):
    """Restart pilot registration from name step."""
    await callback.answer()
    await state.clear()
    await state.set_state(PilotRegistration.name)
    await callback.message.answer(
        progress_prefix(1, PILOT_TOTAL_STEPS) + texts.REG_ASK_NAME
    )


async def _finish_pilot_registration(
    message: Message, state: FSMContext, user, *, platform_user_id: int | None = None
):
    """Finish pilot registration. platform_user_id обязателен при вызове из callback (message.from_user = бот)."""
    from src.services.registration_service import finish_pilot_registration as _finish_pilot
    from src.models.user import Platform
    from src.keyboards.menu import get_main_menu_kb_for_user
    from src.services.user import get_or_create_user as _get_user

    data = await state.get_data()
    await state.clear()
    pid = platform_user_id or (message.from_user.id if message.from_user else None)
    logger.info("_finish_pilot_registration: platform_user_id=%s data_keys=%s", pid, list(data.keys()))

    if not pid:
        await message.answer(texts.REG_ERROR_SAVE)
        return

    err = await _finish_pilot(Platform.TELEGRAM, pid, data)
    if err == "user_not_found":
        await message.answer(texts.REG_ERROR_USER_NOT_FOUND)
        return
    if err:
        await message.answer(texts.REG_ERROR_SAVE)
        return

    _u = await _get_user(platform="telegram", platform_user_id=pid)
    await message.answer(
        "✅",
        reply_markup=await get_reply_keyboard_for_user(pid, _u),
    )
    await message.answer(
        texts.REG_DONE,
        reply_markup=await get_main_menu_kb_for_user(pid, _u),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PASSENGER REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

@router.message(PassengerRegistration.name, F.text)
async def passenger_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(PassengerRegistration.phone)
    await message.answer(
        progress_prefix(2, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHONE,
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(PassengerRegistration.name)
async def passenger_name_fallback(message: Message, state: FSMContext):
    await message.answer("Введи имя текстом.")


@router.message(PassengerRegistration.phone, F.contact)
async def passenger_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number or ""
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await _process_telegram_reg_after_phone(message, state, is_pilot=False)


@router.message(PassengerRegistration.phone)
async def passenger_phone_fallback(message: Message, state: FSMContext):
    await message.answer(
        "Нажми кнопку «Отправить мой номер».",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(PassengerRegistration.age, F.text)
async def passenger_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if 18 <= age <= 80:
            await state.update_data(age=age)
            await state.set_state(PassengerRegistration.gender)
            await message.answer(
                progress_prefix(4, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_GENDER,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Муж", callback_data="pax_gender_male"),
                    InlineKeyboardButton(text="Жен", callback_data="pax_gender_female"),
                ]]),
            )
        else:
            await message.answer(texts.REG_ERROR_AGE)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.message(PassengerRegistration.age)
async def passenger_age_fallback(message: Message, state: FSMContext):
    await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data.startswith("pax_gender_"), PassengerRegistration.gender)
async def passenger_gender(callback: CallbackQuery, state: FSMContext):
    await state.update_data(gender=callback.data.replace("pax_gender_", ""))
    await state.set_state(PassengerRegistration.weight)
    await callback.message.edit_text(
        progress_prefix(5, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_WEIGHT
    )
    await callback.answer()


@router.message(PassengerRegistration.weight, F.text)
async def passenger_weight(message: Message, state: FSMContext):
    try:
        w = int(message.text.strip())
        if 30 <= w <= 200:
            await state.update_data(weight=w)
            await state.set_state(PassengerRegistration.height)
            await message.answer(
                progress_prefix(6, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_HEIGHT
            )
        else:
            await message.answer(texts.REG_ERROR_WEIGHT)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.message(PassengerRegistration.weight)
async def passenger_weight_fallback(message: Message, state: FSMContext):
    await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.message(PassengerRegistration.height, F.text)
async def passenger_height(message: Message, state: FSMContext):
    try:
        h = int(message.text.strip())
        if 120 <= h <= 220:
            await state.update_data(height=h)
            await state.set_state(PassengerRegistration.preferred_style)
            await message.answer(
                progress_prefix(7, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PREFERRED_STYLE,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Спокойный", callback_data="pax_style_calm")],
                    [InlineKeyboardButton(text="Динамичный", callback_data="pax_style_dynamic")],
                    [InlineKeyboardButton(text="Смешанный", callback_data="pax_style_mixed")],
                ]),
            )
        else:
            await message.answer(texts.REG_ERROR_HEIGHT)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.message(PassengerRegistration.height)
async def passenger_height_fallback(message: Message, state: FSMContext):
    await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data.startswith("pax_style_"), PassengerRegistration.preferred_style)
async def passenger_preferred_style(callback: CallbackQuery, state: FSMContext):
    await state.update_data(preferred_style=callback.data.replace("pax_style_", ""))
    await state.set_state(PassengerRegistration.photo)
    await callback.message.edit_text(
        progress_prefix(8, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_PHOTO,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="pax_skip_photo")],
        ]),
    )
    await callback.answer()


@router.message(PassengerRegistration.photo, F.photo)
async def passenger_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await state.set_state(PassengerRegistration.about)
    await message.answer(
        progress_prefix(9, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="pax_skip_about")],
        ]),
    )


@router.message(PassengerRegistration.photo)
async def passenger_photo_fallback(message: Message, state: FSMContext):
    await message.answer(
        "Отправь фото или нажми «Пропустить».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="pax_skip_photo")],
        ]),
    )


@router.callback_query(F.data == "pax_skip_photo", PassengerRegistration.photo)
async def passenger_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await state.set_state(PassengerRegistration.about)
    await callback.message.edit_text(
        progress_prefix(9, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_ABOUT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="pax_skip_about")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "pax_skip_about", PassengerRegistration.about)
async def passenger_skip_about_cb(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    await state.update_data(about=None)
    await state.set_state(PassengerRegistration.preview)
    await _show_passenger_preview(callback.message, state)


@router.message(PassengerRegistration.about, F.text)
async def passenger_about(message: Message, state: FSMContext, user=None):
    about = message.text.strip()
    if about.lower() in ("пропустить", "skip"):
        about = None
    else:
        max_len = get_settings().about_text_max_length
        if len(about) > max_len:
            await message.answer(texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len))
            return
    await state.update_data(about=about)
    await state.set_state(PassengerRegistration.preview)
    await _show_passenger_preview(message, state)


@router.message(PassengerRegistration.about)
async def passenger_about_fallback(message: Message, state: FSMContext):
    await message.answer(
        texts.REG_ERROR_NOT_TEXT,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="pax_skip_about")],
        ]),
    )


async def _show_passenger_preview(message: Message, state: FSMContext):
    """Show passenger profile preview card before saving."""
    data = await state.get_data()
    style_labels = {"calm": "Спокойный", "dynamic": "Динамичный", "mixed": "Смешанный"}
    gender_labels = {"male": "Муж", "female": "Жен", "other": "Другое"}

    text = (
        texts.PROFILE_PREVIEW_HEADER
        + f"👤 <b>{data.get('name')}</b>\n"
        + f"Возраст: {data.get('age')} лет\n"
        + f"Пол: {gender_labels.get(str(data.get('gender', '')), '—')}\n"
        + f"Вес: {data.get('weight')} кг, Рост: {data.get('height')} см\n"
        + f"Стиль: {style_labels.get(str(data.get('preferred_style', '')), '—')}\n"
        + f"О себе: {data.get('about') or '—'}\n\n"
        + texts.PROFILE_PREVIEW_CONFIRM
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.PROFILE_BTN_SAVE, callback_data="pax_preview_save")],
        [InlineKeyboardButton(text=texts.PROFILE_BTN_EDIT, callback_data="pax_preview_edit")],
    ])
    if data.get("photo_file_id"):
        try:
            await message.answer_photo(
                photo=data["photo_file_id"],
                caption=text,
                reply_markup=kb,
            )
            return
        except Exception as e:
            logger.warning("passenger_preview_show: answer_photo failed, falling back to text: %s", e)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "pax_preview_save", PassengerRegistration.preview)
async def passenger_preview_save(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    try:
        await _finish_passenger_registration(callback.message, state, user, platform_user_id=callback.from_user.id)
    except Exception as e:
        logger.exception("_finish_passenger_registration error: %s", e)
        try:
            await callback.message.answer(texts.REG_ERROR_SAVE)
        except Exception as e2:
            logger.debug("passenger_preview_save: failed to deliver REG_ERROR_SAVE to user: %s", e2)


@router.callback_query(F.data == "pax_preview_edit", PassengerRegistration.preview)
async def passenger_preview_edit(callback: CallbackQuery, state: FSMContext):
    """Restart passenger registration from name step."""
    await callback.answer()
    await state.clear()
    await state.set_state(PassengerRegistration.name)
    await callback.message.answer(
        progress_prefix(1, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_NAME
    )


async def _finish_passenger_registration(
    message: Message, state: FSMContext, user, *, platform_user_id: int | None = None
):
    """Finish passenger registration. platform_user_id обязателен при вызове из callback (message.from_user = бот)."""
    from src.services.registration_service import finish_passenger_registration as _finish_pax
    from src.models.user import Platform
    from src.keyboards.menu import get_main_menu_kb_for_user
    from src.services.user import get_or_create_user as _get_user

    data = await state.get_data()
    await state.clear()
    pid = platform_user_id or (message.from_user.id if message.from_user else None)
    logger.info("_finish_passenger_registration: platform_user_id=%s data_keys=%s", pid, list(data.keys()))

    if not pid:
        await message.answer(texts.REG_ERROR_SAVE)
        return

    err = await _finish_pax(Platform.TELEGRAM, pid, data)
    if err == "user_not_found":
        await message.answer(texts.REG_ERROR_USER_NOT_FOUND)
        return
    if err:
        await message.answer(texts.REG_ERROR_SAVE)
        return

    _u = await _get_user(platform="telegram", platform_user_id=pid)
    await message.answer(
        "✅",
        reply_markup=await get_reply_keyboard_for_user(pid, _u),
    )
    await message.answer(
        texts.REG_DONE,
        reply_markup=await get_main_menu_kb_for_user(pid, _u),
    )
