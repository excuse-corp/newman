from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceLimits:
    cpu_limit: float
    memory_limit: str
    timeout_seconds: int
    output_limit_bytes: int
