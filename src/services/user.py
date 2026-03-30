"""User service."""

import uuid
from sqlalchemy import select, delete, update, or_

from src.models.base import get_session_factory
from src.models.user import User, Platform, UserRole, effective_user_id
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger
from src.config import get_settings


async def update_max_user_dialog_chat_id(platform_user_id: int, dialog_chat_id: int) -> None:
    """Сохранить MAX recipient.chat_id для исходящих сообщений в личку."""
    if dialog_chat_id <= 0:
        return
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(User).where(
                User.platform == Platform.MAX,
                User.platform_user_id == platform_user_id,
            )
        )
        u = result.scalar_one_or_none()
        if u is None:
            return
        if u.max_dialog_chat_id == dialog_chat_id:
            return
        u.max_dialog_chat_id = dialog_chat_id
        await session.commit()


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


async def get_all_platform_identities(canonical_user_id: uuid.UUID) -> list[User]:
    """
    Все записи User, относящиеся к одному человеку: каноническая запись и все
    привязанные по linked_user_id (TG + MAX и т.д.). Для кросс-платформенных уведомлений.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(
                or_(
                    User.id == canonical_user_id,
                    User.linked_user_id == canonical_user_id,
                )
            )
        )
        return list(r.scalars().all())


async def sync_city_across_linked_identities(
    canonical_user_id: uuid.UUID, city_id: uuid.UUID
) -> None:
    """Прописать city_id всем записям User (TG + MAX), связанным с одним человеком."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(
            update(User)
            .where(
                or_(
                    User.id == canonical_user_id,
                    User.linked_user_id == canonical_user_id,
                )
            )
            .values(city_id=city_id)
        )
        await session.commit()


async def has_profile(user: User) -> bool:
    """Check if user has completed profile (pilot or passenger).

    Uses the effective (canonical) user ID so cross-platform linked accounts
    share the same profile lookup.
    """
    uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        if user.role == UserRole.PILOT:
            result = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == uid))
            return result.scalar_one_or_none() is not None
        else:
            result = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == uid)
            )
            return result.scalar_one_or_none() is not None


async def _load_sos_profile_name_phone(user: User) -> tuple[str, str]:
    """Имя и телефон для SOS/отбой: из анкеты, иначе имя из мессенджера."""
    uid = effective_user_id(user)
    session_factory = get_session_factory()
    async with session_factory() as session:
        name = user.platform_first_name or "Пользователь"
        phone = ""
        if user.role == UserRole.PILOT:
            result = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == uid))
            p = result.scalar_one_or_none()
            if p:
                name = p.name
                phone = p.phone
        else:
            result = await session.execute(
                select(ProfilePassenger).where(ProfilePassenger.user_id == uid)
            )
            p = result.scalar_one_or_none()
            if p:
                name = p.name
                phone = p.phone
        return name, phone


async def get_user_sos_broadcast_name(user: User) -> str:
    """Имя в тексте отбоя — то же, что в блоке «Имя: …» рассылки SOS."""
    name, _ = await _load_sos_profile_name_phone(user)
    return name


async def get_user_profile_display(user: User) -> str:
    """Get short profile string for SOS: name, username, phone."""
    name, phone = await _load_sos_profile_name_phone(user)
    uname = user.platform_username or ""
    parts = [f"Имя: {name}"]
    if uname:
        parts.append(f"@{uname}")
    if phone:
        parts.append(f"Телефон: {phone}")
    return "\n".join(parts)


async def delete_user_data(user: User) -> None:
    """Удалить все персональные данные пользователя (ФЗ-152, запрос /delete_data)."""
    from sqlalchemy import select, update
    from src.models.like import Like, LikeBlacklist
    from src.models.phone_change_request import PhoneChangeRequest
    from src.models.subscription import Subscription
    from src.models.sos_alert import SosAlert
    from src.models.activity_log import ActivityLog
    from src.models.city import CityAdmin
    from src.models.useful_contact import UsefulContact
    from src.models.event import Event, EventRegistration
    from src.models.event_pair_request import EventPairRequest
    from src.models.profile_pilot import ProfilePilot
    from src.models.profile_passenger import ProfilePassenger

    session_factory = get_session_factory()
    async with session_factory() as session:
        uid = user.id
        # 1. EventPairRequest
        await session.execute(
            delete(EventPairRequest).where(
                (EventPairRequest.from_user_id == uid) | (EventPairRequest.to_user_id == uid)
            )
        )
        # 2. EventRegistration — где user участник или matched
        await session.execute(delete(EventRegistration).where(EventRegistration.user_id == uid))
        await session.execute(
            update(EventRegistration)
            .where(EventRegistration.matched_user_id == uid)
            .values(matched_user_id=None)
        )
        # 3. Events, созданные пользователем — удаляем регистрации и заявки, затем сами события
        ev_result = await session.execute(select(Event.id).where(Event.creator_id == uid))
        event_ids = [r[0] for r in ev_result.fetchall()]
        if event_ids:
            await session.execute(
                delete(EventPairRequest).where(EventPairRequest.event_id.in_(event_ids))
            )
            await session.execute(
                delete(EventRegistration).where(EventRegistration.event_id.in_(event_ids))
            )
            await session.execute(delete(Event).where(Event.creator_id == uid))
        # 4. Like, LikeBlacklist
        await session.execute(
            delete(Like).where((Like.from_user_id == uid) | (Like.to_user_id == uid))
        )
        await session.execute(
            delete(LikeBlacklist).where(
                (LikeBlacklist.user_id == uid) | (LikeBlacklist.blocked_user_id == uid)
            )
        )
        # 5. PhoneChangeRequest, Subscription, SosAlert, ActivityLog, CityAdmin
        await session.execute(delete(PhoneChangeRequest).where(PhoneChangeRequest.user_id == uid))
        await session.execute(delete(Subscription).where(Subscription.user_id == uid))
        await session.execute(delete(SosAlert).where(SosAlert.user_id == uid))
        await session.execute(delete(ActivityLog).where(ActivityLog.user_id == uid))
        await session.execute(delete(CityAdmin).where(CityAdmin.user_id == uid))
        # 6. UsefulContact (созданные пользователем)
        await session.execute(delete(UsefulContact).where(UsefulContact.created_by == uid))
        # 7. Profile
        await session.execute(delete(ProfilePilot).where(ProfilePilot.user_id == uid))
        await session.execute(delete(ProfilePassenger).where(ProfilePassenger.user_id == uid))
        # 8. User
        await session.execute(delete(User).where(User.id == uid))
        await session.commit()
