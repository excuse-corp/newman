from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from backend.scheduler.cron_parser import matches_cron, next_run
from backend.scheduler.models import ScheduledTask, TaskAction
from backend.scheduler.scheduler_engine import SchedulerEngine
from backend.scheduler.task_store import TaskStore


class _DummyThreadManager:
    def __init__(self) -> None:
        self.created_titles: list[str] = []
        self.counter = 0

    def create_or_restore(self, title: str):
        self.created_titles.append(title)
        self.counter += 1
        session = SimpleNamespace(session_id=f"background-session-{self.counter}", metadata={})
        return session, True


class _DummySessionStore:
    def __init__(self) -> None:
        self.saved = []
        self.sessions: dict[str, object] = {}

    def save(self, session) -> None:
        self.saved.append(session)
        self.sessions[session.session_id] = session

    def get(self, session_id: str):
        if session_id not in self.sessions:
            raise FileNotFoundError(session_id)
        return self.sessions[session_id]


class _DummyRuntime:
    def __init__(
        self,
        scheduler_dir: Path,
        *,
        should_fail: bool = False,
        finish_reason: str = "stop",
        existing_session_ids: list[str] | None = None,
    ) -> None:
        self.settings = SimpleNamespace(
            paths=SimpleNamespace(
                scheduler_dir=scheduler_dir,
                audit_dir=scheduler_dir / "audit",
            )
        )
        self.thread_manager = _DummyThreadManager()
        self.session_store = _DummySessionStore()
        for session_id in existing_session_ids or []:
            self.session_store.sessions[session_id] = SimpleNamespace(session_id=session_id, metadata={})
        self.should_fail = should_fail
        self.finish_reason = finish_reason
        self.handled_messages: list[dict[str, object]] = []

    async def handle_message(
        self,
        session_id: str,
        prompt: str,
        emit,
        user_metadata: dict[str, object] | None = None,
        turn_approval_mode: str = "manual",
        request_id: str | None = None,
        turn_id: str | None = None,
        on_turn_created=None,
        post_user_message=None,
        scheduler_run_mode: str = "interactive",
    ) -> None:
        self.handled_messages.append(
            {
                "session_id": session_id,
                "prompt": prompt,
                "user_metadata": user_metadata or {},
                "turn_approval_mode": turn_approval_mode,
                "request_id": request_id,
                "scheduler_run_mode": scheduler_run_mode,
            }
        )
        if callable(on_turn_created):
            on_turn_created(turn_id or "turn-1")
        if self.should_fail:
            raise RuntimeError("simulated failure")
        await emit(
            "final_response",
            {
                "session_id": session_id,
                "content": "ok" if self.finish_reason == "stop" else "failed",
                "finish_reason": self.finish_reason,
            },
        )


class SchedulerCronTests(unittest.TestCase):
    def test_matches_cron_uses_standard_weekday_mapping(self) -> None:
        dt = datetime(2026, 4, 12, 12, 30, tzinfo=timezone.utc)
        self.assertTrue(matches_cron("30 12 * * 0", dt))
        self.assertTrue(matches_cron("30 12 * * 7", dt))
        self.assertFalse(matches_cron("30 12 * * 1", dt))

    def test_next_run_respects_task_timezone(self) -> None:
        current = datetime(2026, 4, 8, 23, 30, tzinfo=timezone.utc)
        resolved = next_run("0 8 * * *", current, "Asia/Shanghai")
        self.assertEqual(resolved, datetime(2026, 4, 9, 0, 0, tzinfo=timezone.utc))

    def test_fall_back_hour_only_runs_once(self) -> None:
        first = next_run("30 1 1 11 *", datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc), "America/New_York")
        second = next_run("30 1 1 11 *", first, "America/New_York")

        self.assertEqual(first, datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc))
        self.assertNotEqual(second, datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc))


class SchedulerEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_task_marks_session_background_and_records_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler_dir = Path(tmp)
            runtime = _DummyRuntime(scheduler_dir)
            engine = SchedulerEngine(TaskStore(scheduler_dir / "tasks.json"), runtime)
            task = ScheduledTask(
                task_id="task-1",
                name="Daily Digest",
                cron="*/30 * * * *",
                action=TaskAction(type="background_task", prompt="generate digest"),
            )

            updated = await engine._execute(
                task,
                trigger_kind="manual_run",
                scheduled_for=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(updated.status, "completed")
            self.assertEqual(runtime.handled_messages[0]["scheduler_run_mode"], "unattended")
            self.assertTrue(runtime.session_store.saved[0].metadata["background"])
            self.assertTrue(runtime.session_store.saved[0].metadata["scheduled"])
            runs = engine.run_store.list_runs(task_id="task-1")
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].outcome, "success")

    async def test_session_message_missing_session_disables_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler_dir = Path(tmp)
            runtime = _DummyRuntime(scheduler_dir)
            engine = SchedulerEngine(TaskStore(scheduler_dir / "tasks.json"), runtime)
            task = ScheduledTask(
                task_id="task-2",
                name="Bound Session",
                cron="*/30 * * * *",
                action=TaskAction(type="session_message", prompt="hello", session_id="missing-session"),
            )

            updated = await engine._execute(
                task,
                trigger_kind="cron",
                scheduled_for=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(updated.status, "disabled")
            self.assertFalse(updated.enabled)
            self.assertEqual(updated.last_run_outcome, "skipped_missing_session")
            alerts = engine.alert_store.list_alerts()
            self.assertEqual(alerts[0].severity, "warning")

    async def test_busy_session_skips_run_without_executing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler_dir = Path(tmp)
            runtime = _DummyRuntime(scheduler_dir, existing_session_ids=["session-1"])
            engine = SchedulerEngine(TaskStore(scheduler_dir / "tasks.json"), runtime)
            engine.set_session_busy_checker(lambda session_id: session_id == "session-1")
            task = ScheduledTask(
                task_id="task-3",
                name="Busy Session",
                cron="*/30 * * * *",
                action=TaskAction(type="session_message", prompt="hello", session_id="session-1"),
            )

            updated = await engine._execute(
                task,
                trigger_kind="cron",
                scheduled_for=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(updated.status, "pending")
            self.assertEqual(updated.last_run_outcome, "skipped_conflict")
            self.assertEqual(runtime.handled_messages, [])
            audit_path = scheduler_dir / "audit" / "session-1.log"
            self.assertTrue(audit_path.exists())
            self.assertIn("scheduler_run_skipped", audit_path.read_text(encoding="utf-8"))

    async def test_unattended_approval_becomes_approval_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler_dir = Path(tmp)
            runtime = _DummyRuntime(
                scheduler_dir,
                finish_reason="approval_rejected",
                existing_session_ids=["session-1"],
            )
            engine = SchedulerEngine(TaskStore(scheduler_dir / "tasks.json"), runtime)
            task = ScheduledTask(
                task_id="task-4",
                name="Approval Needed",
                cron="*/30 * * * *",
                action=TaskAction(type="session_message", prompt="hello", session_id="session-1"),
            )

            updated = await engine._execute(
                task,
                trigger_kind="cron",
                scheduled_for=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(updated.status, "failed")
            self.assertEqual(updated.last_run_outcome, "approval_blocked")
            alerts = engine.alert_store.list_alerts()
            self.assertEqual(alerts[0].severity, "warning")

    async def test_task_store_delete_removes_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.json")
            task = ScheduledTask(
                task_id="task-5",
                name="Delete Me",
                cron="*/5 * * * *",
                action=TaskAction(type="background_task", prompt="noop"),
            )
            store.upsert(task)

            store.delete("task-5")

            self.assertEqual(store.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
