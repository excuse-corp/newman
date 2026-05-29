from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.base import BaseTool


def generate_tool_spec(tool: BaseTool, spec_dir: Path) -> Path:
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"{tool.meta.name}.md"
    lines = _render_tool_spec(tool)
    spec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return spec_path


def _render_tool_spec(tool: BaseTool) -> list[str]:
    lines = [f"# {tool.meta.name}", "", tool.meta.description, ""]

    schema = tool.meta.input_schema
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required", [])) if isinstance(schema, dict) else set()

    if properties and isinstance(properties, dict):
        lines.extend(["## Parameters", ""])
        lines.append("| Name | Type | Required | Description |")
        lines.append("|------|------|----------|-------------|")
        for param_name, param_schema in properties.items():
            if not isinstance(param_schema, dict):
                continue
            param_type = param_schema.get("type", "any")
            param_required = "Yes" if param_name in required else "No"
            param_desc = param_schema.get("description", "")
            enum_values = param_schema.get("enum")
            if isinstance(enum_values, list) and enum_values:
                param_desc = f"{param_desc} (values: {', '.join(str(v) for v in enum_values)})" if param_desc else f"values: {', '.join(str(v) for v in enum_values)}"
            lines.append(f"| {param_name} | {param_type} | {param_required} | {param_desc} |")
        lines.append("")

    allowed_paths = tool.meta.allowed_paths
    if allowed_paths:
        lines.extend(["## Path Permissions", ""])
        lines.append("Accessible paths:")
        for path in allowed_paths:
            lines.append(f"- {path}")
        lines.append("")

    lines.extend([
        "## Security",
        f"- Risk level: {tool.meta.risk_level}",
        f"- Approval: {tool.meta.approval_behavior}",
        f"- Timeout: {tool.meta.timeout_seconds}s",
    ])

    return lines


def generate_all_tool_specs(tools: list[BaseTool], spec_dir: Path) -> dict[str, Path]:
    spec_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for tool in tools:
        if tool.meta.alias_of:
            continue
        path = generate_tool_spec(tool, spec_dir)
        result[tool.meta.name] = path
    return result
