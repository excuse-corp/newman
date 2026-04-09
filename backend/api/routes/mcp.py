from __future__ import annotations

from fastapi import APIRouter, Request

from backend.mcp.models import MCPServerConfig


router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
async def list_servers(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    servers: dict[str, MCPServerConfig] = {item.name: item for item in runtime.mcp_registry.list_servers()}
    for item in runtime.plugin_service.mcp_server_configs():
        server = MCPServerConfig.model_validate(item)
        servers[server.name] = server
    return {
        "servers": [item.model_dump(mode="json") for item in servers.values()],
        "statuses": [item.model_dump(mode="json") for item in runtime.mcp_registry.list_statuses()],
    }


@router.post("/servers")
async def upsert_server(payload: MCPServerConfig, request: Request):
    runtime = request.app.state.runtime
    server = runtime.mcp_registry.upsert_server(payload)
    runtime.reload_ecosystem()
    status = next((item for item in runtime.mcp_registry.list_statuses() if item.name == server.name), None)
    return {
        "server": server.model_dump(mode="json"),
        "status": status.model_dump(mode="json") if status else None,
    }


@router.delete("/servers/{server_name}")
async def delete_server(server_name: str, request: Request):
    runtime = request.app.state.runtime
    runtime.mcp_registry.delete_server(server_name)
    runtime.reload_ecosystem()
    return {"deleted": True, "server_name": server_name}


@router.post("/servers/{server_name}/reconnect")
async def reconnect_server(server_name: str, request: Request):
    runtime = request.app.state.runtime
    status = runtime.mcp_registry.reconnect_server(server_name)
    runtime.reload_ecosystem()
    return {"server_name": server_name, "status": status.model_dump(mode="json")}


@router.get("/resources")
async def list_resources(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    return {
        "resources": [item.model_dump(mode="json") for item in runtime.mcp_registry.list_resources()],
        "statuses": [item.model_dump(mode="json") for item in runtime.mcp_registry.list_statuses()],
    }
