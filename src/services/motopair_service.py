"""MotoPair service - profiles, likes, matches."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.models.base import get_session_factory
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.models.like import Like, LikeBlacklist
from src.models.user import User


async def get_next_profile(viewer_user_id: UUID, role: str, offset: int = 0):
    """Get next profile to show. Returns (profile, has_more)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        if role == "pilot":
            stmt = (
                select(ProfilePilot)
                .join(User, ProfilePilot.user_id == User.id)
                .outerjoin(LikeBlacklist, (LikeBlacklist.user_id == viewer_user_id) & (LikeBlacklist.blocked_user_id == User.id))
                .where(
                    ProfilePilot.user_id != viewer_user_id,
                    LikeBlacklist.id.is_(None),
                    ProfilePilot.is_hidden.is_(False),
                )
                .order_by(ProfilePilot.raised_at.desc())
                .offset(offset)
                .limit(2)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
        else:
            stmt = (
                select(ProfilePassenger)
                .join(User, ProfilePassenger.user_id == User.id)
                .outerjoin(LikeBlacklist, (LikeBlacklist.user_id == viewer_user_id) & (LikeBlacklist.blocked_user_id == User.id))
                .where(
                    ProfilePassenger.user_id != viewer_user_id,
                    LikeBlacklist.id.is_(None),
                    ProfilePassenger.is_hidden.is_(False),
                )
                .order_by(ProfilePassenger.raised_at.desc())
                .offset(offset)
                .limit(2)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            return None, False
        return rows[0], len(rows) > 1
