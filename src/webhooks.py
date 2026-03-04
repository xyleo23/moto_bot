"""Webhook handlers for YooKassa and MAX."""
# YooKassa sends POST to /webhook/yookassa with payment status
# When payment succeeds, call activate_subscription or update event/profile

async def handle_yookassa_webhook(request):
    """Handle YooKassa notification. Mount on /webhook/yookassa."""
    # TODO: Verify signature, parse event, activate subscription
    return {"status": "ok"}
