from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeDocument(BaseModel):
    document_id: str
    title: str
    source_path: str
    stored_path: str
    size_bytes: int
    content_type: str = "text/plain"
    parser: str = "text"
    chunk_count: int = 0
    page_count: int | None = None
    imported_at: str = Field(default_factory=utc_now)


class KnowledgeChunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    text: str
    token_count: int
    embedding: list[float] = Field(default_factory=list)
    page_number: int | None = None
    chunk_index: int
    location_label: str | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class KnowledgeCitation(BaseModel):
    document_id: str
    title: str
    stored_path: str
    chunk_id: str
    chunk_index: int
    page_number: int | None = None
    location_label: str | None = None
    snippet: str


class KnowledgeCitationRecord(BaseModel):
    citation_id: str
    query: str
    document_id: str
    chunk_id: str
    score: float
    rank: int
    created_at: str = Field(default_factory=utc_now)


class KnowledgeSearchHit(BaseModel):
    document_id: str
    title: str
    stored_path: str
    snippet: str
    score: float
    lexical_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: float = 0.0
    source: Literal["hybrid", "lexical", "vector"] = "hybrid"
    line_number: int | None = None
    chunk_id: str | None = None
    chunk_index: int | None = None
    page_number: int | None = None
    location_label: str | None = None
    citation: KnowledgeCitation | None = None
