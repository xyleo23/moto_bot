"""Profile editing FSM — allows users to update their existing pilot/passenger profile."""
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
from src.keyboards.menu import get_main_menu_kb, get_back_to_menu_kb
from src.config import get_settings
from src import texts

router = Router()

_SKIP = "—  (оставить без изменений)"
_SKIP_CB = "edit_skip_field"


# ─────────────────────────────────────────────────────────────────────────────
# FSM States
# ─────────────────────────────────────────────────────────────────────────────

class PilotEdit(StatesGroup):
    name = State()
    age = State()
    bike_brand = State()
    bike_model = State()
    engine_cc = State()
    driving_style = State()
    photo = State()
    about = State()


class PassengerEdit(StatesGroup):
    name = State()
    age = State()
    weight = State()
    height = State()
    preferred_style = State()
    photo = State()
    about = State()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "profile_edit")
async def cb_profile_edit_start(callback: CallbackQuery, state: FSMContext, user=None):
    """Begin profile edit flow. Pre-fills FSM data with existing profile values."""
    from sqlalchemy import select

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        if user.role == UserRole.PILOT:
            r = await session.execute(
                select(ProfilePilot).where(ProfilePilot.user_id == user.id)
            )
            p = r.scalar_one_or_none()
            if not p:
                await callback.answer("Анкета не найдена. Пройди регистрацию.", show_alert=True)
                return
            # Pre-fill FSM with current values
            await state.set_state(PilotEdit.name)
            await state.update_data(
                edit_mode=True,
                name=p.name,
                age=p.age,
                bike_brand=p.bike_brand,
                bike_model=p.bike_model,
                engine_cc=p.engine_cc,
                driving_style=p.driving_style.value if p.driving_style else "mixed",
                photo_file_id=p.photo_file_id,
                about=p.about,
            )
            await callback.message.edit_text(
                f"✏️ Редактирование анкеты\n\n"
                f"Текущее имя: <b>{p.name}</b>\n"
                f"Введи новое или нажми «Пропустить»:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
                ]),
            )
        else:
            r = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == user.id)
            )
            p = r.scalar_one_or_none()
            if not p:
                await callback.answer("Анкета не найдена. Пройди регистрацию.", show_alert=True)
                return
            await state.set_state(PassengerEdit.name)
            await state.update_data(
                edit_mode=True,
                name=p.name,
                age=p.age,
                weight=p.weight,
                height=p.height,
                preferred_style=p.preferred_style.value if p.preferred_style else "calm",
                photo_file_id=p.photo_file_id,
                about=p.about,
            )
            await callback.message.edit_text(
                f"✏️ Редактирование анкеты\n\n"
                f"Текущее имя: <b>{p.name}</b>\n"
                f"Введи новое или нажми «Пропустить»:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
                ]),
            )
    await callback.answer()


# ─────────────────────────────────────────────────────────────────────────────
# PILOT EDIT
# ─────────────────────────────────────────────────────────────────────────────

@router.message(PilotEdit.name, F.text)
async def pilot_edit_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await _pilot_edit_ask_age(message, state)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.name)
async def pilot_edit_name_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_age(callback.message, state)


async def _pilot_edit_ask_age(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PilotEdit.age)
    await message.answer(
        f"Текущий возраст: <b>{data.get('age')}</b>\nВведи новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PilotEdit.age, F.text)
async def pilot_edit_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if 18 <= age <= 80:
            await state.update_data(age=age)
            await _pilot_edit_ask_brand(message, state)
        else:
            await message.answer(texts.REG_ERROR_AGE)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.age)
async def pilot_edit_age_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_brand(callback.message, state)


async def _pilot_edit_ask_brand(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PilotEdit.bike_brand)
    await message.answer(
        f"Текущая марка: <b>{data.get('bike_brand')}</b>\nВведи новую или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PilotEdit.bike_brand, F.text)
async def pilot_edit_brand(message: Message, state: FSMContext):
    await state.update_data(bike_brand=message.text.strip())
    await _pilot_edit_ask_model(message, state)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.bike_brand)
async def pilot_edit_brand_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_model(callback.message, state)


async def _pilot_edit_ask_model(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PilotEdit.bike_model)
    await message.answer(
        f"Текущая модель: <b>{data.get('bike_model')}</b>\nВведи новую или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PilotEdit.bike_model, F.text)
async def pilot_edit_model(message: Message, state: FSMContext):
    await state.update_data(bike_model=message.text.strip())
    await _pilot_edit_ask_cc(message, state)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.bike_model)
async def pilot_edit_model_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_cc(callback.message, state)


async def _pilot_edit_ask_cc(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PilotEdit.engine_cc)
    await message.answer(
        f"Текущий объём: <b>{data.get('engine_cc')} см³</b>\nВведи новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PilotEdit.engine_cc, F.text)
async def pilot_edit_cc(message: Message, state: FSMContext):
    try:
        cc = int(message.text.strip())
        if 50 <= cc <= 3000:
            await state.update_data(engine_cc=cc)
            await _pilot_edit_ask_style(message, state)
        else:
            await message.answer(texts.REG_ERROR_ENGINE_CC)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.engine_cc)
