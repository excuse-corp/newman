from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("")
async def list_plugins(request: Request):
    runtime = request.app.state.runtime
    return {
        "plugins": [item.model_dump(mode="json") for item in runtime.plugin_service.list_plugins()],
        "errors": [item.model_dump(mode="json") for item in runtime.plugin_service.list_load_errors()],
    }


@router.post("/rescan")
async def rescan_plugins(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    return {
        "reloaded": True,
        "plugins": [item.model_dump(mode="json") for item in runtime.plugin_service.list_plugins()],
        "errors": [item.model_dump(mode="json") for item in runtime.plugin_service.list_load_errors()],
    }


@router.post("/{plugin_name}/enable")
async def enable_plugin(plugin_name: str, request: Request):
    runtime = request.app.state.runtime
    plugin = runtime.plugin_service.set_enabled(plugin_name, True)
    runtime.reload_ecosystem()
    return {"plugin": plugin.model_dump(mode="json")}


@router.post("/{plugin_name}/disable")
async def disable_plugin(plugin_name: str, request: Request):
    runtime = request.app.state.runtime
    plugin = runtime.plugin_service.set_enabled(plugin_name, False)
    runtime.reload_ecosystem()
    return {"plugin": plugin.model_dump(mode="json")}
