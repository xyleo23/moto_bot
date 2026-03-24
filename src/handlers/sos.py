"""SOS block — emergency alerts with timer and all-clear."""
import asyncio
from html import escape

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

from src.keyboards.menu import get_back_to_menu_kb
from src import texts
from src.models.user import effective_user_id

router = Router()


class SosStates(StatesGroup):
    choose_type = State()
    location = State()
    comment = State()


@router.callback_query(F.data == "menu_sos")
async def cb_sos_menu(callback: CallbackQuery, state: FSMContext, user=None):
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ДТП", callback_data="sos_accident")],
            [InlineKeyboardButton(text="Сломался", callback_data="sos_broken")],
            [InlineKeyboardButton(text="Обсох", callback_data="sos_ran_out")],
            [InlineKeyboardButton(text="Другое", callback_data="sos_other")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ])
        await callback.message.edit_text(texts.SOS_CHOOSE_TYPE, reply_markup=kb)
        await state.set_state(SosStates.choose_type)
    except Exception:
        logger.exception("cb_sos_menu: error")
        await state.clear()
        await callback.message.answer(
            "Произошла ошибка. Попробуй снова.",
            reply_markup=get_back_to_menu_kb(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("sos_"), SosStates.choose_type)
async def cb_sos_type(callback: CallbackQuery, state: FSMContext, user=None):
    try:
        sos_type = callback.data
        await state.update_data(sos_type=sos_type)
        await state.set_state(SosStates.location)
        await callback.message.edit_text(texts.SOS_SEND_LOCATION)
        await callback.message.answer(
            "Нажми кнопку ниже, чтобы отправить местоположение:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
    except Exception:
        logger.exception("cb_sos_type: error")
        await state.clear()
        await callback.message.answer(
            "Произошла ошибка. Попробуй снова.",
            reply_markup=get_back_to_menu_kb(),
        )
    await callback.answer()


@router.message(SosStates.location, F.location)
async def sos_location(message: Message, state: FSMContext, user=None, bot=None):
    try:
        loc = message.location
        await state.update_data(lat=loc.latitude, lon=loc.longitude)
        await state.set_state(SosStates.comment)
        await message.answer(
            texts.SOS_ASK_COMMENT,
            reply_markup=ReplyKeyboardRemove(),
        )
        await message.answer(
            "Можешь добавить описание ситуации.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=texts.BTN_SKIP, callback_data="sos_skip_comment")],
            ]),
        )
    except Exception:
        logger.exception("sos_location: error")
        await state.clear()
        await message.answer(
            "Произошла ошибка. Попробуй снова.",
            reply_markup=get_back_to_menu_kb(),
        )


@router.callback_query(F.data == "sos_skip_comment", SosStates.comment)
async def sos_skip_comment(callback: CallbackQuery, state: FSMContext, user=None, bot=None):
    try:
        logger.info("SOS sending...")
        await _send_sos_alert(callback.message, state, user, None, bot, platform_user_id=callback.from_user.id)
    except Exception as e:
        logger.exception("sos_skip_comment: error in _send_sos_alert: %s", e)
        await state.clear()
        await callback.message.answer(
            "Произошла ошибка при отправке SOS. Попробуй снова.",
            reply_markup=get_back_to_menu_kb(),
        )
    await callback.answer()


@router.message(SosStates.comment, F.text)
async def sos_comment(message: Message, state: FSMContext, user=None, bot=None):
    try:
        logger.info("SOS sending...")
        await _send_sos_alert(message, state, user, message.text.strip(), bot, platform_user_id=message.from_user.id)
    except Exception as e:
        logger.exception("sos_comment: error in _send_sos_alert: %s", e)
        await state.clear()
        await message.answer(
            "Произошла ошибка при отправке SOS. Попробуй снова.",
            reply_markup=get_back_to_menu_kb(),
        )


async def _get_user_phone(user) -> str | None:
    """Get user's phone number from their pilot/passenger profile."""
    from src.models.base import get_session_factory
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger
    from src.models.user import UserRole
    from sqlalchemy import select

    uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        if user.role == UserRole.PILOT:
            r = await session.execute(
                select(ProfilePilot.phone).where(ProfilePilot.user_id == uid)
            )
        else:
            r = await session.execute(
                select(ProfilePassenger.phone).where(ProfilePassenger.user_id == uid)
            )
        return r.scalar_one_or_none()


