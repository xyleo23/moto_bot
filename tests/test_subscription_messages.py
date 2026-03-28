"""subscription_messages: unified paywall texts."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.subscription_messages import (
    motorcade_limit_for_subscription_texts,
    subscription_required_message,
    max_profile_subscription_block,
)


@pytest.mark.asyncio
async def test_motorcade_limit_from_settings():
    mock_row = MagicMock()
    mock_row.event_motorcade_limit_per_month = 3

    with patch(
        "src.services.subscription_messages.get_subscription_settings",
        new_callable=AsyncMock,
        return_value=mock_row,
    ):
        assert await motorcade_limit_for_subscription_texts() == 3


@pytest.mark.asyncio
async def test_motorcade_limit_fallback():
    with patch(
        "src.services.subscription_messages.get_subscription_settings",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await motorcade_limit_for_subscription_texts() == 2


@pytest.mark.asyncio
async def test_subscription_required_message_contains_limit():
    mock_row = MagicMock()
    mock_row.event_motorcade_limit_per_month = 1

    with patch(
        "src.services.subscription_messages.get_subscription_settings",
        new_callable=AsyncMock,
        return_value=mock_row,
    ):
        msg = await subscription_required_message("motopair_menu")
    assert "Мотопара" in msg or "мотопары" in msg
    assert "1 бесплатно в месяц" in msg


@pytest.mark.asyncio
async def test_max_profile_block_matches_benefits():
    mock_row = MagicMock()
    mock_row.event_motorcade_limit_per_month = 2

    with patch(
        "src.services.subscription_messages.get_subscription_settings",
        new_callable=AsyncMock,
        return_value=mock_row,
    ):
        block = await max_profile_subscription_block()
    assert "функциям бота" in block
    assert "Прохваты" in block
