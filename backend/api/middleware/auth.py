from __future__ import annotations

from uuid import uuid4

from fastapi import Request

from backend.api.auth_utils import (
    clear_auth_cookie,
    ensure_state_changing_origin_allowed,
    is_auth_enabled,
    needs_bootstrap,
    resolve_request_auth,
)
from backend.api.errors import api_error_response


PUBLIC_EXACT_PATHS = {
    "/healthz",
    "/readyz",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/bootstrap/status",
    "/api/bootstrap/setup",
}


async def auth_middleware(request: Request, call_next):
    settings = request.app.state.settings
    request.state.authenticated = False
    request.state.auth_method = None

    if not is_auth_enabled(settings) or _is_public_request(request):
        return await call_next(request)

    if needs_bootstrap(settings):
        return _error_response(
            request,
            status_code=503,
            kind="conflict",
            message="服务尚未完成首次配置，请先完成引导。",
        )

    auth_state = resolve_request_auth(request, settings)
    if not auth_state.authenticated:
        response = _error_response(
            request,
            status_code=401,
            kind="auth",
            message="未认证或登录已失效。",
        )
        if auth_state.method == "cookie":
            clear_auth_cookie(response, settings)
        return response

    if not ensure_state_changing_origin_allowed(request, settings, auth_method=auth_state.method):
        import logging
        logging.getLogger("newman.auth").warning(
            "origin check failed: origin=%r referer=%r host=%r xfh=%r xfp=%r cors=%r",
            request.headers.get("origin"),
            request.headers.get("referer"),
            request.headers.get("host"),
            request.headers.get("x-forwarded-host"),
            request.headers.get("x-forwarded-proto"),
            settings.server.cors_origins,
        )
        return _error_response(
            request,
            status_code=403,
            kind="forbidden",
            message="当前请求来源不被允许，请从同源页面发起操作。",
        )

    request.state.authenticated = True
    request.state.auth_method = auth_state.method
    return await call_next(request)


def _is_public_request(request: Request) -> bool:
    path = request.url.path
    if request.method.upper() == "OPTIONS":
        return True
    if path in PUBLIC_EXACT_PATHS:
        return True
    return path.startswith("/api/channels/") and path.endswith("/webhook")


def _error_response(request: Request, *, status_code: int, kind: str, message: str):
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        request_id = uuid4().hex
        request.state.request_id = request_id
    response = api_error_response(request, status_code=status_code, kind=kind, message=message)
    response.headers["x-request-id"] = request_id
    return response
