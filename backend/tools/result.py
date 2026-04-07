from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolExecutionResult:
    success: bool
    tool: str
    action: str
    category: str = "success"
    error_code: str = ""
    severity: str = "info"
    risk_level: str = "low"
    recovery_class: str = "none"
    exit_code: int | None = None
    summary: str = ""
    stdout: str = ""
    stderr: str = ""
    frontend_message: str = ""
    recommended_next_step: str = ""
    duration_ms: int = 0
    retryable: bool = False
    attempt_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
