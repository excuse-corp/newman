from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from backend.api.sse.event_emitter import build_event_payload, format_sse_payload
from backend.sessions.models import SessionMessage
from backend.tools.approval_policy import normalize_turn_approval_mode


router = APIRouter(prefix="/api/sessions", tags=["messages"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@dataclass
class ActiveSessionRun:
    session_id: str
    request_id: str | None
    worker: asyncio.Task
    event_queue: asyncio.Queue[bytes] | None = None
    turn_id: str | None = None
    user_content: str = ""
    approval_mode: str = "manual"
    interrupted: bool = False


@router.post("/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    runtime = request.app.state.runtime
    runtime.session_store.get(session_id)
    request_id = getattr(request.state, "request_id", None)
    active_runs = _ensure_active_session_runs(request)
    existing = active_runs.get(session_id)
    if existing is not None:
        if existing.worker.done():
            _clear_active_session_run(active_runs, session_id, existing)
        else:
            raise HTTPException(status_code=409, detail="当前会话已有任务在运行，请先等待完成或停止")

    content, uploads, approval_mode = await _parse_request_payload(request)
    if not content.strip() and not uploads:
        raise ValueError("content 不能为空，或者至少上传一张图片")
    provisional_turn_id = uuid4().hex

    async def event_stream():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        settings = request.app.state.settings
        audit_path = Path(settings.paths.audit_dir) / f"{session_id}.log"
        upload_dir = settings.paths.data_dir / "uploads" / "chat" / session_id
        stream_failed = False
        stream_closed = False
        active_run: ActiveSessionRun | None = None

        async def emit(event: str, data: dict):
            if stream_closed:
                return
            current_run = active_runs.get(session_id)
            if current_run is not None and current_run.interrupted and event != "stream_completed":
                return
            payload = build_event_payload(event, data, request_id=request_id)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            await queue.put(format_sse_payload(payload))

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
                        session_id=session_id,
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
                    "approval_mode": approval_mode,
                    "original_content": content,
                }
                await runtime.handle_message(
                    session_id,
                    prepared_content,
                    emit,
                    user_metadata=metadata,
                    turn_approval_mode=approval_mode,
                    request_id=request_id,
                    turn_id=provisional_turn_id,
                    on_turn_created=lambda turn_id: _set_active_run_turn_id(active_runs, session_id, active_run, turn_id),
                )
            except asyncio.CancelledError:
                stream_failed = True
                raise
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
                current_run = active_runs.get(session_id)
                if current_run is not None:
                    current_run.turn_id = current_run.turn_id or _resolve_turn_id(runtime, session_id, request_id)
                if not stream_closed:
                    await emit("stream_completed", {"session_id": session_id, "ok": not stream_failed})

        worker = asyncio.create_task(run_worker())
        active_run = ActiveSessionRun(
            session_id=session_id,
            request_id=request_id,
            worker=worker,
            event_queue=queue,
            turn_id=provisional_turn_id,
            user_content=content,
            approval_mode=approval_mode,
        )
        active_runs[session_id] = active_run
        try:
            while True:
                if await request.is_disconnected():
                    stream_closed = True
                    worker.cancel()
                    break
                if worker.done() and queue.empty():
                    break
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
        finally:
            stream_closed = True
            if not worker.done():
                worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
            _clear_active_session_run(active_runs, session_id, active_run)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{session_id}/interrupt")
async def interrupt_message(session_id: str, request: Request):
    runtime = request.app.state.runtime
    runtime.session_store.get(session_id)
    active_runs = _ensure_active_session_runs(request)
    active_run = active_runs.get(session_id)
    if active_run is None:
        return {
            "interrupted": False,
            "session_id": session_id,
            "reason": "no_active_run",
        }

    if active_run.worker.done():
        _clear_active_session_run(active_runs, session_id, active_run)
        return {
            "interrupted": False,
            "session_id": session_id,
            "reason": "already_completed",
        }

    turn_id = active_run.turn_id or _resolve_turn_id(runtime, session_id, active_run.request_id)
    active_run.turn_id = turn_id
    active_run.interrupted = True

    payload = _persist_turn_interrupted(
        runtime,
        request.app.state.settings.paths.audit_dir / f"{session_id}.log",
        session_id=session_id,
        request_id=active_run.request_id,
        turn_id=turn_id,
        user_content=active_run.user_content,
        approval_mode=active_run.approval_mode,
    )

    await _queue_active_run_payload(active_run, payload)
    active_run.worker.cancel()
    with suppress(asyncio.CancelledError):
        await active_run.worker
    _clear_active_session_run(active_runs, session_id, active_run)

    return {
        "interrupted": True,
        "session_id": session_id,
        "request_id": active_run.request_id,
        "turn_id": turn_id,
        "message": payload["data"]["message"],
    }


async def _parse_request_payload(request: Request) -> tuple[str, list[UploadFile], str]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        body = await request.json()
        content = str(body.get("content", "")).strip()
        approval_mode = normalize_turn_approval_mode(body.get("approval_mode"))
        return content, [], approval_mode

    form = await request.form()
    content = str(form.get("content", "")).strip()
    uploads = [item for item in form.getlist("images") if isinstance(item, UploadFile)]
    approval_mode = normalize_turn_approval_mode(form.get("approval_mode"))
    return content, uploads, approval_mode


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


def _ensure_active_session_runs(request: Request) -> dict[str, ActiveSessionRun]:
    active_runs = getattr(request.app.state, "active_message_runs", None)
    if isinstance(active_runs, dict):
        return active_runs
    request.app.state.active_message_runs = {}
    return request.app.state.active_message_runs


def _clear_active_session_run(active_runs: dict[str, ActiveSessionRun], session_id: str, active_run: ActiveSessionRun) -> None:
    current = active_runs.get(session_id)
    if current is active_run:
        active_runs.pop(session_id, None)


def _set_active_run_turn_id(
    active_runs: dict[str, ActiveSessionRun],
    session_id: str,
    active_run: ActiveSessionRun | None,
    turn_id: str,
) -> None:
    if active_run is not None:
        active_run.turn_id = turn_id
    current = active_runs.get(session_id)
    if current is not None:
        current.turn_id = turn_id


def _resolve_turn_id(runtime, session_id: str, request_id: str | None) -> str | None:
    session = runtime.session_store.get(session_id)
    if request_id:
        for message in reversed(session.messages):
            if message.role != "user":
                continue
            if message.metadata.get("request_id") != request_id:
                continue
            turn_id = message.metadata.get("turn_id")
            if isinstance(turn_id, str) and turn_id:
                return turn_id
    for message in reversed(session.messages):
        turn_id = message.metadata.get("turn_id")
        if isinstance(turn_id, str) and turn_id:
            return turn_id
    return None


def _persist_turn_interrupted(
    runtime,
    audit_path: Path,
    *,
    session_id: str,
    request_id: str | None,
    turn_id: str | None,
    user_content: str,
    approval_mode: str,
) -> dict[str, object]:
    message = "当前任务已停止"
    session = runtime.session_store.get(session_id)
    if turn_id and not any(item.role == "user" and item.metadata.get("turn_id") == turn_id for item in session.messages):
        session.messages.append(
            SessionMessage(
                id=turn_id,
                role="user",
                content=user_content,
                metadata={
                    "turn_id": turn_id,
                    **({"request_id": request_id} if request_id else {}),
                    "approval_mode": approval_mode,
                    "original_content": user_content,
                },
            )
        )
    already_recorded = any(
        item.role == "system"
        and item.metadata.get("type") == "turn_interrupted"
        and item.metadata.get("turn_id") == turn_id
        and item.metadata.get("request_id") == request_id
        for item in session.messages
    )
    if not already_recorded:
        session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=message,
                metadata={
                    "type": "turn_interrupted",
                    **({"turn_id": turn_id} if turn_id else {}),
                    **({"request_id": request_id} if request_id else {}),
                },
            )
        )
        runtime.session_store.save(session)

    payload = build_event_payload(
        "turn_interrupted",
        {
            "message": message,
            **({"turn_id": turn_id} if turn_id else {}),
        },
        request_id=request_id,
    )
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


async def _queue_active_run_payload(active_run: ActiveSessionRun, payload: dict[str, object]) -> None:
    if active_run.event_queue is None:
        return
    await active_run.event_queue.put(format_sse_payload(payload))
