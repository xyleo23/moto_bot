"""Platform-agnostic registration service (pilot + passenger).

Extracts DB-commit logic from src/handlers/registration.py so that
MAX (and any future platform) can reuse it without touching Telegram handlers.

Cross-platform account linking: when a user on one platform registers with a
phone number that already exists in a profile on another platform, their
user record is linked (linked_user_id) to the canonical user, and all
profile/subscription/like data is shared.
"""
from datetime import datetime
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.user import User, Platform, UserRole
from src.models.profile_pilot import ProfilePilot, DrivingStyle, Gender
from src.models.profile_passenger import ProfilePassenger, PreferredStyle
from src.models.profile_passenger import Gender as PaxGender
from src.config import get_settings


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_driving_since(value) -> "date | None":  # noqa: F821 (avoid circular import of date)
    from datetime import date as _date
    if isinstance(value, _date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


async def _find_canonical_user_by_phone(
    session, phone: str, exclude_platform: Platform
) -> "UUID | None":
    """Find the canonical user ID that owns a profile with the given phone on another platform."""
    # Search pilot profiles
    r = await session.execute(
        select(ProfilePilot.user_id).where(ProfilePilot.phone == phone)
    )
    uid = r.scalar_one_or_none()
    if uid:
        # Verify the owning user is on a different platform
        ur = await session.execute(select(User).where(User.id == uid))
        owner = ur.scalar_one_or_none()
        if owner and owner.platform != exclude_platform:
            # Follow any existing link to root canonical user
            return owner.linked_user_id if owner.linked_user_id else owner.id

    # Search passenger profiles
    r = await session.execute(
        select(ProfilePassenger.user_id).where(ProfilePassenger.phone == phone)
    )
    uid = r.scalar_one_or_none()
    if uid:
        ur = await session.execute(select(User).where(User.id == uid))
        owner = ur.scalar_one_or_none()
        if owner and owner.platform != exclude_platform:
            return owner.linked_user_id if owner.linked_user_id else owner.id

    return None


# ── public API ────────────────────────────────────────────────────────────────

async def finish_pilot_registration(
    platform: Platform,
    platform_user_id: int,
    data: dict,
) -> str | None:
    """Save pilot profile to DB.

    Returns:
        ``None`` on success.
        ``"user_not_found"`` if the User row is missing.
        ``"invalid_phone"`` if the phone is too short.
        ``"db_error"`` on commit failure.
    """
    logger.info(
        "finish_pilot_registration: platform=%s user_id=%s keys=%s",
        platform, platform_user_id, list(data.keys()),
    )

    phone = str(data.get("phone") or "").strip()[:20]
    if not phone or len(phone) < 5:
        logger.warning("pilot reg: invalid phone %r", data.get("phone"))
        return "invalid_phone"

    gender_map = {
        "male": Gender.MALE,
        "female": Gender.FEMALE,
        "other": Gender.OTHER,
    }
    style_map = {
        "calm": DrivingStyle.CALM,
        "aggressive": DrivingStyle.AGGRESSIVE,
        "mixed": DrivingStyle.MIXED,
    }

    ds = _parse_driving_since(data.get("driving_since"))
    max_about = get_settings().about_text_max_length
    about_clean = (data.get("about") or "")[:max_about] or None

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.platform_user_id == platform_user_id,
                User.platform == platform,
            )
        )
        u = result.scalar_one_or_none()
        if not u:
            logger.warning(
                "finish_pilot_registration: User not found platform=%s id=%s",
                platform, platform_user_id,
            )
            return "user_not_found"

        # Cross-platform linking: check if another platform's user already has
        # a profile with the same phone.  If so, link this user to the canonical
        # account so data is shared between platforms.
        canonical_uid = await _find_canonical_user_by_phone(session, phone, u.platform)
        if canonical_uid and u.linked_user_id != canonical_uid:
            u.linked_user_id = canonical_uid
            logger.info(
                "finish_pilot_registration: linked user %s → canonical %s (phone match)",
                u.id, canonical_uid,
            )

        # Store profile under the canonical user's id so both platforms see the
        # same profile data.
        profile_owner_id = u.linked_user_id if u.linked_user_id else u.id

        existing = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == profile_owner_id)
        )
        profile = existing.scalar_one_or_none()

        kwargs = dict(
            name=data["name"],
            phone=phone,
            age=data["age"],
            gender=gender_map.get(str(data.get("gender", "other")), Gender.OTHER),
            bike_brand=data["bike_brand"],
            bike_model=data["bike_model"],
            engine_cc=data["engine_cc"],
            driving_since=ds,
            driving_style=style_map.get(
                str(data.get("driving_style", "mixed")), DrivingStyle.MIXED
            ),
            photo_file_id=data.get("photo_file_id"),
            about=about_clean,
        )

        if profile:
            for k, v in kwargs.items():
                setattr(profile, k, v)
        else:
            profile = ProfilePilot(user_id=profile_owner_id, **kwargs)
            session.add(profile)

        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.exception("finish_pilot_registration commit failed: %s", exc)
            return "db_error"

    return None


