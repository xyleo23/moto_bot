"""Add reason column to reports.

Revision ID: 014
Revises: 013
Create Date: 2026-05-15

После 15.05.2026 жалобы стали часто прилетать как «случайные клики» — не
понятно за что. Добавляем колонку reason: либо одна из 5 предопределённых
категорий, либо свободный текст при выборе «Другое». Это и усложняет UI
(меньше случайных кликов), и даёт админу понятную причину в уведомлении.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "reason")
