from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class MCPToolSpec(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"


class MCPServerConfig(BaseModel):
    name: str
    transport: Literal["inline", "http_json"] = "inline"
    url: str | None = None
    enabled: bool = True
    requires_approval: bool = False
    timeout_seconds: int = 20
    headers: dict[str, str] = Field(default_factory=dict)
    tools: list[MCPToolSpec] = Field(default_factory=list)


class MCPServerStatus(BaseModel):
    name: str
    transport: str
    enabled: bool
    tool_count: int
    status: str
    detail: str = ""
