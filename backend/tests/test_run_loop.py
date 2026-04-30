from __future__ import annotations

import json
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

from backend.providers.base import ProviderChunk, ProviderError, ProviderResponse, TokenUsage, ToolCall
from backend.runtime.run_loop import NewmanRuntime
from backend.runtime.result_normalizer import normalize_result
from backend.runtime.session_task import SessionTask
from backend.sessions.models import SessionMessage, SessionRecord
from backend.sessions.session_store import SessionStore
from backend.tools.impl.read_file import ReadFileTool
from backend.tools.impl.write_file import WriteFileTool
from backend.tools.permission_context import PermissionContext
from backend.tools.registry import ToolRegistry
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


class _DummyMultiChunkProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="text", delta="第一段结论，")
        yield ProviderChunk(type="text", delta="第二段结论。")
        yield ProviderChunk(type="done", finish_reason="stop", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyMarkdownImageProvider:
    def __init__(self, content: str) -> None:
        self.content = content

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(type="text", delta=self.content)
        yield ProviderChunk(type="done", finish_reason="stop", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyEmptyStreamProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls += 1
        yield ProviderChunk(type="done", finish_reason="stop", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyRetryThenSuccessProvider:
    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise ProviderError("openai_compatible", "upstream_error", "openai_compatible upstream server error", True)
        yield ProviderChunk(type="text", delta="恢复成功")
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


class PostUserMessageHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_user_message_updates_turn_before_first_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            session_store = SessionStore(sessions_dir)
            session = session_store.create(title="image-first")

            runtime = object.__new__(NewmanRuntime)
            runtime.provider = _DummyProvider()
            runtime.usage_store = None
            runtime.session_store = session_store
            runtime.hook_manager = _DummyHookManager()
            runtime.skill_registry = SimpleNamespace(sync_snapshot=lambda: None)
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
            runtime.reload_ecosystem = lambda: None
            runtime.memory_extractor = SimpleNamespace(looks_like_explicit_persistence_signal=lambda content: False)
            runtime._tools_overview = lambda: "tools"
            runtime._assemble_task_messages = lambda task: [{"role": "user", "content": task.session.messages[-1].content}]
            runtime._provider_tools_for_turn = lambda task: []
            runtime.checkpoints = SimpleNamespace(get=lambda session_id: None)

            async def fake_maybe_checkpoint(task, emit):
                return None

            runtime._maybe_checkpoint = fake_maybe_checkpoint

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            async def post_user_message(task, user_message, turn_emit) -> None:
                user_message.content = "更新后的用户消息"
                runtime.session_store.save(task.session)

            await runtime.handle_message(
                session.session_id,
                "原始用户消息",
                emit,
                turn_id="turn-1",
                post_user_message=post_user_message,
            )

            saved = session_store.get(session.session_id)
            self.assertEqual(saved.messages[0].content, "更新后的用户消息")
            self.assertEqual(runtime.provider.calls[0]["messages"][0]["content"], "更新后的用户消息")
            self.assertTrue(any(event == "final_response" for event, _ in events))


class ProviderFailureHandlingTests(unittest.IsolatedAsyncioTestCase):
    def _build_runtime(self, session_store: SessionStore, provider) -> NewmanRuntime:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = provider
        runtime.usage_store = None
        runtime.session_store = session_store
        runtime.hook_manager = _DummyHookManager()
        runtime.skill_registry = SimpleNamespace(sync_snapshot=lambda: None)
        runtime.settings = SimpleNamespace(
            provider=SimpleNamespace(
                model="dummy-model",
                type="openai_compatible",
                context_window=None,
                effective_context_window=None,
            ),
            approval=_DummyApproval(),
            runtime=SimpleNamespace(
                max_tool_depth=30,
                tool_retry_attempts=2,
                tool_retry_backoff_seconds=0.0,
            ),
        )
        runtime.reload_ecosystem = lambda: None
        runtime.memory_extractor = SimpleNamespace(looks_like_explicit_persistence_signal=lambda content: False)
        runtime._tools_overview = lambda: "tools"
        runtime._assemble_task_messages = lambda task: [{"role": "user", "content": task.session.messages[-1].content}]
        runtime._provider_tools_for_turn = lambda task: []
        runtime.checkpoints = SimpleNamespace(get=lambda session_id: None)

        async def fake_maybe_checkpoint(task, emit):
            return None

        runtime._maybe_checkpoint = fake_maybe_checkpoint
        return runtime

    async def test_empty_provider_response_retries_then_persists_failure_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_store = SessionStore(Path(tmp))
            session = session_store.create(title="empty-provider")
            provider = _DummyEmptyStreamProvider()
            runtime = self._build_runtime(session_store, provider)

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime.handle_message(
                session.session_id,
                "请继续",
                emit,
                turn_id="turn-1",
                request_id="req-1",
            )

            saved = session_store.get(session.session_id)
            self.assertEqual(provider.calls, 3)
            self.assertEqual(saved.messages[-1].role, "assistant")
            self.assertIn("主模型本次响应异常，未返回任何内容", saved.messages[-1].content)
            self.assertIn("已重试 2 次", saved.messages[-1].content)
            self.assertNotIn("原因：", saved.messages[-1].content)
            self.assertNotIn("详情：", saved.messages[-1].content)
            self.assertTrue(any(event == "error" for event, _ in events))
            final_response_payload = next(data for event, data in events if event == "final_response")
            self.assertIn("主模型本次响应异常，未返回任何内容", final_response_payload["content"])
            error_payload = next(data for event, data in events if event == "error")
            self.assertEqual(error_payload["category"], "empty_response")
            self.assertEqual(error_payload["message"], "主模型响应异常")
            self.assertEqual(error_payload["attempt_count"], 3)
            self.assertEqual(error_payload["max_attempts"], 3)

    async def test_retryable_provider_error_recovers_before_user_visible_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_store = SessionStore(Path(tmp))
            session = session_store.create(title="retry-provider")
            provider = _DummyRetryThenSuccessProvider(failures_before_success=2)
            runtime = self._build_runtime(session_store, provider)

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime.handle_message(
                session.session_id,
                "请继续",
                emit,
                turn_id="turn-1",
                request_id="req-1",
            )

            saved = session_store.get(session.session_id)
            self.assertEqual(provider.calls, 3)
            self.assertEqual(saved.messages[-1].role, "assistant")
            self.assertEqual(saved.messages[-1].content, "恢复成功")
            self.assertEqual([event for event, _ in events if event in {"final_response", "error"}], ["final_response"])

    async def test_final_response_persists_local_markdown_image_as_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            artifacts = workspace / "artifacts"
            artifacts.mkdir(parents=True)
            image_path = artifacts / "result.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nmock")

            session_store = SessionStore(root / "sessions")
            session = session_store.create(title="image-response")
            provider = _DummyMarkdownImageProvider("![结果图](artifacts/result.png)")
            runtime = self._build_runtime(session_store, provider)
            runtime.settings.paths = SimpleNamespace(workspace=workspace)

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime.handle_message(
                session.session_id,
                "生成一张图",
                emit,
                turn_id="turn-1",
                request_id="req-1",
            )

            saved = session_store.get(session.session_id)
            assistant = saved.messages[-1]
            attachments = assistant.metadata.get("attachments")
            self.assertIsInstance(attachments, list)
            self.assertEqual(len(attachments), 1)
            attachment = attachments[0]
            self.assertEqual(attachment["source"], "assistant_output")
            self.assertEqual(attachment["path"], str(image_path.resolve()))
            self.assertEqual(attachment["workspace_relative_path"], "artifacts/result.png")

            final_response_payload = next(data for event, data in events if event == "final_response")
            self.assertEqual(final_response_payload["attachments"], attachments)


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

    async def test_user_rejected_approval_stops_without_streaming_followup_answer(self) -> None:
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
            self.assertEqual(runtime.provider.calls, [])
            self.assertEqual(checkpoint_calls, [])
            self.assertFalse(any(event == "answer_started" for event, _ in events))
            self.assertFalse(any(event == "assistant_delta" for event, _ in events))
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

    async def test_tool_backed_turn_resets_transient_answer_before_followup_tool_call(self) -> None:
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
            emit_answer_started_event=True,
        )

        self.assertEqual(response.content, "")
        self.assertEqual(response.commentary, "再读取 README 了解产品整体介绍")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(
            [event for event, _ in events],
            ["answer_started", "assistant_delta", "assistant_delta", "commentary_delta", "commentary_complete"],
        )
        self.assertEqual(events[1][1]["content"], "再读取 README 了解产品整体介绍")
        self.assertTrue(events[2][1]["reset"])
        self.assertEqual(events[3][1]["content"], "再读取 README 了解产品整体介绍")

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
            emit_answer_started_event=True,
        )

        self.assertEqual(response.content, "智能体是能够感知环境、做出决策并执行动作以达成目标的系统。")
        self.assertEqual([event for event, _ in events], ["answer_started", "assistant_delta"])
        self.assertEqual(events[0][1]["group_id"], "turn-1:group:final")
        self.assertEqual(events[1][1]["content"], response.content)

    async def test_tool_backed_final_answer_streams_incremental_content(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyMultiChunkProvider()
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
            group_id="turn-1:group:stream",
            emit_answer_started_event=True,
        )

        self.assertEqual(response.content, "第一段结论，第二段结论。")
        self.assertEqual([event for event, _ in events], ["answer_started", "assistant_delta", "assistant_delta"])
        self.assertEqual(events[1][1]["delta"], "第一段结论，")
        self.assertEqual(events[2][1]["delta"], "第二段结论。")
        self.assertEqual(events[2][1]["content"], response.content)

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


