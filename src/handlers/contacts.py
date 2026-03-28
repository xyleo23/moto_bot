"""Useful contacts block."""

from aiogram import Router, F
from aiogram.types import CallbackQuery

from src.keyboards.menu import get_back_to_menu_kb
from src.keyboards.contacts import (
    get_contacts_menu_kb,
    get_contacts_list_kb,
)
from src.services.useful_contacts_service import (
    get_contacts_by_category,
    CAT_LABELS,
    CONTACTS_PER_PAGE,
    format_useful_contact_html,
)

router = Router()


def _format_contact(c: dict) -> str:
    return format_useful_contact_html(c)


@router.callback_query(F.data == "menu_contacts")
async def cb_contacts_menu(callback: CallbackQuery, user=None):
    await callback.message.edit_text("📇 Полезные контакты", reply_markup=get_contacts_menu_kb())
    await callback.answer()


@router.callback_query(
    F.data.regexp(r"^contacts_(motoshop|motoservice|motoschool|motoclubs|motoevac|other)$")
)
async def cb_contacts_category(callback: CallbackQuery, user=None):
    cat = callback.data.replace("contacts_", "")
    contacts, total, has_more = await get_contacts_by_category(
        user.city_id if user else None,
        cat,
        offset=0,
        limit=CONTACTS_PER_PAGE,
    )
    if not contacts:
        await callback.message.edit_text(
            f"Контактов в категории «{CAT_LABELS.get(cat, cat)}» пока нет.",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        label = CAT_LABELS.get(cat, cat)
        text = f"<b>{label}</b>\n\n"
        text += "\n\n".join(_format_contact(c) for c in contacts)
        if total > CONTACTS_PER_PAGE:
            text += f"\n\n📄 1–{len(contacts)} из {total}"
        await callback.message.edit_text(
            text[:4000],
            reply_markup=get_contacts_list_kb(cat, 0, total, has_more),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("contacts_page_"))
async def cb_contacts_page(callback: CallbackQuery, user=None):
    parts = callback.data.replace("contacts_page_", "").split("_")
    if len(parts) < 3:
        await callback.answer()
        return
    cat = parts[0]
    offset = int(parts[1])
    contacts, total, has_more = await get_contacts_by_category(
        user.city_id if user else None,
        cat,
        offset=offset,
        limit=CONTACTS_PER_PAGE,
    )
    if not contacts:
        await callback.message.edit_text(
            "Контактов нет.",
            reply_markup=get_back_to_menu_kb(),
        )
    else:
        label = CAT_LABELS.get(cat, cat)
        text = f"<b>{label}</b>\n\n"
        text += "\n\n".join(_format_contact(c) for c in contacts)
        text += f"\n\n📄 {offset + 1}–{offset + len(contacts)} из {total}"
        await callback.message.edit_text(
            text[:4000],
            reply_markup=get_contacts_list_kb(cat, offset, total, has_more),
        )
    await callback.answer()
