"""Security-related middleware tests."""

import html
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import fakeredis.aioredis as fakeredis
import pytest
from aiogram.types import CallbackQuery, Message

from src.handlers.middleware import BlockCheckMiddleware, RateLimitMiddleware
from src.services.motopair_service import get_profile_info_text
from src.services.report_service import maybe_auto_block_after_report


def _message_event(tg_uid: int = 42) -> Message:
    ev = MagicMock(spec=Message)
    ev.from_user = MagicMock()
    ev.from_user.id = tg_uid
    ev.text = ""
    return ev


@pytest.mark.asyncio
async def test_rate_limit_allows_normal_usage():
    redis = fakeredis.FakeRedis()
    mw = RateLimitMiddleware(redis)
    handler = AsyncMock(return_value="ok")
    event = _message_event()
    data: dict = {}
    for _ in range(29):
        await mw(handler, event, data)
    assert handler.call_count == 29


@pytest.mark.asyncio
async def test_rate_limit_blocks_flood():
    redis = fakeredis.FakeRedis()
    mw = RateLimitMiddleware(redis)
    handler = AsyncMock(return_value="ok")
    event = _message_event()
    data: dict = {}
    for _ in range(31):
        await mw(handler, event, data)
    assert handler.call_count == 30


@pytest.mark.asyncio
async def test_rate_limit_no_redis_allows_all():
    mw = RateLimitMiddleware(None)
    handler = AsyncMock(return_value="ok")
    event = _message_event()
    data: dict = {}
    for _ in range(50):
        await mw(handler, event, data)
    assert handler.call_count == 50


def _make_user(is_blocked: bool = False, block_reason=None):
    user = MagicMock()
    user.id = "test-uuid-123"
    user.is_blocked = is_blocked
    user.block_reason = block_reason
    return user


@pytest.mark.asyncio
async def test_block_check_allows_unblocked_user():
    mw = BlockCheckMiddleware()
    data: dict = {}
    event = _message_event()
    handler = AsyncMock(return_value="ok")
    with patch(
        "src.handlers.middleware.get_or_create_user",
        new_callable=AsyncMock,
        return_value=_make_user(is_blocked=False),
    ):
        await mw(handler, event, data)
    assert handler.call_count == 1


@pytest.mark.asyncio
async def test_block_check_blocks_blocked_user():
    mw = BlockCheckMiddleware()
    data: dict = {}
    event = MagicMock(spec=Message)
    event.from_user = MagicMock()
    event.from_user.id = 42
    event.text = ""
    event.answer = AsyncMock()
    handler = AsyncMock()
    with patch(
        "src.handlers.middleware.get_or_create_user",
        new_callable=AsyncMock,
        return_value=_make_user(is_blocked=True, block_reason="spam"),
    ):
        await mw(handler, event, data)
    assert handler.call_count == 0
    event.answer.assert_called_once()


@pytest.mark.asyncio
async def test_block_check_allows_sos_event():
    """SOS message bypasses block check — handler runs even if user is blocked."""
    mw = BlockCheckMiddleware()
    data: dict = {}
    event = MagicMock(spec=Message)
    event.text = "🚨 SOS"
    event.from_user = MagicMock()
    event.from_user.id = 7
    handler = AsyncMock(return_value="ok")
    with patch(
        "src.handlers.middleware.get_or_create_user",
        new_callable=AsyncMock,
        return_value=_make_user(is_blocked=True),
    ):
        await mw(handler, event, data)
    assert handler.call_count == 1


@pytest.mark.asyncio
async def test_block_check_callback_blocked_user():
    mw = BlockCheckMiddleware()
    data: dict = {}
    event = MagicMock(spec=CallbackQuery)
    event.from_user = MagicMock()
    event.from_user.id = 99
    event.data = ""
    event.answer = AsyncMock()
    handler = AsyncMock()
    with patch(
        "src.handlers.middleware.get_or_create_user",
        new_callable=AsyncMock,
        return_value=_make_user(is_blocked=True),
    ):
        await mw(handler, event, data)
    assert handler.call_count == 0
    event.answer.assert_called_once()


