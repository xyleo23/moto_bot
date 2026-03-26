"""Редактирование текста по callback: если сообщение с фото, edit_text недоступен."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery


async def edit_text_or_send_new(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup=None,
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await callback.bot.send_message(
            callback.message.chat.id,
            text,
            reply_markup=reply_markup,
        )
