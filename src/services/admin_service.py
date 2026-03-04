"""Admin service."""
from sqlalchemy import select, func

from src.models.base import get_session_factory
from src.models.user import User
from src.models.sos_alert import SosAlert
from src.models.event import Event


async def get_stats() -> dict:
    session_factory = get_session_factory()
    async with session_factory() as session:
        users = await session.execute(select(func.count()).select_from(User))
        sos = await session.execute(select(func.count()).select_from(SosAlert))
        events = await session.execute(select(func.count()).select_from(Event))
        return {
            "users": users.scalar() or 0,
            "sos": sos.scalar() or 0,
            "events": events.scalar() or 0,
        }
