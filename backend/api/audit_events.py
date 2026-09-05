from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


COMPACT_TEXT_LIMIT = 12_000
TAIL_BLOCK_SIZE = 64 * 1024


def read_audit_lines(audit_path: Path, *, limit: int | None = None) -> list[str]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than 0")
    if not audit_path.exists():
        return []
    if limit is None:
        with audit_path.open("r", encoding="utf-8") as handle:
            return [line.rstrip("\n") for line in handle]
    return _read_tail_lines(audit_path, limit)


def read_audit_events(
    audit_path: Path,
    *,
    limit: int | None = None,
    compact: bool = False,
) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than 0")
    if not audit_path.exists():
        return []

    if compact:
        events = _compact_audit_payloads(_iter_audit_payloads(audit_path))
        return events[-limit:] if limit is not None else events

    return list(_iter_audit_payloads(audit_path, limit=limit))


def _iter_audit_payloads(audit_path: Path, *, limit: int | None = None) -> Iterable[dict[str, Any]]:
    if limit is None:
        with audit_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                payload = _parse_audit_line(line)
                if payload is not None:
                    yield payload
        return

    for line in _read_tail_lines(audit_path, limit):
        payload = _parse_audit_line(line)
        if payload is not None:
            yield payload


def _read_tail_lines(audit_path: Path, limit: int) -> list[str]:
    chunks: list[bytes] = []
    newline_count = 0
    with audit_path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        while position > 0 and newline_count <= limit:
            read_size = min(TAIL_BLOCK_SIZE, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")

    if not chunks:
        return []
    text = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    return text.splitlines()[-limit:]


def _parse_audit_line(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "event" not in payload or "data" not in payload:
        return None
    if not isinstance(payload.get("event"), str) or not isinstance(payload.get("data"), dict):
        return None
    if not isinstance(payload.get("ts"), (int, float)):
        payload["ts"] = 0
    return payload


def _compact_audit_payloads(payloads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    thinking: _ThinkingAccumulator | None = None

    def flush_thinking() -> None:
        nonlocal thinking
        if thinking is None:
            return
        compacted.append(thinking.to_event())
        thinking = None

    for payload in payloads:
        event = payload.get("event")
        if event in {"thinking_delta", "thinking_complete"}:
            key = _thinking_key(payload)
            if thinking is None or thinking.key != key:
                flush_thinking()
                thinking = _ThinkingAccumulator.from_payload(payload)
            thinking.add(payload)
            continue

        flush_thinking()
        compacted_payload = _compact_regular_payload(payload)
        if compacted_payload is not None:
            compacted.append(compacted_payload)

    flush_thinking()
    return compacted


def _thinking_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return (
        str(payload.get("request_id") or data.get("request_id") or ""),
        str(data.get("turn_id") or ""),
        str(data.get("group_id") or ""),
    )


def _compact_regular_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    event = payload.get("event")
    data = dict(payload.get("data") if isinstance(payload.get("data"), dict) else {})

    if event == "assistant_delta" and data.get("reset") is not True:
        return None

    for key in ("content", "delta", "message", "summary", "output"):
        value = data.get(key)
        if isinstance(value, str):
            data[key], truncated = _truncate_text(value, COMPACT_TEXT_LIMIT)
            if truncated:
                data[f"{key}_truncated"] = True
                data[f"{key}_length"] = len(value)

    return _clone_payload(payload, event=str(event), data=data)


def _clone_payload(payload: dict[str, Any], *, event: str, data: dict[str, Any]) -> dict[str, Any]:
    next_payload: dict[str, Any] = {
        "event": event,
        "data": data,
        "ts": payload.get("ts", 0),
    }
    request_id = payload.get("request_id")
    if isinstance(request_id, str) and request_id:
        next_payload["request_id"] = request_id
    return next_payload


def _truncate_text(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = f"\n\n[content truncated: {len(text) - limit} chars omitted]\n\n"
    head_len = min(2_000, max(0, limit // 4))
    tail_len = max(0, limit - head_len - len(marker))
    if tail_len <= 0:
        return text[:limit], True
    return f"{text[:head_len]}{marker}{text[-tail_len:]}", True


class _ThinkingAccumulator:
    def __init__(self, payload: dict[str, Any]) -> None:
        data = dict(payload.get("data") if isinstance(payload.get("data"), dict) else {})
        data.pop("content", None)
        data.pop("delta", None)
        self.key = _thinking_key(payload)
        self.data = data
        self.request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else None
        self.ts = payload.get("ts", 0)
        self.completed = False
        self.content = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "_ThinkingAccumulator":
        return cls(payload)

    def add(self, payload: dict[str, Any]) -> None:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if isinstance(payload.get("ts"), (int, float)):
            self.ts = payload["ts"]
        delta = data.get("delta")
        content = data.get("content")
        if isinstance(delta, str) and delta:
            self.content += delta
        elif isinstance(content, str):
            if content.startswith(self.content):
                self.content += content[len(self.content) :]
            else:
                self.content = content
        if payload.get("event") == "thinking_complete":
            self.completed = True
            if isinstance(content, str) and len(content) >= len(self.content):
                self.content = content

    def to_event(self) -> dict[str, Any]:
        content, truncated = _truncate_text(self.content, COMPACT_TEXT_LIMIT)
        data = {
            **self.data,
            "content": content,
            "content_length": len(self.content),
        }
        if truncated:
            data["content_truncated"] = True
        event = "thinking_complete" if self.completed else "thinking_delta"
        payload: dict[str, Any] = {"event": event, "data": data, "ts": self.ts}
        if self.request_id:
            payload["request_id"] = self.request_id
        return payload
