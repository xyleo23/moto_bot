"""Add uniqueness constraints for payment and event registration idempotency.

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
    inspector = sa.inspect(bind)

    # 1) subscriptions.payment_id should be unique when not null.
    # Cleanup legacy duplicates first (keep earliest by created_at).
    op.execute(
        """
        DELETE FROM subscriptions s
        USING subscriptions d
        WHERE s.payment_id IS NOT NULL
          AND d.payment_id IS NOT NULL
          AND s.payment_id = d.payment_id
          AND s.id <> d.id
          AND (s.started_at, s.id) > (d.started_at, d.id)
        """
    )
    idx_names = {i["name"] for i in inspector.get_indexes("subscriptions")}
    if "uq_subscriptions_payment_id_not_null" not in idx_names:
        op.create_index(
            "uq_subscriptions_payment_id_not_null",
            "subscriptions",
            ["payment_id"],
            unique=True,
            postgresql_where=sa.text("payment_id IS NOT NULL"),
        )

    # 2) event_registrations should be unique per (event_id, user_id).
    # Cleanup duplicates first (keep earliest row by created_at/id).
    op.execute(
        """
        DELETE FROM event_registrations e
        USING event_registrations d
        WHERE e.event_id = d.event_id
          AND e.user_id = d.user_id
          AND e.id <> d.id
          AND (e.created_at, e.id) > (d.created_at, d.id)
        """
    )
    uqs = {u["name"] for u in inspector.get_unique_constraints("event_registrations")}
    if "uq_event_registration_event_user" not in uqs:
        op.create_unique_constraint(
            "uq_event_registration_event_user",
            "event_registrations",
            ["event_id", "user_id"],
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_event_registration_event_user",
        "event_registrations",
        type_="unique",
    )
    op.drop_index("uq_subscriptions_payment_id_not_null", table_name="subscriptions")

