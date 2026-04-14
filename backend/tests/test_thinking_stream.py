from __future__ import annotations

import unittest

from backend.runtime.thinking_parser import ThinkTagStreamParser


def _collect_runtime_like_events(chunks: list[str]) -> tuple[list[tuple[str, str]], str]:
    parser = ThinkTagStreamParser()
    events: list[tuple[str, str]] = []
    answer_parts: list[str] = []
    thinking_parts: list[str] = []

    def consume(parsed_events) -> None:
        for event in parsed_events:
            if event.kind == "answer" and event.text:
                answer_parts.append(event.text)
                events.append(("assistant_delta", "".join(answer_parts)))
            elif event.kind == "thinking" and event.text:
                thinking_parts.append(event.text)
                events.append(("thinking_delta", "".join(thinking_parts)))
            elif event.kind == "thinking_complete":
                events.append(("thinking_complete", "".join(thinking_parts)))

    for chunk in chunks:
        consume(parser.feed(chunk))
    consume(parser.flush())
    return events, "".join(answer_parts)


class ThinkTagStreamParserTests(unittest.TestCase):
    def test_parser_handles_split_think_tags(self) -> None:
        parser = ThinkTagStreamParser()

        events = []
        events.extend(parser.feed("<th"))
        events.extend(parser.feed("ink>先确认范围"))
        events.extend(parser.feed("</thi"))
        events.extend(parser.feed("nk>然后回答"))
        events.extend(parser.flush())

        self.assertEqual(
            [(event.kind, event.text) for event in events],
            [
                ("thinking", "先确认范围"),
                ("thinking_complete", ""),
                ("answer", "然后回答"),
            ],
        )

    def test_runtime_like_accumulation_keeps_thinking_and_answer_separate(self) -> None:
        events, answer = _collect_runtime_like_events(
            [
                "<think>先看一下上下文",
                "</think>",
                "我来继续处理。",
            ]
        )

        self.assertEqual(
            events,
            [
                ("thinking_delta", "先看一下上下文"),
                ("thinking_complete", "先看一下上下文"),
                ("assistant_delta", "我来继续处理。"),
            ],
        )
        self.assertEqual(answer, "我来继续处理。")


if __name__ == "__main__":
    unittest.main()
