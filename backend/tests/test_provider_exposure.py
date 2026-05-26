from __future__ import annotations

import unittest

from backend.tools.provider_exposure import (
    CORE_TOOL_GROUP,
    DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS,
    EDITING_TOOL_GROUP,
    EXECUTION_TOOL_GROUP,
    KNOWLEDGE_TOOL_GROUP,
    NETWORK_TOOL_GROUP,
    infer_provider_tool_groups,
)


class ProviderExposureTests(unittest.TestCase):
    def test_defaults_to_base_interactive_groups(self) -> None:
        self.assertEqual(infer_provider_tool_groups(""), DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS)

    def test_editing_request_keeps_base_interactive_groups(self) -> None:
        groups = infer_provider_tool_groups("请修改设置页按钮并运行 pytest 确认一下")
        self.assertIn(CORE_TOOL_GROUP, groups)
        self.assertIn(EDITING_TOOL_GROUP, groups)
        self.assertIn(EXECUTION_TOOL_GROUP, groups)

    def test_generation_request_adds_knowledge_when_doc_context_is_present(self) -> None:
        groups = infer_provider_tool_groups("根据文档制作一份架构图给我")
        self.assertIn(CORE_TOOL_GROUP, groups)
        self.assertIn(KNOWLEDGE_TOOL_GROUP, groups)
        self.assertIn(EDITING_TOOL_GROUP, groups)
        self.assertIn(EXECUTION_TOOL_GROUP, groups)

    def test_doc_request_adds_knowledge_group_on_top_of_base_groups(self) -> None:
        groups = infer_provider_tool_groups("根据 PRD 文档和 README 告诉我这个模块做什么")
        self.assertEqual(groups, DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS | {KNOWLEDGE_TOOL_GROUP})

    def test_url_request_adds_network_group_on_top_of_base_groups(self) -> None:
        groups = infer_provider_tool_groups("帮我抓取 https://example.com 这个网页")
        self.assertEqual(groups, DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS | {NETWORK_TOOL_GROUP})

    def test_google_search_request_adds_network_group_on_top_of_base_groups(self) -> None:
        groups = infer_provider_tool_groups("帮我做一个联网 google 搜索工具")
        self.assertEqual(groups, DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS | {NETWORK_TOOL_GROUP})


if __name__ == "__main__":
    unittest.main()
