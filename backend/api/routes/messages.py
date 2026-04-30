from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from backend.attachments import AttachmentService
from backend.api.sse.event_emitter import build_event_payload, format_sse_payload
from backend.runtime.message_rendering import build_user_message_title
from backend.sessions.models import SessionMessage
from backend.tools.approval_policy import normalize_turn_approval_mode


router = APIRouter(prefix="/api/sessions", tags=["messages"])


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
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None and getattr(scheduler, "has_active_scheduler_session", None):
        if scheduler.has_active_scheduler_session(session_id):
            raise HTTPException(status_code=409, detail="当前会话已有定时任务在运行，请先等待完成")

    content, uploads, approval_mode = await _parse_request_payload(request)
    if not content.strip() and not uploads:
        raise ValueError("content 不能为空，或者至少上传一个附件")
    provisional_turn_id = uuid4().hex

    async def event_stream():
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        settings = request.app.state.settings
        audit_path = Path(settings.paths.audit_dir) / f"{session_id}.log"
        workspace_root = Path(getattr(settings.paths, "workspace", settings.paths.data_dir / "runtime_workspace")).resolve()
        attachment_service = AttachmentService(workspace_root, runtime.multimodal_analyzer)
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
                saved_attachments = await attachment_service.save_uploads(session_id, provisional_turn_id, uploads) if uploads else []
                metadata = {
                    "attachments": attachment_service.serialize(saved_attachments),
                    "approval_mode": approval_mode,
                    "original_content": content,
                    "input_modalities": _infer_input_modalities(content, attachment_service.serialize(saved_attachments)),
                }

                post_user_message = None
                if saved_attachments:

                    async def post_user_message(task, user_message, emit_turn):
                        await emit_turn(
                            "attachment_received",
                            {
                                "count": len(saved_attachments),
                                "files": attachment_service.build_event_files(saved_attachments),
                                "turn_id": task.turn_id,
                            },
                        )
                        attachment_analysis, multimodal_parse, multimodal_failure = await attachment_service.analyze_attachments(
                            content,
                            saved_attachments,
                            session_id=session_id,
                            turn_id=task.turn_id,
                        )
                        _apply_attachment_parse_to_user_message(
                            user_message,
                            content,
                            attachment_service.serialize(saved_attachments),
                            attachment_analysis,
                            multimodal_parse,
                        )
                        _maybe_refresh_session_title(task.session, user_message)
                        failed_attachments = [item for item in saved_attachments if item.analysis_status == "failed"]
                        if failed_attachments:
                            warning_metadata = {
                                "type": "attachment_analysis_warning",
                                "turn_id": task.turn_id,
                                **({"request_id": request_id} if request_id else {}),
                            }
                            if multimodal_failure:
                                warning_metadata.update(multimodal_failure)
                            task.session.messages.append(
                                SessionMessage(
                                    id=uuid4().hex,
                                    role="system",
                                    content=attachment_service.build_failure_warning(saved_attachments),
                                    metadata=warning_metadata,
                                )
                            )
                        runtime.session_store.save(task.session)
                        await emit_turn(
                            "attachment_processed",
                            {
                                "count": len(saved_attachments),
                                "files": attachment_service.build_event_files(saved_attachments),
                                "ok": not failed_attachments,
                                "turn_id": task.turn_id,
                                "warnings": attachment_analysis.get("warnings", []),
                                **(multimodal_failure or {}),
                            },
                        )

                await runtime.handle_message(
                    session_id,
                    content,
                    emit,
                    user_metadata=metadata,
                    turn_approval_mode=approval_mode,
                    request_id=request_id,
                    turn_id=provisional_turn_id,
                    on_turn_created=lambda turn_id: _set_active_run_turn_id(active_runs, session_id, active_run, turn_id),
                    post_user_message=post_user_message,
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
    uploads = [item for item in form.getlist("attachments") if isinstance(item, UploadFile)]
    uploads.extend(item for item in form.getlist("images") if isinstance(item, UploadFile))
    approval_mode = normalize_turn_approval_mode(form.get("approval_mode"))
    return content, uploads, approval_mode


def _apply_attachment_parse_to_user_message(
    user_message: SessionMessage,
    original_content: str,
    attachments: list[dict[str, object]],
    attachment_analysis: dict[str, object],
    multimodal_parse: dict[str, object] | None = None,
) -> None:
    user_message.content = original_content
    user_message.metadata["original_content"] = original_content
    user_message.metadata["input_modalities"] = _infer_input_modalities(original_content, attachments)
    user_message.metadata["attachments"] = attachments
    user_message.metadata["attachment_analysis"] = attachment_analysis
    if multimodal_parse is not None:
        user_message.metadata["multimodal_parse"] = multimodal_parse
    else:
        user_message.metadata.pop("multimodal_parse", None)


def _maybe_refresh_session_title(session, user_message: SessionMessage) -> None:
    if session.title != "未命名会话":
        return
    next_title = build_user_message_title(user_message)
    if next_title:
        session.title = next_title


def _infer_input_modalities(content: str, attachments: list[dict[str, str]]) -> list[str]:
    modalities: list[str] = []
    if content.strip():
        modalities.append("text")
    if attachments:
        kinds = {str(item.get("kind") or "image").strip() or "image" for item in attachments if isinstance(item, dict)}
        modalities.extend(sorted(kinds))
    return modalities


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
