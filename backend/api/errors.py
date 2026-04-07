from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.runtime.error_codes import resolve_api_error


def api_error_response(
    request: Request,
    *,
    status_code: int,
    kind: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    descriptor = resolve_api_error(kind)
    payload = {
        "error": {
            "code": descriptor.code,
            "message": message,
            "severity": descriptor.severity,
            "risk_level": descriptor.risk_level,
            "kind": kind,
        },
        "request_id": getattr(request.state, "request_id", None),
    }
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=payload)
