"""Short callback data cache for Telegram (callback_data ≤ 64 bytes)."""
import secrets
from uuid import UUID
_CACHE: dict[str, tuple[UUID, UUID]] = {}
_MAX_SIZE = 2000


def put_pair_callback(eid: UUID, user_id: UUID) -> str:
    """Store (eid, user_id) and return 8-char hex code for callback_data."""
    code = secrets.token_hex(4)
    _CACHE[code] = (eid, user_id)
    if len(_CACHE) > _MAX_SIZE:
        # Evict oldest (first) items
        for k in list(_CACHE.keys())[:_MAX_SIZE // 2]:
            _CACHE.pop(k, None)
    return code


def get_pair_callback(code: str) -> tuple[UUID, UUID] | None:
    """Look up (eid, user_id) by code. Returns None if not found."""
    return _CACHE.get(code)
