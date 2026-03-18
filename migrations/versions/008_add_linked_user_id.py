"""Add linked_user_id to users for cross-platform account unification.

When a user registers on MAX with the same phone as an existing Telegram user
(or vice versa), the newer account's linked_user_id is set to the older account's
id so all profile/subscription/like data is shared across platforms.

Revision ID: 008
Revises: 007
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = [c["name"] for c in sa.inspect(bind).get_columns("users")]
    if "linked_user_id" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "linked_user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.create_index("ix_users_linked_user_id", "users", ["linked_user_id"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_users_linked_user_id", table_name="users")
    op.drop_column("users", "linked_user_id")
