from __future__ import annotations

import unittest

from backend.runtime.message_rendering import build_user_message_for_provider, is_attachment_edit_request
from backend.sessions.models import SessionMessage


class MessageRenderingTests(unittest.TestCase):
    def test_detects_attachment_edit_request(self) -> None:
        self.assertTrue(is_attachment_edit_request("把这份表里新增一行，并回写文件"))
        self.assertFalse(is_attachment_edit_request("总结一下这个附件讲了什么"))

    def test_renders_runtime_context_for_plain_user_message(self) -> None:
        message = SessionMessage(
            id="user-ctx-1",
            role="user",
            content="现在几点，今天适合安排会议吗？",
            metadata={
                "original_content": "现在几点，今天适合安排会议吗？",
                "environment_context": {
                    "time": {
                        "server_received_at_utc": "2026-05-27T08:12:31+00:00",
                        "client_timezone": "Asia/Shanghai",
                        "client_local_now": "2026-05-27T16:12:29+08:00",
                        "clock_skew_seconds": -2,
                    },
                    "location": {
                        "city": "Shanghai",
                        "source": "browser_geolocation",
                        "precision": "city",
                        "captured_at_utc": "2026-05-27T08:00:00+00:00",
                    },
                },
            },
        )

        rendered = build_user_message_for_provider(message)

        self.assertIn("## Runtime Context", rendered)
        self.assertIn("Server received at (UTC): 2026-05-27T08:12:31+00:00", rendered)
        self.assertIn("Client local time: 2026-05-27T16:12:29+08:00 (Asia/Shanghai)", rendered)
        self.assertIn("Client/server clock skew: -2 seconds", rendered)
        self.assertIn("Approximate city: Shanghai (browser_geolocation, city)", rendered)

    def test_attachment_editing_prompt_prefers_skill_over_parse_tool(self) -> None:
        message = SessionMessage(
            id="user-1",
            role="user",
            content="把这份表里新增一行，并回写文件",
            metadata={
                "attachments": [
                    {
                        "attachment_id": "att-1",
                        "filename": "网格员.xlsx",
                        "extension": ".xlsx",
                        "kind": "spreadsheet",
                        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    }
                ],
                "attachment_analysis": {
                    "schema_version": "v1",
                    "status": "completed",
                    "normalized_user_input": "把这份表里新增一行，并回写文件",
                    "attachment_summaries": [
                        {
                            "attachment_id": "att-1",
                            "status": "parsed",
                            "summary": "当前表格已有若干行数据。",
                        }
                    ],
                    "warnings": [],
                },
            },
        )

        rendered = build_user_message_for_provider(message)

        self.assertIn("必须先使用 skill", rendered)
        self.assertIn("不要先把 parse_attachment 当作主路径", rendered)
        self.assertIn("不要把这些解析片段当作已完成任务", rendered)


if __name__ == "__main__":
    unittest.main()
