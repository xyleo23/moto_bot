"""Abstract platform adapter interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ButtonType(str, Enum):
    CALLBACK = "callback"
    MESSAGE = "message"  # MAX: sends button text as user message (pseudo reply-keyboard)
    URL = "url"
    REQUEST_CONTACT = "request_contact"
    REQUEST_LOCATION = "request_geo_location"


@dataclass
class Button:
    text: str
    type: ButtonType = ButtonType.CALLBACK
    payload: str | None = None
    url: str | None = None


KeyboardRow = list[Button]


@dataclass
class IncomingMessage:
    platform: str
    chat_id: str
    user_id: int
    username: str | None
    first_name: str | None
    text: str | None
    raw: Any = None


@dataclass
class IncomingCallback:
    platform: str
    chat_id: str
    user_id: int
    message_id: str
    callback_data: str
    raw: Any = None


@dataclass
class IncomingContact:
    platform: str
    chat_id: str
    user_id: int
    phone_number: str
    raw: Any = None


@dataclass
class IncomingLocation:
    platform: str
    chat_id: str
    user_id: int
    latitude: float
    longitude: float
    raw: Any = None


@dataclass
class IncomingPhoto:
    platform: str
    chat_id: str
    user_id: int
    file_id: str
    caption: str | None
    raw: Any = None


class PlatformAdapter(ABC):
    """Abstract interface for platform-specific adapters."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        pass

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
        parse_mode: str | None = "HTML",
    ) -> Any:
        pass

    @abstractmethod
    async def send_photo(
        self,
        chat_id: str,
        photo_file_id: str,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def send_photo_bytes(
        self,
        chat_id: str,
        photo_bytes: bytes,
        caption: str | None = None,
        keyboard: list[KeyboardRow] | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: list[KeyboardRow] | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def request_contact(
        self,
        chat_id: str,
        text: str,
    ) -> Any:
        pass

    @abstractmethod
    async def request_location(
        self,
        chat_id: str,
        text: str,
    ) -> Any:
        pass

    @abstractmethod
    async def answer_callback(self, callback_id: str, text: str | None = None) -> Any:
        pass

    @abstractmethod
    async def get_file_url(self, file_id: str) -> str:
        """Get download URL for file (photo, etc)."""
        pass
