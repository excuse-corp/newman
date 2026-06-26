from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.auth_utils import (
    generate_admin_token,
    is_auth_enabled,
    needs_bootstrap,
    persist_project_env_updates,
    set_auth_cookie,
)
from backend.api.runtime_reload import reload_project_runtime
from backend.config.loader import resolve_project_root


router = APIRouter(prefix="/api/bootstrap", tags=["bootstrap"])


class BootstrapSetupRequest(BaseModel):
    primary_endpoint: str = Field(..., min_length=1, max_length=512, description="主模型 endpoint")
    primary_api_key: str = Field(..., min_length=1, max_length=512, description="主模型 API key")
    primary_model: str = Field(..., min_length=1, max_length=256, description="主模型名称")
    share_primary_for_multimodal: bool = True
    multimodal_endpoint: str | None = Field(default=None, max_length=512, description="多模态模型 endpoint")
    multimodal_api_key: str | None = Field(default=None, max_length=512, description="多模态模型 API key")
    multimodal_model: str | None = Field(default=None, max_length=256, description="多模态模型名称")
    serpapi_api_key: str | None = Field(default=None, max_length=512, description="SerpApi key")
    feishu_app_id: str | None = Field(default=None, max_length=256, description="飞书应用 app_id")
    feishu_app_secret: str | None = Field(default=None, max_length=512, description="飞书应用 app_secret")
    login_after_setup: bool = True


@router.get("/status")
async def bootstrap_status(request: Request):
    settings = request.app.state.settings
    return {
        "enabled": is_auth_enabled(settings),
        "needs_setup": needs_bootstrap(settings),
    }


@router.post("/setup")
async def complete_bootstrap(request: Request, payload: BootstrapSetupRequest):
    settings = request.app.state.settings
    if not is_auth_enabled(settings):
        raise HTTPException(status_code=409, detail="当前部署已禁用实例鉴权，不需要执行首次配置。")
    if not needs_bootstrap(settings):
        raise HTTPException(status_code=409, detail="当前部署已经完成首次配置。")
    env_updates = _build_bootstrap_env_updates(payload)
    admin_token = generate_admin_token()
    env_updates["NEWMAN_AUTH__ADMIN_TOKEN"] = admin_token
    persist_project_env_updates(request, env_updates, reload_settings_after_write=False)
    root = resolve_project_root(getattr(request.app.state, "project_root", None))
    warnings = await reload_project_runtime(request.app, root)

    response = JSONResponse({
        "configured": True,
        "authenticated": bool(payload.login_after_setup),
        "admin_token_configured": True,
        "warnings": warnings,
    })
    if payload.login_after_setup:
        set_auth_cookie(response, request, request.app.state.settings, admin_token)
    return response


def _build_bootstrap_env_updates(payload: BootstrapSetupRequest) -> dict[str, str]:
    primary_endpoint = payload.primary_endpoint.strip()
    primary_api_key = payload.primary_api_key.strip()
    primary_model = payload.primary_model.strip()
    if not primary_endpoint or not primary_api_key or not primary_model:
        raise HTTPException(status_code=422, detail="主模型 endpoint、API key 和 model 不能为空。")

    updates: dict[str, str] = {
        "NEWMAN_MODELS_PRIMARY_TYPE": "openai_compatible",
        "NEWMAN_MODELS_PRIMARY_ENDPOINT": primary_endpoint,
        "NEWMAN_MODELS_PRIMARY_API_KEY": primary_api_key,
        "NEWMAN_MODELS_PRIMARY_MODEL": primary_model,
    }

    if payload.share_primary_for_multimodal:
        updates.update(
            {
                "NEWMAN_MODELS_MULTIMODAL_TYPE": "openai_compatible",
                "NEWMAN_MODELS_MULTIMODAL_ENDPOINT": primary_endpoint,
                "NEWMAN_MODELS_MULTIMODAL_API_KEY": primary_api_key,
                "NEWMAN_MODELS_MULTIMODAL_MODEL": (payload.multimodal_model or primary_model).strip() or primary_model,
            }
        )
    else:
        multimodal_endpoint = (payload.multimodal_endpoint or "").strip()
        multimodal_api_key = (payload.multimodal_api_key or "").strip()
        multimodal_model = (payload.multimodal_model or "").strip()
        if not multimodal_endpoint or not multimodal_api_key or not multimodal_model:
            raise HTTPException(status_code=422, detail="多模态单独配置时，endpoint、API key 和 model 都不能为空。")
        updates.update(
            {
                "NEWMAN_MODELS_MULTIMODAL_TYPE": "openai_compatible",
                "NEWMAN_MODELS_MULTIMODAL_ENDPOINT": multimodal_endpoint,
                "NEWMAN_MODELS_MULTIMODAL_API_KEY": multimodal_api_key,
                "NEWMAN_MODELS_MULTIMODAL_MODEL": multimodal_model,
            }
        )

    serpapi_api_key = (payload.serpapi_api_key or "").strip()
    if serpapi_api_key:
        updates["SERPAPI_API_KEY"] = serpapi_api_key

    feishu_app_id = (payload.feishu_app_id or "").strip()
    feishu_app_secret = (payload.feishu_app_secret or "").strip()
    if feishu_app_id or feishu_app_secret:
        if not feishu_app_id or not feishu_app_secret:
            raise HTTPException(status_code=422, detail="飞书接入需要同时填写 app_id 和 app_secret。")
        updates["NEWMAN_CHANNELS__FEISHU__APP_ID"] = feishu_app_id
        updates["NEWMAN_CHANNELS__FEISHU__APP_SECRET"] = feishu_app_secret
    return updates
