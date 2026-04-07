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


class ScheduledTask(BaseModel):
    task_id: str
    name: str
    cron: str
    action: TaskAction
    enabled: bool = True
    max_retries: int = 5
    status: Literal["pending", "running", "completed", "failed", "disabled"] = "pending"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_error: str = ""
    run_count: int = 0
