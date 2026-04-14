from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


OPEN_THINK_TAG = "<think>"
CLOSE_THINK_TAG = "</think>"


@dataclass(frozen=True)
class ThinkingParseEvent:
    kind: Literal["answer", "thinking", "thinking_complete"]
    text: str = ""


class ThinkTagStreamParser:
    def __init__(self) -> None:
        self._buffer = ""
        self._in_thinking = False

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
            tag = CLOSE_THINK_TAG if self._in_thinking else OPEN_THINK_TAG
            tag_index = self._buffer.find(tag)

            if tag_index != -1:
                text = self._buffer[:tag_index]
                if text:
                    events.append(ThinkingParseEvent(kind="thinking" if self._in_thinking else "answer", text=text))
                self._buffer = self._buffer[tag_index + len(tag) :]
                if self._in_thinking:
                    events.append(ThinkingParseEvent(kind="thinking_complete"))
                    self._in_thinking = False
                else:
                    self._in_thinking = True
                continue

            if final:
                if self._buffer:
                    events.append(ThinkingParseEvent(kind="thinking" if self._in_thinking else "answer", text=self._buffer))
                    self._buffer = ""
                if self._in_thinking:
                    events.append(ThinkingParseEvent(kind="thinking_complete"))
                    self._in_thinking = False
                break

            partial_length = _partial_tag_prefix_length(self._buffer, tag)
            emit_upto = len(self._buffer) - partial_length
            if emit_upto <= 0:
                break
            text = self._buffer[:emit_upto]
            self._buffer = self._buffer[emit_upto:]
            if text:
                events.append(ThinkingParseEvent(kind="thinking" if self._in_thinking else "answer", text=text))

        return events


def _partial_tag_prefix_length(buffer: str, tag: str) -> int:
    max_length = min(len(buffer), len(tag) - 1)
    for size in range(max_length, 0, -1):
        if buffer.endswith(tag[:size]):
            return size
    return 0
