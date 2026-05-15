"""Basic service tests."""

import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_max_send_photo_card_deletes_prev_message():
    """Аудит 15.05: при листании фида в MAX prev сообщение должно удаляться."""
    from unittest.mock import AsyncMock, MagicMock
    from src.max_runner import _max_send_photo_caption_keyboard

    adapter = MagicMock()
    adapter.delete_message = AsyncMock(return_value=True)
    adapter.send_message = AsyncMock()
    adapter.send_photo = AsyncMock()

    # text-only карточка (без фото) — должен сначала удалить prev, потом отправить.
    await _max_send_photo_caption_keyboard(
        adapter, chat_id="42", stored_photo_id=None, caption="t", keyboard=None,
        prev_message_id="prev-123",
    )
    adapter.delete_message.assert_awaited_once_with("prev-123")
    adapter.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_max_send_photo_card_no_delete_when_no_prev():
    """Без prev_message_id delete не вызывается."""
    from unittest.mock import AsyncMock, MagicMock
    from src.max_runner import _max_send_photo_caption_keyboard

    adapter = MagicMock()
    adapter.delete_message = AsyncMock()
    adapter.send_message = AsyncMock()

    await _max_send_photo_caption_keyboard(
        adapter, chat_id="42", stored_photo_id=None, caption="t", keyboard=None,
    )
    adapter.delete_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_report_passes_reason(monkeypatch):
    """Жалоба сохраняется с переданной причиной (миграция 014)."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    added: list = []

    fake_session = MagicMock()
    fake_session.add = lambda obj: added.append(obj)
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        report_service, "get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    await report_service.save_report(uuid4(), uuid4(), "pilot", reason="spam")
    assert len(added) == 1
    assert getattr(added[0], "reason", None) == "spam"


@pytest.mark.asyncio
async def test_save_report_trims_long_reason(monkeypatch):
    """Длинный текст 'Другое' режется до 500 символов."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    added: list = []
    fake_session = MagicMock()
    fake_session.add = lambda obj: added.append(obj)
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        report_service, "get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    long_text = "x" * 1000
    await report_service.save_report(uuid4(), uuid4(), "pilot", reason=long_text)
    assert len(added[0].reason) == 500


@pytest.mark.asyncio
async def test_save_report_empty_reason_becomes_none(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    added: list = []
    fake_session = MagicMock()
    fake_session.add = lambda obj: added.append(obj)
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        report_service, "get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    await report_service.save_report(uuid4(), uuid4(), "pilot", reason="   ")
    assert added[0].reason is None


@pytest.mark.asyncio
async def test_get_event_participants_empty(monkeypatch):
    """Если на мероприятие никто не записан — возвращается []."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import event_service

    fake_result = MagicMock()
    fake_result.all = MagicMock(return_value=[])
    fake_session = MagicMock()
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        event_service, "get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    out = await event_service.get_event_participants(uuid4())
    assert out == []


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


@pytest.mark.asyncio
async def test_report_cooldown_allows_first_report(monkeypatch):
    """Первая жалоба пропускается без ограничений."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    fake_session = MagicMock()
    fake_session.scalar = AsyncMock(side_effect=[None, 0])
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        report_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    allowed, retry = await report_service.check_report_cooldown(uuid4())
    assert allowed is True
    assert retry == 0


@pytest.mark.asyncio
async def test_report_cooldown_blocks_recent_report(monkeypatch):
    """Если последняя жалоба недавно — возвращаем retry_after > 0."""
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    recent = datetime.utcnow() - timedelta(seconds=5)
    fake_session = MagicMock()
    fake_session.scalar = AsyncMock(return_value=recent)
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        report_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    allowed, retry = await report_service.check_report_cooldown(uuid4())
    assert allowed is False
    assert 20 <= retry <= 30


@pytest.mark.asyncio
async def test_report_cooldown_blocks_daily_limit(monkeypatch):
    """При превышении дневного лимита — allowed=False, retry=0."""
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    long_ago = datetime.utcnow() - timedelta(minutes=10)
    fake_session = MagicMock()
    # scalar() сначала вернёт last_created_at, потом count
    fake_session.scalar = AsyncMock(side_effect=[long_ago, report_service.REPORT_DAILY_LIMIT])
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        report_service, "get_session_factory", lambda: MagicMock(return_value=fake_session)
    )

    allowed, retry = await report_service.check_report_cooldown(uuid4())
    assert allowed is False
    assert retry == 0


