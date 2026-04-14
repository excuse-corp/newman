from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    coerce_path_access_policy,
    ensure_readable_path,
    should_skip_path,
)


class ListDirectoryTool(BaseTool):
    def __init__(self, policy_or_workspace: PathAccessPolicy | Path, name: str = "list_dir", description: str | None = None):
        self.policy = coerce_path_access_policy(policy_or_workspace)
        self.workspace = self.policy.workspace
        self.meta = ToolMeta(
            name=name,
            description=description or "List files and directories inside the workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "recursive": {"type": "boolean", "default": False},
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 2},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 400, "default": 120},
                    "show_hidden": {"type": "boolean", "default": False},
                },
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=10,
            allowed_paths=[str(path) for path in self.policy.readable_roots],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            target = ensure_readable_path(self.policy, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "list", "permission_error", summary=str(exc))

        if not target.exists():
            return ToolExecutionResult(False, self.meta.name, "list", "validation_error", summary=f"路径不存在: {target}")
        if target.is_file():
            return ToolExecutionResult(False, self.meta.name, "list", "validation_error", summary="path 必须是目录")

        recursive = bool(arguments.get("recursive", False))
        max_depth = max(1, min(int(arguments.get("max_depth", 2)), 6))
        limit = max(1, min(int(arguments.get("limit", 120)), 400))
        show_hidden = bool(arguments.get("show_hidden", False))

        lines = [f"{target}/"]
        entries: list[dict[str, Any]] = []
        seen = 0
        truncated = False

        def walk(current: Path, depth: int, prefix: str) -> None:
            nonlocal seen, truncated
            if truncated:
                return
            children = [
                child
                for child in sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
                if not should_skip_path(child, self.workspace, show_hidden)
            ]
            for child in children:
                if seen >= limit:
                    truncated = True
                    return
                marker = "/" if child.is_dir() else ""
                lines.append(f"{prefix}{child.name}{marker}")
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "type": "dir" if child.is_dir() else "file",
                        "depth": depth,
                    }
                )
                seen += 1
                if recursive and child.is_dir() and depth < max_depth:
                    walk(child, depth + 1, f"{prefix}  ")

        walk(target, 1, "  ")
        if truncated:
            lines.append("  ... (结果已截断)")

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="list",
            summary=f"已列出 {target} 下的 {len(entries)} 个条目",
            stdout="\n".join(lines)[:20_000],
            metadata={"entries": entries, "truncated": truncated},
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [
        ListDirectoryTool(context.path_policy),
        ListDirectoryTool(
            context.path_policy,
            name="list_files",
            description="Alias of list_dir. List files and directories inside the workspace.",
        ),
    ]
