from __future__ import annotations

import re
import json
from pathlib import Path

import yaml

from .draft_models import PluginSpec


def normalize_plugin_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    normalized = re.sub(r"[-_]+", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("plugin name cannot be empty")
    return normalized[:64]


def normalize_skill_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    normalized = re.sub(r"[-_]+", "-", normalized).strip("-")
    if not normalized:
        raise ValueError("skill name cannot be empty")
    return normalized[:64]


def build_plugin_package(spec: PluginSpec, destination: Path) -> Path:
    plugin_name = normalize_plugin_name(spec.name)
    root = destination / plugin_name
    if root.exists():
        raise FileExistsError(f"plugin package already exists: {root}")
    root.mkdir(parents=True, exist_ok=False)

    skill_refs: list[dict[str, str]] = []
    seen_skills: set[str] = set()
    for skill in spec.skills:
        skill_name = normalize_skill_name(skill.name)
        if skill_name in seen_skills:
            raise ValueError(f"duplicate skill name: {skill_name}")
        seen_skills.add(skill_name)
        skill_dir = root / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=False)
        skill_content = (
            "---\n"
            f"name: {skill_name}\n"
            f"description: {json.dumps(skill.description, ensure_ascii=False)}\n"
            f"when_to_use: {json.dumps(skill.when_to_use, ensure_ascii=False)}\n"
            "---\n\n"
            f"{skill.body_markdown.rstrip()}\n"
        )
        (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")
        skill_refs.append({"name": skill_name, "path": f"skills/{skill_name}/SKILL.md"})

    commands: list[dict] = []
    seen_tools: set[str] = set()
    for command in spec.commands:
        if command.tool_name in seen_tools:
            raise ValueError(f"duplicate tool name: {command.tool_name}")
        seen_tools.add(command.tool_name)
        payload = command.model_dump(exclude_none=True)
        payload["env"] = {
            key: value if value.startswith("${") and value.endswith("}") else f"${{{value}}}"
            for key, value in command.env.items()
        }
        payload["sandbox"] = {
            "readable_roots": list(command.readable_roots),
            "writable_roots": list(command.writable_roots),
        }
        payload.pop("readable_roots", None)
        payload.pop("writable_roots", None)
        commands.append(payload)

    manifest = {
        "name": plugin_name,
        "version": spec.version,
        "description": spec.description,
        "enabled_by_default": False,
        "skills": skill_refs,
        "hooks": [],
        "mcp_servers": [],
        "required_permissions": [],
        "commands": commands,
    }
    (root / "plugin.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root
