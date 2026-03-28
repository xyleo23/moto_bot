"""Доставка уведомлений на все привязанные аккаунты пользователя (TG + MAX)."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.models.user import Platform
from src.services.user import get_all_platform_identities

if TYPE_CHECKING:
    pass


async def max_send_message_with_optional_profile_photo(
    max_adapter: Any,
    chat_id: str,
    caption: str,
    keyboard: list | None,
    photo_ref: str | None,
    telegram_bot: Any | None,
) -> None:
    """MAX: картинка + подпись; file_id из Telegram подгружается через API MAX и мост TG→MAX."""
    max_body = caption or ""
    if not photo_ref:
        await max_adapter.send_message(chat_id, max_body, keyboard)
        return
    try:
        await max_adapter.send_photo(chat_id, photo_ref, max_body, keyboard)
        return
    except Exception as e:
        logger.info(
            "MAX send_photo with profile ref failed, try TG→MAX bridge: %s",
            e,
        )
    token = None
    if telegram_bot:
        token = await max_adapter.import_photo_from_telegram(telegram_bot, photo_ref)
    if token:
        for delay in (0.35, 0.9, 1.8):
            await asyncio.sleep(delay)
            try:
                await max_adapter.send_photo(chat_id, token, max_body, keyboard)
                return
            except Exception as e2:
                err = str(e2).lower()
                if "not.ready" in err or "not.processed" in err:
                    logger.debug("MAX attachment not ready, retry: %s", e2)
                    continue
                logger.warning("MAX send_photo after upload failed: %s", e2)
                break
    await max_adapter.send_message(chat_id, max_body, keyboard)


async def send_text_to_all_identities(
    canonical_user_id: uuid.UUID,
    text: str,
    *,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
    tg_reply_markup: Any | None = None,
    max_kb_rows: list | None = None,
    parse_mode: str | None = "HTML",
    max_extra_html: str | None = None,
    photo_file_id: str | None = None,
) -> None:
    """Отправить текст (и опционально фото анкеты) каждой записи User для канонического id."""
    identities = await get_all_platform_identities(canonical_user_id)
    if not identities:
        return
    max_body = (text or "") + (max_extra_html or "")
    for u in identities:
        if u.platform == Platform.TELEGRAM and telegram_bot:
            try:
                if photo_file_id:
                    await telegram_bot.send_photo(
                        u.platform_user_id,
                        photo_file_id,
                        caption=text,
                        reply_markup=tg_reply_markup,
                        parse_mode=parse_mode or "HTML",
                    )
                else:
                    await telegram_bot.send_message(
                        u.platform_user_id,
                        text,
                        reply_markup=tg_reply_markup,
                        parse_mode=parse_mode,
                    )
            except Exception as e:
                logger.warning("cross_notify TG uid=%s: %s", u.platform_user_id, e)
        elif u.platform == Platform.MAX and max_adapter:
            try:
                await max_send_message_with_optional_profile_photo(
                    max_adapter,
                    str(u.platform_user_id),
                    max_body,
                    max_kb_rows,
                    photo_file_id,
                    telegram_bot,
                )
            except Exception as e:
                logger.warning("cross_notify MAX uid=%s: %s", u.platform_user_id, e)


async def notify_like_received_cross_platform(
    canonical_target_id: uuid.UUID,
    notify_text: str,
    from_photo: str | None,
    *,
    telegram_bot: Any | None,
    max_adapter: Any | None,
    tg_reply_markup: Any | None = None,
    max_kb_rows: list | None = None,
    max_extra_html: str | None = None,
) -> None:
    """Лайк получен: TG — send_photo с file_id; MAX — нативный токен или мост из Telegram."""
    identities = await get_all_platform_identities(canonical_target_id)
    max_body = (notify_text or "") + (max_extra_html or "")
    for u in identities:
        if u.platform == Platform.TELEGRAM and telegram_bot:
            try:
                if from_photo:
                    await telegram_bot.send_photo(
                        u.platform_user_id,
                        from_photo,
                        caption=notify_text,
                        reply_markup=tg_reply_markup,
                        parse_mode="HTML",
                    )
                else:
                    await telegram_bot.send_message(
                        u.platform_user_id,
                        notify_text,
                        reply_markup=tg_reply_markup,
                        parse_mode="HTML",
                    )
            except Exception as e:
                logger.warning("like_received TG uid=%s: %s", u.platform_user_id, e)
        elif u.platform == Platform.MAX and max_adapter:
            try:
                await max_send_message_with_optional_profile_photo(
                    max_adapter,
                    str(u.platform_user_id),
                    max_body,
                    max_kb_rows,
                    from_photo,
                    telegram_bot,
                )
            except Exception as e:
                logger.warning("like_received MAX uid=%s: %s", u.platform_user_id, e)
