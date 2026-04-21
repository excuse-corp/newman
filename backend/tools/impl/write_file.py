from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import EDITING_TOOL_GROUP
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    coerce_path_access_policy,
    display_path,
    ensure_writable_path,
)


class WriteFileTool(BaseTool):
    def __init__(self, policy_or_workspace: PathAccessPolicy | Path):
        self.policy = coerce_path_access_policy(policy_or_workspace)
        self.workspace = self.policy.workspace
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
            timeout_seconds=15,
            approval_behavior="confirmable",
            allowed_paths=[str(path) for path in self.policy.writable_roots],
            provider_group=EDITING_TOOL_GROUP,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        validation_error = self.validate_arguments(arguments)
        if validation_error is not None:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "write",
                "validation_error",
                error_code="invalid_arguments",
                summary=validation_error,
            )

        try:
            target = ensure_writable_path(self.policy, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "write", "permission_error", summary=str(exc))

        overwrite = bool(arguments.get("overwrite", True))
        existed_before = target.exists()
        if target.exists() and target.is_dir():
            return ToolExecutionResult(False, self.meta.name, "write", "validation_error", summary="目标路径是目录，不能写入")
        if target.exists() and not overwrite:
            return ToolExecutionResult(False, self.meta.name, "write", "validation_error", summary="目标文件已存在，overwrite=false")

        target.parent.mkdir(parents=True, exist_ok=True)
        content = arguments["content"]
        target.write_text(content, encoding="utf-8")

        preview = content[:2_000]
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="write",
            summary=f"已写入 {display_path(self.policy, target)}",
            stdout=preview,
            metadata={
                "path": str(target),
                "bytes": len(content.encode('utf-8')),
                "created": not existed_before,
            },
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [WriteFileTool(context.path_policy)]
