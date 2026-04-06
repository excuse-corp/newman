from __future__ import annotations

from typing import Any

import httpx

from backend.mcp.models import MCPServerConfig, MCPToolSpec
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult


class MCPToolAdapter(BaseTool):
    def __init__(self, server: MCPServerConfig, spec: MCPToolSpec):
        self.server = server
        self.spec = spec
        self.meta = ToolMeta(
            name=f"mcp__{server.name}__{spec.name}",
            description=spec.description or f"MCP tool {spec.name} from {server.name}",
            input_schema=spec.input_schema,
            risk_level=spec.risk_level,
            requires_approval=server.requires_approval,
            timeout_seconds=server.timeout_seconds,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        if self.server.transport == "inline":
            return ToolExecutionResult(
                success=True,
                tool=self.meta.name,
                action="invoke",
                summary=f"MCP inline tool {self.spec.name} executed",
                stdout=f"[mcp:inline] server={self.server.name} tool={self.spec.name} arguments={arguments}",
            )

        if not self.server.url:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="invoke",
                category="validation_error",
                summary=f"MCP server {self.server.name} is missing url",
            )

        try:
            async with httpx.AsyncClient(timeout=self.server.timeout_seconds) as client:
                response = await client.post(
                    f"{self.server.url.rstrip('/')}/invoke/{self.spec.name}",
                    headers=self.server.headers,
                    json=arguments,
                )
                response.raise_for_status()
                body = response.json()
            return ToolExecutionResult(
                success=bool(body.get("success", True)),
                tool=self.meta.name,
                action="invoke",
                category=body.get("category", "success"),
                summary=body.get("summary", f"MCP tool {self.spec.name} executed"),
                stdout=body.get("stdout", ""),
                stderr=body.get("stderr", ""),
                retryable=bool(body.get("retryable", False)),
            )
        except httpx.HTTPError as exc:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="invoke",
                category="network_error",
                summary=f"MCP server {self.server.name} request failed: {exc}",
                stderr=str(exc),
                retryable=True,
            )
