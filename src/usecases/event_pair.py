"""Заявки «пара на мероприятие» — уведомления TG+MAX."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.user import Platform, User, effective_user_id


async def _telegram_identity_for_match_kb(
    canonical_user_id: uuid.UUID,
) -> tuple[str | None, int | None]:
    """Username + numeric id записи Telegram для кнопки «Написать»."""
    from src.services.user import get_all_platform_identities

    for u in await get_all_platform_identities(canonical_user_id):
        if u.platform == Platform.TELEGRAM:
            return u.platform_username, u.platform_user_id
    return None, None


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
    from src.services.motopair_service import get_contact_footer_html

    foot = await get_contact_footer_html(from_user_canonical_id)
    msg = (
        f"💌 Заявка на пару!\n\n{from_profile_text} хочет поехать с тобой на мероприятие «{title}»."
        + foot
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
    initiator_user_id: uuid.UUID,
    accepter_user_id: uuid.UUID,
) -> None:
    """Оба участника получают анкету и контакты (телефон + Telegram) друг друга."""
    from src.services.cross_platform_notify import send_text_to_all_identities
    from src.services.event_service import get_profile_display
    from src.services.motopair_service import get_contact_footer_html
    from src.keyboards.motopair import get_match_kb
    from src.keyboards.shared import get_match_max_rows

    session_factory = get_session_factory()
    async with session_factory() as session:
        ri = await session.execute(select(User).where(User.id == initiator_user_id))
        ra = await session.execute(select(User).where(User.id == accepter_user_id))
        init_u = ri.scalar_one_or_none()
        acc_u = ra.scalar_one_or_none()
    if not init_u or not acc_u:
        logger.warning("notify_pair_accepted: missing user row")
        return
    i_canon = effective_user_id(init_u)
    a_canon = effective_user_id(acc_u)

    text_i = await get_profile_display(i_canon)
    text_a = await get_profile_display(a_canon)
    foot_i = await get_contact_footer_html(i_canon)
    foot_a = await get_contact_footer_html(a_canon)

    un_a, id_a = await _telegram_identity_for_match_kb(a_canon)
    un_i, id_i = await _telegram_identity_for_match_kb(i_canon)

    msg_initiator = f"✅ Заявка принята!\n\n{text_a}" + foot_a
    msg_accepter = f"✅ Вы в паре на мероприятии!\n\n{text_i}" + foot_i

    try:
        await send_text_to_all_identities(
            i_canon,
            msg_initiator,
            telegram_bot=bot,
            max_adapter=max_adapter,
            tg_reply_markup=get_match_kb(un_a, id_a),
            max_kb_rows=get_match_max_rows(un_a),
        )
        await send_text_to_all_identities(
            a_canon,
            msg_accepter,
            telegram_bot=bot,
            max_adapter=max_adapter,
            tg_reply_markup=get_match_kb(un_i, id_i),
            max_kb_rows=get_match_max_rows(un_i),
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
