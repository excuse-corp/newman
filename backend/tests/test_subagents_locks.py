from __future__ import annotations

import unittest

from backend.subagents.locks import FileLockManager, FileLockTimeout


class FileLockManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_timeout_reports_current_holder(self) -> None:
        manager = FileLockManager()
        acquired = await manager.acquire(["/tmp/demo.txt"], task_id="task-a", timeout_seconds=1)
        try:
            with self.assertRaises(FileLockTimeout) as raised:
                await manager.acquire(["/tmp/demo.txt"], task_id="task-b", timeout_seconds=0.01)
        finally:
            manager.release(acquired, task_id="task-a")

        self.assertEqual(raised.exception.blocked_task_id, "task-b")
        self.assertEqual(raised.exception.holding_task_id, "task-a")

    async def test_locks_are_acquired_in_sorted_order(self) -> None:
        manager = FileLockManager()
        acquired = await manager.acquire(["/tmp/b.txt", "/tmp/a.txt"], task_id="task-a", timeout_seconds=1)

        self.assertEqual(acquired, ["/tmp/a.txt", "/tmp/b.txt"])
        manager.release(acquired, task_id="task-a")


if __name__ == "__main__":
    unittest.main()
