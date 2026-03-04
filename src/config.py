"""Configuration via Pydantic Settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
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

    # App
    superadmin_ids: list[int] = Field(
        default_factory=list,
        description="Comma-separated Telegram/MAX user IDs of superadmins",
    )

    @field_validator("superadmin_ids", mode="before")
    @classmethod
    def parse_superadmin_ids(cls, v) -> list[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, list):
            return v
        return []
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
