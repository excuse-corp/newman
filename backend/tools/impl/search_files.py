from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import iter_workspace_files, matches_glob, read_text_file, resolve_workspace_path


class SearchFilesTool(BaseTool):
    def __init__(self, workspace: Path, name: str = "search_files", description: str | None = None):
        self.workspace = workspace.resolve()
        self.meta = ToolMeta(
            name=name,
            description=description or "Search file contents in the workspace and return matching lines.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "glob": {"type": "string"},
                    "regex": {"type": "boolean", "default": False},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "show_hidden": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=15,
            allowed_paths=[str(self.workspace)],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        query = str(arguments["query"])
        try:
            target = resolve_workspace_path(self.workspace, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "search", "permission_error", summary=str(exc))

        if not target.exists():
            return ToolExecutionResult(False, self.meta.name, "search", "validation_error", summary=f"路径不存在: {target}")

        file_glob = arguments.get("glob")
        regex_mode = bool(arguments.get("regex", False))
        case_sensitive = bool(arguments.get("case_sensitive", False))
        max_results = max(1, min(int(arguments.get("max_results", 20)), 100))
        show_hidden = bool(arguments.get("show_hidden", False))

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query if regex_mode else re.escape(query), flags)
        except re.error as exc:
            return ToolExecutionResult(False, self.meta.name, "search", "validation_error", summary=f"正则表达式无效: {exc}")

        results: list[dict[str, Any]] = []
        lines: list[str] = []
        scanned_files = 0
        truncated = False

        for path in iter_workspace_files(target, self.workspace, include_hidden=show_hidden):
            if not matches_glob(path.relative_to(self.workspace), file_glob):
                continue
            text_file = read_text_file(path, max_bytes=200_000)
            if text_file is None:
                continue
            scanned_files += 1
            for line_number, line in enumerate(text_file.content.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                relative = path.relative_to(self.workspace).as_posix()
                lines.append(f"{relative}:{line_number}: {line.strip()}")
                results.append(
                    {
                        "path": str(path),
                        "relative_path": relative,
                        "line_number": line_number,
                        "line": line,
                    }
                )
                if len(results) >= max_results:
                    truncated = True
                    break
            if truncated:
                break

        if not results:
            return ToolExecutionResult(
                success=True,
                tool=self.meta.name,
                action="search",
                summary=f"未在 {target} 下找到匹配内容",
                stdout="[]",
                metadata={"results": [], "scanned_files": scanned_files},
            )

        if truncated:
            lines.append("... (结果已截断)")

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="search",
            summary=f"命中 {len(results)} 条结果，扫描 {scanned_files} 个文件",
            stdout="\n".join(lines)[:20_000],
            metadata={"results": results, "scanned_files": scanned_files, "truncated": truncated},
        )
