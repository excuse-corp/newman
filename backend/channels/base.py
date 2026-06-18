from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ChannelMessage(BaseModel):
    platform: str
    user_id: str
    conversation_id: str | None = None
    text: str
    transport: str = "webhook"
    app_id: str | None = None
    event_id: str | None = None
    message_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    reply_format: str = "text"


class ChannelResponse(BaseModel):
    platform: str
    user_id: str
    session_id: str
    content: str
    format: str = "text"


class BaseChannel(ABC):
    platform: str

    @abstractmethod
    async def receive_message(self, raw_event: dict[str, Any]) -> ChannelMessage:
        raise NotImplementedError

    @abstractmethod
    async def send_response(self, channel_id: str, response: str, format: str = "text") -> bool:
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, raw_event: dict[str, Any], headers: dict[str, str]) -> bool:
        raise NotImplementedError
