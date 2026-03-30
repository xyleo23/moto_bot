"""CRUD полезных контактов в MAX (те же callback_data, что в Telegram)."""

from __future__ import annotations

import uuid

from src.keyboards.contacts import (
    get_admin_contact_categories_kb,
    get_admin_contact_edit_fields_kb,
    get_admin_contact_edit_kb,
    get_admin_contacts_menu_kb,
)
from src.keyboards.shared import append_main_menu_shortcut_row, get_main_menu_shortcut_row, max_kb_from_tg_inline
from src.models.user import User
from src.platforms.base import Button
from src.platforms.max_adapter import MaxAdapter
from src.services import max_registration_state as reg_state
from src.services.user import get_or_create_user
from src.services.useful_contacts_service import (
    CAT_LABELS,
    can_manage_contact_effective,
    create_contact,
    delete_contact,
    get_cities_for_contact_admin,
    get_admin_contacts_with_cities_for_manager,
    format_useful_contact_admin_view,
    get_contact_by_id,
    update_contact,
    can_manage_contacts_effective,
)

_VALID_CATS = frozenset(
    {"motoshop", "motoservice", "motoschool", "motoclubs", "motoevac", "other"}
)
_EDIT_FIELDS = frozenset({"name", "description", "phone", "link", "address", "category"})


async def _deny(adapter: MaxAdapter, chat_id: str) -> None:
    await adapter.send_message(
        chat_id,
        "Доступ запрещён.",
        append_main_menu_shortcut_row([[Button("« Меню", payload="menu_main")]]),
    )


