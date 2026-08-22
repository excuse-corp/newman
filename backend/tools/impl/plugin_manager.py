from __future__ import annotations

import json
from typing import Any

from backend.plugin_runtime.draft_models import PluginSpec
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


class PluginManagerTool(BaseTool):
    def __init__(self, draft_service):
        self.draft_service = draft_service
        self.meta = ToolMeta(
            name="plugin_manager",
            description=(
                "Create and validate Newman plugin drafts from a structured PluginSpec or natural-language request. "
                "Prefer a structured spec when the capabilities are clear. "
                "This tool cannot approve, install, enable, or generate hooks/MCP servers."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["create", "validate", "preview"]},
                    "draft_id": {"type": "string"},
                    "spec": {"type": "object"},
                    "request": {"type": "string"},
                },
                "required": ["operation"],
                "additionalProperties": False,
            },
            risk_level="medium",
            approval_behavior="safe",
            timeout_seconds=10,
        )

    def validate_arguments(self, arguments: Any) -> str | None:
        error = super().validate_arguments(arguments)
        if error:
            return error
        operation = arguments.get("operation") if isinstance(arguments, dict) else None
        if operation == "create" and not isinstance(arguments.get("spec"), dict):
            request = arguments.get("request")
            if not isinstance(request, str) or not request.strip():
                return "create 操作需要 spec 对象或 request 文本"
        if operation in {"validate", "preview"} and not isinstance(arguments.get("draft_id"), str):
            return f"{operation} 操作需要 draft_id"
        return None

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        operation = arguments.get("operation")
        try:
            if operation == "create":
                if isinstance(arguments.get("spec"), dict):
                    record = self.draft_service.create(
                        PluginSpec.model_validate(arguments["spec"]),
                        source_request=arguments.get("request") if isinstance(arguments.get("request"), str) else None,
                    )
                else:
                    record = self.draft_service.create_from_request(str(arguments["request"]))
            else:
                record = self.draft_service.get(str(arguments["draft_id"]))
                if operation == "validate":
                    record = self.draft_service.validate(record.draft_id)
            payload = record.model_dump(mode="json")
            return ToolExecutionResult(
                success=True,
                tool=self.meta.name,
                action=str(operation),
                summary=f"插件草稿已{operation}",
                stdout=json.dumps(payload, ensure_ascii=False, indent=2),
                persisted_output=json.dumps(payload, ensure_ascii=False),
                metadata={"draft_id": record.draft_id, "draft_status": record.status},
            )
        except Exception as exc:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action=str(operation),
                category="validation_error",
                summary=str(exc),
            )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    service = getattr(context, "plugin_draft_service", None)
    return [PluginManagerTool(service)] if service is not None else []
