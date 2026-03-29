"""Один раз оплатил создание мероприятия (тип) — можно начать заново без повторной оплаты.

Кредит выдаётся при успешной оплате (webhook / кнопка «проверить») и списывается только
после успешного create_event. Отмена превью / сброс FSM кредит не сжигает.
"""

from __future__ import annotations

import uuid

from loguru import logger

from src.services.sos_service import get_redis_client

_KEY_PREFIX = "evcreate_credit:"
_TTL_SECONDS = 30 * 24 * 3600  # 30 дней


def _key(user_id: uuid.UUID, event_type: str) -> str:
    return f"{_KEY_PREFIX}{user_id}:{event_type}"


async def grant_event_creation_credit(user_id: uuid.UUID, event_type: str) -> None:
    if event_type not in ("large", "motorcade", "run"):
        return
    r = get_redis_client()
    if r is None:
        logger.warning("evcreate_credit: Redis unavailable, credit not stored uid=%s", user_id)
        return
    try:
        await r.setex(_key(user_id, event_type), _TTL_SECONDS, "1")
    except Exception as e:
        logger.warning("evcreate_credit grant failed: %s", e)


async def has_event_creation_credit(user_id: uuid.UUID, event_type: str) -> bool:
    if event_type not in ("large", "motorcade", "run"):
        return False
    r = get_redis_client()
    if r is None:
        return False
    try:
        v = await r.get(_key(user_id, event_type))
        return v is not None
    except Exception as e:
        logger.warning("evcreate_credit has failed: %s", e)
        return False


async def consume_event_creation_credit(user_id: uuid.UUID, event_type: str) -> None:
    if event_type not in ("large", "motorcade", "run"):
        return
    r = get_redis_client()
    if r is None:
        return
    try:
        await r.delete(_key(user_id, event_type))
    except Exception as e:
        logger.warning("evcreate_credit consume failed: %s", e)
