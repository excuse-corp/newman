from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from backend.sessions.models import utc_now
from backend.subagents.models import SubagentTask


@dataclass(frozen=True)
class CancellationRequest:
    scope: Literal["run", "task"]
    requested_at: str
    reason: str
    run_id: str | None = None
    task_id: str | None = None


class CancellationRegistry:
    def __init__(self):
        self._run_requests: dict[str, CancellationRequest] = {}
        self._task_requests: dict[str, CancellationRequest] = {}
        self._lock = Lock()

    def request_run_cancel(self, run_id: str, *, reason: str = "user_requested") -> CancellationRequest:
        with self._lock:
            request = self._run_requests.get(run_id)
            if request is None:
                request = CancellationRequest(
                    scope="run",
                    requested_at=utc_now(),
                    reason=reason,
                    run_id=run_id,
                )
                self._run_requests[run_id] = request
            return request

    def request_task_cancel(self, task_id: str, *, reason: str = "user_requested") -> CancellationRequest:
        with self._lock:
            request = self._task_requests.get(task_id)
            if request is None:
                request = CancellationRequest(
                    scope="task",
                    requested_at=utc_now(),
                    reason=reason,
                    task_id=task_id,
                )
                self._task_requests[task_id] = request
            return request

    def request_for_task(self, task: SubagentTask) -> CancellationRequest | None:
        with self._lock:
            request = self._task_requests.get(task.task_id)
            if request is not None:
                return request
            return self._run_requests.get(task.run_id)

    def clear_task(self, task_id: str) -> None:
        with self._lock:
            self._task_requests.pop(task_id, None)

    def clear_run(self, run_id: str) -> None:
        with self._lock:
            self._run_requests.pop(run_id, None)

