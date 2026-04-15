from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.memory.stable_context import StableContextLoader
from backend.runtime.prompt_assembler import COMMENTARY_SYSTEM_GUARDRAIL, PromptAssembler
from backend.sessions.models import SessionMessage, SessionRecord


class PromptAssemblerTests(unittest.TestCase):
    def test_prepends_commentary_guardrail_before_stable_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir), "/tmp/workspace")

            session = SessionRecord(session_id="session-1", title="Prompt Test", messages=[])

            assembled = assembler.assemble(session, "tools", "approval", None)

            self.assertEqual(assembled[0]["role"], "system")
            self.assertTrue(assembled[0]["content"].startswith(COMMENTARY_SYSTEM_GUARDRAIL))
            self.assertIn("# Newman", assembled[0]["content"])

    def test_preserves_tool_call_protocol_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir), "/tmp/workspace")

            session = SessionRecord(
                session_id="session-1",
                title="Protocol Test",
                messages=[
                    SessionMessage(id="u1", role="user", content="帮我看下这个网页"),
                    SessionMessage(
                        id="a1",
                        role="assistant",
                        content="我先抓取页面内容。",
                        metadata={
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "name": "fetch_url",
                                    "arguments": {"url": "https://example.com"},
                                }
                            ]
                        },
                    ),
                    SessionMessage(
                        id="t1",
                        role="tool",
                        content="<html>...</html>",
                        metadata={"tool_call_id": "call_1", "tool": "fetch_url"},
                    ),
                ],
            )

            assembled = assembler.assemble(session, "tools", "approval", None)

            assistant_message = assembled[-2]
            tool_message = assembled[-1]
            self.assertEqual(assistant_message["role"], "assistant")
            self.assertEqual(assistant_message["tool_calls"][0]["id"], "call_1")
            self.assertEqual(assistant_message["tool_calls"][0]["function"]["name"], "fetch_url")
            self.assertIn("https://example.com", assistant_message["tool_calls"][0]["function"]["arguments"])
            self.assertEqual(tool_message["role"], "tool")
            self.assertEqual(tool_message["tool_call_id"], "call_1")


if __name__ == "__main__":
    unittest.main()
