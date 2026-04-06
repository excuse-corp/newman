from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])


class ProviderConfig(BaseModel):
    type: Literal["mock", "openai_compatible", "anthropic_compatible"] = "mock"
    model: str = "newman-dev"
    endpoint: str | None = None
    api_key: str | None = None
    timeout: int = 60
    max_tokens: int = 4096
    temperature: float = 0.2


class RuntimeConfig(BaseModel):
    max_tool_depth: int = 20
    context_compress_threshold: float = 0.8
    context_critical_threshold: float = 0.92
    tool_retry_attempts: int = 3
    tool_retry_backoff_seconds: float = 1.0


class SandboxConfig(BaseModel):
    enabled: bool = False
    image: str = "newman-sandbox:latest"
    cpu_limit: float = 1.0
    memory_limit: str = "512m"
    timeout: int = 30
    output_limit_bytes: int = 10_240


class ApprovalConfig(BaseModel):
    level1_blacklist: list[str] = Field(default_factory=lambda: ["rm -rf /", "sudo", "su ", "chmod 777 /", "chown root"])
    level2_patterns: list[str] = Field(
        default_factory=lambda: ["write_file_outside_workspace", "network_access_unlisted", "process_spawn"]
    )
    timeout_seconds: int = 120


class PathsConfig(BaseModel):
    workspace: Path = Path.cwd()
    data_dir: Path = Path("backend_data")
    sessions_dir: Path = Path("backend_data/sessions")
    memory_dir: Path = Path("backend_data/memory")
    audit_dir: Path = Path("backend_data/audit")
    knowledge_dir: Path = Path("backend_data/knowledge")
    plugins_dir: Path = Path("plugins")
    skills_dir: Path = Path("skills")
    mcp_dir: Path = Path("backend_data/mcp")
    scheduler_dir: Path = Path("backend_data/scheduler")
    channels_dir: Path = Path("backend_data/channels")


class ChannelPlatformConfig(BaseModel):
    enabled: bool = True
    webhook_token: str | None = None


class ChannelsConfig(BaseModel):
    feishu: ChannelPlatformConfig = Field(default_factory=ChannelPlatformConfig)
    wecom: ChannelPlatformConfig = Field(default_factory=ChannelPlatformConfig)


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @classmethod
    def model_validate_merged(cls, data: dict[str, Any]) -> "AppConfig":
        return cls.model_validate(data)