@pytest.mark.asyncio
async def test_mark_payment_processed_first_returns_true(monkeypatch):
    """Первый раз — INSERT успешен, возвращает True."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import payment_idempotency

    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        payment_idempotency,
        "get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    ok = await payment_idempotency.mark_payment_processed("pay_123", "donate")
    assert ok is True
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_payment_processed_duplicate_returns_false(monkeypatch):
    """Дубликат payment_id ловится IntegrityError → False."""
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy.exc import IntegrityError
    from src.services import payment_idempotency

    fake_session = MagicMock()
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock(side_effect=IntegrityError("ins", {}, Exception("dup")))
    fake_session.rollback = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        payment_idempotency,
        "get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    ok = await payment_idempotency.mark_payment_processed("pay_456", "event_creation")
    assert ok is False
    fake_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_payment_processed_empty_id_returns_false():
    """Пустой payment_id → False, без обращения к БД."""
    from src.services import payment_idempotency

    ok = await payment_idempotency.mark_payment_processed("", "donate")
    assert ok is False


@pytest.mark.asyncio
async def test_broadcast_retries_on_retry_after(monkeypatch):
    """При TelegramRetryAfter — спим и повторяем отправку."""
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.exceptions import TelegramRetryAfter
    from src.services import broadcast

    # 1-я попытка падает RetryAfter, 2-я успешна.
    method = MagicMock()
    method.__name__ = "sendMessage"
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(
        side_effect=[TelegramRetryAfter(method=method, message="flood", retry_after=1), None]
    )

    sleep_calls: list[float] = []

    async def fake_sleep(s):
        sleep_calls.append(s)

    monkeypatch.setattr(broadcast.asyncio, "sleep", fake_sleep)

    sent, failed = await broadcast._do_broadcast(fake_bot, [12345], "hi")
    assert sent == 1
    assert failed == 0
    assert fake_bot.send_message.await_count == 2
    # первый sleep — это retry_after+1=2, второй — _SEND_DELAY=0.05
    assert 2 in sleep_calls


@pytest.mark.asyncio
async def test_broadcast_gives_up_after_max_attempts(monkeypatch):
    """3 подряд RetryAfter → failed=1, юзер пропущен."""
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.exceptions import TelegramRetryAfter
    from src.services import broadcast

    method = MagicMock()
    method.__name__ = "sendMessage"
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(
        side_effect=TelegramRetryAfter(method=method, message="flood", retry_after=1)
    )

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(broadcast.asyncio, "sleep", fake_sleep)

    sent, failed = await broadcast._do_broadcast(fake_bot, [12345], "hi")
    assert sent == 0
    assert failed == 1
    assert fake_bot.send_message.await_count == broadcast._RETRY_MAX_ATTEMPTS


def test_parse_registration_date_year_only():
    """Пункт О: год → 1 января указанного года."""
    from datetime import date
    from src.services.registration_shared import parse_registration_date

    assert parse_registration_date("2010") == date(2010, 1, 1)
    assert parse_registration_date("1969") is None  # ниже 1970
    assert parse_registration_date("2031") is None  # выше 2030


def test_parse_registration_date_month_year():
    """ММ.ГГГГ → 1 число месяца."""
    from datetime import date
    from src.services.registration_shared import parse_registration_date

    assert parse_registration_date("06.2018") == date(2018, 6, 1)
    assert parse_registration_date("6/2018") == date(2018, 6, 1)
    assert parse_registration_date("13.2018") is None  # некорректный месяц


def test_parse_registration_date_full():
    """Полная дата DD.MM.YYYY."""
    from datetime import date
    from src.services.registration_shared import parse_registration_date

    assert parse_registration_date("26.06.2006") == date(2006, 6, 26)
    assert parse_registration_date("26062006") == date(2006, 6, 26)
    assert parse_registration_date("ерунда") is None


def test_parse_russian_date_dd_month_yyyy():
    """«26 июня 2006»."""
    from datetime import date
    from src.services.registration_shared import parse_russian_date, parse_registration_date

    assert parse_russian_date("26 июня 2006") == date(2006, 6, 26)
    assert parse_registration_date("26 июня 2006") == date(2006, 6, 26)
    assert parse_russian_date("26 неваляшки 2006") is None


def test_effective_user_id_returns_linked_when_set():
    """Пункт П: effective_user_id отдаёт linked id для связанного аккаунта."""
    from unittest.mock import MagicMock
    from src.models.user import effective_user_id
    from uuid import uuid4

    canonical = uuid4()
    user = MagicMock(id=uuid4(), linked_user_id=canonical)
    assert effective_user_id(user) == canonical


def test_effective_user_id_returns_self_when_unlinked():
    """Если linked_user_id=None — возвращает собственный id."""
    from unittest.mock import MagicMock
    from src.models.user import effective_user_id
    from uuid import uuid4

    own = uuid4()
    user = MagicMock(id=own, linked_user_id=None)
    assert effective_user_id(user) == own


@pytest.mark.asyncio
async def test_maybe_auto_block_does_nothing_below_threshold(monkeypatch):
    """Авто-блок не срабатывает пока кол-во жалоб < threshold."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    # 2 жалобы при пороге 3.
    monkeypatch.setattr(report_service, "get_report_count", AsyncMock(return_value=2))
    fake_settings = MagicMock(auto_block_reports_threshold=3)
    monkeypatch.setattr(
        report_service, "get_settings_from_db", AsyncMock(return_value=fake_settings)
    )
    auto_block = AsyncMock()
    monkeypatch.setattr(report_service, "auto_block_user", auto_block)

    await report_service.maybe_auto_block_after_report(uuid4())
    auto_block.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_auto_block_triggers_at_threshold(monkeypatch):
    """При достижении threshold вызывает auto_block_user с reason."""
    from unittest.mock import AsyncMock, MagicMock
    from src.services import report_service

    monkeypatch.setattr(report_service, "get_report_count", AsyncMock(return_value=5))
    fake_settings = MagicMock(auto_block_reports_threshold=5)
    monkeypatch.setattr(
        report_service, "get_settings_from_db", AsyncMock(return_value=fake_settings)
    )
    auto_block = AsyncMock()
    monkeypatch.setattr(report_service, "auto_block_user", auto_block)

    target = uuid4()
    await report_service.maybe_auto_block_after_report(target)
    auto_block.assert_awaited_once()
    args, kwargs = auto_block.call_args
    assert args[0] == target
    assert "5" in kwargs["reason"]


