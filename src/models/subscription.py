"""Subscription and subscription settings models."""

import uuid
import enum
from datetime import datetime, date
from sqlalchemy import Integer, DateTime, Date, ForeignKey, String, Enum
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class SubscriptionType(str, enum.Enum):
    MONTHLY = "monthly"
    SEASON = "season"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[SubscriptionType] = mapped_column(
        Enum(SubscriptionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SubscriptionSettings(Base):
    """Global subscription settings (managed by superadmin)."""

    __tablename__ = "subscription_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    subscription_enabled: Mapped[bool] = mapped_column(default=False)
    monthly_price_kopecks: Mapped[int] = mapped_column(Integer, default=29900)
    season_price_kopecks: Mapped[int] = mapped_column(Integer, default=79900)
    event_creation_enabled: Mapped[bool] = mapped_column(default=False)
    event_creation_price_kopecks: Mapped[int] = mapped_column(Integer, default=9900)
    event_motorcade_limit_per_month: Mapped[int] = mapped_column(Integer, default=2)
    raise_profile_enabled: Mapped[bool] = mapped_column(default=True)
    raise_profile_price_kopecks: Mapped[int] = mapped_column(Integer, default=4900)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
