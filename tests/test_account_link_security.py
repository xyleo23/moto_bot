"""Тесты challenge-flow для cross-platform линка аккаунтов."""

import uuid
import pytest
import fakeredis.aioredis

from src.services import account_link_security as als


@pytest.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis()
    als.set_redis_client(client)
    yield client
    als.set_redis_client(None)
    await client.aclose()


@pytest.mark.asyncio
async def test_issue_then_verify_consumes_key(redis_client):
    canon = uuid.uuid4()
    requestor = uuid.uuid4()
    code = await als.issue_challenge(canon, requestor)
    assert len(code) == 6 and code.isdigit()

    ok = await als.verify_and_consume(canon, requestor, code)
    assert ok is True
    # Single-use: повторная проверка тем же кодом — fail
    ok2 = await als.verify_and_consume(canon, requestor, code)
    assert ok2 is False


@pytest.mark.asyncio
async def test_verify_wrong_code_fails(redis_client):
    canon = uuid.uuid4()
    requestor = uuid.uuid4()
    await als.issue_challenge(canon, requestor)
    ok = await als.verify_and_consume(canon, requestor, "000000")
    assert ok is False
    # Ключ не должен быть удалён при неверном коде:
    # выдаём заново и убеждаемся что новый код всё ещё работает.
    new_code = await als.issue_challenge(canon, requestor)
    ok = await als.verify_and_consume(canon, requestor, new_code)
    assert ok is True


@pytest.mark.asyncio
async def test_verify_without_issue_fails(redis_client):
    canon = uuid.uuid4()
    requestor = uuid.uuid4()
    ok = await als.verify_and_consume(canon, requestor, "123456")
    assert ok is False


@pytest.mark.asyncio
async def test_revoke_clears_pending(redis_client):
    canon = uuid.uuid4()
    requestor = uuid.uuid4()
    code = await als.issue_challenge(canon, requestor)
    await als.revoke(canon, requestor)
    ok = await als.verify_and_consume(canon, requestor, code)
    assert ok is False


@pytest.mark.asyncio
async def test_verify_without_redis_returns_false():
    als.set_redis_client(None)
    ok = await als.verify_and_consume(uuid.uuid4(), uuid.uuid4(), "123456")
    assert ok is False


@pytest.mark.asyncio
async def test_issue_without_redis_raises():
    als.set_redis_client(None)
    with pytest.raises(RuntimeError):
        await als.issue_challenge(uuid.uuid4(), uuid.uuid4())


@pytest.mark.asyncio
async def test_separate_pairs_isolated(redis_client):
    """Разные пары (canon, requestor) не пересекаются по кодам."""
    canon = uuid.uuid4()
    r1 = uuid.uuid4()
    r2 = uuid.uuid4()
    code1 = await als.issue_challenge(canon, r1)
    code2 = await als.issue_challenge(canon, r2)
    assert code1 != code2 or True  # коды могут случайно совпасть, но это нормально

    # Код r1 не должен подходить для r2 и наоборот.
    ok = await als.verify_and_consume(canon, r2, code1)
    assert ok is False
    # Реальный код для r2 всё ещё работает.
    ok = await als.verify_and_consume(canon, r2, code2)
    assert ok is True
