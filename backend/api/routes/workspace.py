from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.tools.workspace_fs import resolve_workspace_path, should_skip_path


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


MEMORY_FILE_MAP = {
    "newman": "Newman.md",
    "user": "USER.md",
    "skills": "SKILLS_SNAPSHOT.md",
    "memory": "MEMORY.md",
}


class UpdateMemoryRequest(BaseModel):
    content: str = Field(..., min_length=0)


@router.get("/memory")
async def get_memory_workspace(request: Request):
    settings = request.app.state.settings
    files = {}
    for key, name in MEMORY_FILE_MAP.items():
        path = settings.paths.memory_dir / name
        files[key] = {
            "path": str(path),
            "content": path.read_text(encoding="utf-8") if path.exists() else "",
        }
    return {"files": files}


@router.put("/memory/{memory_key}")
async def update_memory_file(memory_key: str, payload: UpdateMemoryRequest, request: Request):
    settings = request.app.state.settings
    file_name = MEMORY_FILE_MAP.get(memory_key)
    if file_name is None:
        raise FileNotFoundError(f"Memory file not found: {memory_key}")
    path = settings.paths.memory_dir / file_name
    path.write_text(payload.content, encoding="utf-8")
    return {"saved": True, "memory_key": memory_key, "path": str(path)}


@router.get("/files")
async def list_workspace_files(request: Request, path: str = "."):
    settings = request.app.state.settings
    target = resolve_workspace_path(settings.paths.workspace, path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if target.is_file():
        return {
            "path": str(target),
            "type": "file",
            "content": target.read_text(encoding="utf-8", errors="replace")[:20000],
        }
    items = []
    for child in sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))[:200]:
        if should_skip_path(child, settings.paths.workspace, include_hidden=False):
            continue
        items.append(
            {
                "name": child.name,
                "path": str(child),
                "type": "dir" if child.is_dir() else "file",
            }
        )
    return {"path": str(target), "type": "dir", "entries": items}
