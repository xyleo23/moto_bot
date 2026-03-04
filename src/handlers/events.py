"""Events block."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb

router = Router()


@router.callback_query(F.data == "menu_events")
async def cb_events_menu(callback: CallbackQuery, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать мероприятие", callback_data="event_create")],
        [InlineKeyboardButton(text="Просмотреть мероприятия", callback_data="event_list")],
        [InlineKeyboardButton(text="Мои мероприятия", callback_data="event_my")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])
    await callback.message.edit_text("📅 Мероприятия", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "event_list")
async def cb_event_list(callback: CallbackQuery, user=None):
    from src.services.event_service import get_events_list

    events = await get_events_list(user.city_id if user else None)
    if not events:
        await callback.message.edit_text("Мероприятий пока нет.", reply_markup=get_back_to_menu_kb())
    else:
        text = "Мероприятия:\n\n" + "\n\n".join(
            f"• {e.get('title', e.get('type', 'Мероприятие'))} — {e.get('date', '')}"
            for e in events[:10]
        )
        await callback.message.edit_text(text, reply_markup=get_back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data.in_(["event_create", "event_my"]))
async def cb_event_create_or_my(callback: CallbackQuery, user=None):
    if callback.data == "event_create":
        await callback.message.edit_text("Создание мероприятия — в разработке. Скоро!", reply_markup=get_back_to_menu_kb())
    else:
        await callback.message.edit_text("Мои мероприятия — в разработке.", reply_markup=get_back_to_menu_kb())
    await callback.answer()
