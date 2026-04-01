"""Уведомления суперадминов и админов городов в Telegram и MAX (одна БД — данные уже «синхронны»)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from src.config import get_settings
from src.models.base import get_session_factory
from src.models.user import Platform, User

if TYPE_CHECKING:
    pass


def tg_inline_markup_to_max_rows(markup: Any) -> list | None:
    """Конвертация Telegram InlineKeyboardMarkup → клавиатура MAX (callback payload = callback_data)."""
    if markup is None:
        return None
    try:
        from aiogram.types import InlineKeyboardMarkup
        from src.platforms.base import Button, ButtonType

        if not isinstance(markup, InlineKeyboardMarkup):
            return None
        rows: list = []
        for row in markup.inline_keyboard or []:
            btns = []
            for b in row:
                cb = getattr(b, "callback_data", None)
                if cb:
                    btns.append(Button(text=b.text, payload=cb))
                else:
                    url = getattr(b, "url", None)
                    if url:
                        btns.append(Button(text=b.text, type=ButtonType.URL, url=url))
            if btns:
                rows.append(btns)
        return rows or None
    except Exception as e:
        logger.debug("tg_inline_markup_to_max_rows: %s", e)
        return None


async def _tg_notify_superadmin(
    telegram_bot: Any,
    chat_id: int,
    html: str,
    *,
    telegram_markup: Any | None,
    telegram_parse_mode: str | None,
    photo_file_id: str | None,
) -> None:
    """Одно уведомление суперадмину в Telegram (текст или фото+подпись)."""
    pm = telegram_parse_mode
    if photo_file_id:
        await telegram_bot.send_photo(
            chat_id,
            photo_file_id,
            caption=html,
            reply_markup=telegram_markup,
            parse_mode=pm,
        )
    else:
        await telegram_bot.send_message(
            chat_id,
            html,
            reply_markup=telegram_markup,
            parse_mode=pm,
        )


async def notify_superadmins_multichannel(
    html: str,
    *,
    telegram_markup: Any | None = None,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
    telegram_parse_mode: str | None = None,
    photo_file_id: str | None = None,
) -> None:
    """Для каждого ID из SUPERADMIN_IDS: если в БД есть User — пишем в его платформу; иначе fallback в Telegram."""
    settings = get_settings()
    if not settings.superadmin_ids:
        return
    max_rows = tg_inline_markup_to_max_rows(telegram_markup)
    session_factory = get_session_factory()

    for sid in settings.superadmin_ids:
        async with session_factory() as session:
            r = await session.execute(select(User).where(User.platform_user_id == sid))
            matches = list(r.scalars().all())
        if not matches:
            if telegram_bot:
                try:
                    await _tg_notify_superadmin(
                        telegram_bot,
                        sid,
                        html,
                        telegram_markup=telegram_markup,
                        telegram_parse_mode=telegram_parse_mode,
                        photo_file_id=photo_file_id,
                    )
                except Exception as e:
                    logger.warning("notify_superadmin sid=%s TG fallback: %s", sid, e)
            continue
        for u in matches:
            if u.platform == Platform.TELEGRAM and telegram_bot:
                try:
                    await _tg_notify_superadmin(
                        telegram_bot,
                        u.platform_user_id,
                        html,
                        telegram_markup=telegram_markup,
                        telegram_parse_mode=telegram_parse_mode,
                        photo_file_id=photo_file_id,
                    )
                except Exception as e:
                    logger.warning(
                        "notify_superadmin TG uid=%s: %s", u.platform_user_id, e
                    )
            elif u.platform == Platform.MAX and max_adapter:
                try:
                    if photo_file_id:
                        from src.services.cross_platform_notify import (
                            max_send_message_with_optional_profile_photo,
                        )

                        await max_send_message_with_optional_profile_photo(
                            max_adapter,
                            str(u.platform_user_id),
                            html,
                            max_rows,
                            photo_file_id,
                            telegram_bot,
                        )
                    else:
                        await max_adapter.send_message(
                            str(u.platform_user_id), html, max_rows
                        )
                except Exception as e:
                    logger.warning(
                        "notify_superadmin MAX uid=%s: %s", u.platform_user_id, e
                    )


async def notify_superadmins_plain(
    html: str,
    *,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
) -> None:
    await notify_superadmins_multichannel(
        html,
        telegram_markup=None,
        telegram_bot=telegram_bot,
        max_adapter=max_adapter,
    )


async def notify_superadmins_same_platform(
    html: str,
    source_platform: Platform,
    *,
    photo_file_id: str | None = None,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
    telegram_markup: Any | None = None,
) -> None:
    """
    Уведомить суперадминов только на той платформе, откуда пришёл репорт (TG → TG, MAX → MAX).
    Если в БД нет записи User для sid, для Telegram используется отправка на numeric sid (как fallback).
    """
    settings = get_settings()
    if not settings.superadmin_ids:
        return
    max_rows = tg_inline_markup_to_max_rows(telegram_markup)
    session_factory = get_session_factory()

    for sid in settings.superadmin_ids:
        async with session_factory() as session:
            r = await session.execute(select(User).where(User.platform_user_id == sid))
            matches = list(r.scalars().all())
        if not matches:
            if source_platform == Platform.TELEGRAM and telegram_bot:
                try:
                    if photo_file_id:
                        await telegram_bot.send_photo(
                            sid,
                            photo_file_id,
                            caption=html,
                            reply_markup=telegram_markup,
                            parse_mode="HTML",
                        )
                    else:
                        await telegram_bot.send_message(
                            sid,
                            html,
                            reply_markup=telegram_markup,
                            parse_mode="HTML",
                        )
                except Exception as e:
                    logger.warning("notify_superadmin_same_platform fallback sid=%s: %s", sid, e)
            continue
        for u in matches:
            if u.platform != source_platform:
                continue
            if u.platform == Platform.TELEGRAM and telegram_bot:
                try:
                    if photo_file_id:
                        await telegram_bot.send_photo(
                            u.platform_user_id,
                            photo_file_id,
                            caption=html,
                            reply_markup=telegram_markup,
                            parse_mode="HTML",
                        )
                    else:
                        await telegram_bot.send_message(
                            u.platform_user_id,
                            html,
                            reply_markup=telegram_markup,
                            parse_mode="HTML",
                        )
                except Exception as e:
                    logger.warning(
                        "notify_superadmin_same_platform TG uid=%s: %s",
                        u.platform_user_id,
                        e,
                    )
            elif u.platform == Platform.MAX and max_adapter:
                try:
                    if photo_file_id:
                        from src.services.cross_platform_notify import (
                            max_send_message_with_optional_profile_photo,
                        )

                        await max_send_message_with_optional_profile_photo(
                            max_adapter,
                            str(u.platform_user_id),
                            html,
                            max_rows,
                            photo_file_id,
                            telegram_bot,
                        )
                    else:
                        await max_adapter.send_message(
                            str(u.platform_user_id), html, max_rows
                        )
                except Exception as e:
                    logger.warning(
                        "notify_superadmin_same_platform MAX uid=%s: %s",
                        u.platform_user_id,
                        e,
                    )


async def notify_city_admins_multichannel(
    city_id: UUID,
    html: str,
    *,
    telegram_markup: Any | None = None,
    telegram_bot: Any | None = None,
    max_adapter: Any | None = None,
) -> None:
    """Рассылка админам города с учётом платформы записи User."""
    from src.services.admin_service import get_city_admins

    max_rows = tg_inline_markup_to_max_rows(telegram_markup)
    admins = await get_city_admins(city_id)
    for _, admin_user in admins:
        if admin_user.platform == Platform.TELEGRAM and telegram_bot:
            try:
                await telegram_bot.send_message(
                    admin_user.platform_user_id, html, reply_markup=telegram_markup
                )
            except Exception as e:
                logger.warning(
                    "notify_city_admin TG uid=%s: %s", admin_user.platform_user_id, e
                )
        elif admin_user.platform == Platform.MAX and max_adapter:
            try:
                await max_adapter.send_message(
                    str(admin_user.platform_user_id), html, max_rows
                )
            except Exception as e:
                logger.warning(
                    "notify_city_admin MAX uid=%s: %s", admin_user.platform_user_id, e
                )
