"""Суперадмин: ответ автору сообщения об ошибке (Telegram + MAX)."""

from __future__ import annotations

import uuid
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src import texts
from src.keyboards.shared import get_main_menu_shortcut_row
from src.models.user import User
from src.platforms.base import Button
from src.platforms.max_adapter import MaxAdapter
from src.services.admin_service import is_effective_superadmin_user
from src.services.broadcast import get_max_adapter
from src.services.cross_platform_notify import send_text_to_all_identities

router = Router()


class AdminBugReplyStates(StatesGroup):
    waiting = State()


def parse_bug_reply_target(callback_data: str) -> uuid.UUID | None:
    prefix = "admin_bugreply_"
    if not callback_data.startswith(prefix):
        return None
    try:
        return uuid.UUID(callback_data[len(prefix) :])
    except ValueError:
        return None


async def deliver_admin_bug_reply_to_user(
    target_canonical_id: uuid.UUID,
    reply_plain: str,
    *,
    telegram_bot,
    max_adapter,
) -> None:
    body = escape((reply_plain or "").strip()[:4000])
    html = f"💬 <b>Ответ команды Motohub</b>\n\n{body}"
    await send_text_to_all_identities(
        target_canonical_id,
        html,
        telegram_bot=telegram_bot,
        max_adapter=max_adapter,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_bugreply_"))
async def cb_admin_bug_reply_start(callback: CallbackQuery, state: FSMContext, user: User | None = None):
    if not user or not await is_effective_superadmin_user(user):
        await callback.answer(texts.ADMIN_BUG_REPLY_NO_ACCESS, show_alert=True)
        return
    tid = parse_bug_reply_target(callback.data or "")
    if not tid:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    await state.set_state(AdminBugReplyStates.waiting)
    await state.update_data(bug_reply_target=str(tid))
    await callback.answer()
    await callback.message.answer(texts.ADMIN_BUG_REPLY_PROMPT, parse_mode="HTML")


@router.message(Command("cancel"), StateFilter(AdminBugReplyStates.waiting))
async def admin_bug_reply_cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(texts.ADMIN_BUG_REPLY_CANCELLED)


@router.message(AdminBugReplyStates.waiting, F.text)
async def admin_bug_reply_send(message: Message, state: FSMContext, user: User | None = None):
    if not user or not await is_effective_superadmin_user(user):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(texts.ADMIN_BUG_REPLY_EMPTY)
        return
    if raw.startswith("/"):
        await message.answer(texts.ADMIN_BUG_REPLY_EMPTY)
        return
    data = await state.get_data()
    await state.clear()
    try:
        tid = uuid.UUID(str(data.get("bug_reply_target")))
    except (ValueError, TypeError):
        await message.answer(texts.ADMIN_BUG_REPLY_SESSION_EXPIRED)
        return
    try:
        await deliver_admin_bug_reply_to_user(
            tid,
            raw,
            telegram_bot=message.bot,
            max_adapter=get_max_adapter(),
        )
    except Exception as e:
        logger.exception("admin bug reply TG deliver: %s", e)
        await message.answer("Не удалось отправить ответ. Попробуй позже.")
        return
    await message.answer(texts.ADMIN_BUG_REPLY_SENT)


# ——— MAX ————————————————————————————————————————————————————————————————


async def max_admin_bug_reply_open_fsm(
    adapter: MaxAdapter,
    chat_id: str,
    user_id: int,
    user: User,
    cb_data: str,
) -> bool:
    """Обработать нажатие «Ответить» в MAX. Возвращает True, если payload распознан."""
    if not cb_data.startswith("admin_bugreply_"):
        return False
    if not await is_effective_superadmin_user(user):
        await adapter.send_message(
            chat_id,
            texts.ADMIN_BUG_REPLY_NO_ACCESS,
            [[Button("« Меню", payload="menu_main")], get_main_menu_shortcut_row()],
        )
        return True
    tid = parse_bug_reply_target(cb_data)
    if not tid:
        await adapter.send_message(
            chat_id,
            "Некорректная кнопка.",
            [[Button("« Меню", payload="menu_main")], get_main_menu_shortcut_row()],
        )
        return True
    from src.services import max_registration_state as reg_state

    await reg_state.set_state(
        user_id,
        "bugreply:wait",
        {"target_canonical_id": str(tid)},
    )
    await adapter.send_message(
        chat_id,
        texts.ADMIN_BUG_REPLY_PROMPT,
        [
            [Button("« Отмена", payload="admin_bugreply_cancel")],
            get_main_menu_shortcut_row(),
        ],
    )
    return True


async def max_admin_bug_reply_deliver_text(
    adapter: MaxAdapter,
    chat_id: str,
    user_id: int,
    text: str,
    fsm: dict,
) -> None:
    from src.services import max_registration_state as reg_state

    d = fsm.get("data") or {}
    try:
        tid = uuid.UUID(str(d.get("target_canonical_id")))
    except (ValueError, TypeError):
        await reg_state.clear_state(user_id)
        await adapter.send_message(
            chat_id,
            texts.ADMIN_BUG_REPLY_SESSION_EXPIRED,
            [
                [Button("« Меню", payload="menu_main")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    body = (text or "").strip()
    if not body:
        await adapter.send_message(
            chat_id,
            texts.ADMIN_BUG_REPLY_EMPTY,
            [
                [Button("« Отмена", payload="admin_bugreply_cancel")],
                get_main_menu_shortcut_row(),
            ],
        )
        return
    if body.startswith("/"):
        low = body.lower()
        if low.startswith("/cancel"):
            await reg_state.clear_state(user_id)
            await adapter.send_message(
                chat_id,
                texts.ADMIN_BUG_REPLY_CANCELLED,
                [
                    [Button("« Меню", payload="menu_main")],
                    get_main_menu_shortcut_row(),
                ],
            )
        return

    await reg_state.clear_state(user_id)
    from src.max_runner import _get_tg_bot

    tg_bot = _get_tg_bot()
    max_ad = get_max_adapter()
    try:
        await deliver_admin_bug_reply_to_user(
            tid,
            body,
            telegram_bot=tg_bot,
            max_adapter=max_ad,
        )
    except Exception as e:
        logger.exception("admin bug reply MAX deliver: %s", e)
        await adapter.send_message(
            chat_id,
            "Не удалось отправить ответ. Попробуй позже.",
            [
                [Button("« Меню", payload="menu_main")],
                get_main_menu_shortcut_row(),
            ],
        )
        return

    await adapter.send_message(
        chat_id,
        texts.ADMIN_BUG_REPLY_SENT,
        [
            [Button("« Меню", payload="menu_main")],
            get_main_menu_shortcut_row(),
        ],
    )
