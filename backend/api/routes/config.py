from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.channels.service import ChannelService
from backend.config.loader import (
    get_project_config_path,
    log_settings_report,
    read_project_config_text,
    reload_settings,
    resolve_project_root,
    validate_project_config_content,
)
from backend.runtime.run_loop import NewmanRuntime
from backend.scheduler.scheduler_engine import SchedulerEngine


router = APIRouter(prefix="/api/config", tags=["config"])

CONFIG_SOURCE_PRIORITY = [
    "environment",
    "~/.newman/config.yaml",
    "newman.yaml",
    "defaults.yaml",
]


class UpdateProjectConfigRequest(BaseModel):
    content: str = Field(..., min_length=0, description="newman.yaml 的完整内容")


@router.get("/project")
async def get_project_config(request: Request):
    root = _project_root(request)
    path = get_project_config_path(str(root))
    content = read_project_config_text(str(root))
    settings = request.app.state.settings
    return {
        "path": str(path),
        "content": content,
        "effective_workspace": str(settings.paths.workspace),
        "source_priority": CONFIG_SOURCE_PRIORITY,
        "reload_supported": True,
    }


@router.put("/project")
async def update_project_config(payload: UpdateProjectConfigRequest, request: Request):
    root = _project_root(request)
    next_settings = validate_project_config_content(payload.content, str(root))
    path = get_project_config_path(str(root))
    path.write_text(payload.content, encoding="utf-8")
    warnings = _build_reload_warnings(request.app.state.settings, next_settings)
    return {
        "saved": True,
        "path": str(path),
        "content": payload.content,
        "effective_workspace": str(next_settings.paths.workspace),
        "requires_reload": True,
        "warnings": warnings,
    }


@router.post("/reload")
async def reload_project_config(request: Request):
    app = request.app
    root = _project_root(request)
    previous_settings = app.state.settings
    previous_runtime = app.state.runtime
    previous_scheduler = app.state.scheduler
    previous_channels = app.state.channels

    next_settings = reload_settings(str(root))
    log_settings_report(str(root))
    next_runtime = NewmanRuntime(next_settings)
    next_scheduler = SchedulerEngine(next_runtime.scheduler_store, next_runtime)
    next_channels = ChannelService(next_settings, next_runtime)
    next_runtime.reload_ecosystem()
    next_scheduler.refresh_schedule()

    await previous_scheduler.stop()
    try:
        app.state.settings = next_settings
        app.state.runtime = next_runtime
        app.state.scheduler = next_scheduler
        app.state.channels = next_channels
        await next_scheduler.start()
    except Exception:
        app.state.settings = previous_settings
        app.state.runtime = previous_runtime
        app.state.scheduler = previous_scheduler
        app.state.channels = previous_channels
        next_runtime.close()
        await previous_scheduler.start()
        raise

    previous_runtime.close()
    warnings = _build_reload_warnings(previous_settings, next_settings)
    return {
        "reloaded": True,
        "path": str(get_project_config_path(str(root))),
        "effective_workspace": str(next_settings.paths.workspace),
        "warnings": warnings,
    }


def _project_root(request: Request) -> Path:
    configured = getattr(request.app.state, "project_root", None)
    return resolve_project_root(str(configured) if configured else None)


def _build_reload_warnings(previous_settings, next_settings) -> list[str]:
    warnings: list[str] = []
    if previous_settings.server.host != next_settings.server.host or previous_settings.server.port != next_settings.server.port:
        warnings.append("`server.host` / `server.port` 的变化需要重启进程后才能真正改变监听地址。")
    if previous_settings.server.cors_origins != next_settings.server.cors_origins:
        warnings.append("`server.cors_origins` 已写入配置，但现有 CORS 中间件需要重启进程后才会更新。")
    return warnings
