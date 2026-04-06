from __future__ import annotations

import json
from time import time
from typing import Any, AsyncIterator


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = {
        "event": event,
        "data": data,
        "ts": int(time() * 1000),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


async def yield_event(event: str, data: dict[str, Any]) -> AsyncIterator[bytes]:
    yield format_sse(event, data)
