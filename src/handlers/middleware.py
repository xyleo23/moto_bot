"""Middleware for handlers."""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.services.user import get_or_create_user
from src.models.user import User
from src.config import get_settings


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
    """Check if user is blocked before processing."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None

        if user_id:
            user = await get_or_create_user(
                platform="telegram",
                platform_user_id=user_id,
                username=getattr(event.from_user, "username", None) if hasattr(event, "from_user") and event.from_user else None,
                first_name=getattr(event.from_user, "first_name", None) if hasattr(event, "from_user") and event.from_user else None,
            )
            if user and user.is_blocked:
                if isinstance(event, Message):
                    await event.answer("Вы заблокированы. Обратитесь в поддержку.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Вы заблокированы.", show_alert=True)
                return
            data["user"] = user

        return await handler(event, data)
