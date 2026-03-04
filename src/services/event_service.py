"""Event service."""
from uuid import UUID

from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.event import Event


async def get_events_list(city_id: UUID | None):
    """Get list of upcoming events."""
    if not city_id:
        return []
    session_factory = get_session_factory()
    async with session_factory() as session:
        from datetime import datetime
        result = await session.execute(
            select(Event)
            .where(
                Event.city_id == city_id,
                Event.is_cancelled.is_(False),
                Event.start_at >= datetime.utcnow(),
            )
            .order_by(Event.start_at)
            .limit(20)
        )
        events = result.scalars().all()
        return [
            {"id": str(e.id), "title": e.title, "type": e.type.value, "date": e.start_at.strftime("%d.%m.%Y %H:%M")}
            for e in events
        ]
