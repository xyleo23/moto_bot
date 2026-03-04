"""About us block."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb

router = Router()


@router.callback_query(F.data == "menu_about")
async def cb_about(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.config import get_settings

    s = get_settings()
    text = """ℹ️ О нас

Бот мото-сообщества Екатеринбурга.
Объединяем пилотов и двоек, помогаем в экстренных ситуациях.

📧 Поддержка: {email}
👤 Telegram: @{username}""".format(
        email=s.support_email,
        username=s.support_username,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Написать в поддержку", url=f"https://t.me/{s.support_username}")],
        [InlineKeyboardButton(text="Поддержать проект", callback_data="about_donate")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "about_donate")
async def cb_about_donate(callback: CallbackQuery):
    await callback.message.edit_text("Донат — в разработке (ЮKassa).", reply_markup=get_back_to_menu_kb())
    await callback.answer()
