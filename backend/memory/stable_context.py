from __future__ import annotations

from pathlib import Path

from backend.config.loader import get_settings


MEMORY_FILES = {
    "newman": "Newman.md",
    "user": "USER.md",
    "skills": "SKILLS_SNAPSHOT.md",
}

MEMORY_TEMPLATES = {
    "newman": "newman_template.md",
    "user": "user_template.md",
    "skills": "skills_snapshot_template.md",
}


class StableContextLoader:
    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        settings = get_settings()
        template_dir = settings.paths.workspace / "backend" / "config" / "prompts"
        for key, filename in MEMORY_FILES.items():
            path = self.memory_dir / filename
            if path.exists():
                continue
            template_name = MEMORY_TEMPLATES.get(key)
            source = template_dir / template_name if template_name else None
            if source and source.exists():
                path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                path.write_text(f"# {filename}\n", encoding="utf-8")

    def load(self) -> dict[str, str]:
        return {
            key: (self.memory_dir / filename).read_text(encoding="utf-8")
            for key, filename in MEMORY_FILES.items()
        }

    def build(self, tools_overview: str, approval_policy: str, workspace_path: str) -> str:
        context = self.load()
        return "\n\n".join(
            [
                context["newman"],
                context["user"],
                context["skills"],
                f"## Tooling Overview\n{tools_overview}",
                f"## Approval Policy\n{approval_policy}",
                f"## Workspace\n{workspace_path}",
            ]
        )
