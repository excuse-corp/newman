from __future__ import annotations

import json
from time import time
from typing import Any, AsyncIterator


def build_event_payload(
    event: str,
    data: dict[str, Any],
    request_id: str | None = None,
    *,
    ts: int | None = None,
) -> dict[str, Any]:
    payload = {
        "event": event,
        "data": data,
        "ts": ts if ts is not None else int(time() * 1000),
    }
    if request_id:
        payload["request_id"] = request_id
    return payload


def format_sse_payload(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def format_sse(event: str, data: dict[str, Any], request_id: str | None = None) -> bytes:
    return format_sse_payload(build_event_payload(event, data, request_id=request_id))


async def yield_event(event: str, data: dict[str, Any], request_id: str | None = None) -> AsyncIterator[bytes]:
    yield format_sse(event, data, request_id=request_id)
