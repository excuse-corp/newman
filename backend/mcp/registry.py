from __future__ import annotations

from pathlib import Path

from backend.mcp.client import MCPClient
from backend.mcp.config import MCPConfigStore
from backend.mcp.models import MCPResourceRecord, MCPServerConfig, MCPServerStatus, utc_timestamp
from backend.mcp.resource_adapter import adapt_resources
from backend.mcp.tool_adapter import MCPToolAdapter
from backend.tools.base import BaseTool


class MCPRegistry:
    def __init__(self, config_path: Path):
        self.store = MCPConfigStore(config_path)
        self._statuses: list[MCPServerStatus] = []
        self._resources: list[MCPResourceRecord] = []
        self._clients: dict[str, MCPClient] = {}

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def list_servers(self) -> list[MCPServerConfig]:
        return self.store.load()

    def upsert_server(self, server: MCPServerConfig) -> MCPServerConfig:
        items = [item for item in self.store.load() if item.name != server.name]
        items.append(server)
        self.store.save(items)
        self._discard_client(server.name)
        return server

    def delete_server(self, server_name: str) -> None:
        items = self.store.load()
        if not any(item.name == server_name for item in items):
            raise FileNotFoundError(f"MCP server not found: {server_name}")
        self.store.save([item for item in items if item.name != server_name])
        self._discard_client(server_name)

    def reconnect_server(self, server_name: str) -> MCPServerStatus:
        server = next((item for item in self.store.load() if item.name == server_name), None)
        if server is None:
            raise FileNotFoundError(f"MCP server not found: {server_name}")
        self._discard_client(server_name)
        self.build_tools()
        status = next((item for item in self._statuses if item.name == server_name), None)
        if status is None:
            raise FileNotFoundError(f"MCP server status not found: {server_name}")
        return status

    def build_tools(self, plugin_configs: list[dict] | None = None) -> list[BaseTool]:
        tools: list[BaseTool] = []
        self._statuses = []
        self._resources = []
        active_names: set[str] = set()
        merged_servers: dict[str, MCPServerConfig] = {server.name: server for server in self.store.load()}
        if plugin_configs:
            for item in plugin_configs:
                server = MCPServerConfig.model_validate(item)
                merged_servers[server.name] = server

        for server in merged_servers.values():
            active_names.add(server.name)
            if not server.enabled:
                self._discard_client(server.name)
                self._statuses.append(
                    MCPServerStatus(
                        name=server.name,
                        transport=server.transport,
                        enabled=False,
                        tool_count=0,
                        resource_count=0,
                        status="disabled",
                        last_checked_at=utc_timestamp(),
                    )
                )
                continue

            client = self._get_client(server)
            try:
                specs = client.list_tools()
                resources = client.list_resources()
                self._resources.extend(adapt_resources(server, resources))
                tools.extend(MCPToolAdapter(server, spec, client) for spec in specs)
                self._statuses.append(
                    MCPServerStatus(
                        name=server.name,
                        transport=server.transport,
                        enabled=True,
                        tool_count=len(specs),
                        resource_count=len(resources),
                        status="connected",
                        last_checked_at=utc_timestamp(),
                    )
                )
            except Exception as exc:
                self._statuses.append(
                    MCPServerStatus(
                        name=server.name,
                        transport=server.transport,
                        enabled=True,
                        tool_count=0,
                        resource_count=0,
                        status="error",
                        detail=str(exc),
                        last_checked_at=utc_timestamp(),
                    )
                )

        stale_names = set(self._clients) - active_names
        for server_name in stale_names:
            self._discard_client(server_name)

        return tools

    def list_statuses(self) -> list[MCPServerStatus]:
        if not self._statuses:
            self.build_tools()
        return list(self._statuses)

    def list_resources(self) -> list[MCPResourceRecord]:
        if not self._statuses:
            self.build_tools()
        return list(self._resources)

    def describe_resources(self) -> str:
        if not self._resources:
            return ""
        return "\n".join(
            f"- {resource.server_name}: {resource.name} ({resource.uri})"
            + (f" - {resource.description}" if resource.description else "")
            for resource in self._resources
        )

    def _get_client(self, server: MCPServerConfig) -> MCPClient:
        signature = server.model_dump_json()
        existing = self._clients.get(server.name)
        if existing is not None and existing.signature == signature:
            return existing
        if existing is not None:
            existing.close()
        client = MCPClient(server)
        self._clients[server.name] = client
        return client

    def _discard_client(self, server_name: str) -> None:
        client = self._clients.pop(server_name, None)
        if client is not None:
            client.close()
