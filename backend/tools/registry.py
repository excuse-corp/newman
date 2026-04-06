from __future__ import annotations

from backend.tools.base import BaseTool
from backend.tools.permission_context import PermissionContext


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.meta.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def tools_for_provider(self, permission_context: PermissionContext) -> list[dict]:
        return [tool.to_provider_schema() for tool in self._tools.values() if permission_context.can_expose(tool.meta.name)]

    def describe(self) -> str:
        return "\n".join(f"- {tool.meta.name}: {tool.meta.description}" for tool in self._tools.values())
