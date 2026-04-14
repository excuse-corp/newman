from __future__ import annotations

from typing import Any

from backend.sessions.models import SessionPlan
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


def _render_plan(plan: SessionPlan) -> str:
    lines = ["Plan Updated"]
    if plan.explanation:
        lines.append(plan.explanation)
    for step in plan.steps:
        lines.append(f"- [{step.status}] {step.step}")
    return "\n".join(lines)


class UpdatePlanTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="update_plan",
            description="Create or update the current multi-step plan for this session. Use it for complex tasks, and keep at most one step in_progress.",
            input_schema={
                "type": "object",
                "properties": {
                    "explanation": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["step", "status"],
                        },
                    },
                },
                "required": ["steps"],
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=5,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            plan = SessionPlan.model_validate(
                {
                    "explanation": arguments.get("explanation"),
                    "steps": arguments.get("steps", []),
                }
            )
        except Exception as exc:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="update",
                category="validation_error",
                summary=f"计划格式无效: {exc}",
            )

        plan_payload = plan.model_dump(mode="json")
        completed = plan.progress.get("completed", 0)
        total = plan.progress.get("total", len(plan.steps))
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="update",
            summary=f"计划已更新，完成 {completed}/{total} 步",
            stdout=_render_plan(plan),
            metadata={
                "plan": plan_payload,
                "session_metadata_updates": {"plan": plan_payload},
            },
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [UpdatePlanTool()]
