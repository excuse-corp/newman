from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel


router = APIRouter(prefix="/api/evolution", tags=["evolution"])


class RunEvolutionRequest(BaseModel):
    session_id: str
    trigger: str = "manual"


@router.get("/runs")
async def list_evolution_runs(request: Request, limit: int = 50):
    runtime = request.app.state.runtime
    return {
        "runs": [
            item.model_dump(mode="json")
            for item in runtime.evolution_store.list_runs(limit=limit)
        ]
    }


@router.get("/runs/{run_id}")
async def get_evolution_run(run_id: str, request: Request):
    runtime = request.app.state.runtime
    return {"run": runtime.evolution_store.get_run(run_id).model_dump(mode="json")}


@router.post("/run")
async def run_evolution(payload: RunEvolutionRequest, request: Request):
    runtime = request.app.state.runtime
    trigger = payload.trigger if payload.trigger in {"new_session_created", "turn_interval", "manual"} else "manual"
    record = await runtime.evolution_service.run_for_session(payload.session_id, trigger)
    return {"run": record.model_dump(mode="json")}


@router.post("/runs/{run_id}/rollback")
async def rollback_evolution_run(run_id: str, request: Request):
    runtime = request.app.state.runtime
    record = runtime.evolution_service.rollback_run(run_id)
    return {"run": record.model_dump(mode="json")}

