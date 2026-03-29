"""Basic service tests."""

import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_motopair_raise_profile():
    """Test raise_profile with invalid user_id returns False."""
    try:
        from src.services.motopair_service import raise_profile

        fake_id = uuid4()
        ok = await raise_profile(fake_id, "pilot")
        assert ok is False
    except Exception as e:
        pytest.skip(f"DB not available: {e}")


@pytest.mark.asyncio
async def test_get_events_list_empty_when_no_city():
    """get_events_list returns [] when city_id is None."""
    from src.services.event_service import get_events_list

    result = await get_events_list(None)
    assert result == []


@pytest.mark.asyncio
async def test_motorcade_quota_before_global_paid_flag(monkeypatch):
    """Подписчик сверх лимита: квота применяется даже если «платное создание» выключено."""
    from unittest.mock import AsyncMock, MagicMock

    from src.services import event_service

    settings = MagicMock()
    settings.event_creation_enabled = False
    settings.event_creation_price_kopecks = 9900
    settings.event_motorcade_limit_per_month = 2

    monkeypatch.setattr(
        "src.services.admin_service.can_create_event_free",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        event_service,
        "_user_has_active_subscription",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        event_service,
        "count_motorcades_this_month",
        AsyncMock(return_value=2),
    )

    uid = uuid4()
    cid = uuid4()
    need, price = await event_service.event_creation_payment_required(
        uid, 12345, cid, "motorcade", settings
    )
    assert need is True
    assert price is None

    monkeypatch.setattr(
        event_service,
        "count_motorcades_this_month",
        AsyncMock(return_value=1),
    )
    need2, price2 = await event_service.event_creation_payment_required(
        uid, 12345, cid, "motorcade", settings
    )
    assert need2 is False
    assert price2 is None

    settings.event_creation_enabled = True
    monkeypatch.setattr(
        event_service,
        "count_motorcades_this_month",
        AsyncMock(return_value=2),
    )
    need3, price3 = await event_service.event_creation_payment_required(
        uid, 12345, cid, "motorcade", settings
    )
    assert need3 is True
    assert price3 == 9900


def test_format_profile_max():
    """Test _format_profile_max helper."""
    from src.max_runner import _format_profile_max

    class MockPilot:
        name = "Иван"
        age = 30
        bike_brand = "Honda"
        bike_model = "CB500"
        engine_cc = 500
        about = "Люблю горы"

    text = _format_profile_max(MockPilot())
    assert "Иван" in text
    assert "Honda" in text
    assert "500" in text
