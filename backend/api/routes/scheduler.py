from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.scheduler.cron_parser import next_run
from backend.scheduler.models import ScheduledTask, TaskAction


router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class CreateTaskRequest(BaseModel):
    name: str = Field(..., min_length=1)
    cron: str = Field(..., min_length=1)
    action: TaskAction
    timezone: str = Field(default="UTC", min_length=1)
    description: str | None = None
    enabled: bool = True
    max_retries: int = Field(default=5, ge=0, le=5)
    source: Literal["chat", "automation_page", "api"] = "api"


class UpdateTaskRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    cron: str | None = Field(default=None, min_length=1)
    action: TaskAction | None = None
    timezone: str | None = Field(default=None, min_length=1)
    description: str | None = None
    enabled: bool | None = None
    max_retries: int | None = Field(default=None, ge=0, le=5)
    source: Literal["chat", "automation_page", "api"] | None = None


@router.get("/tasks")
async def list_tasks(request: Request):
    runtime = request.app.state.runtime
    request.app.state.scheduler.refresh_schedule()
    return {"tasks": [_serialize_task(item) for item in runtime.scheduler_store.list_tasks()]}


@router.get("/tasks/{task_id}/runs")
async def list_task_runs(task_id: str, request: Request, limit: int = 20):
    request.app.state.runtime.scheduler_store.get(task_id)
    runs = request.app.state.scheduler.run_store.list_runs(task_id=task_id, limit=max(1, min(limit, 100)))
    return {"runs": [item.model_dump(mode="json") for item in runs]}


@router.get("/alerts")
async def list_scheduler_alerts(request: Request):
    alerts = request.app.state.scheduler.alert_store.list_alerts()
    return {"alerts": [item.model_dump(mode="json") for item in alerts]}


@router.post("/tasks")
async def create_task(payload: CreateTaskRequest, request: Request):
    runtime = request.app.state.runtime
    action = _normalize_action(payload.action)
    _validate_task_input(runtime, cron=payload.cron, timezone_name=payload.timezone, action=action)
    task = ScheduledTask(
        task_id=uuid4().hex,
        name=payload.name,
        cron=payload.cron,
        action=action,
        timezone=payload.timezone,
        description=payload.description,
        enabled=payload.enabled,
        max_retries=payload.max_retries,
        source=payload.source,
        next_run_at=next_run(payload.cron, datetime.now(timezone.utc), payload.timezone).isoformat(),
    )
    runtime.scheduler_store.upsert(task)
    request.app.state.scheduler.refresh_schedule()
    return {"task": _serialize_task(task)}


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, payload: UpdateTaskRequest, request: Request):
    runtime = request.app.state.runtime
    task = runtime.scheduler_store.get(task_id)
    updates = payload.model_dump(exclude_unset=True)
    if "action" in updates and updates["action"] is not None:
        updates["action"] = _normalize_action(payload.action)
    merged = task.model_copy(update=updates)
    _validate_task_input(runtime, cron=merged.cron, timezone_name=merged.timezone, action=merged.action)
    merged.next_run_at = next_run(merged.cron, datetime.now(timezone.utc), merged.timezone).isoformat()
    runtime.scheduler_store.upsert(merged)
    request.app.state.scheduler.refresh_schedule()
    return {"task": _serialize_task(merged)}


@router.post("/tasks/{task_id}/enable")
async def enable_task(task_id: str, request: Request):
    runtime = request.app.state.runtime
    task = runtime.scheduler_store.get(task_id)
    task.enabled = True
    runtime.scheduler_store.upsert(task)
    request.app.state.scheduler.refresh_schedule()
    return {"task": _serialize_task(task)}


@router.post("/tasks/{task_id}/disable")
async def disable_task(task_id: str, request: Request):
    runtime = request.app.state.runtime
    task = runtime.scheduler_store.get(task_id)
    task.enabled = False
    runtime.scheduler_store.upsert(task)
    request.app.state.scheduler.refresh_schedule()
    return {"task": _serialize_task(task)}


@router.post("/tasks/{task_id}/run")
async def run_task_now(task_id: str, request: Request):
    task = await request.app.state.scheduler.run_now(task_id)
    return {"task": _serialize_task(task)}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    runtime = request.app.state.runtime
    runtime.scheduler_store.delete(task_id)
    request.app.state.scheduler.refresh_schedule()
    return {"deleted": True, "task_id": task_id}


def _validate_task_input(runtime, *, cron: str, timezone_name: str, action: TaskAction) -> None:
    ZoneInfo(timezone_name)
    next_run(cron, datetime.now(timezone.utc), timezone_name)
    if action.type == "session_message":
        if not action.session_id:
            raise ValueError("session_message 任务必须提供 session_id")
        runtime.session_store.get(action.session_id)


def _normalize_action(action: TaskAction | None) -> TaskAction:
    if action is None:
        raise ValueError("action 不能为空")
    if action.type == "background_task":
        return action.model_copy(update={"session_id": None})
    return action


def _serialize_task(task: ScheduledTask) -> dict[str, object]:
    payload = task.model_dump(mode="json")
    payload["human_schedule"] = f"{task.cron} [{task.timezone}]"
    return payload
