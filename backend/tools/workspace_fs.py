from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

from backend.config.schema import AppConfig


IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


@dataclass
class TextFilePayload:
    path: Path
    content: str
    truncated: bool = False


@dataclass(frozen=True)
class PathAccessPolicy:
    workspace: Path
    browse_root: Path
    output_root: Path
    readable_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    protected_roots: tuple[Path, ...]
    sandbox_mode: str = "workspace-write"


class PathPolicyError(ValueError):
    def __init__(self, message: str, *, error_code: str = "", sandbox_denied: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.sandbox_denied = sandbox_denied


def build_path_access_policy(settings: AppConfig) -> PathAccessPolicy:
    workspace = settings.paths.workspace.resolve()
    browse_root_setting = getattr(settings.paths, "browse_root", None)
    output_root_setting = getattr(settings.paths, "output_root", None)
    browse_root = (browse_root_setting or settings.paths.workspace).resolve()
    output_root = (output_root_setting or (settings.paths.workspace / "outputs" / "chat")).resolve()
    permissions = getattr(settings, "permissions", None)
    readable_paths = list(getattr(permissions, "readable_paths", []))
    writable_paths = list(getattr(permissions, "writable_paths", []))
    protected_paths = list(getattr(permissions, "protected_paths", []))
    sandbox = getattr(settings, "sandbox", None)
    sandbox_mode = str(getattr(sandbox, "mode", "workspace-write"))
    writable_roots = _dedupe_roots([output_root, *writable_paths])
    readable_roots = _dedupe_roots([workspace, browse_root, output_root, *writable_roots, *readable_paths])
    protected_roots = _dedupe_roots(protected_paths)
    return PathAccessPolicy(
        workspace=workspace,
        browse_root=browse_root,
        output_root=output_root,
        readable_roots=tuple(readable_roots),
        writable_roots=tuple(writable_roots),
        protected_roots=tuple(protected_roots),
        sandbox_mode=sandbox_mode,
    )


def coerce_path_access_policy(policy_or_workspace: PathAccessPolicy | Path) -> PathAccessPolicy:
    if isinstance(policy_or_workspace, PathAccessPolicy):
        return policy_or_workspace
    workspace = policy_or_workspace.resolve()
    return PathAccessPolicy(
        workspace=workspace,
        browse_root=workspace,
        output_root=workspace / "outputs" / "chat",
        readable_roots=(workspace,),
        writable_roots=(workspace,),
        protected_roots=(),
        sandbox_mode="workspace-write",
    )


def resolve_workspace_path(workspace: Path, raw_path: str | None = None) -> Path:
    candidate = Path(raw_path or ".")
    target = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    workspace_root = workspace.resolve()
    if not target.is_relative_to(workspace_root):
        raise ValueError("path 必须位于 workspace 内")
    return target


def resolve_requested_path(policy: PathAccessPolicy, raw_path: str | None = None) -> Path:
    candidate = Path(raw_path or ".")
    return (policy.browse_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


def resolve_writable_path(policy: PathAccessPolicy, raw_path: str | None = None) -> Path:
    candidate = Path(raw_path or ".")
    return (policy.workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


def classify_path(policy: PathAccessPolicy, path: Path) -> str:
    resolved = path.resolve()
    if _matches_any_root(resolved, policy.protected_roots):
        return "protected"
    if _matches_any_root(resolved, policy.writable_roots):
        return "writable"
    if _matches_any_root(resolved, policy.readable_roots):
        return "readable"
    return "forbidden"


def ensure_readable_path(policy: PathAccessPolicy, raw_path: str | None = None) -> Path:
    target = resolve_requested_path(policy, raw_path)
    state = classify_path(policy, target)
    if state == "protected":
        raise ValueError("path 位于受保护目录内")
    if state == "forbidden":
        raise ValueError("path 不在允许读取的目录内")
    return target


def ensure_writable_path(policy: PathAccessPolicy, raw_path: str | None = None) -> Path:
    if policy.sandbox_mode == "read-only":
        raise PathPolicyError("当前沙箱为 read-only，禁止写入", error_code="SANDBOX_DENIED", sandbox_denied=True)
    target = resolve_writable_path(policy, raw_path)
    state = classify_path(policy, target)
    if state == "protected":
        raise PathPolicyError("path 位于受保护目录内", error_code="SANDBOX_DENIED", sandbox_denied=True)
    if state != "writable":
        raise PathPolicyError("path 不在允许写入的目录内", error_code="SANDBOX_DENIED", sandbox_denied=True)
    return target


def display_path(policy: PathAccessPolicy, path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(policy.browse_root))
    except ValueError:
        return str(resolved)


def is_hidden_path(path: Path, workspace: Path) -> bool:
    try:
        relative = path.relative_to(workspace)
    except ValueError:
        relative = path
    return any(part.startswith(".") for part in relative.parts if part not in {".", ".."})


def should_skip_path(path: Path, workspace: Path, include_hidden: bool) -> bool:
    if path.name in IGNORED_DIRECTORY_NAMES:
        return True
    if not include_hidden and is_hidden_path(path, workspace):
        return True
    return False


def iter_workspace_files(root: Path, workspace: Path, include_hidden: bool) -> list[Path]:
    if root.is_file():
        return [root]

    files: list[Path] = []
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        for child in sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()), reverse=True):
            if should_skip_path(child, workspace, include_hidden):
                continue
            if child.is_dir():
                stack.append(child)
                continue
            files.append(child)
    return sorted(files)


def read_text_file(path: Path, max_bytes: int = 200_000) -> TextFilePayload | None:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return None
    truncated = len(raw) > max_bytes
    data = raw[:max_bytes]
    return TextFilePayload(
        path=path,
        content=data.decode("utf-8", errors="replace"),
        truncated=truncated,
    )


def matches_glob(path: Path, pattern: str | None) -> bool:
    if not pattern:
        return True
    return fnmatch(path.name, pattern) or fnmatch(str(path.as_posix()), pattern)


def _matches_any_root(path: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _dedupe_roots(paths: Iterable[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = raw.resolve()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped
