"""Activity log service — write and query logs for admin panel."""

from uuid import UUID
from datetime import datetime

from sqlalchemy import select, func, and_

from src.models.base import get_session_factory
from src.models.activity_log import ActivityLog, ActivityEventType
from src.models.user import User


async def log_event(
    event_type: str | ActivityEventType,
    user_id: UUID | None = None,
    data: dict | None = None,
) -> None:
    """Log an activity event. Fire-and-forget — errors are logged but don't fail caller."""
    from loguru import logger

    try:
        et = event_type.value if isinstance(event_type, ActivityEventType) else str(event_type)
        session_factory = get_session_factory()
        async with session_factory() as session:
            log = ActivityLog(
                event_type=et,
                user_id=user_id,
                data=data or {},
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        logger.warning("activity_log: failed to write event %s: %s", event_type, e)


async def get_logs(
    event_type: str | None = None,
    user_id: UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[ActivityLog, User | None]], int]:
    """
    Get activity logs with optional filters.
    Returns (list of (log, user) tuples, total count).
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ActivityLog, User).outerjoin(User, ActivityLog.user_id == User.id)
        count_stmt = select(func.count()).select_from(ActivityLog)

        conditions = []
        if event_type:
            conditions.append(ActivityLog.event_type == event_type)
        if user_id:
            conditions.append(ActivityLog.user_id == user_id)
        if date_from:
            conditions.append(ActivityLog.created_at >= date_from)
        if date_to:
            conditions.append(ActivityLog.created_at <= date_to)

        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        total = await session.scalar(count_stmt) or 0
        stmt = stmt.order_by(ActivityLog.created_at.desc()).offset(offset).limit(limit)
        r = await session.execute(stmt)
        logs = list(r.all())
        return logs, total


def get_event_type_labels() -> dict[str, str]:
    """Human-readable labels for event types."""
    return {
        ActivityEventType.SOS.value: "SOS",
        ActivityEventType.SUBSCRIPTION.value: "Подписка",
        ActivityEventType.BLOCK.value: "Блокировка",
        ActivityEventType.UNBLOCK.value: "Разблокировка",
        ActivityEventType.MUTUAL_LIKE.value: "Взаимный лайк",
        ActivityEventType.EVENT_CREATED.value: "Создание мероприятия",
    }
