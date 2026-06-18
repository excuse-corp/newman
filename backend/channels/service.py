from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import json
from pathlib import Path
import re
from uuid import uuid4

from backend.api.sse.event_emitter import build_event_payload
from backend.channels.base import BaseChannel, ChannelResponse
from backend.channels.feishu import FeishuChannel
from backend.channels.feishu_transport import FeishuChannelTransport
from backend.channels.message_converter import to_channel_payload, to_newman_input
from backend.channels.session_store import ChannelSessionStore
from backend.channels.wecom import WecomChannel
from backend.config.schema import AppConfig
from backend.sessions.models import utc_now
from backend.tools.approval_policy import normalize_turn_approval_mode

ACTIVE_SESSION_MESSAGE = "上一个任务还在处理，完成后再继续。"
FEISHU_SESSION_TITLE_PREFIX = "飞书"
FEISHU_SESSION_SUMMARY_LIMIT = 24


class ChannelService:
    def __init__(
        self,
        settings: AppConfig,
        runtime,
        *,
        event_broker=None,
        feishu_transport_factory: Callable[..., FeishuChannelTransport] | None = None,
    ):
        self.settings = settings
        self.runtime = runtime
        self.event_broker = event_broker
        self.session_store = ChannelSessionStore(settings.paths.channels_dir / "session_map.json")
        self._active_transport_sessions: set[str] = set()
        self.channels: dict[str, BaseChannel] = {
            "feishu": FeishuChannel(settings.channels.feishu),
            "wecom": WecomChannel(settings.channels.wecom),
        }
        factory = feishu_transport_factory or FeishuChannelTransport
        self.feishu_transport = factory(
            settings.channels.feishu,
            on_message=self.handle_transport_message,
            state_dir=settings.paths.channels_dir / "feishu_channel",
        )
        self._feishu_turn_approval_mode = normalize_turn_approval_mode(
            settings.channels.feishu.default_turn_approval_mode
        )

    async def start(self) -> None:
        await self.feishu_transport.start()

    async def stop(self) -> None:
        await self.feishu_transport.stop()

    def list_status(self) -> list[dict]:
        feishu_status = {
            "platform": "feishu",
            "enabled": self.settings.channels.feishu.enabled,
            "transport": self.settings.channels.feishu.transport,
            "webhook_token_configured": bool(self.settings.channels.feishu.webhook_token),
        }
        feishu_status.update(self.feishu_transport.status_snapshot())
        return [
            feishu_status,
            {
                "platform": "wecom",
                "enabled": self.settings.channels.wecom.enabled,
                "transport": "webhook",
                "webhook_token_configured": bool(self.settings.channels.wecom.webhook_token),
            },
        ]

    def get_channel_status(self, platform: str) -> dict:
        for item in self.list_status():
            if item.get("platform") == platform:
                return item
        raise FileNotFoundError(f"Channel not found: {platform}")

    def get_feishu_setup_status(self) -> dict:
        status = self.get_channel_status("feishu")
        reason = "ready"
        message = "Feishu channel is ready."
        if not status["enabled"]:
            reason = "channel_disabled"
            message = "Feishu channel is disabled in project config."
        elif status["transport"] != "channel_sdk":
            reason = "transport_not_channel_sdk"
            message = "Feishu transport must be set to `channel_sdk`."
        elif not status["app_configured"]:
            reason = "missing_credentials"
            message = "Feishu app_id or app_secret is missing."
        elif not status["dependency_available"]:
            reason = "missing_dependency"
            message = "Python package `lark-channel-sdk` is not installed."
        elif status["running"] and not status["connected"]:
            reason = "starting"
            message = "Feishu channel transport is starting but not ready yet."
        elif not status["running"]:
            reason = "not_started"
            message = "Feishu channel transport is configured but not running."
        return {
            "platform": "feishu",
            "ok": reason == "ready",
            "reason": reason,
            "message": message,
            "config": {
                "enabled": self.settings.channels.feishu.enabled,
                "transport": self.settings.channels.feishu.transport,
                "domain": self.settings.channels.feishu.domain,
                "default_turn_approval_mode": self.settings.channels.feishu.default_turn_approval_mode,
                "require_mention_in_group": self.settings.channels.feishu.require_mention_in_group,
                "allowed_chat_ids_count": len(self.settings.channels.feishu.allowed_chat_ids),
                "allowed_user_open_ids_count": len(self.settings.channels.feishu.allowed_user_open_ids),
                "reply_timeout_seconds": self.settings.channels.feishu.reply_timeout_seconds,
                "dedup_ttl_seconds": self.settings.channels.feishu.dedup_ttl_seconds,
            },
            "status": status,
        }

    async def validate_feishu_setup(self, *, timeout_seconds: float = 10.0) -> dict:
        return await self.feishu_transport.validate_connection(timeout_seconds=timeout_seconds)

    async def test_feishu_setup(self, *, timeout_seconds: float = 45.0, validate_first: bool = True) -> dict:
        validation = None
        if validate_first:
            validation = await self.validate_feishu_setup(timeout_seconds=min(timeout_seconds, 15.0))
            if not validation.get("ok"):
                return {
                    "ok": False,
                    "reason": "validation_failed",
                    "message": "Feishu channel validation failed before test wait.",
                    "validation": validation,
                    "status": self.get_feishu_setup_status(),
                }

        await self.feishu_transport.start()
        event = await self.feishu_transport.wait_for_next_event(timeout_seconds=timeout_seconds)
        if event is None:
            return {
                "ok": False,
                "reason": "event_timeout",
                "message": "No inbound Feishu message was received within the timeout window.",
                "validation": validation,
                "status": self.get_feishu_setup_status(),
                "timeout_seconds": timeout_seconds,
            }
        return {
            "ok": True,
            "reason": "event_received",
            "message": "Inbound Feishu event received.",
            "validation": validation,
            "status": self.get_feishu_setup_status(),
            "timeout_seconds": timeout_seconds,
            "event": event,
        }

    async def handle_webhook(self, platform: str, payload: dict, headers: dict[str, str]) -> dict:
        channel = self.channels.get(platform)
        if channel is None:
            raise FileNotFoundError(f"Channel not found: {platform}")
        if not channel.verify_webhook(payload, headers):
            raise PermissionError(f"{platform} webhook verification failed")

        message = await channel.receive_message(payload)
        response = await self.process_message(message)
        await channel.send_response(
            message.conversation_id or message.user_id,
            response.content,
            format=message.reply_format,
        )
        return to_channel_payload(response)

    async def handle_transport_message(self, message) -> ChannelResponse:
        try:
            if message.platform == "feishu" and message.transport == "channel_sdk":
                return await self.process_transport_message(message)
            return await self.process_message(message)
        except Exception:
            return ChannelResponse(
                platform=message.platform,
                user_id=message.user_id,
                session_id=self._lookup_or_create_session(message),
                content="我收到消息了，但这次处理失败。请稍后重试。",
                format=message.reply_format,
            )

    async def process_message(self, message, *, timeout_seconds: int | None = None) -> ChannelResponse:
        session_id = self._lookup_or_create_session(message)
        final_content = await self._run_round(session_id, to_newman_input(message), timeout_seconds=timeout_seconds)
        return ChannelResponse(
            platform=message.platform,
            user_id=message.user_id,
            session_id=session_id,
            content=final_content,
            format=message.reply_format,
        )

    async def process_transport_message(self, message) -> ChannelResponse:
        session_id = self._lookup_or_create_session(message)
        if session_id in self._active_transport_sessions:
            return ChannelResponse(
                platform=message.platform,
                user_id=message.user_id,
                session_id=session_id,
                content=ACTIVE_SESSION_MESSAGE,
                format=message.reply_format,
            )
        self._active_transport_sessions.add(session_id)
        request_id = uuid4().hex
        provisional_turn_id = message.message_id or message.event_id or uuid4().hex
        final_content = ""
        created_at = utc_now()

        try:
            await self._emit_channel_event(
                session_id,
                "channel_message_received",
                {
                    "session_id": session_id,
                    "session_title": self.runtime.session_store.get(session_id).title,
                    "platform": message.platform,
                    "transport": message.transport,
                    "channel_user_id": message.user_id,
                    "channel_conversation_id": message.conversation_id,
                    "turn_id": provisional_turn_id,
                    "content": to_newman_input(message),
                    "created_at": created_at,
                },
                request_id=request_id,
            )

            async def emit(event: str, data: dict) -> None:
                nonlocal final_content
                payload = dict(data)
                payload.setdefault("session_id", session_id)
                if event == "final_response":
                    final_content = str(payload.get("content", ""))
                await self._emit_channel_event(session_id, event, payload, request_id=request_id)

            user_metadata = {
                "environment_context": {
                    "time": {
                        "server_received_at_utc": created_at,
                    }
                },
                "channel": {
                    "platform": message.platform,
                    "transport": message.transport,
                    "conversation_id": message.conversation_id,
                    "user_id": message.user_id,
                    "app_id": message.app_id,
                    "message_id": message.message_id,
                    "event_id": message.event_id,
                },
            }

            await self.runtime.handle_message(
                session_id,
                to_newman_input(message),
                emit,
                user_metadata=user_metadata,
                turn_approval_mode=self._feishu_turn_approval_mode,
                request_id=request_id,
                turn_id=provisional_turn_id,
            )
            if not final_content.strip():
                final_content = "我收到消息了，但这次没有生成可发送的结果。请到 Newman 页面查看过程。"
            return ChannelResponse(
                platform=message.platform,
                user_id=message.user_id,
                session_id=session_id,
                content=final_content,
                format=message.reply_format,
            )
        finally:
            self._active_transport_sessions.discard(session_id)

    def _lookup_or_create_session(self, message) -> str:
        key = self._build_session_key(message)
        session_id = self.session_store.get(key)
        if session_id is None:
            return self._create_channel_session(key, message)
        session = self.runtime.session_store.get(session_id)
        self._update_channel_session_metadata(session, message)
        self.runtime.session_store.save(session)
        return session_id

    def _create_channel_session(self, key: str, message) -> str:
        platform = message.platform
        session, _ = self.runtime.thread_manager.create_or_restore(title=self._build_session_title(message))
        session_id = session.session_id
        session.metadata["channel"] = platform
        self._update_channel_session_metadata(session, message, is_new_session=True)
        self.runtime.session_store.save(session)
        self.session_store.set(key, session_id)
        return session_id

    def _build_session_key(self, message) -> str:
        if message.platform == "feishu" and message.transport == "channel_sdk":
            app_id = message.app_id or "-"
            chat_id = message.conversation_id or message.user_id
            session_date = self._resolve_channel_session_date(message)
            return f"feishu:{app_id}:{chat_id}:{message.user_id}:{session_date}"
        return f"{message.platform}:{message.conversation_id or message.user_id}:{message.user_id}"

    async def _run_round(self, session_id: str, content: str, *, timeout_seconds: int | None = None) -> str:
        final_content = ""

        async def emit(event: str, data: dict) -> None:
            nonlocal final_content
            if event == "final_response":
                final_content = str(data.get("content", ""))

        if timeout_seconds is None:
            await self.runtime.handle_message(session_id, content, emit)
            return final_content
        try:
            await asyncio.wait_for(self.runtime.handle_message(session_id, content, emit), timeout=timeout_seconds)
            return final_content
        except TimeoutError:
            return "我收到消息了，但这次处理超时。请稍后重试。"

    def _build_session_title(self, message) -> str:
        if message.platform == "feishu":
            summary = self._summarize_session_title(message.text)
            session_date = self._resolve_channel_session_date(message)
            return f"{FEISHU_SESSION_TITLE_PREFIX} · {summary} · {session_date}"
        return f"[{message.platform}] {message.user_id}"

    def _update_channel_session_metadata(self, session, message, *, is_new_session: bool = False) -> None:
        session.metadata["channel_user_id"] = message.user_id
        session.metadata["channel_transport"] = message.transport
        session.metadata["channel_conversation_id"] = message.conversation_id
        if message.metadata.get("chat_type"):
            session.metadata["channel_chat_type"] = message.metadata.get("chat_type")
        if message.metadata.get("sender_display_name"):
            session.metadata["channel_sender_display_name"] = message.metadata.get("sender_display_name")
        if message.metadata.get("chat_display_name"):
            session.metadata["channel_chat_display_name"] = message.metadata.get("chat_display_name")
        if message.app_id:
            session.metadata["channel_app_id"] = message.app_id
        if message.thread_id:
            session.metadata["channel_thread_id"] = message.thread_id
        if message.message_id:
            session.metadata["channel_last_message_id"] = message.message_id
        session.metadata["channel_session_date"] = self._resolve_channel_session_date(message)
        session.metadata["channel_chat_id"] = message.conversation_id
        session.metadata["channel_sender_open_id"] = message.user_id
        if is_new_session:
            session.metadata["channel_first_message_id"] = message.message_id
            session.metadata["channel_first_message_summary"] = self._summarize_session_title(message.text)

    def _resolve_channel_session_date(self, message) -> str:
        raw_value = message.metadata.get("received_local_date")
        if isinstance(raw_value, str):
            cleaned = raw_value.strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
                return cleaned
        return datetime.now().astimezone().date().isoformat()

    def _summarize_session_title(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return "新对话"
        if len(normalized) <= FEISHU_SESSION_SUMMARY_LIMIT:
            return normalized
        return normalized[:FEISHU_SESSION_SUMMARY_LIMIT].rstrip() + "..."

    async def _emit_channel_event(self, session_id: str, event: str, data: dict, *, request_id: str | None = None) -> None:
        payload = build_event_payload(event, data, request_id=request_id)
        self._append_audit_event(session_id, payload)
        if self.event_broker is not None:
            await self.event_broker.publish(payload)

    def _append_audit_event(self, session_id: str, payload: dict) -> None:
        audit_path = Path(self.settings.paths.audit_dir) / f"{session_id}.log"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
