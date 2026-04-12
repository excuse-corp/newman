from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware.error_handler import install_error_handlers
from backend.api.routes.sessions import router as sessions_router
from backend.config.schema import AppConfig, ModelConfig
from backend.memory.checkpoint_store import CheckpointStore
from backend.memory.compressor import summarize_messages
from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse, TokenUsage
from backend.providers.factory import MockProvider
from backend.sessions.models import SessionMessage, SessionRecord
from backend.sessions.session_store import SessionStore
from backend.usage.models import ModelUsageRecord


class _RecordingProvider(BaseProvider):
    def __init__(self, content: str = "## Current Progress\n- Checked the relevant files.") -> None:
        self.content = content
        self.calls: list[list[dict[str, object]]] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        return ProviderResponse(
            content=self.content,
            usage=TokenUsage(input_tokens=120, output_tokens=48, total_tokens=168),
            model="recording-model",
        )

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages):
        return 0


def _build_session(message_count: int) -> SessionRecord:
    messages = []
    for index in range(message_count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append(
            SessionMessage(
                id=f"msg-{index}",
                role=role,
                content=f"{role} message {index}",
            )
        )
    return SessionRecord(
        session_id="session-1",
        title="Compression Test",
        messages=messages,
    )


class CompressionSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summarize_messages_uses_llm_handoff_summary(self) -> None:
        provider = _RecordingProvider()
        session = _build_session(6)
        config = ModelConfig(type="openai_compatible", model="recording-model", context_window=100_000)

        result = await summarize_messages(provider, config, config.type, session, preserve_recent=4)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.strategy, "llm_handoff_summary")
        self.assertEqual(result.source_message_count, 2)
        self.assertEqual(result.model, "recording-model")
        self.assertEqual(result.summary, "## Current Progress\n- Checked the relevant files.")
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("messages_to_compact", provider.calls[0][1]["content"])
        self.assertIn("preserved_recent_messages", provider.calls[0][1]["content"])

    async def test_summarize_messages_falls_back_for_mock_provider(self) -> None:
        provider = MockProvider()
        session = _build_session(6)
        config = ModelConfig(type="mock", model="newman-dev", context_window=100_000)

        result = await summarize_messages(provider, config, config.type, session, preserve_recent=4)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.strategy, "fallback_archived_snapshot")
        self.assertEqual(result.source_message_count, 2)
        self.assertEqual(result.fallback_reason, "mock_provider")
        self.assertIn("## Archived Message Snapshot", result.summary)

    async def test_summarize_messages_returns_none_when_no_history_can_be_pruned(self) -> None:
        provider = _RecordingProvider()
        session = _build_session(4)
        config = ModelConfig(type="openai_compatible", model="recording-model", context_window=100_000)

        result = await summarize_messages(provider, config, config.type, session, preserve_recent=4)

        self.assertIsNone(result)
        self.assertEqual(provider.calls, [])


class CompressRouteTests(unittest.TestCase):
    def test_manual_compress_trims_session_and_saves_checkpoint_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            session_store = SessionStore(sessions_dir)
            checkpoints = CheckpointStore(sessions_dir)
            session = _build_session(6)
            session_store.save(session, touch_updated_at=False)

            app = FastAPI()
            app.state.runtime = SimpleNamespace(
                session_store=session_store,
                checkpoints=checkpoints,
                provider=_RecordingProvider(),
                settings=AppConfig.model_validate({"models": {"primary": {"type": "openai_compatible", "model": "recording-model", "context_window": 100000}}}),
                usage_store=None,
            )
            install_error_handlers(app)
            app.include_router(sessions_router)
            client = TestClient(app)

            response = client.post(f"/api/sessions/{session.session_id}/compress")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["compressed"])
            self.assertEqual(len(payload["session"]["messages"]), 4)
            self.assertEqual(payload["checkpoint"]["metadata"]["summary_strategy"], "llm_handoff_summary")
            self.assertEqual(payload["checkpoint"]["metadata"]["compressed_message_count"], 2)

            saved_session = session_store.get(session.session_id)
            self.assertEqual(len(saved_session.messages), 4)
            self.assertTrue(saved_session.metadata["checkpoint_active"])

    def test_get_session_prefers_latest_context_usage_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            session_store = SessionStore(sessions_dir)
            session = _build_session(6)
            session_store.save(session, touch_updated_at=False)

            class _UsageStore:
                def latest_context_record(self, session_id: str):
                    return ModelUsageRecord(
                        request_id="req-1",
                        session_id=session_id,
                        request_kind="session_turn",
                        counts_toward_context_window=True,
                        streaming=True,
                        provider_type="openai_compatible",
                        model="recording-model",
                        context_window=100000,
                        effective_context_window=95000,
                        usage_available=True,
                        input_tokens=800,
                        output_tokens=200,
                        total_tokens=1000,
                        created_at="2026-04-11T00:00:00Z",
                    )

            app = FastAPI()
            app.state.runtime = SimpleNamespace(
                session_store=session_store,
                checkpoints=CheckpointStore(sessions_dir),
                provider=_RecordingProvider(),
                settings=AppConfig.model_validate(
                    {"models": {"primary": {"type": "openai_compatible", "model": "recording-model", "context_window": 100000}}}
                ),
                usage_store=_UsageStore(),
            )
            install_error_handlers(app)
            app.include_router(sessions_router)
            client = TestClient(app)

            response = client.get(f"/api/sessions/{session.session_id}")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            context_usage = payload["context_usage"]
            self.assertEqual(context_usage["estimated_tokens"], 1000)
            self.assertEqual(context_usage["context_window"], 95000)
            self.assertEqual(context_usage["source"], "latest_request_usage")
            self.assertEqual(context_usage["request_kind"], "session_turn")


if __name__ == "__main__":
    unittest.main()
