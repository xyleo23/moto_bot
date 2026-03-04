"""Useful contacts service."""
from uuid import UUID

from sqlalchemy import select

from src.models.base import get_session_factory
from src.models.useful_contact import UsefulContact, ContactCategory

CAT_MAP = {
    "motoshop": ContactCategory.MOTOSHOP,
    "motoservice": ContactCategory.MOTOSERVICE,
    "motoschool": ContactCategory.MOTOSCHOOL,
    "motoclubs": ContactCategory.MOTOCLUBS,
    "motoevac": ContactCategory.MOTOEVAC,
    "other": ContactCategory.OTHER,
}


async def get_contacts_by_category(city_id: UUID | None, category: str):
    if not city_id:
        return []
    cat = CAT_MAP.get(category, ContactCategory.OTHER)
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(UsefulContact).where(
                UsefulContact.city_id == city_id,
                UsefulContact.category == cat,
            )
        )
        rows = result.scalars().all()
        return [{"name": r.name, "phone": r.phone, "link": r.link, "address": r.address} for r in rows]
