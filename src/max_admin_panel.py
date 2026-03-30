"""Админ-панель в MAX: те же callback_data и сервисы, что у Telegram — БД общая."""

from __future__ import annotations

import uuid

from loguru import logger
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from src.handlers import admin as tg_admin
from src.keyboards.admin import (
    get_admin_back_kb,
    get_admin_event_kb,
    get_admin_main_kb,
    get_broadcast_confirm_kb,
    get_settings_kb,
    get_user_action_kb,
)
from src.models.user import Platform, User
from src.platforms.base import Button
from src.platforms.max_adapter import MaxAdapter
from src.services import max_registration_state as reg_state
from src.services.admin_phone_actions import phone_change_approve, phone_change_reject
from src.services.activity_log_service import get_logs
from src.services.admin_service import (
    add_city_admin,
    admin_cancel_event,
    block_user,
    can_admin_events_user,
    create_city,
    extend_subscription,
    get_admin_events,
    get_all_cities,
    get_broadcast_recipients,
    get_cities,
    get_city_admins,
    get_global_text,
    get_effective_support_email,
    get_effective_support_username,
    GLOBAL_TEXT_SUPPORT_EMAIL,
    GLOBAL_TEXT_SUPPORT_USERNAME,
    get_stats,
    get_subscription_settings,
    get_user_by_id,
    get_users_list,
    is_city_admin,
    is_effective_city_admin_of,
    is_effective_superadmin_user,
    max_user_should_see_admin_menu,
    remove_city_admin,
    set_event_hidden,
    set_event_official,
    set_event_recommended,
    set_global_text,
    unblock_user,
    update_city,
    update_subscription_settings,
)
from src.services.broadcast import _do_broadcast, _do_max_broadcast, get_max_adapter
from src.services.cross_platform_notify import send_text_to_all_identities
from src.services.event_service import TYPE_LABELS, get_event_by_id
from src.services.motopair_service import hide_profile
from src.services.notification_templates import TEMPLATE_KEYS
from src.services.user import get_or_create_user
from src.utils.callback_short import get_city_admin_remove
from src.keyboards.shared import append_main_menu_shortcut_row, get_main_menu_shortcut_row, max_kb_from_tg_inline

from src import texts


def _city_admin_root_max() -> list:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мероприятия", callback_data="admin_events")],
            [InlineKeyboardButton(text="📇 Контакты", callback_data="admin_contacts")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ]
    )
    return max_kb_from_tg_inline(kb) or []


async def show_max_admin_root(adapter: MaxAdapter, chat_id: str, user: User) -> None:
    if not await max_user_should_see_admin_menu(user):
        logger.info(
            "max_admin_panel denied: platform=max platform_user_id={} chat_id={}",
            user.platform_user_id,
            chat_id,
        )
        await adapter.send_message(
            chat_id, "Нет доступа к админ-панели.", [[Button("« Меню", payload="menu_main")]]
        )
        return
    is_sa = await is_effective_superadmin_user(user)
    logger.info(
        "max_admin_panel open: platform=max platform_user_id={} chat_id={} superadmin={}",
        user.platform_user_id,
        chat_id,
        is_sa,
    )
    if is_sa:
        text = "⚙️ <b>Админ-панель</b>\n\nВыбери раздел (данные общие с Telegram):"
        rows = max_kb_from_tg_inline(get_admin_main_kb()) or []
        await adapter.send_message(chat_id, text, rows)
        return
    text = "⚙️ <b>Админ города</b>\n\nВыбери раздел:"
    await adapter.send_message(chat_id, text, _city_admin_root_max())


async def _max_superadmin(user: User) -> bool:
    return await is_effective_superadmin_user(user)


async def _max_city_events_ok(user: User) -> bool:
    if await _max_superadmin(user):
        return True
    if not user.city_id:
        return False
    return await is_city_admin(user.platform_user_id, user.city_id, platform=Platform.MAX)


async def _max_motopair_moderate_ok(actor: User) -> bool:
    if await is_effective_superadmin_user(actor):
        return True
    if not actor.city_id:
        return False
    return await is_city_admin(actor.platform_user_id, actor.city_id, platform=Platform.MAX)


async def _max_motopair_report_target_ok(actor: User, target_id: uuid.UUID) -> bool:
    """Суперадмин — любой город; админ города — только цель из своего города."""
    if await is_effective_superadmin_user(actor):
        return True
    target = await get_user_by_id(target_id)
    if not target or not actor.city_id:
        return False
    return target.city_id == actor.city_id


async def _max_ev_report_ok(actor: User, ev) -> bool:
    if await is_effective_superadmin_user(actor):
        return True
    return await is_effective_city_admin_of(actor, ev.city_id)


