from __future__ import annotations

import json
from pathlib import Path

from backend.scheduler.models import SchedulerRunRecord


class SchedulerRunStore:
    def __init__(self, path: Path, *, max_records: int = 500):
        self.path = path
        self.max_records = max_records
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_runs(self, task_id: str | None = None, limit: int | None = None) -> list[SchedulerRunRecord]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = [SchedulerRunRecord.model_validate(item) for item in raw.get("runs", [])]
        if task_id is not None:
            items = [item for item in items if item.task_id == task_id]
        if limit is not None:
            items = items[:limit]
        return items

    def append(self, record: SchedulerRunRecord) -> SchedulerRunRecord:
        records = self.list_runs()
        records.insert(0, record)
        self._save(records[: self.max_records])
        return record

    def _save(self, records: list[SchedulerRunRecord]) -> None:
        payload = {"runs": [record.model_dump(mode="json") for record in records]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
