"""Middleware for handlers."""
from typing import Any, Awaitable, Callable, Dict

from loguru import logger
from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.services.user import get_or_create_user
from src.config import get_settings

# Callback data prefixes and text triggers that bypass the block check.
# SOS must be accessible at ALL times — even for blocked users.
_SOS_CALLBACK_PREFIXES = (
    "menu_sos",
    "sos_accident",
    "sos_broken",
    "sos_ran_out",
    "sos_other",
    "sos_skip_comment",
    "sos_all_clear_",
)
_SOS_TEXT_TRIGGERS = ("🆘 SOS",)


def _is_sos_event(event: TelegramObject) -> bool:
    """Return True if the event is SOS-related and must bypass block check."""
    if isinstance(event, CallbackQuery):
        data = event.data or ""
        return any(data == p or data.startswith(p) for p in _SOS_CALLBACK_PREFIXES)
    if isinstance(event, Message):
        text = event.text or ""
        return text in _SOS_TEXT_TRIGGERS
    return False


class BotInjectMiddleware(BaseMiddleware):
    """Inject bot instance into handler data."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["bot"] = self.bot
        return await handler(event, data)


class BlockCheckMiddleware(BaseMiddleware):
    """
    Check if user is blocked before processing any update.

    SOS callbacks/messages bypass this check completely — emergency
    functionality must remain available regardless of block status.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # SOS always passes through — safety-critical feature
        if _is_sos_event(event):
            user_id = None
            if isinstance(event, (Message, CallbackQuery)):
                user_id = event.from_user.id if event.from_user else None
            if user_id:
                user = await get_or_create_user(
                    platform="telegram",
                    platform_user_id=user_id,
                    username=getattr(event.from_user, "username", None),
                    first_name=getattr(event.from_user, "first_name", None),
                )
                data["user"] = user
            return await handler(event, data)

        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        user = None
        if user_id:
            # #region agent log
            text = getattr(event, "text", "") or ""
            if "/start" in text:
                import json
                import time
                try:
                    with open(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"ca1ad6","location":"middleware.py:BlockCheck","message":"BlockCheck before get_or_create_user","data":{"user_id":user_id},"timestamp":int(time.time()*1000),"hypothesisId":"H3"}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
            # #endregion
            try:
                user = await get_or_create_user(
                    platform="telegram",
                    platform_user_id=user_id,
                    username=getattr(event.from_user, "username", None) if event.from_user else None,
                    first_name=getattr(event.from_user, "first_name", None) if event.from_user else None,
                )
            except Exception as e:
                logger.warning("BlockCheckMiddleware: get_or_create_user failed for %s: %s", user_id, e)
                # #region agent log
                import json
                import time
                try:
                    with open(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"ca1ad6","location":"middleware.py:BlockCheck","message":"get_or_create_user FAILED","data":{"user_id":user_id,"error":str(e)},"timestamp":int(time.time()*1000),"hypothesisId":"H3,H5"}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
            if user and user.is_blocked:
                # #region agent log
                import json
                import time
                try:
                    with open(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "debug-ca1ad6.log"), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"ca1ad6","location":"middleware.py:BlockCheck","message":"User BLOCKED - handler NOT called","data":{"user_id":user_id},"timestamp":int(time.time()*1000),"hypothesisId":"H3"}, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                if isinstance(event, Message):
                    await event.answer("Вы заблокированы. Обратитесь в поддержку.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Вы заблокированы.", show_alert=True)
                return
            data["user"] = user

        return await handler(event, data)