async def pilot_edit_cc_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_style(callback.message, state)


async def _pilot_edit_ask_style(message: Message, state: FSMContext):
    data = await state.get_data()
    style_labels = {"calm": "Спокойный", "aggressive": "Агрессивный", "mixed": "Смешанный"}
    current = style_labels.get(str(data.get("driving_style", "")), "—")
    await state.set_state(PilotEdit.driving_style)
    await message.answer(
        f"Текущий стиль: <b>{current}</b>\nВыбери новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Спокойный", callback_data="edit_style_calm"),
                InlineKeyboardButton(text="Агрессивный", callback_data="edit_style_aggressive"),
                InlineKeyboardButton(text="Смешанный", callback_data="edit_style_mixed"),
            ],
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.callback_query(F.data.startswith("edit_style_"), PilotEdit.driving_style)
async def pilot_edit_style(callback: CallbackQuery, state: FSMContext):
    style = callback.data.replace("edit_style_", "")
    await state.update_data(driving_style=style)
    await callback.answer()
    await _pilot_edit_ask_photo(callback.message, state)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.driving_style)
async def pilot_edit_style_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_photo(callback.message, state)


async def _pilot_edit_ask_photo(message: Message, state: FSMContext):
    await state.set_state(PilotEdit.photo)
    await message.answer(
        "Отправь новое фото или пропусти (текущее будет сохранено):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PilotEdit.photo, F.photo)
async def pilot_edit_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await _pilot_edit_ask_about(message, state)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.photo)
async def pilot_edit_photo_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pilot_edit_ask_about(callback.message, state)


@router.message(PilotEdit.photo)
async def pilot_edit_photo_fallback(message: Message, state: FSMContext):
    await message.answer(
        "Отправь фото или нажми «Пропустить».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


async def _pilot_edit_ask_about(message: Message, state: FSMContext):
    data = await state.get_data()
    current = data.get("about") or "—"
    await state.set_state(PilotEdit.about)
    await message.answer(
        f"Текущее «О себе»: {current}\n\nВведи новый текст или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PilotEdit.about, F.text)
async def pilot_edit_about(message: Message, state: FSMContext, user=None):
    max_len = get_settings().about_text_max_length
    about = message.text.strip()
    if len(about) > max_len:
        await message.answer(texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len))
        return
    await state.update_data(about=about)
    await _finish_pilot_edit(message, state, user)


@router.callback_query(F.data == _SKIP_CB, PilotEdit.about)
async def pilot_edit_about_skip(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    await _finish_pilot_edit(callback.message, state, user)


async def _finish_pilot_edit(message: Message, state: FSMContext, user):
    """Save updated pilot profile to DB."""
    data = await state.get_data()
    await state.clear()

    if not user:
        await message.answer(texts.REG_ERROR_USER_NOT_FOUND)
        return

    style_map = {
        "calm": DrivingStyle.CALM,
        "aggressive": DrivingStyle.AGGRESSIVE,
        "mixed": DrivingStyle.MIXED,
    }
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == user.id)
        )
        p = r.scalar_one_or_none()
        if not p:
            await message.answer(texts.REG_ERROR_SAVE)
            return

        p.name = data.get("name") or p.name
        p.age = data.get("age") or p.age
        p.bike_brand = data.get("bike_brand") or p.bike_brand
        p.bike_model = data.get("bike_model") or p.bike_model
        p.engine_cc = data.get("engine_cc") or p.engine_cc
        if data.get("driving_style"):
            p.driving_style = style_map.get(str(data["driving_style"]), p.driving_style)
        if data.get("photo_file_id") is not None:
            p.photo_file_id = data["photo_file_id"]
        p.about = data.get("about", p.about)

        await session.commit()

    await message.answer("✅ Анкета обновлена!", reply_markup=get_main_menu_kb())


# ─────────────────────────────────────────────────────────────────────────────
# PASSENGER EDIT
# ─────────────────────────────────────────────────────────────────────────────

@router.message(PassengerEdit.name, F.text)
async def passenger_edit_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await _pax_edit_ask_age(message, state)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.name)
async def passenger_edit_name_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pax_edit_ask_age(callback.message, state)


