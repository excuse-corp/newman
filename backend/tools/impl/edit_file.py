from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    coerce_path_access_policy,
    display_path,
    ensure_writable_path,
)


class EditFileTool(BaseTool):
    def __init__(self, policy_or_workspace: PathAccessPolicy | Path):
        self.policy = coerce_path_access_policy(policy_or_workspace)
        self.workspace = self.policy.workspace
        self.meta = ToolMeta(
            name="edit_file",
            description="Edit a text file by applying exact string replacements.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {"type": "string", "minLength": 1},
                                "new_text": {"type": "string"},
                                "replace_all": {"type": "boolean", "default": False},
                            },
                            "required": ["old_text", "new_text"],
                        },
                    },
                },
                "required": ["path", "edits"],
            },
            risk_level="high",
            requires_approval=True,
            timeout_seconds=20,
            allowed_paths=[str(path) for path in self.policy.writable_roots],
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        try:
            target = ensure_writable_path(self.policy, arguments.get("path"))
        except ValueError as exc:
            return ToolExecutionResult(False, self.meta.name, "edit", "permission_error", summary=str(exc))

        if not target.exists():
            return ToolExecutionResult(False, self.meta.name, "edit", "validation_error", summary=f"文件不存在: {target}")
        if target.is_dir():
            return ToolExecutionResult(False, self.meta.name, "edit", "validation_error", summary="path 必须是文件")

        original = target.read_text(encoding="utf-8", errors="replace")
        updated = original
        replacement_count = 0

        for index, edit in enumerate(arguments.get("edits", []), start=1):
            old_text = str(edit.get("old_text", ""))
            new_text = str(edit.get("new_text", ""))
            replace_all = bool(edit.get("replace_all", False))
            if not old_text:
                return ToolExecutionResult(
                    False,
                    self.meta.name,
                    "edit",
                    "validation_error",
                    summary=f"第 {index} 个编辑的 old_text 不能为空",
                )
            matches = updated.count(old_text)
            if matches == 0:
                return ToolExecutionResult(
                    False,
                    self.meta.name,
                    "edit",
                    "validation_error",
                    summary=f"第 {index} 个编辑未找到匹配内容",
                )
            if matches > 1 and not replace_all:
                return ToolExecutionResult(
                    False,
                    self.meta.name,
                    "edit",
                    "validation_error",
                    summary=f"第 {index} 个编辑匹配到 {matches} 处内容，请显式设置 replace_all=true",
                )
            if replace_all:
                updated = updated.replace(old_text, new_text)
                replacement_count += matches
            else:
                updated = updated.replace(old_text, new_text, 1)
                replacement_count += 1

        if updated == original:
            return ToolExecutionResult(
                success=True,
                tool=self.meta.name,
                action="edit",
                summary="文件内容未发生变化",
                stdout="",
                metadata={"path": str(target), "replacements": 0},
            )

        target.write_text(updated, encoding="utf-8")
        diff = "".join(
            unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=str(target),
                tofile=str(target),
                n=2,
            )
        )

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="edit",
            summary=f"已更新 {display_path(self.policy, target)}，共应用 {replacement_count} 处替换",
            stdout=diff[:8_000],
            metadata={"path": str(target), "replacements": replacement_count},
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [EditFileTool(context.path_policy)]
