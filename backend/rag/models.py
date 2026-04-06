from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeDocument(BaseModel):
    document_id: str
    title: str
    source_path: str
    stored_path: str
    size_bytes: int
    imported_at: str = Field(default_factory=utc_now)


class KnowledgeSearchHit(BaseModel):
    document_id: str
    title: str
    stored_path: str
    snippet: str
    score: float
    line_number: int | None = None
