from __future__ import annotations

import inspect
from pathlib import Path

from fastapi import APIRouter, Request

from backend.tools.workspace_fs import build_path_access_policy, classify_path


router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    return {"tools": [_build_tool_detail(request, tool) for tool in runtime.registry.list_tools()]}


@router.get("/{tool_name}")
async def get_tool(tool_name: str, request: Request):
    runtime = request.app.state.runtime
    tool = next((item for item in runtime.registry.list_tools() if item.meta.name == tool_name), None)
    if tool is None:
        raise FileNotFoundError(f"Tool not found: {tool_name}")
    return {"tool": _build_tool_detail(request, tool)}


@router.post("/rescan")
async def rescan_tools(request: Request):
    runtime = request.app.state.runtime
    runtime.reload_ecosystem()
    return {"reloaded": True, "tools": [_build_tool_detail(request, tool) for tool in runtime.registry.list_tools()]}


def _build_tool_detail(request: Request, tool) -> dict:
    settings = request.app.state.settings
    policy = build_path_access_policy(settings)
    module_name = tool.__class__.__module__
    module_path = inspect.getsourcefile(tool.__class__)
    source_type = _source_type(tool.meta.name, module_name)
    file_path = str(Path(module_path).resolve()) if module_path else None
    file_access = None
    if file_path is not None:
        try:
            file_access = classify_path(policy, Path(file_path))
        except Exception:
            file_access = None
    return {
        "name": tool.meta.name,
        "description": tool.meta.description,
        "risk_level": tool.meta.risk_level,
        "approval_behavior": tool.meta.approval_behavior,
        "requires_approval": tool.meta.requires_approval,
        "timeout_seconds": tool.meta.timeout_seconds,
        "allowed_paths": tool.meta.allowed_paths,
        "source_type": source_type,
        "module": module_name,
        "class_name": tool.__class__.__name__,
        "file_path": file_path,
        "file_access": file_access,
        "managed": source_type == "builtin" and file_access == "writable",
        "input_schema": tool.meta.input_schema,
    }


def _source_type(tool_name: str, module_name: str) -> str:
    if tool_name.startswith("mcp__") or module_name.startswith("backend.mcp"):
        return "mcp"
    if module_name.startswith("backend.tools.impl"):
        return "builtin"
    return "runtime"
