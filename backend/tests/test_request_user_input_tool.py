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