async def _send_sos_alert(
    message: Message,
    state: FSMContext,
    user,
    comment: str | None,
    bot=None,
    *,
    platform_user_id: int | None = None,
) -> None:
    """Create SOS alert and broadcast to city users as background task."""
    from src.services.sos_service import (
        create_sos_alert,
        get_city_telegram_user_ids,
        get_city_max_user_ids,
    )
    from src.services.broadcast import broadcast_background
    from src.services.user import get_user_profile_display
    from src.config import get_settings

    data = await state.get_data()
    await state.clear()

    # Fallback: load user if middleware didn't pass.
    # Use explicit platform_user_id when called from callback (message.from_user = bot).
    if not user:
        from src.services.user import get_or_create_user
        uid = platform_user_id or (message.from_user.id if message.from_user else None)
        if uid:
            user = await get_or_create_user(
                platform="telegram",
                platform_user_id=uid,
                username=getattr(message.from_user, "username", None) if message.from_user else None,
                first_name=getattr(message.from_user, "first_name", None) if message.from_user else None,
            )

    # Validate FSM data — if state expired (Redis TTL), we may get empty dict
    required_keys = ("sos_type", "lat", "lon")
    if not all(k in data for k in required_keys):
        logger.warning(
            "SOS: missing FSM data keys=%s has=%s",
            [k for k in required_keys if k not in data],
            list(data.keys()),
        )
        await message.answer(
            "Данные устарели. Начни SOS заново — нажми /sos или кнопку 🚨 SOS.",
            reply_markup=get_back_to_menu_kb(),
        )
        return

    if not user or not user.city_id:
        await message.answer(texts.SOS_NO_CITY)
        return

    eff_uid = effective_user_id(user)
    try:
        ok, remaining = await create_sos_alert(
            user_id=eff_uid,
            city_id=user.city_id,
            sos_type=data["sos_type"],
            lat=data["lat"],
            lon=data["lon"],
            comment=comment,
        )
    except Exception as e:
        logger.exception("_send_sos_alert: create_sos_alert failed: %s", e)
        raise

    if not ok:
        mins = remaining // 60
        secs = remaining % 60
        await message.answer(
            texts.SOS_READY_WAIT.format(mins=mins, secs=secs),
            reply_markup=_sos_cooldown_kb(remaining),
        )
        return

    type_labels = {
        "sos_accident": "ДТП",
        "sos_broken": "Сломался",
        "sos_ran_out": "Обсох",
        "sos_other": "Другое",
    }

    settings = get_settings()
    profile = await get_user_profile_display(user)
    user_ids = await get_city_telegram_user_ids(user.city_id)

    max_user_ids = await get_city_max_user_ids(user.city_id)
    logger.info(
        f"SOS broadcast: city_id={user.city_id} tg_recipients={len(user_ids)} max_recipients={len(max_user_ids)} exclude_sender={user.platform_user_id}",
    )

    # HTML parse_mode: escape profile (name, @username, phone may contain <>&)
    broadcast_text = texts.SOS_BROADCAST_TYPE.format(
        type_label=type_labels.get(data["sos_type"], "Другое"),
        profile=escape(profile),
    )
    if comment:
        broadcast_text += texts.SOS_BROADCAST_COMMENT.format(comment=escape(comment))
    broadcast_text += texts.SOS_BROADCAST_MAP.format(
        lon=data["lon"], lat=data["lat"]
    )

    # Build keyboard with "Call" and "Telegram" quick-contact buttons
    phone = await _get_user_phone(user)
    broadcast_kb_rows = []
    if phone:
        broadcast_kb_rows.append([
            InlineKeyboardButton(text=texts.SOS_BTN_CALL, url=f"tel:{phone}"),
        ])
    tg_id = user.platform_user_id  # message.from_user может быть бот (при callback)
    broadcast_kb_rows.append([
        InlineKeyboardButton(text=texts.SOS_BTN_TELEGRAM, url=f"tg://user?id={tg_id}"),
    ])
    broadcast_kb = InlineKeyboardMarkup(inline_keyboard=broadcast_kb_rows)

    send_bot = bot or getattr(message, "bot", None)
    if not send_bot:
        logger.warning("SOS broadcast skipped: no bot instance")
    elif not user_ids:
        logger.warning("SOS broadcast skipped: no recipients in city")
    if send_bot and user_ids:
        # Non-blocking background broadcast with 50ms inter-message delay
        broadcast_background(
            send_bot,
            user_ids,
            broadcast_text,
            exclude_id=tg_id,
            reply_markup=broadcast_kb,
        )

    # Cross-platform: also broadcast to MAX users in the same city
    from src.services.broadcast import get_max_adapter, broadcast_max_background
    from src.platforms.base import Button, ButtonType
    max_adapter = get_max_adapter()
    if max_adapter and max_user_ids:
        max_kb_rows = []
        if phone:
            max_kb_rows.append([Button(text="📞 Позвонить", type=ButtonType.URL, url=f"tel:{phone}")])
        broadcast_max_background(
            max_adapter,
            max_user_ids,
            broadcast_text,
            kb_rows=max_kb_rows if max_kb_rows else None,
        )

    cooldown_mins = settings.sos_cooldown_minutes
    # Reply with confirmation + timer + all-clear button
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.SOS_CHECK_READY, callback_data="sos_check_ready")],
        [InlineKeyboardButton(text=texts.SOS_ALL_CLEAR_BTN, callback_data="sos_all_clear")],
        [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
    ])
    await message.answer(
        texts.SOS_SENT.format(cooldown=cooldown_mins),
        reply_markup=kb,
    )


