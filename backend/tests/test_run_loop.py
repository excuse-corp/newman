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

from backend.providers.base import ProviderChunk, ProviderError, ProviderResponse, TokenUsage, ToolCall, ToolCallDelta
from backend.runtime.run_loop import NewmanRuntime, _build_tool_event_output_preview
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


class _DummyLongToolBackedAnswerProvider:
    def __init__(self, observed_events: list[tuple[str, dict[str, object]]]) -> None:
        self.observed_events = observed_events
        self.stream_released_before_done = False

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(
            type="text",
            delta=(
                "这是一段较长的最终回答，用来确认工具回合后的正式回复不会一直等到 provider 结束后才展示，"
                "而是在足够确定这是回答正文时就开始向前端释放流式片段，让用户能持续看到内容增长，"
                "并且后续增量仍然保持顺序。"
            ),
        )
        self.stream_released_before_done = any(event == "assistant_delta" for event, _ in self.observed_events)
        yield ProviderChunk(type="text", delta="后续内容继续正常追加。")
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


class _ProviderShouldNotRun:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("provider chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        raise AssertionError("provider chat_stream should not be called")

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyCommentaryOnlyProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls += 1
        yield ProviderChunk(type="text", delta="<commentary>我先处理附件</commentary>\n\n")
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


class _DummyBareGoogleSearchProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(
                id="tool-1",
                name="google_search",
                arguments={"q": "L20 显卡 MiniCPM-V 2.5 部署案例"},
            ),
        )
        yield ProviderChunk(type="done", finish_reason="tool_calls", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyBareParsedArtifactReadProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(
                id="tool-1",
                name="read_file_range",
                arguments={
                    "path": (
                        "parser_outputs/chat/5cfc42933c8849e5ab63d0e1e63e67a5/"
                        "2908843bc7b842d3ab6b38c2f2994a5b/e9d8371588054dd88ca3539257500e60.md"
                    ),
                    "offset": 1,
                    "limit": 80,
                },
            ),
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


class _DummyToolCallDeltaProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(
            type="tool_call_delta",
            tool_call_delta=ToolCallDelta(
                index=0,
                id="tool-1",
                name="write_file",
                arguments_delta='{"path":"demo.html","content":"<html>',
            ),
        )
        yield ProviderChunk(
            type="tool_call_delta",
            tool_call_delta=ToolCallDelta(
                index=0,
                id="tool-1",
                name="write_file",
                arguments_delta="x" * 2500,
            ),
        )
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(id="tool-1", name="write_file", arguments={"path": "demo.html", "content": "<html></html>"}),
        )
        yield ProviderChunk(type="done", finish_reason="tool_calls", usage=TokenUsage())

    def estimate_tokens(self, messages) -> int:
        return 0


class _DummyStructuredLeakyToolPreambleProvider:
    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called in this test")

    async def chat_stream(self, messages, tools=None, **kwargs):
        yield ProviderChunk(
            type="text",
            delta=(
                "老板，我先根据文档内容规划一下架构图的层次结构，然后生成 HTML 文件。\n\n"
                "## 架构图规划\n"
                "1. 安全保障层：数据安全、伦理审查、主动防御\n"
                "2. 组织与制度保障层：组织保障、资金保障、制度保障\n"
            ),
        )
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(id="tool-1", name="write_file", arguments={"path": "/root/newman/diagram.html"}),
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

    async def test_commentary_only_provider_response_is_not_persisted_as_blank_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_store = SessionStore(Path(tmp))
            session = session_store.create(title="commentary-only-provider")
            provider = _DummyCommentaryOnlyProvider()
            runtime = self._build_runtime(session_store, provider)

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime.handle_message(
                session.session_id,
                "根据附件制作架构图",
                emit,
                turn_id="turn-1",
                request_id="req-1",
            )

            saved = session_store.get(session.session_id)
            self.assertEqual(provider.calls, 3)
            self.assertEqual(saved.messages[-1].role, "assistant")
            self.assertNotEqual(saved.messages[-1].content, "\n\n")
            self.assertIn("主模型本次响应异常，未返回任何内容", saved.messages[-1].content)
            final_response_payload = next(data for event, data in events if event == "final_response")
            self.assertIn("主模型本次响应异常，未返回任何内容", final_response_payload["content"])
            error_payload = next(data for event, data in events if event == "error")
            self.assertEqual(error_payload["category"], "empty_response")

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


class ContextCompactionGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_irreducible_context_stops_before_provider_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_store = SessionStore(Path(tmp))
            session = session_store.create(title="irreducible-context")

            runtime = object.__new__(NewmanRuntime)
            runtime.provider = _ProviderShouldNotRun()
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
                task.session.metadata["context_irreducible"] = True
                task.session.metadata["last_compaction_failure_reason"] = "max_failures_reached"
                runtime.session_store.save(task.session)
                return False

            runtime._maybe_checkpoint = fake_maybe_checkpoint

            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, data: dict[str, object]) -> None:
                events.append((event, data))

            await runtime.handle_message(
                session.session_id,
                "继续分析",
                emit,
                turn_id="turn-1",
                request_id="req-1",
            )

            saved = session_store.get(session.session_id)
            self.assertEqual(saved.messages[-1].role, "assistant")
            self.assertEqual(saved.messages[-1].metadata["finish_reason"], "context_irreducible")
            self.assertIn("自动压缩后仍无法腾出足够空间", saved.messages[-1].content)
            final_response_payload = next(data for event, data in events if event == "final_response")
            self.assertEqual(final_response_payload["finish_reason"], "context_irreducible")
            error_payload = next(data for event, data in events if event == "error")
            self.assertEqual(error_payload["code"], "NEWMAN-CONTEXT-001")
            self.assertEqual(error_payload["category"], "context_irreducible")


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

    async def test_missing_commentary_without_thinking_uses_tool_argument_brief(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyBareGoogleSearchProvider()
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
            title="Google Search Brief Test",
            messages=[
                SessionMessage(
                    id="user-1",
                    role="user",
                    content="L20显卡有成功部署 mimov2.5 的案例吗",
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
            [{"name": "google_search"}],
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

        self.assertEqual(
            response.commentary,
            "我先搜索「L20 显卡 MiniCPM-V 2.5 部署案例」相关资料，确认可引用的信息来源。",
        )
        self.assertEqual([event for event, _ in events], ["commentary_delta", "commentary_complete"])
        self.assertEqual(events[0][1]["content"], response.commentary)

    async def test_internal_parsed_artifact_path_uses_readable_brief_target(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyBareParsedArtifactReadProvider()
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
            title="Parsed Artifact Brief Test",
            messages=[
                SessionMessage(
                    id="user-1",
                    role="user",
                    content="8卡L20可以部署mimo v2.5吗？",
                    metadata={"turn_id": "turn-1"},
                )
            ],
        )
        task = SessionTask(session=session, permission_context=PermissionContext(), turn_id="turn-1", tool_depth=1)

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
            group_id="turn-1:group:2",
        )
        response = await runtime._ensure_tool_response_commentary(
            task,
            response,
            emit,
            group_id="turn-1:group:2",
        )

        self.assertEqual(response.commentary, "我继续读取 匹配到的解析文档，确认里面的相关信息。")
        self.assertNotIn("5cfc42933c8849e5ab63d0e1e63e67a5", response.commentary)

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
            ["commentary_delta", "commentary_complete"],
        )
        self.assertEqual(events[0][1]["content"], "再读取 README 了解产品整体介绍")

    async def test_structured_tool_preamble_is_not_reclaimed_into_commentary(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyStructuredLeakyToolPreambleProvider()
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
            [{"name": "write_file"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:1",
            emit_answer_started_event=True,
        )

        self.assertEqual(response.content, "")
        self.assertEqual(response.commentary, "")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual([event for event, _ in events], [])

    async def test_tool_call_argument_deltas_emit_progress_before_tool_call_finishes(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        runtime.provider = _DummyToolCallDeltaProvider()
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
            [{"name": "write_file"}],
            emit,
            session_id="session-1",
            turn_id="turn-1",
            request_kind="session_turn",
            counts_toward_context_window=True,
            group_id="turn-1:group:1",
        )

        self.assertEqual(response.content, "")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual([event for event, _ in events], ["tool_call_arguments_delta", "tool_call_arguments_delta"])
        self.assertEqual(events[0][1]["group_id"], "turn-1:group:1")
        self.assertEqual(events[0][1]["tool_call_id"], "tool-1")
        self.assertEqual(events[0][1]["tool"], "write_file")
        self.assertIn("正在准备 write_file 调用参数", events[0][1]["summary"])
        self.assertGreater(events[1][1]["arguments_bytes"], events[0][1]["arguments_bytes"])

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
            ["commentary_delta", "commentary_complete"],
        )
        self.assertEqual(events[0][1]["content"], "再读取 README 了解产品整体介绍")

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

    async def test_tool_backed_long_final_answer_releases_before_provider_done(self) -> None:
        runtime = object.__new__(NewmanRuntime)
        events: list[tuple[str, dict[str, object]]] = []
        provider = _DummyLongToolBackedAnswerProvider(events)
        runtime.provider = provider
        runtime.usage_store = None
        runtime.settings = SimpleNamespace(
            provider=SimpleNamespace(
                model="dummy-model",
                type="mock",
                context_window=None,
                effective_context_window=None,
            )
        )

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

        self.assertTrue(provider.stream_released_before_done)
        self.assertEqual(response.content, events[-1][1]["content"])
        self.assertEqual([event for event, _ in events[:2]], ["answer_started", "assistant_delta"])

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

    def test_skill_usage_payload_detects_skill_file_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "skills" / "arch-diagram"
            skill_dir.mkdir(parents=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text("# Architecture Diagram\n", encoding="utf-8")

            runtime = object.__new__(NewmanRuntime)
            runtime.settings = SimpleNamespace(
                paths=SimpleNamespace(workspace=root),
                permissions=SimpleNamespace(readable_paths=[], writable_paths=[], protected_paths=[]),
            )
            runtime.skill_registry = SimpleNamespace(
                list_skills=lambda: [
                    SimpleNamespace(
                        name="arch-diagram",
                        path=str(skill_path),
                        description="Generate interactive architecture diagrams.",
                        plugin_name=None,
                    )
                ]
            )

            payload = runtime._skill_usage_payload_for_tool_call(
                "read_file",
                {"path": "skills/arch-diagram/SKILL.md"},
            )

            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["skill_name"], "arch-diagram")
            self.assertIn("arch-diagram Skill", payload["summary"])


class ToolResultPersistenceTests(unittest.TestCase):
    def test_build_assistant_message_attaches_turn_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            output_path = workspace / "diagram.html"
            output_path.write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")

            runtime = object.__new__(NewmanRuntime)
            runtime.settings = SimpleNamespace(paths=SimpleNamespace(workspace=workspace))
            session = SessionRecord(
                session_id="session-1",
                title="output file",
                messages=[
                    SessionMessage(
                        id="tool-1",
                        role="tool",
                        content="已写入 diagram.html",
                        metadata={
                            "turn_id": "turn-1",
                            "tool": "write_file",
                            "success": True,
                            "path": str(output_path),
                            "summary": "已写入 diagram.html",
                        },
                    )
                ],
            )
            task = SessionTask(session=session, permission_context=PermissionContext(), turn_id="turn-1")

            message = runtime._build_assistant_message(
                task,
                "文件已生成。",
                request_id="req-1",
                finish_reason="stop",
            )

            attachments = message.metadata.get("attachments")
            self.assertIsInstance(attachments, list)
            assert isinstance(attachments, list)
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0]["kind"], "html")
            self.assertEqual(attachments[0]["filename"], "diagram.html")
            self.assertEqual(attachments[0]["workspace_relative_path"], "diagram.html")

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
            action_brief="我先读取 README.md，确认里面的相关信息。",
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
            action_brief="我先在项目里检索 Newman，定位相关代码。",
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
            action_brief="我先运行命令，确认当前状态。",
            request_id=None,
        )

        self.assertEqual(message.content, "first line\nwarn line")
        self.assertTrue(message.metadata["content_persisted"])

    def test_tool_event_output_preview_prefers_user_facing_summary(self) -> None:
        result = ToolExecutionResult(
            success=True,
            tool="read_file",
            action="read",
            summary="已读取文件 README.md（10 字节）",
            stdout='{"dataBase64":"UkVBRE1FCg=="}',
        )

        self.assertEqual(_build_tool_event_output_preview(result), "已读取文件 README.md（10 字节）")

    def test_tool_event_output_preview_falls_back_to_terminal_output(self) -> None:
        result = ToolExecutionResult(
            success=False,
            tool="terminal",
            action="execute",
            stdout="first line\n",
            stderr="warn line\n",
        )

        self.assertEqual(_build_tool_event_output_preview(result), "first line\nwarn line")


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

    def test_provider_tools_keep_skill_read_and_write_for_attachment_generation_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "skills" / "arch-diagram"
            skill_dir.mkdir(parents=True)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text("Use this skill when the user asks for 架构图 generation.", encoding="utf-8")

            runtime = object.__new__(NewmanRuntime)
            runtime.registry = SimpleNamespace(
                tools_for_provider=lambda permission_context, active_groups=None: [
                    {"type": "function", "function": {"name": "read_file"}},
                    {"type": "function", "function": {"name": "read_file_range"}},
                    {"type": "function", "function": {"name": "list_dir"}},
                    {"type": "function", "function": {"name": "search_files"}},
                    {"type": "function", "function": {"name": "enter_plan_mode"}},
                    {"type": "function", "function": {"name": "update_plan"}},
                    {"type": "function", "function": {"name": "write_file"}},
                ]
            )
            runtime.skill_registry = SimpleNamespace(
                list_skills=lambda: [
                    SimpleNamespace(
                        name="arch-diagram",
                        path=str(skill_path),
                        description="Generate architecture diagrams.",
                        when_to_use=None,
                        summary="",
                    )
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
                            content="根据文档制作一份架构图给我",
                            metadata={
                                "turn_id": "turn-1",
                                "attachment_analysis": {
                                    "schema_version": "v1",
                                    "status": "completed",
                                    "normalized_user_input": "根据文档制作一份架构图给我",
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
            )

            tools = runtime._provider_tools_for_turn(task)

            self.assertEqual(
                [tool["function"]["name"] for tool in tools],
                ["read_file", "enter_plan_mode", "update_plan", "write_file"],
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
