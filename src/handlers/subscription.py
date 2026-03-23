"""Subscription and payment handlers."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from src.services.payment import create_payment
from src.config import get_settings

router = Router()


@router.callback_query(F.data.startswith("sub_"))
async def cb_subscribe(callback: CallbackQuery, user=None, bot=None):
    from src.services.admin_service import get_subscription_settings

    if callback.data == "sub_monthly":
        period = "monthly"
    elif callback.data == "sub_season":
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
        metadata={"user_id": str(user.id), "type": "subscription", "period": period},
        return_url=get_settings().telegram_return_url or "https://t.me",
    )
    if not payment or not payment.get("confirmation_url"):
        await callback.message.edit_text(
            "Оплата временно недоступна. Попробуй позже.",
        )
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
    ])
    await callback.message.edit_text(
        "Перейди по ссылке для оплаты. После оплаты нажми /start для обновления статуса.",
        reply_markup=kb,
    )
    await callback.answer()
