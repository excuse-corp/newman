from __future__ import annotations

from pathlib import Path

from backend.tools.base import BaseTool
from backend.tools.permission_context import PermissionContext
from backend.tools.snapshot import render_tools_snapshot
from backend.tools.spec_generator import generate_all_tool_specs


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.meta.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def tools_for_provider(
        self,
        permission_context: PermissionContext,
    ) -> list[dict]:
        return [
            tool.to_provider_schema()
            for tool in self._primary_tools()
            if permission_context.can_expose(tool.meta.name)
        ]

    def describe(self) -> str:
        return "\n".join(f"- {tool.meta.name}: {tool.meta.description}" for tool in self._primary_tools())

    def sync_tool_snapshot(
        self,
        spec_dir: Path,
        memory_dir: Path,
        permission_context: PermissionContext,
    ) -> None:
        tools = self._primary_tools()
        generate_all_tool_specs(tools, spec_dir)
        lines = render_tools_snapshot(tools, spec_dir, permission_context)
        snapshot_path = memory_dir / "TOOLS_SNAPSHOT.md"
        snapshot_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _primary_tools(self) -> list[BaseTool]:
        return [tool for tool in self._tools.values() if not tool.meta.alias_of]
