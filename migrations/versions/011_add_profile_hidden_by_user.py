"""Add hidden_by_user to profile_pilots and profile_passengers.

Revision ID: 011
Revises: 010
Create Date: 2026-05-11

Пакет 15 000 ₽, пункт А: пользователь может временно скрыть свою анкету
из ленты «Мотопара» (например, на время болезни/отпуска), не удаляя её.
Отдельное поле от is_hidden, чтобы admin-скрытие (по жалобе) не
конфликтовало с пользовательским — это разные оси.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profile_pilots",
        sa.Column(
            "hidden_by_user", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.add_column(
        "profile_passengers",
        sa.Column(
            "hidden_by_user", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("profile_passengers", "hidden_by_user")
    op.drop_column("profile_pilots", "hidden_by_user")
