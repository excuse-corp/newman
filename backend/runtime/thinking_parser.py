from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OPEN_THINK_TAG = "<think>"
CLOSE_THINK_TAG = "</think>"
OPEN_COMMENTARY_TAG = "<commentary>"
CLOSE_COMMENTARY_TAG = "</commentary>"

PHASE_TAGS = {
    "thinking": (OPEN_THINK_TAG, CLOSE_THINK_TAG),
    "commentary": (OPEN_COMMENTARY_TAG, CLOSE_COMMENTARY_TAG),
}

PhaseKind = Literal["thinking", "commentary"]
ParseEventKind = Literal["answer", "thinking", "thinking_complete", "commentary", "commentary_complete"]


@dataclass(frozen=True)
class ThinkingParseEvent:
    kind: ParseEventKind
    text: str = ""


class PhaseTagStreamParser:
    def __init__(self) -> None:
        self._buffer = ""
        self._active_phase: PhaseKind | None = None

    def feed(self, chunk: str) -> list[ThinkingParseEvent]:
        if not chunk:
            return []
        self._buffer += chunk
        return self._drain(final=False)

    def flush(self) -> list[ThinkingParseEvent]:
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> list[ThinkingParseEvent]:
        events: list[ThinkingParseEvent] = []

        while self._buffer:
            if self._active_phase:
                _, close_tag = PHASE_TAGS[self._active_phase]
                tag_index = self._buffer.find(close_tag)

                if tag_index != -1:
                    text = self._buffer[:tag_index]
                    if text:
                        events.append(ThinkingParseEvent(kind=self._active_phase, text=text))
                    self._buffer = self._buffer[tag_index + len(close_tag) :]
                    events.append(ThinkingParseEvent(kind=f"{self._active_phase}_complete"))
                    self._active_phase = None
                    continue

                if final:
                    if self._buffer:
                        events.append(ThinkingParseEvent(kind=self._active_phase, text=self._buffer))
                        self._buffer = ""
                    events.append(ThinkingParseEvent(kind=f"{self._active_phase}_complete"))
                    self._active_phase = None
                    break

                partial_length = _partial_tag_prefix_length(self._buffer, close_tag)
                emit_upto = len(self._buffer) - partial_length
                if emit_upto <= 0:
                    break
                text = self._buffer[:emit_upto]
                self._buffer = self._buffer[emit_upto:]
                if text:
                    events.append(ThinkingParseEvent(kind=self._active_phase, text=text))
                continue

            next_phase, tag_index = _find_next_phase_tag(self._buffer)
            if next_phase is not None and tag_index != -1:
                text = self._buffer[:tag_index]
                if text:
                    events.append(ThinkingParseEvent(kind="answer", text=text))
                open_tag, _ = PHASE_TAGS[next_phase]
                self._buffer = self._buffer[tag_index + len(open_tag) :]
                self._active_phase = next_phase
                continue

            if final:
                if self._buffer:
                    events.append(ThinkingParseEvent(kind="answer", text=self._buffer))
                    self._buffer = ""
                break

            partial_length = _partial_tag_prefix_length_for_tags(self._buffer, [open_tag for open_tag, _ in PHASE_TAGS.values()])
            emit_upto = len(self._buffer) - partial_length
            if emit_upto <= 0:
                break
            text = self._buffer[:emit_upto]
            self._buffer = self._buffer[emit_upto:]
            if text:
                events.append(ThinkingParseEvent(kind="answer", text=text))

        return events


def _partial_tag_prefix_length(buffer: str, tag: str) -> int:
    max_length = min(len(buffer), len(tag) - 1)
    for size in range(max_length, 0, -1):
        if buffer.endswith(tag[:size]):
            return size
    return 0


def _partial_tag_prefix_length_for_tags(buffer: str, tags: list[str]) -> int:
    return max((_partial_tag_prefix_length(buffer, tag) for tag in tags), default=0)


def _find_next_phase_tag(buffer: str) -> tuple[PhaseKind | None, int]:
    earliest_phase: PhaseKind | None = None
    earliest_index = -1
    for phase, (open_tag, _) in PHASE_TAGS.items():
        tag_index = buffer.find(open_tag)
        if tag_index == -1:
            continue
        if earliest_index == -1 or tag_index < earliest_index:
            earliest_phase = phase
            earliest_index = tag_index
    return earliest_phase, earliest_index


ThinkTagStreamParser = PhaseTagStreamParser
