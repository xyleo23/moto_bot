"""MotoPair service - profiles, likes, matches."""
from uuid import UUID

from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.models.like import Like, LikeBlacklist
from src.models.user import User

DISLIKE_BLACKLIST_THRESHOLD = 3


def _apply_filter_pilot(stmt, f: dict):
    """Apply filter conditions for pilot profile query."""
    from sqlalchemy import and_
    conds = []
    if f.get("gender") and f["gender"] in ("male", "female"):
        conds.append(ProfilePilot.gender == f["gender"])
    if f.get("age_max") and f["age_max"] > 0:
        conds.append(ProfilePilot.age <= f["age_max"])
    if conds:
        stmt = stmt.where(and_(*conds))
    return stmt


def _apply_filter_passenger(stmt, f: dict):
    """Apply filter conditions for passenger profile query."""
    from sqlalchemy import and_
    conds = []
    if f.get("gender") and f["gender"] in ("male", "female"):
        conds.append(ProfilePassenger.gender == f["gender"])
    if f.get("age_max") and f["age_max"] > 0:
        conds.append(ProfilePassenger.age <= f["age_max"])
    if f.get("weight_max") and f["weight_max"] > 0:
        conds.append(ProfilePassenger.weight <= f["weight_max"])
    if f.get("height_max") and f["height_max"] > 0:
        conds.append(ProfilePassenger.height <= f["height_max"])
    if conds:
        stmt = stmt.where(and_(*conds))
    return stmt


async def get_next_profile(
    viewer_user_id: UUID,
    role: str,
    offset: int = 0,
    filters: dict | None = None,
):
    """Get next profile, excluding liked/blacklisted. Optionally apply filters."""
    f = filters or {}
    session_factory = get_session_factory()
    async with session_factory() as session:
        liked_ids_sq = (
            select(Like.to_user_id)
            .where(Like.from_user_id == viewer_user_id, Like.is_like.is_(True))
            .scalar_subquery()
        )
        blacklisted_sq = (
            select(LikeBlacklist.blocked_user_id)
            .where(LikeBlacklist.user_id == viewer_user_id)
            .scalar_subquery()
        )

        if role == "pilot":
            stmt = (
                select(ProfilePilot)
                .join(User, ProfilePilot.user_id == User.id)
                .where(
                    ProfilePilot.user_id != viewer_user_id,
                    ProfilePilot.user_id.not_in(liked_ids_sq),
                    ProfilePilot.user_id.not_in(blacklisted_sq),
                    ProfilePilot.is_hidden.is_(False),
                )
                .order_by(ProfilePilot.raised_at.desc())
            )
            stmt = _apply_filter_pilot(stmt, f)
        else:
            stmt = (
                select(ProfilePassenger)
                .join(User, ProfilePassenger.user_id == User.id)
                .where(
                    ProfilePassenger.user_id != viewer_user_id,
                    ProfilePassenger.user_id.not_in(liked_ids_sq),
                    ProfilePassenger.user_id.not_in(blacklisted_sq),
                    ProfilePassenger.is_hidden.is_(False),
                )
                .order_by(ProfilePassenger.raised_at.desc())
            )
            stmt = _apply_filter_passenger(stmt, f)

        stmt = stmt.offset(offset).limit(2)
        result = await session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return None, False
        return rows[0], len(rows) > 1


async def get_user_for_profile(profile_id: UUID, role: str) -> User | None:
    """Get the User who owns the profile."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        if role == "pilot":
            stmt = (
                select(User)
                .join(ProfilePilot, ProfilePilot.user_id == User.id)
                .where(ProfilePilot.id == profile_id)
            )
        else:
            stmt = (
                select(User)
                .join(ProfilePassenger, ProfilePassenger.user_id == User.id)
                .where(ProfilePassenger.id == profile_id)
            )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def get_profile_by_user_id(user_id: UUID, role: str):
    """Get profile by user_id."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        if role == "pilot":
            result = await session.execute(
                select(ProfilePilot).where(ProfilePilot.user_id == user_id)
            )
        else:
            result = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == user_id)
            )
        return result.scalar_one_or_none()