def _sos_cooldown_kb(remaining_seconds: int) -> InlineKeyboardMarkup:
    """Keyboard shown when cooldown is active."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=texts.SOS_CHECK_READY, callback_data="sos_check_ready")],
        [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
    ])


@router.callback_query(F.data == "sos_check_ready")
async def cb_sos_check_ready(callback: CallbackQuery, state: FSMContext, user=None):
    """Edit the SOS message to show current remaining cooldown time."""
    from src.services.sos_service import check_sos_cooldown

    try:
        if not user:
            await callback.answer("Ошибка.")
            return

        remaining = await check_sos_cooldown(effective_user_id(user))
        if remaining <= 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚨 Отправить новый SOS", callback_data="menu_sos")],
                [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
            ])
            await callback.message.edit_text(texts.SOS_READY_NOW, reply_markup=kb)
        else:
            mins = remaining // 60
            secs = remaining % 60
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=texts.SOS_CHECK_READY, callback_data="sos_check_ready")],
                [InlineKeyboardButton(text="« Назад в меню", callback_data="menu_main")],
            ])
            try:
                await callback.message.edit_text(
                    texts.SOS_READY_WAIT.format(mins=mins, secs=secs),
                    reply_markup=kb,
                )
            except Exception as e:
                logger.exception("cb_sos_check_ready: edit_text failed: %s", e)
    except Exception:
        logger.exception("cb_sos_check_ready: error")
        await state.clear()
    await callback.answer()


@router.callback_query(F.data == "sos_all_clear")
async def cb_sos_all_clear(callback: CallbackQuery, state: FSMContext, user=None, bot=None):
    """
    User signals help received. Broadcast all-clear to city.
    Broadcast runs as a background task.
    """
    from src.services.sos_service import get_city_telegram_user_ids
    from src.services.broadcast import broadcast_background
    from src.services.user import get_user_profile_display

    try:
        if not user or not user.city_id:
            await callback.answer(texts.SOS_NO_CITY, show_alert=True)
            return

        profile = await get_user_profile_display(user)
        # Extract user's display name for the broadcast message
        name = (
            getattr(user, "platform_first_name", None)
            or getattr(callback.from_user, "first_name", None)
            or "Участник"
        )

        user_ids = await get_city_telegram_user_ids(user.city_id)
        send_bot = bot or callback.bot

        if send_bot and user_ids:
            broadcast_background(
                send_bot,
                user_ids,
                texts.SOS_ALL_CLEAR_BROADCAST.format(name=name),
                exclude_id=callback.from_user.id,
            )

        await callback.message.edit_text(
            "✅ Рады, что всё хорошо! Отбой разослан.",
            reply_markup=get_back_to_menu_kb(),
        )
    except Exception:
        logger.exception("cb_sos_all_clear: error")
        await state.clear()
        await callback.message.answer(
            "Произошла ошибка. Попробуй снова.",
            reply_markup=get_back_to_menu_kb(),
        )
    await callback.answer()
