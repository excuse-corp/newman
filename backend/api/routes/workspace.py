from __future__ import annotations

from datetime import datetime, timezone
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.tools.workspace_fs import (
    build_path_access_policy,
    classify_path,
    ensure_readable_path,
    should_skip_path,
)


router = APIRouter(prefix="/api/workspace", tags=["workspace"])


MEMORY_FILE_MAP = {
    "newman": "Newman.md",
    "user": "USER.md",
    "memory": "MEMORY.md",
    "skills": "SKILLS_SNAPSHOT.md",
}


class UpdateMemoryRequest(BaseModel):
    content: str = Field(..., min_length=0)


@router.get("/memory")
async def get_memory_workspace(request: Request):
    settings = request.app.state.settings
    files = {}
    latest_updated_at: str | None = None
    for key, name in MEMORY_FILE_MAP.items():
        path = settings.paths.memory_dir / name
        updated_at = _path_updated_at(path)
        if updated_at and (latest_updated_at is None or updated_at > latest_updated_at):
            latest_updated_at = updated_at
        files[key] = {
            "path": str(path),
            "content": path.read_text(encoding="utf-8") if path.exists() else "",
            "updated_at": updated_at,
        }
    return {"files": files, "latest_updated_at": latest_updated_at}


@router.put("/memory/{memory_key}")
async def update_memory_file(memory_key: str, payload: UpdateMemoryRequest, request: Request):
    settings = request.app.state.settings
    file_name = MEMORY_FILE_MAP.get(memory_key)
    if file_name is None:
        raise FileNotFoundError(f"Memory file not found: {memory_key}")
    path = settings.paths.memory_dir / file_name
    path.write_text(payload.content, encoding="utf-8")
    return {
        "saved": True,
        "memory_key": memory_key,
        "path": str(path),
        "updated_at": _path_updated_at(path),
    }


@router.get("/roots")
async def get_workspace_roots(request: Request):
    settings = request.app.state.settings
    policy = build_path_access_policy(settings)
    return {
        "workspace": str(policy.workspace),
        "readable_roots": [str(path) for path in policy.readable_roots],
        "writable_roots": [str(path) for path in policy.writable_roots],
        "protected_roots": [str(path) for path in policy.protected_roots],
    }


@router.get("/files")
async def list_workspace_files(request: Request, path: str = "."):
    settings = request.app.state.settings
    policy = build_path_access_policy(settings)
    target = ensure_readable_path(policy, path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if target.is_file():
        return {
            "path": str(target),
            "type": "file",
            "access": classify_path(policy, target),
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
                "access": classify_path(policy, child),
            }
        )
    return {"path": str(target), "type": "dir", "access": classify_path(policy, target), "entries": items}


@router.get("/file-content")
async def get_workspace_file_content(request: Request, path: str):
    settings = request.app.state.settings
    policy = build_path_access_policy(settings)
    target = ensure_readable_path(policy, path)
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if not target.is_file():
        raise ValueError("path 必须指向文件")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    response = FileResponse(target, media_type=media_type)
    response.headers["content-disposition"] = f'inline; filename="{target.name}"'
    return response


@router.get("/upload-content")
async def get_uploaded_file_content(request: Request, path: str):
    return _build_attachment_file_response(request, path)


@router.get("/attachment-content")
async def get_attachment_file_content(request: Request, path: str):
    return _build_attachment_file_response(request, path)


def _build_attachment_file_response(request: Request, path: str):
    settings = request.app.state.settings
    target = Path(path).resolve()
    workspace_root = Path(getattr(settings.paths, "workspace", settings.paths.data_dir / "runtime_workspace")).resolve()
    allowed_roots = [
        (settings.paths.data_dir / "uploads" / "chat").resolve(),
        (workspace_root / "user_uploads").resolve(),
        (workspace_root / "parser_outputs").resolve(),
    ]
    for root in allowed_roots:
        try:
            target.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise ValueError("path 不在允许读取的附件目录内")
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")
    if not target.is_file():
        raise ValueError("path 必须指向文件")

    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    response = FileResponse(target, media_type=media_type)
    response.headers["content-disposition"] = f'inline; filename="{target.name}"'
    return response


def _path_updated_at(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
