from __future__ import annotations

from typing import Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.usage.models import ModelUsageRecord


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS model_usage_records (
    usage_id BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    session_id TEXT,
    turn_id TEXT,
    request_kind TEXT NOT NULL,
    counts_toward_context_window BOOLEAN NOT NULL DEFAULT FALSE,
    streaming BOOLEAN NOT NULL DEFAULT FALSE,
    provider_type TEXT NOT NULL,
    model TEXT NOT NULL,
    context_window INTEGER,
    effective_context_window INTEGER,
    usage_available BOOLEAN NOT NULL DEFAULT FALSE,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    finish_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_model_usage_session_created_at
    ON model_usage_records(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_usage_turn_created_at
    ON model_usage_records(turn_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_usage_context_records
    ON model_usage_records(session_id, counts_toward_context_window, created_at DESC);
"""


class PostgresModelUsageStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._schema_ready = False

    def record(self, record: ModelUsageRecord) -> None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_usage_records (
                    request_id, session_id, turn_id, request_kind,
                    counts_toward_context_window, streaming,
                    provider_type, model, context_window, effective_context_window,
                    usage_available, input_tokens, output_tokens, total_tokens,
                    finish_reason, created_at, metadata
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (request_id) DO NOTHING
                """,
                (
                    record.request_id,
                    record.session_id,
                    record.turn_id,
                    record.request_kind,
                    record.counts_toward_context_window,
                    record.streaming,
                    record.provider_type,
                    record.model,
                    record.context_window,
                    record.effective_context_window,
                    record.usage_available,
                    record.input_tokens,
                    record.output_tokens,
                    record.total_tokens,
                    record.finish_reason,
                    record.created_at,
                    Jsonb(record.metadata),
                ),
            )
            conn.commit()

    def list_session_records(self, session_id: str, limit: int = 100) -> list[ModelUsageRecord]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    request_id, session_id, turn_id, request_kind,
                    counts_toward_context_window, streaming,
                    provider_type, model, context_window, effective_context_window,
                    usage_available, input_tokens, output_tokens, total_tokens,
                    finish_reason, created_at, metadata
                FROM model_usage_records
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        return [self._record_from_row(row) for row in rows]

    def latest_context_record(self, session_id: str) -> ModelUsageRecord | None:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT
                    request_id, session_id, turn_id, request_kind,
                    counts_toward_context_window, streaming,
                    provider_type, model, context_window, effective_context_window,
                    usage_available, input_tokens, output_tokens, total_tokens,
                    finish_reason, created_at, metadata
                FROM model_usage_records
                WHERE session_id = %s
                  AND counts_toward_context_window = TRUE
                  AND usage_available = TRUE
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cur.fetchone()
        return self._record_from_row(row) if row else None

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
    def _record_from_row(row: dict[str, object]) -> ModelUsageRecord:
        payload = dict(row)
        created_at = payload.get("created_at")
        if hasattr(created_at, "isoformat"):
            payload["created_at"] = created_at.isoformat()
        payload["metadata"] = dict(payload.get("metadata") or {})
        return ModelUsageRecord.model_validate(payload)
