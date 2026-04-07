from __future__ import annotations

from dataclasses import dataclass


TARGET_TOKENS = 512
OVERLAP_TOKENS = 64
MIN_TOKENS = 80


@dataclass(frozen=True)
class RawSegment:
    text: str
    page_number: int | None = None
    location_label: str | None = None
    metadata: dict[str, str | int | float | bool | None] | None = None


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_segments(segments: list[RawSegment]) -> list[RawSegment]:
    chunks: list[RawSegment] = []
    buffer: list[RawSegment] = []
    buffer_tokens = 0

    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        token_count = estimate_tokens(text)
        if buffer and buffer_tokens + token_count > TARGET_TOKENS:
            chunk = _merge(buffer)
            if chunk:
                chunks.append(chunk)
            overlap_text = _take_overlap_text(chunk.text if chunk else "", OVERLAP_TOKENS)
            buffer = []
            buffer_tokens = 0
            if overlap_text:
                buffer.append(
                    RawSegment(
                        text=overlap_text,
                        page_number=chunk.page_number if chunk else segment.page_number,
                        location_label=chunk.location_label if chunk else segment.location_label,
                        metadata=dict(chunk.metadata or {}) if chunk else dict(segment.metadata or {}),
                    )
                )
                buffer_tokens = estimate_tokens(overlap_text)

        buffer.append(segment)
        buffer_tokens += token_count

    chunk = _merge(buffer)
    if chunk:
        chunks.append(chunk)
    return chunks


def _merge(segments: list[RawSegment]) -> RawSegment | None:
    cleaned = [segment for segment in segments if segment.text.strip()]
    if not cleaned:
        return None
    text = "\n\n".join(segment.text.strip() for segment in cleaned).strip()
    if estimate_tokens(text) < MIN_TOKENS and len(cleaned) == 1:
        text = cleaned[0].text.strip()
    first = cleaned[0]
    metadata: dict[str, str | int | float | bool | None] = {}
    for segment in cleaned:
        metadata.update(segment.metadata or {})
    return RawSegment(
        text=text,
        page_number=first.page_number,
        location_label=first.location_label,
        metadata=metadata,
    )


def _take_overlap_text(text: str, target_tokens: int) -> str:
    words = text.split()
    if not words:
        return ""
    token_budget = 0
    collected: list[str] = []
    for word in reversed(words):
        token_budget += estimate_tokens(word + " ")
        collected.append(word)
        if token_budget >= target_tokens:
            break
    return " ".join(reversed(collected)).strip()
