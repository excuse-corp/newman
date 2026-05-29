from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.permission_context import PermissionContext
from backend.tools.registry import ToolRegistry
from backend.tools.snapshot import render_tools_snapshot
from backend.tools.spec_generator import generate_all_tool_specs


class _FakeTool(BaseTool):
    def __init__(self, meta: ToolMeta):
        self.meta = meta

    async def run(self, arguments: dict, session_id: str):
        raise AssertionError("run should not be called in this test")


def _make_test_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        _FakeTool(
            ToolMeta(
                name="read_file",
                description="Read a file",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "offset": {"type": "integer", "description": "Start line"},
                    },
                    "required": ["path"],
                },
                risk_level="low",
                approval_behavior="safe",
                timeout_seconds=10,
                allowed_paths=["/workspace"],
            )
        )
    )
    registry.register(
        _FakeTool(
            ToolMeta(
                name="google_search",
                description="Search Google",
                input_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "Search query"},
                    },
                    "required": ["q"],
                },
                risk_level="medium",
                approval_behavior="safe",
                timeout_seconds=30,
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
    return registry


class ToolSnapshotTests(unittest.TestCase):
    def test_render_snapshot_lists_primary_tools(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            lines = render_tools_snapshot(registry.list_tools(), spec_dir, PermissionContext())
            text = "\n".join(lines)
            self.assertIn("read_file", text)
            self.assertIn("google_search", text)
            self.assertNotIn("grep", text)

    def test_render_snapshot_excludes_denied_tools(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            ctx = PermissionContext(deny_rules={"google_search"})
            lines = render_tools_snapshot(registry.list_tools(), spec_dir, ctx)
            text = "\n".join(lines)
            self.assertIn("read_file", text)
            self.assertNotIn("google_search", text)

    def test_render_snapshot_includes_required_params(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            lines = render_tools_snapshot(registry.list_tools(), spec_dir, PermissionContext())
            text = "\n".join(lines)
            self.assertIn("Required: path", text)
            self.assertIn("Required: q", text)

    def test_render_snapshot_includes_spec_path(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            lines = render_tools_snapshot(registry.list_tools(), spec_dir, PermissionContext())
            text = "\n".join(lines)
            self.assertIn("read_file.md", text)
            self.assertIn("google_search.md", text)


class ToolSpecGeneratorTests(unittest.TestCase):
    def test_generate_all_tool_specs_creates_files(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            result = generate_all_tool_specs(registry.list_tools(), spec_dir)
            self.assertIn("read_file", result)
            self.assertIn("google_search", result)
            self.assertNotIn("grep", result)
            self.assertTrue((spec_dir / "read_file.md").exists())
            self.assertTrue((spec_dir / "google_search.md").exists())

    def test_spec_contains_parameters_table(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            generate_all_tool_specs(registry.list_tools(), spec_dir)
            content = (spec_dir / "read_file.md").read_text()
            self.assertIn("# read_file", content)
            self.assertIn("Read a file", content)
            self.assertIn("| path |", content)
            self.assertIn("| offset |", content)
            self.assertIn("Yes", content)

    def test_spec_contains_path_permissions(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            generate_all_tool_specs(registry.list_tools(), spec_dir)
            content = (spec_dir / "read_file.md").read_text()
            self.assertIn("Path Permissions", content)
            self.assertIn("/workspace", content)

    def test_spec_contains_security_info(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            generate_all_tool_specs(registry.list_tools(), spec_dir)
            content = (spec_dir / "google_search.md").read_text()
            self.assertIn("Risk level: medium", content)
            self.assertIn("Approval: safe", content)

    def test_sync_tool_snapshot_creates_snapshot_and_specs(self) -> None:
        registry = _make_test_registry()
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "specs"
            memory_dir = Path(tmp) / "memory"
            memory_dir.mkdir()
            registry.sync_tool_snapshot(spec_dir, memory_dir, PermissionContext())
            snapshot_path = memory_dir / "TOOLS_SNAPSHOT.md"
            self.assertTrue(snapshot_path.exists())
            content = snapshot_path.read_text()
            self.assertIn("read_file", content)
            self.assertIn("google_search", content)
            self.assertTrue((spec_dir / "read_file.md").exists())


if __name__ == "__main__":
    unittest.main()
