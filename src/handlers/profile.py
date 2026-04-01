"""Profile and subscription block, including phone change workflow."""

from loguru import logger
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.keyboards.menu import get_back_to_menu_kb, get_city_select_kb
from src import texts
from src.models.user import effective_user_id
from src.services.subscription import reconcile_telegram_subscription_checkout
from src.utils.tg_callback_message import edit_text_or_send_new

router = Router()


# ── Profile raise FSM ─────────────────────────────────────────────────────────


class ProfileRaiseStates(StatesGroup):
    """Waiting for raise-profile payment to be confirmed."""

    awaiting_payment = State()


# ── Phone change FSM ──────────────────────────────────────────────────────────


class UserPhoneChangeStates(StatesGroup):
    """User enters new phone number before submitting a change request."""

    enter_new_phone = State()


class AdminPhoneApprovalStates(StatesGroup):
    """Admin approves or rejects a phone change request (no longer enters phone)."""

    enter_phone = State()  # kept for backward compatibility


# ─────────────────────────────────────────────────────────────────────────────
# Profile menu
# ─────────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data == "profile_city_change")
async def cb_profile_city_change(callback: CallbackQuery, state: FSMContext, user=None):
    """Смена города из профиля: список городов, далее тот же callback city_* что и при /start."""
    from src.services.admin_service import get_cities

    await callback.answer()
    await state.update_data(profile_city_change=True)
    cities = await get_cities()
    base = get_city_select_kb(cities)
    rows = list(base.inline_keyboard)
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_profile")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_text_or_send_new(callback, "Выбери новый город:", reply_markup=kb)


