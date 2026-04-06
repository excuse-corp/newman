from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("/status")
async def get_channel_status(request: Request):
    return {"channels": request.app.state.channels.list_status()}


@router.post("/{platform}/webhook")
async def channel_webhook(platform: str, payload: dict, request: Request):
    headers = {key.lower(): value for key, value in request.headers.items()}
    result = await request.app.state.channels.handle_webhook(platform, payload, headers)
    return {"ok": True, "response": result}
