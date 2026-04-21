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
    def assemble(self, session, tools_overview, checkpoint, tool_message_overrides=None):
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


class _DummyToolMarkupProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        yield ProviderChunk(
            type="text",
            delta=(
                "查看 docs 目录下的产品文档\n"
                "<minimax:tool_call>\n"
                "<invoke name=\"list_dir\">\n"
                "<parameter name=\"path\">/root/newman/docs</parameter>\n"
                "</invoke>\n"
                "</minimax:tool_call>"
            ),
        )
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
            tool_call=ToolCall(id="tool-1", name="read_file_range", arguments={"path": "/tmp/demo.txt", "offset": 1, "limit": 5}),
        )
        yield ProviderChunk(type="done", finish_reason="tool_calls", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyLeakyToolPreambleProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="text", delta="再读取 README 了解产品整体介绍")
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(id="tool-1", name="read_file", arguments={"path": "/root/newman/README.md"}),
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
            checkpoint_calls: list[str] = []

            async def fake_maybe_checkpoint(task, emit):
                checkpoint_calls.append(task.turn_id)

            runtime._maybe_checkpoint = fake_maybe_checkpoint
            runtime.settings = SimpleNamespace(
                provider=SimpleNamespace(
                    model="dummy-model",
                    type="mock",
                    context_window=None,
                    effective_context_window=None,
                ),
                approval=_DummyApproval(),
                runtime=SimpleNamespace(max_tool_depth=30),
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
            self.assertEqual(checkpoint_calls, ["turn-1"])

    async def test_fatal_tool_error_falls_back_when_model_returns_tool_markup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            session_store = SessionStore(sessions_dir)
            session = SessionRecord(
                session_id="session-1",
                title="审批失败",
                messages=[
                    SessionMessage(id="user-1", role="user", content="根据产品文档告诉我产品用途", metadata={"turn_id": "turn-1"})
                ],
            )
            session_store.save(session, touch_updated_at=False)

            runtime = object.__new__(NewmanRuntime)
            runtime.provider = _DummyToolMarkupProvider()
            runtime.usage_store = None
            runtime.session_store = session_store
            runtime.prompt_assembler = _DummyPromptAssembler()
            runtime.checkpoints = SimpleNamespace(get=lambda session_id: None)
            runtime.hook_manager = _DummyHookManager()

            async def fake_maybe_checkpoint(task, emit):
                return None

            runtime._maybe_checkpoint = fake_maybe_checkpoint
            runtime.settings = SimpleNamespace(
                provider=SimpleNamespace(
                    model="dummy-model",
                    type="mock",
                    context_window=None,
                    effective_context_window=None,
                ),
                approval=_DummyApproval(),
                runtime=SimpleNamespace(max_tool_depth=30),
            )
            runtime._tools_overview = lambda: "tools"

            task = SessionTask(session=session, permission_context=PermissionContext(), turn_id="turn-1")
            result = normalize_result(
                ToolExecutionResult(
                    success=False,
                    tool="terminal",
                    action="approval",
                    category="user_rejected",
                    summary="用户拒绝或审批超时",
                )
            )

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime._finalize_fatal_tool_error(task, emit, result, request_id="req-1")

            saved = session_store.get("session-1")
            self.assertNotIn("<minimax:tool_call>", saved.messages[-1].content)
            self.assertEqual(saved.messages[-1].content, "工具调用申请被用户拒绝或审批超时，当前任务已终止")
            final_response_payload = next(data for event, data in events if event == "final_response")
            self.assertEqual(final_response_payload["content"], "工具调用申请被用户拒绝或审批超时，当前任务已终止")

    async def test_tool_limit_finalize_runs_checkpoint_check_before_final_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            session_store = SessionStore(sessions_dir)
            session = SessionRecord(
                session_id="session-1",
                title="工具上限",
                messages=[
                    SessionMessage(id="user-1", role="user", content="继续处理", metadata={"turn_id": "turn-1"})
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
            checkpoint_calls: list[str] = []

            async def fake_maybe_checkpoint(task, emit):
                checkpoint_calls.append(task.turn_id)

            runtime._maybe_checkpoint = fake_maybe_checkpoint
            runtime.settings = SimpleNamespace(
                provider=SimpleNamespace(
                    model="dummy-model",
                    type="mock",
                    context_window=None,
                    effective_context_window=None,
                ),
                approval=_DummyApproval(),
                runtime=SimpleNamespace(max_tool_depth=3),
            )
            runtime._tools_overview = lambda: "tools"

            task = SessionTask(session=session, permission_context=PermissionContext(), turn_id="turn-1")

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime._finalize_tool_limit(task, emit, request_id="req-2")

            saved = session_store.get("session-1")
            self.assertEqual(saved.messages[-1].role, "assistant")
            self.assertTrue(any(event == "final_response" for event, _ in events))
            self.assertEqual(checkpoint_calls, ["turn-1"])


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
            [{"name": "read_file_range"}],
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
            ["thinking_delta", "thinking_complete", "commentary_delta", "commentary_complete"],
        )
        self.assertEqual(runtime.provider.chat_calls[0]["tools"], [])

    async def test_tool_preamble_answer_is_reclaimed_into_commentary(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyLeakyToolPreambleProvider()
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
            [{"name": "read_file"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:1",
        )

        self.assertEqual(response.content, "")
        self.assertEqual(response.commentary, "再读取 README 了解产品整体介绍")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(
            [event for event, _ in events],
            ["assistant_delta", "assistant_delta", "commentary_delta", "commentary_complete"],
        )
        self.assertEqual(events[1][1]["content"], "")
        self.assertEqual(events[1][1]["reset"], True)
        self.assertEqual(events[2][1]["content"], "再读取 README 了解产品整体介绍")

    async def test_tool_backed_turn_does_not_emit_answer_started_before_followup_tool_call(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyLeakyToolPreambleProvider()
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
            [{"name": "read_file"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:2",
            emit_answer_started=True,
        )

        self.assertEqual(response.content, "")
        self.assertEqual(response.commentary, "再读取 README 了解产品整体介绍")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual([event for event, _ in events], ["commentary_delta", "commentary_complete"])
        self.assertFalse(any(event == "answer_started" for event, _ in events))

    async def test_answer_started_emits_once_when_tool_backed_turn_enters_final_answer(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyProvider()
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
            [{"name": "read_file"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:final",
            emit_answer_started=True,
        )

        self.assertEqual(response.content, "智能体是能够感知环境、做出决策并执行动作以达成目标的系统。")
        self.assertEqual([event for event, _ in events], ["answer_started", "assistant_delta"])
        self.assertEqual(events[0][1]["group_id"], "turn-1:group:final")
        self.assertEqual(events[1][1]["content"], response.content)

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


class ToolResultPersistenceTests(unittest.TestCase):
    def test_build_tool_session_message_persists_summary_but_keeps_transient_full_output(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        task = SessionTask(
            session=SessionRecord(session_id="session-1", title="Persist Test", messages=[]),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )
        result = ToolExecutionResult(
            success=True,
            tool="read_file",
            action="read",
            summary="已读取文件 README.md（10 字节）",
            stdout='{"dataBase64":"UkVBRE1FCg=="}',
            persisted_output='{"summary":"Read complete file README.md; raw content omitted from persisted history"}',
        )

        message = runtime._build_tool_session_message(
            task,
            result,
            tool_call_id="call-1",
            group_id="turn-1:group:1",
            request_id="req-1",
        )

        self.assertEqual(
            message.content,
            '{"summary":"Read complete file README.md; raw content omitted from persisted history"}',
        )
        self.assertFalse(message.metadata["content_persisted"])
        self.assertEqual(task.transient_tool_messages["call-1"].content, '{"dataBase64":"UkVBRE1FCg=="}')

    def test_build_tool_session_message_uses_single_copy_when_output_matches(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        task = SessionTask(
            session=SessionRecord(session_id="session-1", title="Persist Test", messages=[]),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )
        result = ToolExecutionResult(
            success=True,
            tool="search_files",
            action="search",
            summary="命中 1 条结果",
            stdout="README.md:1: Newman",
        )

        message = runtime._build_tool_session_message(
            task,
            result,
            tool_call_id="call-2",
            group_id="turn-1:group:1",
            request_id=None,
        )

        self.assertEqual(message.content, "README.md:1: Newman")
        self.assertTrue(message.metadata["content_persisted"])
        self.assertNotIn("call-2", task.transient_tool_messages)

    def test_build_tool_session_message_merges_terminal_stdout_and_stderr(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        task = SessionTask(
            session=SessionRecord(session_id="session-1", title="Persist Test", messages=[]),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )
        result = ToolExecutionResult(
            success=False,
            tool="terminal",
            action="execute",
            summary="执行失败",
            stdout="first line\n",
            stderr="warn line\n",
        )

        message = runtime._build_tool_session_message(
            task,
            result,
            tool_call_id="call-3",
            group_id="turn-1:group:3",
            request_id=None,
        )

        self.assertEqual(message.content, "first line\nwarn line")
        self.assertTrue(message.metadata["content_persisted"])


if __name__ == "__main__":
    unittest.main()
