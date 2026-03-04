"""Profile and subscription block."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb

router = Router()


@router.callback_query(F.data == "menu_profile")
async def cb_profile_menu(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.profile_service import get_profile_text
    from src.services.subscription import check_subscription_required

    text = await get_profile_text(user)
    sub_required = await check_subscription_required(user)

    kb_rows = [
        [InlineKeyboardButton(text="Редактировать анкету", callback_data="profile_edit")],
    ]
    if sub_required:
        kb_rows.append([InlineKeyboardButton(text="Оформить подписку", callback_data="profile_subscribe")])
    kb_rows.append([InlineKeyboardButton(text="Поднять анкету", callback_data="profile_raise")])
    kb_rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_main")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@router.callback_query(F.data == "profile_edit")
async def cb_profile_edit(callback: CallbackQuery, user=None):
    await callback.message.edit_text("Редактирование — в разработке.", reply_markup=get_back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "profile_subscribe")
async def cb_profile_subscribe(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.config import get_settings

    s = get_settings()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"1 месяц — {s.subscription_monthly_price // 100} ₽", callback_data="sub_monthly")],
        [InlineKeyboardButton(text=f"Сезон — {s.subscription_season_price // 100} ₽", callback_data="sub_season")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_profile")],
    ])
    await callback.message.edit_text("Выбери срок подписки:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "profile_raise")
async def cb_profile_raise(callback: CallbackQuery, user=None):
    await callback.message.edit_text("Поднять анкету — в разработке.", reply_markup=get_back_to_menu_kb())
    await callback.answer()
