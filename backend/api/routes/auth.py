from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.auth_utils import (
    clear_auth_cookie,
    generate_admin_token,
    get_admin_token,
    is_auth_enabled,
    needs_bootstrap,
    persist_project_env_updates,
    resolve_request_auth,
    set_auth_cookie,
    validate_admin_token,
    verify_admin_token,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    admin_token: str = Field(..., min_length=1, max_length=256, description="实例访问密钥")


class RegenerateTokenResponse(BaseModel):
    rotated: bool
    admin_token: str
    instance_token: str
    auth_method: str


@router.get("/status")
async def auth_status(request: Request):
    settings = request.app.state.settings
    auth_state = resolve_request_auth(request, settings)
    token_present = bool(get_admin_token(settings))
    return {
        "enabled": is_auth_enabled(settings),
        "needs_setup": needs_bootstrap(settings),
        "authenticated": (not is_auth_enabled(settings)) or auth_state.authenticated,
        "auth_method": auth_state.method if auth_state.authenticated else None,
        "admin_token_configured": token_present,
    }


@router.post("/login")
async def login(request: Request, payload: LoginRequest):
    settings = request.app.state.settings
    if not is_auth_enabled(settings):
        return {"authenticated": True, "auth_method": "disabled"}
    if needs_bootstrap(settings):
        raise HTTPException(status_code=409, detail="服务尚未完成首次配置，请先完成引导。")
    admin_token = validate_admin_token(payload.admin_token)
    if not verify_admin_token(settings, admin_token):
        raise HTTPException(status_code=401, detail="实例访问密钥不正确。")

    response = JSONResponse({"authenticated": True, "auth_method": "cookie"})
    set_auth_cookie(response, request, settings, admin_token)
    return response


@router.post("/logout")
async def logout(request: Request):
    response = JSONResponse(
        {
            "authenticated": False,
            "auth_method": None,
            "needs_setup": needs_bootstrap(request.app.state.settings),
        }
    )
    clear_auth_cookie(response, request.app.state.settings)
    return response


@router.post("/regenerate-token", response_model=RegenerateTokenResponse)
async def regenerate_token(request: Request):
    settings = request.app.state.settings
    auth_state = resolve_request_auth(request, settings)
    if not auth_state.authenticated:
        raise HTTPException(status_code=401, detail="未认证或登录已失效。")
    if not is_auth_enabled(settings):
        raise HTTPException(status_code=409, detail="当前部署已禁用实例鉴权，不需要重新生成实例访问密钥。")
    if needs_bootstrap(settings):
        raise HTTPException(status_code=409, detail="服务尚未完成首次配置，请先完成引导。")

    admin_token = generate_admin_token()
    next_settings = persist_project_env_updates(request, {"NEWMAN_AUTH__ADMIN_TOKEN": admin_token})
    if next_settings is None:
        raise HTTPException(status_code=500, detail="实例访问密钥更新失败。")

    response = JSONResponse(
        {"rotated": True, "admin_token": admin_token, "instance_token": admin_token, "auth_method": "cookie"}
    )
    set_auth_cookie(response, request, next_settings, admin_token)
    return response
