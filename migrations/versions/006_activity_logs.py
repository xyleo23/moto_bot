"""Activity logs for admin journal.

Revision ID: 006
Revises: 005
Create Date: 2026-03-16

ТЗ 2.2.11: Логи активности (SOS, подписки, блокировки и т.п.)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "activity_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_activity_logs_event_type", "activity_logs", ["event_type"])
    op.create_index("ix_activity_logs_user_id", "activity_logs", ["user_id"])
    op.create_index("ix_activity_logs_created_at", "activity_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_activity_logs_created_at", table_name="activity_logs")
    op.drop_index("ix_activity_logs_user_id", table_name="activity_logs")
    op.drop_index("ix_activity_logs_event_type", table_name="activity_logs")
    op.drop_table("activity_logs")
