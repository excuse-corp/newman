from __future__ import annotations

from pathlib import Path

from backend.tools.base import BaseTool
from backend.tools.permission_context import PermissionContext


def render_tools_snapshot(
    tools: list[BaseTool],
    spec_dir: Path,
    permission_context: PermissionContext,
) -> list[str]:
    lines = [
        "## Tools",
        "All tools are available via function calling. "
        "For full parameter details and path permissions, read the tool's spec file using `read_file`.",
        "",
        "### Available tools",
    ]

    visible_tools = [
        tool for tool in tools
        if not tool.meta.alias_of and permission_context.can_expose(tool.meta.name)
    ]

    if not visible_tools:
        lines.append("- No tools are currently available.")
    else:
        for tool in visible_tools:
            spec_path = spec_dir / f"{tool.meta.name}.md"
            required_params = _extract_required_params(tool)
            entry = f"- `{tool.meta.name}`: {tool.meta.description}"
            if required_params:
                entry += f" | Required: {', '.join(required_params)}"
            entry += f" | spec: {spec_path}"
            lines.append(entry)

    lines.extend([
        "",
        "### How to use tools",
        "- All listed tools are always available. Choose the right tool based on the task.",
        "- Before calling a tool with complex parameters, read its spec file for full details.",
        "- Do not call tools not listed above.",
    ])

    return lines


def _extract_required_params(tool: BaseTool) -> list[str]:
    schema = tool.meta.input_schema
    if not isinstance(schema, dict):
        return []
    required = schema.get("required", [])
    if isinstance(required, list):
        return [str(p) for p in required if isinstance(p, str)]
    return []
