"""Метаданные платежей ЮKassa — единый канонический user_id."""

from __future__ import annotations

from src.models.user import User, effective_user_id


def subscription_metadata(user: User, period: str, *, platform: str | None = None) -> dict:
    meta: dict = {
        "user_id": str(effective_user_id(user)),
        "type": "subscription",
        "period": period,
    }
    if platform:
        meta["platform"] = platform
    return meta


def donate_metadata(user: User, *, platform: str | None = None) -> dict:
    m: dict = {"type": "donate", "user_id": str(effective_user_id(user))}
    if platform:
        m["platform"] = platform
    return m
