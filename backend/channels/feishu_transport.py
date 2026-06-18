from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
import urllib.parse
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.channels.base import ChannelMessage, ChannelResponse
from backend.config.schema import FeishuChannelConfig

try:
    import lark_channel as _LARK_CHANNEL_SDK
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _LARK_CHANNEL_SDK = None


LOGGER = logging.getLogger("newman.channels.feishu")
FALLBACK_TRANSPORT_ERROR = "我收到消息了，但这次处理失败。请稍后重试。"
ASYNC_ACK_DELAY_SECONDS = 2.0
ASYNC_ACK_TEXT = "已收到，正在处理，完成后回复。"


class FeishuDedupStore:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = max(ttl_seconds, 1)
        self._entries: dict[str, float] = {}

    def try_record(self, key: str, now: float | None = None) -> bool:
        current = now if now is not None else asyncio.get_running_loop().time()
        self._cleanup(current)
        if key in self._entries:
            return False
        self._entries[key] = current
        return True

    def size(self, now: float | None = None) -> int:
        current = now if now is not None else _monotonic_now()
        self._cleanup(current)
        return len(self._entries)

    def _cleanup(self, now: float) -> None:
        expired = [key for key, ts in self._entries.items() if now - ts > self.ttl_seconds]
        for key in expired:
            self._entries.pop(key, None)


