"""Add performance indexes on hot queries.

Revision ID: 013
Revises: 012
Create Date: 2026-05-11

Пакет 15 000 ₽, пункт И: индексы под горячие запросы.

PostgreSQL не создаёт автоматических индексов на FK, поэтому многие
WHERE/JOIN/ORDER BY выполнялись полным сканом таблицы:

- reports (reporter_user_id, created_at desc) — check_report_cooldown
- reports (reported_user_id) — get_report_count + auto-block
- users (created_at)        — admin users list ORDER BY
- users (city_id)           — рассылки/фильтр по городу
- profile_pilots/passengers (raised_at desc) — мотопара-фид ORDER BY
- likes (from_user_id, to_user_id) — анти-дубль и встречные лайки
- activity_log (created_at desc) — лента активности
- subscriptions (user_id, expires_at) — проверка активной подписки
"""
from typing import Sequence, Union

from alembic import op


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    ("ix_reports_reporter_created_at", "reports", ["reporter_user_id", "created_at"]),
    ("ix_reports_reported_user_id", "reports", ["reported_user_id"]),
    ("ix_users_created_at", "users", ["created_at"]),
    ("ix_users_city_id", "users", ["city_id"]),
    ("ix_profile_pilots_raised_at", "profile_pilots", ["raised_at"]),
    ("ix_profile_passengers_raised_at", "profile_passengers", ["raised_at"]),
    ("ix_likes_from_user_id", "likes", ["from_user_id"]),
    ("ix_likes_to_user_id", "likes", ["to_user_id"]),
    ("ix_activity_logs_created_at", "activity_logs", ["created_at"]),
    ("ix_subscriptions_user_id", "subscriptions", ["user_id"]),
    ("ix_subscriptions_expires_at", "subscriptions", ["expires_at"]),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, unique=False, if_not_exists=True)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
