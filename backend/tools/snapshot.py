from __future__ import annotations

from pathlib import Path

from backend.tools.base import BaseTool
from backend.tools.permission_context import PermissionContext


def render_tools_snapshot(
    tools: list[BaseTool],
    spec_dir: Path,
    permission_context: PermissionContext,
    mcp_server_overview: str = "",
) -> list[str]:
    lines = [
        "## Tools",
        "Callable tools are provided via function calling in the current turn.",
        "Use the provider tool definitions as the source of truth for available tool names and parameter schemas.",
        "",
        "### Tool specs",
        "Generated tool spec files contain path permissions, risk level, approval behavior, timeout, and parameter details.",
        f"- Spec path pattern: `{spec_dir / '{tool_name}.md'}`",
        "- Read a spec file only when parameters, path permissions, or risk details are unclear.",
        "",
        "### How to use tools",
        "- Choose only tools present in the current provider tool list.",
        "- Do not invent tool names or call tools that are absent from the current provider tool list.",
    ]
    if mcp_server_overview.strip():
        lines.extend(
            [
                "",
                "## MCP Servers",
                "MCP tools are grouped by server and are not exposed to the provider by default.",
                "Read the server tool snapshot first, then call `activate_mcp_tool` to expose one specific MCP tool schema.",
                "",
                mcp_server_overview.strip(),
            ]
        )
    return lines
