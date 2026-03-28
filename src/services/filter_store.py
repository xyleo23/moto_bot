"""Store motopair filter per user+role. Uses Redis when available."""

from uuid import UUID
import json

from loguru import logger

from src.config import get_settings

_memory_store: dict[str, dict] = {}
_redis_client = None


def _key(user_id: UUID | str, role: str) -> str:
    return f"motopair_filter:{user_id}:{role}"


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            from redis.asyncio import Redis

            _redis_client = Redis.from_url(get_settings().redis_url)
        except Exception as e:
            logger.warning("filter_store: Redis init failed: %s", e)
            _redis_client = None
    return _redis_client


async def get_filter(user_id: UUID | str, role: str) -> dict:
    """Get filter. Returns {gender, age_max, weight_max, height_max}."""
    k = _key(user_id, role)
    r = _get_redis()
    if r:
        try:
            raw = await r.get(k)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug("filter_store get_filter Redis error for %s: %s", k, e)
    return _memory_store.get(k, {})


async def set_filter(user_id: UUID | str, role: str, f: dict) -> None:
    """Save filter."""
    k = _key(user_id, role)
    data = {
        "gender": f.get("gender"),
        "age_max": f.get("age_max"),
        "weight_max": f.get("weight_max"),
        "height_max": f.get("height_max"),
    }
    r = _get_redis()
    if r:
        try:
            await r.set(k, json.dumps(data), ex=86400 * 30)
            return
        except Exception as e:
            logger.debug("filter_store set_filter Redis error for %s: %s", k, e)
    _memory_store[k] = data


async def clear_filter(user_id: UUID | str, role: str) -> None:
    """Remove stored filter."""
    k = _key(user_id, role)
    r = _get_redis()
    if r:
        try:
            await r.delete(k)
        except Exception as e:
            logger.debug("filter_store clear_filter Redis error for %s: %s", k, e)
    _memory_store.pop(k, None)
