from __future__ import annotations

from pathlib import Path

from backend.plugin_runtime.models import LoadedPlugin, PluginRecord, SkillDescriptor
from backend.plugin_runtime.plugin_loader import PluginLoader
from backend.plugin_runtime.plugin_registry import PluginRegistry


class PluginService:
    def __init__(self, plugins_dir: Path, skills_dir: Path, state_path: Path):
        self.plugins_dir = plugins_dir
        self.skills_dir = skills_dir
        self.loader = PluginLoader(plugins_dir)
        self.registry = PluginRegistry(state_path)
        self._plugins: list[LoadedPlugin] = []
        self.reload()

    def reload(self) -> None:
        self._plugins = self.loader.scan()

    def list_plugins(self) -> list[PluginRecord]:
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
        enabled_names = {item.name for item in self.list_plugins() if item.enabled}
        return [plugin for plugin in self._plugins if plugin.manifest.name in enabled_names]

    def list_skills(self) -> list[SkillDescriptor]:
        skills = self._standalone_skills()
        for plugin in self.enabled_plugins():
            skills.extend(plugin.skills)
        return skills

    def write_skills_snapshot(self, snapshot_path: Path) -> None:
        skills = self.list_skills()
        lines = [
            "# Skills Snapshot",
            "",
            "This file is generated from currently enabled plugins and workspace skills.",
            "",
        ]
        if not skills:
            lines.append("- No skills are currently enabled.")
        else:
            for skill in skills:
                label = skill.name if not skill.plugin_name else f"{skill.name} ({skill.plugin_name})"
                summary = f": {skill.summary}" if skill.summary else ""
                lines.append(f"- {label} [{skill.source}]{summary}")
        snapshot_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def hook_messages(self, event: str) -> list[str]:
        messages: list[str] = []
        for plugin in self.enabled_plugins():
            for hook in plugin.manifest.hooks:
                if hook.event == event and hook.message:
                    messages.append(f"{plugin.manifest.name}: {hook.message}")
        return messages

    def mcp_server_configs(self) -> list[dict]:
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
            summary = ""
            for line in skill_file.read_text(encoding="utf-8", errors="replace").splitlines():
                text = line.strip()
                if text and not text.startswith("#"):
                    summary = text[:160]
                    break
            skills.append(
                SkillDescriptor(
                    name=skill_dir.name,
                    source="workspace",
                    path=str(skill_file),
                    summary=summary,
                )
            )
        return skills
