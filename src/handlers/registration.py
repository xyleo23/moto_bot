"""Registration and profile filling with FSM."""
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

from src.models.user import UserRole
from src.models.profile_pilot import ProfilePilot, DrivingStyle, Gender
from src.models.profile_passenger import ProfilePassenger, PreferredStyle
from src.models.base import get_session_factory
from src.keyboards.menu import get_main_menu_kb, get_persistent_kb
from src.config import get_settings
from src.utils.progress import progress_prefix
from src import texts

router = Router()

# ── Step counts for progress bar ──────────────────────────────────────────────
PILOT_TOTAL_STEPS = 11      # name, phone, age, gender, brand, model, cc, since, style, photo, about
PASSENGER_TOTAL_STEPS = 9   # name, phone, age, gender, weight, height, style, photo, about


class PilotRegistration(StatesGroup):
    name = State()
    phone = State()
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
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel current FSM flow and return to main menu."""
    current = await state.get_state()
    if current is not None:
        await state.clear()
    await message.answer(
        texts.FSM_CANCEL_TEXT,
        reply_markup=get_main_menu_kb(platform_user_id=message.from_user.id),
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
    await state.set_state(PilotRegistration.age)
    await message.answer(
        progress_prefix(3, PILOT_TOTAL_STEPS) + texts.REG_ASK_AGE,
        reply_markup=ReplyKeyboardRemove(),
    )


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
                    InlineKeyboardButton(text="Другое", callback_data="gender_other"),
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


def _parse_date(text: str):
    """Parse date from various formats. Returns date or None."""
    text = (text or "").strip()
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
                [InlineKeyboardButton(text="Агрессивный", callback_data="style_aggressive")],
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
    style_labels = {"calm": "Спокойный", "aggressive": "Агрессивный", "mixed": "Смешанный"}
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
        except Exception:
            pass
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
        except Exception:
            pass


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
    data = await state.get_data()
    await state.clear()
    pid = platform_user_id or (message.from_user.id if message.from_user else None)
    logger.info("_finish_pilot_registration: platform_user_id=%s data_keys=%s", pid, list(data.keys()))

    session_factory = get_session_factory()
    async with session_factory() as session:
        from sqlalchemy import select
        from src.models.user import User, Platform

        result = await session.execute(
            select(User).where(
                User.platform_user_id == pid,
                User.platform == Platform.TELEGRAM,
            )
        )
        u = result.scalar_one_or_none()
        if not u:
            logger.warning("_finish_pilot_registration: User not found for platform_user_id=%s", pid)
            await message.answer(texts.REG_ERROR_USER_NOT_FOUND)
            return

        gender_map = {"male": Gender.MALE, "female": Gender.FEMALE, "other": Gender.OTHER}
        style_map = {
            "calm": DrivingStyle.CALM,
            "aggressive": DrivingStyle.AGGRESSIVE,
            "mixed": DrivingStyle.MIXED,
        }

        ds = data.get("driving_since")
        if isinstance(ds, str):
            from datetime import datetime as dt_cls
            ds = dt_cls.strptime(ds, "%Y-%m-%d").date()

        phone = str(data.get("phone") or "")[:20]
        if not phone or len(phone) < 5:
            logger.warning("pilot registration: invalid phone %r", data.get("phone"))
            await message.answer(texts.REG_ERROR_SAVE)
            return
        max_about = get_settings().about_text_max_length
        about_clean = (data.get("about") or "")[:max_about] or None

        existing = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == u.id)
        )
        profile = existing.scalar_one_or_none()
        if profile:
            profile.name = data["name"]
            profile.phone = phone
            profile.age = data["age"]
            profile.gender = gender_map.get(str(data["gender"]), Gender.OTHER)
            profile.bike_brand = data["bike_brand"]
            profile.bike_model = data["bike_model"]
            profile.engine_cc = data["engine_cc"]
            profile.driving_since = ds
            profile.driving_style = style_map.get(
                str(data.get("driving_style", "mixed")), DrivingStyle.MIXED
            )
            profile.photo_file_id = data.get("photo_file_id")
            profile.about = about_clean
        else:
            profile = ProfilePilot(
                user_id=u.id,
                name=data["name"],
                phone=phone,
                age=data["age"],
                gender=gender_map.get(str(data["gender"]), Gender.OTHER),
                bike_brand=data["bike_brand"],
                bike_model=data["bike_model"],
                engine_cc=data["engine_cc"],
                driving_since=ds,
                driving_style=style_map.get(
                    str(data.get("driving_style", "mixed")), DrivingStyle.MIXED
                ),
                photo_file_id=data.get("photo_file_id"),
                about=about_clean,
            )
            session.add(profile)
        await session.commit()

    await message.answer(
        texts.REG_DONE,
        reply_markup=get_main_menu_kb(platform_user_id=pid),
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
    await state.set_state(PassengerRegistration.age)
    await message.answer(
        progress_prefix(3, PASSENGER_TOTAL_STEPS) + texts.REG_ASK_AGE,
        reply_markup=ReplyKeyboardRemove(),
    )


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
                    InlineKeyboardButton(text="Другое", callback_data="pax_gender_other"),
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
        except Exception:
            pass
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
        except Exception:
            pass


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
    data = await state.get_data()
    await state.clear()
    pid = platform_user_id or (message.from_user.id if message.from_user else None)
    logger.info("_finish_passenger_registration: platform_user_id=%s data_keys=%s", pid, list(data.keys()))

    from sqlalchemy import select
    from src.models.user import User, Platform
    from src.models.profile_passenger import Gender as PaxGender

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.platform_user_id == pid,
                User.platform == Platform.TELEGRAM,
            )
        )
        u = result.scalar_one_or_none()
        if not u:
            logger.warning("_finish_passenger_registration: User not found for platform_user_id=%s", pid)
            await message.answer(texts.REG_ERROR_USER_NOT_FOUND)
            return

        gender_map = {
            "male": PaxGender.MALE,
            "female": PaxGender.FEMALE,
            "other": PaxGender.OTHER,
        }
        style_map = {
            "calm": PreferredStyle.CALM,
            "dynamic": PreferredStyle.DYNAMIC,
            "mixed": PreferredStyle.MIXED,
        }

        max_about = get_settings().about_text_max_length
        about_clean = (data.get("about") or "")[:max_about] or None

        # Upsert: update existing or create new
        existing = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == u.id)
        )
        profile = existing.scalar_one_or_none()
        phone_str = str(data.get("phone") or "")[:20]
        if not phone_str or len(phone_str) < 5:
            logger.warning("passenger registration: invalid phone %r", data.get("phone"))
            await message.answer(texts.REG_ERROR_SAVE)
            return

        if profile:
            profile.name = data["name"]
            profile.phone = phone_str
            profile.age = data["age"]
            profile.gender = gender_map.get(str(data.get("gender", "other")), PaxGender.OTHER)
            profile.weight = data["weight"]
            profile.height = data["height"]
            profile.preferred_style = style_map.get(
                data.get("preferred_style", "mixed"), PreferredStyle.MIXED
            )
            profile.photo_file_id = data.get("photo_file_id")
            profile.about = about_clean
        else:
            profile = ProfilePassenger(
                user_id=u.id,
                name=data["name"],
                phone=phone_str,
                age=data["age"],
                gender=gender_map.get(str(data.get("gender", "other")), PaxGender.OTHER),
                weight=data["weight"],
                height=data["height"],
                preferred_style=style_map.get(
                    data.get("preferred_style", "mixed"), PreferredStyle.MIXED
                ),
                photo_file_id=data.get("photo_file_id"),
                about=about_clean,
            )
            session.add(profile)
        await session.commit()

    await message.answer(
        texts.REG_DONE,
        reply_markup=get_main_menu_kb(platform_user_id=pid),
    )
