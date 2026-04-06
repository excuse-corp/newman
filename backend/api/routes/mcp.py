from __future__ import annotations

from fastapi import APIRouter, Request

from backend.mcp.models import MCPServerConfig


router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/servers")
async def list_servers(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    return {
        "servers": [item.model_dump(mode="json") for item in runtime.mcp_registry.list_servers()],
        "statuses": [item.model_dump(mode="json") for item in runtime.mcp_registry.list_statuses()],
    }


@router.post("/servers")
async def upsert_server(payload: MCPServerConfig, request: Request):
    runtime = request.app.state.runtime
    server = runtime.mcp_registry.upsert_server(payload)
    runtime.reload_ecosystem()
    return {"server": server.model_dump(mode="json")}
