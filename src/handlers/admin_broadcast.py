"""Админская рассылка — вынесена из `handlers/admin.py`.

Пакет 15 000 ₽, пункт Н (один из 2-3 автономных кусков): handlers/admin.py
был ~2000 строк. Блок рассылки (выбор сегмента, ввод текста, подтверждение,
отправка) изолирован и не пересекается с остальной админкой — идеальный
кандидат для выделения. Регистрируется как sub-router внутри admin.router.
"""

from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from loguru import logger

from src import texts as _texts
from src.keyboards.admin import (
    get_admin_back_kb,
    get_broadcast_confirm_kb,
)
from src.models.user import Platform as UserPlatform
from src.services.admin_service import (
    get_broadcast_recipients,
    get_cities,
)
from src.services.broadcast import (
    _do_broadcast,
    _do_max_broadcast,
    get_max_adapter,
)


router = Router(name="admin_broadcast")


class AdminBroadcastStates(StatesGroup):
    segment = State()
    message = State()


def _is_superadmin(user_id: int) -> bool:
    # Делегируем в admin.py, чтобы единственный источник правды по суперадминам
    # оставался там же где список настроек. Локальный импорт — анти-cycle.
    from src.handlers.admin import _is_superadmin as _impl

    return _impl(user_id)


def _inline_payments_row():
    from src.handlers.admin import _inline_payments_row as _impl

    return _impl()


@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not _is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён.")
        return
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
    await callback.message.edit_text(
        "Выбери сегмент для рассылки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
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
        seg = {"city_id": str(cid), "role": None, "with_subscription": None}
    else:
        await callback.answer()
        return
    await state.update_data(admin_bc_segment=seg)
    await state.set_state(AdminBroadcastStates.message)
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
