from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from backend.config.schema import AppConfig
from backend.providers.base import ProviderChunk, ProviderError, TokenUsage, ToolCall
from backend.sessions.session_store import SessionStore
from backend.subagents.locks import FileLockManager
from backend.subagents.manager import MultiAgentManager
from backend.subagents.runner import SubagentRunner
from backend.subagents.store import MultiAgentStore
from backend.tools.approval import ApprovalManager
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.orchestrator import ToolOrchestrator
from backend.tools.registry import ToolRegistry
from backend.tools.result import ToolExecutionResult
from backend.tools.router import ToolRouter


class _ReportProvider:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        content = self.responses[index]
        yield ProviderChunk(type="text", delta=content)
        yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 10


class _RateLimitedThenReportProvider:
    def __init__(self, failures: int = 1):
        self.failures = failures
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        if len(self.calls) <= self.failures:
            raise ProviderError(
                "openai_compatible",
                "rate_limit_error",
                "openai_compatible rate limited",
                True,
                status_code=429,
                details={"retry_after_seconds": 0},
            )
        yield ProviderChunk(type="text", delta=_report_text("retried"))
        yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 10


class _ConcurrentReportProvider:
    def __init__(self, delay_seconds: float = 0.05):
        self.delay_seconds = delay_seconds
        self.calls: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0
        self._lock = asyncio.Lock()

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        async with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay_seconds)
            yield ProviderChunk(type="text", delta=_report_json("done"))
            yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
            yield ProviderChunk(type="done", finish_reason="stop")
        finally:
            async with self._lock:
                self.active -= 1

    def estimate_tokens(self, messages) -> int:
        return 10


class _BlockingReportProvider:
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        self.started.set()
        await self.release.wait()
        yield ProviderChunk(type="text", delta=_report_json("done"))
        yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 10


class _MultiBlockingReportProvider:
    def __init__(self, expected_calls: int):
        self.expected_calls = expected_calls
        self.calls: list[dict[str, object]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._lock = asyncio.Lock()

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        async with self._lock:
            if len(self.calls) >= self.expected_calls:
                self.started.set()
        await self.release.wait()
        summary = str(messages[-1].get("content") or "done")
        yield ProviderChunk(type="text", delta=_report_json(summary))
        yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15))
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 10


class _ToolCallingProvider:
    def __init__(self, tool_name: str, arguments: dict[str, object], final_summary: str = "tool complete"):
        self.tool_name = tool_name
        self.arguments = arguments
        self.final_summary = final_summary
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        if len(self.calls) == 1:
            yield ProviderChunk(
                type="tool_call",
                tool_call=ToolCall(id="call-1", name=self.tool_name, arguments=self.arguments),
            )
            yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=2, total_tokens=12))
            yield ProviderChunk(type="done", finish_reason="tool_calls")
            return
        yield ProviderChunk(type="text", delta=_report_json(self.final_summary))
        yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=8, output_tokens=6, total_tokens=14))
        yield ProviderChunk(type="done", finish_reason="stop")

    def estimate_tokens(self, messages) -> int:
        return 10


class _AlwaysWriteThenReportProvider:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    async def chat(self, messages, tools=None, **kwargs):
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools})
        if any(isinstance(message, dict) and message.get("role") == "tool" for message in messages):
            yield ProviderChunk(type="text", delta=_report_json("write attempted"))
            yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=8, output_tokens=6, total_tokens=14))
            yield ProviderChunk(type="done", finish_reason="stop")
            return
        yield ProviderChunk(
            type="tool_call",
            tool_call=ToolCall(id=f"call-{len(self.calls)}", name="write_file", arguments={"path": "shared.txt", "content": "hello"}),
        )
        yield ProviderChunk(type="usage", usage=TokenUsage(input_tokens=10, output_tokens=2, total_tokens=12))
        yield ProviderChunk(type="done", finish_reason="tool_calls")

    def estimate_tokens(self, messages) -> int:
        return 10


