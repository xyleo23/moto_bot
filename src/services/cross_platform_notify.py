"""Доставка уведомлений на все привязанные аккаунты пользователя (TG + MAX)."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.models.user import Platform
from src.services.user import get_all_platform_identities

if TYPE_CHECKING:
    pass


async def send_text_to_all_identities(
    canonical_user_id: uuid.UUID,
    text: str,
    *,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
    tg_reply_markup: Any | None = None,
    max_kb_rows: list | None = None,
    parse_mode: str | None = "HTML",
) -> None:
    """Отправить текст каждой записи User для данного канонического id."""
    identities = await get_all_platform_identities(canonical_user_id)
    if not identities:
        return
    for u in identities:
        if u.platform == Platform.TELEGRAM and telegram_bot:
            try:
                await telegram_bot.send_message(
                    u.platform_user_id,
                    text,
                    reply_markup=tg_reply_markup,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                logger.warning(
                    "cross_notify TG uid=%s: %s", u.platform_user_id, e
                )
        elif u.platform == Platform.MAX and max_adapter:
            try:
                await max_adapter.send_message(
                    str(u.platform_user_id),
                    text,
                    max_kb_rows,
                )
            except Exception as e:
                logger.warning(
                    "cross_notify MAX uid=%s: %s", u.platform_user_id, e
                )


async def notify_like_received_cross_platform(
    canonical_target_id: uuid.UUID,
    notify_text: str,
    from_photo: str | None,
    *,
    telegram_bot: Any | None,
    max_adapter: Any | None,
    tg_reply_markup: Any | None = None,
    max_kb_rows: list | None = None,
) -> None:
    """Лайк получен: в TG — фото+подпись при наличии file_id; в MAX — только текст."""
    identities = await get_all_platform_identities(canonical_target_id)
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
                logger.warning(
                    "like_received TG uid=%s: %s", u.platform_user_id, e
                )
        elif u.platform == Platform.MAX and max_adapter:
            try:
                await max_adapter.send_message(
                    str(u.platform_user_id),
                    notify_text,
                    max_kb_rows,
                )
            except Exception as e:
                logger.warning(
                    "like_received MAX uid=%s: %s", u.platform_user_id, e
                )
