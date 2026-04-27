from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import uuid4

from backend.api.sse.event_emitter import format_sse
from backend.memory.compressor import (
    build_context_usage_snapshot,
    build_checkpoint_metadata,
    split_session_messages,
    summarize_messages,
)
from backend.runtime.collaboration_mode import (
    build_collaboration_mode_payload,
    build_plan_draft_payload,
    get_approved_plan,
    get_collaboration_mode,
    get_plan_draft,
)
from backend.sessions.models import SessionMessage, SessionSummary


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str | None = None


class UpdateSessionRequest(BaseModel):
    title: str


class UpdateCollaborationModeRequest(BaseModel):
    mode: Literal["default", "plan"]


class UpdatePlanDraftRequest(BaseModel):
    markdown: str


@router.post("")
async def create_session(payload: CreateSessionRequest, request: Request):
    runtime = request.app.state.runtime
    session, created = runtime.thread_manager.create_or_restore(title=payload.title)
    memory_extraction = (
        runtime.schedule_previous_session_extraction(session.session_id)
        if created
        else {
            "scheduled": False,
            "trigger": "new_session_created",
            "source_session_id": None,
            "reason": "session_restored",
        }
    )
    return {
        "session_id": session.session_id,
        "title": session.title,
        "created": created,
        "memory_extraction": memory_extraction,
    }


