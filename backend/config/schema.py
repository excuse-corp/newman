from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


EFFECTIVE_CONTEXT_WINDOW_PERCENT = 95


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8005
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"])


class ModelConfig(BaseModel):
    type: Literal["mock", "openai_compatible", "anthropic_compatible"] = "mock"
    model: str = "newman-dev"
    endpoint: str | None = None
    api_key: str | None = None
    context_window: int | None = None
    embedding_dimension: int | None = None
    timeout: int = 60
    max_tokens: int = 4096
    temperature: float = 0.2

    @property
    def effective_context_window(self) -> int | None:
        if self.context_window is None:
            return None
        return max((self.context_window * EFFECTIVE_CONTEXT_WINDOW_PERCENT) // 100, 1)


class ModelsConfig(BaseModel):
    primary: ModelConfig = Field(default_factory=ModelConfig)
    multimodal: ModelConfig = Field(default_factory=ModelConfig)
    embedding: ModelConfig = Field(default_factory=ModelConfig)
    reranker: ModelConfig = Field(default_factory=ModelConfig)


class RuntimeConfig(BaseModel):
    max_tool_depth: int = 30
    context_compress_threshold: float = 0.8
    context_critical_threshold: float = 0.92
    tool_retry_attempts: int = 3
    tool_retry_backoff_seconds: float = 1.0


class SandboxConfig(BaseModel):
    enabled: bool = True
    backend: Literal["linux_bwrap"] = "linux_bwrap"
    mode: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    network_access: bool = False
    writable_roots: list[str] = Field(default_factory=list)
    timeout: int = 30
    output_limit_bytes: int = 10_240


class ApprovalConfig(BaseModel):
    level1_blacklist: list[str] = Field(default_factory=lambda: ["rm -rf /", "sudo", "su ", "chmod 777 /", "chown root"])
    level2_patterns: list[str] = Field(
        default_factory=lambda: [
            "write_file_outside_workspace",
            "process_spawn",
            "terminal_mutation_or_unknown",
            "danger_full_access_terminal",
            "maintain_memory",
            "maintain_skill",
            "maintain_plugin",
            "maintain_tool",
        ]
    )
    timeout_seconds: int = 120


class PermissionsConfig(BaseModel):
    readable_paths: list[Path] = Field(default_factory=list)
    writable_paths: list[Path] = Field(default_factory=list)
    protected_paths: list[Path] = Field(default_factory=list)


class RagConfig(BaseModel):
    postgres_dsn: str = "postgresql://postgres@127.0.0.1:65437/newman"
    chroma_collection: str = "knowledge_chunks"
    lexical_candidate_count: int = 24
    vector_candidate_count: int = 24
    hybrid_candidate_count: int = 32


class PathsConfig(BaseModel):
    workspace: Path = Path.cwd()
    data_dir: Path = Path("backend_data")
    sessions_dir: Path = Path("backend_data/sessions")
    memory_dir: Path = Path("backend_data/memory")
    audit_dir: Path = Path("backend_data/audit")
    knowledge_dir: Path = Path("backend_data/knowledge")
    chroma_dir: Path = Path("backend_data/chroma")
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
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)

    @property
    def provider(self) -> ModelConfig:
        return self.models.primary

    @classmethod
    def model_validate_merged(cls, data: dict[str, Any]) -> "AppConfig":
        payload = dict(data)
        legacy_provider = payload.pop("provider", None)
        models = payload.get("models")
        if not isinstance(models, dict):
            models = {}

        if isinstance(legacy_provider, dict):
            primary = models.get("primary")
            if not isinstance(primary, dict):
                primary = {}
            models["primary"] = {**legacy_provider, **primary}

        payload["models"] = models
        return cls.model_validate(payload)
