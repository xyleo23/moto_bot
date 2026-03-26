"""MAX messenger platform adapter."""
import contextvars
import json
from typing import Any

import aiohttp
from loguru import logger

# When True, send_message uses chat_id param instead of user_id (for dialogs).
_max_use_chat_id_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "max_use_chat_id", default=False
)


def set_max_use_chat_id(value: bool) -> None:
    _max_use_chat_id_var.set(value)


def _get_msg_params(target: str) -> dict[str, int | str]:
    """MAX API expects integer for user_id/chat_id when numeric."""
    try:
        val = int(target)
    except (ValueError, TypeError):
        val = target
    if _max_use_chat_id_var.get():
        return {"chat_id": val}
    return {"user_id": val}


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
            elif btn.type == ButtonType.MESSAGE:
                # MAX: same field as label; client sends this text to the bot as a message
                max_buttons.append({
                    "type": "message",
                    "text": btn.text,
                })
        if max_buttons:
            max_rows.append(max_buttons)
    return max_rows if max_rows else None


def _extract_max_upload_token(parsed: Any) -> str | None:
    """Parse token from MAX POST-to-upload-url JSON (shape varies by CDN build)."""
    if isinstance(parsed, str) and len(parsed.strip()) > 8:
        return parsed.strip()
    if not isinstance(parsed, dict):
        return None
    for k in ("token", "fileToken", "file_token", "retval", "access_token", "photo_token"):
        v = parsed.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for nest in (
        "photo",
        "image",
        "file",
        "result",
        "data",
        "payload",
        "response",
        "body",
        "photos",
    ):
        sub = parsed.get(nest)
        if isinstance(sub, list) and sub:
            sub = sub[0]
        if isinstance(sub, dict):
            t = _extract_max_upload_token(sub)
            if t:
                return t
    return None


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
            "Authorization": self._token,
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
        kwargs: dict = {"params": params} if params else {}
        if json_data is not None:
            kwargs["json"] = json_data
        async with session.request(method, url, **kwargs) as resp:
            if resp.status >= 400:
                text = await resp.text()
                from loguru import logger
                logger.warning(f"MAX API error {resp.status}: {text[:500]}")
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
        params = _get_msg_params(chat_id)
        return await self._request(
            "POST",
            "/messages",
            params=params,
            json_data=body,
        )

    async def upload_image_bytes(self, data: bytes, filename: str = "photo.jpg") -> str | None:
        """Upload image to MAX CDN; returns attachment token for POST /messages or None."""
        if not data:
            return None
        try:
            r1 = await self._request("POST", "/uploads", params={"type": "image"})
        except Exception as e:
            logger.warning("MAX POST /uploads?type=image failed: {}", e)
            return None
        upload_url = r1.get("url") if isinstance(r1, dict) else None
        if not upload_url:
            logger.warning("MAX /uploads response missing url: {}", r1)
            return None

        # Determine content-type by filename extension
        ext = (filename or "").lower().rsplit(".", 1)[-1]
        ct_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                  "gif": "image/gif", "webp": "image/webp"}
        img_ct = ct_map.get(ext, "image/jpeg")

        # MAX API expects field name "data" for multipart uploads.
        form = aiohttp.FormData()
        form.add_field("data", data, filename=filename, content_type=img_ct)

        # IMPORTANT: do NOT pass Content-Type header manually — aiohttp sets
        # multipart/form-data with the correct boundary automatically.
        # Only pass the Authorization header; Content-Type must not be overridden.
        upload_headers = {"Authorization": self._token}
        try:
            async with aiohttp.ClientSession() as upload_session:
                async with upload_session.post(upload_url, data=form, headers=upload_headers) as resp:
                    raw = await resp.text()
                    logger.debug("MAX image upload status={} body={}", resp.status, raw[:500])
                    if resp.status >= 400:
                        logger.warning(
                            "MAX image upload HTTP {}: {}", resp.status, raw[:400]
                        )
                        return None
                    try:
                        parsed = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        logger.warning("MAX image upload non-JSON response: {!r}", raw[:500])
                        return None
                    token = _extract_max_upload_token(parsed)
                    if not token:
                        # Loguru: use {} / {!r} — NOT printf %s (it will print literally).
                        logger.warning(
                            "MAX image upload: no token. http_status={} raw={!r} parsed={}",
                            resp.status,
                            raw[:1200],
                            parsed,
                        )
                    return token
        except Exception as e:
            logger.warning("MAX multipart image upload failed: {}", e)
            return None

    async def import_photo_from_telegram(self, telegram_bot, tg_file_id: str) -> str | None:
        """Download a Telegram file_id and upload to MAX; returns MAX token or None."""
        if not telegram_bot or not tg_file_id:
            return None
        from src.config import get_settings

        token = get_settings().telegram_bot_token
        if not token:
            return None
        try:
            tg_file = await telegram_bot.get_file(tg_file_id)
            if not tg_file or not tg_file.file_path:
                logger.warning("import_photo_from_telegram: get_file returned empty for {}", tg_file_id)
                return None
            file_url = f"https://api.telegram.org/file/bot{token}/{tg_file.file_path}"
            async with aiohttp.ClientSession() as dl_session:
                async with dl_session.get(file_url) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "import_photo_from_telegram: TG download HTTP {} for file_id={}",
                            resp.status, tg_file_id,
                        )
                        return None
                    img_data = await resp.read()
            if not img_data:
                logger.warning("import_photo_from_telegram: empty bytes for file_id={}", tg_file_id)
                return None
            ext = (tg_file.file_path or "").lower().rsplit(".", 1)[-1]
            fname = f"photo.{ext}" if ext in ("jpg", "jpeg", "png", "gif", "webp") else "photo.jpg"
            logger.debug(
                "import_photo_from_telegram: downloaded {} bytes, fname={}", len(img_data), fname
            )
            return await self.upload_image_bytes(img_data, filename=fname)
        except Exception as e:
            logger.warning("import_photo_from_telegram: exception for file_id=%s: %s", tg_file_id, e)
            return None

    async def send_photo(
        self,
        chat_id: str,
        photo_file_id: str,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ):
        """Send photo. photo_file_id is MAX attachment token.

        MAX processes uploaded images asynchronously; retries with backoff on
        'attachment.not.ready' as recommended in the MAX API docs.
        """
        import asyncio

        attachments: list[dict] = []
        if photo_file_id:
            attachments.append({
                "type": "image",
                "payload": {"token": photo_file_id},
            })
        max_kb = _build_max_keyboard(keyboard) if keyboard else None
        if max_kb:
            attachments.append({
                "type": "inline_keyboard",
                "payload": {"buttons": max_kb},
            })
        body: dict = {"text": caption or ""}
        if attachments:
            body["attachments"] = attachments
        if caption:
            body["format"] = "html"
        params = _get_msg_params(chat_id)

        delays = [1, 2, 4]  # seconds between retries for attachment.not.ready
        last_exc = None
        for attempt, delay in enumerate([0] + delays):
            if delay:
                await asyncio.sleep(delay)
            try:
                return await self._request(
                    "POST", "/messages", params=params, json_data=body
                )
            except RuntimeError as e:
                err_str = str(e)
                if "attachment.not.ready" in err_str or "not.processed" in err_str:
                    nxt = delays[attempt] if attempt < len(delays) else None
                    logger.debug(
                        "MAX send_photo: attachment not ready (attempt {}), next_sleep={}",
                        attempt + 1, nxt,
                    )
                    last_exc = e
                    continue
                raise
        raise last_exc  # type: ignore[misc]

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
        """Edit message via PATCH /messages/{messageId}.

        In callback flows prefer answer_callback_with_edit() which uses POST /answers.
        """
        attachments = []
        if keyboard:
            max_kb = _build_max_keyboard(keyboard)
            if max_kb:
                attachments.append({
                    "type": "inline_keyboard",
                    "payload": {"buttons": max_kb},
                })
        body: dict = {"text": text}
        if attachments:
            body["attachments"] = attachments
        return await self._request(
            "PATCH",
            f"/messages/{message_id}",
            json_data=body,
        )

    async def answer_callback_with_edit(
        self,
        callback_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
    ):
        """POST /answers?callback_id=... — edit the message that had the button pressed.

        This is the correct MAX way to update a message in response to a button click.
        """
        if not callback_id:
            return
        attachments = []
        if keyboard:
            max_kb = _build_max_keyboard(keyboard)
            if max_kb:
                attachments.append({
                    "type": "inline_keyboard",
                    "payload": {"buttons": max_kb},
                })
        msg_body: dict = {"text": text}
        if attachments:
            msg_body["attachments"] = attachments
        body = {"message": msg_body}
        try:
            return await self._request(
                "POST",
                "/answers",
                params={"callback_id": callback_id},
                json_data=body,
            )
        except Exception as e:
            logger.warning("MAX answer_callback_with_edit failed: {}", e)

    async def request_contact(self, chat_id: str, text: str):
        keyboard = [[Button("Отправить мой номер", type=ButtonType.REQUEST_CONTACT)]]
        return await self.send_message(chat_id, text, keyboard)

    async def request_location(self, chat_id: str, text: str):
        keyboard = [[Button("Отправить геолокацию", type=ButtonType.REQUEST_LOCATION)]]
        return await self.send_message(chat_id, text, keyboard)

    async def answer_callback(self, callback_id: str, text: str | None = None):
        """POST /answers?callback_id=... — acknowledge button press with optional notification."""
        if not callback_id:
            return
        # MAX API requires at least one of `message` or `notification` in the body.
        body: dict = {"notification": (text or "").strip() or " "}
        try:
            await self._request(
                "POST",
                "/answers",
                params={"callback_id": callback_id},
                json_data=body,
            )
        except Exception as e:
            logger.warning("MAX answer_callback failed: {}", e)

    async def get_file_url(self, file_id: str) -> str:
        # MAX file download - may need GET /files/{fileId}
        return ""

    async def get_me(self) -> dict[str, Any]:
        """GET /me — get bot info. Raises on error."""
        return await self._request("GET", "/me")

    async def set_my_commands(self, commands: list[dict]) -> dict[str, Any]:
        """PATCH /me — set bot commands menu."""
        return await self._request("PATCH", "/me", json_data={"commands": commands})

    async def poll_updates(self, marker: int | None = None, timeout: int = 30):
        """Long polling for updates."""
        params: dict = {
            "timeout": timeout,
            "limit": 100,
            "types": "message_created,message_callback,user_added",
        }
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
