"""Admin panel."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command

from src.config import get_settings

router = Router()


def _is_superadmin(user_id: int) -> bool:
    return user_id in get_settings().superadmin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not _is_superadmin(message.from_user.id):
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Полезные контакты", callback_data="admin_contacts")],
        [InlineKeyboardButton(text="Настройки", callback_data="admin_settings")],
    ])
    await message.answer("Админ-панель", reply_markup=kb)


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Полезные контакты", callback_data="admin_contacts")],
        [InlineKeyboardButton(text="Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await callback.message.edit_text("Админ-панель", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return

    from src.services.admin_service import get_stats

    stats = await get_stats()
    text = f"Пользователей: {stats.get('users', 0)}\nСобытий SOS: {stats.get('sos', 0)}\nМероприятий: {stats.get('events', 0)}"
    from src.keyboards.menu import get_back_to_menu_kb
    await callback.message.edit_text(text, reply_markup=get_back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return

    await callback.message.edit_text("Настройки — в разработке.")
    await callback.answer()
