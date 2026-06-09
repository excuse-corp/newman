from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.subagents.events import run_event_payload, task_event_payload, tool_event_payload
from backend.subagents.models import (
    AgentReport,
    MultiAgentRun,
    SubagentTask,
    UsageSummary,
)
from backend.subagents.store import MultiAgentStore


def _run(run_id: str = "run-1") -> MultiAgentRun:
    return MultiAgentRun(
        run_id=run_id,
        parent_session_id="parent-session",
        parent_turn_id="turn-1",
        mode="parallel",
        task_ids=["task-1"],
    )


def _task(task_id: str = "task-1", run_id: str = "run-1") -> SubagentTask:
    return SubagentTask(
        task_id=task_id,
        run_id=run_id,
        parent_session_id="parent-session",
        parent_turn_id="turn-1",
        child_session_id=f"child-{task_id}",
        name=f"agent-{task_id}",
        assignment_prompt="Read files and report back.",
        allowed_tools=["read_file"],
        denied_tools=["multiagent", "request_user_input"],
    )


class SubagentModelTests(unittest.TestCase):
    def test_agent_report_requires_degraded_reason_when_degraded(self) -> None:
        report = AgentReport(
            task_id="task-1",
            name="reader",
            status="failed",
            summary="fallback",
            transcript_ref="session://child",
            degraded=True,
        )

        self.assertEqual(report.degraded_reason, "degraded")

    def test_usage_summary_adds_token_counts_and_optional_cost(self) -> None:
        left = UsageSummary(input_tokens=10, output_tokens=5, total_tokens=15, request_count=1)
        right = UsageSummary(input_tokens=3, output_tokens=4, total_tokens=7, request_count=2, cost_usd=0.01)

        combined = left.add(right)

        self.assertEqual(combined.input_tokens, 13)
        self.assertEqual(combined.output_tokens, 9)
        self.assertEqual(combined.total_tokens, 22)
        self.assertEqual(combined.request_count, 3)
        self.assertEqual(combined.cost_usd, 0.01)

    def test_event_payloads_use_task_id_and_transcript_ref(self) -> None:
        run = _run()
        task = _task()

        self.assertEqual(run_event_payload(run)["run_id"], "run-1")
        self.assertEqual(task_event_payload(task)["task_id"], "task-1")
        self.assertEqual(task_event_payload(task)["transcript_ref"], "session://child-task-1")
        wrapped = tool_event_payload(task, "tool_call_started", {"tool": "read_file"})
        self.assertEqual(wrapped["task_id"], "task-1")
        self.assertEqual(wrapped["agent_name"], "agent-task-1")


class MultiAgentStoreTests(unittest.TestCase):
    def test_store_round_trips_run_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MultiAgentStore(Path(tmp))
            run = _run()
            task = _task()

            store.save_run(run, [task])
            loaded = store.get_record(run.run_id)
            task_record, loaded_task = store.get_task_record(task.task_id)

            self.assertEqual(loaded.run.run_id, run.run_id)
            self.assertIn(task.task_id, loaded.tasks)
            self.assertEqual(store.get_task(task.task_id).name, task.name)
            self.assertEqual(task_record.run.run_id, run.run_id)
            self.assertEqual(loaded_task.task_id, task.task_id)

    def test_store_filters_by_parent_session_and_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MultiAgentStore(Path(tmp))
            first = _run("run-1")
            second = MultiAgentRun(
                run_id="run-2",
                parent_session_id="other-session",
                parent_turn_id="turn-2",
                mode="parallel",
            )
            store.save_run(first, [_task(run_id=first.run_id)])
            store.save_run(second, [])

            records = store.list_records(parent_session_id="parent-session", parent_turn_id="turn-1")

            self.assertEqual([record.run.run_id for record in records], ["run-1"])


if __name__ == "__main__":
    unittest.main()
