from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


DraftStatus = Literal[
    "draft",
    "generated",
    "validated",
    "awaiting_approval",
    "approved",
    "installed_disabled",
    "rejected",
    "validation_failed",
    "install_failed",
    "rolled_back",
]


class PluginSkillSpec(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    when_to_use: str = Field(min_length=1, max_length=500)
    body_markdown: str = Field(min_length=1, max_length=100_000)


class PluginCommandSpec(BaseModel):
    tool_name: str = Field(min_length=2, max_length=64)
    executable: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=1_000)
    default_args: list[str] = Field(default_factory=list, max_length=32)
    approval_behavior: Literal["safe", "confirmable"] = "safe"
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    confirmation_flag: str | None = Field(default=None, max_length=64)
    readonly_prefixes: list[list[str]] = Field(default_factory=list, max_length=32)
    allow_stdin: bool = True
    readable_roots: list[str] = Field(default_factory=list, max_length=32)
    writable_roots: list[str] = Field(default_factory=list, max_length=32)
    env: dict[str, str] = Field(default_factory=dict, max_length=32)


class PluginEnvironmentSpec(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    required: bool = False
    secret: bool = True
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.replace("_", "").isalnum() or not normalized[0].isalpha():
            raise ValueError("environment variable name must be ASCII alphanumeric/underscore")
        return normalized


class PluginSpec(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(default="0.1.0", min_length=1, max_length=32)
    description: str = Field(default="", max_length=1_000)
    skills: list[PluginSkillSpec] = Field(default_factory=list, max_length=16)
    commands: list[PluginCommandSpec] = Field(default_factory=list, max_length=32)
    environment: list[PluginEnvironmentSpec] = Field(default_factory=list, max_length=32)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-").replace(" ", "-")
        if not normalized or not all(char.isalnum() or char == "-" for char in normalized):
            raise ValueError("plugin name must contain only letters, numbers, hyphens, and underscores")
        normalized = normalized.strip("-")
        if not normalized:
            raise ValueError("plugin name cannot be empty after normalization")
        return normalized


class PluginRiskReport(BaseModel):
    level: Literal["low", "medium", "high", "critical"] = "low"
    reasons: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool = False
    blocked: bool = False


class PluginValidationReport(BaseModel):
    ok: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class PluginDraftFileChange(BaseModel):
    path: str
    status: Literal["added", "modified", "deleted", "unchanged"]
    size_bytes: int | None = None
    sha256: str | None = None


class PluginDraftCommandReview(BaseModel):
    tool_name: str
    executable: str
    approval_behavior: Literal["safe", "confirmable"]
    env_keys: list[str] = Field(default_factory=list)
    readable_roots: list[str] = Field(default_factory=list)
    writable_roots: list[str] = Field(default_factory=list)


class PluginDraftReviewReport(BaseModel):
    install_target: str | None = None
    conflicts: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    commands: list[PluginDraftCommandReview] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    file_changes: list[PluginDraftFileChange] = Field(default_factory=list)
    required_confirmations: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


class PluginDraftRecord(BaseModel):
    draft_id: str
    status: DraftStatus
    created_at: str
    updated_at: str
    plugin_name: str
    spec: PluginSpec
    source_request: str | None = None
    package_path: str | None = None
    package_files: list[str] = Field(default_factory=list)
    manifest_content: str | None = None
    validation: PluginValidationReport | None = None
    risk: PluginRiskReport | None = None
    review: PluginDraftReviewReport | None = None
    error: str | None = None
    installed_path: str | None = None

    def package_dir(self) -> Path | None:
        return Path(self.package_path) if self.package_path else None


class PluginDraftCreateRequest(BaseModel):
    spec: PluginSpec | None = None
    request: str | None = Field(default=None, min_length=1, max_length=20_000)
    generate: bool = True

    @model_validator(mode="after")
    def require_spec_or_request(self):
        if self.spec is None and not (self.request and self.request.strip()):
            raise ValueError("spec 或 request 至少需要提供一个")
        return self


class PluginDraftActionRequest(BaseModel):
    confirm: bool = False
