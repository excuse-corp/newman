from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.sessions.models import utc_now


class ModelUsageRecord(BaseModel):
    request_id: str
    session_id: str | None = None
    turn_id: str | None = None
    request_kind: str
    counts_toward_context_window: bool = False
    streaming: bool = False
    provider_type: str
    model: str
    context_window: int | None = None
    effective_context_window: int | None = None
    usage_available: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    created_at: str = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
