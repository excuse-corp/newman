from __future__ import annotations

from typing import Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.rag.models import KnowledgeChunk, KnowledgeCitationRecord, KnowledgeDocument, utc_now


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rag_documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    stored_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    content_type TEXT NOT NULL,
    parser TEXT NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    page_count INTEGER,
    imported_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rag_documents(document_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    page_number INTEGER,
    chunk_index INTEGER NOT NULL,
    location_label TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_document_id ON rag_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_chunk_index ON rag_chunks(chunk_index);

CREATE TABLE IF NOT EXISTS rag_search_stats (
    stat_id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    hit_count INTEGER NOT NULL,
    top_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_citation_records (
    citation_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    document_id TEXT NOT NULL REFERENCES rag_documents(document_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES rag_chunks(chunk_id) ON DELETE CASCADE,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    rank INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_citation_records_query ON rag_citation_records(query);
CREATE INDEX IF NOT EXISTS idx_rag_citation_records_document_id ON rag_citation_records(document_id);
"""


class PostgresRAGStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._schema_ready = False

    def list_documents(self) -> list[KnowledgeDocument]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM rag_documents ORDER BY imported_at DESC")
            rows = cur.fetchall()
        return [self._document_from_row(row) for row in rows]

    def get_document_by_source_path(self, source_path: str) -> KnowledgeDocument | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM rag_documents WHERE source_path = %s", (source_path,))
            row = cur.fetchone()
        return self._document_from_row(row) if row else None

    def replace_document(self, document: KnowledgeDocument, chunks: list[KnowledgeChunk]) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("DELETE FROM rag_documents WHERE source_path = %s", (document.source_path,))
                cur.execute(
                    """
                    INSERT INTO rag_documents (
                        document_id, title, source_path, stored_path, size_bytes,
                        content_type, parser, chunk_count, page_count, imported_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document.document_id,
                        document.title,
                        document.source_path,
                        document.stored_path,
                        document.size_bytes,
                        document.content_type,
                        document.parser,
                        document.chunk_count,
                        document.page_count,
                        document.imported_at,
                        Jsonb({}),
                    ),
                )
                if chunks:
                    cur.executemany(
                        """
                        INSERT INTO rag_chunks (
                            chunk_id, document_id, title, text, token_count,
                            page_number, chunk_index, location_label, metadata
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                chunk.chunk_id,
                                chunk.document_id,
                                chunk.title,
                                chunk.text,
                                chunk.token_count,
                                chunk.page_number,
                                chunk.chunk_index,
                                chunk.location_label,
                                Jsonb(dict(chunk.metadata)),
                            )
                            for chunk in chunks
                        ],
                    )
            conn.commit()

    def delete_document(self, document_id: str) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM rag_documents WHERE document_id = %s", (document_id,))
            conn.commit()

    def list_chunks(self) -> list[KnowledgeChunk]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM rag_chunks ORDER BY document_id, chunk_index")
            rows = cur.fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def get_chunks_by_ids(self, chunk_ids: Iterable[str]) -> list[KnowledgeChunk]:
        self.ensure_schema()
        ids = list(chunk_ids)
        if not ids:
            return []
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM rag_chunks
                WHERE chunk_id = ANY(%s)
                ORDER BY document_id, chunk_index
                """,
                (ids,),
            )
            rows = cur.fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def record_search_stat(self, query: str, hit_count: int, top_score: float) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rag_search_stats (query, hit_count, top_score, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (query, hit_count, top_score, utc_now()),
            )
            conn.commit()

    def record_citations(self, records: list[KnowledgeCitationRecord]) -> None:
        self.ensure_schema()
        if not records:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO rag_citation_records (
                    citation_id, query, document_id, chunk_id, score, rank, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        record.citation_id,
                        record.query,
                        record.document_id,
                        record.chunk_id,
                        record.score,
                        record.rank,
                        record.created_at,
                    )
                    for record in records
                ],
            )
            conn.commit()

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
            conn.commit()
        self._schema_ready = True

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn)

    @staticmethod
    def _document_from_row(row: dict) -> KnowledgeDocument:
        return KnowledgeDocument(
            document_id=row["document_id"],
            title=row["title"],
            source_path=row["source_path"],
            stored_path=row["stored_path"],
            size_bytes=row["size_bytes"],
            content_type=row["content_type"],
            parser=row["parser"],
            chunk_count=row["chunk_count"],
            page_count=row["page_count"],
            imported_at=row["imported_at"].isoformat() if hasattr(row["imported_at"], "isoformat") else str(row["imported_at"]),
        )

    @staticmethod
    def _chunk_from_row(row: dict) -> KnowledgeChunk:
        return KnowledgeChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            title=row["title"],
            text=row["text"],
            token_count=row["token_count"],
            embedding=[],
            page_number=row["page_number"],
            chunk_index=row["chunk_index"],
            location_label=row["location_label"],
            metadata=dict(row.get("metadata") or {}),
        )
