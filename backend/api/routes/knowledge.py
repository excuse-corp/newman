from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile
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
    return KnowledgeBaseService(
        settings.paths.knowledge_dir,
        settings.paths.workspace,
        settings.models,
        settings.rag,
        settings.paths.chroma_dir,
        request.app.state.runtime.usage_store,
    )


@router.get("/documents")
async def list_documents(request: Request):
    service = _service(request)
    return {"documents": [item.model_dump(mode="json") for item in service.list_documents()]}


@router.post("/documents/import")
async def import_document(payload: ImportKnowledgeRequest, request: Request):
    service = _service(request)
    document = await service.import_document(payload.source_path)
    return {"document": document.model_dump(mode="json")}


@router.post("/documents/upload")
async def upload_document(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        raise ValueError("缺少上传文件名")
    settings = request.app.state.settings
    service = _service(request)
    suffix = Path(file.filename).suffix.lower()
    upload_dir = settings.paths.data_dir / "uploads" / "knowledge"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{uuid4().hex}{suffix}"
    stored_path.write_bytes(await file.read())

    if suffix in {".jpg", ".jpeg", ".png"}:
        analyses = await request.app.state.runtime.multimodal_analyzer.analyze_images("", [stored_path])
        summary = analyses[0]["summary"] if analyses else ""
        document = await service.import_image_analysis(
            source_name=file.filename,
            source_path=str(stored_path),
            summary=summary,
        )
    else:
        document = await service.import_file(
            stored_path,
            enforce_workspace=False,
            display_name=file.filename,
            source_reference=str(stored_path),
        )
    return {"document": document.model_dump(mode="json")}


@router.post("/search")
async def search_knowledge(payload: SearchKnowledgeRequest, request: Request):
    service = _service(request)
    hits = await service.search(payload.query, limit=payload.limit)
    return {"query": payload.query, "hits": [item.model_dump(mode="json") for item in hits]}
