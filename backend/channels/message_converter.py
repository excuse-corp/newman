from __future__ import annotations

from backend.channels.base import ChannelMessage, ChannelResponse


def to_newman_input(message: ChannelMessage) -> str:
    return message.text


def to_channel_payload(response: ChannelResponse) -> dict:
    return {
        "platform": response.platform,
        "user_id": response.user_id,
        "session_id": response.session_id,
        "format": response.format,
        "content": response.content,
    }
