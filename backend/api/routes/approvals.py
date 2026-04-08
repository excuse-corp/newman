from __future__ import annotations

from time import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


router = APIRouter(prefix="/api/sessions", tags=["approvals"])


class ApprovalActionRequest(BaseModel):
    approval_request_id: str


@router.get("/{session_id}/pending-approval")
async def get_pending_approval(session_id: str, request: Request):
    runtime = request.app.state.runtime
    approval = runtime.approvals.find_for_session(session_id)
    if approval is None:
        return {"session_id": session_id, "pending": None}
    timeout_seconds = runtime.settings.approval.timeout_seconds
    elapsed = max(0, int(time() - approval.created_at))
    remaining = max(0, timeout_seconds - elapsed)
    return {
        "session_id": session_id,
        "pending": {
            "approval_request_id": approval.approval_request_id,
            "tool": approval.tool_name,
            "arguments": approval.arguments,
            "reason": approval.reason,
            "timeout_seconds": timeout_seconds,
            "remaining_seconds": remaining,
        },
    }


@router.post("/{session_id}/approve")
async def approve_tool(session_id: str, payload: ApprovalActionRequest, request: Request):
    runtime = request.app.state.runtime
    approval = runtime.approvals.get(payload.approval_request_id)
    if approval.session_id != session_id:
        raise HTTPException(status_code=409, detail="approval_request_id 与 session_id 不匹配")
    approval = runtime.approvals.resolve(payload.approval_request_id, True)
    return {"session_id": session_id, "approval_request_id": approval.approval_request_id, "approved": True}


@router.post("/{session_id}/reject")
async def reject_tool(session_id: str, payload: ApprovalActionRequest, request: Request):
    runtime = request.app.state.runtime
    approval = runtime.approvals.get(payload.approval_request_id)
    if approval.session_id != session_id:
        raise HTTPException(status_code=409, detail="approval_request_id 与 session_id 不匹配")
    approval = runtime.approvals.resolve(payload.approval_request_id, False)
    return {"session_id": session_id, "approval_request_id": approval.approval_request_id, "approved": False}
