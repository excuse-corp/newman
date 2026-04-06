from __future__ import annotations

from backend.channels.base import BaseChannel, ChannelResponse
from backend.channels.feishu import FeishuChannel
from backend.channels.message_converter import to_channel_payload, to_newman_input
from backend.channels.session_store import ChannelSessionStore
from backend.channels.wecom import WecomChannel
from backend.config.schema import AppConfig


class ChannelService:
    def __init__(self, settings: AppConfig, runtime):
        self.settings = settings
        self.runtime = runtime
        self.session_store = ChannelSessionStore(settings.paths.channels_dir / "session_map.json")
        self.channels: dict[str, BaseChannel] = {
            "feishu": FeishuChannel(settings.channels.feishu),
            "wecom": WecomChannel(settings.channels.wecom),
        }

    def list_status(self) -> list[dict]:
        return [
            {
                "platform": "feishu",
                "enabled": self.settings.channels.feishu.enabled,
                "webhook_token_configured": bool(self.settings.channels.feishu.webhook_token),
            },
            {
                "platform": "wecom",
                "enabled": self.settings.channels.wecom.enabled,
                "webhook_token_configured": bool(self.settings.channels.wecom.webhook_token),
            },
        ]

    async def handle_webhook(self, platform: str, payload: dict, headers: dict[str, str]) -> dict:
        channel = self.channels.get(platform)
        if channel is None:
            raise FileNotFoundError(f"Channel not found: {platform}")
        if not channel.verify_webhook(payload, headers):
            raise PermissionError(f"{platform} webhook verification failed")

        message = await channel.receive_message(payload)
        key = f"{platform}:{message.conversation_id or message.user_id}:{message.user_id}"
        session_id = self.session_store.get(key)
        if session_id is None:
            session, _ = self.runtime.thread_manager.create_or_restore(title=f"[{platform}] {message.user_id}")
            session_id = session.session_id
            session.metadata["channel"] = platform
            session.metadata["channel_user_id"] = message.user_id
            self.runtime.session_store.save(session)
            self.session_store.set(key, session_id)

        final_content = await self._run_round(session_id, to_newman_input(message))
        response = ChannelResponse(
            platform=platform,
            user_id=message.user_id,
            session_id=session_id,
            content=final_content,
            format=message.reply_format,
        )
        await channel.send_response(message.conversation_id or message.user_id, final_content, format=message.reply_format)
        return to_channel_payload(response)

    async def _run_round(self, session_id: str, content: str) -> str:
        final_content = ""

        async def emit(event: str, data: dict) -> None:
            nonlocal final_content
            if event == "final_response":
                final_content = str(data.get("content", ""))

        await self.runtime.handle_message(session_id, content, emit)
        return final_content
