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
    get_admin_contact_edit_fields_kb,
)
from src.services.useful_contacts_service import (
    can_manage_contacts,
    can_manage_contact_effective,
    create_contact,
    get_contact_by_id,
    update_contact,
    delete_contact,
    get_admin_contacts_list,
    CAT_LABELS,
)

router = Router()


class ContactAddStates(StatesGroup):
    city = State()
    category = State()
    name = State()
    description = State()
    phone = State()
    link = State()
    address = State()


class ContactEditStates(StatesGroup):
    """Editing single field of a contact."""

    value = State()


@router.callback_query(F.data == "admin_contacts")
async def cb_admin_contacts(callback: CallbackQuery, user=None):
    from src.services.useful_contacts_service import can_manage_contacts

    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return
    await callback.message.edit_text(
        "Контакты — управление",
        reply_markup=get_admin_contacts_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_contact_add")
async def cb_admin_contact_add_start(callback: CallbackQuery, state: FSMContext, user=None):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.admin_service import get_cities

    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return

    # Superadmins can choose any city; regular city admins use their own city
    is_superadmin = (
        hasattr(user, "platform_user_id")
        and user.platform_user_id in get_settings().superadmin_ids
    )
    if is_superadmin:
        cities = await get_cities()
        if not cities:
            await callback.answer("Нет городов в базе.", show_alert=True)
            return
        rows = [
            [InlineKeyboardButton(text=c.name, callback_data=f"admin_contact_city_{c.id}")]
            for c in cities
        ]
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_contacts")])
        await state.set_state(ContactAddStates.city)
        await callback.message.edit_text(
            "Выбери город для нового контакта:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    else:
        if not user.city_id:
            await callback.answer("Город не выбран.", show_alert=True)
            return
        await state.update_data(contact_city_id=str(user.city_id))
        await state.set_state(ContactAddStates.category)
        await callback.message.edit_text(
            "Выбери категорию:",
            reply_markup=get_admin_contact_categories_kb("admin_contact_add"),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_city_"), ContactAddStates.city)
async def cb_admin_contact_city_select(callback: CallbackQuery, state: FSMContext, user=None):
    city_id_str = callback.data.replace("admin_contact_city_", "")
    await state.update_data(contact_city_id=city_id_str)
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
    import uuid as _uuid

    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-"):
        text = None
    await state.update_data(address=text[:500] if text else None)
    data = await state.get_data()
    await state.clear()

    # Use FSM-stored city (set in city selection step or defaulted to user.city_id)
    raw_city_id = data.get("contact_city_id") or (str(user.city_id) if user and user.city_id else None)
    if not raw_city_id:
        await message.answer("Ошибка: город не выбран.", reply_markup=get_admin_contacts_menu_kb())
        return
    try:
        contact_city_id = _uuid.UUID(raw_city_id)
    except (ValueError, TypeError):
        await message.answer("Ошибка: неверный ID города.", reply_markup=get_admin_contacts_menu_kb())
        return

    c = await create_contact(
        city_id=contact_city_id,
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
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
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
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{c.name} ({label})",
                        callback_data=f"admin_contact_view_{c.id}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_contacts")])
        await callback.message.edit_text(
            "Контакты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_view_"))
async def cb_admin_contact_view(callback: CallbackQuery, user=None):
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_contact_view_", "")
    c = await get_contact_by_id(uuid.UUID(cid))
    if not c:
        await callback.answer("Не найден.", show_alert=True)
        return
    if not await can_manage_contact_effective(user, c):
        await callback.answer("Доступ запрещён.", show_alert=True)
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
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_contact_del_", "")
    c = await get_contact_by_id(uuid.UUID(cid))
    if not c:
        await callback.answer("Не найден.", show_alert=True)
        return
    if not await can_manage_contact_effective(user, c):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
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
async def cb_admin_contact_edit(callback: CallbackQuery, state: FSMContext, user=None):
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_contact_edit_", "")
    c = await get_contact_by_id(uuid.UUID(cid))
    if not c:
        await callback.answer("Контакт не найден.", show_alert=True)
        return
    if not await can_manage_contact_effective(user, c):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        f"Выбери поле для редактирования контакта <b>{c.name}</b>:",
        reply_markup=get_admin_contact_edit_fields_kb(cid),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_ef_"))
