"""MAX FSM registration state store — Redis-first with in-memory fallback."""

import json

from loguru import logger

# In-memory fallback: {platform_user_id: {"state": str, "data": dict}}
_memory_store: dict[int, dict] = {}

# Injected redis.asyncio.Redis client (optional)
_redis_client = None

_TTL = 3600  # seconds (1 hour)
_KEY_PREFIX = "max_reg:"


def set_redis_client(redis) -> None:
    """Inject a redis.asyncio.Redis client for state persistence."""
    global _redis_client
    _redis_client = redis


async def get_state(platform_user_id: int) -> dict | None:
    """Return ``{"state": ..., "data": {...}}`` or ``None`` if no active FSM."""
    key = f"{_KEY_PREFIX}{platform_user_id}"
    if _redis_client is not None:
        try:
            val = await _redis_client.get(key)
            if val:
                return json.loads(val)
            return None
        except Exception as exc:
            logger.warning("MAX reg get_state Redis error (falling back to memory): %s", exc)
    return _memory_store.get(platform_user_id)


async def set_state(platform_user_id: int, state: str, data: dict) -> None:
    """Persist FSM state for *platform_user_id*."""
    key = f"{_KEY_PREFIX}{platform_user_id}"
    payload = json.dumps({"state": state, "data": data}, ensure_ascii=False)
    if _redis_client is not None:
        try:
            await _redis_client.set(key, payload, ex=_TTL)
            return
        except Exception as exc:
            logger.warning("MAX reg set_state Redis error (falling back to memory): %s", exc)
    _memory_store[platform_user_id] = {"state": state, "data": data}


async def clear_state(platform_user_id: int) -> None:
    """Remove FSM state for *platform_user_id*."""
    key = f"{_KEY_PREFIX}{platform_user_id}"
    if _redis_client is not None:
        try:
            await _redis_client.delete(key)
            return
        except Exception as exc:
            logger.warning("MAX reg clear_state Redis error (falling back to memory): %s", exc)
    _memory_store.pop(platform_user_id, None)
