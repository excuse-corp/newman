from __future__ import annotations

from typing import Any

from backend.channels.base import BaseChannel, ChannelMessage
from backend.config.schema import ChannelPlatformConfig


class FeishuChannel(BaseChannel):
    platform = "feishu"

    def __init__(self, config: ChannelPlatformConfig):
        self.config = config

    async def receive_message(self, raw_event: dict[str, Any]) -> ChannelMessage:
        event = raw_event.get("event", raw_event)
        user_id = str(event.get("open_id") or event.get("user_id") or "anonymous")
        conversation_id = str(event.get("chat_id") or event.get("conversation_id") or user_id)
        text = str(event.get("text") or event.get("content") or "").strip()
        if not text:
            raise ValueError("飞书消息缺少 text/content")
        return ChannelMessage(
            platform=self.platform,
            user_id=user_id,
            conversation_id=conversation_id,
            text=text,
        )

    async def send_response(self, channel_id: str, response: str, format: str = "text") -> bool:
        return True

    def verify_webhook(self, raw_event: dict[str, Any], headers: dict[str, str]) -> bool:
        if not self.config.enabled:
            return False
        if not self.config.webhook_token:
            return True
        token = headers.get("x-newman-channel-token") or str(raw_event.get("token") or "")
        return token == self.config.webhook_token