@router.callback_query(F.data == "menu_profile")
async def cb_profile_menu(callback: CallbackQuery, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.profile_service import get_profile_display
    from src.models.subscription import Subscription
    from src.models.base import get_session_factory
    from sqlalchemy import select
    from datetime import date

    sub_reconciled = False
    try:
        sub_reconciled = await reconcile_telegram_subscription_checkout(state, user)
    except Exception as e:
        logger.warning("menu_profile: subscription reconcile failed: %s", e)

    await state.clear()
    display_text, photo_id = await get_profile_display(user)

    # Show "Продлить" when there is a non-expired active subscription,
    # otherwise show "Оформить".
    sub_active = False
    if user:
        uid = effective_user_id(user)
        session_factory = get_session_factory()
        async with session_factory() as session:
            sub_r = await session.execute(
                select(Subscription)
                .where(
                    Subscription.user_id == uid,
                    Subscription.is_active.is_(True),
                    Subscription.expires_at >= date.today(),
                )
                .limit(1)
            )
            sub_active = sub_r.scalar_one_or_none() is not None

    kb_rows = [
        [InlineKeyboardButton(text="Редактировать анкету", callback_data="profile_edit")],
    ]
    if sub_active:
        kb_rows.append(
            [InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="profile_subscribe")]
        )
    else:
        kb_rows.append(
            [InlineKeyboardButton(text="💳 Оформить подписку", callback_data="profile_subscribe")]
        )
    kb_rows.extend(
        [
            [InlineKeyboardButton(text="Поднять анкету", callback_data="profile_raise")],
            [
                InlineKeyboardButton(
                    text=texts.PHONE_CHANGE_BTN, callback_data="profile_phone_change"
                )
            ],
            [InlineKeyboardButton(text="🏙️ Сменить город", callback_data="profile_city_change")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if sub_reconciled:
        await callback.answer("✅ Оплата засчитана, подписка продлена.", show_alert=True)
    else:
        await callback.answer()
    if photo_id:
        try:
            await callback.message.delete()
        except Exception as e:
            logger.debug("menu_profile: delete before photo failed: %s", e)
        try:
            await callback.bot.send_photo(
                callback.message.chat.id,
                photo=photo_id,
                caption=display_text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as e:
            logger.warning("menu_profile: send_photo failed, fallback to text: %s", e)
    try:
        await callback.message.edit_text(
            display_text, reply_markup=kb, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.debug("menu_profile: edit_text failed, send new message: %s", e)
        await callback.message.answer(
            display_text, reply_markup=kb, parse_mode=ParseMode.HTML
        )


@router.callback_query(F.data == "profile_subscribe")
async def cb_profile_subscribe(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.admin_service import get_subscription_settings
    from src.config import get_settings

    # БД — источник истины, env — fallback
    settings_db = await get_subscription_settings()
    s = get_settings()

    monthly_price = (
        settings_db.monthly_price_kopecks // 100
        if settings_db and settings_db.monthly_price_kopecks
        else s.subscription_monthly_price // 100
    )
    season_price = (
        settings_db.season_price_kopecks // 100
        if settings_db and settings_db.season_price_kopecks
        else s.subscription_season_price // 100
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"1 месяц — {monthly_price} ₽",
                    callback_data="sub_monthly",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"Год (365 дн.) — {season_price} ₽",
                    callback_data="sub_season",
                )
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
        ]
    )
    from src.services.subscription_messages import subscription_required_message

    await edit_text_or_send_new(
        callback,
        (await subscription_required_message("motopair_menu")) + "\n\nВыбери тариф:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "profile_raise")
async def cb_profile_raise(callback: CallbackQuery, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.motopair_service import raise_profile
    from src.services.admin_service import get_subscription_settings
    from src.services.payment import create_payment
    from src.models.user import UserRole

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    role = "pilot" if user.role == UserRole.PILOT else "passenger"

    settings_db = await get_subscription_settings()

    # Feature disabled entirely — block (do NOT raise for free)
    if not settings_db or not settings_db.raise_profile_enabled:
        await edit_text_or_send_new(
            callback,
            "Поднятие анкеты сейчас недоступно.",
            reply_markup=get_back_to_menu_kb(),
        )
        await callback.answer()
        return

    price = settings_db.raise_profile_price_kopecks

    # Free raise only when price is explicitly zero
    if price <= 0:
        ok = await raise_profile(effective_user_id(user), role)
        if ok:
            await edit_text_or_send_new(
                callback,
                "✅ Анкета поднята! Тебя будут видеть выше в поиске.",
                reply_markup=get_back_to_menu_kb(),
            )
        else:
            await edit_text_or_send_new(
                callback,
                "Ошибка при поднятии анкеты.",
                reply_markup=get_back_to_menu_kb(),
            )
        await callback.answer()
        return

    # Paid raise
    from src.config import get_settings

    s = get_settings()
    payment = await create_payment(
        amount_kopecks=price,
        description="Поднятие анкеты",
        metadata={"type": "raise_profile", "user_id": str(effective_user_id(user)), "role": role},
        return_url=s.telegram_return_url or "https://t.me",
    )
    if payment and payment.get("confirmation_url"):
        await state.set_state(ProfileRaiseStates.awaiting_payment)
        await state.update_data(raise_payment_id=payment["id"], raise_role=role)
        price_rub = price // 100
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
                [
                    InlineKeyboardButton(
                        text="✅ Я оплатил — проверить",
                        callback_data="raise_checkpay",
                    )
                ],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
            ]
        )
        await edit_text_or_send_new(
            callback,
            f"💳 Поднятие анкеты платное: <b>{price_rub} ₽</b>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
        return

    logger.warning("cb_profile_raise: payment service unavailable")
    await edit_text_or_send_new(
        callback,
        "Платёжный сервис временно недоступен. Попробуй позже.",
        reply_markup=get_back_to_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "raise_checkpay", ProfileRaiseStates.awaiting_payment)
async def cb_raise_check_payment(callback: CallbackQuery, state: FSMContext, user=None):
    """User clicked 'I paid — check'. Verify payment and raise profile."""
    from src.services.payment import check_payment_status
    from src.services.motopair_service import raise_profile

    data = await state.get_data()
    payment_id = data.get("raise_payment_id")
    role = data.get("raise_role", "pilot")

    if not payment_id:
        await callback.answer("Ошибка: платёж не найден.", show_alert=True)
        return

    status = await check_payment_status(payment_id)
    if status == "succeeded":
        await state.clear()
        ok = await raise_profile(effective_user_id(user), role)
        if ok:
            await edit_text_or_send_new(
                callback,
                "✅ Оплата прошла! Анкета поднята — тебя увидят первым.",
                reply_markup=get_back_to_menu_kb(),
            )
        else:
            await edit_text_or_send_new(
                callback,
                "Оплата прошла, но поднять анкету не удалось. Обратись в поддержку.",
                reply_markup=get_back_to_menu_kb(),
            )
    elif status == "canceled":
        await state.clear()
        await edit_text_or_send_new(
            callback, "❌ Платёж отменён.", reply_markup=get_back_to_menu_kb()
        )
    else:
        await callback.answer(
            "Платёж ещё не обработан. Подожди несколько секунд и попробуй ещё раз.",
            show_alert=True,
        )
    await callback.answer()


# ─────────────────────────────────────────────────────────────────────────────
# Phone change: user → request → admin approve/reject → confirm
# ─────────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data == "profile_phone_change")
async def cb_phone_change_request(callback: CallbackQuery, state: FSMContext, user=None):
    """Step 1: Ask user to enter new phone number."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.models.base import get_session_factory
    from src.models.phone_change_request import PhoneChangeRequest, PhoneChangeStatus
    from sqlalchemy import select

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    canon_uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.execute(
            select(PhoneChangeRequest).where(
                PhoneChangeRequest.user_id == canon_uid,
                PhoneChangeRequest.status == PhoneChangeStatus.PENDING,
            )
        )
        if existing.scalar_one_or_none():
            await callback.answer(
                "У тебя уже есть активная заявка на смену телефона.", show_alert=True
            )
            return

    await state.set_state(UserPhoneChangeStates.enter_new_phone)
    await edit_text_or_send_new(
        callback,
        "📱 Введи новый номер телефона в формате +79991234567:\n\n"
        "После ввода заявка будет отправлена администратору на подтверждение.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="« Отмена", callback_data="menu_profile")],
            ]
        ),
    )
    await callback.answer()


@router.message(UserPhoneChangeStates.enter_new_phone, F.text)
async def user_phone_change_enter(message: Message, state: FSMContext, user=None):
    """Step 2: User entered new phone — validate and create request for admin."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.models.base import get_session_factory
    from src.models.phone_change_request import PhoneChangeRequest
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger
    from sqlalchemy import select

    new_phone = message.text.strip()
    if not new_phone.startswith("+") or len(new_phone) < 10:
        await message.answer(
            "Введи номер в формате +79991234567.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="« Отмена", callback_data="menu_profile")],
                ]
            ),
        )
        return

    await state.clear()

    if not user:
        await message.answer("Ошибка. Попробуй снова.", reply_markup=get_back_to_menu_kb())
        return

    canon_uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Get current phone
        pilot = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == canon_uid))
        p = pilot.scalar_one_or_none()
        old_phone = p.phone if p else None
        if not old_phone:
            pax = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == canon_uid)
            )
            pp = pax.scalar_one_or_none()
            old_phone = pp.phone if pp else "—"

        # Create pending request with new_phone stored (канонический user_id для профиля)
        req = PhoneChangeRequest(user_id=canon_uid, new_phone=new_phone[:20])
        session.add(req)
        await session.commit()
        req_id = str(req.id)

    # Notify all superadmins with old and new phone
    bot = message.bot
    user_display = (
        f"@{user.platform_username}" if user.platform_username else str(user.platform_user_id)
    )
    admin_text = (
        f"📱 <b>Запрос на смену телефона</b>\n\n"
        f"Пользователь: {user_display}\n"
        f"Текущий номер: {old_phone}\n"
        f"Новый номер: <b>{new_phone}</b>\n\n"
        f"Подтвердить смену?"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.PHONE_CHANGE_BTN_CONFIRM,
                    callback_data=f"admin_phone_approve_{req_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=texts.PHONE_CHANGE_BTN_REJECT,
                    callback_data=f"admin_phone_reject_{req_id}",
                )
            ],
        ]
    )
    from src.services.admin_multichannel_notify import notify_superadmins_multichannel
    from src.services.broadcast import get_max_adapter

    await notify_superadmins_multichannel(
        admin_text,
        telegram_markup=kb,
        telegram_bot=bot,
        max_adapter=get_max_adapter(),
    )

    await message.answer(texts.PHONE_CHANGE_REQUEST_SENT, reply_markup=get_back_to_menu_kb())


