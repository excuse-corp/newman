from __future__ import annotations

import unittest

from backend.subagents.models import MultiAgentRun, SubagentTask, UsageSummary
from backend.subagents.report import (
    AgentReportParseError,
    aggregate_multiagent_report,
    degraded_agent_report,
    parse_agent_report,
)


def _task(task_id: str, status: str = "completed") -> SubagentTask:
    return SubagentTask(
        task_id=task_id,
        run_id="run-1",
        parent_session_id="parent-session",
        parent_turn_id="turn-1",
        child_session_id=f"child-{task_id}",
        name=f"agent-{task_id}",
        assignment_prompt="Report back.",
        status=status,
        usage_summary=UsageSummary(input_tokens=10, output_tokens=5, total_tokens=15, request_count=1),
    )


class SubagentReportTests(unittest.TestCase):
    def test_parse_agent_report_accepts_json_code_block_and_fills_stable_fields(self) -> None:
        task = _task("task-1")
        report = parse_agent_report(
            """
            Done.

            ```json
            {
              "summary": "Read the runtime loop.",
              "status": "completed",
              "findings": [{"title": "Entry point", "detail": "run_loop owns tool dispatch"}],
              "recommended_next_steps": ["Inspect tool router"]
            }
            ```
            """,
            task,
        )

        self.assertEqual(report.task_id, "task-1")
        self.assertEqual(report.name, "agent-task-1")
        self.assertEqual(report.status, "completed")
        self.assertEqual(report.transcript_ref, "session://child-task-1")
        self.assertEqual(report.findings[0].title, "Entry point")

    def test_parse_agent_report_accepts_plain_text_sections(self) -> None:
        task = _task("task-1")
        report = parse_agent_report(
            """
            Scope: runtime inspection
            Result:
            - confirmed the run loop owns tool dispatch
            Key files:
            - backend/runtime/run_loop.py
            Issues:
            - missing timeout guard for long-running provider calls
            Risks:
            - cancellation path still depends on provider responsiveness
            Next steps:
            - add a wall-clock timeout around provider execution
            """,
            task,
        )

        self.assertEqual(report.status, "completed")
        self.assertIn("run loop owns tool dispatch", report.summary)
        self.assertEqual(report.findings[0].title, "missing timeout guard for long-running provider calls")
        self.assertEqual(report.artifacts[0].path, "backend/runtime/run_loop.py")
        self.assertEqual(report.recommended_next_steps[0], "add a wall-clock timeout around provider execution")

    def test_parse_agent_report_coerces_common_json_shape_mismatches(self) -> None:
        task = _task("task-1")
        report = parse_agent_report(
            """
            {
              "status": "completed",
              "summary": "Completed backend review.",
              "findings": [
                {"category": "SSE", "severity": "warning", "detail": "SSE reconnect handling is not obvious.", "line": "L3142-L3160"}
              ],
              "artifacts": [
                {"type": "assessment_summary", "name": "Audit", "content": "structured output"}
              ],
              "risks": [
                {"severity": "medium", "description": "Large file is hard to maintain."}
              ],
              "recommended_next_steps": [
                {"priority": "P1", "action": "Split App.tsx by feature area."}
              ],
              "commands_run": ["rg multiagent frontend/src/App.tsx"],
              "usage_summary": {"tool_calls": 10}
            }
            """,
            task,
        )

        self.assertEqual(report.findings[0].title, "SSE")
        self.assertEqual(report.findings[0].severity, "medium")
        self.assertIsNone(report.findings[0].line)
        self.assertEqual(report.artifacts[0].title, "Audit")
        self.assertEqual(report.artifacts[0].kind, "assessment_summary")
        self.assertEqual(report.risks[0], "Large file is hard to maintain.")
        self.assertEqual(report.recommended_next_steps[0], "P1: Split App.tsx by feature area.")
        self.assertEqual(report.commands_run, [])
        self.assertEqual(report.usage_summary.total_tokens, 15)

    def test_parse_agent_report_rejects_empty_report(self) -> None:
        with self.assertRaises(AgentReportParseError):
            parse_agent_report("   ", _task("task-1"))

    def test_degraded_agent_report_preserves_partial_outputs(self) -> None:
        task = _task("task-1", status="timed_out")
        task.error = "Provider did not return in time."

        report = degraded_agent_report(task, reason="timed_out")

        self.assertTrue(report.degraded)
        self.assertEqual(report.degraded_reason, "timed_out")
        self.assertEqual(report.status, "timed_out")
        self.assertIn("Provider did not return in time.", report.summary)
        self.assertEqual(report.usage_summary.total_tokens, 15)

    def test_aggregate_multiagent_report_marks_partial(self) -> None:
        run = MultiAgentRun(
            run_id="run-1",
            parent_session_id="parent-session",
            parent_turn_id="turn-1",
            mode="parallel",
            task_ids=["task-1", "task-2"],
        )
        completed = _task("task-1")
        completed.result = parse_agent_report('{"status":"completed","summary":"ok"}', completed)
        failed = _task("task-2", status="report_invalid")
        failed.result = degraded_agent_report(failed, reason="parse_failed")

        report = aggregate_multiagent_report(run, [completed, failed])

        self.assertEqual(report.status, "partial")
        self.assertEqual(report.failed_agents, ["task-2"])
        self.assertEqual(len(report.agent_reports), 2)
        self.assertEqual(report.usage_summary.total_tokens, 30)


if __name__ == "__main__":
    unittest.main()
