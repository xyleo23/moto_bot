"""Tests for MAX FSM registration state store."""
import pytest
import importlib

import src.services.max_registration_state as reg_state_module


@pytest.fixture(autouse=True)
def reset_state():
    """Clear in-memory store and Redis client before each test."""
    reg_state_module._memory_store.clear()
    reg_state_module._redis_client = None
    yield
    reg_state_module._memory_store.clear()
    reg_state_module._redis_client = None


# ── In-memory fallback tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_state_returns_none_when_empty():
    result = await reg_state_module.get_state(12345)
    assert result is None


@pytest.mark.asyncio
async def test_set_and_get_state():
    await reg_state_module.set_state(42, "pilot:name", {"foo": "bar"})
    result = await reg_state_module.get_state(42)
    assert result is not None
    assert result["state"] == "pilot:name"
    assert result["data"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_set_state_updates_existing():
    await reg_state_module.set_state(7, "pilot:name", {})
    await reg_state_module.set_state(7, "pilot:phone", {"name": "Иван"})
    result = await reg_state_module.get_state(7)
    assert result["state"] == "pilot:phone"
    assert result["data"]["name"] == "Иван"


@pytest.mark.asyncio
async def test_clear_state():
    await reg_state_module.set_state(99, "passenger:age", {"name": "Маша", "phone": "+79001234567"})
    await reg_state_module.clear_state(99)
    result = await reg_state_module.get_state(99)
    assert result is None


@pytest.mark.asyncio
async def test_clear_nonexistent_state_does_not_raise():
    # Should not raise even if user has no state
    await reg_state_module.clear_state(9999999)


@pytest.mark.asyncio
async def test_multiple_users_independent():
    await reg_state_module.set_state(1, "pilot:name", {})
    await reg_state_module.set_state(2, "passenger:phone", {"name": "Петя"})
    s1 = await reg_state_module.get_state(1)
    s2 = await reg_state_module.get_state(2)
    assert s1["state"] == "pilot:name"
    assert s2["state"] == "passenger:phone"
    assert s2["data"]["name"] == "Петя"


# ── Mock Redis tests ──────────────────────────────────────────────────────────

class _MockRedis:
    """Minimal in-memory mock for redis.asyncio.Redis."""

    def __init__(self):
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex: int | None = None):
        self._store[key] = value

    async def delete(self, key: str):
        self._store.pop(key, None)


@pytest.fixture
def mock_redis():
    r = _MockRedis()
    reg_state_module.set_redis_client(r)
    yield r
    reg_state_module._redis_client = None


@pytest.mark.asyncio
async def test_redis_set_and_get(mock_redis):
    await reg_state_module.set_state(10, "pilot:age", {"name": "Алексей", "phone": "+7900"})
    result = await reg_state_module.get_state(10)
    assert result["state"] == "pilot:age"
    assert result["data"]["name"] == "Алексей"


@pytest.mark.asyncio
async def test_redis_clear(mock_redis):
    await reg_state_module.set_state(20, "pilot:gender", {"name": "X"})
    await reg_state_module.clear_state(20)
    result = await reg_state_module.get_state(20)
    assert result is None


@pytest.mark.asyncio
async def test_redis_get_returns_none_when_missing(mock_redis):
    result = await reg_state_module.get_state(55555)
    assert result is None


@pytest.mark.asyncio
async def test_redis_key_prefix(mock_redis):
    await reg_state_module.set_state(77, "passenger:name", {})
    assert "max_reg:77" in mock_redis._store


@pytest.mark.asyncio
async def test_redis_fallback_on_error():
    """When Redis raises, should fall back to memory store."""

    class _BrokenRedis:
        async def get(self, key):
            raise ConnectionError("Redis down")

        async def set(self, key, value, ex=None):
            raise ConnectionError("Redis down")

        async def delete(self, key):
            raise ConnectionError("Redis down")

    reg_state_module.set_redis_client(_BrokenRedis())
    # set_state should fall back to memory
    await reg_state_module.set_state(500, "pilot:name", {"x": 1})
    assert 500 in reg_state_module._memory_store

    # get_state should fall back to memory
    result = await reg_state_module.get_state(500)
    assert result is not None
    assert result["state"] == "pilot:name"

    # clear_state should fall back to memory
    await reg_state_module.clear_state(500)
    assert 500 not in reg_state_module._memory_store
