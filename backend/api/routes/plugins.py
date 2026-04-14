from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.tools.workspace_fs import build_path_access_policy, ensure_readable_path


router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class ImportPluginRequest(BaseModel):
    source_path: str = Field(..., min_length=1, description="可读目录内待导入的 plugin 文件夹路径")


class UpdatePluginRequest(BaseModel):
    content: str = Field(..., min_length=0, description="plugin.yaml 的完整内容")


@router.get("")
async def list_plugins(request: Request):
    runtime = request.app.state.runtime
    return {
        "plugins": [item.model_dump(mode="json") for item in runtime.plugin_service.list_plugins()],
        "errors": [item.model_dump(mode="json") for item in runtime.plugin_service.list_load_errors()],
    }


@router.post("/import")
async def import_plugin(payload: ImportPluginRequest, request: Request):
    runtime = request.app.state.runtime
    policy = build_path_access_policy(request.app.state.settings)
    source_dir = ensure_readable_path(policy, payload.source_path)
    try:
        plugin = runtime.plugin_service.import_plugin(source_dir)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    runtime.reload_ecosystem()
    return {"plugin": _build_plugin_detail(runtime, plugin.name)}


@router.post("/rescan")
async def rescan_plugins(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    return {
        "reloaded": True,
        "plugins": [item.model_dump(mode="json") for item in runtime.plugin_service.list_plugins()],
        "errors": [item.model_dump(mode="json") for item in runtime.plugin_service.list_load_errors()],
    }


@router.get("/{plugin_name}")
async def get_plugin(plugin_name: str, request: Request):
    runtime = request.app.state.runtime
    return {"plugin": _build_plugin_detail(runtime, plugin_name)}


@router.post("/{plugin_name}/enable")
async def enable_plugin(plugin_name: str, request: Request):
    runtime = request.app.state.runtime
    plugin = runtime.plugin_service.set_enabled(plugin_name, True)
    runtime.reload_ecosystem()
    return {"plugin": _build_plugin_detail(runtime, plugin.name)}


@router.post("/{plugin_name}/disable")
async def disable_plugin(plugin_name: str, request: Request):
    runtime = request.app.state.runtime
    plugin = runtime.plugin_service.set_enabled(plugin_name, False)
    runtime.reload_ecosystem()
    return {"plugin": _build_plugin_detail(runtime, plugin.name)}


@router.put("/{plugin_name}")
async def update_plugin(plugin_name: str, payload: UpdatePluginRequest, request: Request):
    runtime = request.app.state.runtime
    try:
        plugin = runtime.plugin_service.update_plugin_manifest(plugin_name, payload.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runtime.reload_ecosystem()
    return {"plugin": _build_plugin_detail(runtime, plugin.name)}


@router.delete("/{plugin_name}")
async def delete_plugin(plugin_name: str, request: Request):
    runtime = request.app.state.runtime
    plugin = runtime.plugin_service.delete_plugin(plugin_name)
    runtime.reload_ecosystem()
    return {"deleted": True, "plugin_name": plugin.name}


def _build_plugin_detail(runtime, plugin_name: str) -> dict:
    plugin = runtime.plugin_service.get_plugin(plugin_name)
    record = runtime.plugin_service.plugin_record(plugin_name)
    manifest_content = runtime.plugin_service.read_plugin_manifest_content(plugin_name)
    tool_names = sorted(
        tool.meta.name
        for tool in runtime.mcp_registry.build_tools(plugin.manifest.mcp_servers)
    )
    hook_handlers = [
        {
            "event": hook.event,
            "handler": hook.handler,
            "message": hook.message,
            "timeout_seconds": hook.timeout_seconds,
            "path": str((plugin.root_path / hook.handler).resolve()) if hook.handler else None,
        }
        for hook in plugin.manifest.hooks
    ]
    return {
        **record.model_dump(mode="json"),
        "directory_path": str(plugin.root_path),
        "manifest_path": str(plugin.root_path / "plugin.yaml"),
        "manifest": plugin.manifest.model_dump(mode="json"),
        "manifest_content": manifest_content,
        "skill_paths": [str(Path(skill.path).parent) for skill in plugin.skills],
        "hook_handlers": hook_handlers,
        "tool_names": tool_names,
        "available": True,
    }