async def max_contacts_try_dispatch(
    adapter: MaxAdapter, chat_id: str, user: User, data: str
) -> bool:
    """True если callback относится к админке контактов и обработан."""
    if data != "admin_contacts" and not data.startswith("admin_contact"):
        return False

    if not await can_manage_contacts_effective(user):
        await _deny(adapter, chat_id)
        return True

    if data == "admin_contacts":
        await adapter.send_message(
            chat_id,
            "📇 <b>Контакты</b> — управление",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contacts_menu_kb())),
        )
        return True

    if data == "admin_contact_add":
        cities = await get_cities_for_contact_admin(user)
        if not cities:
            await adapter.send_message(
                chat_id,
                "Нет доступных городов для контактов.",
                append_main_menu_shortcut_row([[Button("« Назад", payload="admin_contacts")]]),
            )
            return True
        if len(cities) == 1:
            await reg_state.set_state(
                user.platform_user_id,
                "admin:contact_add_city",
                {"city_id": str(cities[0].id)},
            )
            await adapter.send_message(
                chat_id,
                f"Город: <b>{cities[0].name}</b>\n\nВыбери категорию:",
                append_main_menu_shortcut_row(
                    max_kb_from_tg_inline(get_admin_contact_categories_kb("admin_contact_add"))
                ),
            )
            return True
        rows = [
            [
                Button(
                    (f"{c.name} · выкл" if not c.is_active else c.name),
                    payload=f"admin_contact_city_{c.id}",
                )
            ]
            for c in cities
        ]
        rows.append([Button("« Назад", payload="admin_contacts")])
        rows.append(get_main_menu_shortcut_row())
        await adapter.send_message(
            chat_id,
            "<b>Новый контакт</b>\n\nСначала выбери город («выкл» — скрыт для пользователей в выборе города):",
            rows,
        )
        return True

    if data.startswith("admin_contact_city_"):
        city_id_str = data.replace("admin_contact_city_", "")
        await reg_state.set_state(
            user.platform_user_id,
            "admin:contact_add_city",
            {"city_id": city_id_str},
        )
        await adapter.send_message(
            chat_id,
            "Выбери категорию:",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contact_categories_kb("admin_contact_add"))),
        )
        return True

    if data.startswith("admin_contact_add_") and data != "admin_contact_add":
        cat = data.replace("admin_contact_add_", "", 1)
        if cat not in _VALID_CATS:
            return True
        # Retrieve city_id: prefer city stored in FSM from city selection step
        city_fsm = await reg_state.get_state(user.platform_user_id)
        fsm_city_id = None
        if city_fsm and city_fsm.get("state") == "admin:contact_add_city":
            fsm_city_id = city_fsm.get("data", {}).get("city_id")
        city_id_to_use = fsm_city_id or (str(user.city_id) if user.city_id else None)
        if not city_id_to_use:
            await adapter.send_message(
                chat_id,
                "Город не выбран.",
                append_main_menu_shortcut_row([[Button("« Назад", payload="admin_contacts")]]),
            )
            return True
        await reg_state.set_state(
            user.platform_user_id,
            "admin:contact_add",
            {"category": cat, "step": "name", "city_id": city_id_to_use},
        )
        await adapter.send_message(
            chat_id,
            "Название контакта:",
            [[Button("« Отмена", payload="admin_contacts")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_contact_list":
        pairs = await get_admin_contacts_with_cities_for_manager(user)
        if not pairs:
            await adapter.send_message(
                chat_id,
                "Контактов нет.",
                append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contacts_menu_kb())),
            )
            return True
        distinct_cities = {cn for _, cn in pairs}
        multi_city = len(distinct_cities) > 1
        rows = []
        for c, city_name in pairs[:15]:
            label = CAT_LABELS.get(c.category.value, c.category.value)
            prefix = f"{city_name} · " if multi_city else ""
            rows.append(
                [Button(f"{prefix}{c.name} ({label})", payload=f"admin_contact_view_{c.id}")]
            )
        rows.append([Button("« Назад", payload="admin_contacts")])
        await adapter.send_message(chat_id, "Контакты:", append_main_menu_shortcut_row(rows))
        return True

    if data.startswith("admin_contact_view_"):
        cid_s = data.replace("admin_contact_view_", "", 1)
        try:
            cuid = uuid.UUID(cid_s)
        except ValueError:
            return True
        c = await get_contact_by_id(cuid)
        if not c:
            await adapter.send_message(chat_id, "Не найден.", append_main_menu_shortcut_row(None))
            return True
        if not await can_manage_contact_effective(user, c):
            await _deny(adapter, chat_id)
            return True
        body = await format_useful_contact_admin_view(c)
        await adapter.send_message(
            chat_id,
            body,
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contact_edit_kb(cid_s))),
        )
        return True

    if data.startswith("admin_contact_del_"):
        cid_s = data.replace("admin_contact_del_", "", 1)
        try:
            cuid = uuid.UUID(cid_s)
        except ValueError:
            return True
        c = await get_contact_by_id(cuid)
        if not c:
            await adapter.send_message(chat_id, "Не найден.", append_main_menu_shortcut_row(None))
            return True
        if not await can_manage_contact_effective(user, c):
            await _deny(adapter, chat_id)
            return True
        ok = await delete_contact(cuid)
        if ok:
            await adapter.send_message(
                chat_id,
                "Контакт удалён.",
                append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contacts_menu_kb())),
            )
        else:
            await adapter.send_message(chat_id, "Ошибка.", append_main_menu_shortcut_row(None))
        return True

    if data.startswith("admin_contact_edit_"):
        cid_s = data.replace("admin_contact_edit_", "", 1)
        try:
            cuid = uuid.UUID(cid_s)
        except ValueError:
            return True
        c = await get_contact_by_id(cuid)
        if not c:
            await adapter.send_message(chat_id, "Контакт не найден.", append_main_menu_shortcut_row(None))
            return True
        if not await can_manage_contact_effective(user, c):
            await _deny(adapter, chat_id)
            return True
        await reg_state.clear_state(user.platform_user_id)
        await adapter.send_message(
            chat_id,
            f"Поля контакта <b>{c.name}</b>:",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contact_edit_fields_kb(cid_s))),
        )
        return True

    if data.startswith("admin_contact_ef_"):
        rest = data.replace("admin_contact_ef_", "", 1)
        idx = rest.rfind("_")
        if idx < 0:
            return True
        cid_s, field = rest[:idx], rest[idx + 1 :]
        if field not in _EDIT_FIELDS:
            return True
        try:
            cuid = uuid.UUID(cid_s)
        except ValueError:
            return True
        c = await get_contact_by_id(cuid)
        if not c:
            await adapter.send_message(chat_id, "Контакт не найден.", append_main_menu_shortcut_row(None))
            return True
        if not await can_manage_contact_effective(user, c):
            await _deny(adapter, chat_id)
            return True
        prompts = {
            "name": "Введи новое название:",
            "description": "Введи описание или «Пропустить» для очистки:",
            "phone": "Введи телефон или «Пропустить» для очистки:",
            "link": "Введи ссылку или «Пропустить» для очистки:",
            "address": "Введи адрес или «Пропустить» для очистки:",
        }
        if field == "category":
            await reg_state.set_state(
                user.platform_user_id,
                "admin:contact_edit",
                {"contact_id": cid_s, "field": "category"},
            )
            await adapter.send_message(
                chat_id,
                "Выбери категорию:",
                append_main_menu_shortcut_row(
                    max_kb_from_tg_inline(get_admin_contact_categories_kb(f"admin_contact_ev_{cid_s}"))
                ),
            )
            return True
        await reg_state.set_state(
            user.platform_user_id,
            "admin:contact_edit",
            {"contact_id": cid_s, "field": field},
        )
        await adapter.send_message(
            chat_id,
            prompts[field],
            [[Button("« Отмена", payload=f"admin_contact_view_{cid_s}")], get_main_menu_shortcut_row()],
        )
        return True

    return False


