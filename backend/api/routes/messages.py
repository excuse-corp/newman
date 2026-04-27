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
from backend.providers.base import ProviderError
from backend.runtime.message_rendering import build_user_message_title
from backend.runtime.error_codes import resolve_tool_error
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
                metadata = {
                    "attachments": _serialize_attachments(saved_attachments),
                    "approval_mode": approval_mode,
                    "original_content": content,
                    "input_modalities": _infer_input_modalities(content, saved_attachments),
                }

                post_user_message = None
                if saved_attachments:

                    async def post_user_message(task, user_message, emit_turn):
                        await emit_turn(
                            "attachment_received",
                            {
                                "count": len(saved_attachments),
                                "files": [
                                    {"filename": item["filename"], "content_type": item["content_type"]}
                                    for item in saved_attachments
                                ],
                                "turn_id": task.turn_id,
                            },
                        )
                        try:
                            parsed = await runtime.multimodal_analyzer.parse_user_input(
                                content,
                                [Path(item["path"]) for item in saved_attachments],
                                session_id=session_id,
                                turn_id=task.turn_id,
                            )
                        except ProviderError as exc:
                            failure = _build_attachment_analysis_failure(exc, runtime)
                            _mark_attachments_as_failed(saved_attachments, failure["frontend_message"])
                            _apply_multimodal_parse_to_user_message(
                                user_message,
                                content,
                                saved_attachments,
                                _build_failed_multimodal_parse(failure, runtime),
                            )
                            _maybe_refresh_session_title(task.session, user_message)
                            task.session.messages.append(
                                SessionMessage(
                                    id=uuid4().hex,
                                    role="system",
                                    content=_build_attachment_analysis_warning(saved_attachments, failure),
                                    metadata={
                                        "type": "attachment_analysis_warning",
                                        "turn_id": task.turn_id,
                                        **({"request_id": request_id} if request_id else {}),
                                        **failure,
                                    },
                                )
                            )
                            runtime.session_store.save(task.session)
                            await emit_turn(
                                "attachment_processed",
                                {
                                    "count": len(saved_attachments),
                                    "files": _build_attachment_event_files(saved_attachments),
                                    "ok": False,
                                    "turn_id": task.turn_id,
                                    **failure,
                                },
                            )
                            return
                        except Exception as exc:
                            failure = _build_attachment_analysis_failure(exc, runtime)
                            _mark_attachments_as_failed(saved_attachments, failure["frontend_message"])
                            _apply_multimodal_parse_to_user_message(
                                user_message,
                                content,
                                saved_attachments,
                                _build_failed_multimodal_parse(failure, runtime),
                            )
                            _maybe_refresh_session_title(task.session, user_message)
                            task.session.messages.append(
                                SessionMessage(
                                    id=uuid4().hex,
                                    role="system",
                                    content=_build_attachment_analysis_warning(saved_attachments, failure),
                                    metadata={
                                        "type": "attachment_analysis_warning",
                                        "turn_id": task.turn_id,
                                        **({"request_id": request_id} if request_id else {}),
                                        **failure,
                                    },
                                )
                            )
                            runtime.session_store.save(task.session)
                            await emit_turn(
                                "attachment_processed",
                                {
                                    "count": len(saved_attachments),
                                    "files": _build_attachment_event_files(saved_attachments),
                                    "ok": False,
                                    "turn_id": task.turn_id,
                                    **failure,
                                },
                            )
                            return

                        attachment_summaries = parsed.get("attachment_summaries")
                        if not isinstance(attachment_summaries, list):
                            attachment_summaries = []
                        for index, item in enumerate(saved_attachments):
                            summary = ""
                            if index < len(attachment_summaries):
                                summary = str(attachment_summaries[index]).strip()
                            item["summary"] = summary or "未获得可用图片分析结果。"
                            item["analysis_status"] = "completed"
                            item.pop("analysis_error", None)
                        _apply_multimodal_parse_to_user_message(user_message, content, saved_attachments, parsed)
                        _maybe_refresh_session_title(task.session, user_message)
                        runtime.session_store.save(task.session)
                        await emit_turn(
                            "attachment_processed",
                            {
                                "count": len(saved_attachments),
                                "files": _build_attachment_event_files(saved_attachments),
                                "ok": True,
                                "turn_id": task.turn_id,
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
                "attachment_id": uuid4().hex,
                "kind": "image",
                "filename": filename,
                "content_type": upload.content_type or "application/octet-stream",
                "path": str(target),
                "summary": "",
                "analysis_status": "pending",
            }
        )
    return saved


