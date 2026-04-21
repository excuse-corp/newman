from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import CORE_TOOL_GROUP
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    coerce_path_access_policy,
    ensure_readable_path,
)

MAX_INLINE_READ_BYTES = 64 * 1024
MAX_RANGE_LINES = 200
MAX_RANGE_OUTPUT_BYTES = 48 * 1024


class ReadFileTool(BaseTool):
    def __init__(self, policy_or_workspace: PathAccessPolicy | Path):
        self.policy = coerce_path_access_policy(policy_or_workspace)
        self.workspace = self.policy.workspace
        self.meta = ToolMeta(
            name="read_file",
            description=(
                "Read a small workspace file and return the entire contents as base64 in dataBase64. "
                "Use this only when you need the exact complete file bytes. "
                "If the file may be large or you only need part of a text file, use read_file_range instead."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative or absolute file path. Must point to a file, not a directory.",
                    },
                },
                "required": ["path"],
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=10,
            allowed_paths=[str(path) for path in self.policy.readable_roots],
            provider_group=CORE_TOOL_GROUP,
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
        size_bytes = path.stat().st_size
        if size_bytes > MAX_INLINE_READ_BYTES:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "read",
                "validation_error",
                summary=(
                    f"文件过大：read_file 仅用于不超过 {MAX_INLINE_READ_BYTES} 字节的小文件完整读取；"
                    "请改用 read_file_range(path, offset, limit) 分段读取文本内容"
                ),
                metadata={"path": str(path), "size_bytes": size_bytes, "max_inline_bytes": MAX_INLINE_READ_BYTES},
            )

        data = path.read_bytes()
        payload = {
            "dataBase64": base64.b64encode(data).decode("ascii"),
        }
        metadata = {
            "path": str(path),
            "size_bytes": len(data),
        }
        return ToolExecutionResult(
            True,
            self.meta.name,
            "read",
            summary=f"已读取文件 {path.name}（{len(data)} 字节）",
            stdout=json.dumps(payload, ensure_ascii=False, indent=2),
            metadata=metadata,
            persisted_output=_build_full_read_persisted_output(path, size_bytes=len(data)),
        )


class ReadFileRangeTool(BaseTool):
    def __init__(self, policy_or_workspace: PathAccessPolicy | Path):
        self.policy = coerce_path_access_policy(policy_or_workspace)
        self.workspace = self.policy.workspace
        self.meta = ToolMeta(
            name="read_file_range",
            description=(
                "Read up to limit lines from a UTF-8 text file starting at offset (1-based line number). "
                "Use this for large text files or when you only need part of a file. "
                "Do not use it for binary files or when you need the complete raw file bytes; use read_file for that."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative or absolute path to a UTF-8 text file.",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-based starting line number. Use 1 for the first chunk.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_RANGE_LINES,
                        "description": f"Maximum number of lines to return in one call (1-{MAX_RANGE_LINES}).",
                    },
                },
                "required": ["path", "offset", "limit"],
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=15,
            allowed_paths=[str(path) for path in self.policy.readable_roots],
            provider_group=CORE_TOOL_GROUP,
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

        try:
            offset = _coerce_positive_int(arguments.get("offset"), field_name="offset")
            limit = _coerce_positive_int(arguments.get("limit"), field_name="limit")
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary=str(exc))
        if limit > MAX_RANGE_LINES:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "read",
                "validation_error",
                summary=f"limit 不能超过 {MAX_RANGE_LINES} 行",
            )
        if _looks_binary_file(path):
            return ToolExecutionResult(
                False,
                self.meta.name,
                "read",
                "validation_error",
                summary="read_file_range 仅支持 UTF-8 文本文件；二进制文件请改用 read_file",
                metadata={"path": str(path)},
            )

        try:
            chunk = _read_text_range(path, offset=offset, limit=limit)
        except UnicodeDecodeError:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "read",
                "validation_error",
                summary="read_file_range 仅支持 UTF-8 文本文件；其他编码文件请先转换后再读取",
                metadata={"path": str(path)},
            )
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "read", "validation_error", summary=str(exc))

        payload = {
            "path": str(path),
            "startLine": offset,
            "endLine": chunk["end_line"],
            "requestedLimit": limit,
            "returnedLines": chunk["returned_lines"],
            "nextOffset": chunk["next_offset"],
            "eof": chunk["eof"],
            "truncatedBySize": chunk["truncated_by_size"],
            "content": chunk["content"],
        }
        if chunk["returned_lines"] == 0:
            summary = f"文件 {path.name} 在第 {offset} 行之后没有更多内容"
        else:
            summary = f"已读取文件 {path.name} 第 {offset}-{chunk['end_line']} 行（返回 {chunk['returned_lines']} 行）"
            if chunk["next_offset"] is not None:
                summary += f"，如需更多内容请从第 {chunk['next_offset']} 行继续"
        metadata = {
            "path": str(path),
            "start_line": offset,
            "end_line": chunk["end_line"],
            "returned_lines": chunk["returned_lines"],
            "next_offset": chunk["next_offset"],
            "eof": chunk["eof"],
            "truncated_by_size": chunk["truncated_by_size"],
        }
        return ToolExecutionResult(
            True,
            self.meta.name,
            "read",
            summary=summary,
            stdout=json.dumps(payload, ensure_ascii=False, indent=2),
            metadata=metadata,
            persisted_output=_build_range_read_persisted_output(path, chunk),
        )


