"""Profile and subscription block, including phone change workflow."""
import uuid

from loguru import logger
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from src.keyboards.menu import get_back_to_menu_kb
from src import texts

router = Router()


# ── Profile raise FSM ─────────────────────────────────────────────────────────

class ProfileRaiseStates(StatesGroup):
    """Waiting for raise-profile payment to be confirmed."""
    awaiting_payment = State()


# ── Phone change FSM ──────────────────────────────────────────────────────────

class AdminPhoneApprovalStates(StatesGroup):
    """Admin enters new phone number after approving a phone change request."""
    enter_phone = State()


# ─────────────────────────────────────────────────────────────────────────────
# Profile menu
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu_profile")
async def cb_profile_menu(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.profile_service import get_profile_text
    from src.services.subscription import check_subscription_required
    from src.models.subscription import Subscription
    from src.models.base import get_session_factory
    from sqlalchemy import select

    text = await get_profile_text(user)
    sub_required = await check_subscription_required(user)

    # Check if user has an active subscription to decide which button to show
    sub_active = False
    if user:
        session_factory = get_session_factory()
        async with session_factory() as session:
            sub_r = await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.is_active.is_(True),
                ).limit(1)
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
    kb_rows.extend([
        [InlineKeyboardButton(text="Поднять анкету", callback_data="profile_raise")],
        [InlineKeyboardButton(text=texts.PHONE_CHANGE_BTN, callback_data="profile_phone_change")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )
    await callback.answer()



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

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"1 месяц — {monthly_price} ₽",
            callback_data="sub_monthly",
        )],
        [InlineKeyboardButton(
            text=f"Сезон — {season_price} ₽",
            callback_data="sub_season",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
    ])
    await callback.message.edit_text(
        "Для доступа к поиску мотопары нужна активная подписка.\n\n"
        "Подписка даёт:\n"
        "• Просмотр анкет пилотов и двоек\n"
        "• Лайки и совпадения с контактами\n"
        "• Прохваты — без ограничений бесплатно\n"
        "• Мотопробеги — 2 бесплатно в месяц\n"
        "• Поднятие анкеты (по настройке)\n\n"
        "Выбери срок:",
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

    # Check if profile raise requires payment
    settings_db = await get_subscription_settings()
    if (
        settings_db
        and settings_db.raise_profile_enabled
        and settings_db.raise_profile_price_kopecks > 0
    ):
        price = settings_db.raise_profile_price_kopecks
        payment = await create_payment(
            amount_kopecks=price,
            description="Поднятие анкеты",
            metadata={"type": "raise_profile", "user_id": str(user.id), "role": role},
        )
        if payment and payment.get("confirmation_url"):
            await state.set_state(ProfileRaiseStates.awaiting_payment)
            await state.update_data(raise_payment_id=payment["id"], raise_role=role)
            price_rub = price // 100
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
                [InlineKeyboardButton(
                    text="✅ Я оплатил — проверить",
                    callback_data="raise_checkpay",
                )],
                [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
            ])
            await callback.message.edit_text(
                f"💳 Поднятие анкеты платное: <b>{price_rub} ₽</b>\n\n"
                f"Оплати и нажми «Я оплатил — проверить».",
                reply_markup=kb,
            )
            await callback.answer()
            return
        # Payment is required but service unavailable — do not raise for free
        logger.warning("cb_profile_raise: payment required but service unavailable, blocking free raise")
        await callback.message.edit_text(
            "Платёжный сервис временно недоступен. Попробуй позже.",
            reply_markup=get_back_to_menu_kb(),
        )
        await callback.answer()
        return

    # Free raise (payment not configured or disabled)
    ok = await raise_profile(user.id, role)
    if ok:
        await callback.message.edit_text(
            "✅ Анкета поднята! Тебя будут видеть выше в поиске.",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        await callback.message.edit_text(
            "Ошибка при поднятии анкеты.", reply_markup=get_back_to_menu_kb()
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
        ok = await raise_profile(user.id, role)
        if ok:
            await callback.message.edit_text(
                "✅ Оплата прошла! Анкета поднята — тебя увидят первым.",
                reply_markup=get_back_to_menu_kb(),
            )
        else:
            await callback.message.edit_text(
                "Оплата прошла, но поднять анкету не удалось. Обратись в поддержку.",
                reply_markup=get_back_to_menu_kb(),
            )
    elif status == "canceled":
        await state.clear()
        await callback.message.edit_text("❌ Платёж отменён.", reply_markup=get_back_to_menu_kb())
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
async def cb_phone_change_request(callback: CallbackQuery, user=None):
    """User requests phone change. Creates a pending request and notifies superadmin."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.models.base import get_session_factory
    from src.models.phone_change_request import PhoneChangeRequest, PhoneChangeStatus
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger
    from src.config import get_settings
    from sqlalchemy import select

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Check for existing pending request
        existing = await session.execute(
            select(PhoneChangeRequest).where(
                PhoneChangeRequest.user_id == user.id,
                PhoneChangeRequest.status == PhoneChangeStatus.PENDING,
            )
        )
        if existing.scalar_one_or_none():
            await callback.answer(
                "У тебя уже есть активная заявка на смену телефона.", show_alert=True
            )
            return

        # Get current phone from profile
        pilot = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == user.id)
        )
        p = pilot.scalar_one_or_none()
        old_phone = p.phone if p else None
        if not old_phone:
            pax = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == user.id)
            )
            pp = pax.scalar_one_or_none()
            old_phone = pp.phone if pp else "—"

        # Create pending request
        req = PhoneChangeRequest(user_id=user.id)
        session.add(req)
        await session.commit()
        req_id = str(req.id)

    # Notify all superadmins
    settings = get_settings()
    bot = callback.bot
    user_display = (
        f"@{user.platform_username}" if user.platform_username
        else str(user.platform_user_id)
    )
    admin_text = texts.PHONE_CHANGE_ADMIN_TEXT.format(
        user=user_display,
        old_phone=old_phone,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=texts.PHONE_CHANGE_BTN_CONFIRM,
            callback_data=f"admin_phone_approve_{req_id}",
        )],
        [InlineKeyboardButton(
            text=texts.PHONE_CHANGE_BTN_REJECT,
            callback_data=f"admin_phone_reject_{req_id}",
        )],
    ])
    for admin_id in settings.superadmin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=kb)
        except Exception as e:
            logger.warning("Cannot notify admin %s about phone change: %s", admin_id, e)

    await callback.message.edit_text(
        texts.PHONE_CHANGE_REQUEST_SENT, reply_markup=get_back_to_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_phone_approve_"))
async def cb_admin_phone_approve(callback: CallbackQuery, state: FSMContext):
    """Superadmin approves phone change — enters new number next."""
    from src.config import get_settings

    settings = get_settings()
    if callback.from_user.id not in settings.superadmin_ids:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    req_id = callback.data.replace("admin_phone_approve_", "")
    await state.update_data(phone_change_req_id=req_id)
    await state.set_state(AdminPhoneApprovalStates.enter_phone)
    await callback.message.edit_text(
        "Введи новый номер телефона (формат +79991234567):"
    )
    await callback.answer()


@router.message(AdminPhoneApprovalStates.enter_phone, F.text)
async def admin_phone_enter(message: Message, state: FSMContext):
    """Superadmin enters new phone number, system updates DB and notifies user."""
    from src.config import get_settings

    settings = get_settings()
    if message.from_user.id not in settings.superadmin_ids:
        await state.clear()
        return

    new_phone = message.text.strip()
    if not new_phone.startswith("+") or len(new_phone) < 10:
        await message.answer("Введи номер в формате +79991234567.")
        return

    data = await state.get_data()
    req_id = data.get("phone_change_req_id")
    await state.clear()

    if not req_id:
        await message.answer("Ошибка: не найден запрос.")
        return

    try:
        req_uuid = uuid.UUID(req_id)
    except ValueError:
        await message.answer("Некорректный ID запроса.")
        return

    from src.models.base import get_session_factory
    from src.models.phone_change_request import PhoneChangeRequest, PhoneChangeStatus
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger
    from src.models.user import User
    from sqlalchemy import select
    from datetime import datetime

    session_factory = get_session_factory()
    async with session_factory() as session:
        req_r = await session.execute(
            select(PhoneChangeRequest).where(PhoneChangeRequest.id == req_uuid)
        )
        req = req_r.scalar_one_or_none()
        if not req or req.status != PhoneChangeStatus.PENDING:
            await message.answer("Запрос не найден или уже обработан.")
            return

        # Update phone in pilot/passenger profile
        pilot = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == req.user_id)
        )
        p = pilot.scalar_one_or_none()
        if p:
            p.phone = new_phone[:20]
        else:
            pax = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == req.user_id)
            )
            pp = pax.scalar_one_or_none()
            if pp:
                pp.phone = new_phone[:20]

        # Mark request resolved
        req.status = PhoneChangeStatus.APPROVED
        req.new_phone = new_phone[:20]
        req.resolved_at = datetime.utcnow()
        await session.commit()

        # Get user's platform_user_id for notification
        user_r = await session.execute(select(User).where(User.id == req.user_id))
        u = user_r.scalar_one_or_none()

    await message.answer(
        f"✅ Номер обновлён: {new_phone}",
        reply_markup=get_back_to_menu_kb(),
    )

    if u and u.platform_user_id:
        try:
            await message.bot.send_message(
                u.platform_user_id,
                texts.PHONE_CHANGE_CONFIRMED.format(new_phone=new_phone),
            )
        except Exception as e:
            logger.warning("Cannot notify user %s about phone change: %s", u.platform_user_id, e)


@router.callback_query(F.data.startswith("admin_phone_reject_"))
async def cb_admin_phone_reject(callback: CallbackQuery):
    """Superadmin rejects phone change request."""
    from src.config import get_settings

    settings = get_settings()
    if callback.from_user.id not in settings.superadmin_ids:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    req_id = callback.data.replace("admin_phone_reject_", "")
    try:
        req_uuid = uuid.UUID(req_id)
    except ValueError:
        await callback.answer("Некорректный ID.")
        return

    from src.models.base import get_session_factory
    from src.models.phone_change_request import PhoneChangeRequest, PhoneChangeStatus
    from src.models.user import User
    from sqlalchemy import select
    from datetime import datetime

    session_factory = get_session_factory()
    async with session_factory() as session:
        req_r = await session.execute(
            select(PhoneChangeRequest).where(PhoneChangeRequest.id == req_uuid)
        )
        req = req_r.scalar_one_or_none()
        if not req or req.status != PhoneChangeStatus.PENDING:
            await callback.answer("Запрос не найден или уже обработан.")
            return

        req.status = PhoneChangeStatus.REJECTED
        req.resolved_at = datetime.utcnow()
        await session.commit()

        user_r = await session.execute(select(User).where(User.id == req.user_id))
        u = user_r.scalar_one_or_none()

    await callback.message.edit_text(texts.PHONE_CHANGE_REJECTED)
    await callback.answer()

    if u and u.platform_user_id:
        try:
            await callback.bot.send_message(
                u.platform_user_id,
                texts.PHONE_CHANGE_REJECTED_USER,
            )
        except Exception as e:
            logger.warning("Cannot notify user %s: %s", u.platform_user_id, e)
