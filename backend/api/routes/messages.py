from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from backend.api.sse.event_emitter import format_sse


router = APIRouter(prefix="/api/sessions", tags=["messages"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@router.post("/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    runtime = request.app.state.runtime
    runtime.session_store.get(session_id)
    request_id = getattr(request.state, "request_id", None)

    content, uploads = await _parse_request_payload(request)
    if not content.strip() and not uploads:
        raise ValueError("content 不能为空，或者至少上传一张图片")

    async def event_stream():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        settings = request.app.state.settings
        audit_path = Path(settings.paths.audit_dir) / f"{session_id}.log"
        upload_dir = settings.paths.data_dir / "uploads" / "chat" / session_id
        stream_failed = False

        async def emit(event: str, data: dict):
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"event": event, "data": data, "request_id": request_id}, ensure_ascii=False) + "\n")
            await queue.put(format_sse(event, data, request_id=request_id))

        async def run_worker() -> None:
            nonlocal stream_failed
            try:
                saved_attachments = await _save_uploads(upload_dir, uploads)
                if saved_attachments:
                    await emit(
                        "attachment_received",
                        {
                            "count": len(saved_attachments),
                            "files": [
                                {"filename": item["filename"], "content_type": item["content_type"]}
                                for item in saved_attachments
                            ],
                        },
                    )
                    analyses = await runtime.multimodal_analyzer.analyze_images(
                        content,
                        [Path(item["path"]) for item in saved_attachments],
                    )
                    for item, analysis in zip(saved_attachments, analyses, strict=True):
                        item["summary"] = analysis["summary"]
                    await emit(
                        "attachment_processed",
                        {
                            "count": len(saved_attachments),
                            "files": [
                                {"filename": item["filename"], "summary": item["summary"]}
                                for item in saved_attachments
                            ],
                        },
                    )
                else:
                    saved_attachments = []

                prepared_content = _augment_user_content(content, saved_attachments)
                metadata = {
                    "attachments": [
                        {
                            "filename": item["filename"],
                            "content_type": item["content_type"],
                            "path": item["path"],
                            "summary": item.get("summary", ""),
                        }
                        for item in saved_attachments
                    ],
                    "original_content": content,
                }
                await runtime.handle_message(
                    session_id,
                    prepared_content,
                    emit,
                    user_metadata=metadata,
                )
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


async def _parse_request_payload(request: Request) -> tuple[str, list[UploadFile]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body = await request.json()
        content = str(body.get("content", "")).strip()
        return content, []

    form = await request.form()
    content = str(form.get("content", "")).strip()
    uploads = [item for item in form.getlist("images") if isinstance(item, UploadFile)]
    return content, uploads


async def _save_uploads(upload_dir: Path, uploads: list[UploadFile]) -> list[dict[str, str]]:
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, str]] = []
    for upload in uploads:
        filename = upload.filename or "image"
        suffix = Path(filename).suffix.lower()
        if upload.content_type not in ALLOWED_IMAGE_TYPES or suffix not in ALLOWED_IMAGE_SUFFIXES:
            raise ValueError(f"仅支持 jpg/png 图片: {filename}")
        target = upload_dir / f"{uuid4().hex}{suffix}"
        data = await upload.read()
        target.write_bytes(data)
        saved.append(
            {
                "filename": filename,
                "content_type": upload.content_type or "application/octet-stream",
                "path": str(target),
            }
        )
    return saved


def _augment_user_content(content: str, attachments: list[dict[str, str]]) -> str:
    base = content.strip()
    if not attachments:
        return base
    blocks = ["## Uploaded Images"]
    for item in attachments:
        blocks.append(f"- {item['filename']}: {item.get('summary', '').strip()}")
    image_context = "\n".join(blocks).strip()
    if not base:
        return image_context
    return f"{base}\n\n{image_context}"
