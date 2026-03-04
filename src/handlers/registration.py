"""Registration and profile filling."""
from loguru import logger

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.models.user import UserRole
from src.models.profile_pilot import ProfilePilot, DrivingStyle, Gender
from src.models.profile_passenger import ProfilePassenger, PreferredStyle
from src.models.base import get_session_factory
from src.keyboards.menu import get_main_menu_kb
from src.config import get_settings


router = Router()


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


async def start_registration(message: Message, state: FSMContext, role: UserRole):
    """Start registration flow after role selection."""
    if role == UserRole.PILOT:
        await state.set_state(PilotRegistration.name)
        await message.answer("Введи своё имя или никнейм.\nМы покажем его другим вместе с твоим Telegram-логином.")
    else:
        await state.set_state(PassengerRegistration.name)
        await message.answer("Введи своё имя или никнейм.\nМы покажем его другим вместе с твоим Telegram-логином.")


# Pilot registration
@router.message(PilotRegistration.name, F.text)
async def pilot_name(message: Message, state: FSMContext, user=None):
    await state.update_data(name=message.text.strip())
    await state.set_state(PilotRegistration.phone)
    await message.answer(
        "Теперь отправь свой номер телефона кнопкой ниже.\nВводить номер вручную нельзя — только через Telegram.",
        reply_markup=__import__("aiogram.types", fromlist=["ReplyKeyboardMarkup", "KeyboardButton"]).ReplyKeyboardMarkup(
            keyboard=[
                [__import__("aiogram.types", fromlist=["KeyboardButton"]).KeyboardButton(text="Отправить мой номер", request_contact=True)]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(PilotRegistration.phone, F.contact)
async def pilot_phone(message: Message, state: FSMContext, user=None):
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await state.set_state(PilotRegistration.age)
    await message.answer("Введи свой возраст (число лет):", reply_markup=__import__("aiogram.types", fromlist=["ReplyKeyboardRemove"]).ReplyKeyboardRemove())


@router.message(PilotRegistration.age, F.text)
async def pilot_age(message: Message, state: FSMContext, user=None):
    try:
        age = int(message.text.strip())
        if 18 <= age <= 80:
            await state.update_data(age=age)
            await state.set_state(PilotRegistration.gender)
            await message.answer(
                "Выбери пол:",
                reply_markup=__import__("aiogram.types", fromlist=["InlineKeyboardMarkup", "InlineKeyboardButton"]).InlineKeyboardMarkup(inline_keyboard=[
                    [
                        __import__("aiogram.types", fromlist=["InlineKeyboardButton"]).InlineKeyboardButton(text="Муж", callback_data="gender_male"),
                        __import__("aiogram.types", fromlist=["InlineKeyboardButton"]).InlineKeyboardButton(text="Жен", callback_data="gender_female"),
                        __import__("aiogram.types", fromlist=["InlineKeyboardButton"]).InlineKeyboardButton(text="Другое", callback_data="gender_other"),
                    ]
                ]),
            )
        else:
            await message.answer("Возраст должен быть от 18 до 80 лет.")
    except ValueError:
        await message.answer("Введи число.")


@router.callback_query(F.data.startswith("gender_"), PilotRegistration.gender)
async def pilot_gender(callback: CallbackQuery, state: FSMContext, user=None):
    g = callback.data.replace("gender_", "")
    await state.update_data(gender=g)
    await state.set_state(PilotRegistration.bike_brand)
    await callback.message.edit_text("Введи марку мотоцикла:")
    await callback.answer()


@router.message(PilotRegistration.bike_brand, F.text)
async def pilot_bike_brand(message: Message, state: FSMContext):
    await state.update_data(bike_brand=message.text.strip())
    await state.set_state(PilotRegistration.bike_model)
    await message.answer("Введи модель мотоцикла:")


@router.message(PilotRegistration.bike_model, F.text)
async def pilot_bike_model(message: Message, state: FSMContext):
    await state.update_data(bike_model=message.text.strip())
    await state.set_state(PilotRegistration.engine_cc)
    await message.answer("Введи кубатуру (см³):")


@router.message(PilotRegistration.engine_cc, F.text)
async def pilot_engine_cc(message: Message, state: FSMContext):
    try:
        cc = int(message.text.strip())
        if 50 <= cc <= 3000:
            await state.update_data(engine_cc=cc)
            await state.set_state(PilotRegistration.driving_since)
            await message.answer("Введи дату получения прав или начала вождения (ДД.ММ.ГГГГ):")
        else:
            await message.answer("Укажи разумную кубатуру (50-3000).")
    except ValueError:
        await message.answer("Введи число.")


def _parse_date(text: str):
    """Parse date from various formats. Returns date or None."""
    from datetime import datetime

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
    """Handle date input — text or fallback for non-text."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    if not message.text or not message.text.strip():
        await message.answer("Введи дату текстом в формате ДД.ММ.ГГГГ (например, 26.07.2006):")
        return

    logger.info("pilot_driving_since: user=%s text=%r", message.from_user.id, message.text)
    try:
        raw = message.text.strip()
        dt = _parse_date(raw)
        if dt:
            iso = dt.isoformat()
            await state.update_data(driving_since=iso)
            await state.set_state(PilotRegistration.driving_style)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Спокойный", callback_data="style_calm")],
                [InlineKeyboardButton(text="Агрессивный", callback_data="style_aggressive")],
                [InlineKeyboardButton(text="Смешанный", callback_data="style_mixed")],
            ])
            await message.answer("Выбери стиль вождения:", reply_markup=kb)
        else:
            await message.answer("Формат: ДД.ММ.ГГГГ (например, 15.06.2020). Попробуй ещё раз:")
    except Exception as e:
        logger.exception("pilot_driving_since error: %s", e)
        await message.answer(
            "Не удалось обработать дату. Попробуй ещё раз (например 26.07.2006) или нажми /start для перезапуска.",
        )


@router.callback_query(F.data.startswith("style_"), PilotRegistration.driving_style)
async def pilot_driving_style(callback: CallbackQuery, state: FSMContext):
    await state.update_data(driving_style=callback.data.replace("style_", ""))
    await state.set_state(PilotRegistration.photo)
    await callback.message.edit_text("Отправь своё фото (или нажми «Пропустить»):", reply_markup=__import__("aiogram.types", fromlist=["InlineKeyboardMarkup", "InlineKeyboardButton"]).InlineKeyboardMarkup(inline_keyboard=[
        [__import__("aiogram.types", fromlist=["InlineKeyboardButton"]).InlineKeyboardButton(text="Пропустить", callback_data="skip_photo")],
    ]))
    await callback.answer()


@router.message(PilotRegistration.photo, F.photo)
async def pilot_photo(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=file_id)
    await state.set_state(PilotRegistration.about)
    await message.answer("Напиши о себе (или «Пропустить»):", reply_markup=__import__("aiogram.types", fromlist=["InlineKeyboardMarkup", "InlineKeyboardButton"]).InlineKeyboardMarkup(inline_keyboard=[
        [__import__("aiogram.types", fromlist=["InlineKeyboardButton"]).InlineKeyboardButton(text="Пропустить", callback_data="skip_about")],
    ]))


@router.callback_query(F.data == "skip_photo", PilotRegistration.photo)
async def pilot_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await state.set_state(PilotRegistration.about)
    await callback.message.edit_text("Напиши о себе (или «Пропустить»):", reply_markup=__import__("aiogram.types", fromlist=["InlineKeyboardMarkup", "InlineKeyboardButton"]).InlineKeyboardMarkup(inline_keyboard=[
        [__import__("aiogram.types", fromlist=["InlineKeyboardButton"]).InlineKeyboardButton(text="Пропустить", callback_data="skip_about")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "skip_about", PilotRegistration.about)
async def pilot_skip_about(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    try:
        await _finish_pilot_registration(callback.message, state, user, None)
    except Exception as e:
        logger.exception("_finish_pilot_registration (skip) error: %s", e)
        await callback.message.answer("Ошибка при сохранении. Попробуй /start и пройди регистрацию заново.")


@router.message(PilotRegistration.about)
async def pilot_about(message: Message, state: FSMContext, user=None):
    if not message.text or not message.text.strip():
        await message.answer("Напиши о себе текстом или нажми «Пропустить».")
        return
    about = message.text.strip()
    if about.lower() in ("пропустить", "skip"):
        about = None
    else:
        max_len = get_settings().about_text_max_length
        if len(about) > max_len:
            await message.answer(f"Максимум {max_len} символов.")
            return
    try:
        await _finish_pilot_registration(message, state, user, about)
    except Exception as e:
        logger.exception("_finish_pilot_registration error: %s", e)
        await message.answer("Ошибка при сохранении. Попробуй /start и пройди регистрацию заново.")


async def _finish_pilot_registration(message: Message, state: FSMContext, user, about: str | None):
    data = await state.get_data()
    await state.clear()

    session_factory = get_session_factory()
    async with session_factory() as session:
        from sqlalchemy import select
        from src.models.user import User
        from src.models.user import Platform

        result = await session.execute(
            select(User).where(
                User.platform_user_id == message.from_user.id,
                User.platform == Platform.TELEGRAM,
            )
        )
        u = result.scalar_one_or_none()
        if not u:
            await message.answer("Ошибка: пользователь не найден. Нажми /start")
            return

        gender_map = {"male": Gender.MALE, "female": Gender.FEMALE, "other": Gender.OTHER}
        style_map = {"calm": DrivingStyle.CALM, "aggressive": DrivingStyle.AGGRESSIVE, "mixed": DrivingStyle.MIXED}

        ds = data["driving_since"]
        if isinstance(ds, str):
            from datetime import datetime as dt_cls
            ds = dt_cls.strptime(ds, "%Y-%m-%d").date()

        profile = ProfilePilot(
            user_id=u.id,
            name=data["name"],
            phone=data["phone"],
            age=data["age"],
            gender=gender_map.get(str(data["gender"]), Gender.OTHER),
            bike_brand=data["bike_brand"],
            bike_model=data["bike_model"],
            engine_cc=data["engine_cc"],
            driving_since=ds,
            driving_style=style_map.get(str(data.get("driving_style", "mixed")), DrivingStyle.MIXED),
            photo_file_id=data.get("photo_file_id"),
            about=about,
        )
        session.add(profile)
        await session.commit()

    await message.answer("Анкета заполнена! 🏍", reply_markup=get_main_menu_kb())


# Passenger registration (simplified - similar structure)
@router.message(PassengerRegistration.name, F.text)
async def passenger_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(PassengerRegistration.phone)
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
    await message.answer(
        "Теперь отправь свой номер телефона кнопкой ниже.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(PassengerRegistration.phone, F.contact)
async def passenger_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number or ""
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(phone=phone)
    await state.set_state(PassengerRegistration.age)
    from aiogram.types import ReplyKeyboardRemove
    await message.answer("Введи возраст:", reply_markup=ReplyKeyboardRemove())


@router.message(PassengerRegistration.age, F.text)
async def passenger_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if 18 <= age <= 80:
            await state.update_data(age=age)
            await state.set_state(PassengerRegistration.gender)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            await message.answer(
                "Выбери пол:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Муж", callback_data="pax_gender_male"),
                        InlineKeyboardButton(text="Жен", callback_data="pax_gender_female"),
                        InlineKeyboardButton(text="Другое", callback_data="pax_gender_other"),
                    ]
                ]),
            )
        else:
            await message.answer("Возраст 18-80.")
    except ValueError:
        await message.answer("Введи число.")


@router.callback_query(F.data.startswith("pax_gender_"), PassengerRegistration.gender)
async def passenger_gender(callback: CallbackQuery, state: FSMContext):
    await state.update_data(gender=callback.data.replace("pax_gender_", ""))
    await state.set_state(PassengerRegistration.weight)
    await callback.message.edit_text("Введи вес (кг):")
    await callback.answer()


@router.message(PassengerRegistration.weight, F.text)
async def passenger_weight(message: Message, state: FSMContext):
    try:
        w = int(message.text.strip())
        if 30 <= w <= 200:
            await state.update_data(weight=w)
            await state.set_state(PassengerRegistration.height)
            await message.answer("Введи рост (см):")
        else:
            await message.answer("Укажи разумный вес (30-200).")
    except ValueError:
        await message.answer("Введи число.")


@router.message(PassengerRegistration.height, F.text)
async def passenger_height(message: Message, state: FSMContext):
    try:
        h = int(message.text.strip())
        if 120 <= h <= 220:
            await state.update_data(height=h)
            await state.set_state(PassengerRegistration.preferred_style)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            await message.answer(
                "Желаемый стиль вождения:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Спокойный", callback_data="pax_style_calm")],
                    [InlineKeyboardButton(text="Динамичный", callback_data="pax_style_dynamic")],
                    [InlineKeyboardButton(text="Смешанный", callback_data="pax_style_mixed")],
                ]),
            )
        else:
            await message.answer("Укажи рост 120-220 см.")
    except ValueError:
        await message.answer("Введи число.")


@router.callback_query(F.data.startswith("pax_style_"), PassengerRegistration.preferred_style)
async def passenger_preferred_style(callback: CallbackQuery, state: FSMContext):
    await state.update_data(preferred_style=callback.data.replace("pax_style_", ""))
    await state.set_state(PassengerRegistration.photo)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.edit_text("Отправь фото или «Пропустить»:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="pax_skip_photo")],
    ]))
    await callback.answer()


@router.message(PassengerRegistration.photo, F.photo)
async def passenger_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await state.set_state(PassengerRegistration.about)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer("О себе (или «Пропустить»):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="pax_skip_about")],
    ]))


@router.callback_query(F.data == "pax_skip_photo", PassengerRegistration.photo)
async def passenger_skip_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_file_id=None)
    await state.set_state(PassengerRegistration.about)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await callback.message.edit_text("О себе (или «Пропустить»):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="pax_skip_about")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "pax_skip_about", PassengerRegistration.about)
async def passenger_skip_about_cb(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    try:
        await _finish_passenger_registration(callback.message, state, user, None)
    except Exception as e:
        logger.exception("_finish_passenger_registration (skip) error: %s", e)
        await callback.message.answer("Ошибка при сохранении. Попробуй /start и пройди регистрацию заново.")


@router.message(PassengerRegistration.about)
async def passenger_about(message: Message, state: FSMContext, user=None):
    if not message.text or not message.text.strip():
        await message.answer("Напиши о себе текстом или нажми «Пропустить».")
        return
    about = message.text.strip()
    if about.lower() in ("пропустить", "skip"):
        about = None
    else:
        if len(about) > get_settings().about_text_max_length:
            await message.answer(f"Максимум {get_settings().about_text_max_length} символов.")
            return
    try:
        await _finish_passenger_registration(message, state, user, about)
    except Exception as e:
        logger.exception("_finish_passenger_registration error: %s", e)
        await message.answer("Ошибка при сохранении. Попробуй /start и пройди регистрацию заново.")


async def _finish_passenger_registration(message: Message, state: FSMContext, user, about: str | None):
    data = await state.get_data()
    await state.clear()

    from sqlalchemy import select
    from src.models.user import User, Platform

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.platform_user_id == message.from_user.id,
                User.platform == Platform.TELEGRAM,
            )
        )
        u = result.scalar_one_or_none()
        if not u:
            await message.answer("Ошибка. Нажми /start")
            return

        gender_map = {"male": __import__("src.models.profile_passenger", fromlist=["Gender"]).Gender.MALE, "female": __import__("src.models.profile_passenger", fromlist=["Gender"]).Gender.FEMALE, "other": __import__("src.models.profile_passenger", fromlist=["Gender"]).Gender.OTHER}
        style_map = {"calm": PreferredStyle.CALM, "dynamic": PreferredStyle.DYNAMIC, "mixed": PreferredStyle.MIXED}

        profile = ProfilePassenger(
            user_id=u.id,
            name=data["name"],
            phone=data["phone"],
            age=data["age"],
            gender=gender_map.get(data["gender"], __import__("src.models.profile_passenger", fromlist=["Gender"]).Gender.OTHER),
            weight=data["weight"],
            height=data["height"],
            preferred_style=style_map.get(data["preferred_style"], PreferredStyle.MIXED),
            photo_file_id=data.get("photo_file_id"),
            about=about,
        )
        session.add(profile)
        await session.commit()

    await message.answer("Анкета заполнена! 🏍", reply_markup=get_main_menu_kb())
