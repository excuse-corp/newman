from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel


router = APIRouter(prefix="/api/sessions", tags=["approvals"])


class ApprovalActionRequest(BaseModel):
    approval_request_id: str


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
