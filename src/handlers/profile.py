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
    from src.services.motopair_service import raise_profile
    from src.models.user import UserRole

    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    role = "pilot" if user.role == UserRole.PILOT else "passenger"
    ok = await raise_profile(user.id, role)
    if ok:
        await callback.message.edit_text(
            "✅ Анкета поднята! Тебя будут видеть выше в поиске.",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        await callback.message.edit_text("Ошибка при поднятии анкеты.", reply_markup=get_back_to_menu_kb())
    await callback.answer()
