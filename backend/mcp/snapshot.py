from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.mcp.models import MCPResourceSpec, MCPServerConfig, MCPServerStatus, MCPToolSpec


_UNSAFE_PATH_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class MCPServerSnapshotInfo:
    name: str
    transport: str
    enabled: bool
    status: str
    tool_count: int
    resource_count: int
    server_path: Path
    tools_path: Path
    detail: str = ""
    capability_summary: str = ""


def safe_server_snapshot_name(server_name: str) -> str:
    safe_name = _UNSAFE_PATH_SEGMENT.sub("_", server_name.strip()).strip("._")
    return safe_name or "server"


def write_mcp_server_snapshots(
    snapshot_root: Path,
    server: MCPServerConfig,
    status: MCPServerStatus,
    tools: list[MCPToolSpec],
    resources: list[MCPResourceSpec],
) -> MCPServerSnapshotInfo:
    server_dir = snapshot_root / safe_server_snapshot_name(server.name)
    server_dir.mkdir(parents=True, exist_ok=True)
    server_path = server_dir / "SERVER.md"
    tools_path = server_dir / "TOOLS_SNAPSHOT.md"
    server_path.write_text(
        "\n".join(render_mcp_server_snapshot(server, status, tools_path, tools, resources)) + "\n",
        encoding="utf-8",
    )
    tools_path.write_text(
        "\n".join(render_mcp_tools_snapshot(server, status, tools, resources)) + "\n",
        encoding="utf-8",
    )
    return MCPServerSnapshotInfo(
        name=server.name,
        transport=server.transport,
        enabled=status.enabled,
        status=status.status,
        tool_count=status.tool_count,
        resource_count=status.resource_count,
        detail=status.detail,
        server_path=server_path,
        tools_path=tools_path,
        capability_summary=_summarize_tools(tools),
    )


def render_mcp_server_snapshot(
    server: MCPServerConfig,
    status: MCPServerStatus,
    tools_snapshot_path: Path,
    tools: list[MCPToolSpec] | None = None,
    resources: list[MCPResourceSpec] | None = None,
) -> list[str]:
    tool_specs = tools or []
    resource_specs = resources or []
    lines = [
        f"# MCP Server: {server.name}",
        "",
        "## Status",
        f"- Name: `{server.name}`",
        f"- Transport: `{server.transport}`",
        f"- Enabled: `{str(status.enabled).lower()}`",
        f"- Status: `{status.status}`",
        f"- Tools: {status.tool_count}",
        f"- Resources: {status.resource_count}",
        f"- Last checked: `{status.last_checked_at}`",
    ]
    if status.detail:
        lines.append(f"- Detail: {status.detail}")
    lines.extend(["", "## Capabilities"])
    if tool_specs:
        for spec in tool_specs[:10]:
            description = f" - {_truncate(spec.description, 120)}" if spec.description else ""
            lines.append(f"- `{spec.name}`{description}")
        if len(tool_specs) > 10:
            lines.append(f"- ... {len(tool_specs) - 10} more tools in the tool snapshot")
    else:
        lines.append("- No tools are currently available from this server.")
    if resource_specs:
        lines.append("")
        lines.append("## Resources")
        for resource in resource_specs[:10]:
            description = f" - {_truncate(resource.description, 120)}" if resource.description else ""
            lines.append(f"- `{resource.name}`: `{resource.uri}`{description}")
        if len(resource_specs) > 10:
            lines.append(f"- ... {len(resource_specs) - 10} more resources")
    lines.extend(
        [
            "",
            "## Tool Snapshot",
            f"- Path: `{tools_snapshot_path}`",
            "- Read this file before activating an MCP tool from this server.",
            "- Activate one specific MCP tool with `activate_mcp_tool`; after activation its provider schema is exposed in the next model turn.",
        ]
    )
    return lines


def render_mcp_tools_snapshot(
    server: MCPServerConfig,
    status: MCPServerStatus,
    tools: list[MCPToolSpec],
    resources: list[MCPResourceSpec],
) -> list[str]:
    lines = [
        f"# MCP Tool Snapshot: {server.name}",
        "",
        "MCP tools are not exposed to the provider by default.",
        "To use a tool from this server, call `activate_mcp_tool` with this server name and the exact tool name below.",
        "",
        "## Server",
        f"- Name: `{server.name}`",
        f"- Transport: `{server.transport}`",
        f"- Status: `{status.status}`",
    ]
    if status.detail:
        lines.append(f"- Detail: {status.detail}")
    lines.extend(["", "## Tools"])
    if not tools:
        lines.append("- No tools are currently available from this server.")
    for spec in tools:
        required = _required_parameters(spec.input_schema)
        function_name = f"mcp__{server.name}__{spec.name}"
        lines.extend(
            [
                f"### {spec.name}",
                f"- Activation: `activate_mcp_tool` with `server={server.name}` and `tool={spec.name}`",
                f"- Provider tool name after activation: `{function_name}`",
                f"- Description: {spec.description or '(none)'}",
                f"- Risk level: `{spec.risk_level}`",
                f"- Required parameters: {', '.join(required) if required else '(none)'}",
                "- Input schema:",
                "```json",
                _json_dumps(spec.input_schema),
                "```",
                "",
            ]
        )
    lines.extend(["## Resources"])
    if not resources:
        lines.append("- No resources are currently advertised by this server.")
    for resource in resources:
        detail = f" - {resource.description}" if resource.description else ""
        mime_type = f" ({resource.mime_type})" if resource.mime_type else ""
        lines.append(f"- `{resource.name}`{mime_type}: `{resource.uri}`{detail}")
    return lines


def describe_mcp_server_snapshots(snapshots: list[MCPServerSnapshotInfo]) -> str:
    if not snapshots:
        return ""
    lines = []
    for info in snapshots:
        detail = f", detail={info.detail}" if info.detail else ""
        lines.append(
            f"- `{info.name}` ({info.transport}, status={info.status}, tools={info.tool_count}, "
            f"resources={info.resource_count}{detail})"
        )
        if info.capability_summary:
            lines.append(f"  - Capabilities: {info.capability_summary}")
        lines.append(f"  - Server summary: `{info.server_path}`")
        lines.append(f"  - Tool snapshot: `{info.tools_path}`")
    return "\n".join(lines)


def _required_parameters(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [item for item in required if isinstance(item, str)]


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _summarize_tools(tools: list[MCPToolSpec], limit: int = 5) -> str:
    if not tools:
        return ""
    summaries: list[str] = []
    for spec in tools[:limit]:
        item = spec.name
        if spec.description:
            item = f"{item}: {_truncate(spec.description, 80)}"
        summaries.append(item)
    if len(tools) > limit:
        summaries.append(f"+{len(tools) - limit} more")
    return "; ".join(summaries)


def _truncate(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
