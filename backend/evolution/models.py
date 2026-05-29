from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.sessions.models import utc_now


EvolutionTrigger = Literal["new_session_created", "turn_interval", "manual"]
EvolutionStatus = Literal["running", "applied", "skipped", "failed", "partial", "rolled_back"]
EvolutionChangeKind = Literal["memory_update", "skill_update"]
EvolutionFileAction = Literal["append", "create", "update", "delete"]


class EvolutionChange(BaseModel):
    change_id: str
    kind: EvolutionChangeKind
    action: EvolutionFileAction
    target_path: str
    summary: str = ""
    reason: str = ""
    diff: str = ""
    before_exists: bool = False
    snapshot_path: str | None = None
    validation_status: Literal["not_run", "passed", "failed", "rolled_back"] = "not_run"
    validation_errors: list[str] = Field(default_factory=list)


class EvolutionRunRecord(BaseModel):
    run_id: str
    trigger: EvolutionTrigger
    source_session_id: str | None = None
    status: EvolutionStatus = "running"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    summary: str = ""
    message_range: list[int] = Field(default_factory=list)
    user_turn_count: int = 0
    changes: list[EvolutionChange] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

