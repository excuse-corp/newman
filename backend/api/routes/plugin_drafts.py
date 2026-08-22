from __future__ import annotations

from fastapi import APIRouter, Request

from backend.plugin_runtime.draft_models import PluginDraftActionRequest, PluginDraftCreateRequest


router = APIRouter(prefix="/api/plugin-drafts", tags=["plugin-drafts"])


def _detail(record):
    return {"draft": record.model_dump(mode="json")}


@router.get("")
async def list_plugin_drafts(request: Request):
    return {"drafts": [item.model_dump(mode="json") for item in request.app.state.runtime.plugin_draft_service.list()]}


@router.post("")
async def create_plugin_draft(payload: PluginDraftCreateRequest, request: Request):
    service = request.app.state.runtime.plugin_draft_service
    if payload.spec is not None:
        record = service.create(payload.spec, source_request=payload.request)
    else:
        record = service.create_from_request(payload.request or "")
    if payload.generate and record.status == "generated":
        record = service.validate(record.draft_id)
    return _detail(record)


@router.get("/{draft_id}")
async def get_plugin_draft(draft_id: str, request: Request):
    return _detail(request.app.state.runtime.plugin_draft_service.get(draft_id))


@router.post("/{draft_id}/validate")
async def validate_plugin_draft(draft_id: str, request: Request):
    return _detail(request.app.state.runtime.plugin_draft_service.validate(draft_id))


@router.get("/{draft_id}/review")
async def review_plugin_draft(draft_id: str, request: Request):
    record = request.app.state.runtime.plugin_draft_service.review(draft_id)
    return {"review": record.review.model_dump(mode="json") if record.review else None, "draft": record.model_dump(mode="json")}


@router.post("/{draft_id}/approve")
async def approve_plugin_draft(draft_id: str, payload: PluginDraftActionRequest, request: Request):
    return _detail(request.app.state.runtime.plugin_draft_service.approve(draft_id, confirm=payload.confirm))


@router.post("/{draft_id}/install")
async def install_plugin_draft(draft_id: str, request: Request):
    runtime = request.app.state.runtime
    record = runtime.plugin_draft_service.install(draft_id)
    runtime.reload_ecosystem()
    return _detail(record)


@router.post("/{draft_id}/reject")
async def reject_plugin_draft(draft_id: str, request: Request):
    return _detail(request.app.state.runtime.plugin_draft_service.reject(draft_id))


@router.post("/{draft_id}/rollback")
async def rollback_plugin_draft(draft_id: str, request: Request):
    runtime = request.app.state.runtime
    record = runtime.plugin_draft_service.rollback(draft_id)
    runtime.reload_ecosystem()
    return _detail(record)
