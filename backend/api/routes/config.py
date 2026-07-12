from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.auth_utils import get_admin_token, set_auth_cookie
from backend.api.runtime_reload import _build_reload_warnings, reload_project_runtime
from backend.config.loader import (
    get_project_config_path,
    get_project_dotenv_path,
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
    next_settings = validate_project_dotenv_content(payload.content, str(root))
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
    root = _project_root(request)
    warnings = await reload_project_runtime(request.app, root)
    next_settings = request.app.state.settings
    response = JSONResponse({
        "reloaded": True,
        "path": str(get_project_config_path(str(root))),
        "effective_workspace": str(next_settings.paths.workspace),
        "warnings": warnings,
    })
    if getattr(request.state, "auth_method", None) == "cookie":
        admin_token = get_admin_token(next_settings)
        if admin_token:
            set_auth_cookie(response, request, next_settings, admin_token)
    return response


def _project_root(request: Request) -> Path:
    configured = getattr(request.app.state, "project_root", None)
    return resolve_project_root(str(configured) if configured else None)