async def handle_max_contact_fsm_text(
    adapter: MaxAdapter, chat_id: str, user_id: int, text: str, fsm: dict
) -> None:
    state = fsm.get("state") or ""
    data = fsm.get("data") or {}
    u = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not u or not await can_manage_contacts_effective(u):
        await reg_state.clear_state(user_id)
        return

    raw = (text or "").strip()

    if state == "admin:contact_add":
        # Use FSM-stored city_id (set during city selection) or fallback to user.city_id
        raw_city_id = data.get("city_id") or (str(u.city_id) if u.city_id else None)
        if not raw_city_id:
            await reg_state.clear_state(user_id)
            return
        step = data.get("step")
        cat = data.get("category")
        if step == "name":
            if not raw:
                await adapter.send_message(chat_id, "Введи название.", append_main_menu_shortcut_row(None))
                return
            data["name"] = raw[:200]
            data["step"] = "description"
            await reg_state.set_state(user_id, state, data)
            await adapter.send_message(
                chat_id,
                "Описание (или «Пропустить»):",
                [[Button("« Отмена", payload="admin_contacts")], get_main_menu_shortcut_row()],
            )
            return
        if step == "description":
            if raw.lower() in ("пропустить", "skip", "-"):
                raw = ""
            data["description"] = raw[:1000] if raw else None
            data["step"] = "phone"
            await reg_state.set_state(user_id, state, data)
            await adapter.send_message(chat_id, "Телефон (или «Пропустить»):", append_main_menu_shortcut_row(None))
            return
        if step == "phone":
            if raw.lower() in ("пропустить", "skip", "-"):
                raw = ""
            data["phone"] = raw[:50] if raw else None
            data["step"] = "link"
            await reg_state.set_state(user_id, state, data)
            await adapter.send_message(chat_id, "Ссылка (или «Пропустить»):", append_main_menu_shortcut_row(None))
            return
        if step == "link":
            if raw.lower() in ("пропустить", "skip", "-"):
                raw = ""
            data["link"] = raw[:500] if raw else None
            data["step"] = "address"
            await reg_state.set_state(user_id, state, data)
            await adapter.send_message(chat_id, "Адрес (или «Пропустить»):", append_main_menu_shortcut_row(None))
            return
        if step == "address":
            if raw.lower() in ("пропустить", "skip", "-"):
                raw = ""
            data["address"] = raw[:500] if raw else None
            import uuid as _uuid
            try:
                contact_city_id = _uuid.UUID(raw_city_id)
            except (ValueError, TypeError):
                await reg_state.clear_state(user_id)
                await adapter.send_message(chat_id, "Ошибка: неверный ID города.", append_main_menu_shortcut_row(None))
                return
            c = await create_contact(
                city_id=contact_city_id,
                created_by=u.id,
                category=cat,
                name=data["name"],
                description=data.get("description"),
                phone=data.get("phone"),
                link=data.get("link"),
                address=data.get("address"),
            )
            await reg_state.clear_state(user_id)
            if c:
                await adapter.send_message(
                    chat_id,
                    f"✅ Контакт добавлен: {c.name}",
                    append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contacts_menu_kb())),
                )
            else:
                await adapter.send_message(
                    chat_id,
                    "Ошибка при сохранении.",
                    append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contacts_menu_kb())),
                )
            return

    if state == "admin:contact_edit":
        cid_s = data.get("contact_id")
        field = data.get("field")
        if not cid_s or not field or field == "category":
            return
        try:
            cuid = uuid.UUID(str(cid_s))
        except ValueError:
            await reg_state.clear_state(user_id)
            return
        contact = await get_contact_by_id(cuid)
        if not contact or not await can_manage_contact_effective(u, contact):
            await reg_state.clear_state(user_id)
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return
        if field != "name" and raw.lower() in ("пропустить", "skip", "-"):
            raw = ""
        elif field == "name" and not raw:
            await adapter.send_message(chat_id, "Название не может быть пустым.", append_main_menu_shortcut_row(None))
            return
        kw = {field: raw if raw else None}
        ok = await update_contact(cuid, **kw)
        await reg_state.clear_state(user_id)
        if ok:
            c = await get_contact_by_id(cuid)
            body = await format_useful_contact_admin_view(c)
            await adapter.send_message(
                chat_id,
                f"✅ Обновлено.\n\n{body}",
                append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contact_edit_kb(cid_s))),
            )
        else:
            await adapter.send_message(
                chat_id,
                "Ошибка.",
                append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contacts_menu_kb())),
            )


