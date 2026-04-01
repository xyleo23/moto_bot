"""Редактирование текста по callback: если сообщение с фото, edit_text недоступен."""

from loguru import logger
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery


def _edit_kwargs(reply_markup, parse_mode):
    kw = {"reply_markup": reply_markup}
    if parse_mode is not None:
        kw["parse_mode"] = parse_mode
    return kw


async def edit_text_or_send_new(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
    parse_mode=None,
) -> None:
    """Сначала edit_text или edit_caption (для сообщений с фото); при ошибке — новое сообщение."""
    msg = callback.message
    kw = _edit_kwargs(reply_markup, parse_mode)
    try:
        if msg.photo:
            await msg.edit_caption(caption=text, **kw)
        else:
            await msg.edit_text(text, **kw)
    except TelegramBadRequest as e:
        desc = (e.message or "").lower()
        if "message is not modified" in desc:
            return
        logger.warning("edit_text_or_send_new primary edit failed: {}", e)
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass
        try:
            await callback.bot.send_message(
                msg.chat.id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest as e2:
            logger.warning("edit_text_or_send_new send_message failed: {}", e2)