async def process_like(from_user_id: UUID, to_user_id: UUID, is_like: bool) -> dict:
    """
    Record like or dislike.
    Returns:
        matched: bool — mutual like detected
        blacklisted: bool — dislike threshold reached, both users hidden
        target_platform_user_id: int | None — telegram id of target user
        target_user_id: UUID — internal id of target user
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.execute(
            select(Like).where(
                Like.from_user_id == from_user_id,
                Like.to_user_id == to_user_id,
            )
        )
        like_rec = existing.scalar_one_or_none()

        matched = False
        blacklisted = False

        if is_like:
            if like_rec:
                like_rec.is_like = True
            else:
                like_rec = Like(
                    from_user_id=from_user_id,
                    to_user_id=to_user_id,
                    is_like=True,
                )
                session.add(like_rec)

            # Check for mutual like
            reverse = await session.execute(
                select(Like).where(
                    Like.from_user_id == to_user_id,
                    Like.to_user_id == from_user_id,
                    Like.is_like.is_(True),
                )
            )
            if reverse.scalar_one_or_none():
                matched = True

        else:  # dislike
            if like_rec:
                like_rec.is_like = False
                like_rec.dislike_count = (like_rec.dislike_count or 0) + 1
            else:
                like_rec = Like(
                    from_user_id=from_user_id,
                    to_user_id=to_user_id,
                    is_like=False,
                    dislike_count=1,
                )
                session.add(like_rec)

            if like_rec.dislike_count >= DISLIKE_BLACKLIST_THRESHOLD:
                # Add both sides to blacklist
                for uid, bid in [(from_user_id, to_user_id), (to_user_id, from_user_id)]:
                    bl_check = await session.execute(
                        select(LikeBlacklist).where(
                            LikeBlacklist.user_id == uid,
                            LikeBlacklist.blocked_user_id == bid,
                        )
                    )
                    if not bl_check.scalar_one_or_none():
                        session.add(LikeBlacklist(user_id=uid, blocked_user_id=bid))
                blacklisted = True

        await session.commit()

        # Get target user's platform id for notification
        target_result = await session.execute(
            select(User).where(User.id == to_user_id)
        )
        target_user = target_result.scalar_one_or_none()

        return {
            "matched": matched,
            "blacklisted": blacklisted,
            "target_platform_user_id": target_user.platform_user_id if target_user else None,
            "target_user_id": to_user_id,
            "from_user_id": from_user_id,
        }


async def raise_profile(user_id: UUID, role: str) -> bool:
    """Update raised_at to now. Returns True on success."""
    from datetime import datetime
    session_factory = get_session_factory()
    async with session_factory() as session:
        if role == "pilot":
            result = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == user_id))
            profile = result.scalar_one_or_none()
        else:
            result = await session.execute(select(ProfilePassenger).where(ProfilePassenger.user_id == user_id))
            profile = result.scalar_one_or_none()
        if not profile:
            return False
        profile.raised_at = datetime.utcnow()
        await session.commit()
        return True


async def get_profile_info_text(user_id: UUID) -> tuple[str, str | None]:
    """
    Returns (profile_text, photo_file_id) for user.
    Searches both pilot and passenger profiles.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        pilot = await session.execute(
            select(ProfilePilot).where(ProfilePilot.user_id == user_id)
        )
        p = pilot.scalar_one_or_none()
        if p:
            text = (
                f"🏍 {p.name}\n"
                f"Возраст: {p.age}\n"
                f"{p.bike_brand} {p.bike_model}, {p.engine_cc} см³\n"
                f"О себе: {p.about or '—'}"
            )
            return text, p.photo_file_id

        passenger = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == user_id)
        )
        pp = passenger.scalar_one_or_none()
        if pp:
            text = (
                f"👤 {pp.name}\n"
                f"Возраст: {pp.age}, Рост: {pp.height} см, Вес: {pp.weight} кг\n"
                f"О себе: {pp.about or '—'}"
            )
            return text, pp.photo_file_id

        return "Профиль не найден", None
