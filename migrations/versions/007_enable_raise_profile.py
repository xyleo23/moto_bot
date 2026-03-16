"""Enable raise_profile_enabled by default in existing subscription_settings row.

Revision ID: 007
Revises: 006
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable raise_profile feature for existing settings row (disabled = free raise bug)
    op.execute(
        "UPDATE subscription_settings SET raise_profile_enabled = TRUE "
        "WHERE raise_profile_enabled = FALSE"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE subscription_settings SET raise_profile_enabled = FALSE"
    )
