from __future__ import annotations

from typing import Any

from backend.subagents.models import MultiAgentRun, SubagentTask


MULTIAGENT_EVENT_TYPES = [
    "multiagent_run_started",
    "multiagent_run_updated",
    "multiagent_task_started",
    "multiagent_task_updated",
    "multiagent_model_call_completed",
    "multiagent_failure_decision_required",
    "multiagent_failure_decision_resolved",
    "multiagent_tool_event",
    "multiagent_approval_queued",
    "multiagent_run_completed",
]


def run_event_payload(run: MultiAgentRun, *, include_result: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "parent_session_id": run.parent_session_id,
        "parent_turn_id": run.parent_turn_id,
        "mode": run.mode,
        "run_mode": run.run_mode,
        "return_strategy": run.return_strategy,
        "context_policy": run.context_policy,
        "on_subagent_failure": run.on_subagent_failure,
        "status": run.status,
        "task_ids": list(run.task_ids),
        "pending_failure_task_ids": list(run.pending_failure_task_ids),
        "failure_decision_requested_at": run.failure_decision_requested_at,
        "failure_decision": run.failure_decision,
        "failure_decision_resolved_at": run.failure_decision_resolved_at,
        "usage_summary": run.usage_summary.model_dump(mode="json"),
        "started_at": run.started_at,
        "cancel_requested_at": run.cancel_requested_at,
        "cancel_reason": run.cancel_reason,
        "completed_at": run.completed_at,
        "error": run.error,
    }
    if include_result and run.result is not None:
        payload["result"] = run.result.model_dump(mode="json")
    return payload


def task_event_payload(task: SubagentTask, *, include_result: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "run_id": task.run_id,
        "parent_session_id": task.parent_session_id,
        "parent_turn_id": task.parent_turn_id,
        "child_session_id": task.child_session_id,
        "transcript_ref": task.transcript_ref,
        "name": task.name,
        "agent_type": task.agent_type,
        "description": task.description,
        "status": task.status,
        "current_activity": task.current_activity,
        "progress": task.progress.model_dump(mode="json"),
        "file_changes": [item.model_dump(mode="json") for item in task.file_changes],
        "terminal_commands": [item.model_dump(mode="json") for item in task.terminal_commands],
        "usage_summary": task.usage_summary.model_dump(mode="json"),
        "started_at": task.started_at,
        "cancel_requested_at": task.cancel_requested_at,
        "cancel_reason": task.cancel_reason,
        "completed_at": task.completed_at,
        "error": task.error,
    }
    if include_result and task.result is not None:
        payload["result"] = task.result.model_dump(mode="json")
    return payload


def tool_event_payload(task: SubagentTask, event: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": task.run_id,
        "task_id": task.task_id,
        "agent_name": task.name,
        "parent_session_id": task.parent_session_id,
        "parent_turn_id": task.parent_turn_id,
        "child_session_id": task.child_session_id,
        "event": event,
        "data": data,
    }


def model_call_completed_payload(
    task: SubagentTask,
    *,
    usage_delta: dict[str, Any],
    tool_schema_count: int,
    is_repair: bool,
    is_wrapup: bool,
    finish_reason: str,
    model: str,
) -> dict[str, Any]:
    return {
        "run_id": task.run_id,
        "task_id": task.task_id,
        "agent_name": task.name,
        "parent_session_id": task.parent_session_id,
        "parent_turn_id": task.parent_turn_id,
        "child_session_id": task.child_session_id,
        "usage_delta": usage_delta,
        "task_usage_summary": task.usage_summary.model_dump(mode="json"),
        "tool_schema_count": tool_schema_count,
        "is_wrapup_turn": is_wrapup,
        "is_report_repair": is_repair,
        "finish_reason": finish_reason,
        "model": model,
    }


def failure_decision_required_payload(
    run: MultiAgentRun,
    failed_task: SubagentTask,
    tasks: list[SubagentTask],
) -> dict[str, Any]:
    pending_tasks = [task for task in tasks if task.status == "pending"]
    running_tasks = [task for task in tasks if task.status in {"running", "waiting_file_lock", "waiting_approval"}]
    failed_task_ids = list(dict.fromkeys([*run.pending_failure_task_ids, failed_task.task_id]))
    return {
        **run_event_payload(run),
        "task_id": failed_task.task_id,
        "failed_task_id": failed_task.task_id,
        "failed_task_ids": failed_task_ids,
        "agent_name": failed_task.name,
        "error_summary": failed_task.error or (failed_task.result.summary if failed_task.result is not None else failed_task.current_activity),
        "available_actions": ["retry_failed", "continue", "abort"],
        "can_retry": True,
        "remaining_task_count": len(pending_tasks),
        "running_task_count": len(running_tasks),
    }


def failure_decision_resolved_payload(
    run: MultiAgentRun,
    *,
    decision: str,
    task_ids: list[str],
) -> dict[str, Any]:
    return {
        **run_event_payload(run),
        "decision": decision,
        "task_ids": list(task_ids),
    }