async def max_admin_dispatch(adapter: MaxAdapter, chat_id: str, user: User, data: str) -> bool:
    """Обработать callback админки. True если событие поглощено."""
    if not (data.startswith("admin_") or data.startswith("cam_")):
        return False

    from src.max_runner import _get_tg_bot

    tg_bot = _get_tg_bot()
    max_ad = get_max_adapter() or adapter

    # ——— Модерация заявок (суперадмин / админ города) ———
    if data.startswith("admin_phone_approve_"):
        if not await _max_superadmin(user):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_back_kb("menu_main"))))
            return True
        rid = data.replace("admin_phone_approve_", "", 1)
        ok, msg = await phone_change_approve(
            rid, user, telegram_bot=tg_bot, max_adapter=max_ad
        )
        await adapter.send_message(chat_id, msg, append_main_menu_shortcut_row([[Button("« Админка", payload="admin_panel")]]))
        return True

    if data.startswith("admin_phone_reject_"):
        if not await _max_superadmin(user):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        rid = data.replace("admin_phone_reject_", "", 1)
        ok, msg = await phone_change_reject(
            rid, user, telegram_bot=tg_bot, max_adapter=max_ad
        )
        await adapter.send_message(chat_id, msg, append_main_menu_shortcut_row([[Button("« Админка", payload="admin_panel")]]))
        return True

    if data.startswith("admin_report_accept_"):
        if not await _max_motopair_moderate_ok(user):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        uid_s = data.replace("admin_report_accept_", "", 1)
        try:
            tid = uuid.UUID(uid_s)
        except ValueError:
            return True
        if not await _max_motopair_report_target_ok(user, tid):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        try:
            await hide_profile(tid)
        except ValueError:
            pass
        await adapter.send_message(chat_id, texts.MOTOPAIR_REPORT_ACCEPTED, append_main_menu_shortcut_row(None))
        return True

    if data.startswith("admin_report_reject_"):
        if not await _max_motopair_moderate_ok(user):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        uid_s = data.replace("admin_report_reject_", "", 1)
        try:
            tid = uuid.UUID(uid_s)
        except ValueError:
            return True
        if not await _max_motopair_report_target_ok(user, tid):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        await adapter.send_message(chat_id, texts.MOTOPAIR_REPORT_REJECTED, append_main_menu_shortcut_row(None))
        return True

    if data.startswith("admin_report_block_"):
        if not await _max_motopair_moderate_ok(user):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        uid_s = data.replace("admin_report_block_", "", 1)
        try:
            tid = uuid.UUID(uid_s)
        except ValueError:
            return True
        if not await _max_motopair_report_target_ok(user, tid):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        await reg_state.set_state(
            user.platform_user_id,
            "admin:block_reason",
            {"target_user_id": uid_s},
        )
        await adapter.send_message(
            chat_id,
            "Введи причину блокировки (одним сообщением):",
            [[Button("« Отмена", payload="admin_panel")], get_main_menu_shortcut_row()],
        )
        return True

    if data.startswith("admin_evreport_accept_"):
        eid_s = data.replace("admin_evreport_accept_", "", 1)
        try:
            eid = uuid.UUID(eid_s)
        except ValueError:
            return True
        ev = await get_event_by_id(eid)
        if not ev or not await _max_ev_report_ok(user, ev):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        await set_event_hidden(ev.id, True)
        await adapter.send_message(chat_id, texts.EVENT_REPORT_ACCEPTED, append_main_menu_shortcut_row(None))
        return True

    if data.startswith("admin_evreport_reject_"):
        eid_s = data.replace("admin_evreport_reject_", "", 1)
        try:
            eid = uuid.UUID(eid_s)
        except ValueError:
            return True
        ev = await get_event_by_id(eid)
        if not ev or not await _max_ev_report_ok(user, ev):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        await adapter.send_message(chat_id, texts.EVENT_REPORT_REJECTED, append_main_menu_shortcut_row(None))
        return True

    if data.startswith("cam_"):
        if not await _max_superadmin(user):
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return True
        parsed = get_city_admin_remove(data.replace("cam_", "", 1))
        if not parsed:
            return True
        city_id, adm_user_id = parsed
        await remove_city_admin(city_id, adm_user_id)
        await adapter.send_message(chat_id, "Админ города снят.", [[Button("« Админы городов", payload="admin_city_admins")], get_main_menu_shortcut_row()])
        return True

    if data == "admin_contacts" or data.startswith("admin_contact"):
        from src.max_admin_contacts import max_contacts_try_dispatch

        if await max_contacts_try_dispatch(adapter, chat_id, user, data):
            return True

    if data == "admin_panel":
        await show_max_admin_root(adapter, chat_id, user)
        return True

    if not await max_user_should_see_admin_menu(user):
        return False

    # ——— Суперадмин ———
    if data == "admin_stats" and await _max_superadmin(user):
        stats = await get_stats()
        t = (
            f"📊 <b>Статистика</b>\n\n"
            f"Пользователей: {stats.get('users', 0)}\n"
            f"Заблокировано: {stats.get('blocked', 0)}\n"
            f"Активных подписок: {stats.get('active_subs', 0)}\n"
            f"SOS-сигналов: {stats.get('sos', 0)}\n"
            f"Мероприятий: {stats.get('events', 0)}"
        )
        await adapter.send_message(chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(tg_admin._admin_stats_markup())))
        return True

    if data == "admin_users" and await _max_superadmin(user):
        users, total = await get_users_list(limit=tg_admin.USERS_PAGE_SIZE, offset=0)
        text, kb = tg_admin._build_users_page(users, total, 0, payment_row=True)
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data.startswith("admin_users_p") and await _max_superadmin(user):
        try:
            page = int(data.replace("admin_users_p", "", 1))
        except ValueError:
            page = 0
        users, total = await get_users_list(limit=tg_admin.USERS_PAGE_SIZE, offset=page * tg_admin.USERS_PAGE_SIZE)
        text, kb = tg_admin._build_users_page(users, total, page, payment_row=True)
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data == "admin_users_search" and await _max_superadmin(user):
        await reg_state.set_state(user.platform_user_id, "admin:user_search", {})
        await adapter.send_message(
            chat_id,
            "Введи ID, username или имя для поиска:",
            [[Button("« Отмена", payload="admin_users")], get_main_menu_shortcut_row()],
        )
        return True

    if data.startswith("admin_user_view_") and await _max_superadmin(user):
        uid_s = data.replace("admin_user_view_", "", 1)
        try:
            uu = uuid.UUID(uid_s)
        except ValueError:
            return True
        u = await get_user_by_id(uu)
        if not u:
            await adapter.send_message(chat_id, "Не найден.", append_main_menu_shortcut_row(None))
            return True
        t = (
            f"<b>Пользователь</b>\n"
            f"Платформа: {u.platform.value}\n"
            f"ID: {u.platform_user_id}\n"
            f"Username: @{u.platform_username or '—'}\n"
            f"Имя: {u.platform_first_name or '—'}\n"
            f"Статус: {'🔒 Заблокирован' if u.is_blocked else '✅ Активен'}\n"
            f"Причина: {u.block_reason or '—'}"
        )
        await adapter.send_message(chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(get_user_action_kb(uid_s, u.is_blocked))))
        return True

    if (
        data.startswith("admin_user_block_") or data.startswith("admin_user_unblock_")
    ) and await _max_superadmin(user):
        parts = data.split("_")
        action, uid_s = parts[-2], parts[-1]
        try:
            uu = uuid.UUID(uid_s)
        except ValueError:
            return True
        u = await get_user_by_id(uu)
        if not u:
            return True
        if action == "block":
            await block_user(uu)
            await send_text_to_all_identities(
                uu,
                "Вы заблокированы. Обратитесь в поддержку.",
                telegram_bot=tg_bot,
                max_adapter=max_ad,
                parse_mode="HTML",
            )
            u = await get_user_by_id(uu)
        else:
            await unblock_user(uu)
            u = await get_user_by_id(uu)
        t = (
            f"<b>Пользователь</b>\nID: {u.platform_user_id}\n"
            f"Статус: {'🔒 Заблокирован' if u.is_blocked else '✅ Активен'}"
        )
        await adapter.send_message(chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(get_user_action_kb(uid_s, u.is_blocked))))
        return True

    if data.startswith("admin_sub_extend_") and await _max_superadmin(user):
        uid_s = data.replace("admin_sub_extend_", "", 1)
        try:
            uuid.UUID(uid_s)
        except ValueError:
            return True
        await reg_state.set_state(
            user.platform_user_id, "admin:extend_sub", {"uid": uid_s}
        )
        await adapter.send_message(
            chat_id,
            "Введи число дней продления подписки (1–365):",
            [[Button("« Отмена", payload="admin_users")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_cities" and await _max_superadmin(user):
        text, kb = await tg_admin._admin_cities_list_text_kb()
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data.startswith("admin_city_toggle_") and await _max_superadmin(user):
        cid = data.replace("admin_city_toggle_", "", 1)
        cities = await get_all_cities()
        city = next((c for c in cities if str(c.id) == cid), None)
        if city:
            await update_city(uuid.UUID(cid), is_active=not city.is_active)
        text, kb = await tg_admin._admin_cities_list_text_kb()
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data.startswith("admin_city_edit_") and await _max_superadmin(user):
        cid = data.replace("admin_city_edit_", "", 1)
        await reg_state.set_state(
            user.platform_user_id, "admin:city_name", {"action": "edit", "city_id": cid}
        )
        await adapter.send_message(
            chat_id,
            "Введи новое название города:",
            [[Button("« Отмена", payload="admin_cities")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_cities_add" and await _max_superadmin(user):
        await reg_state.set_state(user.platform_user_id, "admin:city_name", {"action": "add"})
        await adapter.send_message(
            chat_id,
            "Введи название нового города:",
            [[Button("« Отмена", payload="admin_cities")], get_main_menu_shortcut_row()],
        )
        return True

    if (
        data.startswith("admin_city_")
        and data != "admin_city_admins"
        and not data.startswith("admin_city_edit_")
        and not data.startswith("admin_city_toggle_")
        and await _max_superadmin(user)
    ):
        cid = data.replace("admin_city_", "", 1)
        cities = await get_all_cities()
        city = next((c for c in cities if str(c.id) == cid), None)
        if not city:
            return True
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"admin_city_edit_{cid}")],
                [
                    InlineKeyboardButton(
                        text="✅ Активировать" if not city.is_active else "❌ Деактивировать",
                        callback_data=f"admin_city_toggle_{cid}",
                    )
                ],
                [InlineKeyboardButton(text="« К списку", callback_data="admin_cities")],
            ]
        )
        t = f"🏙 {city.name}\nСтатус: {'активен' if city.is_active else 'неактивен'}"
        await adapter.send_message(chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data == "admin_city_admins" and await _max_superadmin(user):
        cities = await get_cities()
        rows_m = [
            [Button(c.name, payload=f"admin_ca_city_{c.id}")] for c in cities
        ]
        rows_m.append([Button("« Назад", payload="admin_panel")])
        await adapter.send_message(
            chat_id, "Выбери город:", append_main_menu_shortcut_row(rows_m)
        )
        return True

    if data.startswith("admin_ca_city_") and await _max_superadmin(user):
        cid = data.replace("admin_ca_city_", "", 1)
        try:
            c_uuid = uuid.UUID(cid)
        except ValueError:
            return True
        admins = await get_city_admins(c_uuid)
        from src.utils.callback_short import put_city_admin_remove

        rows_btn = []
        for _ca, au in admins:
            code = put_city_admin_remove(c_uuid, au.id)
            rows_btn.append(
                [
                    Button(
                        f"@{au.platform_username or au.platform_user_id} — убрать",
                        payload=f"cam_{code}",
                    )
                ]
            )
        rows_btn.append([Button("➕ Добавить админа", payload=f"admin_ca_add_{cid}")])
        rows_btn.append([Button("« Назад", payload="admin_city_admins")])
        t = (
            "Админы города:\n\n"
            + "\n".join(f"• {u.platform_username or u.platform_user_id}" for _x, u in admins)
            if admins
            else "Админов нет."
        )
        await adapter.send_message(chat_id, t, append_main_menu_shortcut_row(rows_btn))
        return True

    if data.startswith("admin_ca_add_") and await _max_superadmin(user):
        cid = data.replace("admin_ca_add_", "", 1)
        await reg_state.set_state(
            user.platform_user_id, "admin:ca_add", {"city_id": cid}
        )
        await adapter.send_message(
            chat_id,
            "Введи <b>числовой ID</b> пользователя (Telegram или MAX — как в БД).",
            [[Button("« Отмена", payload=f"admin_ca_city_{cid}")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_events" and await _max_city_events_ok(user):
        is_sa = await _max_superadmin(user)
        events = await get_admin_events(superadmin=is_sa, city_id=user.city_id if user else None)
        rows = []
        if is_sa:
            rows.append(
                [
                    Button(
                        "💰 Цена создания мероприятия",
                        payload="admin_set_event_creation_price",
                    )
                ]
            )
        for e in events[:20]:
            label = e.title or TYPE_LABELS.get(e.type.value, e.type.value)
            rows.append(
                [Button(f"{e.start_at.strftime('%d.%m')} {label}", payload=f"admin_ev_{e.id}")]
            )
        rows.append([Button("« Назад", payload="admin_panel")])
        t = (
            "Мероприятия:\n\n"
            + "\n".join(
                f"• {(ev.title or TYPE_LABELS.get(ev.type.value, ''))} — {ev.start_at.strftime('%d.%m.%Y')}"
                for ev in events[:20]
            )
            if events
            else "Мероприятий нет."
        )
        await adapter.send_message(chat_id, t, append_main_menu_shortcut_row(rows))
        return True

    if (
        data.startswith("admin_ev_")
        and not data.startswith("admin_ev_rec_")
        and not data.startswith("admin_ev_official_")
        and not data.startswith("admin_ev_cancel_")
        and not data.startswith("admin_evreport_")
        and await _max_city_events_ok(user)
    ):
        eid_s = data.replace("admin_ev_", "", 1)
        try:
            euu = uuid.UUID(eid_s)
        except ValueError:
            return True
        ev = await get_event_by_id(euu)
        if not ev:
            return True
        if not await can_admin_events_user(user, ev.city_id):
            await adapter.send_message(chat_id, "Нет доступа.", append_main_menu_shortcut_row(None))
            return True
        can_edit = await can_admin_events_user(user, ev.city_id)
        t = tg_admin._admin_event_text(ev)
        await adapter.send_message(
            chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_event_kb(eid_s, can_edit, ev.is_recommended, ev.is_official)))
        )
        return True

    if data.startswith("admin_ev_rec_") and await _max_city_events_ok(user):
        eid_s = data.replace("admin_ev_rec_", "", 1)
        try:
            euu = uuid.UUID(eid_s)
        except ValueError:
            return True
        ev = await get_event_by_id(euu)
        if ev and await can_admin_events_user(user, ev.city_id):
            await set_event_recommended(ev.id, not ev.is_recommended)
            ev = await get_event_by_id(euu)
            t = tg_admin._admin_event_text(ev)
            await adapter.send_message(
                chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_event_kb(eid_s, True, ev.is_recommended, ev.is_official)))
            )
        return True

    if data.startswith("admin_ev_official_") and await _max_city_events_ok(user):
        eid_s = data.replace("admin_ev_official_", "", 1)
        try:
            euu = uuid.UUID(eid_s)
        except ValueError:
            return True
        ev = await get_event_by_id(euu)
        if ev and await can_admin_events_user(user, ev.city_id):
            await set_event_official(ev.id, not ev.is_official)
            ev = await get_event_by_id(euu)
            t = tg_admin._admin_event_text(ev)
            await adapter.send_message(
                chat_id, t, append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_event_kb(eid_s, True, ev.is_recommended, ev.is_official)))
            )
        return True

    if data.startswith("admin_ev_cancel_") and await _max_city_events_ok(user):
        eid_s = data.replace("admin_ev_cancel_", "", 1)
        try:
            euu = uuid.UUID(eid_s)
        except ValueError:
            return True
        ev = await get_event_by_id(euu)
        if ev and await can_admin_events_user(user, ev.city_id):
            ok, pids = await admin_cancel_event(euu)
            if ok:
                from src.services.event_participant_notify import notify_event_participants_cancelled

                msg = f"❌ Мероприятие «{ev.title or 'Мероприятие'}» отменено администратором."
                await notify_event_participants_cancelled(
                    pids, msg, telegram_bot=tg_bot, max_adapter=max_ad
                )
            await adapter.send_message(chat_id, "Мероприятие отменено.", append_main_menu_shortcut_row([[Button("« Мероприятия", payload="admin_events")]]))
        return True

    if data == "admin_settings" and await _max_superadmin(user):
        s = await get_subscription_settings()
        await adapter.send_message(
            chat_id, tg_admin._settings_text(s), append_main_menu_shortcut_row(max_kb_from_tg_inline(get_settings_kb(s)))
        )
        return True

    for prefix, fn in (
        ("admin_set_sub_toggle", lambda s: update_subscription_settings(subscription_enabled=not s.subscription_enabled)),
        ("admin_set_ev_toggle", lambda s: update_subscription_settings(event_creation_enabled=not s.event_creation_enabled)),
        ("admin_set_raise_toggle", lambda s: update_subscription_settings(raise_profile_enabled=not s.raise_profile_enabled)),
    ):
        if data == prefix and await _max_superadmin(user):
            s = await get_subscription_settings()
            await fn(s)
            s = await get_subscription_settings()
            await adapter.send_message(
                chat_id, tg_admin._settings_text(s), append_main_menu_shortcut_row(max_kb_from_tg_inline(get_settings_kb(s)))
            )
            return True

    if data.startswith("admin_set_mcl_") and await _max_superadmin(user):
        try:
            val = int(data.replace("admin_set_mcl_", "", 1))
            val = max(0, val)
        except ValueError:
            return True
        await update_subscription_settings(event_motorcade_limit_per_month=val)
        s = await get_subscription_settings()
        await adapter.send_message(
            chat_id, tg_admin._settings_text(s), append_main_menu_shortcut_row(max_kb_from_tg_inline(get_settings_kb(s)))
        )
        return True

    if data == "admin_set_motorcade_limit" and await _max_superadmin(user):
        s = await get_subscription_settings()
        cur = getattr(s, "event_motorcade_limit_per_month", 2)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="0", callback_data="admin_set_mcl_0"),
                    InlineKeyboardButton(text="1", callback_data="admin_set_mcl_1"),
                    InlineKeyboardButton(text="2", callback_data="admin_set_mcl_2"),
                    InlineKeyboardButton(text="5", callback_data="admin_set_mcl_5"),
                ],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_settings")],
            ]
        )
        await adapter.send_message(
            chat_id,
            f"Мотопробегов/мес (с подпиской). Сейчас: {cur}",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)),
        )
        return True

    price_map = {
        "admin_set_monthly": ("monthly", "Введи цену месяца в копейках (например 29900):"),
        "admin_set_season": ("season", "Введи цену года (365 дн.) в копейках:"),
        "admin_set_event_creation_price": ("event_creation", "Введи цену создания мероприятия в копейках:"),
        "admin_set_raise_profile_price": ("raise_profile", "Введи цену поднятия анкеты в копейках:"),
    }
    if data in price_map and await _max_superadmin(user):
        key, prompt = price_map[data]
        await reg_state.set_state(user.platform_user_id, "admin:set_price", {"field": key})
        await adapter.send_message(
            chat_id,
            prompt,
            [[Button("« Отмена", payload="admin_settings")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_logs" and await _max_superadmin(user):
        logs, total = await get_logs(limit=tg_admin.LOGS_PAGE_SIZE, offset=0)
        text, kb = tg_admin._build_logs_page(logs, total, 0, None)
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data.startswith("admin_logs_t_") and await _max_superadmin(user):
        et = data.replace("admin_logs_t_", "", 1) or None
        logs, total = await get_logs(event_type=et, limit=tg_admin.LOGS_PAGE_SIZE, offset=0)
        text, kb = tg_admin._build_logs_page(logs, total, 0, et)
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data.startswith("admin_logs_p") and await _max_superadmin(user):
        rest = data.replace("admin_logs_p", "", 1)
        parts = rest.split("_", 1)
        try:
            page = int(parts[0])
        except ValueError:
            page = 0
        et = parts[1] if len(parts) > 1 and parts[1] else None
        logs, total = await get_logs(
            event_type=et, limit=tg_admin.LOGS_PAGE_SIZE, offset=page * tg_admin.LOGS_PAGE_SIZE
        )
        text, kb = tg_admin._build_logs_page(logs, total, page, et)
        await adapter.send_message(chat_id, text, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return True

    if data == "admin_broadcast" and await _max_superadmin(user):
        rows = [
            [InlineKeyboardButton(text="Всем", callback_data="admin_bc_all")],
            [InlineKeyboardButton(text="Только Пилотам", callback_data="admin_bc_role_pilot")],
            [InlineKeyboardButton(text="Только Двоек", callback_data="admin_bc_role_passenger")],
            [InlineKeyboardButton(text="С подпиской", callback_data="admin_bc_sub_yes")],
            [InlineKeyboardButton(text="Без подписки", callback_data="admin_bc_sub_no")],
        ]
        for c in await get_cities():
            rows.append(
                [InlineKeyboardButton(text=f"Город: {c.name}", callback_data=f"admin_bc_city_{c.id}")]
            )
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
        await adapter.send_message(
            chat_id, "Сегмент рассылки:", append_main_menu_shortcut_row(max_kb_from_tg_inline(InlineKeyboardMarkup(inline_keyboard=rows)))
        )
        return True

    if (
        data.startswith("admin_bc_")
        and data != "admin_bc_confirm"
        and await _max_superadmin(user)
    ):
        sub = data.replace("admin_bc_", "", 1)
        if sub == "all":
            seg = {"city_id": None, "role": None, "with_subscription": None}
        elif sub.startswith("role_"):
            seg = {"city_id": None, "role": sub.replace("role_", ""), "with_subscription": None}
        elif sub.startswith("sub_"):
            seg = {"city_id": None, "role": None, "with_subscription": sub == "sub_yes"}
        elif sub.startswith("city_"):
            seg = {"city_id": str(uuid.UUID(sub.replace("city_", ""))), "role": None, "with_subscription": None}
        else:
            return True
        await reg_state.set_state(user.platform_user_id, "admin:bc_msg", {"segment": seg})
        await adapter.send_message(
            chat_id,
            "Введи текст рассылки одним сообщением.\n\n" + texts.BROADCAST_HTML_HINT,
            [[Button("« Отмена", payload="admin_broadcast")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_text_about" and await _max_superadmin(user):
        cur = await get_global_text("about_us")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✏ Изменить", callback_data="admin_text_about_edit")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
            ]
        )
        await adapter.send_message(
            chat_id,
            f"<b>Текст «О нас»</b>\n\n{cur or '(не задан)'}",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)),
        )
        return True

    if data == "admin_text_about_edit" and await _max_superadmin(user):
        await reg_state.set_state(user.platform_user_id, "admin:about_text", {})
        cur = await get_global_text("about_us")
        await adapter.send_message(
            chat_id,
            f"Отправь новый текст для «О нас». Сейчас:\n\n{cur or ''}",
            [[Button("« Отмена", payload="admin_text_about")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_support_contact" and await _max_superadmin(user):
        email = await get_effective_support_email()
        uname = await get_effective_support_username()
        db_mail = await get_global_text(GLOBAL_TEXT_SUPPORT_EMAIL)
        db_user = await get_global_text(GLOBAL_TEXT_SUPPORT_USERNAME)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏ Email", callback_data="admin_support_edit_email"
                    ),
                    InlineKeyboardButton(
                        text="✏ Telegram @", callback_data="admin_support_edit_username"
                    ),
                ],
                [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
            ]
        )
        await adapter.send_message(
            chat_id,
            "<b>📞 Контакты поддержки</b>\n\n"
            f"Пользователям сейчас:\n📧 <code>{email}</code>\n👤 <code>@{uname}</code>\n\n"
            f"<i>В БД (пусто = .env):</i>\n"
            f"email: <code>{db_mail or '—'}</code>\n"
            f"username: <code>{db_user or '—'}</code>",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)),
        )
        return True

    if data == "admin_support_edit_email" and await _max_superadmin(user):
        await reg_state.set_state(user.platform_user_id, "admin:support_email", {})
        cur = await get_global_text(GLOBAL_TEXT_SUPPORT_EMAIL) or "(из .env)"
        await adapter.send_message(
            chat_id,
            f"Отправь email поддержки (сейчас в БД: {cur}). Пример: info@site.ru",
            [[Button("« Отмена", payload="admin_support_contact")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_support_edit_username" and await _max_superadmin(user):
        await reg_state.set_state(user.platform_user_id, "admin:support_username", {})
        cur = await get_global_text(GLOBAL_TEXT_SUPPORT_USERNAME) or "(из .env)"
        await adapter.send_message(
            chat_id,
            f"Отправь username в Telegram <b>без @</b> (сейчас в БД: {cur}).",
            [[Button("« Отмена", payload="admin_support_contact")], get_main_menu_shortcut_row()],
        )
        return True

    if data == "admin_templates" and await _max_superadmin(user):
        rows = []
        for key in TEMPLATE_KEYS:
            label = key.replace("template_", "").replace("_", " ").title()
            rows.append([InlineKeyboardButton(text=f"✏ {label}", callback_data=f"admin_tpl_edit_{key}")])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
        await adapter.send_message(
            chat_id,
            "<b>Шаблоны уведомлений</b>\n\nВыбери шаблон.",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(InlineKeyboardMarkup(inline_keyboard=rows))),
        )
        return True

    if data.startswith("admin_tpl_edit_") and await _max_superadmin(user):
        key = data.replace("admin_tpl_edit_", "", 1)
        if key not in TEMPLATE_KEYS:
            return True
        default, desc = TEMPLATE_KEYS[key]
        cur = await get_global_text(key) or default
        await reg_state.set_state(
            user.platform_user_id, "admin:template_text", {"tpl_key": key}
        )
        await adapter.send_message(
            chat_id,
            f"<b>{key}</b>\n{desc}\n\nТекущий:\n{cur}\n\nОтправь новый текст:",
            [[Button("« Отмена", payload="admin_templates")], get_main_menu_shortcut_row()],
        )
        return True

    return False


async def handle_max_admin_fsm_text(
    adapter: MaxAdapter, chat_id: str, user_id: int, text: str, fsm: dict
) -> None:
    """Обработка текстовых шагов админ-FSM в MAX."""
    from src.max_runner import _get_tg_bot

    state = fsm.get("state") or ""
    data = fsm.get("data") or {}
    tg_bot = _get_tg_bot()
    max_ad = get_max_adapter() or adapter

    u = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not u:
        return

    async def _done(msg: str, back_payload: str = "admin_panel"):
        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id,
            msg,
            append_main_menu_shortcut_row([[Button("« Назад", payload=back_payload)]]),
        )

    if state == "admin:city_name":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        name = (text or "").strip()[:100]
        if not name:
            await adapter.send_message(chat_id, "Пустое название.", append_main_menu_shortcut_row(None))
            return
        action = data.get("action")
        if action == "add":
            city, err = await create_city(name)
            await _done(f"✅ {city.name}" if city else f"❌ {err}", "admin_cities")
        elif action == "edit" and data.get("city_id"):
            ok, err = await update_city(uuid.UUID(str(data["city_id"])), name=name)
            await _done("✅ Переименовано." if ok else f"❌ {err}", "admin_cities")
        else:
            await reg_state.clear_state(user_id)
        return

    if state == "admin:ca_add":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        cid = data.get("city_id")
        try:
            pid = int((text or "").strip())
        except ValueError:
            await adapter.send_message(chat_id, "Нужно число (platform_user_id).", append_main_menu_shortcut_row(None))
            return
        from sqlalchemy import select
        from src.models.base import get_session_factory
        from src.models.user import User as U2

        session_factory = get_session_factory()
        async with session_factory() as session:
            r = await session.execute(
                select(U2).where(U2.platform_user_id == pid).limit(1)
            )
            target = r.scalar_one_or_none()
        if not target:
            await adapter.send_message(
                chat_id,
                "Пользователь с таким ID не найден. Сначала пусть напишет боту.",
                append_main_menu_shortcut_row([[Button("« Назад", payload=f"admin_ca_city_{cid}")]]),
            )
            return
        ok, err = await add_city_admin(uuid.UUID(str(cid)), target.id)
        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id,
            "✅ Админ добавлен." if ok else f"❌ {err}",
            append_main_menu_shortcut_row([[Button("« Назад", payload=f"admin_ca_city_{cid}")]]),
        )
        return

    if state == "admin:block_reason":
        if not await _max_motopair_moderate_ok(u):
            await reg_state.clear_state(user_id)
            return
        tid = data.get("target_user_id")
        if not tid:
            await reg_state.clear_state(user_id)
            return
        reason = (text or "").strip()[:500]
        try:
            tu = uuid.UUID(str(tid))
        except ValueError:
            await reg_state.clear_state(user_id)
            return
        if not await _max_motopair_report_target_ok(u, tu):
            await reg_state.clear_state(user_id)
            await adapter.send_message(chat_id, "Доступ запрещён.", append_main_menu_shortcut_row(None))
            return
        await block_user(tu, reason=reason)
        await send_text_to_all_identities(
            tu,
            texts.ADMIN_BLOCK_USER_NOTIFICATION.format(reason=reason),
            telegram_bot=tg_bot,
            max_adapter=max_ad,
            parse_mode="HTML",
        )
        await reg_state.clear_state(user_id)
        await adapter.send_message(chat_id, texts.ADMIN_BLOCK_DONE, append_main_menu_shortcut_row([[Button("« Админка", payload="admin_panel")]]))
        return

    if state == "admin:extend_sub":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        uid_s = data.get("uid")
        try:
            days = int((text or "").strip())
            if days < 1 or days > 365:
                raise ValueError
        except ValueError:
            await adapter.send_message(chat_id, "Число от 1 до 365.", append_main_menu_shortcut_row(None))
            return
        ok, msg = await extend_subscription(uuid.UUID(str(uid_s)), days)
        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id, f"✅ {msg}", append_main_menu_shortcut_row([[Button("« Пользователи", payload="admin_users")]])
        )
        return

    if state == "admin:user_search":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        q = (text or "").strip()
        users, total = await get_users_list(
            limit=tg_admin.USERS_PAGE_SIZE, offset=0, search=q if q else None
        )
        text_p, kb = tg_admin._build_users_page(users, total, 0, payment_row=True)
        await reg_state.clear_state(user_id)
        await adapter.send_message(chat_id, text_p, append_main_menu_shortcut_row(max_kb_from_tg_inline(kb)))
        return

    if state == "admin:bc_msg":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        seg = data.get("segment") or {}
        r_tg = await get_broadcast_recipients(
            city_id=seg.get("city_id"),
            role=seg.get("role"),
            with_subscription=seg.get("with_subscription"),
            platform=Platform.TELEGRAM,
        )
        r_max = await get_broadcast_recipients(
            city_id=seg.get("city_id"),
            role=seg.get("role"),
            with_subscription=seg.get("with_subscription"),
            platform=Platform.MAX,
        )
        n = len(r_tg) + len(r_max)
        await reg_state.set_state(
            user_id,
            "admin:bc_confirm",
            {"segment": seg, "bc_text": text, "bc_count": n},
        )
        await adapter.send_message(
            chat_id,
            f"Получателей: {n} (Telegram: {len(r_tg)}, MAX: {len(r_max)}). Отправить?",
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_broadcast_confirm_kb())),
        )
        return

    if state == "admin:about_text":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        await set_global_text("about_us", (text or "").strip()[:5000] or "О нас")
        await _done("✅ Текст «О нас» сохранён.", "admin_panel")
        return

    if state == "admin:support_email":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        em = (text or "").strip()[:320]
        if not em or "@" not in em:
            await adapter.send_message(
                chat_id,
                "Нужен корректный email (с символом @). Попробуй ещё раз.",
                append_main_menu_shortcut_row(None),
            )
            return
        await set_global_text(GLOBAL_TEXT_SUPPORT_EMAIL, em)
        await _done("✅ Email поддержки сохранён.", "admin_support_contact")
        return

    if state == "admin:support_username":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        un = (text or "").strip().lstrip("@")[:64]
        if not un:
            await adapter.send_message(chat_id, "Username не может быть пустым.", append_main_menu_shortcut_row(None))
            return
        await set_global_text(GLOBAL_TEXT_SUPPORT_USERNAME, un)
        await _done("✅ Username Telegram сохранён.", "admin_support_contact")
        return

    if state == "admin:template_text":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        key = data.get("tpl_key")
        if key:
            await set_global_text(key, (text or "").strip()[:5000])
        await _done(f"✅ Шаблон {key} сохранён.", "admin_templates")
        return

    if state == "admin:set_price":
        if not await _max_superadmin(u):
            await reg_state.clear_state(user_id)
            return
        try:
            kop = int((text or "").strip())
            if kop < 0:
                raise ValueError
        except ValueError:
            await adapter.send_message(chat_id, "Нужно неотрицательное целое число (копейки).", append_main_menu_shortcut_row(None))
            return
        field = data.get("field")
        kw = {}
        if field == "monthly":
            kw["monthly_price_kopecks"] = kop
        elif field == "season":
            kw["season_price_kopecks"] = kop
        elif field == "event_creation":
            kw["event_creation_price_kopecks"] = kop
        elif field == "raise_profile":
            kw["raise_profile_price_kopecks"] = kop
        if kw:
            await update_subscription_settings(**kw)
        await reg_state.clear_state(user_id)
        s = await get_subscription_settings()
        await adapter.send_message(
            chat_id,
            "✅ Сохранено.\n\n" + tg_admin._settings_text(s),
            append_main_menu_shortcut_row(max_kb_from_tg_inline(get_settings_kb(s))),
        )
        return


