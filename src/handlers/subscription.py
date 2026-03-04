"""Subscription and payment handlers."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from src.services.payment import create_payment
from src.services.subscription import activate_subscription
from src.config import get_settings

router = Router()


@router.callback_query(F.data.startswith("sub_"))
async def cb_subscribe(callback: CallbackQuery, user=None, bot=None):
    if callback.data == "sub_monthly":
        period = "monthly"
        amount = get_settings().subscription_monthly_price
    elif callback.data == "sub_season":
        period = "season"
        amount = get_settings().subscription_season_price
    else:
        await callback.answer("Неизвестный тип подписки.")
        return

    payment = await create_payment(
        amount_kopecks=amount,
        description=f"Подписка {period}",
        metadata={"user_id": str(user.id), "type": "subscription", "period": period},
    )
    if not payment or not payment.get("confirmation_url"):
        await callback.message.edit_text(
            "Оплата временно недоступна. Попробуй позже.",
        )
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить", url=payment["confirmation_url"])],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
    ])
    await callback.message.edit_text(
        "Перейди по ссылке для оплаты. После оплаты нажми /start для обновления статуса.",
        reply_markup=kb,
    )
    await callback.answer()
