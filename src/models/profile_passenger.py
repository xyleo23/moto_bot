"""Passenger (Двойка) profile model."""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class PreferredStyle(str, enum.Enum):
    CALM = "calm"
    DYNAMIC = "dynamic"
    MIXED = "mixed"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class ProfilePassenger(Base):
    __tablename__ = "profile_passengers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[Gender] = mapped_column(Enum(Gender), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    preferred_style: Mapped[PreferredStyle] = mapped_column(Enum(PreferredStyle), nullable=False)
    photo_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_hidden: Mapped[bool] = mapped_column(default=False)