@router.callback_query(F.data.startswith("admin_phone_approve_"))
async def cb_admin_phone_approve(callback: CallbackQuery, state: FSMContext):
    """Superadmin approves phone change — applies new_phone stored in request."""
    from src.services.admin_service import get_user_by_platform_id, is_effective_superadmin_user
    from src.services.admin_phone_actions import phone_change_approve
    from src.services.broadcast import get_max_adapter

    admin_u = await get_user_by_platform_id(callback.from_user.id)
    if not admin_u or not await is_effective_superadmin_user(admin_u):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    req_id = callback.data.replace("admin_phone_approve_", "")
    ok, msg = await phone_change_approve(
        req_id,
        admin_u,
        telegram_bot=callback.bot,
        max_adapter=get_max_adapter(),
    )
    if not ok:
        await callback.answer(msg, show_alert=True)
        return
    await callback.message.edit_text(msg)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_phone_reject_"))
async def cb_admin_phone_reject(callback: CallbackQuery):
    """Superadmin rejects phone change request."""
    from src.services.admin_service import get_user_by_platform_id, is_effective_superadmin_user
    from src.services.admin_phone_actions import phone_change_reject
    from src.services.broadcast import get_max_adapter

    admin_u = await get_user_by_platform_id(callback.from_user.id)
    if not admin_u or not await is_effective_superadmin_user(admin_u):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    req_id = callback.data.replace("admin_phone_reject_", "")
    ok, msg = await phone_change_reject(
        req_id,
        admin_u,
        telegram_bot=callback.bot,
        max_adapter=get_max_adapter(),
    )
    if not ok:
        await callback.answer(msg)
        return
    await callback.message.edit_text(msg)
    await callback.answer()
