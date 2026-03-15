"""Add event_motorcade_limit_per_month to subscription_settings.

Revision ID: 004
Revises: 003
Create Date: 2026-03-16

Логика: мотопробеги с подпиской — 2 бесплатно в месяц, далее за доп плату.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscription_settings",
        sa.Column("event_motorcade_limit_per_month", sa.Integer(), nullable=False, server_default="2"),
    )


def downgrade() -> None:
    op.drop_column("subscription_settings", "event_motorcade_limit_per_month")
