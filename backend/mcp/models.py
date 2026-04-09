from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class MCPToolSpec(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"


class MCPResourceSpec(BaseModel):
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None
    content: str = ""


class MCPResourceRecord(MCPResourceSpec):
    server_name: str
    transport: str


class MCPServerConfig(BaseModel):
    name: str
    transport: Literal["inline", "http_json", "http_sse", "stdio"] = "inline"
    url: str | None = None
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    requires_approval: bool = False
    timeout_seconds: int = 20
    headers: dict[str, str] = Field(default_factory=dict)
    tools: list[MCPToolSpec] = Field(default_factory=list)
    resources: list[MCPResourceSpec] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_command(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        command = payload.get("command")
        if isinstance(command, str):
            payload["command"] = [command]
        return payload

    @model_validator(mode="after")
    def validate_transport_requirements(self) -> "MCPServerConfig":
        if self.transport in {"http_json", "http_sse"} and not self.url:
            raise ValueError(f"MCP server {self.name} missing url")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP server {self.name} missing command")
        return self

    def identity_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class MCPServerStatus(BaseModel):
    name: str
    transport: str
    enabled: bool
    tool_count: int
    resource_count: int = 0
    status: str
    detail: str = ""
    last_checked_at: str = Field(default_factory=utc_timestamp)