class CollaborationModeRuntimeTests(unittest.TestCase):
    def test_current_turn_user_content_prefers_multimodal_normalized_input(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        session = SessionRecord(
            session_id="session-1",
            title="multimodal",
            messages=[
                SessionMessage(
                    id="user-1",
                    role="user",
                    content="看看这张图",
                    metadata={
                        "turn_id": "turn-1",
                        "original_content": "看看这张图",
                        "multimodal_parse": {
                            "schema_version": "v1",
                            "status": "completed",
                            "normalized_user_input": "请结合截图解释报错并给出排查方向。",
                        },
                    },
                )
            ],
        )

        self.assertEqual(
            runtime._current_turn_user_content(session, "turn-1"),
            "请结合截图解释报错并给出排查方向。",
        )

    def test_current_turn_user_content_prefers_attachment_analysis_normalized_input(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        session = SessionRecord(
            session_id="session-1",
            title="attachments",
            messages=[
                SessionMessage(
                    id="user-1",
                    role="user",
                    content="总结附件",
                    metadata={
                        "turn_id": "turn-1",
                        "original_content": "总结附件",
                        "attachment_analysis": {
                            "schema_version": "v1",
                            "status": "completed",
                            "normalized_user_input": "请基于已解析附件总结重点并指出下一步。",
                        },
                    },
                )
            ],
        )

        self.assertEqual(
            runtime._current_turn_user_content(session, "turn-1"),
            "请基于已解析附件总结重点并指出下一步。",
        )

    def test_provider_tools_require_update_plan_first_when_plan_missing(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.registry = SimpleNamespace(
            tools_for_provider=lambda permission_context, active_groups=None: [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "update_plan"}},
                {"type": "function", "function": {"name": "write_file"}},
                {"type": "function", "function": {"name": "enter_plan_mode"}},
                {"type": "function", "function": {"name": "update_plan_draft"}},
                {"type": "function", "function": {"name": "exit_plan_mode"}},
            ]
        )

        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="plan",
                messages=[],
                metadata={
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    }
                },
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        tools = runtime._provider_tools_for_turn(task)

        self.assertEqual(
            [tool["function"]["name"] for tool in tools],
            ["update_plan"],
        )

    def test_provider_tools_allow_execution_after_plan_exists(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.registry = SimpleNamespace(
            tools_for_provider=lambda permission_context, active_groups=None: [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "update_plan"}},
                {"type": "function", "function": {"name": "write_file"}},
                {"type": "function", "function": {"name": "enter_plan_mode"}},
                {"type": "function", "function": {"name": "update_plan_draft"}},
                {"type": "function", "function": {"name": "exit_plan_mode"}},
            ]
        )

        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="plan",
                messages=[],
                metadata={
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                    "plan": {
                        "steps": [
                            {"step": "先拆任务", "status": "in_progress"},
                            {"step": "再执行", "status": "pending"},
                        ],
                        "progress": {
                            "total": 2,
                            "completed": 0,
                            "in_progress": 1,
                            "pending": 1,
                            "blocked": 0,
                            "cancelled": 0,
                        },
                        "current_step": "先拆任务",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                },
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        tools = runtime._provider_tools_for_turn(task)

        self.assertEqual(
            [tool["function"]["name"] for tool in tools],
            ["read_file", "update_plan", "write_file"],
        )

    def test_provider_tools_hide_plan_only_tools_in_default_mode(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.registry = SimpleNamespace(
            tools_for_provider=lambda permission_context, active_groups=None: [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "enter_plan_mode"}},
                {"type": "function", "function": {"name": "update_plan_draft"}},
                {"type": "function", "function": {"name": "exit_plan_mode"}},
            ]
        )

        task = SessionTask(
            session=SessionRecord(session_id="session-1", title="default", messages=[]),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        tools = runtime._provider_tools_for_turn(task)

        self.assertEqual(
            [tool["function"]["name"] for tool in tools],
            ["read_file", "enter_plan_mode"],
        )

    def test_provider_tools_hide_file_browsing_tools_on_first_attachment_answer(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.registry = SimpleNamespace(
            tools_for_provider=lambda permission_context, active_groups=None: [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "read_file_range"}},
                {"type": "function", "function": {"name": "list_dir"}},
                {"type": "function", "function": {"name": "search_files"}},
                {"type": "function", "function": {"name": "enter_plan_mode"}},
                {"type": "function", "function": {"name": "update_plan"}},
            ]
        )

        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="attachments",
                messages=[
                    SessionMessage(
                        id="user-1",
                        role="user",
                        content="介绍这个架构图",
                        metadata={
                            "turn_id": "turn-1",
                            "original_content": "介绍这个架构图",
                            "attachment_analysis": {
                                "schema_version": "v1",
                                "status": "completed",
                                "normalized_user_input": "介绍这个架构图",
                                "attachment_summaries": [
                                    {
                                        "attachment_id": "att-1",
                                        "filename": "diagram.html",
                                        "status": "parsed",
                                        "summary": "这里是架构图摘要",
                                        "markdown_path": "/tmp/diagram.md",
                                    }
                                ],
                                "warnings": [],
                            },
                        },
                    )
                ],
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        tools = runtime._provider_tools_for_turn(task)

        self.assertEqual(
            [tool["function"]["name"] for tool in tools],
            ["enter_plan_mode", "update_plan"],
        )

    def test_provider_tools_keep_file_browsing_tools_after_attachment_turn_has_already_used_tools(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.registry = SimpleNamespace(
            tools_for_provider=lambda permission_context, active_groups=None: [
                {"type": "function", "function": {"name": "read_file"}},
                {"type": "function", "function": {"name": "search_files"}},
            ]
        )

        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="attachments",
                messages=[
                    SessionMessage(
                        id="user-1",
                        role="user",
                        content="介绍附件并继续处理",
                        metadata={
                            "turn_id": "turn-1",
                            "attachment_analysis": {
                                "schema_version": "v1",
                                "status": "completed",
                                "normalized_user_input": "介绍附件并继续处理",
                                "attachment_summaries": [
                                    {"attachment_id": "att-1", "status": "parsed"}
                                ],
                            },
                        },
                    )
                ],
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
            tool_depth=1,
        )

        tools = runtime._provider_tools_for_turn(task)

        self.assertEqual(
            [tool["function"]["name"] for tool in tools],
            ["read_file", "search_files"],
        )

    def test_provider_tools_keep_history_referenced_write_file_for_follow_up_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = object.__new__(NewmanRuntime)
            runtime.registry = ToolRegistry()
            runtime.registry.register(ReadFileTool(Path(tmp)))
            runtime.registry.register(WriteFileTool(Path(tmp)))

            session = SessionRecord(
                session_id="session-1",
                title="continue",
                messages=[
                    SessionMessage(
                        id="u1",
                        role="user",
                        content="写一个 html 页面",
                        metadata={"turn_id": "turn-1"},
                    ),
                    SessionMessage(
                        id="a1",
                        role="assistant",
                        content="我来创建页面。",
                        metadata={
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "name": "write_file",
                                    "arguments": {"path": "./index.html"},
                                }
                            ]
                        },
                    ),
                    SessionMessage(
                        id="u2",
                        role="user",
                        content="继续",
                        metadata={"turn_id": "turn-2"},
                    ),
                ],
            )
            task = SessionTask(
                session=session,
                permission_context=PermissionContext(),
                turn_id="turn-2",
            )

            tools = runtime._provider_tools_for_turn(task)

            self.assertIn("read_file", [tool["function"]["name"] for tool in tools])
            self.assertIn("write_file", [tool["function"]["name"] for tool in tools])

    def test_assemble_task_messages_repairs_invalid_history_tool_call_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = object.__new__(NewmanRuntime)
            runtime.registry = ToolRegistry()
            runtime.registry.register(WriteFileTool(Path(tmp)))
            runtime.prompt_assembler = SimpleNamespace(
                assemble=lambda session, tools_overview, checkpoint, tool_message_overrides=None: [
                    {"role": "system", "content": "test"},
                    {
                        "role": "assistant",
                        "content": "创建文件",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"path":"./index.html","query":"<h1>Hello</h1>"}',
                                },
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "call_1", "content": "缺少必填参数: content"},
                ]
            )
            runtime.checkpoints = SimpleNamespace(get=lambda session_id: None)
            runtime._tools_overview = lambda: "tools"

            task = SessionTask(
                session=SessionRecord(session_id="session-1", title="repair", messages=[]),
                permission_context=PermissionContext(),
                turn_id="turn-1",
            )

            assembled = runtime._assemble_task_messages(task)
            arguments = json.loads(assembled[1]["tool_calls"][0]["function"]["arguments"])

            self.assertEqual(arguments["path"], "./index.html")
            self.assertEqual(arguments["query"], "<h1>Hello</h1>")
            self.assertIn("content", arguments)
            self.assertEqual(arguments["content"], "")

    def test_assemble_task_messages_downgrades_midstream_system_messages_for_openai_provider(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.registry = ToolRegistry()
        runtime.prompt_assembler = SimpleNamespace(
            assemble=lambda session, tools_overview, checkpoint, tool_message_overrides=None: [
                {"role": "system", "content": "top-level system"},
                {"role": "user", "content": "写一个 html 页面"},
                {"role": "system", "content": "tool failure feedback"},
            ]
        )
        runtime.checkpoints = SimpleNamespace(get=lambda session_id: None)
        runtime._tools_overview = lambda: "tools"
        runtime.settings = SimpleNamespace(provider=SimpleNamespace(type="openai_compatible"))

        task = SessionTask(
            session=SessionRecord(session_id="session-1", title="repair", messages=[]),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        assembled = runtime._assemble_task_messages(task)

        self.assertEqual(assembled[0]["role"], "system")
        self.assertEqual(assembled[2]["role"], "user")
        self.assertIn("Runtime system note:", assembled[2]["content"])
        self.assertIn("tool failure feedback", assembled[2]["content"])

    def test_prepare_tool_arguments_hydrates_exit_plan_mode_markdown_from_session(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="plan",
                messages=[],
                metadata={
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                    "plan_draft": {
                        "markdown": "# 方案\n\n- 先实现后端",
                        "status": "draft",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                },
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        prepared = runtime._prepare_tool_arguments(task, "exit_plan_mode", {})

        self.assertEqual(prepared["markdown"], "# 方案\n\n- 先实现后端")

    def test_plan_mode_blocks_execution_until_checklist_exists(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="plan",
                messages=[],
                metadata={
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    }
                },
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        self.assertFalse(runtime._is_tool_allowed_for_task(task, "write_file"))
        self.assertTrue(runtime._is_tool_allowed_for_task(task, "update_plan"))
        self.assertFalse(runtime._is_tool_allowed_for_task(task, "update_plan_draft"))
        self.assertFalse(runtime._is_tool_allowed_for_task(task, "enter_plan_mode"))

    def test_plan_mode_allows_execution_tools_after_checklist_exists(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        task = SessionTask(
            session=SessionRecord(
                session_id="session-1",
                title="plan",
                messages=[],
                metadata={
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                    "plan": {
                        "steps": [
                            {"step": "先拆任务", "status": "completed"},
                            {"step": "再执行", "status": "in_progress"},
                        ],
                        "progress": {
                            "total": 2,
                            "completed": 1,
                            "in_progress": 1,
                            "pending": 0,
                            "blocked": 0,
                            "cancelled": 0,
                        },
                        "current_step": "再执行",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                },
            ),
            permission_context=PermissionContext(),
            turn_id="turn-1",
        )

        self.assertTrue(runtime._is_tool_allowed_for_task(task, "write_file"))
        self.assertTrue(runtime._is_tool_allowed_for_task(task, "read_file"))
        self.assertTrue(runtime._is_tool_allowed_for_task(task, "update_plan"))


if __name__ == "__main__":
    unittest.main()
