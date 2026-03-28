"""Useful contacts model."""

import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class ContactCategory(str, enum.Enum):
    MOTOSHOP = "motoshop"
    MOTOSERVICE = "motoservice"
    MOTOSCHOOL = "motoschool"
    MOTOCLUBS = "motoclubs"
    MOTOEVAC = "motoevac"
    OTHER = "other"


class UsefulContact(Base):
    __tablename__ = "useful_contacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    city_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cities.id"), nullable=False)
    category: Mapped[ContactCategory] = mapped_column(
        Enum(ContactCategory, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
