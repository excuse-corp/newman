from __future__ import annotations

import json
from pathlib import Path


class ChannelSessionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str) -> str | None:
        return self.load().get(key)

    def set(self, key: str, session_id: str) -> None:
        data = self.load()
        data[key] = session_id
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