async def _pax_edit_ask_age(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PassengerEdit.age)
    await message.answer(
        f"Текущий возраст: <b>{data.get('age')}</b>\nВведи новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PassengerEdit.age, F.text)
async def passenger_edit_age(message: Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if 18 <= age <= 80:
            await state.update_data(age=age)
            await _pax_edit_ask_weight(message, state)
        else:
            await message.answer(texts.REG_ERROR_AGE)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.age)
async def passenger_edit_age_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pax_edit_ask_weight(callback.message, state)


async def _pax_edit_ask_weight(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PassengerEdit.weight)
    await message.answer(
        f"Текущий вес: <b>{data.get('weight')} кг</b>\nВведи новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PassengerEdit.weight, F.text)
async def passenger_edit_weight(message: Message, state: FSMContext):
    try:
        w = int(message.text.strip())
        if 30 <= w <= 200:
            await state.update_data(weight=w)
            await _pax_edit_ask_height(message, state)
        else:
            await message.answer(texts.REG_ERROR_WEIGHT)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.weight)
async def passenger_edit_weight_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pax_edit_ask_height(callback.message, state)


async def _pax_edit_ask_height(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(PassengerEdit.height)
    await message.answer(
        f"Текущий рост: <b>{data.get('height')} см</b>\nВведи новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PassengerEdit.height, F.text)
async def passenger_edit_height(message: Message, state: FSMContext):
    try:
        h = int(message.text.strip())
        if 120 <= h <= 220:
            await state.update_data(height=h)
            await _pax_edit_ask_style(message, state)
        else:
            await message.answer(texts.REG_ERROR_HEIGHT)
    except ValueError:
        await message.answer(texts.REG_ERROR_NOT_NUMBER)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.height)
async def passenger_edit_height_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pax_edit_ask_style(callback.message, state)


async def _pax_edit_ask_style(message: Message, state: FSMContext):
    data = await state.get_data()
    style_labels = {"calm": "Спокойный", "aggressive": "Агрессивный", "mixed": "Смешанный"}
    current = style_labels.get(str(data.get("preferred_style", "")), "—")
    await state.set_state(PassengerEdit.preferred_style)
    await message.answer(
        f"Текущий желаемый стиль: <b>{current}</b>\nВыбери новый или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Спокойный", callback_data="edit_pax_style_calm"),
                InlineKeyboardButton(text="Агрессивный", callback_data="edit_pax_style_aggressive"),
                InlineKeyboardButton(text="Смешанный", callback_data="edit_pax_style_mixed"),
            ],
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.callback_query(F.data.startswith("edit_pax_style_"), PassengerEdit.preferred_style)
async def passenger_edit_style(callback: CallbackQuery, state: FSMContext):
    style = callback.data.replace("edit_pax_style_", "")
    await state.update_data(preferred_style=style)
    await callback.answer()
    await _pax_edit_ask_photo(callback.message, state)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.preferred_style)
async def passenger_edit_style_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pax_edit_ask_photo(callback.message, state)


async def _pax_edit_ask_photo(message: Message, state: FSMContext):
    await state.set_state(PassengerEdit.photo)
    await message.answer(
        "Отправь новое фото или пропусти (текущее сохранится):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PassengerEdit.photo, F.photo)
async def passenger_edit_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await _pax_edit_ask_about(message, state)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.photo)
async def passenger_edit_photo_skip(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _pax_edit_ask_about(callback.message, state)


@router.message(PassengerEdit.photo)
async def passenger_edit_photo_fallback(message: Message, state: FSMContext):
    await message.answer(
        "Отправь фото или нажми «Пропустить».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


async def _pax_edit_ask_about(message: Message, state: FSMContext):
    data = await state.get_data()
    current = data.get("about") or "—"
    await state.set_state(PassengerEdit.about)
    await message.answer(
        f"Текущее «О себе»: {current}\n\nВведи новый текст или пропусти:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data=_SKIP_CB)],
        ]),
    )


@router.message(PassengerEdit.about, F.text)
async def passenger_edit_about(message: Message, state: FSMContext, user=None):
    max_len = get_settings().about_text_max_length
    about = message.text.strip()
    if len(about) > max_len:
        await message.answer(texts.REG_ERROR_ABOUT_TOO_LONG.format(max_len=max_len))
        return
    await state.update_data(about=about)
    await _finish_passenger_edit(message, state, user)


@router.callback_query(F.data == _SKIP_CB, PassengerEdit.about)
async def passenger_edit_about_skip(callback: CallbackQuery, state: FSMContext, user=None):
    await callback.answer()
    await _finish_passenger_edit(callback.message, state, user)


async def _finish_passenger_edit(message: Message, state: FSMContext, user):
    """Save updated passenger profile to DB."""
    data = await state.get_data()
    await state.clear()

    if not user:
        await message.answer(texts.REG_ERROR_USER_NOT_FOUND)
        return

    style_map = {
        "calm": PreferredStyle.CALM,
        "aggressive": PreferredStyle.AGGRESSIVE,
        "mixed": PreferredStyle.MIXED,
    }
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == user.id)
        )
        p = r.scalar_one_or_none()
        if not p:
            await message.answer(texts.REG_ERROR_SAVE)
            return

        p.name = data.get("name") or p.name
        p.age = data.get("age") or p.age
        p.weight = data.get("weight") or p.weight
        p.height = data.get("height") or p.height
        if data.get("preferred_style"):
            p.preferred_style = style_map.get(str(data["preferred_style"]), p.preferred_style)
        if data.get("photo_file_id") is not None:
            p.photo_file_id = data["photo_file_id"]
        p.about = data.get("about", p.about)

        await session.commit()

    await message.answer("✅ Анкета обновлена!", reply_markup=get_main_menu_kb())
