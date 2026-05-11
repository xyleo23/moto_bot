"""Webhook handler tests (unit, mocked)."""

import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.webhooks import handle_health

_TEST_SECRET = "test_key"


def _yookassa_headers(body: bytes, secret: str = _TEST_SECRET) -> dict:
    """X-Content-Signature for YooKassa HMAC-SHA256 body signing."""
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"X-Content-Signature": sig}


def _webhook_settings(**kwargs):
    mock_s = MagicMock()
    mock_s.yookassa_secret_key = kwargs.get("yookassa_secret_key", _TEST_SECRET)
    mock_s.webhook_trust_proxy = kwargs.get("webhook_trust_proxy", False)
    mock_s.webhook_require_signature = kwargs.get("webhook_require_signature", True)
    return mock_s


def _read_json(resp):
    """Read JSON from aiohttp web.Response."""
    body = getattr(resp, "_body", None) or getattr(resp, "body", None)
    if body is not None:
        return json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
    return json.loads(resp.text) if hasattr(resp, "text") else {}


@pytest.mark.asyncio
async def test_health_endpoint_ok():
    """Health returns 200 when DB is reachable."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    inner = MagicMock(return_value=mock_cm)
    mock_factory = MagicMock(return_value=inner)

    with patch("src.webhooks.get_session_factory", mock_factory):
        req = AsyncMock()
        resp = await handle_health(req)
        assert resp.status == 200
        body = _read_json(resp)
        assert body.get("status") == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_degraded():
    """Health returns 503 when DB fails."""
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(side_effect=Exception("DB unreachable"))
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    inner = MagicMock(return_value=mock_cm)
    mock_factory = MagicMock(return_value=inner)

    with patch("src.webhooks.get_session_factory", mock_factory):
        req = AsyncMock()
        resp = await handle_health(req)
        assert resp.status == 503
        body = _read_json(resp)
        assert body.get("status") == "degraded"


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_json():
    """Webhook returns 400 for malformed body after valid signature."""
    from src.webhooks import handle_yookassa_webhook

    raw = b"not json"
    request = AsyncMock()
    request.read = AsyncMock(return_value=raw)
    request.headers = _yookassa_headers(raw)
    request.remote = "185.71.76.1"

    with patch("src.webhooks.get_settings", return_value=_webhook_settings()):
        status, body = await handle_yookassa_webhook(request)
    assert status == 400
    assert "error" in body


@pytest.mark.asyncio
async def test_webhook_ignores_non_succeeded():
    """Webhook should ignore non-payment.succeeded events."""
    import json
    from src.webhooks import handle_yookassa_webhook

    payload = json.dumps(
        {
            "event": "payment.canceled",
            "object": {"id": "pay_123"},
        }
    ).encode()
    request = AsyncMock()
    request.read = AsyncMock(return_value=payload)
    request.headers = _yookassa_headers(payload)
    request.remote = "185.71.76.1"

    with patch("src.webhooks.get_settings", return_value=_webhook_settings()):
        status, body = await handle_yookassa_webhook(request)
    assert status == 200
    assert body.get("status") == "ignored"


@pytest.mark.asyncio
async def test_webhook_rejects_without_signature_when_required():
    """With webhook_require_signature=True, missing signature returns 401."""
    import json
    from src.webhooks import handle_yookassa_webhook

    payload = json.dumps({"event": "payment.canceled", "object": {"id": "pay_1"}}).encode()
    request = AsyncMock()
    request.read = AsyncMock(return_value=payload)
    request.headers = {}
    request.remote = "185.71.76.1"

    with patch("src.webhooks.get_settings", return_value=_webhook_settings(webhook_require_signature=True)):
        status, body = await handle_yookassa_webhook(request)
    assert status == 401
    assert body.get("error") == "Unauthorized"


@pytest.mark.asyncio
async def test_webhook_trust_proxy_x_real_ip():
    """Behind nginx: WEBHOOK_TRUST_PROXY uses X-Real-IP for YooKassa range check."""
    import json
    from src.webhooks import handle_yookassa_webhook

    payload = json.dumps(
        {
            "event": "payment.canceled",
            "object": {"id": "pay_123"},
        }
    ).encode()
    request = AsyncMock()
    request.read = AsyncMock(return_value=payload)
    request.headers = {**_yookassa_headers(payload), "X-Real-IP": "185.71.76.1"}
    request.remote = "127.0.0.1"

    with patch("src.webhooks.get_settings", return_value=_webhook_settings(webhook_trust_proxy=True)):
        status, body = await handle_yookassa_webhook(request)
    assert status == 200
    assert body.get("status") == "ignored"


# ── MAX webhook ──────────────────────────────────────────────────────────────


def _max_settings(secret: str | None = "s3cret", url: str | None = None):
    s = MagicMock()
    s.max_webhook_secret = secret
    s.max_webhook_url = url or (
        f"https://example.com/webhook/max/{secret}" if secret else None
    )
    return s


@pytest.mark.asyncio
async def test_max_webhook_rejects_wrong_secret():
    from src.webhooks import handle_max_webhook

    request = AsyncMock()
    request.headers = {}
    request.match_info = {"secret": "wrong"}
    request.json = AsyncMock(return_value={"update_type": "message_created"})

    with patch("src.webhooks.get_settings", return_value=_max_settings()):
        resp = await handle_max_webhook(request)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_max_webhook_rejects_when_secret_not_configured():
    from src.webhooks import handle_max_webhook

    request = AsyncMock()
    request.headers = {}
    request.match_info = {"secret": "any"}
    request.json = AsyncMock(return_value={})

    with patch(
        "src.webhooks.get_settings",
        return_value=_max_settings(secret=None, url=None),
    ):
        resp = await handle_max_webhook(request)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_max_webhook_accepts_valid_secret_and_dispatches():
    from src import webhooks
    from src.webhooks import handle_max_webhook, set_max_webhook_adapter

    payload = {"update_type": "message_created", "timestamp": 1, "message": {}}
    request = AsyncMock()
    request.headers = {}
    request.match_info = {"secret": "s3cret"}
    request.json = AsyncMock(return_value=payload)

    adapter = MagicMock()
    set_max_webhook_adapter(adapter)

    captured = {}

    async def fake_process(adapter_arg, payload_arg):
        captured["adapter"] = adapter_arg
        captured["payload"] = payload_arg

    with patch("src.webhooks.get_settings", return_value=_max_settings()), \
         patch("src.max_runner.process_max_update", new=fake_process):
        resp = await handle_max_webhook(request)
        # Background task scheduled by handler — let it run.
        import asyncio
        await asyncio.sleep(0)

    assert resp.status == 200
    assert captured.get("adapter") is adapter
    assert captured.get("payload") == payload
    # Cleanup module-level state to avoid leaking into other tests.
    webhooks.handle_max_webhook._adapter = None


@pytest.mark.asyncio
async def test_max_webhook_accepts_secret_via_header():
    """Пакет 15k, пункт М: секрет в заголовке X-MAX-Webhook-Secret."""
    from src.webhooks import handle_max_webhook

    request = AsyncMock()
    request.headers = {"X-MAX-Webhook-Secret": "s3cret"}
    request.match_info = {}
    request.json = AsyncMock(return_value={})

    with patch("src.webhooks.get_settings", return_value=_max_settings()):
        resp = await handle_max_webhook(request)
    # Auth OK → 200 no_adapter (adapter не зарегистрирован).
    assert resp.status == 200


@pytest.mark.asyncio
async def test_max_webhook_rejects_wrong_header_secret():
    from src.webhooks import handle_max_webhook

    request = AsyncMock()
    request.headers = {"X-MAX-Webhook-Secret": "wrong"}
    request.match_info = {}
    request.json = AsyncMock(return_value={})

    with patch("src.webhooks.get_settings", return_value=_max_settings()):
        resp = await handle_max_webhook(request)
    assert resp.status == 401


@pytest.mark.asyncio
async def test_max_webhook_secret_derived_from_url_tail():
    """If max_webhook_secret is empty, last URL segment is used."""
    from src.webhooks import handle_max_webhook

    request = AsyncMock()
    request.headers = {}
    request.match_info = {"secret": "abc123"}
    request.json = AsyncMock(return_value={})

    settings_mock = _max_settings(
        secret=None, url="https://example.com/webhook/max/abc123"
    )
    with patch("src.webhooks.get_settings", return_value=settings_mock):
        resp = await handle_max_webhook(request)
    # Adapter not set → 200 no_adapter (means auth passed).
    assert resp.status == 200
