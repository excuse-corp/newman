from __future__ import annotations

import re
from typing import Any

from backend.runtime.workflow_state import (
    AWAITING_USER_INPUT_METADATA_KEY,
    TURN_OUTCOME_AWAITING_USER,
    WORKFLOW_STATE_METADATA_KEY,
    build_awaiting_user_input_payload,
    build_workflow_state_payload,
)
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import CORE_TOOL_GROUP
from backend.tools.result import ToolExecutionResult


class RequestUserInputTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="request_user_input",
            description=(
                "Pause the current turn and request structured input from the user. Use this for workflow gates such "
                "as confirmation, option selection, or free-form revisions. Do not use a normal final answer when the "
                "next step must wait for the user. When the user can choose from known alternatives, use kind='choice' "
                "and pass concise options with label/value/description instead of embedding a numbered list only in "
                "the prompt. Use kind='free_text' only when the user must type custom information."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["confirm", "choice", "free_text"],
                        "description": "Type of user input needed.",
                    },
                    "prompt": {
                        "type": "string",
                        "minLength": 1,
                        "description": "The direct question or instruction shown to the user.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Optional content the user is being asked to approve or revise.",
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "minLength": 1},
                                "value": {"type": "string", "minLength": 1},
                                "description": {"type": "string"},
                            },
                            "required": ["label", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "workflow_id": {
                        "type": "string",
                        "description": "Stable workflow id when continuing an existing workflow.",
                    },
                    "skill_name": {
                        "type": "string",
                        "description": "Skill or workflow name, e.g. html-ppt.",
                    },
                    "phase": {
                        "type": "string",
                        "description": "Current workflow phase, e.g. outline, color_selection, slide_plan.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Small structured state needed to continue later.",
                    },
                },
                "required": ["kind", "prompt"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=5,
            provider_group=CORE_TOOL_GROUP,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        kind = str(arguments.get("kind") or "").strip()
        prompt = str(arguments.get("prompt") or "").strip()
        content = str(arguments.get("content") or "").strip()
        options = _normalize_options(arguments.get("options"))

        if not options:
            options = _extract_enumerated_options(prompt)
        if kind in {"confirm", "choice"} and not options:
            options = _default_options_for_kind(kind)
        if kind == "choice" and len(options) < 2:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="request",
                category="validation_error",
                summary="choice 类型至少需要两个选项",
            )

        data = arguments.get("data")
        state_data = data if isinstance(data, dict) else None
        awaiting = build_awaiting_user_input_payload(
            kind=kind,
            prompt=prompt,
            content=content or None,
            options=options,
            workflow_id=_clean_optional_string(arguments.get("workflow_id")),
            skill_name=_clean_optional_string(arguments.get("skill_name")),
            phase=_clean_optional_string(arguments.get("phase")),
            data=state_data,
        )
        workflow_state = build_workflow_state_payload(awaiting)
        rendered = _render_user_input_request(awaiting)
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="request",
            summary="已请求用户输入，当前回合暂停等待回复",
            stdout=rendered,
            persisted_output=rendered,
            metadata={
                "turn_outcome": TURN_OUTCOME_AWAITING_USER,
                "assistant_response": {"content": rendered},
                AWAITING_USER_INPUT_METADATA_KEY: awaiting,
                WORKFLOW_STATE_METADATA_KEY: workflow_state,
                "session_metadata_updates": {
                    AWAITING_USER_INPUT_METADATA_KEY: awaiting,
                    WORKFLOW_STATE_METADATA_KEY: workflow_state,
                },
            },
        )


def _clean_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_options(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    options: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _clean_optional_string(item.get("label"))
        option_value = _clean_optional_string(item.get("value"))
        if not label or not option_value:
            continue
        option: dict[str, object] = {"label": label, "value": option_value}
        description = _clean_optional_string(item.get("description"))
        if description:
            option["description"] = description
        options.append(option)
    return options


def _extract_enumerated_options(prompt: str) -> list[dict[str, object]]:
    matches = list(re.finditer(r"(?:^|[\s\n:：，,；;])([1-9]\d*)[.．、)]\s*", prompt))
    if len(matches) < 2:
        return []

    options: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
        raw_text = re.sub(r"\s+", " ", prompt[start:end]).strip()
        if not raw_text:
            continue
        label, description = _split_enumerated_option_text(raw_text)
        if not label:
            continue
        option: dict[str, object] = {
            "label": label,
            "value": f"option_{match.group(1) or index + 1}",
        }
        if description:
            option["description"] = description
        options.append(option)
    return options if len(options) >= 2 else []


def _split_enumerated_option_text(text: str) -> tuple[str, str | None]:
    match = re.search(r"[?？。.!！]\s*(?=(如果|如需|请|需要|可提供|补充))", text)
    if match is None:
        return text.strip(), None
    boundary = match.end()
    label = text[:boundary].strip()
    description = text[boundary:].strip()
    return label, description or None


def _default_options_for_kind(kind: str) -> list[dict[str, object]]:
    if kind == "confirm":
        return [
            {"label": "确认，继续", "value": "approved"},
            {"label": "需要修改", "value": "revise"},
        ]
    return []


def _render_user_input_request(awaiting: dict[str, object]) -> str:
    lines: list[str] = []
    content = awaiting.get("content")
    if isinstance(content, str) and content.strip():
        lines.append(content.strip())
        lines.append("")

    prompt = awaiting.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        lines.append(prompt.strip())

    options = awaiting.get("options")
    if isinstance(options, list) and options:
        lines.append("")
        lines.append("选项：")
        for index, item in enumerate(options, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            description = str(item.get("description") or "").strip()
            if not label:
                continue
            suffix = f" - {description}" if description else ""
            value_part = f" (`{value}`)" if value else ""
            lines.append(f"{index}. {label}{value_part}{suffix}")
    return "\n".join(lines).strip()


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [RequestUserInputTool()]
