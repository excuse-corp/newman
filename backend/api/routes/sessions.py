from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.memory.compressor import summarize_messages
from backend.sessions.models import SessionSummary


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
    summary = summarize_messages(session)
    if not summary:
        return {"compressed": False, "reason": "nothing_to_compress"}
    checkpoint = runtime.checkpoints.save(session_id, summary, [0, max(0, len(session.messages) - 4)])
    return {"compressed": True, "checkpoint": checkpoint}


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request):
    runtime = request.app.state.runtime
    runtime.thread_manager.delete(session_id)
    return {"deleted": True, "session_id": session_id}
