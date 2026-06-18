from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

import yaml

from backend.plugin_runtime.models import (
    LoadedPlugin,
    PluginCLICommandConfig,
    PluginLoadError,
    PluginManifest,
    PluginPreflightCheckResult,
    PluginPreflightReport,
    PluginRecord,
    ResolvedPluginCLICommand,
    SkillDescriptor,
)
from backend.plugin_runtime.plugin_loader import PluginLoader
from backend.plugin_runtime.plugin_registry import PluginRegistry
from backend.plugin_runtime.skill_parser import parse_skill_file


class PluginService:
    def __init__(self, plugins_dir: Path, skills_dir: Path, state_path: Path):
        self.plugins_dir = plugins_dir
        self.skills_dir = skills_dir
        self.loader = PluginLoader(plugins_dir)
        self.registry = PluginRegistry(state_path)
        self._plugins: list[LoadedPlugin] = []
        self._load_errors: list[PluginLoadError] = []
        self._fingerprint = ""
        self.reload()

    def reload(self) -> None:
        self._plugins, self._load_errors = self.loader.scan()
        self._fingerprint = self._compute_fingerprint()

    def ensure_fresh(self) -> None:
        current = self._compute_fingerprint()
        if current != self._fingerprint:
            self.reload()

    def list_plugins(self) -> list[PluginRecord]:
        self.ensure_fresh()
        state = self.registry.load_state()
        items: list[PluginRecord] = []
        for plugin in self._plugins:
            enabled = self._plugin_enabled(plugin, state)
            items.append(
                PluginRecord(
                    name=plugin.manifest.name,
                    version=plugin.manifest.version,
                    description=plugin.manifest.description,
                    enabled=enabled,
                    plugin_path=str(plugin.root_path),
                    skill_count=len(plugin.skills),
                    hook_count=len(plugin.manifest.hooks),
                    mcp_server_count=len(plugin.manifest.mcp_servers),
                    cli_command_count=len(plugin.manifest.commands),
                    preflight=self._build_plugin_preflight(plugin),
                )
            )
        return items

    def list_load_errors(self) -> list[PluginLoadError]:
        self.ensure_fresh()
        return list(self._load_errors)

    def set_enabled(self, plugin_name: str, enabled: bool) -> PluginRecord:
        plugin = next((item for item in self.list_plugins() if item.name == plugin_name), None)
        if plugin is None:
            raise FileNotFoundError(f"Plugin not found: {plugin_name}")
        self.registry.set_enabled(plugin_name, enabled)
        plugin = next((item for item in self.list_plugins() if item.name == plugin_name), None)
        if plugin is None:
            raise FileNotFoundError(f"Plugin not found: {plugin_name}")
        return plugin

    def get_plugin(self, plugin_name: str) -> LoadedPlugin:
        self.ensure_fresh()
        plugin = next((item for item in self._plugins if item.manifest.name == plugin_name), None)
        if plugin is None:
            raise FileNotFoundError(f"Plugin not found: {plugin_name}")
        return plugin

    def plugin_record(self, plugin_name: str) -> PluginRecord:
        plugin = next((item for item in self.list_plugins() if item.name == plugin_name), None)
        if plugin is None:
            raise FileNotFoundError(f"Plugin not found: {plugin_name}")
        return plugin

    def read_plugin_manifest_content(self, plugin_name: str) -> str:
        plugin = self.get_plugin(plugin_name)
        manifest_path = plugin.root_path / "plugin.yaml"
        return manifest_path.read_text(encoding="utf-8")

    def import_plugin(self, source_dir: Path) -> PluginRecord:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        source_dir = source_dir.resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"Plugin directory not found: {source_dir}")
        manifest_path = source_dir / "plugin.yaml"
        if not manifest_path.exists():
            raise ValueError("Plugin 目录缺少 plugin.yaml")

        loader = PluginLoader(source_dir.parent)
        plugins, errors = loader.scan()
        loaded = next((item for item in plugins if item.root_path.resolve() == source_dir), None)
        if loaded is None:
            detail = next((item.message for item in errors if Path(item.plugin_path).resolve() == source_dir), None)
            raise ValueError(detail or "Plugin 清单无效")

        plugin_name = loaded.manifest.name
        if any(item.name == plugin_name for item in self.list_plugins()):
            raise FileExistsError(f"Plugin 已存在：{plugin_name}")

        target_dir = (self.plugins_dir / source_dir.name).resolve()
        if target_dir.exists():
            raise FileExistsError(f"Plugin 目录已存在：{target_dir.name}")
        if source_dir == target_dir:
            raise FileExistsError(f"Plugin 已位于目标目录：{source_dir.name}")

        shutil.copytree(source_dir, target_dir)
        self.reload()
        return self.plugin_record(plugin_name)

    def update_plugin_manifest(self, plugin_name: str, content: str) -> PluginRecord:
        plugin = self.get_plugin(plugin_name)
        manifest = PluginManifest.model_validate(yaml.safe_load(content) or {})
        PluginLoader(self.plugins_dir)._validate_manifest_paths(plugin.root_path, manifest)
        manifest_path = plugin.root_path / "plugin.yaml"
        manifest_path.write_text(content, encoding="utf-8")
        self.reload()
        return self.plugin_record(plugin_name)

    def delete_plugin(self, plugin_name: str) -> PluginRecord:
        record = self.plugin_record(plugin_name)
        plugin = self.get_plugin(plugin_name)
        shutil.rmtree(plugin.root_path)
        self.registry.delete(plugin_name)
        self.reload()
        return record

    def enabled_plugins(self) -> list[LoadedPlugin]:
        self.ensure_fresh()
        state = self.registry.load_state()
        return [plugin for plugin in self._plugins if self._plugin_enabled(plugin, state)]

    def enabled_sandbox_readable_roots(self) -> list[Path]:
        self.ensure_fresh()
        roots: list[Path] = []
        for plugin in self.enabled_plugins():
            roots.extend(self._resolve_plugin_readable_roots(plugin))
        return _dedupe_paths(roots)

    def resolved_sandbox_readable_roots(self, plugin_name: str) -> list[str]:
        plugin = self.get_plugin(plugin_name)
        return [str(path) for path in self._resolve_plugin_readable_roots(plugin)]

    def plugin_preflight(self, plugin_name: str) -> PluginPreflightReport:
        plugin = self.get_plugin(plugin_name)
        return self._build_plugin_preflight(plugin)

    def enabled_cli_commands(self) -> list[ResolvedPluginCLICommand]:
        self.ensure_fresh()
        commands: list[ResolvedPluginCLICommand] = []
        seen_tool_names: set[str] = set()
        for plugin in self.enabled_plugins():
            for command in self._resolve_plugin_cli_commands(plugin):
                if command.tool_name in seen_tool_names:
                    continue
                seen_tool_names.add(command.tool_name)
                commands.append(command)
        return commands

    def list_skills(self) -> list[SkillDescriptor]:
        self.ensure_fresh()
        skills = self._standalone_skills()
        for plugin in self.enabled_plugins():
            skills.extend(plugin.skills)
        return skills

    def get_skill(self, skill_name: str) -> SkillDescriptor:
        matches = [item for item in self.list_skills() if item.name == skill_name]
        if not matches:
            raise FileNotFoundError(f"Skill not found: {skill_name}")

        system_matches = [item for item in matches if item.source == "system"]
        if len(matches) == 1:
            return matches[0]
        if len(system_matches) == 1:
            return system_matches[0]
        raise ValueError(f"Skill 名称不唯一：{skill_name}")

    def get_skill_by_path(self, skill_path: Path) -> SkillDescriptor:
        resolved = skill_path.resolve()
        matches = [item for item in self.list_skills() if Path(item.path).resolve() == resolved]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise FileNotFoundError(f"Skill not found: {resolved}")
        raise ValueError(f"Skill 路径不唯一：{resolved}")

    def get_system_skill(self, skill_name: str) -> SkillDescriptor:
        system_matches = [item for item in self.list_skills() if item.name == skill_name and item.source == "system"]
        if len(system_matches) == 1:
            return system_matches[0]
        if len(system_matches) > 1:
            raise ValueError(f"System skill 名称不唯一：{skill_name}")
        if any(item.name == skill_name for item in self.list_skills()):
            raise PermissionError(f"Skill 为只读，不能修改：{skill_name}")
        raise FileNotFoundError(f"Skill not found: {skill_name}")

    def get_workspace_skill(self, skill_name: str) -> SkillDescriptor:
        return self.get_system_skill(skill_name)

    def read_skill_content(self, skill: SkillDescriptor) -> str:
        return Path(skill.path).read_text(encoding="utf-8")

    def import_system_skill(self, source_dir: Path) -> SkillDescriptor:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        source_dir = source_dir.resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"Skill directory not found: {source_dir}")
        skill_file = source_dir / "SKILL.md"
        if not skill_file.exists():
            raise ValueError("Skill 目录缺少 SKILL.md")

        metadata = parse_skill_file(skill_file, source_dir.name)
        skill_name = str(metadata["name"] or source_dir.name)
        existing_names = {item.name for item in self.list_skills()}
        if skill_name in existing_names:
            raise FileExistsError(f"Skill 已存在：{skill_name}")

        target_dir = (self.skills_dir / source_dir.name).resolve()
        if target_dir.exists():
            raise FileExistsError(f"Skill 目录已存在：{target_dir.name}")
        if source_dir == target_dir:
            raise FileExistsError(f"Skill 已位于工作区：{source_dir.name}")

        shutil.copytree(source_dir, target_dir)
        self.reload()
        return self.get_skill_by_path(target_dir / "SKILL.md")

    def import_workspace_skill(self, source_dir: Path) -> SkillDescriptor:
        return self.import_system_skill(source_dir)

    def update_system_skill(self, skill_name: str, content: str) -> SkillDescriptor:
        skill = self.get_system_skill(skill_name)
        skill_path = Path(skill.path)
        skill_path.write_text(content, encoding="utf-8")
        self.reload()
        return self.get_skill_by_path(skill_path)

    def update_workspace_skill(self, skill_name: str, content: str) -> SkillDescriptor:
        return self.update_system_skill(skill_name, content)

    def delete_system_skill(self, skill_name: str) -> SkillDescriptor:
        skill = self.get_system_skill(skill_name)
        skill_dir = Path(skill.path).parent
        shutil.rmtree(skill_dir)
        self.reload()
        return skill

    def delete_workspace_skill(self, skill_name: str) -> SkillDescriptor:
        return self.delete_system_skill(skill_name)

    def write_skills_snapshot(self, snapshot_path: Path) -> None:
        skills = self.list_skills()
        lines = _render_skills_snapshot(skills)
        snapshot_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def hook_messages(self, event: str) -> list[str]:
        messages: list[str] = []
        for plugin in self.enabled_plugins():
            for hook in plugin.manifest.hooks:
                if hook.event == event and hook.message:
                    messages.append(f"{plugin.manifest.name}: {hook.message}")
        return messages

    def hooks_for(self, event: str) -> list[tuple[LoadedPlugin, object]]:
        self.ensure_fresh()
        hooks: list[tuple[LoadedPlugin, object]] = []
        for plugin in self.enabled_plugins():
            for hook in plugin.manifest.hooks:
                if hook.event == event:
                    hooks.append((plugin, hook))
        return hooks

    def mcp_server_configs(self) -> list[dict]:
        self.ensure_fresh()
        configs: list[dict] = []
        for plugin in self.enabled_plugins():
            configs.extend(
                self._resolve_plugin_mcp_config(plugin, config)
                for config in plugin.manifest.mcp_servers
            )
        return configs

    def _resolve_plugin_mcp_config(self, plugin: LoadedPlugin, config: dict) -> dict:
        payload = dict(config)
        if payload.get("transport") != "stdio":
            return payload

        plugin_root = plugin.root_path.resolve()
        payload["command"] = self._resolve_stdio_path_values(plugin_root, payload.get("command"))
        payload["args"] = self._resolve_stdio_path_values(plugin_root, payload.get("args"))
        env = dict(payload.get("env") or {})
        env.setdefault("NEWMAN_PLUGIN_ROOT", str(plugin_root))
        env.setdefault("NEWMAN_PLUGIN_NAME", plugin.manifest.name)
        payload["env"] = env
        return payload

    def _plugin_enabled(self, plugin: LoadedPlugin, state: dict[str, bool]) -> bool:
        return state.get(plugin.manifest.name, plugin.manifest.enabled_by_default)

    def _resolve_plugin_readable_roots(self, plugin: LoadedPlugin) -> list[Path]:
        sandbox = plugin.manifest.sandbox
        if sandbox is None:
            return []
        roots = [
            self._resolve_plugin_path_spec(plugin.root_path, raw_root)
            for raw_root in sandbox.readable_roots
            if str(raw_root or "").strip()
        ]
        return [path for path in _dedupe_paths(roots) if path.exists()]

    def _resolve_plugin_writable_roots(self, plugin: LoadedPlugin) -> list[Path]:
        sandbox = plugin.manifest.sandbox
        if sandbox is None:
            return []
        roots = [
            self._resolve_plugin_path_spec(plugin.root_path, raw_root)
            for raw_root in sandbox.writable_roots
            if str(raw_root or "").strip()
        ]
        return [path for path in _dedupe_paths(roots) if path.exists()]

    def _resolve_plugin_cli_commands(self, plugin: LoadedPlugin) -> list[ResolvedPluginCLICommand]:
        commands: list[ResolvedPluginCLICommand] = []
        for command in plugin.manifest.commands:
            commands.append(self._resolve_plugin_cli_command(plugin, command))
        return commands

    def _resolve_plugin_cli_command(
        self,
        plugin: LoadedPlugin,
        command: PluginCLICommandConfig,
    ) -> ResolvedPluginCLICommand:
        readable_roots = self._resolve_plugin_readable_roots(plugin)
        writable_roots = self._resolve_plugin_writable_roots(plugin)
        command_sandbox = command.sandbox
        if command_sandbox is not None:
            readable_roots = _dedupe_paths(
                [
                    *readable_roots,
                    *(
                        self._resolve_plugin_path_spec(plugin.root_path, raw_root)
                        for raw_root in command_sandbox.readable_roots
                        if str(raw_root or "").strip()
                    ),
                ]
            )
            writable_roots = _dedupe_paths(
                [
                    *writable_roots,
                    *(
                        self._resolve_plugin_path_spec(plugin.root_path, raw_root)
                        for raw_root in command_sandbox.writable_roots
                        if str(raw_root or "").strip()
                    ),
                ]
            )
        env = {
            key: os.path.expandvars(str(value))
            for key, value in (command.env or {}).items()
            if str(key).strip()
        }
        env.setdefault("NEWMAN_PLUGIN_ROOT", str(plugin.root_path.resolve()))
        env.setdefault("NEWMAN_PLUGIN_NAME", plugin.manifest.name)
        return ResolvedPluginCLICommand(
            plugin_name=plugin.manifest.name,
            plugin_root=str(plugin.root_path.resolve()),
            tool_name=command.tool_name,
            executable=self._resolve_plugin_command_executable(plugin.root_path, command.executable),
            description=command.description,
            default_args=list(command.default_args),
            env=env,
            approval_behavior=command.approval_behavior,
            timeout_seconds=command.timeout_seconds,
            confirmation_flag=command.confirmation_flag,
            confirmation_protocol=command.confirmation_protocol,
            readonly_prefixes=[list(prefix) for prefix in command.readonly_prefixes if prefix],
            allow_stdin=command.allow_stdin,
            readable_roots=[str(path) for path in readable_roots if path.exists()],
            writable_roots=[str(path) for path in writable_roots if path.exists()],
        )

    def _build_plugin_preflight(self, plugin: LoadedPlugin) -> PluginPreflightReport:
        config = plugin.manifest.preflight
        if config is None:
            return PluginPreflightReport()

        checks: list[PluginPreflightCheckResult] = []
        for raw_bin in config.bins:
            binary = str(raw_bin or "").strip()
            if not binary:
                continue
            resolved = shutil.which(binary)
            checks.append(
                PluginPreflightCheckResult(
                    kind="bin",
                    target=binary,
                    resolved=resolved,
                    ok=resolved is not None,
                    message="binary available" if resolved else "binary not found in PATH",
                )
            )

        for raw_path in config.readable_paths:
            target = str(raw_path or "").strip()
            if not target:
                continue
            resolved_path = self._resolve_plugin_path_spec(plugin.root_path, target)
            ok, message = _check_readable_path(resolved_path)
            checks.append(
                PluginPreflightCheckResult(
                    kind="readable_path",
                    target=target,
                    resolved=str(resolved_path),
                    ok=ok,
                    message=message,
                )
            )

        issue_count = sum(1 for check in checks if not check.ok)
        return PluginPreflightReport(ok=issue_count == 0, issue_count=issue_count, checks=checks)

    def _resolve_plugin_path_spec(self, plugin_root: Path, raw_path: str) -> Path:
        expanded = os.path.expandvars(str(raw_path).strip())
        candidate = Path(expanded).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (plugin_root / candidate).resolve()

    def _resolve_plugin_command_executable(self, plugin_root: Path, executable: str) -> str:
        candidate = Path(str(executable).strip()).expanduser()
        if candidate.is_absolute():
            return str(candidate.resolve()) if candidate.exists() else str(candidate)
        if "/" not in str(executable) and "\\" not in str(executable):
            return str(executable)
        resolved = (plugin_root / candidate).resolve()
        return str(resolved) if resolved.exists() else str(executable)

    def _resolve_stdio_path_values(self, plugin_root: Path, value: object) -> object:
        if isinstance(value, list):
            return [self._resolve_stdio_path_values(plugin_root, item) for item in value]
        if not isinstance(value, str) or not value.strip():
            return value
        path = Path(value)
        if path.is_absolute():
            return value
        candidate = (plugin_root / path).resolve()
        if candidate.exists():
            return str(candidate)
        return value

    def _standalone_skills(self) -> list[SkillDescriptor]:
        if not self.skills_dir.exists():
            return []
        skills: list[SkillDescriptor] = []
        for skill_dir in sorted(self.skills_dir.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            metadata = parse_skill_file(skill_file, skill_dir.name)
            skills.append(
                SkillDescriptor(
                    name=str(metadata["name"] or skill_dir.name),
                    source="system",
                    path=str(skill_file),
                    description=str(metadata["description"] or ""),
                    when_to_use=str(metadata["when_to_use"]) if metadata["when_to_use"] else None,
                    summary=str(metadata["description"] or ""),
                )
            )
        return skills

    def _compute_fingerprint(self) -> str:
        parts: list[str] = []
        parts.extend(self._collect_paths(self.plugins_dir))
        parts.extend(self._collect_paths(self.skills_dir))
        return "|".join(parts)

    def _collect_paths(self, root: Path) -> list[str]:
        if not root.exists():
            return [f"{root}:missing"]
        collected: list[str] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            try:
                stat = path.stat()
                collected.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
            except FileNotFoundError:
                continue
        return collected or [f"{root}:empty"]


def _check_readable_path(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "path missing"
    if os.access(path, os.R_OK):
        return True, "path readable"
    return False, "path is not readable"


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        path = raw.resolve()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _render_skills_snapshot(skills: list[SkillDescriptor]) -> list[str]:
    lines = [
        "## Skills",
        "A skill is a set of local instructions stored in a `SKILL.md` file. Below is the list of skills available in this session.",
        "### Available skills",
    ]
    if not skills:
        lines.append("- No skills are currently enabled.")
    else:
        for skill in skills:
            label = skill.name if not skill.plugin_name else f"{skill.name} ({skill.plugin_name})"
            description = skill.description or skill.summary or "No description."
            entry = f"- {label}: {description} (file: {skill.path})"
            if skill.when_to_use:
                entry += f" | when_to_use: {skill.when_to_use}"
            lines.append(entry)

    lines.extend(
        [
            "### How to use skills",
            "- Trigger rules: if the user names a skill, or the task clearly matches a skill description, you must use that skill for this turn.",
            "- Progressive disclosure: do not preload skill bodies. First decide which single skill is most relevant, then read its `SKILL.md` with `read_file`.",
            "- If the skill references sibling files such as `references/`, `templates/`, or `scripts/`, inspect only the files needed for the current task.",
            "- Prefer using existing tools (`read_file`, `list_dir`, `search_files`, `write_file`, `edit_file`, `update_plan`, `terminal`) exactly as the skill instructs.",
            "- Do not read multiple skills up front unless the user explicitly asks for a comparison.",
        ]
    )
    return lines
