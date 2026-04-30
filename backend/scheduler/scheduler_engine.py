from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from backend.api.sse.event_emitter import build_event_payload
from backend.scheduler.alert_store import SchedulerAlert, SchedulerAlertStore
from backend.scheduler.cron_parser import next_run
from backend.scheduler.models import SchedulerRunRecord, ScheduledTask, TaskOutcome, utc_now
from backend.scheduler.run_store import SchedulerRunStore
from backend.scheduler.task_store import TaskStore


EventEmitter = Callable[[str, dict], Awaitable[None]]


@dataclass
class _RunAuditState:
    request_id: str
    session_id: str
    audit_path: Path
    turn_id: str | None = None
    final_finish_reason: str | None = None
    final_content: str = ""


@dataclass
class _TaskExecutionResult:
    outcome: TaskOutcome
    session_id: str | None
    turn_id: str | None
    message: str


class SchedulerEngine:
    def __init__(self, task_store: TaskStore, runtime):
        self.task_store = task_store
        self.runtime = runtime
        scheduler_dir = runtime.settings.paths.scheduler_dir
        self.alert_store = SchedulerAlertStore(scheduler_dir / "alerts.json")
        self.run_store = SchedulerRunStore(scheduler_dir / "runs.json")
        self._worker: asyncio.Task | None = None
        self._running = False
        self._active_task_ids: set[str] = set()
        self._active_session_ids: set[str] = set()
        self._session_busy_checker: Callable[[str], bool] = lambda _session_id: False

    def set_session_busy_checker(self, checker: Callable[[str], bool] | None) -> None:
        self._session_busy_checker = checker or (lambda _session_id: False)

    def is_session_busy(self, session_id: str) -> bool:
        return session_id in self._active_session_ids or self._session_busy_checker(session_id)

    def has_active_scheduler_session(self, session_id: str) -> bool:
        return session_id in self._active_session_ids

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._worker:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    def refresh_schedule(self) -> None:
        now = datetime.now(timezone.utc)
        tasks = [self._normalize_task(task, now, recompute=True) for task in self.task_store.list_tasks()]
        self.task_store.save_tasks(tasks)

    async def run_now(self, task_id: str) -> ScheduledTask:
        task = self._normalize_task(self.task_store.get(task_id), datetime.now(timezone.utc))
        self.task_store.upsert(task)
        return await self._execute(
            task,
            trigger_kind="manual_run",
            scheduled_for=datetime.now(timezone.utc),
        )

    async def _loop(self) -> None:
        while self._running:
            await self._tick()
            await asyncio.sleep(1)

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        for original in self.task_store.list_tasks():
            before = original.model_dump(mode="json")
            task = self._normalize_task(original, now)
            if task.model_dump(mode="json") != before:
                self.task_store.upsert(task)

            next_run_at = self._parse_timestamp(task.next_run_at)
            if not task.enabled or next_run_at is None or next_run_at > now:
                continue

            await self._execute(task, trigger_kind="cron", scheduled_for=next_run_at)

    async def _execute(
        self,
        task: ScheduledTask,
        *,
        trigger_kind: str,
        scheduled_for: datetime,
    ) -> ScheduledTask:
        now = datetime.now(timezone.utc)
        task = self._normalize_task(task, now)

        if task.task_id in self._active_task_ids:
            return self._finalize_non_success(
                task,
                outcome="skipped_conflict",
                trigger_kind=trigger_kind,
                scheduled_for=scheduled_for,
                message="同一定时任务仍在执行中，本次触发已跳过",
                severity="warning",
            )

        session_id = task.action.session_id if task.action.type == "session_message" else None
        if session_id:
            try:
                self.runtime.session_store.get(session_id)
            except FileNotFoundError:
                task.enabled = False
                task.status = "disabled"
                task.last_skip_reason = "绑定的目标会话不存在，任务已自动禁用"
                return self._finalize_non_success(
                    task,
                    outcome="skipped_missing_session",
                    trigger_kind=trigger_kind,
                    scheduled_for=scheduled_for,
                    message="绑定的目标会话不存在，任务已自动禁用",
                    severity="warning",
                )

            if self.is_session_busy(session_id):
                return self._finalize_non_success(
                    task,
                    outcome="skipped_conflict",
                    trigger_kind=trigger_kind,
                    scheduled_for=scheduled_for,
                    session_id=session_id,
                    message="目标会话当前有任务在运行，本次触发已跳过",
                    severity="warning",
                )

        self._active_task_ids.add(task.task_id)
        if session_id:
            self._active_session_ids.add(session_id)

        task.status = "running"
        task.last_skip_reason = None
        task.updated_at = utc_now()
        self.task_store.upsert(task)
        total_attempts = max(1, task.max_retries + 1)
        last_error = ""

        try:
            for attempt in range(1, total_attempts + 1):
                try:
                    result = await self._run_task_action(
                        task,
                        trigger_kind=trigger_kind,
                        scheduled_for=scheduled_for,
                    )
                    if result.outcome == "success":
                        return self._finalize_success(
                            task,
                            trigger_kind=trigger_kind,
                            scheduled_for=scheduled_for,
                            session_id=result.session_id,
                            turn_id=result.turn_id,
                            message=result.message,
                        )
                    severity = "warning" if result.outcome == "approval_blocked" else "error"
                    return self._finalize_non_success(
                        task,
                        outcome=result.outcome,
                        trigger_kind=trigger_kind,
                        scheduled_for=scheduled_for,
                        session_id=result.session_id,
                        turn_id=result.turn_id,
                        message=result.message,
                        severity=severity,
                    )
                except Exception as exc:
                    last_error = str(exc)
                    if attempt >= total_attempts:
                        return self._finalize_non_success(
                            task,
                            outcome="failed",
                            trigger_kind=trigger_kind,
                            scheduled_for=scheduled_for,
                            session_id=session_id,
                            message=f"任务执行失败，已重试 {task.max_retries} 次: {last_error}",
                            severity="error",
                        )
                    await asyncio.sleep(min(attempt, 5))
        finally:
            self._active_task_ids.discard(task.task_id)
            if session_id:
                self._active_session_ids.discard(session_id)

    async def _run_task_action(
        self,
        task: ScheduledTask,
        *,
        trigger_kind: str,
        scheduled_for: datetime,
    ) -> _TaskExecutionResult:
        if task.action.type == "session_message":
            if not task.action.session_id:
                raise ValueError("session_message 任务必须提供 session_id")
            session_id = task.action.session_id
        else:
            session, _ = self.runtime.thread_manager.create_or_restore(title=f"[Scheduled] {task.name}")
            session.metadata.update(
                {
                    "background": True,
                    "scheduled": True,
                    "scheduler_task_id": task.task_id,
                    "scheduler_task_name": task.name,
                    "scheduler_trigger_type": trigger_kind,
                }
            )
            self.runtime.session_store.save(session)
            session_id = session.session_id

        state = _RunAuditState(
            request_id=uuid4().hex,
            session_id=session_id,
            audit_path=self.runtime.settings.paths.audit_dir / f"{session_id}.log",
        )
        emit = self._build_audit_emitter(state)
        await emit(
            "scheduler_run_started",
            {
                "task_id": task.task_id,
                "task_name": task.name,
                "trigger_kind": trigger_kind,
                "scheduled_for": scheduled_for.isoformat(),
            },
        )

        turn_id_holder: dict[str, str] = {}
        await self.runtime.handle_message(
            session_id,
            task.action.prompt,
            emit,
            user_metadata={
                "scheduled": True,
                "scheduled_task_id": task.task_id,
                "scheduled_task_name": task.name,
                "scheduler_trigger_kind": trigger_kind,
                "scheduler_run_mode": "unattended",
            },
            turn_approval_mode="manual",
            request_id=state.request_id,
            on_turn_created=lambda turn_id: turn_id_holder.setdefault("turn_id", turn_id),
            scheduler_run_mode="unattended",
        )

        state.turn_id = turn_id_holder.get("turn_id") or state.turn_id
        outcome, message = self._outcome_from_finish_reason(state)
        await emit(
            "scheduler_run_completed",
            {
                "task_id": task.task_id,
                "task_name": task.name,
                "trigger_kind": trigger_kind,
                "outcome": outcome,
                "message": message,
                "scheduled_for": scheduled_for.isoformat(),
                **({"turn_id": state.turn_id} if state.turn_id else {}),
            },
        )
        return _TaskExecutionResult(
            outcome=outcome,
            session_id=session_id,
            turn_id=state.turn_id,
            message=message,
        )

    def _build_audit_emitter(self, state: _RunAuditState) -> EventEmitter:
        async def emit(event: str, data: dict) -> None:
            turn_id = data.get("turn_id")
            if isinstance(turn_id, str) and turn_id:
                state.turn_id = turn_id
            if event == "final_response":
                finish_reason = data.get("finish_reason")
                if isinstance(finish_reason, str) and finish_reason:
                    state.final_finish_reason = finish_reason
                content = data.get("content")
                if isinstance(content, str):
                    state.final_content = content
            payload = build_event_payload(event, data, request_id=state.request_id)
            state.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with state.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        return emit

    def _outcome_from_finish_reason(self, state: _RunAuditState) -> tuple[TaskOutcome, str]:
        if state.final_finish_reason == "approval_rejected":
            return "approval_blocked", "无人值守定时任务命中工具审批，已快速失败"
        if state.final_finish_reason in {"provider_error", "fatal_tool_error"}:
            message = state.final_content.strip() or "执行过程中发生致命错误"
            return "failed", message
        return "success", state.final_content.strip() or "任务执行成功"

    def _finalize_success(
        self,
        task: ScheduledTask,
        *,
        trigger_kind: str,
        scheduled_for: datetime,
        session_id: str | None,
        turn_id: str | None,
        message: str,
    ) -> ScheduledTask:
        finished_at = utc_now()
        task.status = "completed"
        task.last_error = ""
        task.last_skip_reason = None
        task.last_run_outcome = "success"
        task.last_run_session_id = session_id
        task.last_run_turn_id = turn_id
        task.last_run_at = finished_at
        task.last_success_at = finished_at
        task.run_count += 1
        task.next_run_at = self._next_run_after(task, trigger_kind=trigger_kind, scheduled_for=scheduled_for)
        self.run_store.append(
            SchedulerRunRecord(
                run_id=uuid4().hex,
                task_id=task.task_id,
                trigger_kind=trigger_kind,
                outcome="success",
                scheduled_for=scheduled_for.isoformat(),
                started_at=finished_at,
                finished_at=finished_at,
                session_id=session_id,
                turn_id=turn_id,
                message=message,
            )
        )
        return self.task_store.upsert(task)

    def _finalize_non_success(
        self,
        task: ScheduledTask,
        *,
        outcome: TaskOutcome,
        trigger_kind: str,
        scheduled_for: datetime,
        message: str,
        severity: str,
        session_id: str | None = None,
        turn_id: str | None = None,
    ) -> ScheduledTask:
        finished_at = utc_now()
        if outcome == "skipped_missing_session":
            task.status = "disabled"
            task.enabled = False
        elif outcome == "skipped_conflict":
            task.status = "pending"
        else:
            task.status = "failed"
            task.failure_count += 1
            task.last_error = message

        if outcome in {"skipped_conflict", "skipped_missing_session"}:
            task.last_error = ""
            task.last_skip_reason = message
        else:
            task.last_skip_reason = None

        task.last_run_outcome = outcome
        task.last_run_session_id = session_id
        task.last_run_turn_id = turn_id
        task.last_run_at = finished_at
        task.run_count += 1
        task.next_run_at = self._next_run_after(task, trigger_kind=trigger_kind, scheduled_for=scheduled_for)

        if session_id and outcome == "skipped_conflict":
            self._append_audit_event(
                session_id,
                "scheduler_run_skipped",
                {
                    "task_id": task.task_id,
                    "task_name": task.name,
                    "trigger_kind": trigger_kind,
                    "outcome": outcome,
                    "message": message,
                    "scheduled_for": scheduled_for.isoformat(),
                },
            )

        self.alert_store.append(
            SchedulerAlert(
                alert_id=uuid4().hex,
                task_id=task.task_id,
                task_name=task.name,
                severity=severity,
                message=message,
            )
        )
        self.run_store.append(
            SchedulerRunRecord(
                run_id=uuid4().hex,
                task_id=task.task_id,
                trigger_kind=trigger_kind,
                outcome=outcome,
                scheduled_for=scheduled_for.isoformat(),
                started_at=finished_at,
                finished_at=finished_at,
                session_id=session_id,
                turn_id=turn_id,
                message=message,
            )
        )
        return self.task_store.upsert(task)

    def _normalize_task(self, task: ScheduledTask, now: datetime, *, recompute: bool = False) -> ScheduledTask:
        if recompute or self._parse_timestamp(task.next_run_at) is None:
            reference = self._schedule_reference(task, now, recompute=recompute)
            task.next_run_at = next_run(task.cron, reference, task.timezone).isoformat()
        if not task.enabled:
            task.status = "disabled"
        elif task.status == "disabled":
            task.status = "pending"
        return task

    def _schedule_reference(self, task: ScheduledTask, now: datetime, *, recompute: bool) -> datetime:
        if recompute:
            return now
        last_run_at = self._parse_timestamp(task.last_run_at)
        return last_run_at or now

    def _next_run_after(self, task: ScheduledTask, *, trigger_kind: str, scheduled_for: datetime) -> str | None:
        if not task.enabled:
            return next_run(task.cron, datetime.now(timezone.utc), task.timezone).isoformat()
        if trigger_kind == "manual_run":
            current = self._parse_timestamp(task.next_run_at)
            if current is not None and current > datetime.now(timezone.utc):
                return current.isoformat()
            return next_run(task.cron, datetime.now(timezone.utc), task.timezone).isoformat()
        return next_run(task.cron, scheduled_for, task.timezone).isoformat()

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _append_audit_event(self, session_id: str, event: str, data: dict) -> None:
        audit_path = self.runtime.settings.paths.audit_dir / f"{session_id}.log"
        payload = build_event_payload(event, data)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
