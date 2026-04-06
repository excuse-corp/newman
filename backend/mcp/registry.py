from __future__ import annotations

from pathlib import Path

import httpx

from backend.mcp.config import MCPConfigStore
from backend.mcp.models import MCPServerConfig, MCPServerStatus, MCPToolSpec
from backend.mcp.tool_adapter import MCPToolAdapter
from backend.tools.base import BaseTool


class MCPRegistry:
    def __init__(self, config_path: Path):
        self.store = MCPConfigStore(config_path)
        self._statuses: list[MCPServerStatus] = []

    def list_servers(self) -> list[MCPServerConfig]:
        return self.store.load()

    def upsert_server(self, server: MCPServerConfig) -> MCPServerConfig:
        items = [item for item in self.store.load() if item.name != server.name]
        items.append(server)
        self.store.save(items)
        return server

    def build_tools(self, plugin_configs: list[dict] | None = None) -> list[BaseTool]:
        tools: list[BaseTool] = []
        self._statuses = []
        servers = self.store.load()
        if plugin_configs:
            servers.extend(MCPServerConfig.model_validate(item) for item in plugin_configs)
        for server in servers:
            if not server.enabled:
                self._statuses.append(
                    MCPServerStatus(
                        name=server.name,
                        transport=server.transport,
                        enabled=False,
                        tool_count=0,
                        status="disabled",
                    )
                )
                continue
            try:
                specs = self._resolve_tools(server)
                tools.extend(MCPToolAdapter(server, spec) for spec in specs)
                self._statuses.append(
                    MCPServerStatus(
                        name=server.name,
                        transport=server.transport,
                        enabled=True,
                        tool_count=len(specs),
                        status="connected",
                    )
                )
            except Exception as exc:
                self._statuses.append(
                    MCPServerStatus(
                        name=server.name,
                        transport=server.transport,
                        enabled=True,
                        tool_count=0,
                        status="error",
                        detail=str(exc),
                    )
                )
        return tools

    def list_statuses(self) -> list[MCPServerStatus]:
        if not self._statuses:
            self.build_tools()
        return list(self._statuses)

    def _resolve_tools(self, server: MCPServerConfig) -> list[MCPToolSpec]:
        if server.transport == "inline":
            return server.tools
        if not server.url:
            raise ValueError(f"MCP server {server.name} missing url")
        with httpx.Client(timeout=server.timeout_seconds) as client:
            response = client.get(f"{server.url.rstrip('/')}/tools", headers=server.headers)
            response.raise_for_status()
            body = response.json()
        return [MCPToolSpec.model_validate(item) for item in body.get("tools", [])]
