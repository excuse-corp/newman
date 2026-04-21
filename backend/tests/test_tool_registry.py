from __future__ import annotations

import unittest

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.permission_context import PermissionContext
from backend.tools.registry import ToolRegistry


class _FakeTool(BaseTool):
    def __init__(self, meta: ToolMeta):
        self.meta = meta

    async def run(self, arguments: dict, session_id: str):
        raise AssertionError("run should not be called in this test")


class ToolRegistryExposureTests(unittest.TestCase):
    def test_describe_omits_alias_tools(self) -> None:
        registry = ToolRegistry()
        registry.register(
            _FakeTool(
                ToolMeta(
                    name="list_dir",
                    description="List files",
                    input_schema={"type": "object"},
                    risk_level="low",
                    approval_behavior="safe",
                    timeout_seconds=1,
                )
            )
        )
        registry.register(
            _FakeTool(
                ToolMeta(
                    name="list_files",
                    description="Alias of list_dir",
                    input_schema={"type": "object"},
                    risk_level="low",
                    approval_behavior="safe",
                    timeout_seconds=1,
                    alias_of="list_dir",
                )
            )
        )

        overview = registry.describe()
        self.assertIn("list_dir", overview)
        self.assertNotIn("list_files", overview)

    def test_tools_for_provider_filters_by_group_alias_and_permission(self) -> None:
        registry = ToolRegistry()
        registry.register(
            _FakeTool(
                ToolMeta(
                    name="read_file",
                    description="Read a file",
                    input_schema={"type": "object"},
                    risk_level="low",
                    approval_behavior="safe",
                    timeout_seconds=1,
                    provider_group="core",
                )
            )
        )
        registry.register(
            _FakeTool(
                ToolMeta(
                    name="grep",
                    description="Alias of search_files",
                    input_schema={"type": "object"},
                    risk_level="low",
                    approval_behavior="safe",
                    timeout_seconds=1,
                    provider_group="core",
                    alias_of="search_files",
                )
            )
        )
        registry.register(
            _FakeTool(
                ToolMeta(
                    name="terminal",
                    description="Run shell",
                    input_schema={"type": "object"},
                    risk_level="high",
                    approval_behavior="confirmable",
                    timeout_seconds=1,
                    provider_group="execution",
                )
            )
        )

        schemas = registry.tools_for_provider(PermissionContext(), active_groups={"core"})
        self.assertEqual([item["function"]["name"] for item in schemas], ["read_file"])

        expanded = registry.tools_for_provider(PermissionContext(), active_groups={"core", "execution"})
        self.assertEqual([item["function"]["name"] for item in expanded], ["read_file", "terminal"])

        denied = registry.tools_for_provider(PermissionContext(deny_rules={"read_file"}), active_groups={"core", "execution"})
        self.assertEqual([item["function"]["name"] for item in denied], ["terminal"])


if __name__ == "__main__":
    unittest.main()
