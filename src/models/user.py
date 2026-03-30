"""User model."""

import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column

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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Cross-platform account linking: when a user registers on MAX with the same
    # phone as an existing Telegram user (or vice versa), their linked_user_id
    # is set to the canonical (first-registered) user's id.  All profile,
    # subscription and like data is stored under the canonical user's id.
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # MAX: id диалога пользователь↔бот (recipient.chat_id в апдейтах). Для POST /messages
    # в личку надёжнее chat_id, чем platform_user_id — они могут различаться.
    max_dialog_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_users_linked_user_id", "linked_user_id"),
        {"sqlite_autoincrement": False},
    )


def effective_user_id(user: "User") -> uuid.UUID:
    """Return the canonical UUID used for all data lookups.

    When a user is linked to another account (cross-platform), returns the
    linked (primary) user's id so profile/subscription/like data is shared.
    """
    return user.linked_user_id if user.linked_user_id else user.id
