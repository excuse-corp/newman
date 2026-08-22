from __future__ import annotations

import hashlib
from pathlib import Path

from .draft_models import (
    PluginDraftCommandReview,
    PluginDraftFileChange,
    PluginDraftReviewReport,
    PluginSpec,
)


def build_plugin_review(plugin_service, spec: PluginSpec, plugin_name: str, package_path: Path | None) -> PluginDraftReviewReport:
    install_target = str((plugin_service.plugins_dir / plugin_name).resolve())
    conflicts: list[str] = []
    existing_path = _existing_plugin_path(plugin_service, plugin_name)
    if existing_path is not None:
        conflicts.append(f"Plugin 已存在：{plugin_name}")
    elif Path(install_target).exists():
        conflicts.append(f"目标目录已存在：{install_target}")

    commands = [
        PluginDraftCommandReview(
            tool_name=command.tool_name,
            executable=command.executable,
            approval_behavior=command.approval_behavior,
            env_keys=sorted(command.env.keys()),
            readable_roots=list(command.readable_roots),
            writable_roots=list(command.writable_roots),
        )
        for command in spec.commands
    ]

    safety_notes = ["安装后插件默认停用，需要用户手动启用。"]
    if spec.commands:
        safety_notes.append("CLI wrapper 会暴露为可调用工具；启用插件前请确认命令路径和默认参数。")
    if any(command.writable_roots for command in spec.commands):
        safety_notes.append("存在可写目录声明，运行时可能修改这些路径下的文件。")
    if any(command.approval_behavior == "confirmable" for command in spec.commands):
        safety_notes.append("存在 confirmable 命令，执行时还会触发运行时确认。")

    required_confirmations = ["approve_draft", "install_disabled"]
    if spec.commands:
        required_confirmations.append("enable_plugin_before_cli_use")

    return PluginDraftReviewReport(
        install_target=install_target,
        conflicts=conflicts,
        skills=[skill.name for skill in spec.skills],
        commands=commands,
        environment=sorted({item.name for item in spec.environment} | {key for command in spec.commands for key in command.env.keys()}),
        file_changes=_file_changes(package_path, existing_path),
        required_confirmations=required_confirmations,
        safety_notes=safety_notes,
    )


def _existing_plugin_path(plugin_service, plugin_name: str) -> Path | None:
    try:
        plugin = plugin_service.get_plugin(plugin_name)
    except FileNotFoundError:
        return None
    return plugin.root_path.resolve()


def _file_changes(package_path: Path | None, existing_path: Path | None) -> list[PluginDraftFileChange]:
    if package_path is None or not package_path.exists():
        return []

    draft_files = _file_map(package_path)
    existing_files = _file_map(existing_path) if existing_path and existing_path.exists() else {}
    changes: list[PluginDraftFileChange] = []

    for path in sorted(set(draft_files) | set(existing_files)):
        draft_file = draft_files.get(path)
        existing_file = existing_files.get(path)
        if draft_file is None:
            changes.append(PluginDraftFileChange(path=path, status="deleted"))
            continue
        draft_hash = _sha256(draft_file)
        if existing_file is None:
            status = "added"
        else:
            status = "unchanged" if draft_hash == _sha256(existing_file) else "modified"
        changes.append(
            PluginDraftFileChange(
                path=path,
                status=status,
                size_bytes=draft_file.stat().st_size,
                sha256=draft_hash,
            )
        )
    return changes


def _file_map(root: Path | None) -> dict[str, Path]:
    if root is None or not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
