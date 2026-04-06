from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult


class ReadFileTool(BaseTool):
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.meta = ToolMeta(
            name="read_file",
            description="Read a text file from the workspace.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=10,
            allowed_paths=[str(self.workspace)],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        path = Path(arguments["path"]).resolve()
        if not path.is_relative_to(self.workspace):
            return ToolExecutionResult(False, self.meta.name, "read", "permission_error", summary="路径不在 workspace 内")
        if not path.exists():
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="文件不存在")
        content = path.read_text(encoding="utf-8", errors="replace")
        return ToolExecutionResult(True, self.meta.name, "read", summary=f"已读取 {path.name}", stdout=content[:20_000])
