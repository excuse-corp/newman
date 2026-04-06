from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


HookEvent = Literal["SessionStart", "PreToolUse", "PostToolUse", "SessionEnd", "FileChanged"]


class PluginHook(BaseModel):
    event: HookEvent
    message: str = ""


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str = ""
    enabled_by_default: bool = True
    hooks: list[PluginHook] = Field(default_factory=list)
    mcp_servers: list[dict] = Field(default_factory=list)


class PluginRecord(BaseModel):
    name: str
    version: str
    description: str
    enabled: bool
    plugin_path: str
    skill_count: int = 0
    hook_count: int = 0
    mcp_server_count: int = 0


class SkillDescriptor(BaseModel):
    name: str
    source: str
    plugin_name: str | None = None
    path: str
    summary: str = ""


class LoadedPlugin(BaseModel):
    manifest: PluginManifest
    root_path: Path
    skills: list[SkillDescriptor] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}
