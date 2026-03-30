"""SOS service — create alerts, Redis-based rate limiting, and broadcast helpers."""

from uuid import UUID


from src.models.base import get_session_factory
from src.models.sos_alert import SosAlert, SosType
from src.config import get_settings

TYPE_MAP = {
    "sos_accident": SosType.ACCIDENT,
    "sos_broken": SosType.BROKEN_DOWN,
    "sos_ran_out": SosType.RAN_OUT_OF_GAS,
    "sos_other": SosType.OTHER,
}

# Redis key pattern: sos_cooldown:<user_id>
_SOS_COOLDOWN_KEY = "sos_cooldown:{user_id}"

# Module-level Redis client injected at startup (set_redis_client)
_redis = None


def set_redis_client(redis_client) -> None:
    """Inject the shared Redis client from main.py startup."""
    global _redis
    _redis = redis_client


def get_redis_client():
    """Return the shared Redis client (for scheduler, etc.)."""
    return _redis


def _cooldown_key(user_id: UUID) -> str:
    return _SOS_COOLDOWN_KEY.format(user_id=str(user_id))


async def check_sos_cooldown(user_id: UUID) -> int:
    """
    Check if SOS cooldown is active via Redis TTL.

    Returns:
        0  — no cooldown, SOS is allowed
        >0 — remaining seconds before next SOS is allowed
    """
    if _redis is None:
        return 0  # Redis unavailable — allow SOS
    key = _cooldown_key(user_id)
    ttl = await _redis.ttl(key)
    return max(0, ttl)


async def set_sos_cooldown(user_id: UUID) -> None:
    """Set Redis TTL key for SOS cooldown. Duration from config."""
    if _redis is None:
        return
    settings = get_settings()
    cooldown = settings.sos_cooldown_seconds
    key = _cooldown_key(user_id)
    await _redis.setex(key, cooldown, "1")


async def create_sos_alert(
    user_id: UUID,
    city_id: UUID,
    sos_type: str,
    lat: float,
    lon: float,
    comment: str | None,
) -> tuple[bool, int]:
    """
    Create SOS alert.

    Checks rate limit via Redis TTL (not PostgreSQL).
    Returns:
        (True, 0) — alert created
        (False, remaining_seconds) — cooldown active
    """
    remaining = await check_sos_cooldown(user_id)
    if remaining > 0:
        return False, remaining

    session_factory = get_session_factory()
    async with session_factory() as session:
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

    # Set cooldown AFTER successful DB write
    await set_sos_cooldown(user_id)

    from src.services.activity_log_service import log_event
    from src.models.activity_log import ActivityEventType

    await log_event(
        ActivityEventType.SOS,
        user_id=user_id,
        data={"city_id": str(city_id), "type": sos_type, "lat": lat, "lon": lon},
    )

    return True, 0


async def get_city_telegram_user_ids(city_id: UUID) -> list[int]:
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


async def get_city_max_user_ids(city_id: UUID) -> list[int]:
    """MAX platform_user_id для SOS в городе.

    Берём всех, у кого *любая* запись User с этим city_id, и добавляем все MAX-аккаунты
    их канонической связки (TG+MAX), чтобы не терять MAX, если city_id был только на TG.
    """
    from src.models.user import User, Platform
    from sqlalchemy import select
    from src.services.user import effective_user_id, get_all_platform_identities

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.city_id == city_id, User.is_blocked.is_(False))
        )
        rows = list(result.scalars().all())

    canonicals: set[UUID] = {effective_user_id(u) for u in rows}
    max_ids: set[int] = set()
    for canon in canonicals:
        for ident in await get_all_platform_identities(canon):
            if ident.platform == Platform.MAX and not ident.is_blocked:
                max_ids.add(int(ident.platform_user_id))

    return sorted(max_ids)