class FeishuChannelTransport:
    def __init__(
        self,
        config: FeishuChannelConfig,
        *,
        on_message: Callable[[ChannelMessage], Awaitable[ChannelResponse]],
        state_dir: Path,
    ) -> None:
        self.config = config
        self._on_message = on_message
        self._state_dir = state_dir
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._sdk_available = _LARK_CHANNEL_SDK is not None
        self._running = False
        self._connected = False
        self._last_event_at: str | None = None
        self._last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._channel: Any | None = None
        self._dedup = FeishuDedupStore(config.dedup_ttl_seconds)
        self._last_connection_snapshot: dict[str, Any] = {}
        self._last_event_preview: dict[str, Any] | None = None
        self._event_waiters: list[asyncio.Future[dict[str, Any]]] = []

    async def start(self) -> None:
        if not self.config.enabled or self.config.transport != "channel_sdk":
            return
        if self._task and not self._task.done():
            return
        if not self.is_configured():
            self._last_error = None
            return
        self._main_loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run(), name="newman-feishu-channel")

    async def stop(self) -> None:
        task = self._task
        channel = self._channel
        self._task = None
        self._main_loop = None
        if channel is not None:
            stop_method = getattr(channel, "stop", None)
            if callable(stop_method):
                await asyncio.to_thread(stop_method)
            else:
                await _maybe_close(channel)
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=10)
            except TimeoutError:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def is_configured(self) -> bool:
        return bool((self.config.app_id or "").strip() and (self.config.app_secret or "").strip())

    def is_running(self) -> bool:
        return self._running

    def status_snapshot(self) -> dict[str, Any]:
        snapshot = self._current_connection_snapshot()
        return {
            "transport": self.config.transport,
            "app_configured": self.is_configured(),
            "dependency_available": self._sdk_available,
            "running": self._running,
            "connected": bool(snapshot.get("ready", self._connected)),
            "connection_state": snapshot.get("state"),
            "reconnect_attempts": snapshot.get("reconnect_attempts"),
            "last_connected_at": snapshot.get("last_connected_at"),
            "last_disconnected_at": snapshot.get("last_disconnected_at"),
            "last_sdk_error_at": snapshot.get("last_error_at"),
            "last_sdk_error": snapshot.get("last_error"),
            "connection_id": snapshot.get("connection_id"),
            "last_event_at": self._last_event_at,
            "recent_event_preview": self._last_event_preview,
            "last_error": self._last_error,
            "dedup_cache_size": self._dedup.size(),
        }

    async def validate_connection(self, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
        status = self.status_snapshot()
        if not self.config.enabled:
            return {
                "ok": False,
                "reason": "channel_disabled",
                "message": "Feishu channel is disabled.",
                "status": status,
            }
        if self.config.transport != "channel_sdk":
            return {
                "ok": False,
                "reason": "transport_not_channel_sdk",
                "message": "Feishu transport is not set to `channel_sdk`.",
                "status": status,
            }
        if not self.is_configured():
            return {
                "ok": False,
                "reason": "missing_credentials",
                "message": "Missing Feishu app_id or app_secret.",
                "status": status,
            }

        if self._channel is not None and self._running:
            snapshot = self._current_connection_snapshot()
            ready = bool(snapshot.get("ready", self._connected))
            return {
                "ok": ready,
                "reason": "running_transport",
                "message": "Using active Feishu channel transport state.",
                "snapshot": snapshot,
                "status": self.status_snapshot(),
            }

        sdk = _LARK_CHANNEL_SDK
        if sdk is None:
            self._sdk_available = False
            return {
                "ok": False,
                "reason": "missing_dependency",
                "message": "Python package `lark-channel-sdk` is not installed.",
                "status": self.status_snapshot(),
            }

        self._sdk_available = True
        result = await asyncio.to_thread(self._probe_connection_blocking, max(timeout_seconds, 1.0))
        if result.get("ok"):
            self._last_error = None
        else:
            self._last_error = str(result.get("message") or "")
        return result

    async def wait_for_next_event(self, *, timeout_seconds: float = 45.0) -> dict[str, Any] | None:
        if timeout_seconds <= 0:
            return self._last_event_preview
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._event_waiters.append(future)
        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError:
            return None
        finally:
            if future in self._event_waiters:
                self._event_waiters.remove(future)

    async def _run(self) -> None:
        sdk = _LARK_CHANNEL_SDK
        if sdk is None:
            self._sdk_available = False
            self._last_error = "Python package `lark-channel-sdk` is not installed."
            LOGGER.warning(self._last_error)
            return

        self._sdk_available = True
        self._running = True
        self._last_error = None
        try:
            await asyncio.to_thread(self._run_blocking, sdk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = str(exc)
            self._connected = False
            LOGGER.exception("Feishu channel transport failed: %s", exc)
        finally:
            self._running = False
            self._connected = False
            self._channel = None

    def _run_blocking(self, sdk: Any) -> None:
        self._prepare_sdk_worker_context()
        channel_cls = getattr(sdk, "FeishuChannel")
        channel = channel_cls(
            app_id=(self.config.app_id or "").strip(),
            app_secret=(self.config.app_secret or "").strip(),
            domain=_normalize_domain_origin(self.config.domain),
        )
        self._channel = channel
        channel.on("message", self._handle_message_from_worker)
        channel.start()

    def _probe_connection_blocking(self, timeout_seconds: float) -> dict[str, Any]:
        sdk = _LARK_CHANNEL_SDK
        if sdk is None:
            return {
                "ok": False,
                "reason": "missing_dependency",
                "message": "Python package `lark-channel-sdk` is not installed.",
                "status": self.status_snapshot(),
            }

        self._prepare_sdk_worker_context()
        channel_cls = getattr(sdk, "FeishuChannel")
        channel = channel_cls(
            app_id=(self.config.app_id or "").strip(),
            app_secret=(self.config.app_secret or "").strip(),
            domain=_normalize_domain_origin(self.config.domain),
        )
        error_box: list[BaseException] = []

        def _runner() -> None:
            try:
                channel.start()
            except BaseException as exc:  # pragma: no cover - thread handoff
                error_box.append(exc)

        thread = threading.Thread(target=_runner, name="newman-feishu-probe", daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if error_box:
                    raise error_box[0]
                snapshot = _connection_snapshot_dict(channel)
                if snapshot.get("ready"):
                    self._last_connection_snapshot = snapshot
                    return {
                        "ok": True,
                        "reason": "probe_success",
                        "message": "Feishu channel connection probe succeeded.",
                        "snapshot": snapshot,
                        "status": self.status_snapshot(),
                    }
                time.sleep(0.05)
            raise TimeoutError(f"Feishu channel connection probe timed out after {timeout_seconds:.1f}s")
        except Exception as exc:
            return {
                "ok": False,
                "reason": "probe_failed",
                "message": str(exc),
                "error_type": exc.__class__.__name__,
                "status": self.status_snapshot(),
            }
        finally:
            stop_method = getattr(channel, "stop", None)
            if callable(stop_method):
                try:
                    stop_method()
                except Exception:
                    pass
            thread.join(timeout=3)

    def _handle_message_from_worker(self, raw_message: Any) -> None:
        loop = self._main_loop
        if loop is None or loop.is_closed():
            LOGGER.warning("Dropping Feishu message because Newman main loop is not available.")
            return
        future = asyncio.run_coroutine_threadsafe(self._handle_message(raw_message), loop)

        def _done(result_future) -> None:
            try:
                result_future.result()
            except Exception as exc:  # pragma: no cover - defensive logging
                self._last_error = str(exc)
                LOGGER.exception("Feishu worker message dispatch failed: %s", exc)

        future.add_done_callback(_done)

    def _prepare_sdk_worker_context(self) -> None:
        try:
            from lark_channel.ws import client as ws_client_module
        except Exception:
            return
        ws_loop = getattr(ws_client_module, "loop", None)
        if ws_loop is None or ws_loop.is_running() or ws_loop.is_closed():
            ws_loop = asyncio.new_event_loop()
            ws_client_module.loop = ws_loop
        asyncio.set_event_loop(ws_loop)

    async def _handle_message(self, raw_message: Any) -> None:
        self._last_event_at = _utc_now()
        self._publish_event_preview(_event_preview(raw_message))
        message = self._normalize_message(raw_message)
        if message is None:
            return
        dedup_key = message.event_id or message.message_id
        if dedup_key and not self._dedup.try_record(dedup_key):
            LOGGER.info("Skipping duplicate Feishu event: %s", dedup_key)
            return

        response_task = asyncio.create_task(self._on_message(message))
        ack_sent = False
        try:
            try:
                response = await asyncio.wait_for(asyncio.shield(response_task), timeout=ASYNC_ACK_DELAY_SECONDS)
            except TimeoutError:
                ack_sent = True
                await self._send_response(message, ASYNC_ACK_TEXT)
                response = await response_task
            if response.content.strip():
                await self._send_response(message, response.content)
        except Exception as exc:
            self._last_error = str(exc)
            LOGGER.exception("Failed to process Feishu message: %s", exc)
            if ack_sent:
                await self._send_response(message, FALLBACK_TRANSPORT_ERROR)
            else:
                await self._send_response(message, FALLBACK_TRANSPORT_ERROR)

    def _normalize_message(self, raw_message: Any) -> ChannelMessage | None:
        raw_payload = _to_payload(raw_message)
        conversation = getattr(raw_message, "conversation", None)
        sender = getattr(raw_message, "sender", None)
        chat_id = getattr(conversation, "chat_id", None) or _coalesce(raw_message, raw_payload, "chat_id")
        message_id = getattr(raw_message, "id", None) or _coalesce(raw_message, raw_payload, "message_id", "id")
        event_id = _coalesce(raw_message, raw_payload, "event_id")
        sender_open_id = getattr(sender, "open_id", None) or _coalesce(
            raw_message,
            raw_payload,
            "sender_open_id",
            "open_id",
            "user_open_id",
        )
        chat_type = (
            str(getattr(conversation, "chat_type", None) or _coalesce(raw_message, raw_payload, "chat_type"))
            .strip()
            .lower()
            or None
        )
        text = _extract_text(raw_message, raw_payload)
        if not chat_id or not sender_open_id or not text:
            return None

        thread_id = getattr(conversation, "thread_id", None) or _coalesce(raw_message, raw_payload, "thread_id", "root_id", "parent_id")
        mentions = getattr(raw_message, "mentions", None) or _coalesce(raw_message, raw_payload, "mentions")
        is_mention = bool(getattr(raw_message, "mentioned_bot", None))
        if not is_mention:
            is_mention = bool(_coalesce(raw_message, raw_payload, "is_mention", "mentioned"))
        if not is_mention and isinstance(mentions, list):
            is_mention = len(mentions) > 0

        if chat_type != "p2p" and self.config.require_mention_in_group and not is_mention:
            return None

        allowed_chat_ids = {item.strip() for item in self.config.allowed_chat_ids if item.strip()}
        if allowed_chat_ids and str(chat_id) not in allowed_chat_ids:
            return None
        allowed_user_ids = {item.strip() for item in self.config.allowed_user_open_ids if item.strip()}
        if allowed_user_ids and str(sender_open_id) not in allowed_user_ids:
            return None

        sender_display_name = _extract_sender_display_name(raw_message, raw_payload)
        chat_display_name = _extract_chat_display_name(raw_message, raw_payload)

        return ChannelMessage(
            platform="feishu",
            transport="channel_sdk",
            app_id=(self.config.app_id or "").strip() or None,
            user_id=str(sender_open_id),
            conversation_id=str(chat_id),
            text=text,
            event_id=str(event_id) if event_id else None,
            message_id=str(message_id) if message_id else None,
            thread_id=str(thread_id) if thread_id else None,
            metadata={
                "chat_type": chat_type,
                "sender_display_name": sender_display_name,
                "chat_display_name": chat_display_name,
                "raw": raw_payload,
                "is_mention": is_mention,
                "received_local_date": _local_date_string(),
            },
        )

    async def _send_response(self, inbound: ChannelMessage, text: str) -> None:
        if self._channel is None:
            return
        payload = {"markdown": text}
        options = {"reply_to": inbound.message_id} if inbound.message_id else None
        try:
            if options:
                await self._channel.send(inbound.conversation_id, payload, options)
            else:
                await self._channel.send(inbound.conversation_id, payload)
        except TypeError:
            if options:
                await self._channel.send(inbound.conversation_id, payload)
            else:
                raise

    def _publish_event_preview(self, preview: dict[str, Any]) -> None:
        self._last_event_preview = preview
        if not self._event_waiters:
            return
        waiters = list(self._event_waiters)
        self._event_waiters.clear()
        for future in waiters:
            if not future.done():
                future.set_result(preview)

    def _current_connection_snapshot(self) -> dict[str, Any]:
        if self._channel is not None:
            snapshot = _connection_snapshot_dict(self._channel)
            if snapshot:
                self._last_connection_snapshot = snapshot
                return snapshot
        return dict(self._last_connection_snapshot)


async def _maybe_close(channel: Any) -> None:
    for name in ("stop_background", "close", "disconnect", "shutdown"):
        method = getattr(channel, name, None)
        if method is None:
            continue
        result = method()
        if inspect.isawaitable(result):
            await result
        return


def _coalesce(raw_message: Any, raw_payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw_payload and raw_payload[name] is not None:
            return raw_payload[name]
        if hasattr(raw_message, name):
            value = getattr(raw_message, name)
            if value is not None:
                return value
    return None


def _extract_text(raw_message: Any, raw_payload: dict[str, Any]) -> str:
    direct = _coalesce(raw_message, raw_payload, "safe_content_text", "content_text", "text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    content = _coalesce(raw_message, raw_payload, "content", "body")
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if isinstance(parsed, dict):
            text = parsed.get("text")
            if isinstance(text, str):
                return text.strip()
    return ""


def _to_payload(raw_message: Any) -> dict[str, Any]:
    if isinstance(raw_message, dict):
        return raw_message
    if hasattr(raw_message, "model_dump"):
        try:
            dumped = raw_message.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
    data = getattr(raw_message, "__dict__", None)
    if isinstance(data, dict):
        return {key: value for key, value in data.items() if not key.startswith("_")}
    return {}


def _extract_sender_display_name(raw_message: Any, raw_payload: dict[str, Any]) -> str | None:
    sender = getattr(raw_message, "sender", None)
    if sender is not None:
        for attr in ("name", "display_name", "sender_name"):
            value = getattr(sender, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        user = getattr(sender, "user", None)
        if user is not None:
            for attr in ("name", "display_name"):
                value = getattr(user, attr, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    for value in (
        _deep_get(raw_payload, "sender", "name"),
        _deep_get(raw_payload, "sender", "display_name"),
        _deep_get(raw_payload, "sender", "sender_name"),
        _deep_get(raw_payload, "sender", "user", "name"),
        _deep_get(raw_payload, "sender", "user", "display_name"),
        raw_payload.get("sender_name"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_chat_display_name(raw_message: Any, raw_payload: dict[str, Any]) -> str | None:
    conversation = getattr(raw_message, "conversation", None)
    if conversation is not None:
        for attr in ("chat_name", "name", "title"):
            value = getattr(conversation, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for value in (
        _deep_get(raw_payload, "conversation", "chat_name"),
        _deep_get(raw_payload, "conversation", "name"),
        _deep_get(raw_payload, "chat_name"),
        _deep_get(raw_payload, "chat", "name"),
        _deep_get(raw_payload, "chat", "chat_name"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _deep_get(mapping: dict[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _local_date_string() -> str:
    return datetime.now().astimezone().date().isoformat()


def _monotonic_now() -> float:
    return time.monotonic()


def _connection_snapshot_dict(channel: Any) -> dict[str, Any]:
    snapshot = getattr(channel, "connection_snapshot", None)
    if snapshot is None:
        return {}
    try:
        value = snapshot()
    except Exception:
        return {}
    data: dict[str, Any] = {}
    for name in (
        "state",
        "ready",
        "reconnect_attempts",
        "last_connected_at",
        "last_disconnected_at",
        "last_error_at",
        "last_error",
    ):
        field = getattr(value, name, None)
        if name.endswith("_at"):
            data[name] = _epoch_to_utc(field)
        else:
            data[name] = field
    ws_client = getattr(channel, "_ws_client", None)
    if ws_client is not None:
        conn = getattr(ws_client, "_conn", None)
        conn_id = getattr(ws_client, "_conn_id", None)
        if conn is not None:
            data["ready"] = True
            if not data.get("state") or data.get("state") == "idle":
                data["state"] = "connected"
        if conn_id:
            data["connection_id"] = conn_id
    return data


def _epoch_to_utc(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat()
    except Exception:
        return None


def _event_preview(raw_message: Any) -> dict[str, Any]:
    raw_payload = _to_payload(raw_message)
    conversation = getattr(raw_message, "conversation", None)
    sender = getattr(raw_message, "sender", None)
    return {
        "received_at": _utc_now(),
        "message_id": str(getattr(raw_message, "id", None) or _coalesce(raw_message, raw_payload, "message_id", "id") or ""),
        "chat_id": str(getattr(conversation, "chat_id", None) or _coalesce(raw_message, raw_payload, "chat_id") or ""),
        "chat_type": str(getattr(conversation, "chat_type", None) or _coalesce(raw_message, raw_payload, "chat_type") or ""),
        "thread_id": str(getattr(conversation, "thread_id", None) or _coalesce(raw_message, raw_payload, "thread_id", "root_id", "parent_id") or ""),
        "sender_open_id": str(getattr(sender, "open_id", None) or _coalesce(raw_message, raw_payload, "sender_open_id", "open_id", "user_open_id") or ""),
        "text_preview": _extract_text(raw_message, raw_payload)[:200],
        "mentioned_bot": bool(getattr(raw_message, "mentioned_bot", None)),
    }


def _normalize_domain_origin(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "https://open.feishu.cn"
    lowered = raw.lower().rstrip("/")
    if lowered == "feishu":
        return "https://open.feishu.cn"
    if lowered in {"lark", "larksuite"}:
        return "https://open.larksuite.com"

    parsed = urllib.parse.urlsplit(raw)
    if not parsed.scheme:
        return raw.rstrip("/")
    if parsed.path in {"", "/"} and not parsed.query and not parsed.fragment:
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    return raw.rstrip("/")
