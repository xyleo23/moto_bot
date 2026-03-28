"""Webhook handler tests (unit, mocked)."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.webhooks import handle_health


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
    """Webhook returns 400 for malformed body when the request is from YooKassa IP."""
    from src.webhooks import handle_yookassa_webhook

    request = AsyncMock()
    request.read = AsyncMock(return_value=b"not json")
    request.headers = {}
    # Without trusted IP/signature the handler rejects before JSON parse (401).
    request.remote = "185.71.76.1"  # YooKassa range — same as test_webhook_ignores_non_succeeded

    status, body = await handle_yookassa_webhook(request)
    assert status == 400
    assert "error" in body


@pytest.mark.asyncio
async def test_webhook_ignores_non_succeeded():
    """Webhook should ignore non-payment.succeeded events."""
    import json
    from src.webhooks import handle_yookassa_webhook

    request = AsyncMock()
    request.read = AsyncMock(
        return_value=json.dumps(
            {
                "event": "payment.canceled",
                "object": {"id": "pay_123"},
            }
        ).encode()
    )
    request.headers = {}
    request.remote = "185.71.76.1"  # YooKassa IP

    status, body = await handle_yookassa_webhook(request)
    assert status == 200
    assert body.get("status") == "ignored"


@pytest.mark.asyncio
async def test_webhook_trust_proxy_x_real_ip():
    """Behind nginx: WEBHOOK_TRUST_PROXY uses X-Real-IP for YooKassa range check."""
    import json
    from src.webhooks import handle_yookassa_webhook

    request = AsyncMock()
    request.read = AsyncMock(
        return_value=json.dumps(
            {
                "event": "payment.canceled",
                "object": {"id": "pay_123"},
            }
        ).encode()
    )
    request.headers = {"X-Real-IP": "185.71.76.1"}
    request.remote = "127.0.0.1"

    with patch("src.webhooks.get_settings") as gs:
        mock_s = MagicMock()
        mock_s.yookassa_secret_key = "test_key"
        mock_s.webhook_trust_proxy = True
        gs.return_value = mock_s

        status, body = await handle_yookassa_webhook(request)
    assert status == 200
    assert body.get("status") == "ignored"