class _EchoTool(BaseTool):
    def __init__(self):
        self.calls: list[dict[str, object]] = []
        self.meta = ToolMeta(
            name="echo_tool",
            description="Echo text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=5,
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="echo",
            summary="echoed",
            stdout=str(arguments.get("text") or ""),
        )


class _FakeWriteTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="write_file",
            description="Fake write",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=5,
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="write",
            summary=f"wrote {arguments['path']}",
            stdout="ok",
            metadata={"path": str(arguments["path"]), "bytes": len(str(arguments.get("content") or "").encode()), "created": True},
        )


class _SlowWriteTool(_FakeWriteTool):
    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        await asyncio.sleep(0.1)
        return await super().run(arguments, session_id)


def _report_json(summary: str = "done") -> str:
    return (
        "{"
        '"status":"completed",'
        f'"summary":"{summary}",'
        '"findings":[],'
        '"files_changed":[],'
        '"commands_run":[],'
        '"artifacts":[],'
        '"risks":[],'
        '"recommended_next_steps":[]'
        "}"
    )


def _report_text(summary: str = "done") -> str:
    return "\n".join(
        [
            "Scope: delegated review",
            f"Result: {summary}",
            "Key files: None",
            "Files changed: None",
            "Issues: None",
            "Risks: None",
            "Next steps: None",
        ]
    )


def _request() -> dict[str, object]:
    return {
        "mode": "parallel",
        "agents": [
            {
                "name": "reader",
                "prompt": "Inspect the runtime.",
                "allowed_tools": ["read_file"],
                "max_turns": 3,
            }
        ],
    }


def _writable_workspace_settings(workspace: Path) -> AppConfig:
    settings = AppConfig()
    settings.paths.workspace = workspace
    settings.paths.browse_root = workspace
    settings.paths.output_root = workspace / "outputs" / "chat"
    settings.permissions.writable_paths = [workspace]
    return settings


class SubagentRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_with_runner_creates_child_session_and_completed_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ReportProvider([_report_json("runtime inspected")])
            runner = SubagentRunner(AppConfig(), provider, session_store, subagent_store)
            manager = MultiAgentManager(
                AppConfig(),
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "completed")
            self.assertEqual(report.agent_reports[0].summary, "runtime inspected")
            record = subagent_store.get_record(report.run_id)
            task = next(iter(record.tasks.values()))
            child = session_store.get(task.child_session_id)
            self.assertTrue(child.metadata["subagent"])
            self.assertEqual(child.metadata["parent_session_id"], "parent-session")
            self.assertEqual(child.messages[0].role, "system")
            self.assertEqual(child.messages[1].role, "user")
            self.assertEqual(child.messages[-1].role, "assistant")
            self.assertIn("Do not return JSON.", child.messages[0].content)
            self.assertIn("Final report format:", child.messages[1].content)
            self.assertIn("Inspect the runtime.", child.messages[1].content)
            self.assertEqual(task.status, "completed")
            self.assertEqual(task.usage_summary.total_tokens, 15)

    async def test_runner_accepts_plain_text_report_without_repair(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ReportProvider([_report_text("runtime inspected")])
            runner = SubagentRunner(AppConfig(), provider, session_store, subagent_store)
            manager = MultiAgentManager(
                AppConfig(),
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "completed")
            self.assertIn("runtime inspected", report.agent_reports[0].summary)
            self.assertEqual(len(provider.calls), 1)

    async def test_runner_repairs_blank_report_once(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ReportProvider(["   ", _report_text("repaired")])
            runner = SubagentRunner(AppConfig(), provider, session_store, subagent_store)
            manager = MultiAgentManager(
                AppConfig(),
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "completed")
            self.assertIn("repaired", report.agent_reports[0].summary)
            self.assertEqual(len(provider.calls), 2)
            task = next(iter(subagent_store.get_record(report.run_id).tasks.values()))
            child = session_store.get(task.child_session_id)
            self.assertEqual(child.messages[-2].metadata["phase"], "report_repair")
            self.assertEqual(task.usage_summary.total_tokens, 30)

    async def test_runner_retries_rate_limited_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _RateLimitedThenReportProvider(failures=1)
            settings = AppConfig()
            settings.runtime.provider_retry_attempts = 1
            settings.runtime.provider_retry_backoff_seconds = 0.0
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "completed")
            self.assertIn("retried", report.agent_reports[0].summary)
            self.assertEqual(len(provider.calls), 2)

    async def test_runner_returns_report_invalid_after_failed_repair(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ReportProvider(["   ", "   "])
            runner = SubagentRunner(AppConfig(), provider, session_store, subagent_store)
            manager = MultiAgentManager(
                AppConfig(),
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "failed")
            self.assertEqual(report.agent_reports[0].status, "report_invalid")
            self.assertEqual(report.agent_reports[0].degraded_reason, "parse_failed")

    async def test_sequential_mode_injects_previous_summary_into_next_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ReportProvider([_report_json("alpha complete"), _report_json("beta complete")])
            settings = AppConfig()
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                {
                    "mode": "sequential",
                    "agents": [
                        {"name": "alpha", "prompt": "Inspect alpha.", "allowed_tools": ["read_file"], "max_turns": 3},
                        {"name": "beta", "prompt": "Inspect beta.", "allowed_tools": ["read_file"], "max_turns": 3},
                    ],
                },
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "completed")
            second_call_messages = provider.calls[1]["messages"]
            self.assertIn("Inspect beta.", second_call_messages[1]["content"])
            self.assertIn("Sequential context from previous subagents:", second_call_messages[1]["content"])
            self.assertIn("alpha complete", second_call_messages[1]["content"])

    async def test_parallel_mode_respects_max_parallel_agents(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ConcurrentReportProvider()
            settings = AppConfig()
            settings.subagents.max_parallel_agents = 1
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            report = await manager.run_sync(
                {
                    "mode": "parallel",
                    "agents": [
                        {"name": "a", "prompt": "A", "allowed_tools": ["read_file"], "max_turns": 3},
                        {"name": "b", "prompt": "B", "allowed_tools": ["read_file"], "max_turns": 3},
                        {"name": "c", "prompt": "C", "allowed_tools": ["read_file"], "max_turns": 3},
                    ],
                },
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "completed")
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(provider.max_active, 1)

    async def test_manager_emits_multiagent_lifecycle_events(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ReportProvider([_report_json("runtime inspected")])
            settings = AppConfig()
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )
            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, payload: dict[str, object]) -> None:
                events.append((event, payload))

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
                event_emitter=emit,
            )

            self.assertEqual(report.status, "completed")
            self.assertEqual([event for event, _ in events], [
                "multiagent_run_started",
                "multiagent_task_started",
                "multiagent_task_updated",
                "multiagent_run_completed",
            ])

    async def test_runner_emits_multiagent_tool_events(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ToolCallingProvider("echo_tool", {"text": "hello"}, final_summary="echo observed")
            registry = ToolRegistry()
            registry.register(_EchoTool())
            settings = AppConfig()
            router = ToolRouter(registry, settings)
            orchestrator = ToolOrchestrator(settings, ApprovalManager())
            runner = SubagentRunner(
                settings,
                provider,
                session_store,
                subagent_store,
                registry_provider=lambda: registry,
                router_provider=lambda: router,
                orchestrator_provider=lambda: orchestrator,
            )
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"echo_tool", "multiagent", "request_user_input"},
                runner=runner,
            )
            events: list[tuple[str, dict[str, object]]] = []

            async def emit(event: str, payload: dict[str, object]) -> None:
                events.append((event, payload))

            request = _request()
            request["agents"][0]["allowed_tools"] = ["echo_tool"]  # type: ignore[index]
            report = await manager.run_sync(
                request,
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
                event_emitter=emit,
            )

            self.assertEqual(report.status, "completed")
            tool_events = [payload for event, payload in events if event == "multiagent_tool_event"]
            self.assertTrue(tool_events)
            self.assertEqual(tool_events[0]["event"], "tool_call_started")
            self.assertTrue(any(payload["event"] == "tool_call_finished" for payload in tool_events))

    async def test_runner_executes_allowed_tool_and_replays_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ToolCallingProvider("echo_tool", {"text": "hello"}, final_summary="echo observed")
            registry = ToolRegistry()
            echo_tool = _EchoTool()
            registry.register(echo_tool)
            settings = AppConfig()
            router = ToolRouter(registry, settings)
            orchestrator = ToolOrchestrator(settings, ApprovalManager())
            runner = SubagentRunner(
                settings,
                provider,
                session_store,
                subagent_store,
                registry_provider=lambda: registry,
                router_provider=lambda: router,
                orchestrator_provider=lambda: orchestrator,
            )
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"echo_tool", "multiagent", "request_user_input"},
                runner=runner,
            )

            request = _request()
            request["agents"][0]["allowed_tools"] = ["echo_tool"]  # type: ignore[index]
            report = await manager.run_sync(request, parent_session_id="parent-session", parent_turn_id="turn-1")

            self.assertEqual(report.status, "completed")
            self.assertEqual(report.agent_reports[0].summary, "echo observed")
            self.assertEqual(echo_tool.calls[0]["arguments"], {"text": "hello"})
            self.assertEqual(provider.calls[0]["tools"][0]["function"]["name"], "echo_tool")
            task = next(iter(subagent_store.get_record(report.run_id).tasks.values()))
            child = session_store.get(task.child_session_id)
            self.assertEqual(child.messages[-2].role, "tool")
            self.assertEqual(child.messages[-2].content, "hello")
            self.assertEqual(child.messages[-2].metadata["tool"], "echo_tool")
            second_call_messages = provider.calls[1]["messages"]
            self.assertEqual(second_call_messages[-1]["role"], "tool")
            self.assertEqual(second_call_messages[-1]["tool_call_id"], "call-1")

    async def test_runner_records_file_changes_from_write_tool(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ToolCallingProvider("write_file", {"path": "demo.txt", "content": "hello"}, final_summary="file written")
            registry = ToolRegistry()
            registry.register(_FakeWriteTool())
            settings = _writable_workspace_settings(tmp / "workspace")
            router = ToolRouter(registry, settings)
            orchestrator = ToolOrchestrator(settings, ApprovalManager())
            runner = SubagentRunner(
                settings,
                provider,
                session_store,
                subagent_store,
                registry_provider=lambda: registry,
                router_provider=lambda: router,
                orchestrator_provider=lambda: orchestrator,
            )
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"write_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            request = _request()
            request["agents"][0]["allowed_tools"] = ["write_file"]  # type: ignore[index]
            report = await manager.run_sync(request, parent_session_id="parent-session", parent_turn_id="turn-1")

            self.assertEqual(report.status, "completed")
            self.assertEqual(len(report.agent_reports[0].files_changed), 1)
            change = report.agent_reports[0].files_changed[0]
            self.assertEqual(change.path, "demo.txt")
            self.assertEqual(change.tool, "write_file")
            self.assertTrue(change.created)

    async def test_runner_uses_final_turn_for_wrapup_without_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _ToolCallingProvider("echo_tool", {"text": "hello"}, final_summary="wrapped up")
            registry = ToolRegistry()
            echo_tool = _EchoTool()
            registry.register(echo_tool)
            settings = AppConfig()
            router = ToolRouter(registry, settings)
            orchestrator = ToolOrchestrator(settings, ApprovalManager())
            runner = SubagentRunner(
                settings,
                provider,
                session_store,
                subagent_store,
                registry_provider=lambda: registry,
                router_provider=lambda: router,
                orchestrator_provider=lambda: orchestrator,
            )
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"echo_tool", "multiagent", "request_user_input"},
                runner=runner,
            )

            request = _request()
            request["agents"][0]["allowed_tools"] = ["echo_tool"]  # type: ignore[index]
            request["agents"][0]["max_turns"] = 2  # type: ignore[index]
            report = await manager.run_sync(request, parent_session_id="parent-session", parent_turn_id="turn-1")

            self.assertEqual(report.status, "completed")
            self.assertEqual(report.agent_reports[0].summary, "wrapped up")
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(provider.calls[1]["tools"], [])
            self.assertEqual(len(echo_tool.calls), 1)
            task = next(iter(subagent_store.get_record(report.run_id).tasks.values()))
            child = session_store.get(task.child_session_id)
            self.assertEqual(task.progress.completed_turns, 2)
            self.assertEqual(child.messages[-2].metadata["phase"], "wrapup_request")
            self.assertTrue(child.messages[-1].metadata["is_wrapup_turn"])

    async def test_cancel_run_stops_running_task_at_provider_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _BlockingReportProvider()
            settings = AppConfig()
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            worker = asyncio.create_task(
                manager.run_sync(
                    _request(),
                    parent_session_id="parent-session",
                    parent_turn_id="turn-1",
                )
            )
            await provider.started.wait()
            record = subagent_store.list_records()[0]

            outcome = manager.cancel_run(record.run.run_id)
            self.assertTrue(outcome.accepted)

            provider.release.set()
            report = await worker

            self.assertEqual(report.status, "cancelled")
            self.assertEqual(report.agent_reports[0].status, "cancelled")
            self.assertEqual(report.agent_reports[0].degraded_reason, "cancelled")
            saved = subagent_store.get_record(record.run.run_id)
            self.assertEqual(saved.run.status, "cancelled")
            self.assertIsNotNone(saved.run.completed_at)
            saved_task = next(iter(saved.tasks.values()))
            self.assertEqual(saved_task.status, "cancelled")
            self.assertIsNotNone(saved_task.completed_at)

    async def test_cancel_single_task_does_not_stop_other_parallel_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _MultiBlockingReportProvider(expected_calls=2)
            settings = AppConfig()
            settings.subagents.max_parallel_agents = 2
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )
            request = {
                "mode": "parallel",
                "agents": [
                    {"name": "a", "prompt": "A", "allowed_tools": ["read_file"], "max_turns": 3},
                    {"name": "b", "prompt": "B", "allowed_tools": ["read_file"], "max_turns": 3},
                ],
            }

            worker = asyncio.create_task(
                manager.run_sync(
                    request,
                    parent_session_id="parent-session",
                    parent_turn_id="turn-1",
                )
            )
            await provider.started.wait()
            record = subagent_store.list_records()[0]
            target_task = next(task for task in record.tasks.values() if task.name == "b")

            outcome = manager.cancel_task(target_task.task_id)
            self.assertTrue(outcome.accepted)

            provider.release.set()
            report = await worker

            self.assertEqual(report.status, "partial")
            statuses = {agent_report.name: agent_report.status for agent_report in report.agent_reports}
            self.assertEqual(statuses["a"], "completed")
            self.assertEqual(statuses["b"], "cancelled")
            saved = subagent_store.get_record(record.run.run_id)
            saved_statuses = {task.name: task.status for task in saved.tasks.values()}
            self.assertEqual(saved.run.status, "partial")
            self.assertEqual(saved_statuses["a"], "completed")
            self.assertEqual(saved_statuses["b"], "cancelled")

    async def test_parent_cancel_marks_run_terminal_in_store(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _BlockingReportProvider()
            settings = AppConfig()
            runner = SubagentRunner(settings, provider, session_store, subagent_store)
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"read_file", "multiagent", "request_user_input"},
                runner=runner,
            )

            worker = asyncio.create_task(
                manager.run_sync(
                    _request(),
                    parent_session_id="parent-session",
                    parent_turn_id="turn-1",
                )
            )
            await provider.started.wait()
            record = subagent_store.list_records()[0]

            worker.cancel()
            provider.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await worker

            saved = subagent_store.get_record(record.run.run_id)
            self.assertEqual(saved.run.status, "cancelled")
            self.assertEqual(saved.run.cancel_reason, "parent_interrupted")
            self.assertIsNotNone(saved.run.completed_at)
            saved_task = next(iter(saved.tasks.values()))
            self.assertEqual(saved_task.status, "cancelled")
            self.assertEqual(saved_task.result.degraded_reason, "cancelled")

    async def test_parallel_writes_same_path_report_file_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _AlwaysWriteThenReportProvider()
            registry = ToolRegistry()
            registry.register(_SlowWriteTool())
            settings = _writable_workspace_settings(tmp / "workspace")
            settings.subagents.lock_wait_timeout_seconds = 0.01
            router = ToolRouter(registry, settings)
            orchestrator = ToolOrchestrator(settings, ApprovalManager())
            lock_manager = FileLockManager()
            runner = SubagentRunner(
                settings,
                provider,
                session_store,
                subagent_store,
                registry_provider=lambda: registry,
                router_provider=lambda: router,
                orchestrator_provider=lambda: orchestrator,
                lock_manager=lock_manager,
            )
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"write_file", "multiagent", "request_user_input"},
                runner=runner,
            )
            request = {
                "mode": "parallel",
                "agents": [
                    {"name": "writer-a", "prompt": "write", "allowed_tools": ["write_file"], "max_turns": 3},
                    {"name": "writer-b", "prompt": "write", "allowed_tools": ["write_file"], "max_turns": 3},
                ],
            }

            report = await manager.run_sync(request, parent_session_id="parent-session", parent_turn_id="turn-1")

            self.assertEqual(report.status, "completed")
            self.assertEqual(len(report.file_conflicts), 1)
            self.assertEqual(report.file_conflicts[0].reason, "lock_timeout")
            self.assertEqual(len(report.agent_reports), 2)
            changed_count = sum(len(agent_report.files_changed) for agent_report in report.agent_reports)
            self.assertEqual(changed_count, 1)

    async def test_parallel_successful_writes_same_path_report_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            session_store = SessionStore(tmp / "sessions")
            subagent_store = MultiAgentStore(tmp / "subagents")
            provider = _AlwaysWriteThenReportProvider()
            registry = ToolRegistry()
            registry.register(_FakeWriteTool())
            settings = _writable_workspace_settings(tmp / "workspace")
            router = ToolRouter(registry, settings)
            orchestrator = ToolOrchestrator(settings, ApprovalManager())
            runner = SubagentRunner(
                settings,
                provider,
                session_store,
                subagent_store,
                registry_provider=lambda: registry,
                router_provider=lambda: router,
                orchestrator_provider=lambda: orchestrator,
                lock_manager=FileLockManager(),
            )
            manager = MultiAgentManager(
                settings,
                subagent_store,
                tool_names_provider=lambda: {"write_file", "multiagent", "request_user_input"},
                runner=runner,
            )
            request = {
                "mode": "parallel",
                "agents": [
                    {"name": "writer-a", "prompt": "write", "allowed_tools": ["write_file"], "max_turns": 3},
                    {"name": "writer-b", "prompt": "write", "allowed_tools": ["write_file"], "max_turns": 3},
                ],
            }

            report = await manager.run_sync(request, parent_session_id="parent-session", parent_turn_id="turn-1")

            self.assertEqual(report.status, "completed")
            self.assertEqual(report.file_conflicts, [])
            self.assertEqual(len(report.file_overlaps), 1)
            self.assertEqual(len(report.file_overlaps[0].writers), 2)


if __name__ == "__main__":
    unittest.main()
