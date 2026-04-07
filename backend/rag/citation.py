from __future__ import annotations

from backend.rag.models import KnowledgeCitation, KnowledgeChunk, KnowledgeDocument


def build_citation(document: KnowledgeDocument, chunk: KnowledgeChunk) -> KnowledgeCitation:
    return KnowledgeCitation(
        document_id=document.document_id,
        title=document.title,
        stored_path=document.stored_path,
        chunk_id=chunk.chunk_id,
        chunk_index=chunk.chunk_index,
        page_number=chunk.page_number,
        location_label=chunk.location_label,
        snippet=chunk.text[:400],
    )


def format_citation_label(citation: KnowledgeCitation) -> str:
    parts = [citation.title]
    if citation.location_label:
        parts.append(citation.location_label)
    elif citation.page_number is not None:
        parts.append(f"page {citation.page_number}")
    parts.append(f"chunk {citation.chunk_index}")
    return " · ".join(parts)
