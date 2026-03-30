"""Platform-agnostic registration service (pilot + passenger).

Extracts DB-commit logic from src/handlers/registration.py so that
MAX (and any future platform) can reuse it without touching Telegram handlers.

Cross-platform account linking: when a user on one platform registers with a
phone number that already exists in a profile on another platform, their
user record is linked (linked_user_id) to the canonical user, and all
profile/subscription/like data is shared.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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
            # Fallback for other date formats
            return None
    return None


def registration_phone_lookup_variants(normalized: str) -> list[str]:
    """Possible stored forms for the same subscriber (E.164 + legacy 8… without +)."""
    if not normalized:
        return []
    variants = {normalized}
    d = normalized[1:] if normalized.startswith("+") else normalized
    if len(d) == 11 and d.startswith("7"):
        variants.add("8" + d[1:])
        variants.add("+8" + d[1:])
    return list(variants)


async def _find_canonical_user_by_phone(
    session, phone: str, exclude_platform: Platform
) -> "UUID | None":
    """Find the canonical user ID that owns a profile with the given phone on another platform."""
    norm = normalize_registration_phone(phone)
    variants = registration_phone_lookup_variants(norm)
    if not variants:
        return None
    # Search pilot profiles
    r = await session.execute(
        select(ProfilePilot.user_id).where(ProfilePilot.phone.in_(variants)).limit(1)
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
        select(ProfilePassenger.user_id)
        .where(ProfilePassenger.phone.in_(variants))
        .limit(1)
    )
    uid = r.scalar_one_or_none()
    if uid:
        ur = await session.execute(select(User).where(User.id == uid))
        owner = ur.scalar_one_or_none()
        if owner and owner.platform != exclude_platform:
            return owner.linked_user_id if owner.linked_user_id else owner.id

    return None


def normalize_registration_phone(raw: str) -> str:
    """E.164-style: strip formatting, optional RU trunk fix, leading +, max 20 chars (DB)."""
    s = str(raw or "").strip()
    if not s:
        return ""
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return ""
    # Russia: 8XXXXXXXXXXX (11 digits) -> 7XXXXXXXXXX
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    # Russia: 10-digit mobile starting with 9 -> assume country code 7
    if len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits
    out = "+" + digits
    return out[:20]


def mask_registration_phone_hint(phone: str) -> str:
    """Masked phone for cross-link confirmation UI."""
    p = phone.replace(" ", "")
    if len(p) <= 4:
        return "••••"
    return f"{p[:2]} •••• {p[-4:]}"


def user_role_display_ru(role: UserRole | None) -> str:
    if role is None:
        return "—"
    return {
        UserRole.PILOT: "Пилот",
        UserRole.PASSENGER: "Двойка",
        UserRole.ADMIN: "Администратор",
        UserRole.SUPERADMIN: "Администратор",
    }.get(role, str(role.value))


class MaxCrossLinkKind(str, Enum):
    """Registration: outcome of phone lookup against other platforms (TG ↔ MAX)."""

    NONE = "none"
    OFFER = "offer"
    ROLE_MISMATCH = "role_mismatch"


@dataclass(frozen=True)
class MaxCrossLinkCheck:
    kind: MaxCrossLinkKind
    canonical_user_id: UUID | None = None
    display_name: str = ""
    platform_label: str = "Telegram"
    existing_role: UserRole | None = None


async def check_cross_platform_registration_link(
    phone_raw: str,
    *,
    platform: Platform,
    platform_user_id: int,
    registering_as: UserRole,
) -> MaxCrossLinkCheck:
    """
    After the user entered a phone mid-registration: if another platform already
    has this number (same role), offer early link via linked_user_id.
    """
    phone = normalize_registration_phone(phone_raw)
    if len(phone) < 5:
        return MaxCrossLinkCheck(kind=MaxCrossLinkKind.NONE)

    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(
                User.platform_user_id == platform_user_id,
                User.platform == platform,
            )
        )
        row = r.scalar_one_or_none()
        if not row or row.linked_user_id:
            return MaxCrossLinkCheck(kind=MaxCrossLinkKind.NONE)

        canonical_uid = await _find_canonical_user_by_phone(session, phone, platform)
        if not canonical_uid:
            return MaxCrossLinkCheck(kind=MaxCrossLinkKind.NONE)

        r2 = await session.execute(select(User).where(User.id == canonical_uid))
        canon = r2.scalar_one_or_none()
        if not canon or canon.role in (UserRole.ADMIN, UserRole.SUPERADMIN):
            return MaxCrossLinkCheck(kind=MaxCrossLinkKind.NONE)

        if canon.role != registering_as:
            plab = "Telegram" if canon.platform == Platform.TELEGRAM else "MAX"
            return MaxCrossLinkCheck(
                kind=MaxCrossLinkKind.ROLE_MISMATCH,
                platform_label=plab,
                existing_role=canon.role,
            )

        display_name = ""
        pp = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == canonical_uid)
        )
        pilot = pp.scalar_one_or_none()
        if pilot:
            display_name = pilot.name or ""
        else:
            ppr = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == canonical_uid)
            )
            pax = ppr.scalar_one_or_none()
            if pax:
                display_name = pax.name or ""

        plab = "Telegram" if canon.platform == Platform.TELEGRAM else "MAX"
        return MaxCrossLinkCheck(
            kind=MaxCrossLinkKind.OFFER,
            canonical_user_id=canonical_uid,
            display_name=display_name or "—",
            platform_label=plab,
            existing_role=canon.role,
        )


async def check_max_registration_cross_link(
    phone_raw: str,
    *,
    max_platform_user_id: int,
    registering_as: UserRole,
) -> MaxCrossLinkCheck:
    """See :func:`check_cross_platform_registration_link` (MAX entry)."""
    return await check_cross_platform_registration_link(
        phone_raw,
        platform=Platform.MAX,
        platform_user_id=max_platform_user_id,
        registering_as=registering_as,
    )


async def apply_max_early_account_link(
    max_platform_user_id: int,
    canonical_user_id: UUID,
) -> str | None:
    """
    Link MAX user row to an existing canonical account before registration ends.
    Returns None on success, or an error code string.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(
                User.platform_user_id == max_platform_user_id,
                User.platform == Platform.MAX,
            )
        )
        max_u = r.scalar_one_or_none()
        if not max_u:
            return "user_not_found"
        r2 = await session.execute(select(User).where(User.id == canonical_user_id))
        canon = r2.scalar_one_or_none()
        if not canon:
            return "canonical_not_found"
        max_u.linked_user_id = canonical_user_id
        if max_u.city_id is None and canon.city_id is not None:
            max_u.city_id = canon.city_id
        max_u.role = canon.role
        await session.commit()
    return None


