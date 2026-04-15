from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

fake_psycopg = types.ModuleType("psycopg")
fake_psycopg.connect = lambda *args, **kwargs: None
fake_rows = types.ModuleType("psycopg.rows")
fake_rows.dict_row = object()
fake_types = types.ModuleType("psycopg.types")
fake_json = types.ModuleType("psycopg.types.json")
fake_json.Jsonb = lambda value: value
fake_chromadb = types.ModuleType("chromadb")


class _FakeCollection:
    def upsert(self, *args, **kwargs):
        return None

    def delete(self, *args, **kwargs):
        return None

    def query(self, *args, **kwargs):
        return {"ids": [[]], "distances": [[]], "metadatas": [[]], "documents": [[]]}


class _FakePersistentClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_or_create_collection(self, *args, **kwargs):
        return _FakeCollection()


fake_chromadb.PersistentClient = _FakePersistentClient
sys.modules.setdefault("psycopg", fake_psycopg)
sys.modules.setdefault("psycopg.rows", fake_rows)
sys.modules.setdefault("psycopg.types", fake_types)
sys.modules.setdefault("psycopg.types.json", fake_json)
sys.modules.setdefault("chromadb", fake_chromadb)

from backend.providers.base import ProviderChunk, ProviderResponse, TokenUsage, ToolCall
from backend.runtime.run_loop import NewmanRuntime
from backend.runtime.result_normalizer import normalize_result
from backend.runtime.session_task import SessionTask
from backend.sessions.models import SessionMessage, SessionRecord
from backend.sessions.session_store import SessionStore
from backend.tools.permission_context import PermissionContext
from backend.tools.result import ToolExecutionResult


class _DummyApproval:
    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {}


class _DummyPromptAssembler:
    def assemble(self, session, tools_overview, approval_policy, checkpoint):
        return [{"role": "system", "content": "test"}]


class _DummyHookManager:
    def messages_for(self, event: str) -> list[str]:
        return []

    async def handler_messages_for(self, event: str, data: dict[str, object]) -> list[str]:
        return []


