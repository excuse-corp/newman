from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.scheduler.models import ScheduledTask, TaskAction
from backend.scheduler.scheduler_engine import SchedulerEngine
from backend.scheduler.task_store import TaskStore
from backend.tools.discovery import BuiltinToolContext
from backend.tools.impl.schedule import SchedulerTool


class _DummyThreadManager:
    def __init__(self) -> None:
        self.counter = 0

    def create_or_restore(self, title: str):
        self.counter += 1
        session = SimpleNamespace(session_id=f"bg-{self.counter}", metadata={})
        return session, True


class _DummySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, object] = {}

    def get(self, session_id: str):
        if session_id not in self.sessions:
            raise FileNotFoundError(session_id)
        return self.sessions[session_id]


class _DummyRuntime:
    def __init__(self, scheduler_dir: Path) -> None:
        self.settings = SimpleNamespace(
            paths=SimpleNamespace(
                scheduler_dir=scheduler_dir,
                audit_dir=scheduler_dir / "audit",
            )
        )
        self.thread_manager = _DummyThreadManager()
        self.session_store = _DummySessionStore()
        self.handled_messages: list[dict] = []

    async def handle_message(self, session_id, prompt, emit, **kwargs):
        self.handled_messages.append({"session_id": session_id, "prompt": prompt})
        await emit("final_response", {"content": "ok", "finish_reason": "stop", "session_id": session_id})


def _make_tool(tmp_dir: Path) -> tuple[SchedulerTool, TaskStore, SchedulerEngine]:
    store = TaskStore(tmp_dir / "tasks.json")
    runtime = _DummyRuntime(tmp_dir)
    engine = SchedulerEngine(store, runtime)
    ctx = BuiltinToolContext(
        path_policy=SimpleNamespace(workspace=tmp_dir, writable_roots=[tmp_dir]),
        sandbox=SimpleNamespace(),
        scheduler_store=store,
        scheduler_engine=engine,
    )
    tool = SchedulerTool(ctx)
    return tool, store, engine


class SchedulerToolListTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "list"}, "s1")
            self.assertTrue(result.success)
            self.assertIn("共 0 个定时任务", result.stdout)

    async def test_list_with_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="Test", cron="*/5 * * * *",
                action=TaskAction(prompt="hello"),
            ))
            result = await tool.run({"action": "list"}, "s1")
            self.assertTrue(result.success)
            self.assertIn("共 1 个定时任务", result.stdout)
            self.assertEqual(len(result.metadata["tasks"]), 1)


class SchedulerToolAddTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_task_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            result = await tool.run({
                "action": "add",
                "name": "Daily Report",
                "cron": "0 9 * * *",
                "prompt": "生成日报",
                "timezone": "Asia/Shanghai",
            }, "s1")
            self.assertTrue(result.success)
            self.assertIn("Daily Report", result.summary)
            tasks = store.list_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].name, "Daily Report")
            self.assertEqual(tasks[0].cron, "0 9 * * *")
            self.assertEqual(tasks[0].timezone, "Asia/Shanghai")
            self.assertEqual(tasks[0].source, "chat")

    async def test_add_task_missing_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "add", "cron": "0 9 * * *", "prompt": "hi"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("name", result.summary)

    async def test_add_task_missing_cron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "add", "name": "X", "prompt": "hi"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("cron", result.summary)

    async def test_add_task_missing_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "add", "name": "X", "cron": "0 9 * * *"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("prompt", result.summary)

    async def test_add_task_invalid_cron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({
                "action": "add", "name": "X", "cron": "bad", "prompt": "hi",
            }, "s1")
            self.assertFalse(result.success)
            self.assertIn("Cron", result.summary)

    async def test_add_task_with_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            result = await tool.run({
                "action": "add", "name": "Sess", "cron": "0 * * * *",
                "prompt": "check", "session_id": "sess-123",
            }, "s1")
            self.assertTrue(result.success)
            task = store.list_tasks()[0]
            self.assertEqual(task.action.type, "session_message")
            self.assertEqual(task.action.session_id, "sess-123")

    async def test_add_task_defaults_to_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            await tool.run({
                "action": "add", "name": "BG", "cron": "0 * * * *", "prompt": "run",
            }, "s1")
            task = store.list_tasks()[0]
            self.assertEqual(task.action.type, "background_task")
            self.assertIsNone(task.action.session_id)


class SchedulerToolUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="Old", cron="*/5 * * * *",
                action=TaskAction(prompt="hi"),
            ))
            result = await tool.run({"action": "update", "task_id": "t1", "name": "New"}, "s1")
            self.assertTrue(result.success)
            self.assertEqual(store.get("t1").name, "New")

    async def test_update_cron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="T", cron="*/5 * * * *",
                action=TaskAction(prompt="hi"),
            ))
            result = await tool.run({"action": "update", "task_id": "t1", "cron": "0 9 * * *"}, "s1")
            self.assertTrue(result.success)
            self.assertEqual(store.get("t1").cron, "0 9 * * *")

    async def test_update_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "update", "task_id": "nope", "name": "X"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("不存在", result.summary)

    async def test_update_missing_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "update", "name": "X"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("task_id", result.summary)

    async def test_update_invalid_cron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="T", cron="*/5 * * * *",
                action=TaskAction(prompt="hi"),
            ))
            result = await tool.run({"action": "update", "task_id": "t1", "cron": "bad"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("Cron", result.summary)


class SchedulerToolRemoveTests(unittest.IsolatedAsyncioTestCase):
    async def test_remove_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="Del", cron="*/5 * * * *",
                action=TaskAction(prompt="hi"),
            ))
            result = await tool.run({"action": "remove", "task_id": "t1"}, "s1")
            self.assertTrue(result.success)
            self.assertEqual(store.list_tasks(), [])

    async def test_remove_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "remove", "task_id": "nope"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("不存在", result.summary)

    async def test_remove_missing_task_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "remove"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("task_id", result.summary)


class SchedulerToolRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="Run", cron="*/5 * * * *",
                action=TaskAction(prompt="do something"),
            ))
            result = await tool.run({"action": "run", "task_id": "t1"}, "s1")
            self.assertTrue(result.success)
            self.assertIn("Run", result.summary)

    async def test_run_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "run", "task_id": "nope"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("不存在", result.summary)

    async def test_run_no_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "tasks.json")
            ctx = BuiltinToolContext(
                path_policy=SimpleNamespace(workspace=Path(tmp), writable_roots=[Path(tmp)]),
                sandbox=SimpleNamespace(),
                scheduler_store=store,
                scheduler_engine=None,
            )
            tool = SchedulerTool(ctx)
            store.upsert(ScheduledTask(
                task_id="t1", name="T", cron="*/5 * * * *",
                action=TaskAction(prompt="hi"),
            ))
            result = await tool.run({"action": "run", "task_id": "t1"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("调度引擎", result.summary)


class SchedulerToolStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "status"}, "s1")
            self.assertTrue(result.success)
            self.assertIn("任务总数: 0", result.stdout)
            self.assertEqual(result.metadata["total"], 0)

    async def test_status_with_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, store, _ = _make_tool(Path(tmp))
            store.upsert(ScheduledTask(
                task_id="t1", name="A", cron="*/5 * * * *",
                action=TaskAction(prompt="a"), enabled=True,
            ))
            store.upsert(ScheduledTask(
                task_id="t2", name="B", cron="*/5 * * * *",
                action=TaskAction(prompt="b"), enabled=False,
            ))
            result = await tool.run({"action": "status"}, "s1")
            self.assertTrue(result.success)
            self.assertIn("任务总数: 2", result.stdout)
            self.assertEqual(result.metadata["total"], 2)
            self.assertEqual(result.metadata["enabled"], 1)
            self.assertEqual(result.metadata["disabled"], 1)


class SchedulerToolValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool, _, _ = _make_tool(Path(tmp))
            result = await tool.run({"action": "bogus"}, "s1")
            self.assertFalse(result.success)
            self.assertIn("未知", result.summary)

    async def test_no_scheduler_store(self) -> None:
        ctx = BuiltinToolContext(
            path_policy=SimpleNamespace(workspace=Path("/tmp"), writable_roots=[Path("/tmp")]),
            sandbox=SimpleNamespace(),
            scheduler_store=None,
        )
        tool = SchedulerTool(ctx)
        result = await tool.run({"action": "list"}, "s1")
        self.assertFalse(result.success)
        self.assertIn("未初始化", result.summary)


if __name__ == "__main__":
    unittest.main()
