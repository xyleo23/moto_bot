"""Global editable texts (О нас, templates, etc)."""

import uuid
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, generate_uuid


class GlobalText(Base):
    __tablename__ = "global_texts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
