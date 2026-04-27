from __future__ import annotations

from typing import Any

from backend.runtime.collaboration_mode import build_plan_draft_payload
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import CORE_TOOL_GROUP
from backend.tools.result import ToolExecutionResult


class UpdatePlanDraftTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="update_plan_draft",
            description="Create or overwrite the current Markdown planning draft while in plan mode.",
            input_schema={
                "type": "object",
                "properties": {
                    "markdown": {"type": "string", "minLength": 1},
                },
                "required": ["markdown"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=5,
            provider_group=CORE_TOOL_GROUP,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        markdown = str(arguments.get("markdown", "")).strip()
        if not markdown:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="update",
                category="validation_error",
                summary="计划草案不能为空",
            )

        draft_payload = build_plan_draft_payload(markdown, status="draft")
        line_count = len(markdown.splitlines())
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="update",
            summary=f"规划草案已更新，共 {line_count} 行",
            stdout=markdown,
            persisted_output=f"Plan draft updated ({line_count} lines)",
            metadata={
                "plan_draft": draft_payload,
                "session_metadata_updates": {"plan_draft": draft_payload},
            },
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [UpdatePlanDraftTool()]
