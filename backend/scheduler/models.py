from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskAction(BaseModel):
    type: Literal["session_message", "background_task"] = "background_task"
    prompt: str
    session_id: str | None = None


TaskStatus = Literal["pending", "running", "completed", "failed", "disabled"]
TaskOutcome = Literal[
    "success",
    "failed",
    "skipped_conflict",
    "skipped_missing_session",
    "approval_blocked",
]


class ScheduledTask(BaseModel):
    task_id: str
    name: str
    cron: str
    action: TaskAction
    timezone: str = "UTC"
    description: str | None = None
    enabled: bool = True
    max_retries: int = 5
    status: TaskStatus = "pending"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_run_session_id: str | None = None
    last_run_turn_id: str | None = None
    last_success_at: str | None = None
    failure_count: int = 0
    last_run_outcome: TaskOutcome | None = None
    last_skip_reason: str | None = None
    source: Literal["chat", "automation_page", "api"] = "api"
    last_error: str = ""
    run_count: int = 0


class SchedulerRunRecord(BaseModel):
    run_id: str
    task_id: str
    trigger_kind: Literal["cron", "manual_run"]
    outcome: TaskOutcome
    scheduled_for: str
    started_at: str = Field(default_factory=utc_now)
    finished_at: str = Field(default_factory=utc_now)
    session_id: str | None = None
    turn_id: str | None = None
    message: str = ""
