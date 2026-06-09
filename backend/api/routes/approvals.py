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
            "turn_id": approval.turn_id,
            "tool": approval.tool_name,
            "arguments": approval.arguments,
            "reason": approval.reason,
            "timeout_seconds": timeout_seconds,
            "remaining_seconds": remaining,
        },
    }


@router.get("/{session_id}/multiagent-approvals")
async def get_pending_multiagent_approvals(session_id: str, request: Request):
    runtime = request.app.state.runtime
    timeout_seconds = runtime.settings.approval.timeout_seconds
    task_map = _multiagent_child_session_task_map(runtime, session_id)
    approvals = runtime.approvals.list_for_sessions(task_map.keys())
    return {
        "session_id": session_id,
        "pending": [
            _serialize_multiagent_approval(approval, task_map[approval.session_id], timeout_seconds)
            for approval in approvals
            if approval.session_id in task_map
        ],
    }


@router.post("/{session_id}/approve")
async def approve_tool(session_id: str, payload: ApprovalActionRequest, request: Request):
    runtime = request.app.state.runtime
    resolved = runtime.approvals.get_resolved(payload.approval_request_id)
    approval = resolved.request if resolved is not None else runtime.approvals.get(payload.approval_request_id)
    if approval.session_id != session_id:
        raise HTTPException(status_code=409, detail="approval_request_id 与 session_id 不匹配")
    if resolved is not None:
        return {
            "session_id": session_id,
            "approval_request_id": approval.approval_request_id,
            "approved": resolved.approved,
            "already_resolved": True,
        }
    approval = runtime.approvals.resolve(payload.approval_request_id, True)
    return {"session_id": session_id, "approval_request_id": approval.approval_request_id, "approved": True, "already_resolved": False}


@router.post("/{session_id}/reject")
async def reject_tool(session_id: str, payload: ApprovalActionRequest, request: Request):
    runtime = request.app.state.runtime
    resolved = runtime.approvals.get_resolved(payload.approval_request_id)
    approval = resolved.request if resolved is not None else runtime.approvals.get(payload.approval_request_id)
    if approval.session_id != session_id:
        raise HTTPException(status_code=409, detail="approval_request_id 与 session_id 不匹配")
    if resolved is not None:
        return {
            "session_id": session_id,
            "approval_request_id": approval.approval_request_id,
            "approved": resolved.approved,
            "already_resolved": True,
        }
    approval = runtime.approvals.resolve(payload.approval_request_id, False)
    return {"session_id": session_id, "approval_request_id": approval.approval_request_id, "approved": False, "already_resolved": False}


@router.post("/{session_id}/multiagent-approvals/{approval_request_id}/approve")
async def approve_multiagent_tool(session_id: str, approval_request_id: str, request: Request):
    runtime = request.app.state.runtime
    resolved = runtime.approvals.get_resolved(approval_request_id)
    approval = resolved.request if resolved is not None else runtime.approvals.get(approval_request_id)
    task = _require_multiagent_task(runtime, session_id, approval.session_id, approval_request_id)
    if resolved is not None:
        return _multiagent_resolution_payload(session_id, approval, task, approved=resolved.approved, already_resolved=True)
    approval = runtime.approvals.resolve(approval_request_id, True)
    return _multiagent_resolution_payload(session_id, approval, task, approved=True, already_resolved=False)


@router.post("/{session_id}/multiagent-approvals/{approval_request_id}/reject")
async def reject_multiagent_tool(session_id: str, approval_request_id: str, request: Request):
    runtime = request.app.state.runtime
    resolved = runtime.approvals.get_resolved(approval_request_id)
    approval = resolved.request if resolved is not None else runtime.approvals.get(approval_request_id)
    task = _require_multiagent_task(runtime, session_id, approval.session_id, approval_request_id)
    if resolved is not None:
        return _multiagent_resolution_payload(session_id, approval, task, approved=resolved.approved, already_resolved=True)
    approval = runtime.approvals.resolve(approval_request_id, False)
    return _multiagent_resolution_payload(session_id, approval, task, approved=False, already_resolved=False)


def _multiagent_resolution_payload(
    session_id: str,
    approval,
    task: dict[str, str],
    *,
    approved: bool,
    already_resolved: bool,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "approval_request_id": approval.approval_request_id,
        "approved": approved,
        "already_resolved": already_resolved,
        "run_id": task["run_id"],
        "task_id": task["task_id"],
        "child_session_id": task["child_session_id"],
    }


def _multiagent_child_session_task_map(runtime, parent_session_id: str) -> dict[str, dict[str, str]]:
    manager = getattr(runtime, "subagent_manager", None)
    if manager is None:
        return {}

    task_map: dict[str, dict[str, str]] = {}
    for record in manager.list_runs(parent_session_id=parent_session_id):
        for task in record.tasks.values():
            task_map[task.child_session_id] = {
                "run_id": task.run_id,
                "task_id": task.task_id,
                "task_name": task.name,
                "child_session_id": task.child_session_id,
            }
    return task_map


def _serialize_multiagent_approval(approval, task: dict[str, str], timeout_seconds: int) -> dict[str, object]:
    elapsed = max(0, int(time() - approval.created_at))
    remaining = max(0, timeout_seconds - elapsed)
    return {
        "approval_request_id": approval.approval_request_id,
        "run_id": task["run_id"],
        "task_id": task["task_id"],
        "task_name": task["task_name"],
        "child_session_id": task["child_session_id"],
        "turn_id": approval.turn_id,
        "tool": approval.tool_name,
        "arguments": approval.arguments,
        "reason": approval.reason,
        "timeout_seconds": timeout_seconds,
        "remaining_seconds": remaining,
    }


def _require_multiagent_task(runtime, parent_session_id: str, child_session_id: str, approval_request_id: str) -> dict[str, str]:
    task_map = _multiagent_child_session_task_map(runtime, parent_session_id)
    task = task_map.get(child_session_id)
    if task is None:
        raise HTTPException(
            status_code=409,
            detail=f"approval_request_id 不属于 parent session: {approval_request_id}",
        )
    return task
