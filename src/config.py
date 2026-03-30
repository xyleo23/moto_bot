"""Configuration via Pydantic Settings."""

from pydantic import Field
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
    telegram_bot_username: str | None = Field(
        default=None,
        description="Bot username for return_url after YooKassa payment (e.g. MyMotoBot)",
    )

    # MAX
    max_bot_token: str | None = Field(default=None, description="MAX bot token")
    max_api_base: str = Field(
        default="https://platform-api.max.ru",
        description="MAX API base URL",
    )
    max_bot_username: str | None = Field(
        default=None,
        description="MAX bot username for return_url (e.g. id123456_bot)",
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
    webhook_trust_proxy: bool = Field(
        default=False,
        description="Behind nginx: trust X-Real-IP / X-Forwarded-For for YooKassa IP check",
    )
    webhook_require_signature: bool = Field(
        default=True,
        description="Require valid YooKassa X-Content-Signature for webhook acceptance",
    )

    # App — str избегает JSON-парсинга; @property не участвует в env-загрузке
    superadmin_ids_raw: str = Field(
        default="",
        alias="SUPERADMIN_IDS",
        description=(
            "Comma-separated platform user IDs of superadmins (Telegram user_id и/или MAX user_id). "
            "Добавь все свои ID, если заходишь и из TG, и из MAX — иначе уведомления придут не на ту платформу."
        ),
    )

    @property
    def superadmin_ids(self) -> list[int]:
        """List of superadmin IDs — computed from superadmin_ids_raw."""
        return _parse_superadmin_ids(self.superadmin_ids_raw)

    @property
    def telegram_return_url(self) -> str | None:
        """URL for YooKassa 'return to store' — opens bot in Telegram."""
        if self.telegram_bot_username:
            uname = self.telegram_bot_username.lstrip("@")
            return f"https://t.me/{uname}"
        return None

    @property
    def max_return_url(self) -> str:
        """URL for YooKassa 'return to store' — opens bot in MAX (официальный формат max.ru/id…_bot)."""
        if self.max_bot_username:
            uname = self.max_bot_username.lstrip("@")
            return f"https://max.ru/{uname}"
        return "https://max.ru/"

    support_username: str = Field(
        default="support",
        description="Support Telegram @username (fallback if not set in admin → БД)",
    )
    support_email: str = Field(
        default="support@example.com",
        description="Support email (fallback if not set in admin → БД)",
    )

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
