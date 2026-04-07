from __future__ import annotations

from pathlib import Path

import yaml

from backend.plugin_runtime.models import LoadedPlugin, PluginLoadError, PluginManifest, SkillDescriptor
from backend.plugin_runtime.skill_parser import parse_skill_file


class PluginLoader:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir

    def scan(self) -> tuple[list[LoadedPlugin], list[PluginLoadError]]:
        plugins: list[LoadedPlugin] = []
        errors: list[PluginLoadError] = []
        for path in sorted(self.plugins_dir.iterdir() if self.plugins_dir.exists() else []):
            if not path.is_dir():
                continue
            manifest_path = path / "plugin.yaml"
            if not manifest_path.exists():
                continue
            try:
                manifest = PluginManifest.model_validate(
                    yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                )
                self._validate_manifest_paths(path, manifest)
                plugins.append(
                    LoadedPlugin(
                        manifest=manifest,
                        root_path=path,
                        skills=self._discover_skills(path, manifest.name),
                    )
                )
            except Exception as exc:
                plugin_name = None
                try:
                    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                    if isinstance(raw, dict) and isinstance(raw.get("name"), str):
                        plugin_name = raw["name"]
                except Exception:
                    pass
                errors.append(
                    PluginLoadError(
                        plugin_path=str(path),
                        plugin_name=plugin_name,
                        message=str(exc),
                    )
                )
        return plugins, errors

    def _discover_skills(self, plugin_path: Path, plugin_name: str) -> list[SkillDescriptor]:
        skills_root = plugin_path / "skills"
        if not skills_root.exists():
            return []
        skills: list[SkillDescriptor] = []
        for skill_dir in sorted(skills_root.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            metadata = parse_skill_file(skill_file, skill_dir.name)
            skills.append(
                SkillDescriptor(
                    name=str(metadata["name"] or skill_dir.name),
                    source="plugin",
                    plugin_name=plugin_name,
                    path=str(skill_file),
                    description=str(metadata["description"] or ""),
                    when_to_use=str(metadata["when_to_use"]) if metadata["when_to_use"] else None,
                    summary=str(metadata["description"] or ""),
                )
            )
        return skills

    def _validate_manifest_paths(self, plugin_path: Path, manifest: PluginManifest) -> None:
        for skill in manifest.skills:
            skill_path = (plugin_path / skill.path).resolve()
            if not skill_path.exists():
                raise ValueError(f"Skill path not found: {skill.path}")
        for hook in manifest.hooks:
            if not hook.handler:
                continue
            hook_path = (plugin_path / hook.handler).resolve()
            if not hook_path.exists():
                raise ValueError(f"Hook handler not found: {hook.handler}")
        if manifest.ui and manifest.ui.entry:
            ui_entry = (plugin_path / manifest.ui.entry).resolve()
            if not ui_entry.exists():
                raise ValueError(f"UI entry not found: {manifest.ui.entry}")
