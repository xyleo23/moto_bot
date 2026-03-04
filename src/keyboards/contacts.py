"""Contacts keyboards."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_contacts_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="МотоМагазин", callback_data="contacts_motoshop")],
        [InlineKeyboardButton(text="МотоСервис", callback_data="contacts_motoservice")],
        [InlineKeyboardButton(text="МотоШкола", callback_data="contacts_motoschool")],
        [InlineKeyboardButton(text="МотоКлубы", callback_data="contacts_motoclubs")],
        [InlineKeyboardButton(text="МотоЭвакуатор", callback_data="contacts_motoevac")],
        [InlineKeyboardButton(text="Другое", callback_data="contacts_other")],
        [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
    ])


def get_contacts_list_kb(category: str, offset: int, total: int, has_more: bool, per_page: int = 5) -> InlineKeyboardMarkup:
    rows = []
    if offset > 0:
        rows.append([InlineKeyboardButton(text="◀ Пред", callback_data=f"contacts_page_{category}_{max(0, offset - per_page)}")])
    if has_more:
        rows.append([InlineKeyboardButton(text="След ▶", callback_data=f"contacts_page_{category}_{offset + per_page}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_contacts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_contacts_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить контакт", callback_data="admin_contact_add")],
        [InlineKeyboardButton(text="Список контактов", callback_data="admin_contact_list")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
    ])


def get_admin_contact_categories_kb(prefix: str = "admin_contact_add") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="МотоМагазин", callback_data=f"{prefix}_motoshop"),
            InlineKeyboardButton(text="МотоСервис", callback_data=f"{prefix}_motoservice"),
        ],
        [
            InlineKeyboardButton(text="МотоШкола", callback_data=f"{prefix}_motoschool"),
            InlineKeyboardButton(text="МотоКлубы", callback_data=f"{prefix}_motoclubs"),
        ],
        [
            InlineKeyboardButton(text="МотоЭвакуатор", callback_data=f"{prefix}_motoevac"),
            InlineKeyboardButton(text="Другое", callback_data=f"{prefix}_other"),
        ],
        [InlineKeyboardButton(text="« Отмена", callback_data="admin_contacts")],
    ])


def get_admin_contact_edit_kb(contact_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Изменить", callback_data=f"admin_contact_edit_{contact_id}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_contact_del_{contact_id}")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_contact_list")],
    ])
