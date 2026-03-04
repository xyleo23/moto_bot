"""SOS block - emergency alerts."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.keyboards.menu import get_back_to_menu_kb

router = Router()


class SosStates(StatesGroup):
    choose_type = State()
    location = State()
    comment = State()


@router.callback_query(F.data == "menu_sos")
async def cb_sos_menu(callback: CallbackQuery, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ДТП", callback_data="sos_accident")],
        [InlineKeyboardButton(text="Сломался", callback_data="sos_broken")],
        [InlineKeyboardButton(text="Обсох", callback_data="sos_ran_out")],
        [InlineKeyboardButton(text="Другое", callback_data="sos_other")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await callback.message.edit_text("🚨 Выбери тип SOS:", reply_markup=kb)
    await state.set_state(SosStates.choose_type)
    await callback.answer()


@router.callback_query(F.data.startswith("sos_"), SosStates.choose_type)
async def cb_sos_type(callback: CallbackQuery, state: FSMContext, user=None):
    type_map = {
        "sos_accident": "ДТП",
        "sos_broken": "Сломался",
        "sos_ran_out": "Обсох",
        "sos_other": "Другое",
    }
    sos_type = callback.data
    await state.update_data(sos_type=sos_type)
    await state.set_state(SosStates.location)
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
    await callback.message.edit_text("Отправь свою геолокацию:")
    await callback.message.answer(
        "Нажми кнопку ниже, чтобы отправить местоположение:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    await callback.answer()


@router.message(SosStates.location, F.location)
async def sos_location(message: Message, state: FSMContext, user=None, bot=None):
    loc = message.location
    await state.update_data(lat=loc.latitude, lon=loc.longitude)
    await state.set_state(SosStates.comment)
    from aiogram.types import ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer(
        "Введи комментарий (или «Пропустить»):",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        "Можешь добавить описание ситуации.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="sos_skip_comment")],
        ]),
    )


@router.callback_query(F.data == "sos_skip_comment", SosStates.comment)
async def sos_skip_comment(callback: CallbackQuery, state: FSMContext, user=None, bot=None):
    await _send_sos_alert(callback.message, state, user, None, bot)
    await callback.answer()


@router.message(SosStates.comment, F.text)
async def sos_comment(message: Message, state: FSMContext, user=None, bot=None):
    await _send_sos_alert(message, state, user, message.text.strip(), bot)


async def _send_sos_alert(message: Message, state: FSMContext, user, comment: str | None, bot=None):
    """Send SOS and broadcast to city users."""
    from src.services.sos_service import create_sos_alert
    from src.config import get_settings

    data = await state.get_data()
    await state.clear()

    if not user or not user.city_id:
        await message.answer("Ошибка: город не выбран. Нажми /start")
        return

    cooldown_ok = await create_sos_alert(
        user_id=user.id,
        city_id=user.city_id,
        sos_type=data["sos_type"],
        lat=data["lat"],
        lon=data["lon"],
        comment=comment,
    )
    if not cooldown_ok:
        mins = get_settings().sos_cooldown_seconds // 60
        await message.answer(
            f"Подожди {mins} мин. перед следующим SOS.",
            reply_markup=get_back_to_menu_kb(),
        )
        return

    type_labels = {"sos_accident": "ДТП", "sos_broken": "Сломался", "sos_ran_out": "Обсох", "sos_other": "Другое"}
    from src.services.sos_service import get_city_telegram_user_ids
    from src.services.user import get_user_profile_display
    profile = await get_user_profile_display(user)
    user_ids = await get_city_telegram_user_ids(user.city_id)
    text = f"🚨 SOS: {type_labels.get(data['sos_type'], 'Другое')}\n\n{profile}\n\n"
    if comment:
        text += f"Комментарий: {comment}\n\n"
    text += f"📍 https://yandex.ru/maps/?ll={data['lon']},{data['lat']}&z=16"

    send_bot = bot or getattr(message, "bot", None)
    if send_bot:
        for uid in user_ids:
            if uid != message.from_user.id:
                try:
                    await send_bot.send_message(uid, text)
                except Exception:
                    pass

    await message.answer(
        "SOS отправлен! Помощь в пути.",
        reply_markup=get_back_to_menu_kb(),
    )
