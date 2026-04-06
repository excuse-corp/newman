from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


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


def resolve_workspace_path(workspace: Path, raw_path: str | None = None) -> Path:
    candidate = Path(raw_path or ".")
    target = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    workspace_root = workspace.resolve()
    if not target.is_relative_to(workspace_root):
        raise ValueError("path 必须位于 workspace 内")
    return target


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
