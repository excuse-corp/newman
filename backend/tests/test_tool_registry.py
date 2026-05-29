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
    def test_provider_schema_has_clean_description(self) -> None:
        tool = _FakeTool(
            ToolMeta(
                name="write_file",
                description="Create a file",
                input_schema={"type": "object"},
                risk_level="high",
                approval_behavior="confirmable",
                timeout_seconds=1,
                allowed_paths=["/workspace", "/workspace/skills"],
            )
        )

        schema = tool.to_provider_schema()

        description = schema["function"]["description"]
        self.assertEqual(description, "Create a file")
        self.assertNotIn("Path access", description)

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

    def test_tools_for_provider_filters_by_alias_and_permission(self) -> None:
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
                )
            )
        )

        schemas = registry.tools_for_provider(PermissionContext())
        names = [item["function"]["name"] for item in schemas]
        self.assertIn("read_file", names)
        self.assertIn("terminal", names)
        self.assertNotIn("grep", names)

        denied = registry.tools_for_provider(PermissionContext(deny_rules={"read_file"}))
        denied_names = [item["function"]["name"] for item in denied]
        self.assertNotIn("read_file", denied_names)
        self.assertIn("terminal", denied_names)


if __name__ == "__main__":
    unittest.main()
