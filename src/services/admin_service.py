"""Admin service."""

import time
from uuid import UUID
from datetime import date, timedelta

from sqlalchemy import select, func, or_, and_, String

from src.models.base import get_session_factory
from src.models.user import User, UserRole, Platform, effective_user_id
from src.models.sos_alert import SosAlert
from src.models.event import Event, EventRegistration
from src.models.city import City, CityAdmin
from src.models.subscription import Subscription, SubscriptionSettings, SubscriptionType
from src.models.global_text import GlobalText
from src.config import get_settings


async def get_stats() -> dict:
    session_factory = get_session_factory()
    async with session_factory() as session:
        users = await session.scalar(select(func.count()).select_from(User)) or 0
        sos = await session.scalar(select(func.count()).select_from(SosAlert)) or 0
        events = await session.scalar(select(func.count()).select_from(Event)) or 0
        blocked = (
            await session.scalar(
                select(func.count()).select_from(User).where(User.is_blocked.is_(True))
            )
            or 0
        )
        active_subs = (
            await session.scalar(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.is_active.is_(True),
                    Subscription.expires_at >= date.today(),
                )
            )
            or 0
        )
        return {
            "users": users,
            "blocked": blocked,
            "sos": sos,
            "events": events,
            "active_subs": active_subs,
        }


async def get_users_list(
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
    city_id: UUID | None = None,
    role: str | None = None,
    blocked_only: bool = False,
) -> tuple[list[User], int]:
    """Return (users, total_count)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User)
        count_stmt = select(func.count()).select_from(User)

        conditions = []
        if blocked_only:
            conditions.append(User.is_blocked.is_(True))
        if city_id:
            conditions.append(User.city_id == city_id)
        if role and role in ("pilot", "passenger"):
            conditions.append(
                User.role == UserRole.PILOT if role == "pilot" else UserRole.PASSENGER
            )
        if search and search.strip():
            s = f"%{search.strip()}%"
            search_val = search.strip()
            conditions.append(
                or_(
                    User.platform_username.ilike(s),
                    User.platform_first_name.ilike(s),
                    func.cast(User.platform_user_id, String).like(f"%{search_val}%"),
                )
            )

        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        total = await session.scalar(count_stmt) or 0
        stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all(), total


async def block_user(user_id: UUID, reason: str | None = None) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == user_id))
        u = r.scalar_one_or_none()
        if not u:
            return False
        u.is_blocked = True
        u.block_reason = (reason or "")[:500]
        await session.commit()
    from src.services.activity_log_service import log_event
    from src.models.activity_log import ActivityEventType

    await log_event(ActivityEventType.BLOCK, user_id=user_id, data={"reason": (reason or "")[:200]})
    return True


async def unblock_user(user_id: UUID) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == user_id))
        u = r.scalar_one_or_none()
        if not u:
            return False
        u.is_blocked = False
        u.block_reason = None
        await session.commit()
    from src.services.activity_log_service import log_event
    from src.models.activity_log import ActivityEventType

    await log_event(ActivityEventType.UNBLOCK, user_id=user_id)
    return True


async def get_user_by_id(user_id: UUID) -> User | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(User).where(User.id == user_id))
        return r.scalar_one_or_none()


async def get_user_by_platform_id(platform_user_id: int) -> User | None:
    """Только Telegram — для обратной совместимости (например, коллбеки TG-админов)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(User).where(
                User.platform == Platform.TELEGRAM,
                User.platform_user_id == platform_user_id,
            )
        )
        return r.scalar_one_or_none()


async def get_user_by_platform_numeric_id_any(platform_user_id: int) -> User | None:
    """Пользователь по числовому ID на MAX или Telegram (для выдачи админа города)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        for plat in (Platform.MAX, Platform.TELEGRAM):
            r = await session.execute(
                select(User).where(
                    User.platform == plat,
                    User.platform_user_id == platform_user_id,
                ).limit(1)
            )
            u = r.scalar_one_or_none()
            if u:
                return u
    return None


async def get_cities() -> list[City]:
    """Active cities only (for user-facing selection)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(City).where(City.is_active.is_(True)).order_by(City.name))
        return list(r.scalars().all())


