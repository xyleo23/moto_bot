"""Уведомления участников мероприятия на всех платформах (TG + MAX)."""

import uuid

from loguru import logger

from src.models.user import Platform


async def notify_event_participants_cancelled(
    participant_canonical_user_ids: list[uuid.UUID],
    message_text: str,
    *,
    telegram_bot=None,
    max_adapter=None,
) -> None:
    """
    Рассылает текст каждому участнику по всем привязанным аккаунтам (Telegram и MAX).
    participant_canonical_user_ids — значения EventRegistration.user_id (канонический user id).
    """
    from src.services.user import get_all_platform_identities

    for uid in participant_canonical_user_ids:
        try:
            identities = await get_all_platform_identities(uid)
        except Exception as e:
            logger.warning("notify_event_cancel: get_all_platform_identities %s: %s", uid, e)
            continue
        for ident in identities:
            if ident.is_blocked:
                continue
            try:
                if ident.platform == Platform.TELEGRAM and telegram_bot:
                    await telegram_bot.send_message(ident.platform_user_id, message_text)
                elif ident.platform == Platform.MAX and max_adapter:
                    await max_adapter.send_message(str(ident.platform_user_id), message_text)
            except Exception as e:
                logger.warning(
                    "notify_event_cancel: user_id=%s platform=%s err=%s",
                    ident.platform_user_id,
                    ident.platform,
                    e,
                )
