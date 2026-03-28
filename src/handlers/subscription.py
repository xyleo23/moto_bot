"""Subscription and payment handlers."""

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery

from src.services.payment import create_payment
from src.config import get_settings
from src.usecases.payment_metadata import subscription_metadata
from src import texts
from src.utils.tg_callback_message import edit_text_or_send_new

router = Router()


@router.callback_query(F.data.startswith("sub_"))
async def cb_subscribe(callback: CallbackQuery, user=None, bot=None):
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

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
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
