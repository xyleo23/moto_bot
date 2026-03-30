"""Event service."""

from uuid import UUID
from datetime import datetime, date

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from src.models.base import get_session_factory
from src.models.event import Event, EventRegistration, EventType, RideType
from src.models.event_pair_request import EventPairRequest, PairRequestStatus
from src.models.subscription import Subscription, SubscriptionSettings
from src.models.user import User
from src.models.profile_pilot import ProfilePilot
from src.models.profile_passenger import ProfilePassenger


TYPE_LABELS = {
    "large": "Масштабное",
    "motorcade": "Мотопробег",
    "run": "Прохват",
}
RIDE_LABELS = {"column": "Колонна", "free": "Свободная"}


async def get_events_list(
    city_id: UUID | None, event_type: str | None = None
) -> list[dict[str, str | int]]:
    """Get list of upcoming events with pilot/passenger counts.

    Uses correlated subqueries to avoid N+1 queries.
    Returns list of dicts with id, title, type, date, point_start, pilots, passengers.
    """
    if not city_id:
        return []
    pilots_sq = (
        select(func.count())
        .select_from(EventRegistration)
        .where(
            EventRegistration.event_id == Event.id,
            EventRegistration.role == "pilot",
        )
        .scalar_subquery()
        .correlate(Event)
    )
    passengers_sq = (
        select(func.count())
        .select_from(EventRegistration)
        .where(
            EventRegistration.event_id == Event.id,
            EventRegistration.role == "passenger",
        )
        .scalar_subquery()
        .correlate(Event)
    )
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(Event, pilots_sq.label("pilots"), passengers_sq.label("passengers"))
            .where(
                Event.city_id == city_id,
                Event.is_cancelled.is_(False),
                Event.is_hidden.is_(False),
                Event.start_at >= datetime.utcnow(),
            )
            .order_by(Event.start_at)
            .limit(30)
        )
        if event_type and event_type in ("large", "motorcade", "run"):
            stmt = stmt.where(Event.type == event_type)
        result = await session.execute(stmt)
        rows = result.all()

        out = []
        for row in rows:
            e, pilots, passengers = row
            pilots = pilots or 0
            passengers = passengers or 0
            base_title = e.title or TYPE_LABELS.get(e.type.value, e.type.value)
            badges: list[str] = []
            if getattr(e, "is_official", False):
                badges.append("офиц.")
            if getattr(e, "is_recommended", False):
                badges.append("реком.")
            title = f"{base_title} ({', '.join(badges)})" if badges else base_title
            out.append(
                {
                    "id": str(e.id),
                    "title": title,
                    "type": e.type.value,
                    "date": e.start_at.strftime("%d.%m.%Y %H:%M"),
                    "point_start": e.point_start,
                    "pilots": pilots,
                    "passengers": passengers,
                }
            )
        return out


async def count_motorcades_this_month(user_id: UUID) -> int:
    """Count motorcade events **created** in the current UTC calendar month.

    Quota «N мотопробегов в месяц» applies to creations in this month, not to the
    month of ``start_at``. Otherwise events scheduled for next month while
    ``today`` is still in the previous month were not counted and all were free.
    """
    now = datetime.utcnow()
    y, m = now.year, now.month
    start_dt = datetime(y, m, 1)
    if m == 12:
        end_dt = datetime(y + 1, 1, 1)
    else:
        end_dt = datetime(y, m + 1, 1)

    session_factory = get_session_factory()
    async with session_factory() as session:
        r = await session.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.creator_id == user_id,
                Event.type == EventType.MOTORCADE,
                Event.created_at >= start_dt,
                Event.created_at < end_dt,
                Event.is_cancelled.is_(False),
            )
        )
        return r or 0


