from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta, ToolOutputEmitter
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import EDITING_TOOL_GROUP
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    coerce_path_access_policy,
    display_path,
    ensure_writable_path,
)

HTML_PREVIEW_CHUNK_CHARS = 2_048


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
        return await self._write(arguments, session_id, emit_output=None)

    async def run_streaming(
        self,
        arguments: dict[str, Any],
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        return await self._write(arguments, session_id, emit_output=emit_output)

    async def _write(
        self,
        arguments: dict[str, Any],
        session_id: str,
        *,
        emit_output: ToolOutputEmitter | None,
    ) -> ToolExecutionResult:
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
        if emit_output is not None and _should_stream_html_preview(target, content):
            for index in range(0, len(content), HTML_PREVIEW_CHUNK_CHARS):
                await emit_output("file_content", content[index : index + HTML_PREVIEW_CHUNK_CHARS])
                await asyncio.sleep(0)
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
                **({"content_type": "text/html"} if _is_html_path(target) else {}),
            },
        )


def _is_html_path(path: Path) -> bool:
    return path.suffix.lower() in {".html", ".htm"}


def _looks_like_html(content: str) -> bool:
    stripped = content.lstrip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html") or "<body" in stripped[:2_000]


def _should_stream_html_preview(path: Path, content: object) -> bool:
    return isinstance(content, str) and bool(content) and (_is_html_path(path) or _looks_like_html(content))


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [WriteFileTool(context.path_policy)]
