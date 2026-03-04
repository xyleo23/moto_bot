"""Initial schema.

Revision ID: 001
Revises:
Create Date: 2025-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cities_name", "cities", ["name"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Enum("telegram", "max", name="platform"), nullable=False),
        sa.Column("platform_user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_username", sa.String(255), nullable=True),
        sa.Column("platform_first_name", sa.String(255), nullable=True),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.Enum("pilot", "passenger", "admin", "superadmin", name="userrole"), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), default=False),
        sa.Column("block_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
    )
    op.create_index(op.f("ix_users_platform_user_id"), "users", ["platform_user_id"])
    op.create_unique_constraint("uq_users_platform_user", "users", ["platform", "platform_user_id"])

    op.create_table(
        "city_admins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    op.create_table(
        "profile_pilots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("gender", sa.Enum("male", "female", "other", name="gender"), nullable=False),
        sa.Column("bike_brand", sa.String(100), nullable=False),
        sa.Column("bike_model", sa.String(100), nullable=False),
        sa.Column("engine_cc", sa.Integer(), nullable=False),
        sa.Column("driving_since", sa.Date(), nullable=False),
        sa.Column("driving_style", sa.Enum("calm", "aggressive", "mixed", name="drivingstyle"), nullable=False),
        sa.Column("photo_file_id", sa.String(255), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("raised_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("is_hidden", sa.Boolean(), default=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_profile_pilots_user_id", "profile_pilots", ["user_id"], unique=True)

    op.create_table(
        "profile_passengers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("gender", sa.Enum("male", "female", "other", name="gender_passenger"), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("preferred_style", sa.Enum("calm", "dynamic", "mixed", name="preferredstyle"), nullable=False),
        sa.Column("photo_file_id", sa.String(255), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("raised_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("is_hidden", sa.Boolean(), default=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_profile_passengers_user_id", "profile_passengers", ["user_id"], unique=True)

    op.create_table(
        "subscription_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_enabled", sa.Boolean(), default=False),
        sa.Column("monthly_price_kopecks", sa.Integer(), default=29900),
        sa.Column("season_price_kopecks", sa.Integer(), default=79900),
        sa.Column("event_creation_enabled", sa.Boolean(), default=False),
        sa.Column("event_creation_price_kopecks", sa.Integer(), default=9900),
        sa.Column("raise_profile_enabled", sa.Boolean(), default=False),
        sa.Column("raise_profile_price_kopecks", sa.Integer(), default=4900),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Enum("monthly", "season", name="subscriptiontype"), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("expires_at", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("payment_id", sa.String(100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    op.create_table(
        "likes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_like", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
        sa.UniqueConstraint("from_user_id", "to_user_id", name="uq_likes_from_to"),
    )

    op.create_table(
        "like_blacklist",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocked_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocked_user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id", "blocked_user_id", name="uq_like_blacklist"),
    )

    op.create_table(
        "sos_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Enum("accident", "broken_down", "ran_out_of_gas", "other", name="sostype"), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
    )

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.Enum("large", "motorcade", "run", name="eventtype"), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("point_start", sa.String(500), nullable=False),
        sa.Column("point_end", sa.String(500), nullable=True),
        sa.Column("ride_type", sa.Enum("column", "free", name="ridetype"), nullable=True),
        sa.Column("avg_speed", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_recommended", sa.Boolean(), default=False),
        sa.Column("is_official", sa.Boolean(), default=False),
        sa.Column("is_cancelled", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
    )

    op.create_table(
        "event_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("seeking_pair", sa.Boolean(), default=False),
        sa.Column("matched_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["matched_user_id"], ["users.id"]),
    )

    op.create_table(
        "event_pair_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Enum("pending", "accepted", "rejected", name="pairrequeststatus"), server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
    )

    op.create_table(
        "useful_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("city_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.Enum("motoshop", "motoservice", "motoschool", "motoclubs", "motoevac", "other", name="contactcategory"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    op.create_table(
        "global_texts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_global_texts_key", "global_texts", ["key"], unique=True)


def downgrade() -> None:
    op.drop_table("global_texts")
    op.drop_table("useful_contacts")
    op.drop_table("event_pair_requests")
    op.drop_table("event_registrations")
    op.drop_table("events")
    op.drop_table("sos_alerts")
    op.drop_table("like_blacklist")
    op.drop_table("likes")
    op.drop_table("subscriptions")
    op.drop_table("subscription_settings")
    op.drop_table("profile_passengers")
    op.drop_table("profile_pilots")
    op.drop_table("city_admins")
    op.drop_table("users")
    op.drop_table("cities")