async def get_all_cities() -> list[City]:
    """All cities including inactive (for admin CRUD)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(City).order_by(City.name))
        return list(r.scalars().all())


async def create_city(name: str) -> tuple[City | None, str]:
    """Create city. Returns (city, error_msg)."""
    name = (name or "").strip()[:100]
    if not name:
        return None, "Название не может быть пустым"
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.execute(select(City).where(City.name.ilike(name)))
        if existing.scalar_one_or_none():
            return None, "Город с таким названием уже есть"
        city = City(name=name)
        session.add(city)
        await session.commit()
        await session.refresh(city)
        return city, ""


async def update_city(
    city_id: UUID,
    name: str | None = None,
    is_active: bool | None = None,
) -> tuple[bool, str]:
    """Update city. Returns (ok, error_msg)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(City).where(City.id == city_id))
        city = r.scalar_one_or_none()
        if not city:
            return False, "Город не найден"
        if name is not None:
            name = name.strip()[:100]
            if not name:
                return False, "Название не может быть пустым"
            existing = await session.execute(
                select(City).where(City.name.ilike(name), City.id != city_id)
            )
            if existing.scalar_one_or_none():
                return False, "Город с таким названием уже есть"
            city.name = name
        if is_active is not None:
            city.is_active = is_active
        await session.commit()
        return True, ""


async def get_city_admins(city_id: UUID) -> list[tuple[CityAdmin, User]]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(CityAdmin, User)
            .join(User, CityAdmin.user_id == User.id)
            .where(CityAdmin.city_id == city_id)
        )
        return r.all()


async def add_city_admin(city_id: UUID, user_id: UUID) -> tuple[bool, str]:
    """Returns (ok, error_msg)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        if get_settings().superadmin_ids:
            u = await session.get(User, user_id)
            if not u:
                return False, "Пользователь не найден"
            if u.platform_user_id in get_settings().superadmin_ids:
                return False, "Суперадмин уже имеет полный доступ"
        existing = await session.execute(
            select(CityAdmin).where(
                CityAdmin.city_id == city_id,
                CityAdmin.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            return False, "Уже администратор"
        ca = CityAdmin(city_id=city_id, user_id=user_id)
        session.add(ca)
        await session.commit()
        return True, ""


async def remove_city_admin(city_id: UUID, user_id: UUID) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(CityAdmin).where(
                CityAdmin.city_id == city_id,
                CityAdmin.user_id == user_id,
            )
        )
        ca = r.scalar_one_or_none()
        if not ca:
            return False
        await session.delete(ca)
        await session.commit()
        return True


async def is_superadmin(platform_user_id: int) -> bool:
    return platform_user_id in get_settings().superadmin_ids


async def is_effective_superadmin_user(user: User) -> bool:
    """Суперадмин по любой связанной записи (TG id в SUPERADMIN_IDS + сессия в MAX)."""
    from src.models.user import effective_user_id
    from src.services.user import get_all_platform_identities

    s = get_settings()
    if not s.superadmin_ids:
        return False
    canon = effective_user_id(user)
    identities = await get_all_platform_identities(canon)
    return any(i.platform_user_id in s.superadmin_ids for i in identities)


async def is_effective_city_admin_for_city(user: User) -> bool:
    """Админ города: CityAdmin привязан к любой из связанных записей User (TG/MAX)."""
    from src.models.user import effective_user_id
    from src.services.user import get_all_platform_identities

    if not user.city_id:
        return False
    canon = effective_user_id(user)
    identities = await get_all_platform_identities(canon)
    identity_ids = [u.id for u in identities]
    if not identity_ids:
        return False
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(CityAdmin.id).where(
                CityAdmin.user_id.in_(identity_ids),
                CityAdmin.city_id == user.city_id,
            ).limit(1)
        )
        return r.scalar_one_or_none() is not None


async def is_effective_city_admin_of(user: User, city_id: UUID) -> bool:
    """Есть ли у связанных идентичностей роль админа указанного города."""
    from src.services.user import get_all_platform_identities

    canon = effective_user_id(user)
    identities = await get_all_platform_identities(canon)
    identity_ids = [u.id for u in identities]
    if not identity_ids:
        return False
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(CityAdmin.id)
            .where(
                CityAdmin.user_id.in_(identity_ids),
                CityAdmin.city_id == city_id,
            )
            .limit(1)
        )
        return r.scalar_one_or_none() is not None


async def can_admin_events_user(actor: User, event_city_id: UUID) -> bool:
    """Суперадмин или админ города мероприятия (с учётом связки TG/MAX)."""
    if await is_effective_superadmin_user(actor):
        return True
    return await is_effective_city_admin_of(actor, event_city_id)


async def has_any_city_admin_role_for_linked(user: User) -> bool:
    """Есть ли у любой связанной записи роль админа хотя бы одного города."""
    from src.models.user import effective_user_id
    from src.services.user import get_all_platform_identities

    canon = effective_user_id(user)
    identities = await get_all_platform_identities(canon)
    identity_ids = [u.id for u in identities]
    if not identity_ids:
        return False
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(CityAdmin.id).where(CityAdmin.user_id.in_(identity_ids)).limit(1)
        )
        return r.scalar_one_or_none() is not None


async def max_user_should_see_admin_menu(user: User | None) -> bool:
    """MAX главное меню: кнопка админки, если права есть через TG-ID или связку аккаунтов."""
    if user is None or getattr(user, "platform_user_id", None) is None:
        return False
    if await is_effective_superadmin_user(user):
        return True
    if user.city_id and await is_effective_city_admin_for_city(user):
        return True
    if await has_any_city_admin_role_for_linked(user):
        return True
    return False


async def is_city_admin(
    platform_user_id: int, city_id: UUID | None, platform: Platform | None = None
) -> bool:
    if not city_id:
        return False
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(CityAdmin.id)
            .join(User, CityAdmin.user_id == User.id)
            .where(
                User.platform_user_id == platform_user_id,
                CityAdmin.city_id == city_id,
            )
        )
        if platform is not None:
            stmt = stmt.where(User.platform == platform)
        r = await session.execute(stmt.limit(1))
        return r.scalar_one_or_none() is not None


async def get_city_admin_city_id(platform_user_id: int) -> UUID | None:
    """Возвращает city_id, если пользователь — админ какого-либо города. Иначе None."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(CityAdmin.city_id)
            .join(User, CityAdmin.user_id == User.id)
            .where(User.platform_user_id == platform_user_id)
            .limit(1)
        )
        return r.scalar_one_or_none()