async def event_creation_payment_required(
    user_id: UUID,
    platform_user_id: int,
    city_id: UUID,
    event_type: str,
    settings: SubscriptionSettings | None,
    *,
    apply_subscription_benefits: bool = True,
) -> tuple[bool, int | None]:
    """
    Determine if payment is required for creating an event.
    Returns (needs_payment, price_kopecks).
    - large: admin free, user always paid (not in subscription)
    - motorcade: admin free; no sub = paid; with sub = N/month free (by **created**
      month, UTC), then paid
    - run: admin free; no sub = paid; with sub = free unlimited

    If ``apply_subscription_benefits`` is False (MAX messenger), льготы подписки
    на создание не применяются — как платное создание для всех (кроме админов).

    Важно: лимит мотопробегов для подписчиков проверяется **до** раннего выхода
    «платное создание выключено», иначе квота никогда не применялась.
    """
    if not settings:
        return False, None

    from src.services.admin_service import can_create_event_free

    if await can_create_event_free(platform_user_id, city_id):
        return False, None

    price = int(settings.event_creation_price_kopecks or 0)
    payment_available = bool(settings.event_creation_enabled and price > 0)

    if event_type == "motorcade" and apply_subscription_benefits:
        has_sub = await _user_has_active_subscription(user_id)
        if has_sub:
            limit = int(getattr(settings, "event_motorcade_limit_per_month", 2) or 2)
            count = await count_motorcades_this_month(user_id)
            if limit > 0 and count < limit:
                return False, None
            if payment_available:
                return True, price
            return True, None

    if not settings.event_creation_enabled or price <= 0:
        return False, None

    if event_type == "large":
        return True, price

    if event_type == "motorcade":
        if not apply_subscription_benefits:
            return True, price
        if not await _user_has_active_subscription(user_id):
            return True, price
        return True, price

    if event_type == "run":
        if not apply_subscription_benefits:
            return True, price
        has_sub = await _user_has_active_subscription(user_id)
        return not has_sub, price if not has_sub else None

    return True, price


async def _user_has_active_subscription(user_id: UUID) -> bool:
    session_factory = get_session_factory()
    today = date.today()
    async with session_factory() as session:
        r = await session.execute(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.is_active.is_(True),
                Subscription.expires_at >= today,
            )
            .limit(1)
        )
        return r.scalar_one_or_none() is not None


async def get_event_by_id(event_id: UUID):
    """Get single event with details."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Event).where(Event.id == event_id))
        return result.scalar_one_or_none()


async def format_event_report_admin_html(ev: Event, reporter: str) -> str:
    """HTML для admins по шаблону texts.EVENT_REPORT_ADMIN_TEXT (creator + event_text)."""
    from html import escape

    from src import texts
    from src.services.admin_service import get_user_by_id

    type_val = ev.type.value if hasattr(ev.type, "value") else str(ev.type)
    ev_title_raw = ev.title or TYPE_LABELS.get(type_val, type_val)
    cu = await get_user_by_id(ev.creator_id)
    if cu and cu.platform_username:
        un = cu.platform_username.lstrip("@")
        creator = escape(f"@{un}")
    elif cu:
        creator = escape(str(cu.platform_user_id))
    else:
        creator = "—"
    lines = [
        f"📅 {ev.start_at.strftime('%d.%m.%Y %H:%M')}",
        f"Тип: {escape(TYPE_LABELS.get(type_val, type_val))}",
        f"Старт: {escape(ev.point_start)}",
    ]
    if ev.point_end:
        lines.append(f"Финиш: {escape(ev.point_end)}")
    if ev.description:
        lines.append("")
        lines.append(escape(ev.description))
    event_text = "\n".join(lines)
    return texts.EVENT_REPORT_ADMIN_TEXT.format(
        reporter=escape(reporter),
        event_title=escape(ev_title_raw),
        creator=creator,
        event_text=event_text,
    )


async def create_event(
    city_id: UUID,
    creator_id: UUID,
    event_type: str,
    title: str | None,
    start_at: datetime,
    point_start: str,
    point_end: str | None,
    ride_type: str | None,
    avg_speed: int | None,
    description: str | None,
) -> Event | None:
    """Create event."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        et = EventType(event_type) if event_type in ("large", "motorcade", "run") else EventType.RUN
        rt = RideType(ride_type) if ride_type in ("column", "free") else None
        ev = Event(
            city_id=city_id,
            creator_id=creator_id,
            type=et,
            title=title or None,
            start_at=start_at,
            point_start=point_start,
            point_end=point_end or None,
            ride_type=rt,
            avg_speed=avg_speed,
            description=description or None,
        )
        session.add(ev)
        await session.commit()
        await session.refresh(ev)

        from src.services.activity_log_service import log_event
        from src.models.activity_log import ActivityEventType

        await log_event(
            ActivityEventType.EVENT_CREATED,
            user_id=creator_id,
            data={"event_id": str(ev.id), "event_type": event_type},
        )
        return ev


