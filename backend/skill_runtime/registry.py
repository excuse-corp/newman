from __future__ import annotations

from pathlib import Path

from backend.plugin_runtime.models import SkillDescriptor
from backend.plugin_runtime.service import PluginService


class SkillRegistry:
    def __init__(self, plugin_service: PluginService, memory_dir: Path):
        self.plugin_service = plugin_service
        self.memory_dir = memory_dir

    def list_skills(self) -> list[SkillDescriptor]:
        return self.plugin_service.list_skills()

    def sync_snapshot(self) -> Path:
        snapshot_path = self.memory_dir / "SKILLS_SNAPSHOT.md"
        self.plugin_service.write_skills_snapshot(snapshot_path)
        return snapshot_path
