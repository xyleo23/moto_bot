"""Admin panel — Stage 8."""
import uuid
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config import get_settings
from src.keyboards.admin import (
    get_admin_main_kb,
    get_admin_back_kb,
    get_user_action_kb,
    get_city_admins_kb,
    get_admin_event_kb,
    get_settings_kb,
    get_broadcast_confirm_kb,
)
from src.keyboards.menu import get_back_to_menu_kb
from src.services.admin_service import (
    get_stats,
    get_users_list,
    block_user,
    unblock_user,
    get_user_by_id,
    get_user_by_platform_id,
    get_cities,
    get_city_admins,
    add_city_admin,
    remove_city_admin,
    is_superadmin,
    is_city_admin,
    can_admin_events,
    get_subscription_settings,
    update_subscription_settings,
    extend_subscription,
    deactivate_subscription,
    get_admin_events,
    admin_cancel_event,
    set_event_recommended,
    get_broadcast_recipients,
    get_global_text,
    set_global_text,
)
from src.services.event_service import TYPE_LABELS, get_event_by_id
from loguru import logger

router = Router()

USERS_PAGE_SIZE = 10


def _is_superadmin(user_id: int) -> bool:
    return user_id in get_settings().superadmin_ids


class AdminUserSearchStates(StatesGroup):
    search = State()


class AdminAddCityAdminStates(StatesGroup):
    user_id = State()


class AdminBroadcastStates(StatesGroup):
    segment = State()
    message = State()


class AdminExtendSubStates(StatesGroup):
    days = State()


class AdminSettingsStates(StatesGroup):
    monthly_price = State()
    season_price = State()


class AdminTextAboutStates(StatesGroup):
    text = State()


# ——— Main / Stats ———

@router.message(Command("admin"))
async def cmd_admin(message: Message, user=None):
    if _is_superadmin(message.from_user.id):
        await message.answer("Админ-панель", reply_markup=get_admin_main_kb())
        return
    if user and user.city_id and await is_city_admin(message.from_user.id, user.city_id):
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мероприятия", callback_data="admin_events")],
            [InlineKeyboardButton(text="📇 Полезные контакты", callback_data="admin_contacts")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ])
        await message.answer("Админ города", reply_markup=kb)


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery, user=None):
    if _is_superadmin(callback.from_user.id):
        await callback.message.edit_text("Админ-панель", reply_markup=get_admin_main_kb())
        await callback.answer()
        return
    if user and user.city_id and await is_city_admin(callback.from_user.id, user.city_id):
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📅 Мероприятия", callback_data="admin_events")],
            [InlineKeyboardButton(text="📇 Полезные контакты", callback_data="admin_contacts")],
            [InlineKeyboardButton(text="« Назад", callback_data="menu_main")],
        ])
        await callback.message.edit_text("Админ города", reply_markup=kb)
        await callback.answer()
        return
    await callback.answer("Доступ запрещён.")


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    stats = await get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей: {stats.get('users', 0)}\n"
        f"Заблокировано: {stats.get('blocked', 0)}\n"
        f"Активных подписок: {stats.get('active_subs', 0)}\n"
        f"SOS-сигналов: {stats.get('sos', 0)}\n"
        f"Мероприятий: {stats.get('events', 0)}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_back_kb())
    await callback.answer()


# ——— Users: block/unblock ———