async def register_for_event(event_id: UUID, user_id: UUID, role: str) -> tuple[bool, str]:
    """Register user for event. Returns (ok, error_msg)."""
    if role not in ("pilot", "passenger"):
        return False, "Некорректная роль."

    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == event_id,
                EventRegistration.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            return False, "Ты уже записан."
        reg = EventRegistration(event_id=event_id, user_id=user_id, role=role)
        session.add(reg)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False, "Ты уже записан."
        return True, ""


async def set_seeking_pair(event_id: UUID, user_id: UUID, seeking: bool) -> bool:
    """Set seeking_pair flag."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == event_id,
                EventRegistration.user_id == user_id,
            )
        )
        reg = result.scalar_one_or_none()
        if not reg:
            return False
        reg.seeking_pair = seeking
        await session.commit()
        return True


async def get_seeking_users(
    event_id: UUID, opposite_role: str, exclude_user_id: UUID | None = None
):
    """Get users seeking pair (opposite role). Exclude viewers already sent request to."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(EventRegistration, User)
            .join(User, EventRegistration.user_id == User.id)
            .where(
                EventRegistration.event_id == event_id,
                EventRegistration.role == opposite_role,
                EventRegistration.seeking_pair.is_(True),
                EventRegistration.matched_user_id.is_(None),
            )
        )
        if exclude_user_id:
            # Exclude users we already sent request to
            existing = (
                select(EventPairRequest.to_user_id)
                .where(
                    EventPairRequest.event_id == event_id,
                    EventPairRequest.from_user_id == exclude_user_id,
                )
                .scalar_subquery()
            )
            stmt = stmt.where(EventRegistration.user_id.not_in(existing))
        result = await session.execute(stmt)
        return result.all()


async def get_user_registration(event_id: UUID, user_id: UUID):
    """Get user's registration for event."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == event_id,
                EventRegistration.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


async def send_pair_request(
    event_id: UUID, from_user_id: UUID, to_user_id: UUID
) -> tuple[bool, str]:
    """Send pair request. Returns (ok, msg)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.execute(
            select(EventPairRequest).where(
                EventPairRequest.event_id == event_id,
                EventPairRequest.from_user_id == from_user_id,
                EventPairRequest.to_user_id == to_user_id,
            )
        )
        if existing.scalar_one_or_none():
            return False, "Запрос уже отправлен."
        req = EventPairRequest(
            event_id=event_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
        )
        session.add(req)
        await session.commit()
        return True, ""


