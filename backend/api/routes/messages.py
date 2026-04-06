from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.sse.event_emitter import format_sse


router = APIRouter(prefix="/api/sessions", tags=["messages"])


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


@router.post("/{session_id}/messages")
async def send_message(session_id: str, payload: SendMessageRequest, request: Request):
    runtime = request.app.state.runtime
    runtime.session_store.get(session_id)

    async def event_stream():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        settings = request.app.state.settings
        audit_path = Path(settings.paths.audit_dir) / f"{session_id}.log"
        stream_failed = False

        async def emit(event: str, data: dict):
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n")
            await queue.put(format_sse(event, data))

        async def run_worker() -> None:
            nonlocal stream_failed
            try:
                await runtime.handle_message(session_id, payload.content, emit)
            except Exception as exc:
                stream_failed = True
                await emit(
                    "error",
                    {
                        "code": "NEWMAN-API-999",
                        "message": "消息流处理中断",
                        "detail": str(exc),
                    },
                )
            finally:
                await emit("stream_completed", {"session_id": session_id, "ok": not stream_failed})

        worker = asyncio.create_task(run_worker())

        while True:
            if worker.done() and queue.empty():
                break
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue

        await worker

    return StreamingResponse(event_stream(), media_type="text/event-stream")
