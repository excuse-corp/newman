from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.evolution.models import EvolutionRunRecord


class EvolutionStore:
    def __init__(self, root: Path):
        self.root = root
        self.runs_dir = root / "runs"
        self.snapshots_dir = root / "snapshots"
        self.events_path = root / "events.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def list_runs(self, limit: int = 50) -> list[EvolutionRunRecord]:
        records: list[EvolutionRunRecord] = []
        for path in self.runs_dir.glob("*.json"):
            try:
                records.append(EvolutionRunRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records[: max(limit, 0)]

    def get_run(self, run_id: str) -> EvolutionRunRecord:
        path = self.runs_dir / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Evolution run not found: {run_id}")
        return EvolutionRunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save_run(self, record: EvolutionRunRecord) -> None:
        path = self.runs_dir / f"{record.run_id}.json"
        path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.append_event(
            {
                "run_id": record.run_id,
                "trigger": record.trigger,
                "status": record.status,
                "updated_at": record.updated_at,
                "change_count": len(record.changes),
            }
        )

    def append_event(self, payload: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_file_snapshot(self, run_id: str, target_path: Path) -> tuple[bool, str | None]:
        exists = target_path.exists()
        if not exists:
            return False, None
        digest = hashlib.sha256(str(target_path.resolve()).encode("utf-8")).hexdigest()[:20]
        snapshot_dir = self.snapshots_dir / run_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{digest}.before"
        snapshot_path.write_text(target_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        return True, str(snapshot_path)

