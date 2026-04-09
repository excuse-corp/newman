from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from backend.scheduler.models import utc_now


class SchedulerAlert(BaseModel):
    alert_id: str
    task_id: str
    task_name: str
    severity: str = "error"
    message: str
    created_at: str = Field(default_factory=utc_now)
    acknowledged: bool = False


class SchedulerAlertStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_alerts(self) -> list[SchedulerAlert]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [SchedulerAlert.model_validate(item) for item in raw.get("alerts", [])]

    def save_alerts(self, alerts: list[SchedulerAlert]) -> None:
        payload = {"alerts": [alert.model_dump(mode="json") for alert in alerts]}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append(self, alert: SchedulerAlert) -> SchedulerAlert:
        alerts = self.list_alerts()
        alerts.insert(0, alert)
        self.save_alerts(alerts[:200])
        return alert

