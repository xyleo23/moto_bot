"""Сохраняем MAX dialog chat_id для platform_user_id — для рассылок (SOS) POST /messages с chat_id."""

from loguru import logger

_redis = None
_memory: dict[int, str] = {}
_KEY_PREFIX = "max_peer_chat:"
_TTL = 60 * 60 * 24 * 120  # 120 дней


def set_redis_client(client) -> None:
    global _redis
    _redis = client


def _decode_redis_val(raw) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace").strip()
    return str(raw).strip()


async def remember(platform_user_id: int, chat_id: str) -> None:
    """Запомнить id диалога с пользователем (из update.message.recipient.chat_id)."""
    if not chat_id or not str(chat_id).strip():
        return
    uid = int(platform_user_id)
    key = f"{_KEY_PREFIX}{uid}"
    val = str(chat_id).strip()
    if _redis is not None:
        try:
            await _redis.set(key, val, ex=_TTL)
            return
        except Exception as e:
            logger.debug("max_peer_chat Redis set: %s", e)
    _memory[uid] = val


async def get_dialog_chat_id(platform_user_id: int) -> str | None:
    """Последний известный chat_id диалога или None."""
    uid = int(platform_user_id)
    key = f"{_KEY_PREFIX}{uid}"
    if _redis is not None:
        try:
            raw = await _redis.get(key)
            got = _decode_redis_val(raw)
            if got:
                return got
        except Exception as e:
            logger.debug("max_peer_chat Redis get: %s", e)
    v = _memory.get(uid)
    return str(v).strip() if v else None
