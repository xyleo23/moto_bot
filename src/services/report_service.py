"""Persist motopair profile reports and optional auto-block by threshold."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from src.models.base import get_session_factory
from src.models.report import Report
from src.models.user import User

if TYPE_CHECKING:
    from src.models.bot_settings import BotSettings


async def get_settings_from_db() -> BotSettings:
    from src.services.bot_settings_service import get_bot_settings

    return await get_bot_settings()


async def save_report(
    reporter_user_id: uuid.UUID,
    reported_user_id: uuid.UUID,
    role: str,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(
            Report(
                reporter_user_id=reporter_user_id,
                reported_user_id=reported_user_id,
                profile_role=role,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.debug(
                "save_report: duplicate reporter/reported pair skipped (%s → %s)",
                reporter_user_id,
                reported_user_id,
            )


async def get_report_count(reported_user_id: uuid.UUID) -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        q = select(func.count()).select_from(Report).where(
            Report.reported_user_id == reported_user_id
        )
        result = await session.execute(q)
        return int(result.scalar_one())


async def auto_block_user(user_id: uuid.UUID, reason: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_blocked=True, block_reason=reason)
        )
        await session.commit()


async def maybe_auto_block_after_report(
    reported_user_id: uuid.UUID,
    *,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
) -> None:
    count = await get_report_count(reported_user_id)
    settings = await get_settings_from_db()
    threshold = settings.auto_block_reports_threshold
    if threshold <= 0 or count < threshold:
        return
    reason = f"Авто-блокировка: {count} жалоб"
    await auto_block_user(reported_user_id, reason=reason)
    if telegram_bot is None:
        return
    from src.services.admin_multichannel_notify import notify_superadmins_multichannel

    html = (
        f"⛔️ <b>Авто-блокировка</b>\n"
        f"Пользователь: <code>{reported_user_id}</code>\n"
        f"{reason}"
    )
    await notify_superadmins_multichannel(
        html,
        telegram_markup=None,
        telegram_bot=telegram_bot,
        max_adapter=max_adapter,
        telegram_parse_mode="HTML",
    )
