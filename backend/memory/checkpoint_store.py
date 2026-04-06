from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from backend.sessions.models import CheckpointRecord


class CheckpointStore:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir

    def save(self, session_id: str, summary: str, turn_range: list[int]) -> CheckpointRecord:
        record = CheckpointRecord(
            session_id=session_id,
            checkpoint_id=uuid4().hex,
            summary=summary,
            turn_range=turn_range,
        )
        self._path_for(session_id).write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return record

    def get(self, session_id: str) -> CheckpointRecord | None:
        path = self._path_for(session_id)
        if not path.exists():
            return None
        return CheckpointRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def _path_for(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}_checkpoint.json"
