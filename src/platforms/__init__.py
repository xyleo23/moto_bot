"""Platform adapters for Telegram and MAX."""

from src.platforms.base import (
    PlatformAdapter,
    IncomingMessage,
    IncomingCallback,
    IncomingContact,
    IncomingLocation,
    Button,
    KeyboardRow,
)
from src.platforms.telegram_adapter import TelegramAdapter
from src.platforms.max_adapter import MaxAdapter

__all__ = [
    "PlatformAdapter",
    "IncomingMessage",
    "IncomingCallback",
    "IncomingContact",
    "IncomingLocation",
    "Button",
    "KeyboardRow",
    "TelegramAdapter",
    "MaxAdapter",
]
