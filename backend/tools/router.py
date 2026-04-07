from __future__ import annotations

from pathlib import Path

from backend.config.schema import AppConfig
from backend.tools.base import BaseTool
from backend.tools.registry import ToolRegistry


class ToolRouter:
    def __init__(self, registry: ToolRegistry, settings: AppConfig):
        self.registry = registry
        self.settings = settings

    def route(self, tool_name: str, arguments: dict) -> BaseTool:
        return self.registry.get(tool_name)

    def static_checks(self, tool: BaseTool, arguments: dict) -> list[str]:
        checks: list[str] = []
        if tool.meta.allowed_paths and "path" in arguments:
            raw = Path(arguments["path"])
            path = (self.settings.paths.workspace / raw).resolve() if not raw.is_absolute() else raw.resolve()
            if not any(path.is_relative_to(Path(base).resolve()) for base in tool.meta.allowed_paths):
                checks.append("write_file_outside_workspace")
        return checks
