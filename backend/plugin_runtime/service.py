from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from backend.plugin_runtime.models import LoadedPlugin, PluginLoadError, PluginRecord, SkillDescriptor
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
            enabled = state.get(plugin.manifest.name, plugin.manifest.enabled_by_default)
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

    def enabled_plugins(self) -> list[LoadedPlugin]:
        self.ensure_fresh()
        enabled_names = {item.name for item in self.list_plugins() if item.enabled}
        return [plugin for plugin in self._plugins if plugin.manifest.name in enabled_names]

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

        workspace_matches = [item for item in matches if item.source == "workspace"]
        if len(matches) == 1:
            return matches[0]
        if len(workspace_matches) == 1:
            return workspace_matches[0]
        raise ValueError(f"Skill 名称不唯一：{skill_name}")

    def get_skill_by_path(self, skill_path: Path) -> SkillDescriptor:
        resolved = skill_path.resolve()
        matches = [item for item in self.list_skills() if Path(item.path).resolve() == resolved]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise FileNotFoundError(f"Skill not found: {resolved}")
        raise ValueError(f"Skill 路径不唯一：{resolved}")

    def get_workspace_skill(self, skill_name: str) -> SkillDescriptor:
        workspace_matches = [item for item in self.list_skills() if item.name == skill_name and item.source == "workspace"]
        if len(workspace_matches) == 1:
            return workspace_matches[0]
        if len(workspace_matches) > 1:
            raise ValueError(f"Workspace skill 名称不唯一：{skill_name}")
        if any(item.name == skill_name for item in self.list_skills()):
            raise PermissionError(f"Skill 为只读，不能修改：{skill_name}")
        raise FileNotFoundError(f"Skill not found: {skill_name}")

    def read_skill_content(self, skill: SkillDescriptor) -> str:
        return Path(skill.path).read_text(encoding="utf-8")

    def import_workspace_skill(self, source_dir: Path) -> SkillDescriptor:
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

    def update_workspace_skill(self, skill_name: str, content: str) -> SkillDescriptor:
        skill = self.get_workspace_skill(skill_name)
        skill_path = Path(skill.path)
        skill_path.write_text(content, encoding="utf-8")
        self.reload()
        return self.get_skill_by_path(skill_path)

    def delete_workspace_skill(self, skill_name: str) -> SkillDescriptor:
        skill = self.get_workspace_skill(skill_name)
        skill_dir = Path(skill.path).parent
        shutil.rmtree(skill_dir)
        self.reload()
        return skill

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
            configs.extend(plugin.manifest.mcp_servers)
        return configs

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
                    source="workspace",
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
