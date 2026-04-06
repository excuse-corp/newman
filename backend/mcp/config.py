from __future__ import annotations

from pathlib import Path

import yaml

from backend.mcp.models import MCPServerConfig


class MCPConfigStore:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[MCPServerConfig]:
        if not self.config_path.exists():
            return []
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        items = raw.get("mcp_servers", [])
        return [MCPServerConfig.model_validate(item) for item in items]

    def save(self, servers: list[MCPServerConfig]) -> None:
        payload = {"mcp_servers": [server.model_dump(mode="json") for server in servers]}
        self.config_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
