"""Add processed_payments table for YooKassa webhook idempotency.

Revision ID: 012
Revises: 011
Create Date: 2026-05-11

Пакет 15 000 ₽, пункт Д: ЮKassa может повторно отправить webhook
после таймаута/5xx. Без записи факта обработки в одной общей таблице
donate/event_creation/raise_profile-обработчики дважды
зачисляли кредит / слали уведомление. Идемпотентность по payment_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_payments",
        sa.Column("payment_id", sa.String(length=128), primary_key=True),
        sa.Column("payment_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_processed_payments_created_at",
        "processed_payments",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_processed_payments_created_at", table_name="processed_payments")
    op.drop_table("processed_payments")
