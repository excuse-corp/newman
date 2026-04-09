from __future__ import annotations

from backend.mcp.models import MCPResourceRecord, MCPResourceSpec, MCPServerConfig


def adapt_resources(server: MCPServerConfig, resources: list[MCPResourceSpec]) -> list[MCPResourceRecord]:
    return [
        MCPResourceRecord(
            server_name=server.name,
            transport=server.transport,
            uri=resource.uri,
            name=resource.name,
            description=resource.description,
            mime_type=resource.mime_type,
            content=resource.content,
        )
        for resource in resources
    ]

