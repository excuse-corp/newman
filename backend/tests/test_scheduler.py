from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.scheduler.cron_parser import matches_cron, next_run
from backend.scheduler.models import ScheduledTask, TaskAction
from backend.scheduler.scheduler_engine import SchedulerEngine
from backend.scheduler.task_store import TaskStore


class _DummyThreadManager:
    def __init__(self) -> None:
        self.created_titles: list[str] = []

    def create_or_restore(self, title: str):
        self.created_titles.append(title)
        session = SimpleNamespace(session_id="background-session", metadata={})
        return session, True


class _DummySessionStore:
    def __init__(self) -> None:
        self.saved = []

    def save(self, session) -> None:
        self.saved.append(session)


class _DummyRuntime:
    def __init__(self, scheduler_dir: Path, should_fail: bool = False) -> None:
        self.settings = SimpleNamespace(paths=SimpleNamespace(scheduler_dir=scheduler_dir))
        self.thread_manager = _DummyThreadManager()
        self.session_store = _DummySessionStore()
        self.should_fail = should_fail
        self.handled_messages: list[tuple[str, str]] = []

    async def handle_message(self, session_id: str, prompt: str, emit) -> None:
        self.handled_messages.append((session_id, prompt))
        if self.should_fail:
            raise RuntimeError("simulated failure")


class SchedulerCronTests(unittest.TestCase):
    def test_matches_cron_supports_step_values(self) -> None:
        from datetime import datetime, timezone

        dt = datetime(2026, 4, 8, 12, 30, tzinfo=timezone.utc)
        self.assertTrue(matches_cron("*/30 * * * *", dt))
        self.assertFalse(matches_cron("15 * * * *", dt))

    def test_next_run_returns_future_match(self) -> None:
        from datetime import datetime, timezone

        current = datetime(2026, 4, 8, 12, 14, tzinfo=timezone.utc)
        resolved = next_run("15 * * * *", current)
        self.assertEqual((resolved.hour, resolved.minute), (12, 15))


class SchedulerEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_task_marks_session_background(self) -> None:
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

            updated = await engine._execute(task)

            self.assertEqual(updated.status, "completed")
            self.assertEqual(runtime.handled_messages, [("background-session", "generate digest")])
            self.assertTrue(runtime.session_store.saved[0].metadata["background"])

    async def test_session_message_requires_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler_dir = Path(tmp)
            runtime = _DummyRuntime(scheduler_dir)
            engine = SchedulerEngine(TaskStore(scheduler_dir / "tasks.json"), runtime)
            task = ScheduledTask(
                task_id="task-2",
                name="Bad Task",
                cron="*/30 * * * *",
                action=TaskAction(type="session_message", prompt="hello", session_id=None),
                max_retries=0,
            )

            updated = await engine._execute(task)

            self.assertEqual(updated.status, "failed")
            alerts = engine.alert_store.list_alerts()
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].task_id, "task-2")

    async def test_task_store_delete_removes_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.json")
            task = ScheduledTask(
                task_id="task-3",
                name="Delete Me",
                cron="*/5 * * * *",
                action=TaskAction(type="background_task", prompt="noop"),
            )
            store.upsert(task)

            store.delete("task-3")

            self.assertEqual(store.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
