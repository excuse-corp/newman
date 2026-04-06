from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/{session_id}")
async def get_audit_logs(session_id: str, request: Request):
    settings = request.app.state.settings
    audit_path = Path(settings.paths.audit_dir) / f"{session_id}.log"
    if not audit_path.exists():
        return {"session_id": session_id, "events": []}
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    return {"session_id": session_id, "events": lines}
