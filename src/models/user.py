"""User model."""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, generate_uuid


class Platform(str, enum.Enum):
    TELEGRAM = "telegram"
    MAX = "max"


class UserRole(str, enum.Enum):
    PILOT = "pilot"
    PASSENGER = "passenger"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    platform_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform_first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cities.id"), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        default=UserRole.PILOT,
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    block_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        {"sqlite_autoincrement": False}
    )
