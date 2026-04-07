from __future__ import annotations

import hashlib
import math
from typing import Iterable

import httpx

from backend.config.schema import ModelConfig


HASH_EMBED_DIM = 256


class Embedder:
    def __init__(self, config: ModelConfig):
        self.config = config

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.config.type == "openai_compatible" and self.config.endpoint:
            try:
                return await self._embed_openai_compatible(texts)
            except Exception:
                pass
        return [hashed_embedding(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_texts([text])
        return embeddings[0] if embeddings else hashed_embedding(text)

    async def _embed_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.config.model,
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.config.endpoint.rstrip('/')}/embeddings",
                headers=_auth_headers(self.config.api_key),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        embeddings = [list(map(float, item.get("embedding", []))) for item in data]
        if len(embeddings) != len(texts) or any(not embedding for embedding in embeddings):
            raise ValueError("invalid embedding response")
        return embeddings


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def hashed_embedding(text: str, dim: int = HASH_EMBED_DIM) -> list[float]:
    vector = [0.0] * dim
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index, byte in enumerate(digest):
            bucket = index % dim
            vector[bucket] += (byte / 255.0) - 0.5
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _tokenize(text: str) -> Iterable[str]:
    for raw in text.lower().split():
        token = raw.strip()
        if token:
            yield token


def _auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}
