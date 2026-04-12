from __future__ import annotations

import json
from typing import Any

from backend.config.schema import ModelConfig
from backend.providers.factory import build_provider
from backend.rag.models import KnowledgeChunk
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


class Reranker:
    def __init__(self, config: ModelConfig, usage_store: PostgresModelUsageStore | None = None):
        self.config = config
        self.provider = build_provider(config)
        self.usage_store = usage_store

    async def rerank(self, query: str, chunks: list[KnowledgeChunk], initial_scores: dict[str, float]) -> dict[str, float]:
        if not chunks:
            return {}
        if self.config.type == "mock":
            return {chunk.chunk_id: initial_scores.get(chunk.chunk_id, 0.0) for chunk in chunks}
        try:
            return await self._rerank_with_model(query, chunks, initial_scores)
        except Exception:
            return {chunk.chunk_id: initial_scores.get(chunk.chunk_id, 0.0) for chunk in chunks}

    async def _rerank_with_model(self, query: str, chunks: list[KnowledgeChunk], initial_scores: dict[str, float]) -> dict[str, float]:
        if self.config.type != "openai_compatible":
            raise ValueError("RAG reranker requires an OpenAI-compatible model or mock fallback")
        payload = {
            "query": query,
            "candidates": [
                {
                    "chunk_id": chunk.chunk_id,
                    "title": chunk.title,
                    "location": chunk.location_label,
                    "text": chunk.text[:1200],
                    "initial_score": round(initial_scores.get(chunk.chunk_id, 0.0), 4),
                }
                for chunk in chunks
            ],
        }
        response = await self.provider.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 RAG reranker。请根据 query 对候选片段相关性打分，只输出 JSON 数组。"
                        "每项格式为 {\"chunk_id\": \"...\", \"score\": 0-100}。不要输出额外解释。"
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            tools=None,
            temperature=0,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="rag_rerank",
                model_config=self.config,
                provider_type=self.config.type,
                streaming=False,
                counts_toward_context_window=False,
                metadata={
                    "candidate_count": len(chunks),
                    "query_length": len(query),
                },
            ),
            response,
        )
        data = _parse_json_array(response.content)
        scores: dict[str, float] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id", "")).strip()
            if not chunk_id:
                continue
            try:
                score = float(item.get("score", 0))
            except (TypeError, ValueError):
                continue
            scores[chunk_id] = max(0.0, min(100.0, score)) / 100.0
        if scores:
            return scores
        return {chunk.chunk_id: initial_scores.get(chunk.chunk_id, 0.0) for chunk in chunks}


def _parse_json_array(content: str) -> list[Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json", "", 1).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return []
    return payload if isinstance(payload, list) else []
