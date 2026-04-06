from __future__ import annotations

import json
from pathlib import Path

from backend.scheduler.models import ScheduledTask, utc_now


class TaskStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> list[ScheduledTask]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [ScheduledTask.model_validate(item) for item in raw.get("tasks", [])]

    def save_tasks(self, tasks: list[ScheduledTask]) -> None:
        payload = {"tasks": [task.model_dump(mode="json") for task in tasks]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, task: ScheduledTask) -> ScheduledTask:
        tasks = [item for item in self.list_tasks() if item.task_id != task.task_id]
        task.updated_at = utc_now()
        tasks.append(task)
        self.save_tasks(tasks)
        return task

    def get(self, task_id: str) -> ScheduledTask:
        for task in self.list_tasks():
            if task.task_id == task_id:
                return task
        raise FileNotFoundError(f"Scheduler task not found: {task_id}")
