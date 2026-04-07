from __future__ import annotations

from pathlib import Path

import chromadb

from backend.rag.models import KnowledgeChunk


class ChromaVectorStore:
    def __init__(self, path: Path, collection_name: str):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=[chunk.embedding for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {
                    "document_id": chunk.document_id,
                    "title": chunk.title,
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number or -1,
                    "location_label": chunk.location_label or "",
                }
                for chunk in chunks
            ],
        )

    def delete_document(self, document_id: str) -> None:
        self.collection.delete(where={"document_id": document_id})

    def query(self, query_embedding: list[float], limit: int) -> list[dict[str, object]]:
        if not query_embedding:
            return []
        payload = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, limit),
            include=["distances", "metadatas", "documents"],
        )
        ids = payload.get("ids", [[]])[0]
        distances = payload.get("distances", [[]])[0]
        metadatas = payload.get("metadatas", [[]])[0]
        documents = payload.get("documents", [[]])[0]

        results: list[dict[str, object]] = []
        for chunk_id, distance, metadata, document in zip(ids, distances, metadatas, documents, strict=True):
            results.append(
                {
                    "chunk_id": chunk_id,
                    "distance": float(distance if distance is not None else 1.0),
                    "metadata": metadata or {},
                    "document": document or "",
                }
            )
        return results
