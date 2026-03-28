"""Заявки «пара на мероприятие» — уведомления TG+MAX."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.user import User, effective_user_id


async def notify_pair_request_cross_platform(
    *,
    bot,
    max_adapter,
    event_id: uuid.UUID,
    from_user_canonical_id: uuid.UUID,
    to_user_internal_id: uuid.UUID,
    from_profile_text: str,
    event_title: str | None,
) -> None:
    from src.services.cross_platform_notify import send_text_to_all_identities
    from src.keyboards.events import get_pair_request_kb
    from src.keyboards.shared import get_pair_request_max_rows

    title = (event_title or "").strip() or "Мероприятие"
    msg = (
        f"💌 Заявка на пару!\n\n{from_profile_text} хочет поехать с тобой на мероприятие «{title}»."
    )
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == to_user_internal_id))
        target = r.scalar_one_or_none()
    canon_to = effective_user_id(target) if target else to_user_internal_id
    eid_s = str(event_id)
    from_s = str(from_user_canonical_id)
    try:
        await send_text_to_all_identities(
            canon_to,
            msg,
            telegram_bot=bot,
            max_adapter=max_adapter,
            tg_reply_markup=get_pair_request_kb(eid_s, from_s),
            max_kb_rows=get_pair_request_max_rows(eid_s, from_s),
        )
    except Exception as e:
        logger.warning("notify_pair_request_cross_platform: %s", e)


async def notify_pair_accepted_cross_platform(
    *,
    bot,
    max_adapter,
    initiator_internal_user_id: uuid.UUID,
    accepter_telegram_username: str | None,
    accepter_telegram_id: int | None,
    to_profile_text: str,
) -> None:
    from src.services.cross_platform_notify import send_text_to_all_identities
    from src.keyboards.motopair import get_match_kb
    from src.keyboards.shared import get_match_max_rows

    msg_ok = f"✅ Заявка принята! {to_profile_text} едет с тобой."
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == initiator_internal_user_id))
        initiator = r.scalar_one_or_none()
    canon_from = effective_user_id(initiator) if initiator else initiator_internal_user_id
    try:
        await send_text_to_all_identities(
            canon_from,
            msg_ok,
            telegram_bot=bot,
            max_adapter=max_adapter,
            tg_reply_markup=get_match_kb(accepter_telegram_username, accepter_telegram_id),
            max_kb_rows=get_match_max_rows(accepter_telegram_username),
        )
    except Exception as e:
        logger.warning("notify_pair_accepted_cross_platform: %s", e)


async def build_max_seeking_list_rows(event_id: str, seekers: list) -> list:
    from src.platforms.base import Button
    from src.utils.callback_short import put_pair_callback
    from src.services.event_service import get_profile_display
    from src.keyboards.shared import get_main_menu_shortcut_row

    eid = uuid.UUID(event_id)
    rows: list = []
    for _reg, u in seekers[:8]:
        label = (await get_profile_display(u.id))[:40]
        code = put_pair_callback(eid, u.id)
        rows.append([Button(label, payload=f"epr_{code}")])
    rows.append([Button("« Назад", payload=f"event_detail_{event_id}")])
    rows.append(get_main_menu_shortcut_row())
    return rows


async def build_telegram_seeking_list_markup(event_id: str, seekers: list) -> InlineKeyboardMarkup:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from src.utils.callback_short import put_pair_callback
    from src.services.event_service import get_profile_display

    eid = uuid.UUID(event_id)
    rows = []
    for _reg, u in seekers[:8]:
        name = await get_profile_display(u.id)
        code = put_pair_callback(eid, u.id)
        rows.append([InlineKeyboardButton(text=name[:40], callback_data=f"epr_{code}")])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=f"event_detail_{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
