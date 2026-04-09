from __future__ import annotations

from typing import Any

from backend.mcp.client import MCPClient, MCPClientError
from backend.mcp.models import MCPServerConfig, MCPToolSpec
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult


class MCPToolAdapter(BaseTool):
    def __init__(self, server: MCPServerConfig, spec: MCPToolSpec, client: MCPClient):
        self.server = server
        self.spec = spec
        self.client = client
        self.meta = ToolMeta(
            name=f"mcp__{server.name}__{spec.name}",
            description=spec.description or f"MCP tool {spec.name} from {server.name}",
            input_schema=spec.input_schema,
            risk_level=spec.risk_level,
            requires_approval=server.requires_approval,
            timeout_seconds=server.timeout_seconds,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            body = await self.client.invoke_tool(self.spec, arguments)
        except MCPClientError as exc:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="invoke",
                category="network_error",
                summary=f"MCP server {self.server.name} request failed: {exc}",
                stderr=str(exc),
                retryable=True,
            )
        except Exception as exc:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="invoke",
                category="runtime_exception",
                summary=f"MCP tool {self.spec.name} 执行异常: {exc}",
                stderr=str(exc),
                retryable=False,
            )

        return ToolExecutionResult(
            success=bool(body.get("success", True)),
            tool=self.meta.name,
            action="invoke",
            category=str(body.get("category", "success")),
            summary=str(body.get("summary", f"MCP tool {self.spec.name} executed")),
            stdout=str(body.get("stdout", "")),
            stderr=str(body.get("stderr", "")),
            retryable=bool(body.get("retryable", False)),
            metadata=body.get("metadata", {}) if isinstance(body.get("metadata"), dict) else {},
        )

