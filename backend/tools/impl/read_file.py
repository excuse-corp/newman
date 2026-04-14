from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    coerce_path_access_policy,
    ensure_readable_path,
)


DEFAULT_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_BYTES = 2 * 1024 * 1024
DEFAULT_TEXT_OFFSET = 1
DEFAULT_TEXT_LIMIT = 200
MAX_TEXT_LIMIT = 2_000
MAX_TEXT_LINE_CHARS = 500


class ReadFileTool(BaseTool):
    def __init__(self, policy_or_workspace: PathAccessPolicy | Path):
        self.policy = coerce_path_access_policy(policy_or_workspace)
        self.workspace = self.policy.workspace
        self.meta = ToolMeta(
            name="read_file",
            description="Read a workspace file. Text files support line-based pagination; binary files return a size-limited preview.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {
                        "type": "integer",
                        "minimum": 1,
                        "default": DEFAULT_TEXT_OFFSET,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TEXT_LIMIT,
                        "default": DEFAULT_TEXT_LIMIT,
                    },
                    "max_bytes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_PREVIEW_BYTES,
                        "default": DEFAULT_PREVIEW_BYTES,
                    },
                },
                "required": ["path"],
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=10,
            allowed_paths=[str(path) for path in self.policy.readable_roots],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            path = ensure_readable_path(self.policy, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "read", "permission_error", summary=str(exc))
        if not path.exists():
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="文件不存在")
        if path.is_dir():
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="path 必须是文件")

        requested_bytes = int(arguments.get("max_bytes", DEFAULT_PREVIEW_BYTES))
        preview_bytes = max(1, min(requested_bytes, MAX_PREVIEW_BYTES))
        file_size = path.stat().st_size
        offset = int(arguments.get("offset", DEFAULT_TEXT_OFFSET))
        limit = min(int(arguments.get("limit", DEFAULT_TEXT_LIMIT)), MAX_TEXT_LIMIT)

        if offset < 1:
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="offset 必须大于 0")
        if limit < 1:
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary="limit 必须大于 0")

        with path.open("rb") as handle:
            preview = handle.read(preview_bytes)

        if _looks_binary(preview):
            truncated = file_size > preview_bytes
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

        return self._read_text_file(path, offset, limit)

    def _read_text_file(self, path: Path, offset: int, limit: int) -> ToolExecutionResult:
        lines: list[str] = []
        line_number = 0
        reached_more = False

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line_number += 1
                if line_number < offset:
                    continue
                if len(lines) >= limit:
                    reached_more = True
                    break
                lines.append(f"L{line_number}: {_truncate_line(raw_line.rstrip('\r\n'))}")

        if line_number == 0:
            return ToolExecutionResult(
                True,
                self.meta.name,
                "read",
                summary=f"已读取空文本文件 {path.name}",
                stdout="",
                metadata={
                    "path": str(path),
                    "binary": False,
                    "offset": offset,
                    "limit": limit,
                    "returned_lines": 0,
                    "truncated": False,
                    "next_offset": None,
                    "line_char_limit": MAX_TEXT_LINE_CHARS,
                },
            )

        if line_number < offset:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "read",
                "validation_error",
                summary="offset 超出文件总行数",
            )

        truncated = reached_more
        next_offset = offset + len(lines) if truncated else None

        start_line = offset
        end_line = offset + len(lines) - 1
        summary = f"已读取文本文件 {path.name} 的第 {start_line}-{end_line} 行"
        if truncated:
            summary += f"（可从第 {next_offset} 行继续读取）"
        return ToolExecutionResult(
            True,
            self.meta.name,
            "read",
            summary=summary,
            stdout="\n".join(lines),
            metadata={
                "path": str(path),
                "binary": False,
                "offset": offset,
                "limit": limit,
                "returned_lines": len(lines),
                "start_line": start_line,
                "end_line": end_line,
                "truncated": truncated,
                "next_offset": next_offset,
                "line_char_limit": MAX_TEXT_LINE_CHARS,
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


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_TEXT_LINE_CHARS:
        return line
    return line[:MAX_TEXT_LINE_CHARS]


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [ReadFileTool(context.path_policy)]
