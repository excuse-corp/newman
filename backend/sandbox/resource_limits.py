from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResourceLimits:
    timeout_seconds: int
    output_limit_bytes: int
