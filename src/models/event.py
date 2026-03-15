"""Event and event registration models."""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Enum, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class EventType(str, enum.Enum):
    LARGE = "large"
    MOTORCADE = "motorcade"
    RUN = "run"


class RideType(str, enum.Enum):
    COLUMN = "column"
    FREE = "free"


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    city_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cities.id"), nullable=False)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[EventType] = mapped_column(
        Enum(EventType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    point_start: Mapped[str] = mapped_column(String(500), nullable=False)
    point_end: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ride_type: Mapped[RideType | None] = mapped_column(
        Enum(RideType, values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    avg_speed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_recommended: Mapped[bool] = mapped_column(default=False)
    is_official: Mapped[bool] = mapped_column(default=False)
    is_cancelled: Mapped[bool] = mapped_column(default=False)
    is_hidden: Mapped[bool] = mapped_column(default=False)  # скрыто по жалобе
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EventRegistration(Base):
    __tablename__ = "event_registrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # pilot | passenger
    seeking_pair: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
