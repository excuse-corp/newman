from __future__ import annotations

import asyncio
import unittest
from typing import Any

from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse
from backend.providers.limited import LimitedProvider


class _StreamingProvider(BaseProvider):
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._lock = asyncio.Lock()

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        raise AssertionError("chat should not be called")

    async def chat_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any):
        async with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
        try:
            await self.release.wait()
            yield ProviderChunk(type="text", delta="ok")
            yield ProviderChunk(type="done", finish_reason="stop")
        finally:
            async with self._lock:
                self.active -= 1

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return 1


class ProviderLimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_request_holds_slot_until_stream_finishes(self) -> None:
        raw = _StreamingProvider()
        provider = LimitedProvider(raw, max_concurrent_requests=1)

        async def consume() -> list[str]:
            chunks: list[str] = []
            async for chunk in provider.chat_stream([{"role": "user", "content": "hello"}]):
                chunks.append(chunk.type)
            return chunks

        first = asyncio.create_task(consume())
        await raw.started.wait()
        self.assertEqual(raw.calls, 1)

        second = asyncio.create_task(consume())
        await asyncio.sleep(0.02)
        self.assertEqual(raw.calls, 1)
        self.assertEqual(raw.max_active, 1)

        raw.release.set()
        self.assertEqual(await first, ["text", "done"])
        self.assertEqual(await second, ["text", "done"])
        self.assertEqual(raw.calls, 2)
        self.assertEqual(raw.max_active, 1)


if __name__ == "__main__":
    unittest.main()
