"""Add is_hidden to events for complaint handling.

Revision ID: 005
Revises: 004
Create Date: 2026-03-16

Жалобы на мероприятия: принять = скрыть мероприятие из списка.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("events", "is_hidden")
