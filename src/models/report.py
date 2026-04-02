"""User profile reports (motopair)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reported_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    profile_role: Mapped[str] = mapped_column(String(20))  # "pilot" / "passenger"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("reporter_user_id", "reported_user_id", name="uq_report_pair"),
    )
