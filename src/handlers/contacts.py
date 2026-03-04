"""Useful contacts block."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb

router = Router()


@router.callback_query(F.data == "menu_contacts")
async def cb_contacts_menu(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="МотоМагазин", callback_data="contacts_motoshop")],
        [InlineKeyboardButton(text="МотоСервис", callback_data="contacts_motoservice")],
        [InlineKeyboardButton(text="МотоШкола", callback_data="contacts_motoschool")],
        [InlineKeyboardButton(text="МотоКлубы", callback_data="contacts_motoclubs")],
        [InlineKeyboardButton(text="МотоЭвакуатор", callback_data="contacts_motoevac")],
        [InlineKeyboardButton(text="Другое", callback_data="contacts_other")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await callback.message.edit_text("📇 Полезные контакты", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("contacts_"))
async def cb_contacts_category(callback: CallbackQuery, user=None):
    from src.services.useful_contacts_service import get_contacts_by_category

    cat = callback.data.replace("contacts_", "")
    contacts = await get_contacts_by_category(user.city_id if user else None, cat)
    if not contacts:
        await callback.message.edit_text(f"Контактов в категории пока нет.", reply_markup=get_back_to_menu_kb())
    else:
        text = "\n\n".join(f"• {c['name']}\n{c.get('phone', c.get('link', ''))}" for c in contacts)
        await callback.message.edit_text(text[:4000], reply_markup=get_back_to_menu_kb())
    await callback.answer()

