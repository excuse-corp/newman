from __future__ import annotations

from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/channels", tags=["channels"])


class FeishuValidateRequest(BaseModel):
    timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)


class FeishuSetupTestRequest(BaseModel):
    timeout_seconds: float = Field(default=45.0, ge=1.0, le=300.0)
    validate_first: bool = True


@router.get("/status")
async def get_channel_status(request: Request):
    return {"channels": request.app.state.channels.list_status()}


@router.get("/events/stream")
async def stream_channel_events(request: Request):
    broker = request.app.state.channel_events

    async def event_stream():
        async for chunk in broker.stream():
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/feishu/setup/status")
async def get_feishu_setup_status(request: Request):
    return request.app.state.channels.get_feishu_setup_status()


@router.post("/feishu/setup/validate")
async def validate_feishu_setup(request: Request, body: FeishuValidateRequest | None = None):
    payload = body or FeishuValidateRequest()
    return await request.app.state.channels.validate_feishu_setup(timeout_seconds=payload.timeout_seconds)


@router.post("/feishu/setup/test")
async def test_feishu_setup(request: Request, body: FeishuSetupTestRequest | None = None):
    payload = body or FeishuSetupTestRequest()
    return await request.app.state.channels.test_feishu_setup(
        timeout_seconds=payload.timeout_seconds,
        validate_first=payload.validate_first,
    )


@router.post("/{platform}/webhook")
async def channel_webhook(platform: str, payload: dict, request: Request):
    headers = {key.lower(): value for key, value in request.headers.items()}
    result = await request.app.state.channels.handle_webhook(platform, payload, headers)
    return {"ok": True, "response": result}
