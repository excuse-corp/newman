from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from backend.api.sse.event_emitter import format_sse_payload


class ChannelEventBroker:
    def __init__(self, *, max_queue_size: int = 256, keepalive_seconds: float = 15.0) -> None:
        self._max_queue_size = max(1, max_queue_size)
        self._keepalive_seconds = max(1.0, keepalive_seconds)
        self._queues: set[asyncio.Queue[bytes]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, payload: dict[str, Any]) -> None:
        frame = format_sse_payload(payload)
        async with self._lock:
            queues = list(self._queues)
        for queue in queues:
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(frame)

    async def stream(self) -> AsyncIterator[bytes]:
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._max_queue_size)
        async with self._lock:
            self._queues.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=self._keepalive_seconds)
                except TimeoutError:
                    yield b": keep-alive\n\n"
        finally:
            async with self._lock:
                self._queues.discard(queue)
