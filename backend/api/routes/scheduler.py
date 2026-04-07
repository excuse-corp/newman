from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.scheduler.cron_parser import next_run
from backend.scheduler.models import ScheduledTask, TaskAction


router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


class CreateTaskRequest(BaseModel):
    name: str = Field(..., min_length=1)
    cron: str = Field(..., min_length=1)
    action: TaskAction
    enabled: bool = True
    max_retries: int = Field(default=5, ge=0, le=5)


@router.get("/tasks")
async def list_tasks(request: Request):
    runtime = request.app.state.runtime
    request.app.state.scheduler.refresh_schedule()
    return {"tasks": [item.model_dump(mode="json") for item in runtime.scheduler_store.list_tasks()]}


@router.post("/tasks")
async def create_task(payload: CreateTaskRequest, request: Request):
    runtime = request.app.state.runtime
    task = ScheduledTask(
        task_id=uuid4().hex,
        name=payload.name,
        cron=payload.cron,
        action=payload.action,
        enabled=payload.enabled,
        max_retries=payload.max_retries,
        next_run_at=next_run(payload.cron, datetime.now(timezone.utc)).isoformat(),
    )
    runtime.scheduler_store.upsert(task)
    request.app.state.scheduler.refresh_schedule()
    return {"task": task.model_dump(mode="json")}


@router.post("/tasks/{task_id}/enable")
async def enable_task(task_id: str, request: Request):
    runtime = request.app.state.runtime
    task = runtime.scheduler_store.get(task_id)
    task.enabled = True
    runtime.scheduler_store.upsert(task)
    request.app.state.scheduler.refresh_schedule()
    return {"task": task.model_dump(mode="json")}


@router.post("/tasks/{task_id}/disable")
async def disable_task(task_id: str, request: Request):
    runtime = request.app.state.runtime
    task = runtime.scheduler_store.get(task_id)
    task.enabled = False
    runtime.scheduler_store.upsert(task)
    request.app.state.scheduler.refresh_schedule()
    return {"task": task.model_dump(mode="json")}


@router.post("/tasks/{task_id}/run")
async def run_task_now(task_id: str, request: Request):
    task = await request.app.state.scheduler.run_now(task_id)
    return {"task": task.model_dump(mode="json")}
