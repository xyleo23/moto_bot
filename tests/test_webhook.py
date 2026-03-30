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