@router.post("/stream")
async def create_session_stream(payload: CreateSessionRequest, request: Request):
    runtime = request.app.state.runtime
    request_id = getattr(request.state, "request_id", None)

    async def event_stream():
        session, created = runtime.thread_manager.create_or_restore(title=payload.title)
        memory_extraction = (
            runtime.schedule_previous_session_extraction(session.session_id)
            if created
            else {
                "scheduled": False,
                "trigger": "new_session_created",
                "source_session_id": None,
                "reason": "session_restored",
            }
        )
        data = {
            "session_id": session.session_id,
            "title": session.title,
            "created": created,
            "memory_extraction": memory_extraction,
        }
        yield format_sse("session_created", data, request_id=request_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("", response_model=list[SessionSummary])
async def list_sessions(request: Request):
    runtime = request.app.state.runtime
    return runtime.thread_manager.list_sessions()


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    checkpoint = runtime.checkpoints.get(session_id)
    plan_draft = get_plan_draft(session)
    approved_plan = get_approved_plan(session)
    return {
        "session": session,
        "plan": session.metadata.get("plan"),
        "collaboration_mode": get_collaboration_mode(session).model_dump(mode="json"),
        "plan_draft": plan_draft.model_dump(mode="json") if plan_draft else None,
        "approved_plan": approved_plan.model_dump(mode="json") if approved_plan else None,
        "checkpoint": checkpoint,
        "context_usage": _build_context_usage(runtime, session, checkpoint),
    }


@router.get("/{session_id}/usage")
async def get_session_usage(session_id: str, request: Request, limit: int = 100):
    if limit <= 0:
        raise ValueError("limit 必须大于 0")

    runtime = request.app.state.runtime
    runtime.session_store.get(session_id)
    usage_store = getattr(runtime, "usage_store", None)
    if usage_store is None:
        return {"session_id": session_id, "records": [], "available": False}

    try:
        records = usage_store.list_session_records(session_id, limit=min(limit, 500))
    except Exception as exc:
        return {
            "session_id": session_id,
            "records": [],
            "available": False,
            "error": str(exc),
        }
    return {
        "session_id": session_id,
        "records": [record.model_dump(mode="json") for record in records],
        "available": True,
    }


@router.get("/{session_id}/events")
async def get_session_events(session_id: str, request: Request, limit: int = 200):
    if limit <= 0:
        raise ValueError("limit 必须大于 0")

    audit_path = request.app.state.settings.paths.audit_dir / f"{session_id}.log"
    if not audit_path.exists():
        return {"session_id": session_id, "events": []}

    raw_lines = audit_path.read_text(encoding="utf-8").splitlines()
    payloads: list[dict] = []
    for line in raw_lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if "event" not in payload or "data" not in payload:
            continue
        payload.setdefault("ts", 0)
        payloads.append(payload)

    if limit:
        payloads = payloads[-limit:]
    return {"session_id": session_id, "events": payloads}


@router.post("/{session_id}/compress")
async def compress_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    checkpoint = runtime.checkpoints.get(session_id)
    preserved = runtime.settings.runtime.context_compaction_preserve_recent
    summary_result = await summarize_messages(
        runtime.provider,
        runtime.settings.provider,
        runtime.settings.provider.type,
        session,
        preserve_recent=preserved,
        checkpoint=checkpoint,
        usage_store=getattr(runtime, "usage_store", None),
        request_kind="manual_context_compaction",
    )
    if not summary_result:
        return {"compressed": False, "reason": "nothing_to_compress"}
    _, preserved_messages = split_session_messages(session, preserve_recent=preserved)
    original_count = len(session.messages)
    session.messages = preserved_messages
    session.metadata["checkpoint_active"] = True
    runtime.session_store.save(session)
    checkpoint = runtime.checkpoints.save(
        session_id,
        summary_result.summary,
        [0, max(0, original_count - len(preserved_messages))],
        metadata=build_checkpoint_metadata(
            summary_result,
            preserve_recent=preserved,
            compression_level="manual",
            original_message_count=original_count,
        ),
    )
    session.metadata["checkpoint_restore_hint"] = checkpoint.checkpoint_id
    runtime.session_store.save(session)
    return {"compressed": True, "checkpoint": checkpoint, "session": session}


@router.post("/{session_id}/restore-checkpoint")
async def restore_checkpoint(session_id: str, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    checkpoint = runtime.checkpoints.get(session_id)
    if checkpoint is None:
        return {"restored": False, "reason": "checkpoint_not_found"}

    restored_message = SessionMessage(
        id=uuid4().hex,
        role="system",
        content=f"## Restored From Checkpoint\n{checkpoint.summary}",
        metadata={"type": "checkpoint_restore", "checkpoint_id": checkpoint.checkpoint_id},
    )
    session.messages = [
        message
        for message in session.messages
        if not (message.role == "system" and message.metadata.get("type") == "checkpoint_restore")
    ]
    session.messages.insert(0, restored_message)
    session.metadata["checkpoint_active"] = False
    session.metadata["checkpoint_restore_hint"] = checkpoint.checkpoint_id
    runtime.session_store.save(session)
    return {
        "restored": True,
        "checkpoint": checkpoint,
        "session": session,
    }


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    runtime.thread_manager.delete(session_id)
    return {"deleted": True, "session_id": session_id}


@router.patch("/{session_id}")
async def update_session(session_id: str, payload: UpdateSessionRequest, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.rename(session_id, payload.title)
    return {
        "updated": True,
        "session_id": session.session_id,
        "title": session.title,
        "updated_at": session.updated_at,
    }


@router.patch("/{session_id}/collaboration-mode")
async def update_collaboration_mode(session_id: str, payload: UpdateCollaborationModeRequest, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    mode_payload = build_collaboration_mode_payload(payload.mode, source="manual")
    session.metadata["collaboration_mode"] = mode_payload
    runtime.session_store.save(session)
    return {
        "updated": True,
        "session_id": session_id,
        "collaboration_mode": mode_payload,
    }


@router.get("/{session_id}/plan-draft")
async def get_session_plan_draft(session_id: str, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    draft = get_plan_draft(session)
    return {
        "session_id": session_id,
        "plan_draft": draft.model_dump(mode="json") if draft else None,
    }


@router.put("/{session_id}/plan-draft")
async def update_session_plan_draft(session_id: str, payload: UpdatePlanDraftRequest, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    markdown = payload.markdown.strip()
    if not markdown:
        session.metadata.pop("plan_draft", None)
        runtime.session_store.save(session)
        return {
            "updated": True,
            "session_id": session_id,
            "plan_draft": None,
        }

    draft_payload = build_plan_draft_payload(markdown, status="draft")
    session.metadata["plan_draft"] = draft_payload
    runtime.session_store.save(session)
    return {
        "updated": True,
        "session_id": session_id,
        "plan_draft": draft_payload,
    }


def _build_context_usage(runtime, session, checkpoint) -> dict[str, object]:
    usage_store = getattr(runtime, "usage_store", None)
    latest_record = None
    if usage_store is not None:
        try:
            latest_record = usage_store.latest_context_record(session.session_id)
        except Exception:
            latest_record = None
    assembled_messages = _build_session_context_messages(runtime, session, checkpoint)
    return build_context_usage_snapshot(
        runtime.provider,
        runtime.settings.provider,
        runtime.settings.runtime,
        assembled_messages,
        session,
        checkpoint,
        latest_record=latest_record,
    ).to_dict()


def _build_session_context_messages(runtime, session, checkpoint) -> list[dict[str, object]]:
    prompt_assembler = getattr(runtime, "prompt_assembler", None)
    if prompt_assembler is not None and hasattr(runtime, "_tools_overview"):
        return prompt_assembler.assemble(
            session,
            runtime._tools_overview(),
            checkpoint,
        )
    return _build_session_history_messages(session, checkpoint)


def _build_session_history_messages(session, checkpoint) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    has_restored_checkpoint = any(
        item.role == "system" and item.metadata.get("type") == "checkpoint_restore"
        for item in session.messages
    )
    if checkpoint and not has_restored_checkpoint:
        messages.append({"role": "system", "content": f"## Checkpoint Summary\n{checkpoint.summary}"})
    for item in session.messages:
        messages.append({"role": item.role, "content": item.content})
    return messages
