"""Subscription and payment handlers."""

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.services.payment import create_payment
from src.config import get_settings
from src.usecases.payment_metadata import subscription_metadata
from src import texts
from src.models.user import effective_user_id
from src.keyboards.menu import get_back_to_menu_kb
from src.utils.tg_callback_message import edit_text_or_send_new

router = Router()


class SubscriptionPayStates(StatesGroup):
    awaiting = State()


@router.callback_query(F.data.in_(("sub_monthly", "sub_season", "sub_year")))
async def cb_subscribe(
    callback: CallbackQuery, state: FSMContext, user=None, bot=None
):
    from src.services.admin_service import get_subscription_settings

    if callback.data == "sub_monthly":
        period = "monthly"
    elif callback.data in ("sub_season", "sub_year"):
        period = "season"
    else:
        await callback.answer("Неизвестный тип подписки.")
        return

    # БД — приоритет, env — fallback
    s = get_settings()
    settings_db = await get_subscription_settings()
    if period == "monthly":
        amount = (
            settings_db.monthly_price_kopecks
            if settings_db and settings_db.monthly_price_kopecks
            else s.subscription_monthly_price
        )
    else:
        amount = (
            settings_db.season_price_kopecks
            if settings_db and settings_db.season_price_kopecks
            else s.subscription_season_price
        )

    payment = await create_payment(
        amount_kopecks=amount,
        description=f"Подписка {period}",
        metadata=subscription_metadata(user, period, platform="telegram"),
        return_url=get_settings().telegram_return_url or "https://t.me",
    )
    if not payment or not payment.get("confirmation_url"):
        await edit_text_or_send_new(
            callback,
            "Оплата временно недоступна. Попробуй позже.",
        )
        await callback.answer()
        return

    await state.set_state(SubscriptionPayStates.awaiting)
    await state.update_data(sub_payment_id=payment["id"], sub_period=period)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
            [
                InlineKeyboardButton(
                    text="✅ Я оплатил — проверить",
                    callback_data="subscription_checkpay",
                )
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
        ]
    )
    await edit_text_or_send_new(
        callback,
        texts.SUBSCRIPTION_PAY_FOLLOWUP_TG,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "subscription_checkpay")
async def cb_subscription_checkpay(callback: CallbackQuery, state: FSMContext, user=None):
    """User completed YooKassa redirect; webhook may lag — verify and activate."""
    from src.services.payment import check_payment_status
    from src.services.subscription import activate_subscription

    if await state.get_state() != SubscriptionPayStates.awaiting:
        await callback.answer(
            "Сначала выбери тариф и открой ссылку на оплату.",
            show_alert=True,
        )
        return

    data = await state.get_data()
    payment_id = data.get("sub_payment_id")
    period = data.get("sub_period")

    if not payment_id or not period:
        await callback.answer("Ошибка: платёж не найден.", show_alert=True)
        return

    status = await check_payment_status(payment_id)
    if status == "succeeded":
        await state.clear()
        period_arg = period if period == "monthly" else "season"
        ok = await activate_subscription(
            effective_user_id(user), period_arg, payment_id
        )
        if ok:
            await edit_text_or_send_new(
                callback,
                "✅ Оплата прошла! Подписка активирована. Открой «👤 Профиль», чтобы увидеть дату.",
                reply_markup=get_back_to_menu_kb(),
            )
        else:
            await edit_text_or_send_new(
                callback,
                "Оплата прошла, но активировать подписку не удалось. Обратись в поддержку.",
                reply_markup=get_back_to_menu_kb(),
            )
        await callback.answer()
    elif status == "canceled":
        await state.clear()
        await edit_text_or_send_new(
            callback, "❌ Платёж отменён.", reply_markup=get_back_to_menu_kb()
        )
        await callback.answer()
    else:
        await callback.answer(
            "Платёж ещё не обработан. Подожди несколько секунд и попробуй ещё раз.",
            show_alert=True,
        )
