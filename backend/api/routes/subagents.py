from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.subagents.report import aggregate_current_usage_summary


router = APIRouter(prefix="/api/multiagent", tags=["multiagent"])


class CancelRequest(BaseModel):
    reason: str = "user_requested"


class FailureDecisionRequest(BaseModel):
    decision: str
    task_id: str | None = None


@router.get("/runs/{run_id}")
async def get_multiagent_run(run_id: str, request: Request):
    runtime = request.app.state.runtime
    record = runtime.subagent_manager.get_run_record(run_id)
    run = record.run.model_copy(deep=True)
    run.usage_summary = aggregate_current_usage_summary(list(record.tasks.values()))
    return {
        "run": run.model_dump(mode="json"),
        "tasks": [task.model_dump(mode="json") for task in record.tasks.values()],
        "updated_at": record.updated_at,
    }


@router.get("/tasks/{task_id}")
async def get_multiagent_task(task_id: str, request: Request):
    runtime = request.app.state.runtime
    record, task = runtime.subagent_manager.get_task_record(task_id)
    run = record.run.model_copy(deep=True)
    run.usage_summary = aggregate_current_usage_summary(list(record.tasks.values()))
    return {
        "task": task.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "updated_at": record.updated_at,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_multiagent_run(run_id: str, request: Request, payload: CancelRequest | None = None):
    runtime = request.app.state.runtime
    outcome = runtime.subagent_manager.cancel_run(run_id, reason=(payload.reason if payload is not None else "user_requested"))
    run = outcome.run or runtime.subagent_manager.store.get_run(run_id)
    return {
        "accepted": outcome.accepted,
        "message": outcome.message,
        "run_id": run_id,
        "status": run.status,
        "cancel_requested_at": run.cancel_requested_at,
        "cancel_reason": run.cancel_reason,
        "completed_at": run.completed_at,
    }


@router.post("/runs/{run_id}/failure-decision")
async def resolve_multiagent_failure_decision(run_id: str, request: Request, payload: FailureDecisionRequest):
    runtime = request.app.state.runtime
    try:
        outcome = runtime.subagent_manager.resolve_failure_decision(
            run_id,
            decision=payload.decision,
            task_id=payload.task_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "accepted": outcome.accepted,
        "message": outcome.message,
        "run_id": run_id,
        "status": outcome.run.status,
        "decision": payload.decision,
        "tasks": [task.model_dump(mode="json") for task in outcome.tasks],
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_multiagent_task(task_id: str, request: Request, payload: CancelRequest | None = None):
    runtime = request.app.state.runtime
    outcome = runtime.subagent_manager.cancel_task(task_id, reason=(payload.reason if payload is not None else "user_requested"))
    task = outcome.task or runtime.subagent_manager.store.get_task(task_id)
    return {
        "accepted": outcome.accepted,
        "message": outcome.message,
        "task_id": task_id,
        "run_id": task.run_id,
        "status": task.status,
        "cancel_requested_at": task.cancel_requested_at,
        "cancel_reason": task.cancel_reason,
        "completed_at": task.completed_at,
    }


def list_multiagent_runs_payload(records) -> list[dict]:
    return [
        {
            "run": _run_with_live_usage(record).model_dump(mode="json"),
            "task_count": len(record.tasks),
            "updated_at": record.updated_at,
        }
        for record in records
    ]


def _run_with_live_usage(record):
    run = record.run.model_copy(deep=True)
    run.usage_summary = aggregate_current_usage_summary(list(record.tasks.values()))
    return run