@router.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.clear()
    users, total = await get_users_list(limit=USERS_PAGE_SIZE, offset=0)
    await _render_users_page(callback, users, total, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_users_p"))
async def cb_admin_users_page(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    try:
        page = int(callback.data.replace("admin_users_p", ""))
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    search = data.get("admin_search")
    users, total = await get_users_list(
        limit=USERS_PAGE_SIZE,
        offset=page * USERS_PAGE_SIZE,
        search=search,
    )
    await _render_users_page(callback, users, total, page)
    await callback.answer()


@router.callback_query(F.data == "admin_users_search")
async def cb_admin_users_search_start(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminUserSearchStates.search)
    await callback.message.edit_text(
        "Введи ID, username или имя для поиска (или «Сброс» для сброса):",
        reply_markup=get_admin_back_kb("admin_users"),
    )
    await callback.answer()


@router.message(AdminUserSearchStates.search, F.text)
async def admin_users_search_input(message: Message, state: FSMContext):
    search_text = message.text.strip()
    if search_text.lower() in ("сброс", "reset", "-"):
        await state.update_data(admin_search=None)
        users, total = await get_users_list(limit=USERS_PAGE_SIZE, offset=0)
    else:
        await state.update_data(admin_search=search_text)
        users, total = await get_users_list(limit=USERS_PAGE_SIZE, offset=0, search=search_text)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for u in users:
        bl = " 🔒" if u.is_blocked else ""
        rows.append([InlineKeyboardButton(
            text=f"{u.platform_user_id} {u.platform_first_name or '?'}{bl}",
            callback_data=f"admin_user_view_{u.id}",
        )])
    if total > USERS_PAGE_SIZE:
        rows.append([InlineKeyboardButton(text="След ▶", callback_data="admin_users_p1")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_users")])
    text = f"<b>Пользователи</b> (найдено {total}):\n\nНажми для действий." if users else "Никого не найдено."
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _render_users_page(callback: CallbackQuery, users: list, total: int, page: int):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for u in users:
        bl = " 🔒" if u.is_blocked else ""
        rows.append([InlineKeyboardButton(
            text=f"{u.platform_user_id} {u.platform_first_name or '?'}{bl}",
            callback_data=f"admin_user_view_{u.id}",
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ Пред", callback_data=f"admin_users_p{page - 1}"))
    if total > (page + 1) * USERS_PAGE_SIZE:
        nav.append(InlineKeyboardButton(text="След ▶", callback_data=f"admin_users_p{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_users_search")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    text = f"<b>Пользователи</b> (всего {total}):\n\nНажми на пользователя для действий."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("admin_user_view_"))
async def cb_admin_user_view(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    uid = callback.data.replace("admin_user_view_", "")
    try:
        user_uuid = uuid.UUID(uid)
    except ValueError:
        await callback.answer("Ошибка.")
        return
    u = await get_user_by_id(user_uuid)
    if not u:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    text = (
        f"<b>Пользователь</b>\n"
        f"ID: {u.platform_user_id}\n"
        f"Username: @{u.platform_username or '—'}\n"
        f"Имя: {u.platform_first_name or '—'}\n"
        f"Статус: {'🔒 Заблокирован' if u.is_blocked else '✅ Активен'}\n"
        f"Причина блокировки: {u.block_reason or '—'}"
    )
    await callback.message.edit_text(text, reply_markup=get_user_action_kb(uid, u.is_blocked))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_block_"))
@router.callback_query(F.data.startswith("admin_user_unblock_"))
async def cb_admin_user_block_toggle(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    parts = callback.data.split("_")
    action, uid = parts[-2], parts[-1]
    try:
        user_uuid = uuid.UUID(uid)
    except ValueError:
        await callback.answer("Ошибка.", show_alert=True)
        return
    u = await get_user_by_id(user_uuid)
    if not u:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    if action == "block":
        await block_user(user_uuid)
        await callback.answer("Пользователь заблокирован.")
        try:
            await callback.bot.send_message(
                u.platform_user_id,
                "Вы заблокированы. Обратитесь в поддержку.",
            )
        except Exception:
            pass
        u.is_blocked = True
    else:
        await unblock_user(user_uuid)
        await callback.answer("Пользователь разблокирован.")
        u.is_blocked = False
    text = (
        f"<b>Пользователь</b>\n"
        f"ID: {u.platform_user_id}\n"
        f"Username: @{u.platform_username or '—'}\n"
        f"Имя: {u.platform_first_name or '—'}\n"
        f"Статус: {'🔒 Заблокирован' if u.is_blocked else '✅ Активен'}"
    )
    await callback.message.edit_text(text, reply_markup=get_user_action_kb(uid, u.is_blocked))


@router.callback_query(F.data.startswith("admin_sub_extend_"))
async def cb_admin_sub_extend(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    uid = callback.data.replace("admin_sub_extend_", "")
    try:
        user_uuid = uuid.UUID(uid)
    except ValueError:
        await callback.answer("Ошибка.")
        return
    await state.update_data(admin_extend_user=uid)
    await state.set_state(AdminExtendSubStates.days)
    await callback.message.edit_text(
        "Введи количество дней для продления подписки (число):",
        reply_markup=get_admin_back_kb("admin_users"),
    )
    await callback.answer()


@router.message(AdminExtendSubStates.days, F.text)
async def admin_sub_extend_days(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("admin_extend_user")
    if not uid:
        await state.clear()
        return
    try:
        days = int(message.text.strip())
        if days < 1 or days > 365:
            raise ValueError("invalid")
    except ValueError:
        await message.answer("Введи число от 1 до 365.")
        return
    ok, msg = await extend_subscription(uuid.UUID(uid), days)
    await message.answer(f"✅ {msg}", reply_markup=get_admin_back_kb("admin_users"))
    await state.clear()


# ——— City admins ———

@router.callback_query(F.data == "admin_city_admins")
async def cb_admin_city_admins(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cities = await get_cities()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = [[InlineKeyboardButton(text=c.name, callback_data=f"admin_ca_city_{c.id}")] for c in cities]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    await callback.message.edit_text(
        "Выбери город для управления админами:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ca_city_"))
async def cb_admin_ca_city(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_ca_city_", "")
    city_uuid = uuid.UUID(cid)
    admins = await get_city_admins(city_uuid)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for ca, u in admins:
        rows.append([
            InlineKeyboardButton(
                text=f"@{u.platform_username or u.platform_user_id} — убрать",
                callback_data=f"admin_ca_rm_{cid}_{u.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="➕ Добавить админа", callback_data=f"admin_ca_add_{cid}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")])
    text = "Админы города:\n\n" + "\n".join(
        f"• {u.platform_username or u.platform_user_id}" for _, u in admins
    ) if admins else "Админов нет."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ca_add_"))
async def cb_admin_ca_add(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_ca_add_", "")
    await state.update_data(admin_ca_city=cid)
    await state.set_state(AdminAddCityAdminStates.user_id)
    await callback.message.edit_text(
        "Введи Telegram user ID нового админа (число):",
        reply_markup=get_admin_back_kb(f"admin_ca_city_{cid}"),
    )
    await callback.answer()


@router.message(AdminAddCityAdminStates.user_id, F.text)
async def admin_ca_add_input(message: Message, state: FSMContext):
    data = await state.get_data()
    cid = data.get("admin_ca_city")
    if not cid:
        await state.clear()
        return
    try:
        platform_user_id = int(message.text.strip())
    except ValueError:
        await message.answer("Введи число (Telegram user ID).")
        return
    u = await get_user_by_platform_id(platform_user_id)
    if not u:
        await message.answer("Пользователь не найден. Он должен хотя бы раз написать боту.")
        return
    city_uuid = uuid.UUID(cid)
    ok, err = await add_city_admin(city_uuid, u.id)
    if ok:
        await message.answer(f"✅ Добавлен админ: @{u.platform_username or u.platform_user_id}")
    else:
        await message.answer(f"❌ {err}")
    await state.clear()
    cities = await get_cities()
    city = next((c for c in cities if str(c.id) == cid), None)
    if city:
        admins = await get_city_admins(city_uuid)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        rows = [[InlineKeyboardButton(text=f"@{x.platform_username or x.platform_user_id} — убрать", callback_data=f"admin_ca_rm_{cid}_{x.id}")] for _, x in admins]
        rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"admin_ca_add_{cid}")])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")])
        await message.answer("Админы города:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("admin_ca_rm_"))
async def cb_admin_ca_remove(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    parts = callback.data.replace("admin_ca_rm_", "").split("_")
    if len(parts) != 2:
        await callback.answer()
        return
    cid, uid = parts[0], parts[1]
    ok = await remove_city_admin(uuid.UUID(cid), uuid.UUID(uid))
    if ok:
        await callback.answer("Админ удалён.")
    else:
        await callback.answer("Ошибка.", show_alert=True)
    cities = await get_cities()
    city_uuid = uuid.UUID(cid)
    admins = await get_city_admins(city_uuid)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = [[InlineKeyboardButton(text=f"@{x.platform_username or x.platform_user_id} — убрать", callback_data=f"admin_ca_rm_{cid}_{x.id}")] for _, x in admins]
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"admin_ca_add_{cid}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")])
    text = "Админы города:\n\n" + "\n".join(f"• {x.platform_username or x.platform_user_id}" for _, x in admins) if admins else "Админов нет."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# ——— Events ———

@router.callback_query(F.data == "admin_events")
async def cb_admin_events(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = user and user.city_id and await is_city_admin(callback.from_user.id, user.city_id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    events = await get_admin_events(superadmin=is_sa, city_id=user.city_id if user else None)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = []
    for e in events[:20]:
        label = e.title or TYPE_LABELS.get(e.type.value, e.type.value)
        rows.append([InlineKeyboardButton(text=f"{e.start_at.strftime('%d.%m')} {label}", callback_data=f"admin_ev_{e.id}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    text = "Мероприятия (последние):\n\n" + "\n".join(
        f"• {(ev.title or TYPE_LABELS.get(ev.type.value, ''))} — {ev.start_at.strftime('%d.%m.%Y')}"
        for ev in events[:20]
    ) if events else "Мероприятий нет."
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ev_"))
async def cb_admin_event_detail(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = user and user.city_id and await is_city_admin(callback.from_user.id, user.city_id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_", "")
    if eid in ("rec", "cancel"):
        return
    try:
        ev_uuid = uuid.UUID(eid)
    except ValueError:
        await callback.answer()
        return
    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await callback.answer("Не найдено.", show_alert=True)
        return
    can_edit = await can_admin_events(
        callback.from_user.id,
        user.city_id if user else None,
        ev.city_id,
    )
    text = (
        f"<b>{ev.title or TYPE_LABELS.get(ev.type.value, 'Мероприятие')}</b>\n"
        f"Тип: {TYPE_LABELS.get(ev.type.value, ev.type.value)}\n"
        f"📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {ev.point_start}\n"
        f"Описание: {ev.description or '—'}\n"
        f"Рекомендуемое: {'✅' if ev.is_recommended else '❌'}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_event_kb(eid, can_edit))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ev_rec_"))
async def cb_admin_ev_recommend(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = user and user.city_id and await is_city_admin(callback.from_user.id, user.city_id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_rec_", "")
    ev = await get_event_by_id(uuid.UUID(eid))
    if not ev:
        await callback.answer("Не найдено.")
        return
    can_edit = await can_admin_events(callback.from_user.id, user.city_id if user else None, ev.city_id)
    if not can_edit:
        await callback.answer("Нет доступа.")
        return
    new_val = not ev.is_recommended
    await set_event_recommended(ev.id, new_val)
    await callback.answer(f"{'Рекомендовано' if new_val else 'Снято с рекомендуемых'}")
    ev = await get_event_by_id(ev.id)
    text = (
        f"<b>{ev.title or TYPE_LABELS.get(ev.type.value, 'Мероприятие')}</b>\n"
        f"Тип: {TYPE_LABELS.get(ev.type.value, ev.type.value)}\n"
        f"📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {ev.point_start}\n"
        f"Описание: {ev.description or '—'}\n"
        f"Рекомендуемое: {'✅' if ev.is_recommended else '❌'}"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_event_kb(eid, can_edit))


@router.callback_query(F.data.startswith("admin_ev_cancel_"))
async def cb_admin_ev_cancel(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = user and user.city_id and await is_city_admin(callback.from_user.id, user.city_id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_cancel_", "")
    ev = await get_event_by_id(uuid.UUID(eid))
    if not ev:
        await callback.answer("Не найдено.")
        return
    can_edit = await can_admin_events(callback.from_user.id, user.city_id if user else None, ev.city_id)
    if not can_edit:
        await callback.answer("Нет доступа.")
        return
    ok, notify_ids = await admin_cancel_event(ev.id)
    if not ok:
        await callback.answer("Ошибка.")
        return
    bot = callback.bot
    for pid in notify_ids:
        try:
            await bot.send_message(pid, f"⚠️ Мероприятие «{ev.title or 'Мероприятие'}» отменено.")
        except Exception:
            pass
    await callback.answer("Мероприятие отменено. Участники уведомлены.")
    await callback.message.edit_text(
        "Мероприятие отменено.",
        reply_markup=get_admin_back_kb("admin_events"),
    )


# ——— Settings ———

@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    s = await get_subscription_settings()
    text = (
        "⚙️ <b>Настройки подписки</b>\n\n"
        f"Подписка: {'✅ вкл' if s.subscription_enabled else '❌ выкл'}\n"
        f"Цена месяца: {s.monthly_price_kopecks / 100:.0f} ₽\n"
        f"Цена сезона: {s.season_price_kopecks / 100:.0f} ₽\n"
        f"Платное создание мероприятий: {'✅' if s.event_creation_enabled else '❌'}\n"
        f"Платное поднятие анкеты: {'✅' if s.raise_profile_enabled else '❌'}"
    )
    await callback.message.edit_text(text, reply_markup=get_settings_kb(s))
    await callback.answer()


def _settings_text(s) -> str:
    return (
        "⚙️ <b>Настройки подписки</b>\n\n"
        f"Подписка: {'✅ вкл' if s.subscription_enabled else '❌ выкл'}\n"
        f"Цена месяца: {s.monthly_price_kopecks / 100:.0f} ₽\n"
        f"Цена сезона: {s.season_price_kopecks / 100:.0f} ₽\n"
        f"Платное создание мероприятий: {'✅' if s.event_creation_enabled else '❌'}\n"
        f"Платное поднятие анкеты: {'✅' if s.raise_profile_enabled else '❌'}"
    )


@router.callback_query(F.data == "admin_set_sub_toggle")
async def cb_admin_set_sub_toggle(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    s = await get_subscription_settings()
    await update_subscription_settings(subscription_enabled=not s.subscription_enabled)
    s = await get_subscription_settings()
    await callback.message.edit_text(_settings_text(s), reply_markup=get_settings_kb(s))
    await callback.answer()


@router.callback_query(F.data == "admin_set_ev_toggle")
async def cb_admin_set_ev_toggle(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    s = await get_subscription_settings()
    await update_subscription_settings(event_creation_enabled=not s.event_creation_enabled)
    s = await get_subscription_settings()
    await callback.message.edit_text(_settings_text(s), reply_markup=get_settings_kb(s))
    await callback.answer()


@router.callback_query(F.data == "admin_set_raise_toggle")
async def cb_admin_set_raise_toggle(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    s = await get_subscription_settings()
    await update_subscription_settings(raise_profile_enabled=not s.raise_profile_enabled)
    s = await get_subscription_settings()
    await callback.message.edit_text(_settings_text(s), reply_markup=get_settings_kb(s))
    await callback.answer()


@router.callback_query(F.data == "admin_set_monthly")
async def cb_admin_set_monthly(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminSettingsStates.monthly_price)
    await state.update_data(admin_set_key="monthly")
    await callback.message.edit_text("Введи цену месяца в копейках (например 29900 = 299 ₽):")
    await callback.answer()


@router.callback_query(F.data == "admin_set_season")
async def cb_admin_set_season(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminSettingsStates.season_price)
    await state.update_data(admin_set_key="season")
    await callback.message.edit_text("Введи цену сезона в копейках (например 79900):")
    await callback.answer()


@router.message(AdminSettingsStates.monthly_price, F.text)
async def admin_set_price_monthly(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("admin_set_key") != "monthly":
        await state.clear()
        return
    try:
        val = int(message.text.strip())
        if val < 0 or val > 10000000:
            raise ValueError()
    except ValueError:
        await message.answer("Введи число копеек (0–10000000).")
        return
    await update_subscription_settings(monthly_price_kopecks=val)
    s = await get_subscription_settings()
    await message.answer(_settings_text(s), reply_markup=get_settings_kb(s))
    await state.clear()


@router.message(AdminSettingsStates.season_price, F.text)
async def admin_set_price_season(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("admin_set_key") != "season":
        await state.clear()
        return
    try:
        val = int(message.text.strip())
        if val < 0 or val > 10000000:
            raise ValueError()
    except ValueError:
        await message.answer("Введи число копеек.")
        return
    await update_subscription_settings(season_price_kopecks=val)
    s = await get_subscription_settings()
    await message.answer(_settings_text(s), reply_markup=get_settings_kb(s))
    await state.clear()


# ——— Global texts: О нас ———

@router.callback_query(F.data == "admin_text_about")
async def cb_admin_text_about(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    text = await get_global_text("about_us")
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏ Изменить", callback_data="admin_text_about_edit")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
    ])
    await callback.message.edit_text(
        f"<b>Текст «О нас»</b> (показывается в разделе О нас):\n\n{text or '(не задан)'}",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_text_about_edit")
async def cb_admin_text_about_edit(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminTextAboutStates.text)
    text = await get_global_text("about_us")
    await callback.message.edit_text(
        f"Отправь новый текст для «О нас». Сейчас:\n\n{text or ''}\n\nОтправь сообщение с новым текстом.",
        reply_markup=get_admin_back_kb("admin_text_about"),
    )
    await callback.answer()


@router.message(AdminTextAboutStates.text, F.text)
async def admin_text_about_save(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    text = message.text.strip()[:5000]
    await set_global_text("about_us", text or "О нас")
    await state.clear()
    await message.answer(
        f"✅ Текст «О нас» сохранён ({len(text)} символов).",
        reply_markup=get_admin_back_kb("admin_panel"),
    )


# ——— Broadcast ———

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rows = [
        [InlineKeyboardButton(text="Всем", callback_data="admin_bc_all")],
        [InlineKeyboardButton(text="Только Пилотам", callback_data="admin_bc_role_pilot")],
        [InlineKeyboardButton(text="Только Двоек", callback_data="admin_bc_role_passenger")],
        [InlineKeyboardButton(text="С подпиской", callback_data="admin_bc_sub_yes")],
        [InlineKeyboardButton(text="Без подписки", callback_data="admin_bc_sub_no")],
    ]
    cities = await get_cities()
    for c in cities:
        rows.append([InlineKeyboardButton(text=f"Город: {c.name}", callback_data=f"admin_bc_city_{c.id}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(
        "Выбери сегмент для рассылки:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_bc_"))
async def cb_admin_broadcast_segment(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    data = callback.data.replace("admin_bc_", "")
    if data == "all":
        seg = {"city_id": None, "role": None, "with_subscription": None}
    elif data.startswith("role_"):
        seg = {"city_id": None, "role": data.replace("role_", ""), "with_subscription": None}
    elif data.startswith("sub_"):
        seg = {"city_id": None, "role": None, "with_subscription": data == "sub_yes"}
    elif data.startswith("city_"):
        cid = uuid.UUID(data.replace("city_", ""))
        seg = {"city_id": cid, "role": None, "with_subscription": None}
    else:
        await callback.answer()
        return
    await state.update_data(admin_bc_segment=seg)
    await state.set_state(AdminBroadcastStates.message)
    await callback.message.edit_text("Введи текст рассылки (поддерживается HTML):")
    await callback.answer()


@router.message(AdminBroadcastStates.message, F.text)
async def admin_broadcast_message(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        return
    data = await state.get_data()
    seg = data.get("admin_bc_segment") or {}
    recipients = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
    )
    text = message.text
    await state.update_data(admin_bc_text=text, admin_bc_count=len(recipients))
    await state.set_state(AdminBroadcastStates.segment)
    await message.answer(
        f"Получателей: {len(recipients)}. Отправить?",
        reply_markup=get_broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "admin_bc_confirm")
async def cb_admin_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    data = await state.get_data()
    text = data.get("admin_bc_text")
    count = data.get("admin_bc_count", 0)
    if not text:
        await callback.answer("Нет текста.")
        return
    seg = data.get("admin_bc_segment") or {}
    recipients = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
    )
    sent, failed = 0, 0
    for uid in recipients:
        try:
            await callback.bot.send_message(uid, text)
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning("Broadcast failed to %s: %s", uid, e)
    await state.clear()
    await callback.message.edit_text(
        f"✅ Рассылка завершена: отправлено {sent}, ошибок {failed}",
        reply_markup=get_admin_back_kb(),
    )
    await callback.answer()
