from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import resolve_workspace_path


class WriteFileTool(BaseTool):
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.meta = ToolMeta(
            name="write_file",
            description="Create or overwrite a text file inside the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": True},
                },
                "required": ["path", "content"],
            },
            risk_level="high",
            requires_approval=True,
            timeout_seconds=15,
            allowed_paths=[str(self.workspace)],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            target = resolve_workspace_path(self.workspace, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "write", "permission_error", summary=str(exc))

        overwrite = bool(arguments.get("overwrite", True))
        existed_before = target.exists()
        if target.exists() and target.is_dir():
            return ToolExecutionResult(False, self.meta.name, "write", "validation_error", summary="目标路径是目录，不能写入")
        if target.exists() and not overwrite:
            return ToolExecutionResult(False, self.meta.name, "write", "validation_error", summary="目标文件已存在，overwrite=false")

        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(arguments.get("content", ""))
        target.write_text(content, encoding="utf-8")

        preview = content[:2_000]
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="write",
            summary=f"已写入 {target.relative_to(self.workspace)}",
            stdout=preview,
            metadata={
                "path": str(target),
                "bytes": len(content.encode('utf-8')),
                "created": not existed_before,
            },
        )
