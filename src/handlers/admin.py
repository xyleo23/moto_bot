"""Admin panel — Stage 8."""

import uuid
from html import escape
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config import get_settings
from src.utils.callback_short import put_city_admin_remove, get_city_admin_remove
from src.models.user import Platform as UserPlatform
from src.services.broadcast import (
    get_max_adapter,
    _do_broadcast,
    _do_max_broadcast,
)
from src.keyboards.admin import (
    get_admin_back_kb,
    get_user_action_kb,
    get_admin_event_kb,
    get_settings_kb,
    get_broadcast_confirm_kb,
)
from src.keyboards.menu import (
    get_admin_superadmin_kb,
    get_admin_city_kb,
)
from src.services.admin_service import (
    get_stats,
    get_users_list,
    block_user,
    unblock_user,
    get_user_by_id,
    get_user_by_platform_numeric_id_any,
    get_cities,
    get_all_cities,
    create_city,
    update_city,
    get_city_admins,
    add_city_admin,
    remove_city_admin,
    is_city_admin,
    can_admin_events,
    can_admin_events_user,
    get_subscription_settings,
    update_subscription_settings,
    extend_subscription,
    get_admin_events,
    get_effective_city_admin_city_ids,
    admin_cancel_event,
    set_event_recommended,
    set_event_official,
    set_event_hidden,
    get_broadcast_recipients,
    get_global_text,
    set_global_text,
    get_effective_support_email,
    get_effective_support_username,
    GLOBAL_TEXT_SUPPORT_EMAIL,
    GLOBAL_TEXT_SUPPORT_USERNAME,
)
from src.services.event_service import TYPE_LABELS, get_event_by_id
from src.services.activity_log_service import get_logs, get_event_type_labels
from loguru import logger

router = Router()

USERS_PAGE_SIZE = 10


def _is_superadmin(user_id: int) -> bool:
    return user_id in get_settings().superadmin_ids


class AdminUserSearchStates(StatesGroup):
    search = State()


class AdminAddCityAdminStates(StatesGroup):
    user_id = State()


class AdminCitiesStates(StatesGroup):
    name = State()


class AdminBroadcastStates(StatesGroup):
    segment = State()
    message = State()


class AdminExtendSubStates(StatesGroup):
    days = State()


class AdminSettingsStates(StatesGroup):
    monthly_price = State()
    season_price = State()
    event_creation_price = State()
    raise_profile_price = State()


class AdminTextAboutStates(StatesGroup):
    text = State()


class AdminSupportContactStates(StatesGroup):
    email = State()
    username = State()


class AdminTemplatesStates(StatesGroup):
    template_key = State()
    text = State()


# ——— Main / Stats ———


def _inline_payments_row():
    from aiogram.types import InlineKeyboardButton

    return [InlineKeyboardButton(text="💰 Подписки и оплаты", callback_data="admin_settings")]


def _about_admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏ Изменить", callback_data="admin_text_about_edit"),
                InlineKeyboardButton(text="👁 Предпросмотр", callback_data="admin_text_about_preview"),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сбросить к умолчанию", callback_data="admin_text_about_reset"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📞 Контакты поддержки", callback_data="admin_support_contact"
                )
            ],
            _inline_payments_row(),
            [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
        ]
    )


def _about_admin_panel_caption(text: str | None) -> str:
    raw = text if (text and text.strip()) else "(не задан — пользователям покажется текст по умолчанию)"
    clipped = raw if len(raw) <= 3500 else raw[:3497] + "…"
    return (
        "<b>Текст «О нас»</b>\n"
        "<i>Редактируется только основной блок. Внизу у пользователей автоматически "
        "добавляются email и Telegram из «Контакты поддержки».</i>\n\n"
        f"<pre>{escape(clipped)}</pre>\n\n"
        "Допустим HTML в тексте: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, "
        "<code>&lt;a href=\"…\"&gt;</code>. Символ <code>&lt;</code> в обычном тексте "
        "пиши как <code>&amp;lt;</code>."
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, user=None):
    from src.services.admin_service import get_city_admin_city_id

    if _is_superadmin(message.from_user.id):
        await message.answer(
            "⚙️ <b>Админ-панель</b>\n\nВыбери раздел:",
            reply_markup=get_admin_superadmin_kb(),
        )
        return
    city_id = (user.city_id if user and user.city_id else None) or await get_city_admin_city_id(
        message.from_user.id
    )
    if city_id and await is_city_admin(message.from_user.id, city_id):
        await message.answer(
            "⚙️ <b>Админ города</b>\n\nВыбери раздел:",
            reply_markup=get_admin_city_kb(),
        )
        return
    from src import texts as _texts

    await message.answer(_texts.ADMIN_ACCESS_DENIED)


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery, user=None):
    if _is_superadmin(callback.from_user.id):
        await callback.message.answer(
            "⚙️ <b>Админ-панель</b>\n\nВыбери раздел:",
            reply_markup=get_admin_superadmin_kb(),
        )
        await callback.answer()
        return
    if user and user.city_id and await is_city_admin(callback.from_user.id, user.city_id):
        await callback.message.answer(
            "⚙️ <b>Админ города</b>\n\nВыбери раздел:",
            reply_markup=get_admin_city_kb(),
        )
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
    await callback.message.edit_text(text, reply_markup=_admin_stats_markup())
    await callback.answer()


LOGS_PAGE_SIZE = 15


