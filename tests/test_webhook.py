"""Webhook handler tests (unit, mocked)."""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_json():
    """Webhook should return 400 for invalid JSON."""
    from src.webhooks import handle_yookassa_webhook

    request = AsyncMock()
    request.read = AsyncMock(return_value=b"not json")
    request.headers = {}
    request.remote = ""

    status, body = await handle_yookassa_webhook(request)
    assert status == 400
    assert "error" in body


@pytest.mark.asyncio
async def test_webhook_ignores_non_succeeded():
    """Webhook should ignore non-payment.succeeded events."""
    import json
    from src.webhooks import handle_yookassa_webhook

    request = AsyncMock()
    request.read = AsyncMock(return_value=json.dumps({
        "event": "payment.canceled",
        "object": {"id": "pay_123"},
    }).encode())
    request.headers = {}
    request.remote = "185.71.76.1"  # YooKassa IP

    status, body = await handle_yookassa_webhook(request)
    assert status == 200
    assert body.get("status") == "ignored"
