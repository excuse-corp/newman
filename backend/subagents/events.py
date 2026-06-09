from __future__ import annotations

from typing import Any

from backend.subagents.models import MultiAgentRun, SubagentTask


MULTIAGENT_EVENT_TYPES = [
    "multiagent_run_started",
    "multiagent_run_updated",
    "multiagent_task_started",
    "multiagent_task_updated",
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
        "status": run.status,
        "task_ids": list(run.task_ids),
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
