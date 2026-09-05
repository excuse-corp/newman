from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from backend.api.audit_events import read_audit_lines


router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/{session_id}")
async def get_audit_logs(session_id: str, request: Request, limit: int | None = None):
    if limit is not None and limit <= 0:
        raise ValueError("limit 必须大于 0")
    settings = request.app.state.settings
    audit_path = Path(settings.paths.audit_dir) / f"{session_id}.log"
    if not audit_path.exists():
        return {"session_id": session_id, "events": []}
    lines = read_audit_lines(audit_path, limit=limit)
    return {"session_id": session_id, "events": lines}