async def cb_admin_contact_edit_field(callback: CallbackQuery, state: FSMContext, user=None):
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return
    # admin_contact_ef_{cid}_{field}
    parts = callback.data.replace("admin_contact_ef_", "").split("_", 1)
    if len(parts) != 2:
        await callback.answer()
        return
    cid, field = parts[0], parts[1]
    if field not in ("name", "description", "phone", "link", "address", "category"):
        await callback.answer()
        return
    c = await get_contact_by_id(uuid.UUID(cid))
    if not c:
        await callback.answer("Контакт не найден.", show_alert=True)
        return
    if not await can_manage_contact_effective(user, c):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    prompts = {
        "name": "Введи новое название:",
        "description": "Введи новое описание (или «Пропустить» для очистки):",
        "phone": "Введи новый телефон (или «Пропустить» для очистки):",
        "link": "Введи новую ссылку (или «Пропустить» для очистки):",
        "address": "Введи новый адрес (или «Пропустить» для очистки):",
        "category": "Выбери категорию:",
    }
    await state.update_data(contact_edit_id=cid, contact_edit_field=field)
    await state.set_state(ContactEditStates.value)
    if field == "category":
        await callback.message.edit_text(
            "Выбери новую категорию:",
            reply_markup=get_admin_contact_categories_kb(f"admin_contact_ev_{cid}"),
        )
    else:
        await callback.message.edit_text(prompts[field])
    await callback.answer()


@router.callback_query(F.data.startswith("admin_contact_ev_"), ContactEditStates.value)
async def cb_admin_contact_edit_value_category(
    callback: CallbackQuery, state: FSMContext, user=None
):
    """Обработка выбора категории при редактировании."""
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        await callback.answer("Доступ запрещён.")
        return
    # admin_contact_ev_{cid}_{category}
    raw = callback.data.replace("admin_contact_ev_", "")
    parts = raw.split("_", 1)
    if len(parts) != 2:
        await callback.answer()
        return
    cid, cat = parts[0], parts[1]
    if cat not in ("motoshop", "motoservice", "motoschool", "motoclubs", "motoevac", "other"):
        await callback.answer()
        return
    data = await state.get_data()
    if data.get("contact_edit_field") != "category" or data.get("contact_edit_id") != cid:
        await callback.answer()
        return
    contact = await get_contact_by_id(uuid.UUID(cid))
    if not contact:
        await state.clear()
        await callback.answer("Контакт не найден.", show_alert=True)
        return
    if not await can_manage_contact_effective(user, contact):
        await state.clear()
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    ok = await update_contact(uuid.UUID(cid), category=cat)
    await state.clear()
    if ok:
        c = await get_contact_by_id(uuid.UUID(cid))
        text = (
            f"✅ Категория обновлена.\n\n<b>{c.name}</b>\n"
            f"Категория: {CAT_LABELS.get(c.category.value, c.category.value)}\n"
            f"Описание: {c.description or '—'}\nТелефон: {c.phone or '—'}\n"
            f"Ссылка: {c.link or '—'}\nАдрес: {c.address or '—'}"
        )
        await callback.message.edit_text(text, reply_markup=get_admin_contact_edit_kb(cid))
    else:
        await callback.message.edit_text("Ошибка.", reply_markup=get_admin_contact_edit_kb(cid))
    await callback.answer()


@router.message(ContactEditStates.value, F.text)
async def admin_contact_edit_value_message(message: Message, state: FSMContext, user=None):
    if not user or not await can_manage_contacts(
        user.id, user.city_id, get_settings().superadmin_ids
    ):
        return
    data = await state.get_data()
    cid = data.get("contact_edit_id")
    field = data.get("contact_edit_field")
    if not cid or not field or field == "category":
        await state.clear()
        return
    contact = await get_contact_by_id(uuid.UUID(cid))
    if not contact or not await can_manage_contact_effective(user, contact):
        await state.clear()
        await message.answer("Доступ запрещён.")
        return
    text = message.text.strip()
    if text.lower() in ("пропустить", "skip", "-") and field != "name":
        text = None
    elif field == "name" and not text:
        await message.answer("Название не может быть пустым.")
        return
    updates = {field: text if text else None}
    ok = await update_contact(uuid.UUID(cid), **updates)
    await state.clear()
    if ok:
        c = await get_contact_by_id(uuid.UUID(cid))
        text_msg = (
            f"✅ Поле обновлено.\n\n<b>{c.name}</b>\n"
            f"Категория: {CAT_LABELS.get(c.category.value, c.category.value)}\n"
            f"Описание: {c.description or '—'}\nТелефон: {c.phone or '—'}\n"
            f"Ссылка: {c.link or '—'}\nАдрес: {c.address or '—'}"
        )
        await message.answer(text_msg, reply_markup=get_admin_contact_edit_kb(cid))
    else:
        await message.answer("Ошибка.", reply_markup=get_admin_contacts_menu_kb())
