"""User service."""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import get_session_factory
from src.models.user import User, Platform, UserRole
from src.models.city import City
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.config import get_settings


async def get_or_create_user(
    platform: str,
    platform_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
    city_id: uuid.UUID | None = None,
) -> User | None:
    """Get existing user or create new one."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        platform_enum = Platform.TELEGRAM if platform == "telegram" else Platform.MAX
        result = await session.execute(
            select(User).where(
                User.platform == platform_enum,
                User.platform_user_id == platform_user_id,
            )
        )
        user = result.scalar_one_or_none()
        if user:
            user.platform_username = username or user.platform_username
            user.platform_first_name = first_name or user.platform_first_name
            if city_id:
                user.city_id = city_id
            await session.commit()
            await session.refresh(user)
            return user

        user = User(
            platform=platform_enum,
            platform_user_id=platform_user_id,
            platform_username=username,
            platform_first_name=first_name,
            city_id=city_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def get_user_by_platform(platform: str, platform_user_id: int) -> User | None:
    """Get user by platform and platform user ID."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        platform_enum = Platform.TELEGRAM if platform == "telegram" else Platform.MAX
        result = await session.execute(
            select(User).where(
                User.platform == platform_enum,
                User.platform_user_id == platform_user_id,
            )
        )
        return result.scalar_one_or_none()


async def is_superadmin(platform_user_id: int) -> bool:
    return platform_user_id in get_settings().superadmin_ids


async def has_profile(user: User) -> bool:
    """Check if user has completed profile (pilot or passenger)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        if user.role == UserRole.PILOT:
            result = await session.execute(
                select(ProfilePilot).where(ProfilePilot.user_id == user.id)
            )
            return result.scalar_one_or_none() is not None
        else:
            result = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == user.id)
            )
            return result.scalar_one_or_none() is not None


async def get_user_profile_display(user: User) -> str:
    """Get short profile string for SOS: name, username, phone."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        uname = user.platform_username or ""
        name = user.platform_first_name or "Пользователь"
        phone = ""
        if user.role == UserRole.PILOT:
            result = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == user.id))
            p = result.scalar_one_or_none()
            if p:
                name = p.name
                phone = p.phone
        else:
            result = await session.execute(select(ProfilePassenger).where(ProfilePassenger.user_id == user.id))
            p = result.scalar_one_or_none()
            if p:
                name = p.name
                phone = p.phone

        parts = [f"Имя: {name}"]
        if uname:
            parts.append(f"@{uname}")
        if phone:
            parts.append(f"Телефон: {phone}")
        return "\n".join(parts)