def _build_logs_page(logs: list, total: int, page: int, event_type: str | None):
    """Build logs list text and keyboard."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    labels = get_event_type_labels()
    lines = []
    for log, user in logs:
        ts = log.created_at.strftime("%d.%m %H:%M") if log.created_at else ""
        lbl = labels.get(log.event_type, log.event_type)
        uid = f"{user.platform_user_id}" if user else (str(log.user_id)[:8] if log.user_id else "-")
        name = (user.platform_first_name or "?") if user else "-"
        lines.append(f"• {ts} | {lbl} | {uid} {name}")
    text = f"<b>📋 Логи активности</b> (всего {total})\n\n" + "\n".join(
        lines or ["Пока нет записей."]
    )
    rows = []
    # Filter buttons
    filter_rows = []
    for et, lbl in labels.items():
        sel = " ✓" if et == event_type else ""
        filter_rows.append(
            InlineKeyboardButton(text=f"{lbl}{sel}", callback_data=f"admin_logs_t_{et}")
        )
    if len(filter_rows) <= 4:
        rows.append(filter_rows)
    else:
        rows.append(filter_rows[:3])
        rows.append(filter_rows[3:])
    rows.append([InlineKeyboardButton(text="Все типы", callback_data="admin_logs_t_")])
    # Pagination
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀ Пред", callback_data=f"admin_logs_p{page - 1}_{event_type or ''}"
            )
        )
    if total > (page + 1) * LOGS_PAGE_SIZE:
        nav.append(
            InlineKeyboardButton(
                text="След ▶", callback_data=f"admin_logs_p{page + 1}_{event_type or ''}"
            )
        )
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton(text="💰 Подписки и оплаты", callback_data="admin_settings")]
    )
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin_logs")
async def cb_admin_logs(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    logs, total = await get_logs(limit=LOGS_PAGE_SIZE, offset=0)
    text, kb = _build_logs_page(logs, total, 0, None)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_logs_t_"))
async def cb_admin_logs_filter(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    event_type = callback.data.replace("admin_logs_t_", "") or None
    logs, total = await get_logs(event_type=event_type, limit=LOGS_PAGE_SIZE, offset=0)
    text, kb = _build_logs_page(logs, total, 0, event_type)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_logs_p"))
async def cb_admin_logs_page(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    parts = callback.data.replace("admin_logs_p", "").split("_")
    try:
        page = int(parts[0]) if parts else 0
    except ValueError:
        page = 0
    event_type = parts[1] if len(parts) > 1 and parts[1] else None
    logs, total = await get_logs(
        event_type=event_type, limit=LOGS_PAGE_SIZE, offset=page * LOGS_PAGE_SIZE
    )
    text, kb = _build_logs_page(logs, total, page, event_type)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ——— ReplyKeyboard text buttons (superadmin / city admin) ———


def _admin_stats_markup():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Подписки и оплаты",
                    callback_data="admin_settings",
                )
            ],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
        ]
    )


async def _show_admin_stats(message: Message):
    """Show stats — used by both callback and text handler."""
    stats = await get_stats()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей: {stats.get('users', 0)}\n"
        f"Заблокировано: {stats.get('blocked', 0)}\n"
        f"Активных подписок: {stats.get('active_subs', 0)}\n"
        f"SOS-сигналов: {stats.get('sos', 0)}\n"
        f"Мероприятий: {stats.get('events', 0)}"
    )
    await message.answer(text, reply_markup=_admin_stats_markup())


def _build_users_page(users: list, total: int, page: int, *, payment_row: bool = False):
    """Build users list (text + markup) for both callback and message."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = []
    if payment_row:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💰 Подписки и оплаты",
                    callback_data="admin_settings",
                )
            ]
        )
    for u in users:
        bl = " 🔒" if u.is_blocked else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{u.platform_user_id} {u.platform_first_name or '?'}{bl}",
                    callback_data=f"admin_user_view_{u.id}",
                )
            ]
        )
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
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "📊 Статистика")
async def msg_admin_stats(message: Message, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    await _show_admin_stats(message)


@router.message(F.text == "👥 Пользователи")
async def msg_admin_users(message: Message, state: FSMContext, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    await state.clear()
    users, total = await get_users_list(limit=USERS_PAGE_SIZE, offset=0)
    text, kb = _build_users_page(users, total, 0, payment_row=True)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == "🏙 Города")
async def msg_admin_cities(message: Message, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    text, kb = await _admin_cities_list_text_kb()
    await message.answer(text, reply_markup=kb)


@router.message(F.text.in_({"🏙 Админы городов", "👤 Админы городов"}))
async def msg_admin_city_admins(message: Message, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    cities = await get_cities()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = [
        [InlineKeyboardButton(text=c.name, callback_data=f"admin_ca_city_{c.id}")] for c in cities
    ]
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    await message.answer(
        "Выбери город для управления админами:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(F.text.in_({"⚙️ Настройки", "💰 Подписки и оплаты"}))
async def msg_admin_settings(message: Message, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    s = await get_subscription_settings()
    await message.answer(_settings_text(s), reply_markup=get_settings_kb(s))


@router.message(F.text == "📧 Шаблоны")
async def msg_admin_templates(message: Message, state: FSMContext, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    await state.clear()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.notification_templates import TEMPLATE_KEYS

    rows = []
    for key, (_default, _desc) in TEMPLATE_KEYS.items():
        label = key.replace("template_", "").replace("_", " ").title()
        rows.append(
            [InlineKeyboardButton(text=f"✏ {label}", callback_data=f"admin_tpl_edit_{key}")]
        )
    rows.append(_inline_payments_row())
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    await message.answer(
        "<b>📧 Шаблоны уведомлений</b>\n\n"
        "Выбери шаблон для редактирования. Поддерживаются плейсхолдеры: "
        "<code>{profile}</code>, <code>{period}</code> и т.д.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.message(F.text == "📋 Логи")
async def msg_admin_logs(message: Message, user=None):
    if not _is_superadmin(message.from_user.id):
        return

    logs, total = await get_logs(limit=LOGS_PAGE_SIZE, offset=0)
    text, kb = _build_logs_page(logs, total, 0, None)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == "📢 Рассылка")
async def msg_admin_broadcast(message: Message, state: FSMContext, user=None):
    if not _is_superadmin(message.from_user.id):
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
        rows.append(
            [InlineKeyboardButton(text=f"Город: {c.name}", callback_data=f"admin_bc_city_{c.id}")]
        )
    rows.append(_inline_payments_row())
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer("Выбери сегмент для рассылки:", reply_markup=kb)


@router.message(F.text.in_({"📇 Контакты", "📁 Контакты", "🗃️ Контакты"}))
async def msg_admin_contacts(message: Message, user=None):
    from src.services.useful_contacts_service import can_manage_contacts_effective

    if not user or not await can_manage_contacts_effective(user):
        return
    from src.keyboards.contacts import get_admin_contacts_menu_kb

    await message.answer("Контакты — управление", reply_markup=get_admin_contacts_menu_kb())


@router.message(F.text.in_({"📞 Контакты поддержки", "📞 Поддержка (бот)"}))
async def msg_admin_support_contact(message: Message, state: FSMContext, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    await state.clear()
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
            _inline_payments_row(),
            [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
        ]
    )
    await message.answer(
        "<b>📞 Контакты поддержки</b>\n\n"
        f"Пользователям сейчас показываются:\n📧 <code>{email}</code>\n"
        f"👤 <code>@{uname}</code>\n\n"
        f"<i>В БД (пусто = взять из .env):</i>\n"
        f"email: <code>{db_mail or '—'}</code>\n"
        f"username: <code>{db_user or '—'}</code>",
        reply_markup=kb,
    )


@router.message(F.text.in_({"📝 О нас", "📝 Текст «О нас»"}))
async def msg_admin_text_about(message: Message, state: FSMContext, user=None):
    if not _is_superadmin(message.from_user.id):
        return
    await state.clear()
    text = await get_global_text("about_us")
    await message.answer(
        _about_admin_panel_caption(text),
        reply_markup=_about_admin_panel_kb(),
        parse_mode=ParseMode.HTML,
    )


@router.message(F.text == "🏠 Главное меню")
async def msg_admin_main_menu(message: Message, state: FSMContext, user=None):
    """Return to main menu — always works as escape hatch (e.g. after losing admin rights)."""
    from src import texts
    from src.keyboards.menu import get_main_menu_kb_for_user, get_reply_keyboard_for_user

    await state.clear()
    await message.answer(
        "⌨️",
        reply_markup=await get_reply_keyboard_for_user(message.from_user.id, user),
    )
    await message.answer(
        texts.WELCOME_RETURNING,
        reply_markup=await get_main_menu_kb_for_user(message.from_user.id, user),
    )


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
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{u.platform_user_id} {u.platform_first_name or '?'}{bl}",
                    callback_data=f"admin_user_view_{u.id}",
                )
            ]
        )
    if total > USERS_PAGE_SIZE:
        rows.append([InlineKeyboardButton(text="След ▶", callback_data="admin_users_p1")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_users")])
    text = (
        f"<b>Пользователи</b> (найдено {total}):\n\nНажми для действий."
        if users
        else "Никого не найдено."
    )
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _render_users_page(callback: CallbackQuery, users: list, total: int, page: int):
    text, kb = _build_users_page(users, total, page, payment_row=True)
    await callback.message.edit_text(text, reply_markup=kb)


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
        except Exception as e:
            logger.debug("block_user: could not notify user {}: {}", u.platform_user_id, e)
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
        uuid.UUID(uid)
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


# ——— Cities CRUD ———


def _admin_cities_kb() -> InlineKeyboardMarkup:
    from aiogram.types import InlineKeyboardButton

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить город", callback_data="admin_cities_add")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
        ]
    )


async def _admin_cities_list_text_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    cities = await get_all_cities()
    rows = []
    for c in cities:
        status = "✅" if c.is_active else "❌"
        rows.append(
            [
                InlineKeyboardButton(text=f"{status} {c.name}", callback_data=f"admin_city_{c.id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ Добавить город", callback_data="admin_cities_add")])
    rows.append(_inline_payments_row())
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    text = (
        "🏙 <b>Города</b>\n\n"
        + "\n".join(f"{'✅' if c.is_active else '❌'} {c.name}" for c in cities)
        if cities
        else "Городов пока нет."
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin_cities")
async def cb_admin_cities(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    text, kb = await _admin_cities_list_text_kb()
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_city_edit_"))
async def cb_admin_city_edit(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_city_edit_", "")
    await state.set_state(AdminCitiesStates.name)
    await state.update_data(admin_cities_action="edit", admin_cities_id=cid)
    await callback.message.edit_text(
        "Введи новое название города:",
        reply_markup=get_admin_back_kb("admin_cities"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_city_toggle_"))
async def cb_admin_city_toggle(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_city_toggle_", "")
    cities = await get_all_cities()
    city = next((c for c in cities if str(c.id) == cid), None)
    if not city:
        await callback.answer("Город не найден.")
        return
    ok, _ = await update_city(uuid.UUID(cid), is_active=not city.is_active)
    if ok:
        await callback.answer(f"{'Активирован' if not city.is_active else 'Деактивирован'}")
    else:
        await callback.answer("Ошибка.", show_alert=True)
    text, kb = await _admin_cities_list_text_kb()
    await callback.message.edit_text(text, reply_markup=kb)


@router.callback_query(
    F.data.startswith("admin_city_")
    & (F.data != "admin_city_admins")
    & ~F.data.startswith("admin_city_edit_")
    & ~F.data.startswith("admin_city_toggle_"),
)
async def cb_admin_city_detail(callback: CallbackQuery):
    """Single city: Edit name, Activate/Deactivate."""
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cid = callback.data.replace("admin_city_", "", 1)
    cities = await get_all_cities()
    city = next((c for c in cities if str(c.id) == cid), None)
    if not city:
        await callback.answer("Город не найден.")
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = [
        [InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"admin_city_edit_{cid}")],
        [
            InlineKeyboardButton(
                text="✅ Активировать" if not city.is_active else "❌ Деактивировать",
                callback_data=f"admin_city_toggle_{cid}",
            )
        ],
        [InlineKeyboardButton(text="« К списку", callback_data="admin_cities")],
    ]
    text = f"🏙 {city.name}\nСтатус: {'активен' if city.is_active else 'неактивен'}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "admin_cities_add")
async def cb_admin_cities_add(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminCitiesStates.name)
    await state.update_data(admin_cities_action="add")
    await callback.message.edit_text(
        "Введи название нового города:",
        reply_markup=get_admin_back_kb("admin_cities"),
    )
    await callback.answer()


@router.message(AdminCitiesStates.name, F.text)
async def admin_cities_name_input(message: Message, state: FSMContext):
    data = await state.get_data()
    action = data.get("admin_cities_action")
    cid = data.get("admin_cities_id")
    name = (message.text or "").strip()[:100]
    await state.clear()
    if not name:
        await message.answer("Название не может быть пустым.", reply_markup=_admin_cities_kb())
        return
    if action == "add":
        city, err = await create_city(name)
        if city:
            await message.answer(
                f"✅ Город «{city.name}» создан.", reply_markup=get_admin_back_kb("admin_cities")
            )
        else:
            await message.answer(f"❌ {err}", reply_markup=get_admin_back_kb("admin_cities"))
    elif action == "edit" and cid:
        ok, err = await update_city(uuid.UUID(cid), name=name)
        if ok:
            await message.answer(
                f"✅ Переименовано в «{name}».", reply_markup=get_admin_back_kb("admin_cities")
            )
        else:
            await message.answer(f"❌ {err}", reply_markup=get_admin_back_kb("admin_cities"))
    else:
        await message.answer("Ошибка.", reply_markup=get_admin_back_kb("admin_cities"))


# ——— City admins ———


@router.callback_query(F.data == "admin_city_admins")
async def cb_admin_city_admins(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    cities = await get_cities()
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = [
        [InlineKeyboardButton(text=c.name, callback_data=f"admin_ca_city_{c.id}")] for c in cities
    ]
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
        rm_code = put_city_admin_remove(city_uuid, u.id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"@{u.platform_username or u.platform_user_id} — убрать",
                    callback_data=f"cam_{rm_code}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data=f"admin_ca_add_{cid}")]
    )
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")])
    text = (
        "Админы города:\n\n"
        + "\n".join(f"• {u.platform_username or u.platform_user_id}" for _, u in admins)
        if admins
        else "Админов нет."
    )
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
        "Введи <b>числовой ID</b> пользователя: <b>Telegram</b> или <b>MAX</b> "
        "(в MAX можно посмотреть командой <code>/myid</code>).",
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
        await message.answer("Введи число (ID из Telegram или MAX).")
        return
    u = await get_user_by_platform_numeric_id_any(platform_user_id)
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

        rows = []
        for _, x in admins:
            rm_code = put_city_admin_remove(city_uuid, x.id)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"@{x.platform_username or x.platform_user_id} — убрать",
                        callback_data=f"cam_{rm_code}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"admin_ca_add_{cid}")])
        rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")])
        await message.answer(
            "Админы города:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )


@router.callback_query(F.data.startswith("cam_"))
async def cb_admin_ca_remove(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    code = callback.data[4:]
    pair = get_city_admin_remove(code)
    if not pair:
        await callback.answer("Кнопка устарела.", show_alert=True)
        return
    cid_uuid, uid_uuid = pair
    ok = await remove_city_admin(cid_uuid, uid_uuid)
    if ok:
        await callback.answer("Админ удалён.")
    else:
        await callback.answer("Ошибка.", show_alert=True)
    city_uuid = cid_uuid
    admins = await get_city_admins(city_uuid)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = []
    for _, x in admins:
        rm_code = put_city_admin_remove(city_uuid, x.id)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"@{x.platform_username or x.platform_user_id} — убрать",
                    callback_data=f"cam_{rm_code}",
                )
            ]
        )
    cid = str(city_uuid)
    rows.append([InlineKeyboardButton(text="➕ Добавить", callback_data=f"admin_ca_add_{cid}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_city_admins")])
    text = (
        "Админы города:\n\n"
        + "\n".join(f"• {x.platform_username or x.platform_user_id}" for _, x in admins)
        if admins
        else "Админов нет."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# ——— Events ———


async def _tg_user_can_open_admin_events_menu(user, telegram_user_id: int) -> bool:
    """Доступ к разделу админских мероприятий: TG city_id или CityAdmin по связанным User."""
    if not user:
        return False
    if user.city_id and await is_city_admin(telegram_user_id, user.city_id):
        return True
    if await get_effective_city_admin_city_ids(user):
        return True
    return False


@router.callback_query(F.data == "admin_events")
async def cb_admin_events(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    if is_sa:
        events = await get_admin_events(superadmin=True)
    else:
        cids = await get_effective_city_admin_city_ids(user)
        if not cids and user and user.city_id:
            cids = [user.city_id]
        events = await get_admin_events(superadmin=False, city_ids=cids or [])
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows = []
    if is_sa:
        rows.append(
            [
                InlineKeyboardButton(
                    text="💰 Цена создания мероприятия",
                    callback_data="admin_set_event_creation_price",
                )
            ]
        )
    for e in events[:20]:
        label = e.title or TYPE_LABELS.get(e.type.value, e.type.value)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{e.start_at.strftime('%d.%m')} {label}", callback_data=f"admin_ev_{e.id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    text = (
        "Мероприятия (последние):\n\n"
        + "\n".join(
            f"• {(ev.title or TYPE_LABELS.get(ev.type.value, ''))} — {ev.start_at.strftime('%d.%m.%Y')}"
            for ev in events[:20]
        )
        if events
        else "Мероприятий нет."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(
    F.data.startswith("admin_ev_")
    & ~F.data.startswith("admin_ev_rec_")
    & ~F.data.startswith("admin_ev_official_")
    & ~F.data.startswith("admin_ev_cancel_")
    & ~F.data.startswith("admin_evreport_"),
)
async def cb_admin_event_detail(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_", "", 1)
    try:
        ev_uuid = uuid.UUID(eid)
    except ValueError:
        await callback.answer()
        return
    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await callback.answer("Не найдено.", show_alert=True)
        return
    can_edit = user and await can_admin_events_user(user, ev.city_id)
    text = _admin_event_text(ev)
    await callback.message.edit_text(
        text,
        reply_markup=get_admin_event_kb(eid, can_edit, ev.is_recommended, ev.is_official),
    )
    await callback.answer()


def _admin_event_text(ev) -> str:
    """Format admin event detail text."""
    return (
        f"<b>{ev.title or TYPE_LABELS.get(ev.type.value, 'Мероприятие')}</b>\n"
        f"Тип: {TYPE_LABELS.get(ev.type.value, ev.type.value)}\n"
        f"📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {ev.point_start}\n"
        f"Описание: {ev.description or '—'}\n"
        f"Рекомендуемое: {'✅' if ev.is_recommended else '❌'}\n"
        f"Официальное: {'✅' if ev.is_official else '❌'}"
    )


@router.callback_query(F.data.startswith("admin_ev_rec_"))
async def cb_admin_ev_recommend(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_rec_", "")
    ev = await get_event_by_id(uuid.UUID(eid))
    if not ev:
        await callback.answer("Не найдено.")
        return
    can_edit = user and await can_admin_events_user(user, ev.city_id)
    if not can_edit:
        await callback.answer("Нет доступа.")
        return
    new_val = not ev.is_recommended
    await set_event_recommended(ev.id, new_val)
    await callback.answer(f"{'Рекомендовано' if new_val else 'Снято с рекомендуемых'}")
    ev = await get_event_by_id(ev.id)
    await callback.message.edit_text(
        _admin_event_text(ev),
        reply_markup=get_admin_event_kb(eid, can_edit, ev.is_recommended, ev.is_official),
    )


@router.callback_query(F.data.startswith("admin_ev_official_"))
async def cb_admin_ev_official(callback: CallbackQuery, user=None):
    """Toggle is_official flag on an event."""
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_official_", "")
    ev = await get_event_by_id(uuid.UUID(eid))
    if not ev:
        await callback.answer("Не найдено.")
        return
    can_edit = user and await can_admin_events_user(user, ev.city_id)
    if not can_edit:
        await callback.answer("Нет доступа.")
        return
    new_val = not ev.is_official
    await set_event_official(ev.id, new_val)
    await callback.answer(f"{'Официальное' if new_val else 'Убрано из официальных'}")
    ev = await get_event_by_id(ev.id)
    await callback.message.edit_text(
        _admin_event_text(ev),
        reply_markup=get_admin_event_kb(eid, can_edit, ev.is_recommended, ev.is_official),
    )


@router.callback_query(F.data.startswith("admin_ev_cancel_"))
async def cb_admin_ev_cancel(callback: CallbackQuery, user=None):
    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.")
        return
    eid = callback.data.replace("admin_ev_cancel_", "")
    ev = await get_event_by_id(uuid.UUID(eid))
    if not ev:
        await callback.answer("Не найдено.")
        return
    can_edit = user and await can_admin_events_user(user, ev.city_id)
    if not can_edit:
        await callback.answer("Нет доступа.")
        return
    ok, participant_ids = await admin_cancel_event(ev.id)
    if not ok:
        await callback.answer("Ошибка.")
        return
    msg = f"⚠️ Мероприятие «{ev.title or 'Мероприятие'}» отменено."
    from src.services.event_participant_notify import notify_event_participants_cancelled
    from src.services.broadcast import get_max_adapter

    await notify_event_participants_cancelled(
        participant_ids,
        msg,
        telegram_bot=callback.bot,
        max_adapter=get_max_adapter(),
    )
    await callback.answer("Мероприятие отменено. Участники уведомлены.")
    await callback.message.edit_text(
        "Мероприятие отменено.",
        reply_markup=get_admin_back_kb("admin_events"),
    )


@router.callback_query(F.data.startswith("admin_evreport_accept_"))
async def cb_admin_evreport_accept(callback: CallbackQuery, user=None):
    """Admin accepts event report — hides the event from public list."""
    from src import texts

    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    eid = callback.data.replace("admin_evreport_accept_", "")
    try:
        ev_uuid = uuid.UUID(eid)
    except ValueError:
        await callback.answer("Ошибка.")
        return
    ev = await get_event_by_id(ev_uuid)
    if not ev:
        await callback.answer("Мероприятие не найдено.")
        return
    if not is_sa and (not user or not await can_admin_events_user(user, ev.city_id)):
        await callback.answer("Нет доступа к мероприятиям другого города.", show_alert=True)
        return
    await set_event_hidden(ev.id, True)
    await callback.message.edit_text(texts.EVENT_REPORT_ACCEPTED)
    await callback.answer("Мероприятие скрыто.")


@router.callback_query(F.data.startswith("admin_evreport_reject_"))
async def cb_admin_evreport_reject(callback: CallbackQuery, user=None):
    """Admin rejects event report."""
    from src import texts

    is_sa = _is_superadmin(callback.from_user.id)
    is_ca = await _tg_user_can_open_admin_events_menu(user, callback.from_user.id)
    if not is_sa and not is_ca:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    eid = callback.data.replace("admin_evreport_reject_", "")
    try:
        ev = await get_event_by_id(uuid.UUID(eid))
    except ValueError:
        ev = None
    if ev and not is_sa and user and not await can_admin_events_user(user, ev.city_id):
        await callback.answer("Нет доступа.")
        return
    await callback.message.edit_text(texts.EVENT_REPORT_REJECTED)
    await callback.answer("Жалоба отклонена.")


# ——— Settings ———


@router.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    s = await get_subscription_settings()
    await callback.message.edit_text(_settings_text(s), reply_markup=get_settings_kb(s))
    await callback.answer()


def _settings_text(s) -> str:
    limit = getattr(s, "event_motorcade_limit_per_month", 2)
    ev_pr = getattr(s, "event_creation_price_kopecks", 9900)
    ra_pr = getattr(s, "raise_profile_price_kopecks", 4900)
    return (
        "💰 <b>Подписки, оплаты и лимиты</b>\n\n"
        f"Подписка: {'✅ вкл' if s.subscription_enabled else '❌ выкл'}\n"
        f"Цена месяца: {s.monthly_price_kopecks / 100:.0f} ₽ "
        f"({s.monthly_price_kopecks} коп.)\n"
        f"Цена года (365 дн.): {s.season_price_kopecks / 100:.0f} ₽ "
        f"({s.season_price_kopecks} коп.)\n"
        f"Мотопробегов/мес (с подпиской): {limit}\n\n"
        f"Платное создание мероприятий: {'✅' if s.event_creation_enabled else '❌'}\n"
        f"→ цена создания: {ev_pr / 100:.0f} ₽ ({ev_pr} коп.)\n\n"
        f"Платное поднятие анкеты: {'✅' if s.raise_profile_enabled else '❌'}\n"
        f"→ цена поднятия: {ra_pr / 100:.0f} ₽ ({ra_pr} коп.)\n\n"
        "<i>Цены меняются кнопками «Месяц», «Год», «Создание», «Поднятие» — "
        "затем отправь число <b>в копейках</b> (например 9900 = 99 ₽).</i>\n\n"
        "<i>Суперадмины и админы городов создают мероприятия без оплаты и без "
        "лимита мотопробегов.</i>"
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


@router.callback_query(F.data == "admin_set_motorcade_limit")
async def cb_admin_set_motorcade_limit(callback: CallbackQuery):
    """Show inline buttons to pick event_motorcade_limit_per_month."""
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    s = await get_subscription_settings()
    current = getattr(s, "event_motorcade_limit_per_month", 2)
    rows = [
        [
            InlineKeyboardButton(text="0", callback_data="admin_set_mcl_0"),
            InlineKeyboardButton(text="1", callback_data="admin_set_mcl_1"),
            InlineKeyboardButton(text="2", callback_data="admin_set_mcl_2"),
            InlineKeyboardButton(text="5", callback_data="admin_set_mcl_5"),
        ],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_settings")],
    ]
    await callback.message.edit_text(
        f"Сколько мотопробегов/мотособытий бесплатно в месяц (с подпиской)? Сейчас: {current}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_mcl_"))
async def cb_admin_set_motorcade_limit_val(callback: CallbackQuery):
    """Save selected event_motorcade_limit_per_month."""
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    try:
        val = int(callback.data.replace("admin_set_mcl_", ""))
        if val < 0:
            val = 0
    except ValueError:
        await callback.answer("Ошибка.")
        return
    await update_subscription_settings(event_motorcade_limit_per_month=val)
    s = await get_subscription_settings()
    await callback.message.edit_text(_settings_text(s), reply_markup=get_settings_kb(s))
    await callback.answer(f"Установлено: {val} мотопробегов/мес")


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
    s = await get_subscription_settings()
    cur = s.season_price_kopecks
    await callback.message.edit_text(
        f"Текущая цена года: <b>{cur}</b> коп. ({cur // 100} ₽).\n\n"
        "Отправь <b>новое число в копейках</b> ответом в этот чат "
        "(например <code>79900</code>)."
    )
    await callback.answer()


@router.callback_query(F.data == "admin_set_event_creation_price")
async def cb_admin_set_event_creation_price(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminSettingsStates.event_creation_price)
    s = await get_subscription_settings()
    cur = s.event_creation_price_kopecks
    await callback.message.edit_text(
        f"💳 <b>Цена создания мероприятия</b>\n\n"
        f"Сейчас: <b>{cur}</b> коп. ({cur // 100} ₽).\n\n"
        "Отправь <b>новое число в копейках</b> ответом в этот чат "
        "(например <code>9900</code> = 99 ₽). <code>0</code> — бесплатно при включённом платном создании."
    )
    await callback.answer()


@router.callback_query(F.data == "admin_set_raise_profile_price")
async def cb_admin_set_raise_profile_price(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminSettingsStates.raise_profile_price)
    s = await get_subscription_settings()
    cur = s.raise_profile_price_kopecks
    await callback.message.edit_text(
        f"⬆️ <b>Цена поднятия анкеты</b>\n\n"
        f"Сейчас: <b>{cur}</b> коп. ({cur // 100} ₽).\n\n"
        "Отправь <b>новое число в копейках</b> ответом в этот чат "
        "(например <code>4900</code> = 49 ₽). <code>0</code> — поднятие бесплатно при включённой опции."
    )
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


@router.message(AdminSettingsStates.event_creation_price, F.text)
async def admin_set_price_event_creation(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    try:
        val = int(message.text.strip())
        if val < 0 or val > 10000000:
            raise ValueError()
    except ValueError:
        await message.answer("Введи число копеек (0–10000000).")
        return
    await update_subscription_settings(event_creation_price_kopecks=val)
    s = await get_subscription_settings()
    await message.answer(_settings_text(s), reply_markup=get_settings_kb(s))
    await state.clear()


@router.message(AdminSettingsStates.raise_profile_price, F.text)
async def admin_set_price_raise_profile(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    try:
        val = int(message.text.strip())
        if val < 0 or val > 10000000:
            raise ValueError()
    except ValueError:
        await message.answer("Введи число копеек (0–10000000).")
        return
    await update_subscription_settings(raise_profile_price_kopecks=val)
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
    await callback.message.edit_text(
        _about_admin_panel_caption(text),
        reply_markup=_about_admin_panel_kb(),
        parse_mode=ParseMode.HTML,
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
        "Отправь новый <b>основной</b> текст для «О нас» (до 5000 символов). "
        "Контакты поддержки внизу настраиваются отдельно.\n\n"
        f"<pre>{escape((text or '')[:4000])}</pre>",
        reply_markup=get_admin_back_kb("admin_text_about"),
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_text_about_preview")
async def cb_admin_text_about_preview(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    from src.handlers.about import (
        build_about_reply_markup_telegram,
        get_about_display_full_text,
    )
    from src.utils.text_format import split_plain_text_chunks

    text = await get_about_display_full_text()
    kb = await build_about_reply_markup_telegram()
    chunks = split_plain_text_chunks(text, max_len=3800)
    await callback.bot.send_message(
        callback.from_user.id,
        "👁 <b>Так раздел «О нас» видят пользователи в Telegram:</b>",
        parse_mode=ParseMode.HTML,
    )
    await callback.bot.send_message(
        callback.from_user.id,
        chunks[0],
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )
    for part in chunks[1:]:
        await callback.bot.send_message(
            callback.from_user.id,
            part,
            parse_mode=ParseMode.HTML,
        )
    await callback.answer("Предпросмотр отправлен в этот чат.")


@router.callback_query(F.data == "admin_text_about_reset")
async def cb_admin_text_about_reset(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.clear()
    await set_global_text("about_us", "")
    await callback.answer("Сброшено: снова показывается текст по умолчанию.")
    text = await get_global_text("about_us")
    await callback.message.edit_text(
        _about_admin_panel_caption(text),
        reply_markup=_about_admin_panel_kb(),
        parse_mode=ParseMode.HTML,
    )


@router.message(AdminTextAboutStates.text, F.text)
async def admin_text_about_save(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()[:5000]
    await set_global_text("about_us", text)
    await state.clear()
    await message.answer(
        f"✅ Текст «О нас» сохранён ({len(text)} символов). Пустое значение = текст по умолчанию.",
        reply_markup=get_admin_back_kb("admin_panel"),
    )


@router.callback_query(F.data == "admin_support_contact")
async def cb_admin_support_contact(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
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
            _inline_payments_row(),
            [InlineKeyboardButton(text="« Назад", callback_data="admin_panel")],
        ]
    )
    await callback.message.edit_text(
        "<b>📞 Контакты поддержки</b>\n\n"
        f"Пользователям сейчас показываются:\n📧 <code>{email}</code>\n"
        f"👤 <code>@{uname}</code>\n\n"
        f"<i>В БД (пусто = взять из .env):</i>\n"
        f"email: <code>{db_mail or '—'}</code>\n"
        f"username: <code>{db_user or '—'}</code>",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_support_edit_email")
async def cb_admin_support_edit_email(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminSupportContactStates.email)
    await callback.message.edit_text(
        "Отправь email поддержки одним сообщением (например <code>info@site.ru</code>).",
        reply_markup=get_admin_back_kb("admin_support_contact"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_support_edit_username")
async def cb_admin_support_edit_username(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    await state.set_state(AdminSupportContactStates.username)
    await callback.message.edit_text(
        "Отправь username в Telegram <b>без @</b> (как в ссылке t.me/username).",
        reply_markup=get_admin_back_kb("admin_support_contact"),
    )
    await callback.answer()


@router.message(AdminSupportContactStates.email, F.text)
async def admin_support_contact_save_email(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    em = message.text.strip()[:320]
    if "@" not in em:
        await message.answer("Нужен email с символом @.")
        return
    await set_global_text(GLOBAL_TEXT_SUPPORT_EMAIL, em)
    await state.clear()
    await message.answer(
        "✅ Email поддержки сохранён.",
        reply_markup=get_admin_back_kb("admin_support_contact"),
    )


@router.message(AdminSupportContactStates.username, F.text)
async def admin_support_contact_save_username(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    un = message.text.strip().lstrip("@")[:64]
    if not un:
        await message.answer("Username не может быть пустым.")
        return
    await set_global_text(GLOBAL_TEXT_SUPPORT_USERNAME, un)
    await state.clear()
    await message.answer(
        "✅ Username Telegram сохранён.",
        reply_markup=get_admin_back_kb("admin_support_contact"),
    )


# ——— Шаблоны уведомлений ———


@router.callback_query(F.data == "admin_templates")
async def cb_admin_templates(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.services.notification_templates import TEMPLATE_KEYS

    rows = []
    for key, (default, desc) in TEMPLATE_KEYS.items():
        label = key.replace("template_", "").replace("_", " ").title()
        rows.append(
            [InlineKeyboardButton(text=f"✏ {label}", callback_data=f"admin_tpl_edit_{key}")]
        )
    rows.append(_inline_payments_row())
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    await callback.message.edit_text(
        "<b>📧 Шаблоны уведомлений</b>\n\n"
        "Выбери шаблон для редактирования. Поддерживаются плейсхолдеры: "
        "<code>{profile}</code>, <code>{period}</code> и т.д.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_tpl_edit_"))
async def cb_admin_templates_edit(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    key = callback.data.replace("admin_tpl_edit_", "")
    from src.services.notification_templates import TEMPLATE_KEYS

    if key not in TEMPLATE_KEYS:
        await callback.answer("Шаблон не найден.")
        return
    default, desc = TEMPLATE_KEYS[key]
    text = await get_global_text(key) or default
    await state.set_state(AdminTemplatesStates.text)
    await state.update_data(admin_tpl_key=key)
    await callback.message.edit_text(
        f"<b>Редактирование шаблона:</b> {key}\n\n"
        f"{desc}\n\n"
        f"Текущий текст:\n{text}\n\n"
        f"Отправь новый текст:",
        reply_markup=get_admin_back_kb("admin_templates"),
    )
    await callback.answer()


@router.message(AdminTemplatesStates.text, F.text)
async def admin_templates_save(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    key = data.get("admin_tpl_key")
    if not key:
        await state.clear()
        return
    text = message.text.strip()[:5000]
    await set_global_text(key, text)
    await state.clear()
    await message.answer(
        f"✅ Шаблон {key} сохранён.",
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
        rows.append(
            [InlineKeyboardButton(text=f"Город: {c.name}", callback_data=f"admin_bc_city_{c.id}")]
        )
    rows.append(_inline_payments_row())
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(
        "Выбери сегмент для рассылки:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_bc_") & (F.data != "admin_bc_confirm"))
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
        # str for Redis JSON (UUID is not serializable)
        seg = {"city_id": str(cid), "role": None, "with_subscription": None}
    else:
        await callback.answer()
        return
    await state.update_data(admin_bc_segment=seg)
    await state.set_state(AdminBroadcastStates.message)
    from src import texts as _texts

    await callback.message.edit_text(
        "Введи текст рассылки одним сообщением.\n\n" + _texts.BROADCAST_HTML_HINT,
    )
    await callback.answer()


@router.message(AdminBroadcastStates.message, F.text)
async def admin_broadcast_message(message: Message, state: FSMContext):
    if not _is_superadmin(message.from_user.id):
        return
    data = await state.get_data()
    seg = data.get("admin_bc_segment") or {}
    r_tg = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
        platform=UserPlatform.TELEGRAM,
    )
    r_max = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
        platform=UserPlatform.MAX,
    )
    n = len(r_tg) + len(r_max)
    text = message.text
    await state.update_data(admin_bc_text=text, admin_bc_count=n)
    await state.set_state(AdminBroadcastStates.segment)
    await message.answer(
        f"Получателей: {n} (Telegram: {len(r_tg)}, MAX: {len(r_max)}). Отправить?",
        reply_markup=get_broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "admin_bc_confirm")
async def cb_admin_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
    data = await state.get_data()
    text = data.get("admin_bc_text")
    if not text:
        await callback.answer("Нет текста.")
        return
    seg = data.get("admin_bc_segment") or {}
    r_tg = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
        platform=UserPlatform.TELEGRAM,
    )
    r_max = await get_broadcast_recipients(
        city_id=seg.get("city_id"),
        role=seg.get("role"),
        with_subscription=seg.get("with_subscription"),
        platform=UserPlatform.MAX,
    )
    logger.info(
        "Broadcast started: tg={} max={} segment={}",
        len(r_tg),
        len(r_max),
        seg,
    )
    sent, failed = 0, 0
    st, fl = await _do_broadcast(callback.bot, r_tg, text)
    sent += st
    failed += fl
    adapter = get_max_adapter()
    if adapter and r_max:
        sm, fm = await _do_max_broadcast(adapter, r_max, text)
        sent += sm
        failed += fm
    logger.info("Broadcast finished: sent={}, failed={}", sent, failed)
    await state.clear()
    await callback.message.edit_text(
        f"✅ Рассылка завершена: отправлено {sent}, ошибок {failed}",
        reply_markup=get_admin_back_kb(),
    )
    await callback.answer()
