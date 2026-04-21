from __future__ import annotations

import unittest

from backend.tools.provider_exposure import (
    CORE_TOOL_GROUP,
    EDITING_TOOL_GROUP,
    EXECUTION_TOOL_GROUP,
    KNOWLEDGE_TOOL_GROUP,
    NETWORK_TOOL_GROUP,
    infer_provider_tool_groups,
)


class ProviderExposureTests(unittest.TestCase):
    def test_defaults_to_core_group(self) -> None:
        self.assertEqual(infer_provider_tool_groups(""), {CORE_TOOL_GROUP})

    def test_editing_request_enables_editing_and_execution(self) -> None:
        groups = infer_provider_tool_groups("请修改设置页按钮并运行 pytest 确认一下")
        self.assertIn(CORE_TOOL_GROUP, groups)
        self.assertIn(EDITING_TOOL_GROUP, groups)
        self.assertIn(EXECUTION_TOOL_GROUP, groups)

    def test_doc_request_enables_knowledge_group(self) -> None:
        groups = infer_provider_tool_groups("根据 PRD 文档和 README 告诉我这个模块做什么")
        self.assertEqual(groups, {CORE_TOOL_GROUP, KNOWLEDGE_TOOL_GROUP})

    def test_url_request_enables_network_group(self) -> None:
        groups = infer_provider_tool_groups("帮我抓取 https://example.com 这个网页")
        self.assertEqual(groups, {CORE_TOOL_GROUP, NETWORK_TOOL_GROUP})

    def test_google_search_request_enables_network_group(self) -> None:
        groups = infer_provider_tool_groups("帮我做一个联网 google 搜索工具")
        self.assertEqual(groups, {CORE_TOOL_GROUP, NETWORK_TOOL_GROUP})


if __name__ == "__main__":
    unittest.main()
