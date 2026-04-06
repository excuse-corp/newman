from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionMessage(BaseModel):
    id: str
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    created_at: str = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionRecord(BaseModel):
    session_id: str
    title: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    messages: list[SessionMessage] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    step: str = Field(..., min_length=1)
    status: Literal["pending", "in_progress", "completed"]


class SessionPlan(BaseModel):
    explanation: str | None = None
    steps: list[PlanStep] = Field(..., min_length=1)
    updated_at: str = Field(default_factory=utc_now)
    current_step: str | None = None
    progress: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_progress(self) -> "SessionPlan":
        in_progress = [step for step in self.steps if step.status == "in_progress"]
        if len(in_progress) > 1:
            raise ValueError("同一时间只能有一个 in_progress 步骤")
        counts = {
            "total": len(self.steps),
            "completed": sum(1 for step in self.steps if step.status == "completed"),
            "in_progress": len(in_progress),
            "pending": sum(1 for step in self.steps if step.status == "pending"),
        }
        self.current_step = in_progress[0].step if in_progress else None
        self.progress = counts
        return self


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class CheckpointRecord(BaseModel):
    session_id: str
    checkpoint_id: str
    created_at: str = Field(default_factory=utc_now)
    turn_range: list[int] = Field(default_factory=list)
    summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)
