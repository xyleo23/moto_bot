"""MAX: store dialog chat_id for reliable proactive POST /messages.

Revision ID: 009
Revises: 008
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "max_dialog_chat_id" not in cols:
        op.add_column(
            "users",
            sa.Column("max_dialog_chat_id", sa.BigInteger(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("users", "max_dialog_chat_id")
