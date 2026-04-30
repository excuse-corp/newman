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
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(session_id="session-1", title="Prompt Test", messages=[])

            assembled = assembler.assemble(session, "tools", None)

            self.assertEqual(assembled[0]["role"], "system")
            self.assertTrue(assembled[0]["content"].startswith(COMMENTARY_SYSTEM_GUARDRAIL))
            self.assertIn("# Newman", assembled[0]["content"])
            self.assertIn("当前处于 Default mode", assembled[0]["content"])
            self.assertNotIn("## Approval Policy", assembled[0]["content"])
            self.assertNotIn("## Workspace", assembled[0]["content"])

    def test_preserves_tool_call_protocol_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

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

            assembled = assembler.assemble(session, "tools", None)

            assistant_message = assembled[-2]
            tool_message = assembled[-1]
            self.assertEqual(assistant_message["role"], "assistant")
            self.assertEqual(assistant_message["tool_calls"][0]["id"], "call_1")
            self.assertEqual(assistant_message["tool_calls"][0]["function"]["name"], "fetch_url")
            self.assertIn("https://example.com", assistant_message["tool_calls"][0]["function"]["arguments"])
            self.assertEqual(tool_message["role"], "tool")
            self.assertEqual(tool_message["tool_call_id"], "call_1")

    def test_prefers_transient_tool_override_for_current_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(
                session_id="session-1",
                title="Transient Tool Output Test",
                messages=[
                    SessionMessage(id="u1", role="user", content="读一下 README"),
                    SessionMessage(
                        id="a1",
                        role="assistant",
                        content="我先读取 README。",
                        metadata={
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "name": "read_file",
                                    "arguments": {"path": "README.md"},
                                }
                            ]
                        },
                    ),
                    SessionMessage(
                        id="t1",
                        role="tool",
                        content='{"summary":"Read complete file README.md; raw content omitted from persisted history"}',
                        metadata={"tool_call_id": "call_1", "tool": "read_file"},
                    ),
                ],
            )

            assembled = assembler.assemble(
                session,
                "tools",
                None,
                tool_message_overrides={
                    "call_1": SessionMessage(
                        id="transient-1",
                        role="tool",
                        content='{"dataBase64":"UkVBRE1FCg=="}',
                        metadata={"tool_call_id": "call_1", "tool": "read_file"},
                    )
                },
            )

            tool_message = assembled[-1]
            self.assertEqual(tool_message["role"], "tool")
            self.assertEqual(tool_message["tool_call_id"], "call_1")
            self.assertEqual(tool_message["content"], '{"dataBase64":"UkVBRE1FCg=="}')

    def test_omits_failed_tool_protocol_messages_from_provider_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(
                session_id="session-1",
                title="Failed Tool Replay Test",
                messages=[
                    SessionMessage(id="u1", role="user", content="写一个 html 页面"),
                    SessionMessage(
                        id="a1",
                        role="assistant",
                        content="我来创建页面。",
                        metadata={
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "name": "write_file",
                                    "arguments": {"path": "./index.html"},
                                }
                            ]
                        },
                    ),
                    SessionMessage(
                        id="t1",
                        role="tool",
                        content="缺少必填参数: content",
                        metadata={
                            "tool_call_id": "call_1",
                            "tool": "write_file",
                            "success": False,
                            "category": "validation_error",
                        },
                    ),
                    SessionMessage(
                        id="s1",
                        role="system",
                        content="上一步执行失败了，请修正参数再继续。",
                        metadata={"type": "tool_error_feedback"},
                    ),
                ],
            )

            assembled = assembler.assemble(session, "tools", None)

            assistant_message = assembled[2]
            self.assertEqual(assistant_message["role"], "assistant")
            self.assertNotIn("tool_calls", assistant_message)
            self.assertFalse(any(item["role"] == "tool" for item in assembled))
            self.assertEqual(assembled[-1]["role"], "system")
            self.assertIn("修正参数再继续", assembled[-1]["content"])

    def test_injects_default_mode_guidance_without_rendering_approved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(
                session_id="session-1",
                title="Prompt Test",
                metadata={
                    "approved_plan": {
                        "markdown": "1. 先改后端\n2. 再跑测试",
                        "approved_at": "2026-04-22T00:00:00+00:00",
                    }
                },
            )

            assembled = assembler.assemble(session, "tools", None)

            self.assertEqual(assembled[0]["role"], "system")
            self.assertIn("当前处于 Default mode", assembled[0]["content"])
            self.assertIn("`enter_plan_mode`", assembled[0]["content"])
            self.assertNotIn("## Approved Plan", assembled[0]["content"])
            self.assertNotIn("先改后端", assembled[0]["content"])

    def test_injects_plan_mode_guidance_and_current_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(
                session_id="session-1",
                title="Plan Prompt",
                metadata={
                    "collaboration_mode": {
                        "mode": "plan",
                        "source": "tool",
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                    "plan": {
                        "explanation": "先把任务拆成 checklist，再逐项推进。",
                        "steps": [
                            {"step": "先梳理接口", "status": "in_progress"},
                            {"step": "再改前端", "status": "pending"},
                        ],
                        "current_step": "先梳理接口",
                        "progress": {
                            "total": 2,
                            "completed": 0,
                            "in_progress": 1,
                            "pending": 1,
                            "blocked": 0,
                            "cancelled": 0,
                        },
                        "updated_at": "2026-04-22T00:00:00+00:00",
                    },
                },
            )

            assembled = assembler.assemble(session, "tools", None)

            self.assertEqual(assembled[0]["role"], "system")
            self.assertIn("当前处于 Plan mode", assembled[0]["content"])
            self.assertIn("`update_plan`", assembled[0]["content"])
            self.assertIn("不要调用 `update_plan_draft`", assembled[0]["content"])
            self.assertIn("## Current Checklist", assembled[0]["content"])
            self.assertIn("先梳理接口", assembled[0]["content"])

    def test_merges_checkpoint_summary_into_single_leading_system_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(
                session_id="session-1",
                title="Checkpoint Prompt",
                messages=[SessionMessage(id="u1", role="user", content="hello")],
            )

            checkpoint = type("Checkpoint", (), {"summary": "上轮已经读取过 README"})()
            assembled = assembler.assemble(session, "tools", checkpoint)

            self.assertEqual(len([item for item in assembled if item["role"] == "system"]), 1)
            self.assertIn("## Checkpoint Summary", assembled[0]["content"])
            self.assertIn("上轮已经读取过 README", assembled[0]["content"])

    def test_renders_multimodal_user_message_with_original_and_normalized_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))

            session = SessionRecord(
                session_id="session-1",
                title="Multimodal Prompt",
                messages=[
                    SessionMessage(
                        id="u1",
                        role="user",
                        content="看看这张图",
                        metadata={
                            "original_content": "看看这张图",
                            "attachments": [
                                {
                                    "attachment_id": "att-1",
                                    "kind": "image",
                                    "filename": "demo.png",
                                    "content_type": "image/png",
                                    "path": "/tmp/demo.png",
                                    "summary": "这是一个设置页报错截图",
                                    "analysis_status": "completed",
                                }
                            ],
                            "multimodal_parse": {
                                "schema_version": "v1",
                                "status": "completed",
                                "parser_provider": "openai_compatible",
                                "parser_model": "dummy-mm",
                                "normalized_user_input": "请结合截图解释报错并指出优先排查方向。",
                                "task_intent": "debug_screenshot",
                                "key_facts": ["截图里出现 TypeError"],
                                "ocr_text": ["TypeError: Cannot read properties of undefined"],
                                "uncertainties": ["无法仅凭截图确认是前端还是后端空值"],
                                "attachment_summaries": ["这是一个设置页报错截图"],
                            },
                        },
                    )
                ],
            )

            assembled = assembler.assemble(session, "tools", None)

            user_message = assembled[-1]
            self.assertEqual(user_message["role"], "user")
            self.assertIn("## User Original Request", user_message["content"])
            self.assertIn("看看这张图", user_message["content"])
            self.assertIn("## Uploaded Attachments", user_message["content"])
            self.assertIn("demo.png (image/png)", user_message["content"])
            self.assertIn("## Attachment Context", user_message["content"])
            self.assertIn("不要再说你看不到图片", user_message["content"])
            self.assertIn("禁止为了理解该附件再次调用 search_files、list_dir、read_file、read_file_range", user_message["content"])
            self.assertIn("## Multimodal Parse", user_message["content"])
            self.assertIn("TypeError", user_message["content"])
            self.assertIn("## Normalized User Input", user_message["content"])
            self.assertIn("请结合截图解释报错并指出优先排查方向。", user_message["content"])

    def test_renders_attachment_analysis_for_document_user_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            (memory_dir / "Newman.md").write_text("# Newman\n", encoding="utf-8")
            (memory_dir / "USER.md").write_text("# USER\n", encoding="utf-8")
            (memory_dir / "SKILLS_SNAPSHOT.md").write_text("# Skills\n", encoding="utf-8")
            assembler = PromptAssembler(StableContextLoader(memory_dir))
            parsed_path = memory_dir / "notes.md"
            parsed_path.write_text("# notes.txt\n\n这里是解析后的正文内容。\n\n包含明确的任务、风险和负责人。\n", encoding="utf-8")

            session = SessionRecord(
                session_id="session-1",
                title="Attachment Prompt",
                messages=[
                    SessionMessage(
                        id="u1",
                        role="user",
                        content="总结附件",
                        metadata={
                            "original_content": "总结附件",
                            "attachments": [
                                {
                                    "attachment_id": "att-1",
                                    "kind": "text",
                                    "filename": "notes.txt",
                                    "content_type": "text/plain",
                                    "path": "/tmp/notes.txt",
                                    "summary": "会议纪要包含排期、风险和负责人。",
                                    "analysis_status": "parsed",
                                }
                            ],
                            "attachment_analysis": {
                                "schema_version": "v1",
                                "status": "completed",
                                "normalized_user_input": "请基于已解析附件总结重点。",
                                "attachment_summaries": [
                                    {
                                        "attachment_id": "att-1",
                                        "filename": "notes.txt",
                                        "summary": "会议纪要包含排期、风险和负责人。",
                                        "markdown_path": str(parsed_path),
                                    }
                                ],
                                "warnings": [],
                            },
                        },
                    )
                ],
            )

            assembled = assembler.assemble(session, "tools", None)

            user_message = assembled[-1]
            self.assertEqual(user_message["role"], "user")
            self.assertIn("notes.txt (text/plain)", user_message["content"])
            self.assertIn("会议纪要包含排期、风险和负责人。", user_message["content"])
            self.assertIn("请基于已解析附件总结重点。", user_message["content"])
            self.assertIn("## Parsed Attachment Content", user_message["content"])
            self.assertIn("这里是解析后的正文内容。", user_message["content"])
            self.assertIn(f"parsed_markdown={parsed_path}", user_message["content"])
            self.assertIn("不要把附件文件名当作检索关键词。", user_message["content"])


if __name__ == "__main__":
    unittest.main()
