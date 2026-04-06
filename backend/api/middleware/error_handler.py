from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.api.errors import api_error_response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(FileNotFoundError)
    async def handle_not_found(request: Request, exc: FileNotFoundError) -> JSONResponse:
        return api_error_response(request, status_code=404, kind="not_found", message=str(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return api_error_response(request, status_code=422, kind="validation", message="请求参数校验失败", details=exc.errors())

    @app.exception_handler(ValueError)
    async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        return api_error_response(request, status_code=400, kind="validation", message=str(exc))

    @app.exception_handler(PermissionError)
    async def handle_permission_error(request: Request, exc: PermissionError) -> JSONResponse:
        return api_error_response(request, status_code=403, kind="conflict", message=str(exc))

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        kind = "not_found" if exc.status_code == 404 else "conflict" if exc.status_code == 409 else "validation"
        return api_error_response(request, status_code=exc.status_code, kind=kind, message=str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unknown(request: Request, exc: Exception) -> JSONResponse:
        return api_error_response(request, status_code=500, kind="internal", message="服务内部错误", details=str(exc))