class _DummyProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        yield ProviderChunk(type="text", delta="智能体是能够感知环境、做出决策并执行动作以达成目标的系统。")
        yield ProviderChunk(type="done", finish_reason="stop", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyCommentaryProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="text", delta="<commentary>我先定位相关文件</commentary>")
        yield ProviderChunk(type="text", delta="<think>先理一下上下文</think>")
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(id="tool-1", name="search_files", arguments={"pattern": "group_id"}),
        )
        yield ProviderChunk(type="done", finish_reason="tool_calls", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyThinkingFallbackProvider:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.chat_calls.append({"messages": messages, "tools": tools})
        return ProviderResponse(
            content="<commentary>我先读取目标文件</commentary>",
            usage=TokenUsage(),
            model="dummy-model",
            finish_reason="stop",
        )

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="text", delta="<think>先读取目标文件并确认开头内容</think>\n\n")
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(id="tool-1", name="read_file", arguments={"path": "/tmp/demo.txt", "limit": 5}),
        )
        yield ProviderChunk(type="done", finish_reason="tool_calls", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyHookManagerWithMessage:
    def messages_for(self, event: str) -> list[str]:
        return [f"{event} hook"]

    async def handler_messages_for(self, event: str, data: dict[str, object]) -> list[str]:
        return []


class FatalToolFinalizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fatal_tool_error_still_emits_final_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            session_store = SessionStore(sessions_dir)
            session = SessionRecord(
                session_id="session-1",
                title="智能体",
                messages=[
                    SessionMessage(id="user-1", role="user", content="告诉我什么叫智能体", metadata={"turn_id": "turn-1"})
                ],
            )
            session_store.save(session, touch_updated_at=False)

            runtime = object.__new__(NewmanRuntime)
            runtime.provider = _DummyProvider()
            runtime.usage_store = None
            runtime.session_store = session_store
            runtime.prompt_assembler = _DummyPromptAssembler()
            runtime.checkpoints = SimpleNamespace(get=lambda session_id: None)
            runtime.hook_manager = _DummyHookManager()
            runtime.settings = SimpleNamespace(
                provider=SimpleNamespace(
                    model="dummy-model",
                    type="mock",
                    context_window=None,
                    effective_context_window=None,
                ),
                approval=_DummyApproval(),
            )
            runtime._tools_overview = lambda: "tools"

            task = SessionTask(session=session, permission_context=PermissionContext(), turn_id="turn-1")
            result = normalize_result(
                ToolExecutionResult(
                    success=False,
                    tool="search_knowledge_base",
                    action="search",
                    category="runtime_exception",
                    summary="Collection expecting embedding with dimension of 256, got 4096",
                )
            )

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime._finalize_fatal_tool_error(task, emit, result, request_id="req-1")

            saved = session_store.get("session-1")
            self.assertEqual(saved.messages[-1].role, "assistant")
            self.assertIn("智能体是能够感知环境", saved.messages[-1].content)
            self.assertTrue(any(event == "final_response" for event, _ in events))
            self.assertEqual(runtime.provider.calls[0]["tools"], [])


class CommentaryStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_response_emits_grouped_commentary_before_tool_execution(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyCommentaryProvider()
        runtime.usage_store = None
        runtime.settings = SimpleNamespace(
            provider=SimpleNamespace(
                model="dummy-model",
                type="mock",
                context_window=None,
                effective_context_window=None,
            )
        )

        events: list[tuple[str, dict[str, object]]] = []

        async def emit(event: str, data: dict[str, object]) -> None:
            events.append((event, data))

        response = await runtime._stream_provider_response(
            [{"role": "system", "content": "test"}],
            [{"name": "search_files"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:1",
        )

        self.assertEqual(response.commentary, "我先定位相关文件")
        self.assertEqual(response.content, "")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(
            [event for event, _ in events],
            ["thinking_delta", "thinking_complete", "commentary_delta", "commentary_complete"],
        )
        self.assertEqual(events[2][1]["group_id"], "turn-1:group:1")
        self.assertEqual(events[2][1]["content"], "我先定位相关文件")

    async def test_missing_commentary_uses_thinking_fallback_brief(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyThinkingFallbackProvider()
        runtime.usage_store = None
        runtime.settings = SimpleNamespace(
            provider=SimpleNamespace(
                model="dummy-model",
                type="mock",
                context_window=None,
                effective_context_window=None,
            )
        )

        session = SessionRecord(
            session_id="session-1",
            title="Fallback Test",
            messages=[
                SessionMessage(
                    id="user-1",
                    role="user",
                    content="请读取 /tmp/demo.txt 的前 5 行",
                    metadata={"turn_id": "turn-1"},
                )
            ],
        )
        task = SessionTask(session=session, permission_context=PermissionContext(), turn_id="turn-1")

        events: list[tuple[str, dict[str, object]]] = []

        async def emit(event: str, data: dict[str, object]) -> None:
            events.append((event, data))

        response = await runtime._stream_provider_response(
            [{"role": "system", "content": "test"}],
            [{"name": "read_file"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:1",
        )
        response = await runtime._ensure_tool_response_commentary(
            task,
            response,
            emit,
            group_id="turn-1:group:1",
        )

        self.assertEqual(response.thinking, "先读取目标文件并确认开头内容")
        self.assertEqual(response.commentary, "我先读取目标文件")
        self.assertEqual(
            [event for event, _ in events],
            ["thinking_delta", "thinking_complete", "assistant_delta", "commentary_delta", "commentary_complete"],
        )
        self.assertEqual(runtime.provider.chat_calls[0]["tools"], [])

    async def test_emit_hooks_carries_group_id_for_skill_timeline(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.hook_manager = _DummyHookManagerWithMessage()

        events: list[tuple[str, dict[str, object]]] = []

        async def emit(event: str, data: dict[str, object]) -> None:
            events.append((event, data))

        await runtime._emit_hooks("PreToolUse", emit, group_id="turn-1:group:2", tool="search_files")

        self.assertEqual(events[0][0], "hook_triggered")
        self.assertEqual(events[0][1]["group_id"], "turn-1:group:2")
        self.assertEqual(events[0][1]["event"], "PreToolUse")


if __name__ == "__main__":
    unittest.main()
