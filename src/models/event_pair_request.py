"""Event pair request (Ищу двойку / Ищу мотоциклиста)."""
import uuid
import enum
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class PairRequestStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EventPairRequest(Base):
    __tablename__ = "event_pair_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id"), nullable=False)
    from_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[PairRequestStatus] = mapped_column(Enum(PairRequestStatus), default=PairRequestStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
