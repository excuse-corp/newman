from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import resolve_workspace_path


DEFAULT_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024


class ReadFileTool(BaseTool):
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.meta = ToolMeta(
            name="read_file",
            description="Read a text or binary file from the workspace with a size-limited preview.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_PREVIEW_BYTES, "default": DEFAULT_PREVIEW_BYTES},
                },
                "required": ["path"],
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=10,
            allowed_paths=[str(self.workspace)],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            path = resolve_workspace_path(self.workspace, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "read", "permission_error", summary=str(exc))
        if not path.exists():
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="文件不存在")
        if path.is_dir():
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="path 必须是文件")

        requested_bytes = int(arguments.get("max_bytes", DEFAULT_PREVIEW_BYTES))
        preview_bytes = max(1, min(requested_bytes, MAX_PREVIEW_BYTES))
        file_size = path.stat().st_size

        with path.open("rb") as handle:
            preview = handle.read(preview_bytes)

        truncated = file_size > preview_bytes
        if _looks_binary(preview):
            payload = {
                "path": str(path),
                "binary": True,
                "encoding": "base64",
                "preview_base64": base64.b64encode(preview).decode("ascii"),
                "preview_bytes": len(preview),
                "size_bytes": file_size,
                "truncated": truncated,
            }
            summary = f"已读取二进制文件 {path.name} 的前 {len(preview)} 字节"
            if truncated:
                summary += f"（文件总大小 {file_size} 字节，结果已截断）"
            return ToolExecutionResult(
                True,
                self.meta.name,
                "read",
                summary=summary,
                stdout=json.dumps(payload, ensure_ascii=False, indent=2),
                metadata=payload,
            )

        content = preview.decode("utf-8", errors="replace")
        summary = f"已读取文本文件 {path.name}"
        if truncated:
            summary += f"（仅返回前 {preview_bytes} 字节，文件总大小 {file_size} 字节）"
        return ToolExecutionResult(
            True,
            self.meta.name,
            "read",
            summary=summary,
            stdout=content,
            metadata={
                "path": str(path),
                "binary": False,
                "preview_bytes": len(preview),
                "size_bytes": file_size,
                "truncated": truncated,
            },
        )


def _looks_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:4096]
    text_like = sum(byte in b"\t\n\r\f\b" or 32 <= byte <= 126 for byte in sample)
    return (text_like / len(sample)) < 0.7
