from __future__ import annotations

from pathlib import Path


def resolve_workspace(workspace: Path) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace.resolve()