@pytest.mark.asyncio
async def test_profile_info_text_escapes_html_in_name():
    uid = uuid4()
    p = MagicMock()
    p.name = "<script>alert(1)</script>"
    p.age = 25
    p.bike_brand = "Y"
    p.bike_model = "Z"
    p.engine_cc = 600
    p.about = "ok"
    p.photo_file_id = None
    pilot_result = MagicMock()
    pilot_result.scalar_one_or_none.return_value = p
    session = MagicMock()
    session.execute = AsyncMock(return_value=pilot_result)
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx
    with patch("src.services.motopair_service.get_session_factory", return_value=factory):
        text, _ = await get_profile_info_text(uid)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


@pytest.mark.asyncio
async def test_profile_info_text_escapes_ampersand():
    uid = uuid4()
    p = MagicMock()
    p.name = "Moto & Bike <test>"
    p.age = 30
    p.bike_brand = "A"
    p.bike_model = "B"
    p.engine_cc = 800
    p.about = "x"
    p.photo_file_id = None
    pilot_result = MagicMock()
    pilot_result.scalar_one_or_none.return_value = p
    session = MagicMock()
    session.execute = AsyncMock(return_value=pilot_result)
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx
    with patch("src.services.motopair_service.get_session_factory", return_value=factory):
        text, _ = await get_profile_info_text(uid)
    assert "&amp;" in text
    assert "&lt;" in text


@pytest.mark.asyncio
async def test_profile_info_text_empty_about_returns_dash():
    uid = uuid4()
    p = MagicMock()
    p.name = "Ivan"
    p.age = 40
    p.bike_brand = "K"
    p.bike_model = "L"
    p.engine_cc = 400
    p.about = None
    p.photo_file_id = None
    pilot_result = MagicMock()
    pilot_result.scalar_one_or_none.return_value = p
    session = MagicMock()
    session.execute = AsyncMock(return_value=pilot_result)
    factory = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory.return_value = ctx
    with patch("src.services.motopair_service.get_session_factory", return_value=factory):
        text, _ = await get_profile_info_text(uid)
    assert "О себе: —" in text
    assert "None" not in text

    about = None
    result = html.escape(str(about)) if about else "—"
    assert result == "—"


@pytest.mark.asyncio
async def test_auto_block_triggers_at_threshold():
    uid = uuid4()
    with (
        patch(
            "src.services.report_service.get_report_count",
            new_callable=AsyncMock,
            return_value=5,
        ),
        patch(
            "src.services.report_service.get_settings_from_db",
            new_callable=AsyncMock,
        ) as mock_settings,
        patch(
            "src.services.report_service.auto_block_user",
            new_callable=AsyncMock,
        ) as mock_block,
        patch(
            "src.services.admin_multichannel_notify.notify_superadmins_multichannel",
            new_callable=AsyncMock,
        ),
    ):
        m = MagicMock()
        m.auto_block_reports_threshold = 5
        mock_settings.return_value = m
        await maybe_auto_block_after_report(uid, telegram_bot=MagicMock(), max_adapter=None)
    mock_block.assert_awaited_once_with(uid, reason="Авто-блокировка: 5 жалоб")


@pytest.mark.asyncio
async def test_auto_block_disabled_when_threshold_zero():
    uid = uuid4()
    with (
        patch(
            "src.services.report_service.get_report_count",
            new_callable=AsyncMock,
            return_value=10,
        ),
        patch(
            "src.services.report_service.get_settings_from_db",
            new_callable=AsyncMock,
        ) as mock_settings,
        patch(
            "src.services.report_service.auto_block_user",
            new_callable=AsyncMock,
        ) as mock_block,
    ):
        m = MagicMock()
        m.auto_block_reports_threshold = 0
        mock_settings.return_value = m
        await maybe_auto_block_after_report(uid, telegram_bot=None, max_adapter=None)
    mock_block.assert_not_called()
