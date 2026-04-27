from __future__ import annotations

from typing import Any

from backend.runtime.collaboration_mode import (
    DEFAULT_COLLABORATION_MODE,
    build_approved_plan_payload,
    build_collaboration_mode_payload,
    build_plan_draft_payload,
)
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import CORE_TOOL_GROUP
from backend.tools.result import ToolExecutionResult


class ExitPlanModeTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="exit_plan_mode",
            description=(
                "Request to leave plan mode and submit the current Markdown plan for user approval. Include the full"
                " approved plan markdown in the `markdown` argument."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "markdown": {"type": "string", "minLength": 1},
                },
                "required": ["markdown"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="confirmable",
            force_user_confirmation=True,
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
                summary="退出规划模式前必须提交非空的方案草案",
            )

        mode_payload = build_collaboration_mode_payload(DEFAULT_COLLABORATION_MODE, source="tool")
        approved_plan = build_approved_plan_payload(markdown)
        draft_payload = build_plan_draft_payload(markdown, status="approved")
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="update",
            summary="计划已批准，已回到默认执行模式",
            stdout=markdown,
            persisted_output="Plan approved and plan mode exited",
            metadata={
                "collaboration_mode": mode_payload,
                "plan_draft": draft_payload,
                "approved_plan": approved_plan,
                "session_metadata_updates": {
                    "collaboration_mode": mode_payload,
                    "plan_draft": draft_payload,
                    "approved_plan": approved_plan,
                },
            },
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [ExitPlanModeTool()]
