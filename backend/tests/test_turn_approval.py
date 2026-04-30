import asyncio
import unittest

from backend.config.schema import AppConfig
from backend.tools.approval import ApprovalManager
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.orchestrator import ToolOrchestrator
from backend.tools.result import ToolExecutionResult


class FakeWriteTool(BaseTool):
    def __init__(self):
        self.calls: list[dict] = []
        self.meta = ToolMeta(
            name="write_file",
            description="fake write tool",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            risk_level="high",
            timeout_seconds=5,
            approval_behavior="confirmable",
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="execute",
            summary="write complete",
        )


class FakeTerminalTool(BaseTool):
    def __init__(self):
        self.calls: list[dict] = []
        self.meta = ToolMeta(
            name="terminal",
            description="fake terminal tool",
            input_schema={"type": "object"},
            risk_level="high",
            timeout_seconds=5,
            approval_behavior="confirmable",
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="execute",
            summary="terminal complete",
        )


class FakeStreamingTerminalTool(FakeTerminalTool):
    async def run_streaming(self, arguments, session_id: str, emit_output=None) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        if emit_output is not None:
            await emit_output("stdout", "line 1\n")
            await emit_output("stderr", "warn 1\n")
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="execute",
            summary="terminal complete",
            stdout="line 1\n",
            stderr="warn 1\n",
        )


class FakeMCPTool(BaseTool):
    def __init__(self):
        self.calls: list[dict] = []
        self.meta = ToolMeta(
            name="mcp__demo__reader",
            description="fake mcp tool",
            input_schema={"type": "object"},
            risk_level="medium",
            timeout_seconds=5,
            approval_behavior="safe",
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="invoke",
            summary="mcp complete",
        )


class FakeLevel2Tool(BaseTool):
    def __init__(self):
        self.calls: list[dict] = []
        self.meta = ToolMeta(
            name="skill_maintenance",
            description="fake level2 tool",
            input_schema={"type": "object"},
            risk_level="medium",
            timeout_seconds=5,
            approval_behavior="safe",
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="execute",
            summary="level2 complete",
        )


class FakePlanModeTool(BaseTool):
    def __init__(self):
        self.calls: list[dict] = []
        self.meta = ToolMeta(
            name="enter_plan_mode",
            description="enter plan mode",
            input_schema={"type": "object"},
            risk_level="low",
            timeout_seconds=5,
            approval_behavior="confirmable",
            force_user_confirmation=True,
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="execute",
            summary="plan mode entered",
        )


class TurnApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_allow_skips_optional_approval(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeLevel2Tool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"path": "/root/newman/skills/demo/SKILL.md"},
            "session-auto",
            emit,
            extra_reasons=["maintain_skill"],
            turn_approval_mode="auto_allow",
        )

        self.assertTrue(result.success)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual([name for name, _ in events], [])
        self.assertIsNone(approvals.find_for_session("session-auto"))

    async def test_manual_mode_still_requires_user_confirmation(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeWriteTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        task = asyncio.create_task(
            orchestrator.execute(
                tool,
                {"path": "/root/newman/demo.txt", "content": "hello"},
                "session-manual",
                emit,
                turn_approval_mode="manual",
            )
        )

        await asyncio.sleep(0)

        self.assertEqual(events[0][0], "tool_approval_request")
        approval_request_id = events[0][1]["approval_request_id"]
        approvals.resolve(approval_request_id, True)

        result = await task

        self.assertTrue(result.success)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual([name for name, _ in events], ["tool_approval_request", "tool_approval_resolved"])
        self.assertTrue(events[1][1]["approved"])

    async def test_invalid_arguments_do_not_enter_manual_approval(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeWriteTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"path": "/root/newman/demo.txt"},
            "session-invalid",
            emit,
            turn_approval_mode="manual",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "validation_error")
        self.assertEqual(result.summary, "缺少必填参数: content")
        self.assertEqual(len(tool.calls), 0)
        self.assertEqual(events, [])

    async def test_auto_allow_bypasses_confirmable_tool_prompt(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeWriteTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"path": "/root/newman/demo.txt", "content": "hello"},
            "session-auto-manual-required",
            emit,
            turn_approval_mode="auto_allow",
        )

        self.assertTrue(result.success)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual([name for name, _ in events], [])

    async def test_force_user_confirmation_still_prompts_in_auto_allow(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakePlanModeTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        task = asyncio.create_task(
            orchestrator.execute(
                tool,
                {},
                "session-plan",
                emit,
                turn_approval_mode="auto_allow",
            )
        )

        await asyncio.sleep(0)

        self.assertEqual(events[0][0], "tool_approval_request")
        approval_request_id = events[0][1]["approval_request_id"]
        approvals.resolve(approval_request_id, True)

        result = await task

        self.assertTrue(result.success)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual([name for name, _ in events], ["tool_approval_request", "tool_approval_resolved"])
        self.assertIsNone(approvals.find_for_session("session-auto-manual-required"))

    async def test_auto_allow_does_not_bypass_level1_denies(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeTerminalTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"command": "rm -rf /"},
            "session-deny",
            emit,
            turn_approval_mode="auto_allow",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "permission_error")
        self.assertEqual(len(tool.calls), 0)
        self.assertEqual(events, [])

    async def test_unattended_scheduler_rejects_approval_immediately(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeWriteTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"path": "/root/newman/demo.txt", "content": "hello"},
            "session-scheduled",
            emit,
            turn_approval_mode="manual",
            scheduler_run_mode="unattended",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "user_rejected")
        self.assertEqual(len(tool.calls), 0)
        self.assertEqual([name for name, _ in events], ["tool_approval_request", "tool_approval_resolved"])
        self.assertFalse(events[1][1]["approved"])
        self.assertIsNone(approvals.find_for_session("session-scheduled"))

    async def test_mcp_path_denies_do_not_enter_manual_approval(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeMCPTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"path": "/tmp/outside.txt"},
            "session-mcp-deny",
            emit,
            extra_reasons=["mcp_path_outside_workspace:/tmp/outside.txt"],
            turn_approval_mode="manual",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "permission_error")
        self.assertEqual(len(tool.calls), 0)
        self.assertEqual(events, [])

    async def test_cancelling_manual_approval_discards_pending_request(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeWriteTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        task = asyncio.create_task(
            orchestrator.execute(
                tool,
                {"path": "/root/newman/demo.txt", "content": "hello"},
                "session-cancel",
                emit,
                turn_approval_mode="manual",
            )
        )

        await asyncio.sleep(0)
        approval_request_id = events[0][1]["approval_request_id"]

        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertNotIn(approval_request_id, approvals._pending)
        self.assertEqual(len(tool.calls), 0)

    async def test_streaming_terminal_emits_output_delta_events(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeStreamingTerminalTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"command": "pwd"},
            "session-streaming-terminal",
            emit,
            tool_call_id="call-1",
            group_id="turn-1:group:1",
            turn_approval_mode="manual",
        )

        self.assertTrue(result.success)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual(
            [name for name, _ in events],
            ["tool_call_output_delta", "tool_call_output_delta"],
        )
        self.assertEqual(events[0][1]["tool_call_id"], "call-1")
        self.assertEqual(events[0][1]["group_id"], "turn-1:group:1")
        self.assertEqual(events[0][1]["stream"], "stdout")
        self.assertEqual(events[0][1]["delta"], "line 1\n")
        self.assertEqual(events[1][1]["stream"], "stderr")
        self.assertEqual(events[1][1]["delta"], "warn 1\n")


if __name__ == "__main__":
    unittest.main()
