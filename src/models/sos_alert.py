"""SOS alert model."""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Float, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class SosType(str, enum.Enum):
    ACCIDENT = "accident"
    BROKEN_DOWN = "broken_down"
    RAN_OUT_OF_GAS = "ran_out_of_gas"
    OTHER = "other"


class SosAlert(Base):
    __tablename__ = "sos_alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    city_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cities.id"), nullable=False)
    type: Mapped[SosType] = mapped_column(Enum(SosType), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