async def handle_max_admin_fsm_callback(
    adapter: MaxAdapter, chat_id: str, user_id: int, cb_data: str, fsm: dict
) -> bool:
    """Callback при активном FSM: категория контакта, подтверждение рассылки."""
    state = (fsm or {}).get("state")
    if state == "admin:contact_edit":
        from src.max_admin_contacts import handle_max_contact_category_fsm_callback

        if await handle_max_contact_category_fsm_callback(
            adapter, chat_id, user_id, cb_data, fsm
        ):
            return True
    if state != "admin:bc_confirm":
        return False
    if cb_data != "admin_bc_confirm":
        return False
    u = await get_or_create_user(platform="max", platform_user_id=user_id)
    if not u or not await _max_superadmin(u):
        await reg_state.clear_state(user_id)
        return True
    from src.max_runner import _get_tg_bot

    fd = fsm.get("data") or {}
    text_bc = fd.get("bc_text")
    seg = fd.get("segment") or {}
    await reg_state.clear_state(user_id)
    if not text_bc:
        await adapter.send_message(chat_id, "Нет текста.", append_main_menu_shortcut_row(None))
        return True
    tg_bot = _get_tg_bot()
    max_ad = get_max_adapter() or adapter
    r_tg = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
        platform=Platform.TELEGRAM,
    )
    r_max = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
        platform=Platform.MAX,
    )
    sent, failed = 0, 0
    if tg_bot and r_tg:
        st, fl = await _do_broadcast(tg_bot, r_tg, text_bc)
        sent += st
        failed += fl
    if max_ad and r_max:
        sm, fm = await _do_max_broadcast(max_ad, r_max, text_bc)
        sent += sm
        failed += fm
    await adapter.send_message(
        chat_id,
        f"✅ Рассылка: отправлено {sent}, ошибок {failed}",
        append_main_menu_shortcut_row(max_kb_from_tg_inline(get_admin_back_kb("admin_panel"))),
    )
    return True
