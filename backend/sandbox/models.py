from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Mapping


SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
Enforcement = Literal["full", "partial", "unsupported"]
SandboxBackend = Literal[
    "auto",
    "linux_bwrap",
    "linux_landlock",
    "macos_seatbelt",
    "windows_acl",
    "none",
]
PolicySource = Literal["deployment", "session", "approval"]


@dataclass(frozen=True)
class SandboxPolicy:
    mode: SandboxMode
    workspace_root: Path
    cwd: Path
    readable_roots: tuple[Path, ...] = ()
    writable_roots: tuple[Path, ...] = ()
    protected_roots: tuple[Path, ...] = ()
    network_access: bool = False
    require_network_isolation: bool = True
    require_process_isolation: bool = True
    allow_partial_enforcement: bool = False
    env_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_*")
    timeout_seconds: int | None = None
    output_limit_bytes: int | None = None
    session_id: str | None = None
    tool_call_id: str | None = None
    invocation_id: str = ""
    source: PolicySource = "deployment"


@dataclass(frozen=True)
class RunnerFailureRule:
    exit_codes: tuple[int, ...] = ()
    stderr_prefixes: tuple[str, ...] = ()
    stderr_substrings: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ConfinedArgv:
    argv: tuple[str, ...]
    backend: str
    file_enforcement: Enforcement
    network_enforcement: Enforcement
    process_enforcement: Enforcement
    resource_enforcement: Enforcement = "partial"
    denial_signatures: tuple[str, ...] = ()
    runner_failure_rules: tuple[RunnerFailureRule, ...] = ()
    notes: tuple[str, ...] = ()
    # Optional child-only hook used by providers such as Landlock. It must
    # never run in the Newman parent process.
    preexec_fn: Callable[[], None] | None = None
    process_visibility_enforcement: Enforcement = "unsupported"
    process_lifecycle_enforcement: Enforcement = "unsupported"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedSandboxInvocation:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path
    backend: str
    file_enforcement: Enforcement
    network_enforcement: Enforcement
    process_visibility_enforcement: Enforcement
    process_lifecycle_enforcement: Enforcement
    resource_enforcement: Enforcement = "partial"
    denial_signatures: tuple[str, ...] = ()
    runner_failure_rules: tuple[RunnerFailureRule, ...] = ()
    notes: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    cleanup: Callable[[], Awaitable[None]] | None = None
    start_new_session: bool = False
    preexec_fn: Callable[[], None] | None = None


@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    backend: str
    file_enforcement: Enforcement
    network_enforcement: Enforcement
    process_enforcement: Enforcement
    resource_enforcement: Enforcement = "partial"
    detail: str = ""
    process_visibility_enforcement: Enforcement = "unsupported"
    process_lifecycle_enforcement: Enforcement = "unsupported"


@dataclass(frozen=True)
class SandboxRunRequest:
    argv: tuple[str, ...]
    policy: SandboxPolicy
    env: Mapping[str, str] = field(default_factory=dict)
    stdin: bytes | None = None
    stream: bool = False
    label: str = ""


@dataclass(frozen=True)
class SandboxRunResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    error_code: str | None
    error_message: str | None
    metadata: Mapping[str, object]
