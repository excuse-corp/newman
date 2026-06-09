from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.config.schema import AppConfig
from backend.subagents.manager import MultiAgentManager, MultiAgentValidationError
from backend.subagents.store import MultiAgentStore
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext, load_builtin_tools
from backend.tools.impl.multiagent import MultiAgentTool
from backend.tools.orchestrator import ToolOrchestrator
from backend.tools.approval import ApprovalManager
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import PathAccessPolicy


def _request(*, allowed_tools: list[str] | None = None) -> dict[str, object]:
    return {
        "mode": "parallel",
        "run_mode": "sync",
        "return_strategy": "wait_all",
        "context_policy": "fresh",
        "agents": [
            {
                "name": "reader",
                "prompt": "Read backend/runtime/run_loop.py and report back.",
                "allowed_tools": allowed_tools or ["read_file"],
                "max_turns": 3,
            }
        ],
    }


def _manager(tmp: Path, *, tool_names: set[str] | None = None, settings: AppConfig | None = None) -> MultiAgentManager:
    return MultiAgentManager(
        settings or AppConfig(),
        MultiAgentStore(tmp / "subagents"),
        tool_names_provider=lambda: tool_names or {"read_file", "search_files", "multiagent", "request_user_input"},
        skill_names_provider=lambda: {"ppt-studio", "html-excel-skill"},
    )


