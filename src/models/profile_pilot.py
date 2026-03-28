"""Pilot profile model."""

import uuid
import enum
from datetime import datetime, date
from sqlalchemy import String, Integer, Date, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class DrivingStyle(str, enum.Enum):
    CALM = "calm"
    AGGRESSIVE = "aggressive"
    MIXED = "mixed"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class ProfilePilot(Base):
    __tablename__ = "profile_pilots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    bike_brand: Mapped[str] = mapped_column(String(100), nullable=False)
    bike_model: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_cc: Mapped[int] = mapped_column(Integer, nullable=False)
    driving_since: Mapped[date] = mapped_column(Date, nullable=False)
    driving_style: Mapped[DrivingStyle] = mapped_column(
        Enum(DrivingStyle, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_hidden: Mapped[bool] = mapped_column(default=False)