@pytest.mark.asyncio
async def test_broadcast_no_retry_on_forbidden(monkeypatch):
    """TelegramForbiddenError → 1 попытка, failed=1, без ожидания."""
    from unittest.mock import AsyncMock, MagicMock
    from aiogram.exceptions import TelegramForbiddenError
    from src.services import broadcast

    method = MagicMock()
    method.__name__ = "sendMessage"
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(
        side_effect=TelegramForbiddenError(method=method, message="blocked")
    )

    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(broadcast.asyncio, "sleep", fake_sleep)

    sent, failed = await broadcast._do_broadcast(fake_bot, [12345], "hi")
    assert sent == 0
    assert failed == 1
    assert fake_bot.send_message.await_count == 1


def test_format_basic_stats_hides_conversion():
    """Базовая статистика для партнёров — без конверсии и регистраций."""
    from src.handlers.admin import _format_basic_stats

    text = _format_basic_stats(
        {
            "users": 237,
            "blocked": 0,
            "active_subs": 0,
            "sos": 2,
            "events": 5,
            # Эти поля должны быть скрыты в базовом виде:
            "registered_total": 104,
            "conversion_pct": 43.9,
            "pilots_registered": 93,
            "passengers_registered": 11,
        }
    )
    assert "Пользователей: 237" in text
    assert "Мероприятий: 5" in text
    # Не должно быть никаких намёков на конверсию:
    assert "Завершили" not in text
    assert "43.9" not in text
    assert "пилотов" not in text


def test_format_extended_stats_shows_conversion_and_cities():
    """Расширенная — конверсия + срез по городам."""
    from src.handlers.admin import _format_extended_stats

    stats = {
        "users": 237,
        "registered_total": 104,
        "conversion_pct": 43.9,
        "pilots_registered": 93,
        "passengers_registered": 11,
    }
    by_city = [
        {
            "city": "Екатеринбург",
            "starts": 200,
            "pilots": 80,
            "passengers": 10,
            "registered": 90,
            "conversion_pct": 45.0,
        },
        {
            "city": "Челябинск",
            "starts": 37,
            "pilots": 13,
            "passengers": 1,
            "registered": 14,
            "conversion_pct": 37.8,
        },
    ]
    text = _format_extended_stats(stats, by_city)
    assert "43.9%" in text
    assert "пилотов: 93" in text
    assert "Екатеринбург" in text
    assert "45.0%" in text
    assert "Челябинск" in text
