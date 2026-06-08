from __future__ import annotations

from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


ACTIVE_MCP_TOOLS_METADATA_KEY = "active_mcp_tools"


class ActivateMCPTool(BaseTool):
    def __init__(self, context: BuiltinToolContext):
        self.context = context
        self.meta = ToolMeta(
            name="activate_mcp_tool",
            description=(
                "Expose one specific MCP tool's provider function schema for subsequent model calls in this session. "
                "Use this after reading an MCP server tool snapshot and choosing the exact server/tool pair."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Exact MCP server name from the server snapshot.",
                    },
                    "tool": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Exact MCP tool name from the server tool snapshot.",
                    },
                },
                "required": ["server", "tool"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=5,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        registry = self.context.mcp_registry
        if registry is None:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="activate",
                category="runtime_error",
                summary="MCP registry is not available in this runtime",
                retryable=False,
            )

        server_name = str(arguments.get("server", "")).strip()
        tool_name = str(arguments.get("tool", "")).strip()
        full_tool_name = registry.mcp_tool_name(server_name, tool_name)
        if full_tool_name is None:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="activate",
                category="validation_error",
                summary=f"MCP tool not found: server={server_name} tool={tool_name}",
                stdout=registry.describe_tool_snapshots(),
                retryable=True,
            )

        active_tools = self._current_active_tools(session_id)
        if full_tool_name not in active_tools:
            active_tools.append(full_tool_name)
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="activate",
            summary=f"MCP tool 已激活：{full_tool_name}",
            stdout=f"Activated MCP tool: {full_tool_name}",
            metadata={
                "activated_mcp_tool": full_tool_name,
                ACTIVE_MCP_TOOLS_METADATA_KEY: active_tools,
                "session_metadata_updates": {ACTIVE_MCP_TOOLS_METADATA_KEY: active_tools},
            },
        )

    def _current_active_tools(self, session_id: str) -> list[str]:
        session_store = self.context.session_store
        if session_store is None:
            return []
        try:
            session = session_store.get(session_id)
        except Exception:
            return []
        raw_active_tools = session.metadata.get(ACTIVE_MCP_TOOLS_METADATA_KEY)
        if not isinstance(raw_active_tools, list):
            return []
        active_tools: list[str] = []
        for item in raw_active_tools:
            if isinstance(item, str) and item.startswith("mcp__") and item not in active_tools:
                active_tools.append(item)
        return active_tools


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [ActivateMCPTool(context)]
