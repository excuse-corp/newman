from __future__ import annotations

from pathlib import Path

import yaml

from backend.plugin_runtime.models import LoadedPlugin, PluginManifest, SkillDescriptor


class PluginLoader:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir

    def scan(self) -> list[LoadedPlugin]:
        plugins: list[LoadedPlugin] = []
        for path in sorted(self.plugins_dir.iterdir() if self.plugins_dir.exists() else []):
            if not path.is_dir():
                continue
            manifest_path = path / "plugin.yaml"
            if not manifest_path.exists():
                continue
            manifest = PluginManifest.model_validate(
                yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            )
            plugins.append(
                LoadedPlugin(
                    manifest=manifest,
                    root_path=path,
                    skills=self._discover_skills(path, manifest.name),
                )
            )
        return plugins

    def _discover_skills(self, plugin_path: Path, plugin_name: str) -> list[SkillDescriptor]:
        skills_root = plugin_path / "skills"
        if not skills_root.exists():
            return []
        skills: list[SkillDescriptor] = []
        for skill_dir in sorted(skills_root.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            skills.append(
                SkillDescriptor(
                    name=skill_dir.name,
                    source="plugin",
                    plugin_name=plugin_name,
                    path=str(skill_file),
                    summary=self._extract_summary(skill_file),
                )
            )
        return skills

    def _extract_summary(self, skill_file: Path) -> str:
        for line in skill_file.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if text and not text.startswith("#"):
                return text[:160]
        return ""
