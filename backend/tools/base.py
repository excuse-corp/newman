from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from backend.tools.result import ToolExecutionResult


@dataclass
class ToolMeta:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: Literal["low", "medium", "high", "critical"]
    requires_approval: bool
    timeout_seconds: int
    allowed_paths: list[str] | None = None
    allowed_domains: list[str] | None = None


class BaseTool(ABC):
    meta: ToolMeta

    @abstractmethod
    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        raise NotImplementedError

    def to_provider_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.meta.name,
                "description": self.meta.description,
                "parameters": self.meta.input_schema,
            },
        }
