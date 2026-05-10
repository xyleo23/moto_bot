"""Two-factor flow для подтверждения cross-platform линка аккаунтов.

Проблема: ручной ввод номера телефона на этапе регистрации в MAX позволяет
любому пользователю заявить чужой номер и быть связанным с чужим аккаунтом.
Защита из stage 1 закрывает только эскалацию до админа.

Решение: на подтверждение линка ВЛАДЕЛЬЦУ канонического аккаунта на его
платформу отправляется одноразовый 6-значный код. Заявитель должен ввести
этот код, чтобы линк применился. Если владелец не передаст код — линк
не применится.

API:
    set_redis_client(client) — инициализация (вызывается из main.py)
    issue_challenge(canonical_id, requestor_user_id) -> code
    verify_and_consume(canonical_id, requestor_user_id, code) -> bool

Хранение: Redis-ключ `link_chal:<canonical_id>:<requestor_id>` со значением
кода и TTL 10 минут. После успешной проверки ключ удаляется (single-use).
"""

from __future__ import annotations

import secrets
from uuid import UUID

from loguru import logger

CHALLENGE_TTL_SECONDS = 600  # 10 минут — баланс между UX и безопасностью
CHALLENGE_CODE_LENGTH = 6

_redis = None


def set_redis_client(client) -> None:
    """Инжектируется на старте бота из main.py."""
    global _redis
    _redis = client


def _key(canonical_id: UUID, requestor_id: UUID) -> str:
    return f"link_chal:{canonical_id}:{requestor_id}"


def _generate_code() -> str:
    """6-значный код. `secrets` — криптостойкий источник."""
    n = secrets.randbelow(10**CHALLENGE_CODE_LENGTH)
    return str(n).zfill(CHALLENGE_CODE_LENGTH)


async def issue_challenge(canonical_id: UUID, requestor_id: UUID) -> str:
    """Создать новый код для пары (canonical, requestor) и сохранить в Redis.

    Возвращает code. Если Redis недоступен — поднимает RuntimeError;
    линк-флоу должен в этом случае отказать пользователю.
    """
    if _redis is None:
        raise RuntimeError("Redis client is not configured for account link security")
    code = _generate_code()
    await _redis.set(_key(canonical_id, requestor_id), code, ex=CHALLENGE_TTL_SECONDS)
    logger.info(
        "account_link: issued challenge canonical={} requestor={} (TTL={}s)",
        canonical_id,
        requestor_id,
        CHALLENGE_TTL_SECONDS,
    )
    return code


async def verify_and_consume(
    canonical_id: UUID, requestor_id: UUID, code: str
) -> bool:
    """Проверить введённый код и удалить ключ (single-use).

    Возвращает True если код совпал, False во всех остальных случаях
    (Redis недоступен, ключ просрочен, код неверен).
    """
    if _redis is None:
        logger.warning("account_link: Redis unavailable during verify")
        return False
    key = _key(canonical_id, requestor_id)
    stored = await _redis.get(key)
    if stored is None:
        logger.info(
            "account_link: verify miss (expired or never issued) canonical={} requestor={}",
            canonical_id,
            requestor_id,
        )
        return False
    stored_str = stored.decode() if isinstance(stored, (bytes, bytearray)) else str(stored)
    submitted = (code or "").strip()
    # constant-time compare
    import hmac as _hmac

    if not _hmac.compare_digest(stored_str.strip(), submitted):
        logger.warning(
            "account_link: code mismatch canonical={} requestor={}",
            canonical_id,
            requestor_id,
        )
        return False
    # Single-use: invalidate immediately on success.
    await _redis.delete(key)
    logger.info(
        "account_link: code verified canonical={} requestor={}",
        canonical_id,
        requestor_id,
    )
    return True


async def revoke(canonical_id: UUID, requestor_id: UUID) -> None:
    """Отменить текущий challenge (если пользователь вышел/нажал «отмена»)."""
    if _redis is None:
        return
    await _redis.delete(_key(canonical_id, requestor_id))