async def handle_max_contact_category_fsm_callback(
    adapter: MaxAdapter, chat_id: str, user_id: int, cb_data: str, fsm: dict
) -> bool:
    if not cb_data.startswith("admin_contact_ev_"):
        return False
    fd = fsm.get("data") or {}
    if fd.get("field") != "category":
        return False
    cid_s = fd.get("contact_id")
    if not cid_s:
        return False
    raw = cb_data.replace("admin_contact_ev_", "", 1)
    idx = raw.rfind("_")
    if idx < 0:
        return False
    ev_cid, cat = raw[:idx], raw[idx + 1 :]
    if ev_cid != cid_s or cat not in _VALID_CATS:
        await reg_state.clear_state(user_id)
        return True
    u = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not u or not await can_manage_contacts_effective(u):
        await reg_state.clear_state(user_id)
        return True
    try:
        cuid = uuid.UUID(cid_s)
    except ValueError:
        await reg_state.clear_state(user_id)
        return True
    contact = await get_contact_by_id(cuid)
    if not contact or not await can_manage_contact_effective(u, contact):
        await reg_state.clear_state(user_id)
        await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
        return True
    ok = await update_contact(cuid, category=cat)
    await reg_state.clear_state(user_id)
    if ok:
        c = await get_contact_by_id(cuid)
        body = await format_useful_contact_admin_view(c)
        await adapter.send_message(
            chat_id,
            f"✅ Категория обновлена.\n\n{body}",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_contact_edit_kb(cid_s))),
        )
    else:
        await adapter.send_message(chat_id, "Ошибка.", append_main_menu_shortcut_row(None))
    return True

