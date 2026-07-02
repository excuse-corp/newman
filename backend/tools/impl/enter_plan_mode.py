from __future__ import annotations

from typing import Any

from backend.runtime.collaboration_mode import PLAN_COLLABORATION_MODE, build_collaboration_mode_payload
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


class EnterPlanModeTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="enter_plan_mode",
            description=(
                "Enter execution-oriented plan mode. Use this when the task is complex and should be decomposed into"
                " a checklist before implementation continues."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="confirmable",
            timeout_seconds=5,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        mode_payload = build_collaboration_mode_payload(PLAN_COLLABORATION_MODE, source="tool")
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="update",
            summary="已进入计划模式",
            stdout="Plan mode enabled",
            metadata={
                "collaboration_mode": mode_payload,
                "session_metadata_updates": {"collaboration_mode": mode_payload},
            },
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [EnterPlanModeTool()]
