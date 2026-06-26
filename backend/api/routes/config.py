from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.api.runtime_reload import reload_project_runtime
from backend.config.loader import (
    get_project_config_path,
    get_project_dotenv_path,
    parse_dotenv_content,
    read_project_config_text,
    read_project_dotenv_text,
    resolve_project_root,
    validate_project_config_content,
    validate_project_dotenv_content,
)


router = APIRouter(prefix="/api/config", tags=["config"])

CONFIG_SOURCE_PRIORITY = [
    "environment",
    "~/.newman/config.yaml",
    "newman.yaml",
    "defaults.yaml",
]


class UpdateProjectConfigRequest(BaseModel):
    content: str = Field(..., min_length=0, description="newman.yaml 的完整内容")


class UpdateProjectDotenvRequest(BaseModel):
    content: str = Field(..., min_length=0, description=".env 的完整内容")


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


@router.get("/env")
async def get_project_dotenv(request: Request):
    root = _project_root(request)
    path = get_project_dotenv_path(str(root))
    content = read_project_dotenv_text(str(root))
    settings = request.app.state.settings
    return {
        "path": str(path),
        "content": content,
        "effective_workspace": str(settings.paths.workspace),
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


@router.put("/env")
async def update_project_dotenv(payload: UpdateProjectDotenvRequest, request: Request):
    root = _project_root(request)
    path = get_project_dotenv_path(str(root))
    previous_values = parse_dotenv_content(path.read_text(encoding="utf-8")) if path.exists() else {}
    next_values = parse_dotenv_content(payload.content)
    next_settings = validate_project_dotenv_content(payload.content, str(root))
    path.write_text(payload.content, encoding="utf-8")
    for key in previous_values:
        if key not in next_values:
            os.environ.pop(key, None)
    os.environ.update(next_values)
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
    root = _project_root(request)
    warnings = await reload_project_runtime(request.app, root)
    next_settings = request.app.state.settings
    return {
        "reloaded": True,
        "path": str(get_project_config_path(str(root))),
        "effective_workspace": str(next_settings.paths.workspace),
        "warnings": warnings,
    }


def _project_root(request: Request) -> Path:
    configured = getattr(request.app.state, "project_root", None)
    return resolve_project_root(str(configured) if configured else None)
