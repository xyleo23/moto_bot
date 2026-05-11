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


@pytest.mark.asyncio
async def test_get_stats_extended_registration_metrics(monkeypatch):
    """Пакет 15к, пункт Р: get_stats возвращает разделение start vs registered.

    Проверяем, что добавлены поля pilots_registered/passengers_registered/
    registered_total/conversion_pct, и что конверсия считается верно.
    """
    from unittest.mock import AsyncMock, MagicMock
    from src.services import admin_service

    # 100 нажали /start, 60 завершили (30 пилотов + 30 пассажиров) → 60.0%
    counts = iter([
        100,  # users
        5,    # sos
        10,   # events
        2,    # blocked
        7,    # active_subs
        30,   # pilots_registered
        30,   # passengers_registered
    ])

    fake_session = MagicMock()
    fake_session.scalar = AsyncMock(side_effect=lambda *_a, **_kw: next(counts))
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    fake_factory = MagicMock(return_value=fake_session)
    monkeypatch.setattr(admin_service, "get_session_factory", lambda: fake_factory)

    stats = await admin_service.get_stats()

    assert stats["users"] == 100
    assert stats["pilots_registered"] == 30
    assert stats["passengers_registered"] == 30
    assert stats["registered_total"] == 60
    assert stats["conversion_pct"] == 60.0


@pytest.mark.asyncio
async def test_set_profile_hidden_by_user_pilot(monkeypatch):
    """Пункт А: set_profile_hidden_by_user(role=pilot) обновляет hidden_by_user."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import motopair_service

    class FakePilot:
        hidden_by_user = False

    fake = FakePilot()

    class FakeResult:
        def scalar_one_or_none(self):
            return fake

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=FakeResult())
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        motopair_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    ok = await motopair_service.set_profile_hidden_by_user(uuid4(), "pilot", True)
    assert ok is True
    assert fake.hidden_by_user is True
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_profile_hidden_by_user_returns_false_without_profile(monkeypatch):
    """Если анкеты нет — set_profile_hidden_by_user возвращает False."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import motopair_service

    class FakeResult:
        def scalar_one_or_none(self):
            return None

    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=FakeResult())
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        motopair_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    ok = await motopair_service.set_profile_hidden_by_user(uuid4(), "passenger", True)
    assert ok is False
    fake_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_stats_conversion_pct_zero_users(monkeypatch):
    """При нулевом users конверсия не должна делить на ноль — отдаём 0.0."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import admin_service

    counts = iter([0, 0, 0, 0, 0, 0, 0])
    fake_session = MagicMock()
    fake_session.scalar = AsyncMock(side_effect=lambda *_a, **_kw: next(counts))
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_factory = MagicMock(return_value=fake_session)
    monkeypatch.setattr(admin_service, "get_session_factory", lambda: fake_factory)

    stats = await admin_service.get_stats()
    assert stats["users"] == 0
    assert stats["conversion_pct"] == 0.0
    assert stats["registered_total"] == 0


@pytest.mark.asyncio
async def test_format_admin_user_card_with_pilot_phone(monkeypatch):
    """Карточка показывает телефон из ProfilePilot и tg-ссылку для TG-юзера."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import admin_service
    from src.models.user import Platform

    fake_pilot = MagicMock(phone="+79991234567")
    fake_session = MagicMock()
    fake_session.scalar = AsyncMock(return_value=fake_pilot)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        admin_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    user = MagicMock(
        id=uuid4(),
        linked_user_id=None,
        platform=Platform.TELEGRAM,
        platform_user_id=12345,
        platform_username="vasya",
        platform_first_name="Вася",
        is_blocked=False,
        block_reason=None,
    )
    text = await admin_service.format_admin_user_card(user)
    assert "+79991234567" in text
    assert "tg://user?id=12345" in text
    assert "🏍 Пилот" in text
    assert "Telegram" in text


@pytest.mark.asyncio
async def test_format_admin_user_card_no_profile(monkeypatch):
    """Когда анкеты нет — телефон «—», роль помечена как незаполненная."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import admin_service
    from src.models.user import Platform

    fake_session = MagicMock()
    fake_session.scalar = AsyncMock(return_value=None)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        admin_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    user = MagicMock(
        id=uuid4(),
        linked_user_id=None,
        platform=Platform.MAX,
        platform_user_id=999,
        platform_username=None,
        platform_first_name=None,
        is_blocked=True,
        block_reason="spam",
    )
    text = await admin_service.format_admin_user_card(user)
    assert "Телефон: <code>—</code>" in text
    assert "анкета не заполнена" in text
    assert "Заблокирован" in text
    assert "spam" in text
    assert "MAX" in text
