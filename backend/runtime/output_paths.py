from __future__ import annotations

from pathlib import Path


def output_root_dir(workspace: Path) -> Path:
    return workspace.resolve() / "outputs" / "chat"


def session_output_dir(workspace: Path, session_id: str) -> Path:
    return output_root_dir(workspace) / session_id


def turn_output_dir(workspace: Path, session_id: str, turn_id: str) -> Path:
    return session_output_dir(workspace, session_id) / turn_id


def turn_output_relative_dir(session_id: str, turn_id: str) -> str:
    return f"outputs/chat/{session_id}/{turn_id}"


def is_within_turn_output_dir(path: Path, workspace: Path, session_id: str, turn_id: str) -> bool:
    target = path.resolve()
    root = turn_output_dir(workspace, session_id, turn_id).resolve()
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def is_within_session_output_dir(path: Path, workspace: Path, session_id: str) -> bool:
    target = path.resolve()
    root = session_output_dir(workspace, session_id).resolve()
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False
