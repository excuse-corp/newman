from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


HookEvent = Literal["SessionStart", "PreToolUse", "PostToolUse", "SessionEnd", "FileChanged"]


class PluginHook(BaseModel):
    event: HookEvent
    message: str = ""
    handler: str | None = None
    timeout_seconds: int = Field(default=5, ge=1, le=30)


class PluginSkillRef(BaseModel):
    name: str
    path: str


class PluginUIConfig(BaseModel):
    entry: str | None = None


class PluginSandboxConfig(BaseModel):
    readable_roots: list[str] = Field(default_factory=list)
    writable_roots: list[str] = Field(default_factory=list)


class PluginPreflightConfig(BaseModel):
    bins: list[str] = Field(default_factory=list)
    readable_paths: list[str] = Field(default_factory=list)


class PluginPreflightCheckResult(BaseModel):
    kind: Literal["bin", "readable_path"]
    target: str
    resolved: str | None = None
    ok: bool
    message: str


class PluginPreflightReport(BaseModel):
    ok: bool = True
    issue_count: int = 0
    checks: list[PluginPreflightCheckResult] = Field(default_factory=list)


class PluginCLIConfirmationProtocolConfig(BaseModel):
    exit_code: int = Field(default=10, ge=1, le=255)
    error_type: str = Field(default="confirmation_required", min_length=1)


class PluginCLICommandConfig(BaseModel):
    tool_name: str = Field(min_length=2)
    executable: str = Field(min_length=1)
    description: str = ""
    default_args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    approval_behavior: Literal["safe", "confirmable"] = "safe"
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    confirmation_flag: str | None = None
    confirmation_protocol: PluginCLIConfirmationProtocolConfig = Field(
        default_factory=PluginCLIConfirmationProtocolConfig
    )
    readonly_prefixes: list[list[str]] = Field(default_factory=list)
    sandbox: PluginSandboxConfig | None = None
    allow_stdin: bool = True


class ResolvedPluginCLICommand(BaseModel):
    plugin_name: str
    plugin_root: str
    tool_name: str
    executable: str
    description: str = ""
    default_args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    approval_behavior: Literal["safe", "confirmable"] = "safe"
    timeout_seconds: int = 30
    confirmation_flag: str | None = None
    confirmation_protocol: PluginCLIConfirmationProtocolConfig = Field(
        default_factory=PluginCLIConfirmationProtocolConfig
    )
    readonly_prefixes: list[list[str]] = Field(default_factory=list)
    allow_stdin: bool = True
    readable_roots: list[str] = Field(default_factory=list)
    writable_roots: list[str] = Field(default_factory=list)


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str = ""
    enabled_by_default: bool = True
    skills: list[PluginSkillRef] = Field(default_factory=list)
    hooks: list[PluginHook] = Field(default_factory=list)
    mcp_servers: list[dict] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    sandbox: PluginSandboxConfig | None = None
    preflight: PluginPreflightConfig | None = None
    commands: list[PluginCLICommandConfig] = Field(default_factory=list)
    ui: PluginUIConfig | None = None


class PluginRecord(BaseModel):
    name: str
    version: str
    description: str
    enabled: bool
    plugin_path: str
    skill_count: int = 0
    hook_count: int = 0
    mcp_server_count: int = 0
    cli_command_count: int = 0
    preflight: PluginPreflightReport = Field(default_factory=PluginPreflightReport)


class SkillDescriptor(BaseModel):
    name: str
    source: str
    plugin_name: str | None = None
    path: str
    description: str = ""
    when_to_use: str | None = None
    summary: str = ""


class LoadedPlugin(BaseModel):
    manifest: PluginManifest
    root_path: Path
    skills: list[SkillDescriptor] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class PluginLoadError(BaseModel):
    plugin_path: str
    plugin_name: str | None = None
    message: str
