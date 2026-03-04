"""MAX messenger platform adapter."""
import asyncio
import json
from typing import Any

import aiohttp

from src.platforms.base import (
    PlatformAdapter,
    Button,
    KeyboardRow,
    ButtonType,
)
from src.config import get_settings


def _build_max_keyboard(rows: list[KeyboardRow]) -> list | None:
    if not rows:
        return None
    max_rows = []
    for row in rows:
        max_buttons = []
        for btn in row:
            if btn.type == ButtonType.CALLBACK:
                max_buttons.append({
                    "type": "callback",
                    "text": btn.text,
                    "payload": btn.payload or btn.text,
                })
            elif btn.type == ButtonType.URL:
                max_buttons.append({
                    "type": "link",
                    "text": btn.text,
                    "url": btn.url or "",
                })
            elif btn.type == ButtonType.REQUEST_CONTACT:
                max_buttons.append({
                    "type": "request_contact",
                    "text": btn.text,
                })
            elif btn.type == ButtonType.REQUEST_LOCATION:
                max_buttons.append({
                    "type": "request_geo_location",
                    "text": btn.text,
                })
        if max_buttons:
            max_rows.append(max_buttons)
    return max_rows if max_rows else None


class MaxAdapter(PlatformAdapter):
    """MAX messenger adapter using platform-api.max.ru."""

    def __init__(self, token: str | None = None, base_url: str | None = None):
        settings = get_settings()
        self._token = token or settings.max_bot_token
        self._base_url = (base_url or settings.max_api_base).rstrip("/")
        if not self._token:
            raise ValueError("MAX bot token is required")
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self._headers())
        return self._session

    @property
    def platform_name(self) -> str:
        return "max"

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session()
        url = f"{self._base_url}{path}"
        kwargs = {"params": params} if params else {}
        if json_data is not None:
            kwargs["json"] = json_data
        async with session.request(method, url, **kwargs) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"MAX API error {resp.status}: {text}")
            if resp.status == 204:
                return {}
            return await resp.json()

    async def send_message(
        self,
        chat_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
        parse_mode: str | None = "HTML",
    ):
        attachments = []
        max_kb = _build_max_keyboard(keyboard) if keyboard else None
        if max_kb:
            attachments.append({
                "type": "inline_keyboard",
                "payload": {"buttons": max_kb},
            })
        body = {"text": text}
        if attachments:
            body["attachments"] = attachments
        if parse_mode:
            body["format"] = parse_mode.lower()
        return await self._request(
            "POST",
            f"/messages?user_id={chat_id}",
            json_data=body,
        )

    async def send_photo(
        self,
        chat_id: str,
        photo_file_id: str,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ):
        # MAX may need different API for photo - check docs
        # Fallback: send as message with caption
        text = caption or ""
        return await self.send_message(chat_id, text or "[Фото]", keyboard)

    async def send_photo_bytes(
        self,
        chat_id: str,
        photo_bytes: bytes,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ):
        return await self.send_photo(chat_id, "", caption, keyboard)

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
    ):
        # MAX PATCH /messages/{messageId} - need chat context
        attachments = []
        if keyboard:
            max_kb = _build_max_keyboard(keyboard)
            if max_kb:
                attachments.append({
                    "type": "inline_keyboard",
                    "payload": {"buttons": max_kb},
                })
        body = {"text": text}
        if attachments:
            body["attachments"] = attachments
        return await self._request(
            "PATCH",
            f"/messages/{message_id}",
            json_data=body,
        )

    async def request_contact(self, chat_id: str, text: str):
        keyboard = [[Button("Отправить мой номер", type=ButtonType.REQUEST_CONTACT)]]
        return await self.send_message(chat_id, text, keyboard)

    async def request_location(self, chat_id: str, text: str):
        keyboard = [[Button("Отправить геолокацию", type=ButtonType.REQUEST_LOCATION)]]
        return await self.send_message(chat_id, text, keyboard)

    async def answer_callback(self, callback_id: str, text: str | None = None):
        # MAX: answer callback if supported
        pass

    async def get_file_url(self, file_id: str) -> str:
        # MAX file download - may need GET /files/{fileId}
        return ""

    async def poll_updates(self, marker: int | None = None, timeout: int = 30):
        """Long polling for updates."""
        params = {"timeout": timeout, "limit": 100}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
