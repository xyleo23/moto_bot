"""Contacts keyboards."""

from uuid import UUID

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def contact_callback_uid(value: UUID | str) -> str:
    """32-char hex for inline callback_data (Telegram max 64 bytes; UUID+long suffix was >64)."""
    if isinstance(value, UUID):
        return value.hex
    text = str(value).strip()
    if len(text) == 36 and text[8] == "-":
        return UUID(text).hex
    return text


def parse_contact_callback_uid(raw: str) -> UUID:
    """Parse id from callback (compact hex or legacy hyphenated UUID)."""
    text = (raw or "").strip()
    if len(text) == 32:
        try:
            return UUID(hex=text)
        except ValueError:
            pass
    return UUID(text)


def get_contacts_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="МотоМагазин", callback_data="contacts_motoshop")],
            [InlineKeyboardButton(text="МотоСервис", callback_data="contacts_motoservice")],
            [InlineKeyboardButton(text="МотоШкола", callback_data="contacts_motoschool")],
            [InlineKeyboardButton(text="МотоКлубы", callback_data="contacts_motoclubs")],
            [InlineKeyboardButton(text="МотоЭвакуатор", callback_data="contacts_motoevac")],
            [InlineKeyboardButton(text="Другое", callback_data="contacts_other")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ]
    )


def get_contacts_list_kb(
    category: str, offset: int, total: int, has_more: bool, per_page: int = 5
) -> InlineKeyboardMarkup:
    rows = []
    if offset > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="◀ Пред",
                    callback_data=f"contacts_page_{category}_{max(0, offset - per_page)}",
                )
            ]
        )
    if has_more:
        rows.append(
            [
                InlineKeyboardButton(
                    text="След ▶", callback_data=f"contacts_page_{category}_{offset + per_page}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="menu_contacts")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_contacts_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Добавить контакт", callback_data="admin_contact_add")],
            [InlineKeyboardButton(text="Список контактов", callback_data="admin_contact_list")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
        ]
    )


def get_admin_contact_categories_kb(prefix: str = "admin_contact_add") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
        ]
    )


def get_admin_contact_edit_kb(contact_id: UUID | str) -> InlineKeyboardMarkup:
    uid = contact_callback_uid(contact_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏ Изменить", callback_data=f"admin_contact_edit_{uid}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"admin_contact_del_{uid}"
                )
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_contact_list")],
        ]
    )


def get_admin_contact_edit_fields_kb(contact_id: UUID | str) -> InlineKeyboardMarkup:
    """Клавиатура выбора поля для редактирования."""
    uid = contact_callback_uid(contact_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Название", callback_data=f"admin_contact_ef_{uid}_name"
                ),
                InlineKeyboardButton(
                    text="Описание", callback_data=f"admin_contact_ef_{uid}_description"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Телефон", callback_data=f"admin_contact_ef_{uid}_phone"
                ),
                InlineKeyboardButton(
                    text="Ссылка", callback_data=f"admin_contact_ef_{uid}_link"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Адрес", callback_data=f"admin_contact_ef_{uid}_address"
                ),
                InlineKeyboardButton(
                    text="Категория", callback_data=f"admin_contact_ef_{uid}_category"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="« Назад", callback_data=f"admin_contact_view_{uid}"
                )
            ],
        ]
    )