def _serialize_attachments(attachments: list[dict[str, str]]) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    for item in attachments:
        payload = {
            "attachment_id": item["attachment_id"],
            "kind": item.get("kind", "image"),
            "filename": item["filename"],
            "content_type": item["content_type"],
            "path": item["path"],
            "summary": item.get("summary", ""),
        }
        if analysis_status := item.get("analysis_status"):
            payload["analysis_status"] = analysis_status
        if analysis_error := item.get("analysis_error"):
            payload["analysis_error"] = analysis_error
        serialized.append(payload)
    return serialized


def _apply_multimodal_parse_to_user_message(
    user_message: SessionMessage,
    original_content: str,
    attachments: list[dict[str, str]],
    multimodal_parse: dict[str, object],
) -> None:
    user_message.content = original_content
    user_message.metadata["original_content"] = original_content
    user_message.metadata["input_modalities"] = _infer_input_modalities(original_content, attachments)
    user_message.metadata["attachments"] = _serialize_attachments(attachments)
    user_message.metadata["multimodal_parse"] = multimodal_parse


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


def _build_attachment_event_files(attachments: list[dict[str, str]]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for item in attachments:
        payload = {
            "filename": item["filename"],
            "summary": item.get("summary", ""),
        }
        if analysis_status := item.get("analysis_status"):
            payload["analysis_status"] = analysis_status
        if analysis_error := item.get("analysis_error"):
            payload["analysis_error"] = analysis_error
        files.append(payload)
    return files


def _mark_attachments_as_failed(attachments: list[dict[str, str]], frontend_message: str) -> None:
    failure_summary = f"图片预解析失败：{frontend_message}"
    for item in attachments:
        item["summary"] = failure_summary
        item["analysis_status"] = "failed"
        item["analysis_error"] = frontend_message


def _build_attachment_analysis_failure(exc: Exception, runtime) -> dict[str, str]:
    if isinstance(exc, ProviderError):
        descriptor = resolve_tool_error(exc.kind, success=False)
        detail = exc.message
        category = exc.kind
        provider = exc.provider
        status_code = exc.status_code
    else:
        descriptor = resolve_tool_error("runtime_exception", success=False)
        detail = str(exc) or exc.__class__.__name__
        category = "runtime_exception"
        provider = "multimodal_analyzer"
        status_code = None

    frontend_message = "图片预解析超时，已跳过图片内容解析" if category == "timeout_error" else "图片预解析失败，已跳过图片内容解析"
    timeout_seconds = getattr(getattr(runtime, "settings", None), "models", None)
    timeout_value = getattr(getattr(timeout_seconds, "multimodal", None), "timeout", None)
    summary = detail
    if isinstance(timeout_value, int) and category == "timeout_error":
        summary = f"{detail} (multimodal timeout={timeout_value}s)"

    return {
        "category": category,
        "error_code": descriptor.code,
        "severity": descriptor.severity,
        "risk_level": descriptor.risk_level,
        "recovery_class": "recoverable",
        "frontend_message": frontend_message,
        "recommended_next_step": "Continue this round without image context, then inspect the multimodal provider configuration or retry the upload.",
        "summary": summary,
        "provider": provider,
        "status_code": "" if status_code is None else str(status_code),
    }


def _build_failed_multimodal_parse(failure: dict[str, str], runtime) -> dict[str, object]:
    multimodal_config = getattr(getattr(getattr(runtime, "settings", None), "models", None), "multimodal", None)
    parser_provider = getattr(multimodal_config, "type", "multimodal_analyzer")
    parser_model = getattr(multimodal_config, "model", "")
    return {
        "schema_version": "v1",
        "status": "failed",
        "parser_provider": parser_provider,
        "parser_model": parser_model,
        "normalized_user_input": "",
        "task_intent": "",
        "key_facts": [],
        "ocr_text": [],
        "uncertainties": [failure["frontend_message"]],
        "attachment_summaries": [],
        "frontend_message": failure["frontend_message"],
        "error_code": failure["error_code"],
        "summary": failure["summary"],
        "category": failure["category"],
    }


def _build_attachment_analysis_warning(
    attachments: list[dict[str, str]],
    failure: dict[str, str],
) -> str:
    lines = [
        "## Uploaded Images Warning",
        f"图片预解析失败，当前回合不要把这些图片当作已成功读取的上下文。原因：{failure['summary']}",
        "如果必须依赖图片内容，请提示用户稍后重试，或先检查多模态模型/网络配置。",
    ]
    for item in attachments:
        lines.append(f"- {item['filename']}: {item.get('summary', '').strip()}")
    return "\n".join(lines)


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