async def finish_passenger_registration(
    platform: Platform,
    platform_user_id: int,
    data: dict,
) -> str | None:
    """Save passenger profile to DB.

    Returns ``None`` on success or an error code string on failure.
    """
    logger.info(
        "finish_passenger_registration: platform=%s user_id=%s keys=%s",
        platform, platform_user_id, list(data.keys()),
    )

    required = ("name", "phone", "age", "gender", "weight", "height", "preferred_style")
    missing = [k for k in required if not data.get(k)]
    if missing:
        logger.warning("passenger reg: missing fields %s", missing)
        return "missing_fields"

    phone_str = str(data.get("phone") or "").strip()[:20]
    if not phone_str or len(phone_str) < 5:
        logger.warning("passenger reg: invalid phone %r", data.get("phone"))
        return "invalid_phone"

    gender_map = {
        "male": PaxGender.MALE,
        "female": PaxGender.FEMALE,
        "other": PaxGender.OTHER,
    }
    style_map = {
        "calm": PreferredStyle.CALM,
        "dynamic": PreferredStyle.DYNAMIC,
        "mixed": PreferredStyle.MIXED,
    }

    max_about = get_settings().about_text_max_length
    about_clean = (data.get("about") or "")[:max_about] or None

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.platform_user_id == platform_user_id,
                User.platform == platform,
            )
        )
        u = result.scalar_one_or_none()
        if not u:
            logger.warning(
                "finish_passenger_registration: User not found platform=%s id=%s",
                platform, platform_user_id,
            )
            return "user_not_found"

        u.role = UserRole.PASSENGER

        # Cross-platform linking: check if another platform's user already has
        # a profile with the same phone.
        canonical_uid = await _find_canonical_user_by_phone(session, phone_str, u.platform)
        if canonical_uid and u.linked_user_id != canonical_uid:
            u.linked_user_id = canonical_uid
            logger.info(
                "finish_passenger_registration: linked user %s → canonical %s (phone match)",
                u.id, canonical_uid,
            )

        profile_owner_id = u.linked_user_id if u.linked_user_id else u.id

        existing = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == profile_owner_id)
        )
        profile = existing.scalar_one_or_none()

        kwargs = dict(
            name=data["name"],
            phone=phone_str,
            age=data["age"],
            gender=gender_map.get(str(data.get("gender", "other")), PaxGender.OTHER),
            weight=data["weight"],
            height=data["height"],
            preferred_style=style_map.get(
                str(data.get("preferred_style", "mixed")), PreferredStyle.MIXED
            ),
            photo_file_id=data.get("photo_file_id"),
            about=about_clean,
        )

        if profile:
            for k, v in kwargs.items():
                setattr(profile, k, v)
        else:
            profile = ProfilePassenger(user_id=profile_owner_id, **kwargs)
            session.add(profile)

        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.exception("finish_passenger_registration commit failed: %s", exc)
            return "db_error"

    return None
