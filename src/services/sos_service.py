"""SOS service - create alerts and broadcast."""
from datetime import datetime, timedelta

from src.models.base import get_session_factory
from src.models.sos_alert import SosAlert, SosType
from src.config import get_settings


TYPE_MAP = {
    "sos_accident": SosType.ACCIDENT,
    "sos_broken": SosType.BROKEN_DOWN,
    "sos_ran_out": SosType.RAN_OUT_OF_GAS,
    "sos_other": SosType.OTHER,
}


async def create_sos_alert(
    user_id,
    city_id,
    sos_type: str,
    lat: float,
    lon: float,
    comment: str | None,
) -> bool:
    """Create SOS alert. Returns False if cooldown active."""
    session_factory = get_session_factory()
    settings = get_settings()
    cooldown = timedelta(seconds=settings.sos_cooldown_seconds)

    async with session_factory() as session:
        from sqlalchemy import select

        last = await session.execute(
            select(SosAlert)
            .where(SosAlert.user_id == user_id)
            .order_by(SosAlert.created_at.desc())
            .limit(1)
        )
        last_alert = last.scalar_one_or_none()
        if last_alert and datetime.utcnow() - last_alert.created_at < cooldown:
            return False

        alert = SosAlert(
            user_id=user_id,
            city_id=city_id,
            type=TYPE_MAP.get(sos_type, SosType.OTHER),
            lat=lat,
            lon=lon,
            comment=comment,
        )
        session.add(alert)
        await session.commit()

    return True


async def get_city_telegram_user_ids(city_id) -> list[int]:
    """Get Telegram user IDs for SOS broadcast."""
    from src.models.user import User, Platform
    from sqlalchemy import select

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User.platform_user_id).where(
                User.city_id == city_id,
                User.platform == Platform.TELEGRAM,
                User.is_blocked.is_(False),
            )
        )
        return [r[0] for r in result.fetchall()]
