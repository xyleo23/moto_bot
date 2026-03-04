"""Add bot_settings table and phone_change_requests table.

Revision ID: 003
Revises: 002
Create Date: 2026-03-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── bot_settings: single-row configurable parameters ──────────────────────
    op.create_table(
        "bot_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("subscription_price_month", sa.Integer(), nullable=False, server_default="29900"),
        sa.Column("subscription_price_season", sa.Integer(), nullable=False, server_default="79900"),
        sa.Column("event_creation_paid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("event_creation_price", sa.Integer(), nullable=False, server_default="9900"),
        sa.Column("profile_raise_paid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("profile_raise_price", sa.Integer(), nullable=False, server_default="4900"),
        sa.Column("sos_cooldown_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("about_text", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── phone_change_requests: user → admin phone change workflow ─────────────
    op.create_table(
        "phone_change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="phonechangestatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("new_phone", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_phone_change_requests_user_id",
        "phone_change_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_phone_change_requests_status",
        "phone_change_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_phone_change_requests_status", "phone_change_requests")
    op.drop_index("ix_phone_change_requests_user_id", "phone_change_requests")
    op.drop_table("phone_change_requests")
    op.drop_table("bot_settings")
    op.execute("DROP TYPE IF EXISTS phonechangestatus")
