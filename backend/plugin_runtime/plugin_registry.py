from __future__ import annotations

import json
from pathlib import Path


class PluginRegistry:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def load_state(self) -> dict[str, bool]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def set_enabled(self, plugin_name: str, enabled: bool) -> None:
        state = self.load_state()
        state[plugin_name] = enabled
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