async def can_admin_events(
    platform_user_id: int, city_id: UUID | None, event_city_id: UUID
) -> bool:
    if platform_user_id in get_settings().superadmin_ids:
        return True
    if not city_id or city_id != event_city_id:
        return False
    return await is_city_admin(platform_user_id, city_id)


async def can_create_event_free(platform_user_id: int, city_id: UUID | None) -> bool:
    """Admin (суперадмин или городской админ) создаёт мероприятия бесплатно."""
    if platform_user_id in get_settings().superadmin_ids:
        return True
    if city_id and await is_city_admin(platform_user_id, city_id):
        return True
    return False


# In-memory cache for get_subscription_settings (TTL 60 seconds).
_subscription_settings_cache: tuple[SubscriptionSettings | None, float] | None = None
_SUBSCRIPTION_CACHE_TTL = 60


def _invalidate_subscription_settings_cache() -> None:
    """Clear cache after admin updates settings."""
    global _subscription_settings_cache
    _subscription_settings_cache = None


async def get_subscription_settings() -> SubscriptionSettings | None:
    global _subscription_settings_cache
    now = time.monotonic()
    if _subscription_settings_cache is not None:
        cached, ts = _subscription_settings_cache
        if now - ts < _SUBSCRIPTION_CACHE_TTL:
            return cached
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(SubscriptionSettings).limit(1))
        s = r.scalar_one_or_none()
        if not s:
            s = SubscriptionSettings()
            session.add(s)
            await session.commit()
            await session.refresh(s)
        _subscription_settings_cache = (s, now)
        return s


async def update_subscription_settings(
    subscription_enabled: bool | None = None,
    monthly_price_kopecks: int | None = None,
    season_price_kopecks: int | None = None,
    event_creation_enabled: bool | None = None,
    event_creation_price_kopecks: int | None = None,
    event_motorcade_limit_per_month: int | None = None,
    raise_profile_enabled: bool | None = None,
    raise_profile_price_kopecks: int | None = None,
) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(SubscriptionSettings).limit(1))
        s = r.scalar_one_or_none()
        if not s:
            s = SubscriptionSettings()
            session.add(s)
            await session.flush()
        if subscription_enabled is not None:
            s.subscription_enabled = subscription_enabled
        if monthly_price_kopecks is not None:
            s.monthly_price_kopecks = monthly_price_kopecks
        if season_price_kopecks is not None:
            s.season_price_kopecks = season_price_kopecks
        if event_creation_enabled is not None:
            s.event_creation_enabled = event_creation_enabled
        if event_creation_price_kopecks is not None:
            s.event_creation_price_kopecks = event_creation_price_kopecks
        if event_motorcade_limit_per_month is not None:
            s.event_motorcade_limit_per_month = max(0, event_motorcade_limit_per_month)
        if raise_profile_enabled is not None:
            s.raise_profile_enabled = raise_profile_enabled
        if raise_profile_price_kopecks is not None:
            s.raise_profile_price_kopecks = raise_profile_price_kopecks
        await session.commit()
        _invalidate_subscription_settings_cache()
        return True


