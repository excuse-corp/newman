from __future__ import annotations

from pathlib import Path

MEMORY_FILES = {
    "newman": "Newman.md",
    "user": "USER.md",
    "memory": "MEMORY.md",
    "skills": "SKILLS_SNAPSHOT.md",
    "tools": "TOOLS_SNAPSHOT.md",
}

MEMORY_TEMPLATES = {
    "newman": "newman_template.md",
    "user": "user_template.md",
    "memory": "memory_template.md",
    "skills": "skills_snapshot_template.md",
    "tools": "tools_snapshot_template.md",
}


class StableContextLoader:
    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "config" / "prompts"
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

    def build(self, tools_overview: str = "") -> str:
        context = self.load()
        sections = [
            context["newman"],
            context["user"],
            context["memory"],
            context["skills"],
            context["tools"],
        ]
        if tools_overview:
            sections.append(f"## Tooling Overview\n{tools_overview}")
        return "\n\n".join(sections)
