"""Tests for registration_service — finish_pilot/passenger_registration."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.models.user import Platform


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_pilot_data(**overrides) -> dict:
    data = {
        "name": "Тест Пилот",
        "phone": "+79001234567",
        "age": 28,
        "gender": "male",
        "bike_brand": "Honda",
        "bike_model": "CB500",
        "engine_cc": 500,
        "driving_since": "2020-01-01",
        "driving_style": "calm",
        "photo_file_id": None,
        "about": None,
    }
    data.update(overrides)
    return data


def _make_passenger_data(**overrides) -> dict:
    data = {
        "name": "Тест Двойка",
        "phone": "+79009876543",
        "age": 25,
        "gender": "female",
        "weight": 60,
        "height": 170,
        "preferred_style": "calm",
        "photo_file_id": None,
        "about": "Тест",
    }
    data.update(overrides)
    return data


def _mock_user(uid: uuid.UUID | None = None, role=None):
    from src.models.user import UserRole
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    u.role = role or UserRole.PILOT
    return u


def _scalar_none_result():
    """SQLAlchemy result mock: scalar_one_or_none() → None (no phone match on other platform)."""
    m = MagicMock()
    m.scalar_one_or_none.return_value = None
    return m


# ── finish_pilot_registration ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pilot_returns_user_not_found_when_no_user():
    """Returns 'user_not_found' when User row is missing."""
    from src.services.registration_service import finish_pilot_registration

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_pilot_registration(Platform.MAX, 999, _make_pilot_data())

    assert result == "user_not_found"


@pytest.mark.asyncio
async def test_pilot_returns_invalid_phone_for_short_phone():
    """Returns 'invalid_phone' when phone is too short."""
    from src.services.registration_service import finish_pilot_registration

    result = await finish_pilot_registration(Platform.MAX, 1, _make_pilot_data(phone="123"))
    assert result == "invalid_phone"


@pytest.mark.asyncio
async def test_pilot_returns_none_on_success():
    """Returns None when profile is saved successfully."""
    from src.services.registration_service import finish_pilot_registration

    user = _mock_user()
    existing_profile_result = MagicMock()
    existing_profile_result.scalar_one_or_none.return_value = None

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    # User → phone lookup (pilot+passenger, no cross-platform match) → ProfilePilot row
    mock_session.execute = AsyncMock(
        side_effect=[
            user_result,
            _scalar_none_result(),
            _scalar_none_result(),
            existing_profile_result,
        ]
    )
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_pilot_registration(Platform.MAX, user.id, _make_pilot_data())

    assert result is None
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pilot_updates_existing_profile():
    """Updates existing ProfilePilot when one already exists."""
    from src.services.registration_service import finish_pilot_registration

    user = _mock_user()
    existing_profile = MagicMock()

    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = existing_profile

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(
        side_effect=[
            user_result,
            _scalar_none_result(),
            _scalar_none_result(),
            profile_result,
        ]
    )
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_pilot_registration(
            Platform.MAX, user.id, _make_pilot_data(name="Обновлённое имя")
        )

    assert result is None
    assert existing_profile.name == "Обновлённое имя"


@pytest.mark.asyncio
async def test_pilot_returns_db_error_on_commit_failure():
    """Returns 'db_error' when DB commit raises."""
    from src.services.registration_service import finish_pilot_registration

    user = _mock_user()
    no_profile_result = MagicMock()
    no_profile_result.scalar_one_or_none.return_value = None
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            user_result,
            _scalar_none_result(),
            _scalar_none_result(),
            no_profile_result,
        ]
    )
    mock_session.commit = AsyncMock(side_effect=Exception("DB down"))
    mock_session.rollback = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_pilot_registration(Platform.MAX, user.id, _make_pilot_data())

    assert result == "db_error"
    mock_session.rollback.assert_awaited_once()


# ── finish_passenger_registration ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_passenger_returns_user_not_found():
    from src.services.registration_service import finish_passenger_registration

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_passenger_registration(
            Platform.MAX, 888, _make_passenger_data()
        )

    assert result == "user_not_found"


@pytest.mark.asyncio
async def test_passenger_returns_missing_fields_for_incomplete_data():
    from src.services.registration_service import finish_passenger_registration

    # Missing required fields
    incomplete = {"name": "Test", "phone": "+79001234567"}
    result = await finish_passenger_registration(Platform.MAX, 1, incomplete)
    assert result == "missing_fields"


@pytest.mark.asyncio
async def test_passenger_returns_invalid_phone():
    from src.services.registration_service import finish_passenger_registration

    result = await finish_passenger_registration(
        Platform.MAX, 1, _make_passenger_data(phone="12")
    )
    assert result == "invalid_phone"


@pytest.mark.asyncio
async def test_passenger_returns_none_on_success():
    from src.services.registration_service import finish_passenger_registration

    user = _mock_user()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    no_profile_result = MagicMock()
    no_profile_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            user_result,
            _scalar_none_result(),
            _scalar_none_result(),
            no_profile_result,
        ]
    )
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_passenger_registration(
            Platform.MAX, user.id, _make_passenger_data()
        )

    assert result is None
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_passenger_sets_role_to_passenger():
    """Ensures user.role is set to PASSENGER during registration."""
    from src.services.registration_service import finish_passenger_registration
    from src.models.user import UserRole

    user = _mock_user()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    no_profile_result = MagicMock()
    no_profile_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            user_result,
            _scalar_none_result(),
            _scalar_none_result(),
            no_profile_result,
        ]
    )
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        await finish_passenger_registration(Platform.MAX, user.id, _make_passenger_data())

    assert user.role == UserRole.PASSENGER


@pytest.mark.asyncio
async def test_passenger_db_error_returns_db_error():
    from src.services.registration_service import finish_passenger_registration

    user = _mock_user()
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    no_profile_result = MagicMock()
    no_profile_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            user_result,
            _scalar_none_result(),
            _scalar_none_result(),
            no_profile_result,
        ]
    )
    mock_session.commit = AsyncMock(side_effect=Exception("DB error"))
    mock_session.rollback = AsyncMock()

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.services.registration_service.get_session_factory", return_value=mock_factory):
        result = await finish_passenger_registration(Platform.MAX, user.id, _make_passenger_data())

    assert result == "db_error"
    mock_session.rollback.assert_awaited_once()