async def apply_telegram_early_account_link(
    telegram_platform_user_id: int,
    canonical_user_id: UUID,
) -> str | None:
    """
    Link Telegram user row to an existing canonical account before registration ends.
    Returns None on success, or an error code string.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(
                User.platform_user_id == telegram_platform_user_id,
                User.platform == Platform.TELEGRAM,
            )
        )
        tg_u = r.scalar_one_or_none()
        if not tg_u:
            return "user_not_found"
        r2 = await session.execute(select(User).where(User.id == canonical_user_id))
        canon = r2.scalar_one_or_none()
        if not canon:
            return "canonical_not_found"
        tg_u.linked_user_id = canonical_user_id
        if tg_u.city_id is None and canon.city_id is not None:
            tg_u.city_id = canon.city_id
        tg_u.role = canon.role
        await session.commit()
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
        platform,
        platform_user_id,
        list(data.keys()),
    )

    phone = normalize_registration_phone(str(data.get("phone") or ""))
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
                platform,
                platform_user_id,
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
                u.id,
                canonical_uid,
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
                # Не затирать фото при обновлении, если в data нет ключа (частичные апдейты)
                if k == "photo_file_id" and "photo_file_id" not in data:
                    continue
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
        platform,
        platform_user_id,
        list(data.keys()),
    )

    required = ("name", "phone", "age", "gender", "weight", "height", "preferred_style")
    missing = [k for k in required if not data.get(k)]
    if missing:
        logger.warning("passenger reg: missing fields %s", missing)
        return "missing_fields"

    phone_str = normalize_registration_phone(str(data.get("phone") or ""))
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
                platform,
                platform_user_id,
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
                u.id,
                canonical_uid,
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
                if k == "photo_file_id" and "photo_file_id" not in data:
                    continue
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
