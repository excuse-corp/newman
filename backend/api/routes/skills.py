from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills(request: Request):
    runtime = request.app.state.runtime
    runtime.skill_registry.sync_snapshot()
    return {"skills": [item.model_dump(mode="json") for item in runtime.skill_registry.list_skills()]}
