from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import uuid4

from backend.api.sse.event_emitter import format_sse
from backend.memory.compressor import summarize_messages
from backend.sessions.models import SessionMessage, SessionSummary


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    title: str | None = None


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
    return {
        "session": session,
        "plan": session.metadata.get("plan"),
        "checkpoint": runtime.checkpoints.get(session_id),
    }


@router.post("/{session_id}/compress")
async def compress_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    session = runtime.session_store.get(session_id)
    checkpoint = runtime.checkpoints.get(session_id)
    summary = summarize_messages(session, checkpoint=checkpoint)
    if not summary:
        return {"compressed": False, "reason": "nothing_to_compress"}
    preserved = 4
    checkpoint = runtime.checkpoints.save(
        session_id,
        summary,
        [0, max(0, len(session.messages) - preserved)],
        metadata={
            "preserve_recent": preserved,
            "compression_level": "manual",
            "original_message_count": len(session.messages),
        },
    )
    return {"compressed": True, "checkpoint": checkpoint}


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
