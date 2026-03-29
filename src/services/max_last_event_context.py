"""Последняя открытая карточка мероприятия в MAX (для fallback, когда клиент шлёт текст вместо callback)."""

from loguru import logger

_memory: dict[int, str] = {}
_redis_client = None
_KEY_PREFIX = "max_evtctx:"
_TTL = 7200


def set_redis_client(redis) -> None:
    global _redis_client
    _redis_client = redis


async def set_last_event_id(platform_user_id: int, event_id: str) -> None:
    """Запомнить UUID мероприятия (строка с дефисами)."""
    key = f"{_KEY_PREFIX}{platform_user_id}"
    if _redis_client is not None:
        try:
            await _redis_client.set(key, event_id, ex=_TTL)
            return
        except Exception as exc:
            logger.warning("max_evtctx set Redis error (memory): %s", exc)
    _memory[platform_user_id] = event_id


async def get_last_event_id(platform_user_id: int) -> str | None:
    key = f"{_KEY_PREFIX}{platform_user_id}"
    if _redis_client is not None:
        try:
            val = await _redis_client.get(key)
            if val:
                return val.decode() if isinstance(val, (bytes, bytearray)) else str(val)
        except Exception as exc:
            logger.warning("max_evtctx get Redis error (memory): %s", exc)
    return _memory.get(platform_user_id)


async def clear_last_event_id(platform_user_id: int) -> None:
    key = f"{_KEY_PREFIX}{platform_user_id}"
    if _redis_client is not None:
        try:
            await _redis_client.delete(key)
        except Exception as exc:
            logger.warning("max_evtctx clear Redis error: %s", exc)
    _memory.pop(platform_user_id, None)
