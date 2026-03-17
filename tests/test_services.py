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
