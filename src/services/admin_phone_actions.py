"""Подтверждение/отклонение смены телефона — общая логика для Telegram и MAX."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.phone_change_request import PhoneChangeRequest, PhoneChangeStatus
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.models.user import User
from src.services.admin_service import is_effective_superadmin_user
from src.services.cross_platform_notify import send_text_to_all_identities

if TYPE_CHECKING:
    pass


async def phone_change_approve(
    req_id_str: str,
    admin_user: User,
    *,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
) -> tuple[bool, str]:
    """Суперадмин подтверждает заявку. Возвращает (успех, текст ответа админу)."""
    from src import texts

    if not await is_effective_superadmin_user(admin_user):
        return False, "Доступ запрещён."
    try:
        req_uuid = uuid.UUID(req_id_str)
    except ValueError:
        return False, "Некорректный ID."

    session_factory = get_session_factory()
    async with session_factory() as session:
        req_r = await session.execute(
            select(PhoneChangeRequest).where(PhoneChangeRequest.id == req_uuid)
        )
        req = req_r.scalar_one_or_none()
        if not req or req.status != PhoneChangeStatus.PENDING:
            return False, "Запрос не найден или уже обработан."
        new_phone = req.new_phone
        if not new_phone:
            return False, "Новый номер не указан в заявке."

        pilot = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == req.user_id)
        )
        p = pilot.scalar_one_or_none()
        if p:
            p.phone = new_phone[:20]
        else:
            pax = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == req.user_id)
            )
            pp = pax.scalar_one_or_none()
            if pp:
                pp.phone = new_phone[:20]

        req.status = PhoneChangeStatus.APPROVED
        req.resolved_at = datetime.utcnow()
        target_uid = req.user_id
        await session.commit()

    user_msg = texts.PHONE_CHANGE_CONFIRMED.format(new_phone=new_phone)
    try:
        await send_text_to_all_identities(
            target_uid,
            user_msg,
            telegram_bot=telegram_bot,
            max_adapter=max_adapter,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("phone_change_approve notify user: %s", e)

    return True, f"✅ Номер изменён на {new_phone}."


async def phone_change_reject(
    req_id_str: str,
    admin_user: User,
    *,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
) -> tuple[bool, str]:
    from src import texts

    if not await is_effective_superadmin_user(admin_user):
        return False, "Доступ запрещён."
    try:
        req_uuid = uuid.UUID(req_id_str)
    except ValueError:
        return False, "Некорректный ID."

    session_factory = get_session_factory()
    async with session_factory() as session:
        req_r = await session.execute(
            select(PhoneChangeRequest).where(PhoneChangeRequest.id == req_uuid)
        )
        req = req_r.scalar_one_or_none()
        if not req or req.status != PhoneChangeStatus.PENDING:
            return False, "Запрос не найден или уже обработан."

        req.status = PhoneChangeStatus.REJECTED
        req.resolved_at = datetime.utcnow()
        target_uid = req.user_id
        await session.commit()

    try:
        await send_text_to_all_identities(
            target_uid,
            texts.PHONE_CHANGE_REJECTED_USER,
            telegram_bot=telegram_bot,
            max_adapter=max_adapter,
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("phone_change_reject notify user: %s", e)

    return True, texts.PHONE_CHANGE_REJECTED