class MultiAgentManagerPhase2Tests(unittest.IsolatedAsyncioTestCase):
    async def test_validate_request_applies_global_tool_denylist(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            manager = _manager(Path(raw_tmp))

            validated = manager.validate_request(_request(allowed_tools=["read_file", "multiagent", "request_user_input"]))

            agent = validated.agents[0]
            self.assertEqual(agent.allowed_tools, ["read_file"])
            self.assertIn("multiagent", agent.denied_tools)
            self.assertIn("request_user_input", agent.denied_tools)
            self.assertEqual(agent.tool_policy_snapshot.approval_mode, "manual")

    async def test_validate_request_rejects_unknown_tool(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            manager = _manager(Path(raw_tmp), tool_names={"read_file"})

            with self.assertRaises(MultiAgentValidationError) as raised:
                manager.validate_request(_request(allowed_tools=["read_file", "missing_tool"]))

            self.assertIn("unknown tools", str(raised.exception))

    async def test_validate_request_defaults_max_turns_to_200(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            manager = _manager(Path(raw_tmp))
            request = _request()
            request["agents"][0].pop("max_turns")  # type: ignore[index,union-attr]

            validated = manager.validate_request(request)

            self.assertEqual(validated.agents[0].max_turns, 200)

    async def test_validate_request_rejects_removed_budget_and_timeout_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            manager = _manager(Path(raw_tmp))
            request = _request()
            request["token_budget"] = 10
            request["run_timeout_seconds"] = 60
            request["agents"][0]["task_timeout_seconds"] = 10  # type: ignore[index]

            with self.assertRaises(MultiAgentValidationError) as raised:
                manager.validate_request(request)

            message = str(raised.exception)
            self.assertIn("unsupported multiagent fields: run_timeout_seconds, token_budget", message)
            self.assertIn("agents[1].task_timeout_seconds is not supported", message)

    async def test_run_sync_persists_validated_run_with_phase2_degraded_report(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            manager = _manager(tmp)

            report = await manager.run_sync(
                _request(),
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
                turn_approval_mode="auto_allow",
            )

            self.assertEqual(report.status, "failed")
            self.assertEqual(len(report.agent_reports), 1)
            self.assertEqual(report.agent_reports[0].degraded_reason, "runner_not_implemented")
            record = manager.store.get_record(report.run_id)
            self.assertEqual(record.run.parent_session_id, "parent-session")
            self.assertEqual(record.run.parent_turn_id, "turn-1")
            task = next(iter(record.tasks.values()))
            self.assertEqual(task.tool_policy_snapshot.approval_mode, "auto_allow")

    async def test_validation_failure_returns_structured_report_without_persisting_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            manager = _manager(tmp)

            report = await manager.run_sync(
                {"agents": []},
                parent_session_id="parent-session",
                parent_turn_id="turn-1",
            )

            self.assertEqual(report.status, "failed")
            self.assertIn("validation failed", report.summary)
            self.assertEqual(manager.store.list_records(), [])


class MultiAgentToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiagent_tool_returns_report_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            manager = _manager(Path(raw_tmp))
            tool = MultiAgentTool(manager)

            result = await tool.run(
                {
                    **_request(),
                    "__parent_turn_id": "turn-1",
                    "__turn_approval_mode": "auto_allow",
                },
                "parent-session",
            )

            self.assertTrue(result.success)
            self.assertEqual(result.tool, "multiagent")
            self.assertEqual(result.metadata["multiagent_status"], "failed")
            self.assertIn("multiagent_report", result.metadata)

    async def test_multiagent_tool_schema_matches_max_turn_contract(self) -> None:
        tool = MultiAgentTool(_manager(Path(tempfile.mkdtemp())))
        properties = tool.meta.input_schema["properties"]
        agent_properties = properties["agents"]["items"]["properties"]

        self.assertNotIn("run_timeout_seconds", properties)
        self.assertNotIn("token_budget", properties)
        self.assertNotIn("task_timeout_seconds", agent_properties)
        self.assertEqual(agent_properties["max_turns"]["default"], 200)
        self.assertIsNone(tool.meta.timeout_seconds)

    async def test_orchestrator_injects_parent_turn_without_exposing_it_to_validation(self) -> None:
        class FakeMultiAgentTool(BaseTool):
            def __init__(self):
                self.calls: list[dict[str, object]] = []
                self.meta = ToolMeta(
                    name="multiagent",
                    description="fake multiagent",
                    input_schema={
                        "type": "object",
                        "properties": {"agents": {"type": "array"}},
                        "required": ["agents"],
                        "additionalProperties": False,
                    },
                    risk_level="medium",
                    approval_behavior="safe",
                    timeout_seconds=5,
                )

            async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
                self.calls.append({"arguments": arguments, "session_id": session_id})
                return ToolExecutionResult(success=True, tool=self.meta.name, action="run", summary="ok")

        tool = FakeMultiAgentTool()
        orchestrator = ToolOrchestrator(AppConfig(), ApprovalManager())

        async def emit(event: str, data: dict) -> None:
            return None

        result = await orchestrator.execute(
            tool,
            {"agents": []},
            "session-1",
            emit,
            turn_id="turn-1",
            turn_approval_mode="auto_allow",
        )

        self.assertTrue(result.success)
        self.assertEqual(tool.calls[0]["arguments"]["__parent_turn_id"], "turn-1")
        self.assertEqual(tool.calls[0]["arguments"]["__turn_approval_mode"], "auto_allow")
        self.assertTrue(callable(tool.calls[0]["arguments"]["__multiagent_event_emitter"]))

    async def test_builtin_discovery_registers_multiagent_when_manager_available(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            workspace = tmp / "workspace"
            workspace.mkdir()
            policy = PathAccessPolicy(
                workspace=workspace,
                browse_root=workspace,
                output_root=workspace / "outputs" / "chat",
                readable_roots=(workspace,),
                writable_roots=(workspace,),
                protected_roots=(),
            )
            manager = _manager(tmp)
            context = BuiltinToolContext(
                path_policy=policy,
                sandbox=SimpleNamespace(limits=SimpleNamespace(timeout_seconds=30), execute_shell=None),
                session_store=None,
                multimodal_analyzer=None,
                subagent_manager=manager,
            )

            tools = load_builtin_tools(context)

            self.assertIn("multiagent", [tool.meta.name for tool in tools])


if __name__ == "__main__":
    unittest.main()
