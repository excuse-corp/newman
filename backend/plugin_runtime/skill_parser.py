from __future__ import annotations

from pathlib import Path

import yaml


def parse_skill_file(skill_file: Path, fallback_name: str) -> dict[str, str | None]:
    content = skill_file.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _split_frontmatter(content)

    name = fallback_name
    description: str | None = None
    when_to_use: str | None = None

    if frontmatter:
        try:
            payload = yaml.safe_load(frontmatter) or {}
            if isinstance(payload, dict):
                raw_name = payload.get("name")
                raw_description = payload.get("description")
                raw_when = payload.get("when_to_use", payload.get("when-to-use"))
                if isinstance(raw_name, str) and raw_name.strip():
                    name = raw_name.strip()
                if isinstance(raw_description, str) and raw_description.strip():
                    description = raw_description.strip()
                if isinstance(raw_when, str) and raw_when.strip():
                    when_to_use = raw_when.strip()
        except yaml.YAMLError:
            pass

    if not description:
        description = _extract_summary(body)

    return {
        "name": name,
        "description": description,
        "when_to_use": when_to_use,
    }


def _split_frontmatter(content: str) -> tuple[str | None, str]:
    if not content.startswith("---\n"):
        return None, content
    end = content.find("\n---\n", 4)
    if end == -1:
        return None, content
    return content[4:end], content[end + 5 :]


def _extract_summary(body: str) -> str:
    for raw_line in body.splitlines():
        text = raw_line.strip()
        if text and not text.startswith("#"):
            return text[:160]
    return ""
