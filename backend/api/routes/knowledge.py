from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.rag.service import KnowledgeBaseService


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class ImportKnowledgeRequest(BaseModel):
    source_path: str = Field(..., min_length=1, description="Workspace 内待导入文件路径")


class SearchKnowledgeRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=5, ge=1, le=10)


def _service(request: Request) -> KnowledgeBaseService:
    settings = request.app.state.settings
    return KnowledgeBaseService(settings.paths.knowledge_dir, settings.paths.workspace)


@router.get("/documents")
async def list_documents(request: Request):
    service = _service(request)
    return {"documents": [item.model_dump(mode="json") for item in service.list_documents()]}


@router.post("/documents/import")
async def import_document(payload: ImportKnowledgeRequest, request: Request):
    service = _service(request)
    document = service.import_document(payload.source_path)
    return {"document": document.model_dump(mode="json")}


@router.post("/search")
async def search_knowledge(payload: SearchKnowledgeRequest, request: Request):
    service = _service(request)
    hits = service.search(payload.query, limit=payload.limit)
    return {"query": payload.query, "hits": [item.model_dump(mode="json") for item in hits]}
