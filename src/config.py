"""Configuration via Pydantic Settings."""
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_superadmin_ids(v: str) -> list[int]:
    """Parse comma-separated IDs string to list[int]."""
    if not v or not isinstance(v, str):
        return []
    return [int(x.strip()) for x in v.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,  # env SUPERADMIN_IDS → superadmin_ids_raw via alias
    )

    # Platform
    platform: str = Field(default="telegram", description="telegram | max | both")

    # Telegram
    telegram_bot_token: str | None = Field(default=None, description="Telegram bot token")

    # MAX
    max_bot_token: str | None = Field(default=None, description="MAX bot token")
    max_api_base: str = Field(
        default="https://platform-api.max.ru",
        description="MAX API base URL",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/moto_bot",
        description="PostgreSQL connection URL (asyncpg)",
    )

    # Redis (FSM, cache, rate limits)
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis URL")

    # YooKassa
    yookassa_shop_id: str | None = Field(default=None, description="YooKassa shop ID")
    yookassa_secret_key: str | None = Field(default=None, description="YooKassa secret key")
    webhook_port: int = Field(default=8080, description="Port for YooKassa webhook server")

    # App — str избегает JSON-парсинга Pydantic; список через @computed_field
    superadmin_ids_raw: str = Field(
        default="",
        alias="SUPERADMIN_IDS",
        description="Comma-separated Telegram/MAX user IDs of superadmins",
    )

    @computed_field
    @property
    def superadmin_ids(self) -> list[int]:
        return _parse_superadmin_ids(self.superadmin_ids_raw)

    support_username: str = Field(default="support", description="Support Telegram username")
    support_email: str = Field(default="support@example.com", description="Support email")

    # SOS
    sos_cooldown_minutes: int = Field(default=10, description="Minutes between SOS per user")
    sos_cooldown_seconds: int = Field(default=600, description="SOS cooldown in seconds")

    # Limits
    about_text_max_length: int = Field(default=500, description="Max chars for 'About me'")
    about_text_max_extended: int = Field(default=1000, description="Extended limit if needed")

    # Subscription (defaults, overridable by admin)
    subscription_monthly_price: int = Field(default=29900, description="Monthly price in kopecks")
    subscription_season_price: int = Field(default=79900, description="Season price in kopecks")
    event_creation_price: int = Field(default=9900, description="Event creation price in kopecks")
    raise_profile_price: int = Field(default=4900, description="Raise profile price in kopecks")


def get_settings() -> Settings:
    return Settings()