def _coerce_positive_int(raw_value: Any, *, field_name: str) -> int:
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是正整数") from exc
    if value < 1:
        raise ValueError(f"{field_name} 必须大于等于 1")
    return value


def _build_full_read_persisted_output(path: Path, *, size_bytes: int) -> str:
    return json.dumps(
        {
            "summary": f"Read complete file {path.name}; raw content omitted from persisted history",
            "path": str(path),
            "sizeBytes": size_bytes,
            "contentPersisted": False,
            "mode": "full_base64",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _build_range_read_persisted_output(path: Path, chunk: dict[str, Any]) -> str:
    start_line = chunk["end_line"] - chunk["returned_lines"] + 1 if chunk["returned_lines"] else None
    return json.dumps(
        {
            "summary": f"Read text range from {path.name}; content omitted from persisted history",
            "path": str(path),
            "startLine": start_line,
            "endLine": chunk["end_line"],
            "returnedLines": chunk["returned_lines"],
            "nextOffset": chunk["next_offset"],
            "eof": chunk["eof"],
            "truncatedBySize": chunk["truncated_by_size"],
            "contentPersisted": False,
            "mode": "line_range",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _looks_binary_file(path: Path) -> bool:
    with path.open("rb") as handle:
        return b"\x00" in handle.read(4096)


def _read_text_range(path: Path, *, offset: int, limit: int) -> dict[str, Any]:
    rendered_lines: list[str] = []
    output_bytes = 0
    next_offset: int | None = None
    eof = True
    truncated_by_size = False

    with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number < offset:
                continue
            if len(rendered_lines) >= limit:
                next_offset = line_number
                eof = False
                break

            rendered = f"{line_number}: {line.rstrip('\r\n')}"
            separator_bytes = 1 if rendered_lines else 0
            rendered_bytes = len(rendered.encode("utf-8"))
            if rendered_lines and output_bytes + separator_bytes + rendered_bytes > MAX_RANGE_OUTPUT_BYTES:
                next_offset = line_number
                eof = False
                truncated_by_size = True
                break
            if not rendered_lines and rendered_bytes > MAX_RANGE_OUTPUT_BYTES:
                raise ValueError(
                    f"第 {line_number} 行过长，单次 read_file_range 返回不能超过 {MAX_RANGE_OUTPUT_BYTES} 字节"
                )

            rendered_lines.append(rendered)
            output_bytes += separator_bytes + rendered_bytes

    end_line = offset + len(rendered_lines) - 1 if rendered_lines else None
    return {
        "content": "\n".join(rendered_lines),
        "returned_lines": len(rendered_lines),
        "end_line": end_line,
        "next_offset": next_offset,
        "eof": eof,
        "truncated_by_size": truncated_by_size,
    }


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [ReadFileTool(context.path_policy), ReadFileRangeTool(context.path_policy)]
