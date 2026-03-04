"""Admin: useful contacts CRUD."""
import uuid

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config import get_settings
from src.keyboards.contacts import (
    get_admin_contacts_menu_kb,
    get_admin_contact_categories_kb,
    get_admin_contact_edit_kb,
)
from src.keyboards.menu import get_back_to_menu_kb
from src.services.useful_contacts_service import (
    can_manage_contacts,
    create_contact,
    get_contact_by_id,
    update_contact,
    delete_contact,
    get_admin_contacts_list,
    CAT_LABELS,
)

router = Router()


def _is_superadmin(user_id: int) -> bool:
    return user_id in get_settings().superadmin_ids


class ContactAddStates(StatesGroup):
    category = State()
    name = State()
    description = State()
    phone = State()
    link = State()
    address = State()


@router.callback_query(F.data == "admin_contacts")
async def cb_admin_contacts(callback: CallbackQuery, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await callback.message.edit_text(
        "Контакты — управление",
        reply_markup=get_admin_contacts_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_contact_add")
async def cb_admin_contact_add_start(callback: CallbackQuery, state: FSMContext, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    if not user or not user.city_id:
        await callback.answer("Город не выбран.", show_alert=True)
        return
    await state.set_state(ContactAddStates.category)
    await callback.message.edit_text(
        "Выбери категорию:",
        reply_markup=get_admin_contact_categories_kb("admin_contact_add"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_add_"), ContactAddStates.category)
async def cb_admin_contact_add_category(callback: CallbackQuery, state: FSMContext, user=None):
    cat = callback.data.replace("admin_contact_add_", "")
    if cat not in ("motoshop", "motoservice", "motoschool", "motoclubs", "motoevac", "other"):
        await callback.answer()
        return
    await state.update_data(category=cat)
    await state.set_state(ContactAddStates.name)
    await callback.message.edit_text("Название контакта:")
    await callback.answer()


@router.message(ContactAddStates.name, F.text)
async def admin_contact_add_name(message: Message, state: FSMContext, user=None):
    await state.update_data(name=message.text.strip()[:200])
    await state.set_state(ContactAddStates.description)
    await message.answer("Описание (или «Пропустить»):")


@router.message(ContactAddStates.description, F.text)
async def admin_contact_add_description(message: Message, state: FSMContext, user=None):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(description=text[:1000] if text else None)
    await state.set_state(ContactAddStates.phone)
    await message.answer("Телефон (или «Пропустить»):")


@router.message(ContactAddStates.phone, F.text)
async def admin_contact_add_phone(message: Message, state: FSMContext, user=None):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(phone=text[:50] if text else None)
    await state.set_state(ContactAddStates.link)
    await message.answer("Ссылка (или «Пропустить»):")


@router.message(ContactAddStates.link, F.text)
async def admin_contact_add_link(message: Message, state: FSMContext, user=None):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(link=text[:500] if text else None)
    await state.set_state(ContactAddStates.address)
    await message.answer("Адрес (или «Пропустить»):")


@router.message(ContactAddStates.address, F.text)
async def admin_contact_add_address(message: Message, state: FSMContext, user=None):
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(address=text[:500] if text else None)
    data = await state.get_data()
    await state.clear()

    c = await create_contact(
        city_id=user.city_id,
        created_by=user.id,
        category=data["category"],
        name=data["name"],
        description=data.get("description"),
        phone=data.get("phone"),
        link=data.get("link"),
        address=data.get("address"),
    )
    if c:
        await message.answer(
            f"✅ Контакт добавлен: {c.name}",
            reply_markup=get_admin_contacts_menu_kb(),
        )
    else:
        await message.answer("Ошибка.", reply_markup=get_admin_contacts_menu_kb())


@router.callback_query(F.data == "admin_contact_list")
async def cb_admin_contact_list(callback: CallbackQuery, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    if not user or not user.city_id:
        await callback.answer("Город не выбран.", show_alert=True)
        return

    contacts = await get_admin_contacts_list(user.city_id)
    if not contacts:
        await callback.message.edit_text(
            "Контактов нет.",
            reply_markup=get_admin_contacts_menu_kb(),
        )
    else:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        rows = []
        for c in contacts[:15]:
            label = CAT_LABELS.get(c.category.value, c.category.value)
            rows.append([InlineKeyboardButton(
                text=f"{c.name} ({label})",
                callback_data=f"admin_contact_view_{c.id}",
            )])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_contacts")])
        await callback.message.edit_text(
            "Контакты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_view_"))
async def cb_admin_contact_view(callback: CallbackQuery, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_contact_view_", "")
    c = await get_contact_by_id(uuid.UUID(cid))
    if not c:
        await callback.answer("Не найден.", show_alert=True)
        return
    text = (
        f"<b>{c.name}</b>\n"
        f"Категория: {CAT_LABELS.get(c.category.value, c.category.value)}\n"
        f"Описание: {c.description or '—'}\n"
        f"Телефон: {c.phone or '—'}\n"
        f"Ссылка: {c.link or '—'}\n"
        f"Адрес: {c.address or '—'}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_contact_edit_kb(cid))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_del_"))
async def cb_admin_contact_del(callback: CallbackQuery, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_contact_del_", "")
    ok = await delete_contact(uuid.UUID(cid))
    if ok:
        await callback.message.edit_text(
            "Контакт удалён.",
            reply_markup=get_admin_contacts_menu_kb(),
        )
    else:
        await callback.answer("Ошибка.", show_alert=True)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_edit_"))
async def cb_admin_contact_edit(callback: CallbackQuery, user=None):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await callback.message.edit_text(
        "Редактирование контакта — в разработке. Пока доступно только удаление.",
        reply_markup=get_admin_contact_edit_kb(callback.data.replace("admin_contact_edit_", "")),
    )
    await callback.answer()