async def extend_subscription(user_id: UUID, days: int) -> tuple[bool, str]:
    """Manually extend subscription. Returns (ok, msg)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.is_active.is_(True))
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        sub = r.scalar_one_or_none()
        exp = date.today() + timedelta(days=days)
        if sub:
            sub.expires_at = sub.expires_at + timedelta(days=days)
            await session.commit()
            return True, f"Подписка продлена до {sub.expires_at.strftime('%d.%m.%Y')}"
        sub = Subscription(
            user_id=user_id,
            type=SubscriptionType.MONTHLY,
            expires_at=exp,
            payment_id="admin_manual",
        )
        session.add(sub)
        await session.commit()
        return True, f"Подписка создана до {exp.strftime('%d.%m.%Y')}"


async def deactivate_subscription(user_id: UUID) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
        for sub in r.scalars().all():
            sub.is_active = False
        await session.commit()
        return True


async def get_admin_events(superadmin: bool, city_id: UUID | None, limit: int = 50) -> list[Event]:
    """All events for superadmin, city events for city admin."""

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Event).where(Event.is_cancelled.is_(False))
        if not superadmin and city_id:
            stmt = stmt.where(Event.city_id == city_id)
        stmt = stmt.order_by(Event.start_at.desc()).limit(limit)
        r = await session.execute(stmt)
        return list(r.scalars().all())


async def admin_cancel_event(event_id: UUID) -> tuple[bool, list[UUID]]:
    """Cancel event by admin. Returns (ok, participant canonical user ids)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(Event).where(Event.id == event_id))
        ev = r.scalar_one_or_none()
        if not ev:
            return False, []
        ev.is_cancelled = True
        regs = await session.execute(
            select(EventRegistration.user_id).where(EventRegistration.event_id == event_id)
        )
        participant_ids = [row[0] for row in regs.all()]
        await session.commit()
        return True, participant_ids


async def set_event_recommended(event_id: UUID, recommended: bool) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(Event).where(Event.id == event_id))
        ev = r.scalar_one_or_none()
        if not ev:
            return False
        ev.is_recommended = recommended
        await session.commit()
        return True


async def set_event_official(event_id: UUID, official: bool) -> bool:
    """Toggle is_official flag on an event."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(Event).where(Event.id == event_id))
        ev = r.scalar_one_or_none()
        if not ev:
            return False
        ev.is_official = official
        await session.commit()
        return True


async def set_event_hidden(event_id: UUID, hidden: bool) -> bool:
    """Hide/unhide event (e.g. after complaint accepted)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(Event).where(Event.id == event_id))
        ev = r.scalar_one_or_none()
        if not ev:
            return False
        ev.is_hidden = hidden
        await session.commit()
        return True


async def get_broadcast_recipients(
    city_id: UUID | str | None = None,
    role: str | None = None,
    with_subscription: bool | None = None,
    platform: Platform = Platform.TELEGRAM,
    limit: int = 10000,
) -> list[int]:
    """Get platform_user_ids for broadcast for one platform (Telegram or MAX)."""
    if city_id is not None and not isinstance(city_id, UUID):
        city_id = UUID(str(city_id))
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User.platform_user_id).where(
            User.platform == platform,
            User.is_blocked.is_(False),
        )
        if city_id:
            stmt = stmt.where(User.city_id == city_id)
        if role and role in ("pilot", "passenger"):
            stmt = stmt.where(
                User.role == (UserRole.PILOT if role == "pilot" else UserRole.PASSENGER)
            )
        if with_subscription is not None:
            sub_q = select(Subscription.user_id).where(
                Subscription.is_active.is_(True),
                Subscription.expires_at >= date.today(),
            )
            if with_subscription:
                stmt = stmt.where(User.id.in_(sub_q.scalar_subquery()))
            else:
                stmt = stmt.where(User.id.not_in(sub_q.scalar_subquery()))
        stmt = stmt.limit(limit)
        r = await session.execute(stmt)
        return [row[0] for row in r.all()]


async def get_global_text(key: str) -> str | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(GlobalText).where(GlobalText.key == key))
        g = r.scalar_one_or_none()
        return g.value if g else None


async def set_global_text(key: str, value: str) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.execute(select(GlobalText).where(GlobalText.key == key))
        g = r.scalar_one_or_none()
        if g:
            g.value = value[:10000]
        else:
            g = GlobalText(key=key, value=value[:10000])
            session.add(g)
        await session.commit()
        return True


# Ключи global_texts: непустое значение переопределяет .env (SETTINGS)
GLOBAL_TEXT_SUPPORT_EMAIL = "support_email"
GLOBAL_TEXT_SUPPORT_USERNAME = "support_username"


async def get_effective_support_email() -> str:
    """Email поддержки: из БД (global_texts), иначе из настроек окружения."""
    raw = await get_global_text(GLOBAL_TEXT_SUPPORT_EMAIL)
    if raw is not None and raw.strip():
        return raw.strip()
    return (get_settings().support_email or "").strip() or "support@example.com"


async def get_effective_support_username() -> str:
    """Username Telegram поддержки без @: БД или .env."""
    raw = await get_global_text(GLOBAL_TEXT_SUPPORT_USERNAME)
    if raw is not None and raw.strip():
        return raw.strip().lstrip("@")
    return (get_settings().support_username or "support").strip().lstrip("@") or "support"
