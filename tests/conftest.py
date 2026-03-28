"""Pytest fixtures for moto_bot tests."""

import pytest


@pytest.fixture
def mock_settings(monkeypatch):
    """Override settings for tests."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/moto_bot_test"
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("YOOKASSA_SHOP_ID", "")
    monkeypatch.setenv("YOOKASSA_SECRET_KEY", "")
