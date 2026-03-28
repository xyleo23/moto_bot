"""Activity log — journal of user actions for admin statistics."""

import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class ActivityEventType(str, enum.Enum):
    """Types of logged events."""

    SOS = "sos"
    SUBSCRIPTION = "subscription"
    BLOCK = "block"
    UNBLOCK = "unblock"
    MUTUAL_LIKE = "mutual_like"
    EVENT_CREATED = "event_created"


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    data: Mapped[dict | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