async def get_pair_request(event_id: UUID, from_user_id: UUID, to_user_id: UUID):
    """Get pair request by ids."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventPairRequest).where(
                EventPairRequest.event_id == event_id,
                EventPairRequest.from_user_id == from_user_id,
                EventPairRequest.to_user_id == to_user_id,
            )
        )
        return result.scalar_one_or_none()


async def accept_pair_request(event_id: UUID, from_user_id: UUID, to_user_id: UUID) -> bool:
    """Accept pair request, set matched_user_id on both registrations."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        req = await session.execute(
            select(EventPairRequest).where(
                EventPairRequest.event_id == event_id,
                EventPairRequest.from_user_id == from_user_id,
                EventPairRequest.to_user_id == to_user_id,
            )
        )
        req = req.scalar_one_or_none()
        if not req:
            return False
        req.status = PairRequestStatus.ACCEPTED

        from_reg = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == event_id,
                EventRegistration.user_id == from_user_id,
            )
        )
        to_reg = await session.execute(
            select(EventRegistration).where(
                EventRegistration.event_id == event_id,
                EventRegistration.user_id == to_user_id,
            )
        )
        fr = from_reg.scalar_one_or_none()
        tr = to_reg.scalar_one_or_none()
        if fr:
            fr.matched_user_id = to_user_id
        if tr:
            tr.matched_user_id = from_user_id
        await session.commit()
        return True


async def reject_pair_request(event_id: UUID, from_user_id: UUID, to_user_id: UUID) -> bool:
    """Reject pair request."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventPairRequest).where(
                EventPairRequest.event_id == event_id,
                EventPairRequest.from_user_id == from_user_id,
                EventPairRequest.to_user_id == to_user_id,
            )
        )
        req = result.scalar_one_or_none()
        if not req:
            return False
        req.status = PairRequestStatus.REJECTED
        await session.commit()
        return True


async def get_creator_events(creator_id: UUID):
    """Get events created by user."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Event)
            .where(
                Event.creator_id == creator_id,
                Event.is_cancelled.is_(False),
                Event.start_at >= datetime.utcnow(),
            )
            .order_by(Event.start_at)
        )
        return result.scalars().all()


async def cancel_event(event_id: UUID, creator_id: UUID) -> tuple[bool, list[UUID]]:
    """Cancel event. Returns (ok, participant user ids — канонические UUID для рассылки)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Event).where(Event.id == event_id, Event.creator_id == creator_id)
        )
        ev = result.scalar_one_or_none()
        if not ev:
            return False, []
        ev.is_cancelled = True

        regs = await session.execute(
            select(EventRegistration.user_id).where(EventRegistration.event_id == event_id)
        )
        participant_ids = [r[0] for r in regs.all()]
        await session.commit()
        return True, participant_ids


async def update_event(
    event_id: UUID,
    creator_id: UUID,
    title: str | None = None,
    start_at: datetime | None = None,
    point_start: str | None = None,
    point_end: str | None = None,
    description: str | None = None,
) -> bool:
    """Update mutable event fields. Returns True on success."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(Event).where(
                Event.id == event_id,
                Event.creator_id == creator_id,
                Event.is_cancelled.is_(False),
            )
        )
        ev = result.scalar_one_or_none()
        if not ev:
            return False
        if title is not None:
            ev.title = title[:200] if title else None
        if start_at is not None:
            ev.start_at = start_at
        if point_start is not None:
            ev.point_start = point_start[:500]
        if point_end is not None:
            ev.point_end = point_end[:500] if point_end else None
        if description is not None:
            ev.description = description[:1000] if description else None
        await session.commit()
        return True


async def get_profile_display(user_id: UUID) -> str:
    """Short profile text for events."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        user_r = await session.execute(select(User).where(User.id == user_id))
        u = user_r.scalar_one_or_none()
        if not u:
            return "Пользователь"
        pilot = await session.execute(select(ProfilePilot).where(ProfilePilot.user_id == user_id))
        p = pilot.scalar_one_or_none()
        if p:
            return f"{p.name}, {p.age} лет, {p.bike_brand}"
        pass_r = await session.execute(
            select(ProfilePassenger).where(ProfilePassenger.user_id == user_id)
        )
        pp = pass_r.scalar_one_or_none()
        if pp:
            return f"{pp.name}, {pp.age} лет"
        return u.platform_first_name or "Пользователь"
