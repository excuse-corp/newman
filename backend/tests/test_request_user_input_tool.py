from __future__ import annotations

import unittest

from backend.runtime.workflow_state import (
    AWAITING_USER_INPUT_METADATA_KEY,
    TURN_OUTCOME_AWAITING_USER,
    WORKFLOW_STATE_METADATA_KEY,
)
from backend.tools.impl.request_user_input import RequestUserInputTool


class RequestUserInputToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_request_builds_pending_workflow_state(self) -> None:
        tool = RequestUserInputTool()

        result = await tool.run(
            {
                "kind": "confirm",
                "skill_name": "html-ppt",
                "phase": "outline",
                "content": "【PPT 大纲】\n1. 封面",
                "prompt": "这个大纲可以继续吗？",
            },
            session_id="session-1",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.metadata["turn_outcome"], TURN_OUTCOME_AWAITING_USER)
        awaiting = result.metadata[AWAITING_USER_INPUT_METADATA_KEY]
        self.assertIsInstance(awaiting, dict)
        assert isinstance(awaiting, dict)
        self.assertEqual(awaiting["skill_name"], "html-ppt")
        self.assertEqual(awaiting["phase"], "outline")
        self.assertEqual(awaiting["status"], "pending")
        self.assertGreaterEqual(len(awaiting["options"]), 2)

        workflow_state = result.metadata[WORKFLOW_STATE_METADATA_KEY]
        self.assertIsInstance(workflow_state, dict)
        assert isinstance(workflow_state, dict)
        self.assertEqual(workflow_state["status"], "awaiting_user")
        self.assertEqual(workflow_state["phase"], "outline")
        self.assertIn("这个大纲可以继续吗？", result.stdout)

    async def test_choice_request_requires_multiple_options(self) -> None:
        tool = RequestUserInputTool()

        result = await tool.run(
            {
                "kind": "choice",
                "prompt": "请选择配色。",
                "options": [{"label": "暗夜金沙", "value": "dark_gold"}],
            },
            session_id="session-1",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "validation_error")

    async def test_numbered_prompt_is_exposed_as_options(self) -> None:
        tool = RequestUserInputTool()

        result = await tool.run(
            {
                "kind": "free_text",
                "prompt": (
                    "请确认您的具体需求：1. 为所有信息管理部项目添加古勇？ "
                    "2. 只为特定信息管理部项目添加古勇？ "
                    "3. 添加一个新的信息管理部项目，网格员设为古勇？如果是这种情况，请提供项目名称。"
                ),
            },
            session_id="session-1",
        )

        self.assertTrue(result.success)
        awaiting = result.metadata[AWAITING_USER_INPUT_METADATA_KEY]
        self.assertIsInstance(awaiting, dict)
        assert isinstance(awaiting, dict)
        options = awaiting["options"]
        self.assertIsInstance(options, list)
        self.assertEqual(len(options), 3)
        self.assertEqual(options[0]["value"], "option_1")
        self.assertIn("所有信息管理部", options[0]["label"])
        self.assertIn("请提供项目名称", options[2]["description"])
