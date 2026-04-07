from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from backend.scheduler.cron_parser import matches_cron, next_run
from backend.scheduler.models import ScheduledTask, utc_now
from backend.scheduler.task_store import TaskStore


class SchedulerEngine:
    def __init__(self, task_store: TaskStore, runtime):
        self.task_store = task_store
        self.runtime = runtime
        self._worker: asyncio.Task | None = None
        self._running = False

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
        tasks = [self._with_next_run(task) for task in self.task_store.list_tasks()]
        self.task_store.save_tasks(tasks)

    async def run_now(self, task_id: str) -> ScheduledTask:
        task = self.task_store.get(task_id)
        return await self._execute(task)

    async def _loop(self) -> None:
        while self._running:
            await self._tick()
            await asyncio.sleep(1)

    async def _tick(self) -> None:
        now = datetime.now(timezone.utc)
        updated: list[ScheduledTask] = []
        for task in self.task_store.list_tasks():
            task = self._with_next_run(task)
            if task.enabled and matches_cron(task.cron, now) and not self._already_ran_this_minute(task, now):
                task = await self._execute(task)
            updated.append(task)
        self.task_store.save_tasks(updated)

    async def _execute(self, task: ScheduledTask) -> ScheduledTask:
        task.status = "running"
        task.updated_at = utc_now()
        self.task_store.upsert(task)
        total_attempts = max(1, task.max_retries + 1)
        last_error = ""

        for attempt in range(1, total_attempts + 1):
            try:
                await self._run_task_action(task)
                task.status = "completed"
                task.last_error = ""
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt >= total_attempts:
                    task.status = "failed"
                    task.last_error = f"任务执行失败，已重试 {task.max_retries} 次: {last_error}"
                    break
                await asyncio.sleep(min(attempt, 5))

        task.last_run_at = utc_now()
        task.run_count += 1
        task.next_run_at = next_run(task.cron, datetime.now(timezone.utc)).isoformat()
        return self.task_store.upsert(task)

    async def _noop_emit(self, event: str, data: dict) -> None:
        return None

    async def _run_task_action(self, task: ScheduledTask) -> None:
        if task.action.type == "session_message":
            if not task.action.session_id:
                raise ValueError("session_message 任务必须提供 session_id")
            await self.runtime.handle_message(task.action.session_id, task.action.prompt, self._noop_emit)
            return

        session, _ = self.runtime.thread_manager.create_or_restore(title=f"[Scheduled] {task.name}")
        session.metadata["background"] = True
        self.runtime.session_store.save(session)
        await self.runtime.handle_message(session.session_id, task.action.prompt, self._noop_emit)

    def _with_next_run(self, task: ScheduledTask) -> ScheduledTask:
        task.next_run_at = next_run(task.cron, datetime.now(timezone.utc)).isoformat()
        if not task.enabled:
            task.status = "disabled"
        elif task.status == "disabled":
            task.status = "pending"
        return task

    def _already_ran_this_minute(self, task: ScheduledTask, now: datetime) -> bool:
        if not task.last_run_at:
            return False
        last_run = datetime.fromisoformat(task.last_run_at)
        return last_run.replace(second=0, microsecond=0) == now.replace(second=0, microsecond=0)
