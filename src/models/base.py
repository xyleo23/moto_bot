"""Base model and database setup."""

import uuid
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.postgresql import UUID, JSONB

from src.config import get_settings


convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)

    type_annotation_map = {
        uuid.UUID: UUID(as_uuid=True),
        dict: JSONB,
    }


def generate_uuid() -> uuid.UUID:
    return uuid.uuid4()


_engine = None
_async_session_factory = None


def init_db(database_url: str | None = None) -> None:
    global _engine, _async_session_factory
    url = database_url or get_settings().database_url
    _engine = create_async_engine(
        url,
        echo=False,
    )
    _async_session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_async_session() -> AsyncSession:
    if _async_session_factory is None:
        init_db()
    async with _async_session_factory() as session:
        yield session


def get_session_factory():
    if _async_session_factory is None:
        init_db()
    return _async_session_factory
