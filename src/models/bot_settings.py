"""Bot settings model — configurable parameters managed by superadmin."""

import uuid
from datetime import datetime
from sqlalchemy import Integer, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class BotSettings(Base):
    """
    Single-row table for runtime-configurable bot parameters.
    Superadmin can change these through the admin panel without redeploying.
    """

    __tablename__ = "bot_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)

    # Subscription feature flags
    subscription_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_price_month: Mapped[int] = mapped_column(Integer, default=29900)
    subscription_price_season: Mapped[int] = mapped_column(Integer, default=79900)

    # Paid event creation
    event_creation_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    event_creation_price: Mapped[int] = mapped_column(Integer, default=9900)

    # Paid profile raise
    profile_raise_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_raise_price: Mapped[int] = mapped_column(Integer, default=4900)

    # SOS rate limit (minutes between consecutive SOS per user)
    sos_cooldown_minutes: Mapped[int] = mapped_column(Integer, default=10)

    # "About us" text shown in the О нас section
    about_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
