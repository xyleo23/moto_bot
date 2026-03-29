"""Useful contacts service."""

from uuid import UUID

from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.useful_contact import UsefulContact, ContactCategory
from src.models.city import CityAdmin
from src.models.user import User

CAT_MAP = {
    "motoshop": ContactCategory.MOTOSHOP,
    "motoservice": ContactCategory.MOTOSERVICE,
    "motoschool": ContactCategory.MOTOSCHOOL,
    "motoclubs": ContactCategory.MOTOCLUBS,
    "motoevac": ContactCategory.MOTOEVAC,
    "other": ContactCategory.OTHER,
}
CAT_LABELS = {
    "motoshop": "МотоМагазин",
    "motoservice": "МотоСервис",
    "motoschool": "МотоШкола",
    "motoclubs": "МотоКлубы",
    "motoevac": "МотоЭвакуатор",
    "other": "Другое",
}
CONTACTS_PER_PAGE = 5


def format_useful_contact_html(c: dict) -> str:
    """Один контакт в HTML (как в Telegram-боте) — для MAX и TG."""
    parts = [f"• <b>{c['name']}</b>"]
    if c.get("description"):
        parts.append(c["description"])
    if c.get("phone"):
        parts.append(f"📞 {c['phone']}")
    if c.get("link"):
        parts.append(f"🔗 {c['link']}")
    if c.get("address"):
        parts.append(f"📍 {c['address']}")
    return "\n".join(parts)


async def can_manage_contacts_effective(session_user: User) -> bool:
    """Суперадмин (с учётом связки TG/MAX) или админ текущего города по любой связанной записи User."""
    from src.services.admin_service import is_effective_superadmin_user
    from src.models.user import effective_user_id
    from src.services.user import get_all_platform_identities

    if await is_effective_superadmin_user(session_user):
        return True
    if not session_user.city_id:
        return False
    canon = effective_user_id(session_user)
    identities = await get_all_platform_identities(canon)
    session_factory = get_session_factory()
    async with session_factory() as session:
        for iu in identities:
            r = await session.execute(
                select(CityAdmin).where(
                    CityAdmin.user_id == iu.id,
                    CityAdmin.city_id == session_user.city_id,
                ).limit(1)
            )
            if r.scalar_one_or_none() is not None:
                return True
    return False


async def can_manage_contacts(
    user_id: UUID, city_id: UUID | None, superadmin_ids: list[int]
) -> bool:
    """True if user can add/edit contacts: superadmin or city admin."""
    from src.models.user import User

    session_factory = get_session_factory()
    async with session_factory() as session:
        user_r = await session.execute(select(User).where(User.id == user_id))
        u = user_r.scalar_one_or_none()
        if not u:
            return False
        if u.platform_user_id in superadmin_ids:
            return True
        if not city_id:
            return False
        ca = await session.execute(
            select(CityAdmin).where(
                CityAdmin.city_id == city_id,
                CityAdmin.user_id == user_id,
            )
        )
        return ca.scalar_one_or_none() is not None


async def get_contacts_by_category(
    city_id: UUID | None,
    category: str,
    offset: int = 0,
    limit: int = CONTACTS_PER_PAGE,
) -> tuple[list[dict], int, bool]:
    """
    Get contacts with pagination.
    Returns (contacts, total_count, has_more).
    """
    if not city_id:
        return [], 0, False
    cat = CAT_MAP.get(category, ContactCategory.OTHER)
    session_factory = get_session_factory()
    async with session_factory() as session:
        from sqlalchemy import func

        total = (
            await session.scalar(
                select(func.count())
                .select_from(UsefulContact)
                .where(
                    UsefulContact.city_id == city_id,
                    UsefulContact.category == cat,
                )
            )
            or 0
        )
        result = await session.execute(
            select(UsefulContact)
            .where(
                UsefulContact.city_id == city_id,
                UsefulContact.category == cat,
            )
            .offset(offset)
            .limit(limit + 1)
        )
        rows = result.scalars().all()
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        return (
            [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "phone": r.phone,
                    "link": r.link,
                    "address": r.address,
                    "description": r.description,
                }
                for r in rows
            ],
            total,
            has_more,
        )


async def get_contact_by_id(contact_id: UUID) -> UsefulContact | None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(UsefulContact).where(UsefulContact.id == contact_id))
        return result.scalar_one_or_none()


async def create_contact(
    city_id: UUID,
    created_by: UUID,
    category: str,
    name: str,
    description: str | None = None,
    phone: str | None = None,
    link: str | None = None,
    address: str | None = None,
) -> UsefulContact | None:
    cat = CAT_MAP.get(category, ContactCategory.OTHER)
    session_factory = get_session_factory()
    async with session_factory() as session:
        c = UsefulContact(
            city_id=city_id,
            created_by=created_by,
            category=cat,
            name=name[:200],
            description=description[:1000] if description else None,
            phone=phone[:50] if phone else None,
            link=link[:500] if link else None,
            address=address[:500] if address else None,
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        return c


async def update_contact(
    contact_id: UUID,
    name: str | None = None,
    description: str | None = None,
    phone: str | None = None,
    link: str | None = None,
    address: str | None = None,
    category: str | None = None,
) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(UsefulContact).where(UsefulContact.id == contact_id))
        c = result.scalar_one_or_none()
        if not c:
            return False
        if name is not None:
            c.name = name[:200]
        if description is not None:
            c.description = description[:1000] if description else None
        if phone is not None:
            c.phone = phone[:50] if phone else None
        if link is not None:
            c.link = link[:500] if link else None
        if address is not None:
            c.address = address[:500] if address else None
        if category is not None and category in CAT_MAP:
            c.category = CAT_MAP[category]
        await session.commit()
        return True


async def delete_contact(contact_id: UUID) -> bool:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(UsefulContact).where(UsefulContact.id == contact_id))
        c = result.scalar_one_or_none()
        if not c:
            return False
        await session.delete(c)
        await session.commit()
        return True


async def get_admin_contacts_list(city_id: UUID | None, category: str | None = None) -> list:
    """List contacts for admin (all or by category)."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(UsefulContact).where(UsefulContact.city_id == city_id)
        if category and category in CAT_MAP:
            stmt = stmt.where(UsefulContact.category == CAT_MAP[category])
        stmt = stmt.order_by(UsefulContact.category, UsefulContact.name)
        result = await session.execute(stmt)
        return result.scalars().all()
