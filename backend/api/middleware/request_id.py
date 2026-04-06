from __future__ import annotations

from uuid import uuid4

from fastapi import Request


async def request_id_middleware(request: Request, call_next):
    request.state.request_id = uuid4().hex
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    return response
