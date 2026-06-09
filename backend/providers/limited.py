from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse


class LimitedProvider(BaseProvider):
    def __init__(
        self,
        provider: BaseProvider,
        *,
        max_concurrent_requests: int = 1,
        min_interval_seconds: float = 0.0,
    ):
        self.provider = provider
        self.max_concurrent_requests = max(int(max_concurrent_requests), 1)
        self.min_interval_seconds = max(float(min_interval_seconds), 0.0)
        self._semaphore = asyncio.Semaphore(self.max_concurrent_requests)
        self._interval_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        async with self._semaphore:
            await self._wait_for_request_slot()
            return await self.provider.chat(messages, tools=tools, **kwargs)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProviderChunk]:
        async with self._semaphore:
            await self._wait_for_request_slot()
            async for chunk in self.provider.chat_stream(messages, tools=tools, **kwargs):
                yield chunk

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return self.provider.estimate_tokens(messages)

    async def _wait_for_request_slot(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        async with self._interval_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next_request_at > now:
                await asyncio.sleep(self._next_request_at - now)
                now = loop.time()
            self._next_request_at = now + self.min_interval_seconds

    def __getattr__(self, name: str) -> Any:
        return getattr(self.provider, name)
