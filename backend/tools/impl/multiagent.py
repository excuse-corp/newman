from __future__ import annotations

import json
from typing import Any

from backend.subagents.manager import MultiAgentManager
from backend.tools.base import BaseTool, ToolMeta, ToolOutputEmitter
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


class MultiAgentTool(BaseTool):
    def __init__(self, manager: MultiAgentManager):
        self.manager = manager
        self.meta = ToolMeta(
            name="multiagent",
            description=(
                "Delegate one or more clearly scoped tasks to temporary Newman subagents and return a structured "
                "MultiAgentReport. Use this only for execution of well-specified subtasks; the main agent remains "
                "responsible for planning and final synthesis."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["parallel", "sequential"], "default": "parallel"},
                    "run_mode": {"type": "string", "enum": ["sync"], "default": "sync"},
                    "return_strategy": {"type": "string", "enum": ["wait_all"], "default": "wait_all"},
                    "context_policy": {"type": "string", "enum": ["fresh"], "default": "fresh"},
                    "agents": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "minLength": 1},
                                "agent_type": {"type": "string"},
                                "description": {"type": "string"},
                                "prompt": {"type": "string", "minLength": 1},
                                "allowed_tools": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string"},
                                },
                                "allowed_skills": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "approval_mode": {
                                    "type": "string",
                                    "enum": ["inherit", "auto_allow", "manual"],
                                    "default": "auto_allow",
                                },
                                "model": {"type": "string"},
                                "max_turns": {"type": "integer", "default": 200},
                                "working_scope": {
                                    "type": "string",
                                    "enum": ["shared_workspace"],
                                    "default": "shared_workspace",
                                },
                            },
                            "required": ["name", "prompt", "allowed_tools"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["agents"],
                "additionalProperties": False,
            },
            risk_level="medium",
            approval_behavior="safe",
            timeout_seconds=None,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        return await self._run(arguments, session_id)

    async def run_streaming(
        self,
        arguments: dict[str, Any],
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        return await self._run(arguments, session_id)

    async def _run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        public_arguments = {key: value for key, value in arguments.items() if not key.startswith("__")}
        parent_turn_id = str(arguments.get("__parent_turn_id") or "").strip() or "unknown-turn"
        turn_approval_mode = str(arguments.get("__turn_approval_mode") or "manual").strip() or "manual"
        event_emitter = arguments.get("__multiagent_event_emitter")
        report = await self.manager.run_sync(
            public_arguments,
            parent_session_id=session_id,
            parent_turn_id=parent_turn_id,
            turn_approval_mode=turn_approval_mode,
            event_emitter=event_emitter if callable(event_emitter) else None,
        )
        payload = report.model_dump(mode="json")
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="run",
            summary=report.summary,
            stdout=json.dumps(payload, ensure_ascii=False, indent=2),
            metadata={
                "multiagent_run_id": report.run_id,
                "multiagent_status": report.status,
                "multiagent_report": payload,
            },
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    subagent_manager = getattr(context, "subagent_manager", None)
    if subagent_manager is None:
        return []
    return [MultiAgentTool(subagent_manager)]
