"""Telegram platform adapter using aiogram."""

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.enums import ParseMode

from src.platforms.base import (
    PlatformAdapter,
    KeyboardRow,
    ButtonType,
)
from src.config import get_settings


def _build_inline_keyboard(rows: list[KeyboardRow]) -> InlineKeyboardMarkup | None:
    if not rows:
        return None
    kb_rows = []
    for row in rows:
        kb_buttons = []
        for btn in row:
            if btn.type == ButtonType.CALLBACK:
                kb_buttons.append(
                    InlineKeyboardButton(text=btn.text, callback_data=btn.payload or btn.text)
                )
            elif btn.type == ButtonType.URL:
                kb_buttons.append(InlineKeyboardButton(text=btn.text, url=btn.url or ""))
        if kb_buttons:
            kb_rows.append(kb_buttons)
    return InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None


class TelegramAdapter(PlatformAdapter):
    def __init__(self, token: str | None = None):
        self._token = token or get_settings().telegram_bot_token
        if not self._token:
            raise ValueError("Telegram bot token is required")
        self._bot = Bot(token=self._token)

    @property
    def platform_name(self) -> str:
        return "telegram"

    @property
    def bot(self) -> Bot:
        return self._bot

    async def send_message(
        self,
        chat_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
        parse_mode: str | None = "HTML",
    ):
        kb = _build_inline_keyboard(keyboard) if keyboard else None
        return await self._bot.send_message(
            chat_id=int(chat_id),
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML if parse_mode == "HTML" else ParseMode.MARKDOWN,
        )

    async def send_photo(
        self,
        chat_id: str,
        photo_file_id: str,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ):
        kb = _build_inline_keyboard(keyboard) if keyboard else None
        return await self._bot.send_photo(
            chat_id=int(chat_id),
            photo=photo_file_id,
            caption=caption,
            reply_markup=kb,
        )

    async def send_photo_bytes(
        self,
        chat_id: str,
        photo_bytes: bytes,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ):
        kb = _build_inline_keyboard(keyboard) if keyboard else None
        from aiogram.types import BufferedInputFile

        return await self._bot.send_photo(
            chat_id=int(chat_id),
            photo=BufferedInputFile(photo_bytes, filename="photo.jpg"),
            caption=caption,
            reply_markup=kb,
        )

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
    ):
        kb = _build_inline_keyboard(keyboard) if keyboard else None
        return await self._bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(message_id),
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    async def request_contact(self, chat_id: str, text: str):
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить мой номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        return await self._bot.send_message(
            chat_id=int(chat_id),
            text=text,
            reply_markup=kb,
        )

    async def request_location(self, chat_id: str, text: str):
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Отправить геолокацию", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        return await self._bot.send_message(
            chat_id=int(chat_id),
            text=text,
            reply_markup=kb,
        )

    async def answer_callback(self, callback_id: str, text: str | None = None):
        # callback_id in Telegram is the callback_query id
        await self._bot.answer_callback_query(
            callback_query_id=callback_id,
            text=text,
        )

    async def get_file_url(self, file_id: str) -> str:
        file = await self._bot.get_file(file_id)
        return self._bot.session.api.file_url(file.file_path)
