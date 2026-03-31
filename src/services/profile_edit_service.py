"""Общая запись изменений анкеты (Telegram FSM / MAX FSM)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from src.config import get_settings
from src.models.base import get_session_factory
from src.models.profile_pilot import ProfilePilot, DrivingStyle
from src.models.profile_passenger import ProfilePassenger, PreferredStyle


async def load_pilot_edit_fields(canonical_user_id: UUID) -> dict | None:
    """Поля для FSM редактирования пилота. None — анкеты нет."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == canonical_user_id)
        )
        p = r.scalar_one_or_none()
        if not p:
            return None
        return {
            "name": p.name,
            "age": p.age,
            "bike_brand": p.bike_brand,
            "bike_model": p.bike_model,
            "engine_cc": p.engine_cc,
            "driving_style": p.driving_style.value if p.driving_style else "mixed",
            "photo_file_id": p.photo_file_id,
            "about": p.about,
        }


async def load_passenger_edit_fields(canonical_user_id: UUID) -> dict | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == canonical_user_id)
        )
        p = r.scalar_one_or_none()
        if not p:
            return None
        return {
            "name": p.name,
            "age": p.age,
            "weight": p.weight,
            "height": p.height,
            "preferred_style": p.preferred_style.value if p.preferred_style else "calm",
            "photo_file_id": p.photo_file_id,
            "about": p.about,
        }


async def commit_pilot_profile_edit(canonical_user_id: UUID, data: dict) -> bool:
    style_map = {
        "calm": DrivingStyle.CALM,
        "aggressive": DrivingStyle.AGGRESSIVE,
        "mixed": DrivingStyle.MIXED,
    }
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == canonical_user_id)
        )
        p = r.scalar_one_or_none()
        if not p:
            return False

        p.name = data.get("name") or p.name
        p.age = data.get("age") or p.age
        p.bike_brand = data.get("bike_brand") or p.bike_brand
        p.bike_model = data.get("bike_model") or p.bike_model
        p.engine_cc = data.get("engine_cc") or p.engine_cc
        if data.get("driving_style"):
            p.driving_style = style_map.get(str(data["driving_style"]), p.driving_style)
        if data.get("photo_file_id") is not None:
            p.photo_file_id = data["photo_file_id"]
        p.about = data.get("about", p.about)

        await session.commit()
    return True


async def commit_passenger_profile_edit(canonical_user_id: UUID, data: dict) -> bool:
    style_map = {
        "calm": PreferredStyle.CALM,
        "dynamic": PreferredStyle.DYNAMIC,
        "mixed": PreferredStyle.MIXED,
        "aggressive": PreferredStyle.DYNAMIC,
    }
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == canonical_user_id)
        )
        p = r.scalar_one_or_none()
        if not p:
            return False

        p.name = data.get("name") or p.name
        p.age = data.get("age") or p.age
        p.weight = data.get("weight") or p.weight
        p.height = data.get("height") or p.height
        if data.get("preferred_style"):
            p.preferred_style = style_map.get(str(data["preferred_style"]), p.preferred_style)
        if data.get("photo_file_id") is not None:
            p.photo_file_id = data["photo_file_id"]
        p.about = data.get("about", p.about)

        await session.commit()
    return True


def about_max_length() -> int:
    return get_settings().about_text_max_length
