"""ProcessedPayment — idempotency log for YooKassa webhook."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class ProcessedPayment(Base):
    __tablename__ = "processed_payments"

    payment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
