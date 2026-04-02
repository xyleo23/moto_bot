"""Security-related middleware tests."""

from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis as fakeredis
import pytest
from aiogram.types import Message

from src.handlers.middleware import RateLimitMiddleware


def _message_event(tg_uid: int = 42) -> Message:
    ev = MagicMock(spec=Message)
    ev.from_user = MagicMock()
    ev.from_user.id = tg_uid
    return ev


@pytest.mark.asyncio
async def test_rate_limit_allows_normal_usage():
    redis = fakeredis.FakeRedis()
    mw = RateLimitMiddleware(redis)
    handler = AsyncMock(return_value="ok")
    event = _message_event()
    data: dict = {}
    for _ in range(29):
        await mw(handler, event, data)
    assert handler.call_count == 29


@pytest.mark.asyncio
async def test_rate_limit_blocks_flood():
    redis = fakeredis.FakeRedis()
    mw = RateLimitMiddleware(redis)
    handler = AsyncMock(return_value="ok")
    event = _message_event()
    data: dict = {}
    for _ in range(31):
        await mw(handler, event, data)
    assert handler.call_count == 30


@pytest.mark.asyncio
async def test_rate_limit_no_redis_allows_all():
    mw = RateLimitMiddleware(None)
    handler = AsyncMock(return_value="ok")
    event = _message_event()
    data: dict = {}
    for _ in range(50):
        await mw(handler, event, data)
    assert handler.call_count == 50
