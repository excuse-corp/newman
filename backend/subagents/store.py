from __future__ import annotations

import json
from pathlib import Path

from backend.sessions.models import utc_now
from backend.subagents.models import MultiAgentRun, MultiAgentRunRecord, SubagentTask


class MultiAgentStore:
    def __init__(self, root: Path):
        self.root = root
        self.runs_dir = root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def save_run(self, run: MultiAgentRun, tasks: list[SubagentTask] | dict[str, SubagentTask] | None = None) -> None:
        existing = self.get_record(run.run_id) if self.run_exists(run.run_id) else None
        task_map = dict(existing.tasks) if existing is not None else {}
        if tasks is not None:
            incoming = tasks.values() if isinstance(tasks, dict) else tasks
            for task in incoming:
                task_map[task.task_id] = task
        record = MultiAgentRunRecord(run=run, tasks=task_map, updated_at=utc_now())
        self._write_record(record)

    def save_task(self, task: SubagentTask) -> None:
        record = self.get_record(task.run_id)
        record.tasks[task.task_id] = task
        record.updated_at = utc_now()
        self._write_record(record)

    def get_run(self, run_id: str) -> MultiAgentRun:
        return self.get_record(run_id).run

    def get_task(self, task_id: str) -> SubagentTask:
        return self.get_task_record(task_id)[1]

    def get_task_record(self, task_id: str) -> tuple[MultiAgentRunRecord, SubagentTask]:
        for record in self.list_records():
            task = record.tasks.get(task_id)
            if task is not None:
                return record, task
        raise FileNotFoundError(f"Subagent task not found: {task_id}")

    def get_record(self, run_id: str) -> MultiAgentRunRecord:
        path = self._path_for(run_id)
        if not path.exists():
            raise FileNotFoundError(f"Multiagent run not found: {run_id}")
        return MultiAgentRunRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_records(
        self,
        *,
        parent_session_id: str | None = None,
        parent_turn_id: str | None = None,
    ) -> list[MultiAgentRunRecord]:
        records: list[MultiAgentRunRecord] = []
        for path in sorted(self.runs_dir.glob("*.json")):
            try:
                record = MultiAgentRunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if parent_session_id is not None and record.run.parent_session_id != parent_session_id:
                continue
            if parent_turn_id is not None and record.run.parent_turn_id != parent_turn_id:
                continue
            records.append(record)
        records.sort(key=lambda item: item.run.started_at, reverse=True)
        return records

    def run_exists(self, run_id: str) -> bool:
        return self._path_for(run_id).exists()

    def delete_run(self, run_id: str) -> None:
        path = self._path_for(run_id)
        if path.exists():
            path.unlink()

    def _write_record(self, record: MultiAgentRunRecord) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(record.run.run_id)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _path_for(self, run_id: str) -> Path:
        safe_run_id = "".join(char for char in run_id if char.isalnum() or char in {"-", "_"})
        if not safe_run_id:
            raise ValueError("run_id is empty")
        return self.runs_dir / f"{safe_run_id}.json"
