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
            input_schema={"type": "object"},
            risk_level="high",
            requires_approval=True,
            timeout_seconds=5,
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
            requires_approval=False,
            timeout_seconds=5,
        )

    async def run(self, arguments: dict, session_id: str) -> ToolExecutionResult:
        self.calls.append({"arguments": arguments, "session_id": session_id})
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="execute",
            summary="terminal complete",
        )


class TurnApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_approve_level2_skips_manual_approval(self):
        approvals = ApprovalManager()
        orchestrator = ToolOrchestrator(AppConfig(), approvals)
        tool = FakeWriteTool()
        events: list[tuple[str, dict]] = []

        async def emit(event: str, data: dict) -> None:
            events.append((event, data))

        result = await orchestrator.execute(
            tool,
            {"path": "/root/newman/demo.txt", "content": "hello"},
            "session-auto",
            emit,
            turn_approval_mode="auto_approve_level2",
        )

        self.assertTrue(result.success)
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual([name for name, _ in events], [])

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

    async def test_auto_approve_level2_does_not_bypass_level1_denies(self):
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
            turn_approval_mode="auto_approve_level2",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "permission_error")
        self.assertEqual(len(tool.calls), 0)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
