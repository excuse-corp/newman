from __future__ import annotations

import json
from uuid import uuid4
from typing import Any

from backend.sessions.models import SessionRecord, utc_now


TURN_OUTCOME_ANSWERED = "answered"
TURN_OUTCOME_AWAITING_USER = "awaiting_user"
TURN_OUTCOME_ARTIFACT_READY = "artifact_ready"
TURN_OUTCOME_TASK_COMPLETED = "task_completed"
TURN_OUTCOME_BLOCKED = "blocked"
TURN_OUTCOME_FAILED = "failed"

AWAITING_USER_INPUT_METADATA_KEY = "awaiting_user_input"
WORKFLOW_STATE_METADATA_KEY = "workflow_state"


def normalize_turn_outcome(value: object | None, *, fallback: str = TURN_OUTCOME_ANSWERED) -> str:
    if isinstance(value, str) and value in {
        TURN_OUTCOME_ANSWERED,
        TURN_OUTCOME_AWAITING_USER,
        TURN_OUTCOME_ARTIFACT_READY,
        TURN_OUTCOME_TASK_COMPLETED,
        TURN_OUTCOME_BLOCKED,
        TURN_OUTCOME_FAILED,
    }:
        return value
    return fallback


def build_awaiting_user_input_payload(
    *,
    kind: str,
    prompt: str,
    content: str | None = None,
    options: list[dict[str, object]] | None = None,
    workflow_id: str | None = None,
    skill_name: str | None = None,
    phase: str | None = None,
    data: dict[str, object] | None = None,
) -> dict[str, object]:
    resolved_workflow_id = workflow_id or f"{skill_name or 'workflow'}:{uuid4().hex}"
    payload: dict[str, object] = {
        "request_id": uuid4().hex,
        "kind": kind,
        "prompt": prompt,
        "workflow_id": resolved_workflow_id,
        "status": "pending",
        "created_at": utc_now(),
    }
    if content:
        payload["content"] = content
    if options:
        payload["options"] = options
    if skill_name:
        payload["skill_name"] = skill_name
    if phase:
        payload["phase"] = phase
    if data:
        payload["data"] = data
    return payload


def build_workflow_state_payload(awaiting: dict[str, object]) -> dict[str, object]:
    workflow_state: dict[str, object] = {
        "workflow_id": str(awaiting.get("workflow_id") or ""),
        "status": "awaiting_user",
        "updated_at": utc_now(),
        "awaiting": {
            "request_id": awaiting.get("request_id"),
            "kind": awaiting.get("kind"),
            "prompt": awaiting.get("prompt"),
            **({"content": awaiting.get("content")} if awaiting.get("content") else {}),
            **({"options": awaiting.get("options")} if awaiting.get("options") else {}),
        },
    }
    for key in ("skill_name", "phase"):
        value = awaiting.get(key)
        if isinstance(value, str) and value:
            workflow_state[key] = value
    data = awaiting.get("data")
    if isinstance(data, dict) and data:
        workflow_state["data"] = data
    return workflow_state


def get_pending_awaiting_user_input(session: SessionRecord) -> dict[str, object] | None:
    raw = session.metadata.get(AWAITING_USER_INPUT_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    if raw.get("status") != "pending":
        return None
    if not isinstance(raw.get("prompt"), str) or not str(raw.get("prompt")).strip():
        return None
    return raw


def build_pending_user_input_reply_metadata(session: SessionRecord) -> dict[str, object] | None:
    awaiting = get_pending_awaiting_user_input(session)
    if awaiting is None:
        return None
    reply: dict[str, object] = {
        "request_id": awaiting.get("request_id"),
        "workflow_id": awaiting.get("workflow_id"),
        "kind": awaiting.get("kind"),
    }
    for key in ("skill_name", "phase"):
        value = awaiting.get(key)
        if isinstance(value, str) and value:
            reply[key] = value
    return reply


def build_workflow_state_prompt(session: SessionRecord) -> str:
    awaiting = get_pending_awaiting_user_input(session)
    workflow_state = session.metadata.get(WORKFLOW_STATE_METADATA_KEY)
    if awaiting is None and not isinstance(workflow_state, dict):
        return ""

    payload: dict[str, object] = {}
    if isinstance(workflow_state, dict):
        payload["workflow_state"] = workflow_state
    if awaiting is not None:
        payload["awaiting_user_input"] = awaiting

    return (
        "## Workflow State\n"
        "The session may be inside a multi-turn workflow. Treat this JSON as authoritative state.\n"
        "If `awaiting_user_input.status` is `pending`, the latest user message is likely the user's reply to that request. "
        "Continue from the stored phase. If the next workflow step requires confirmation, selection, or free-form input, "
        "call `request_user_input` instead of presenting it as a completed final answer.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )

