from __future__ import annotations

import json

from backend.memory.stable_context import StableContextLoader
from backend.runtime.collaboration_mode import build_collaboration_mode_prompt
from backend.runtime.message_rendering import build_user_message_for_provider
from backend.sessions.models import CheckpointRecord, SessionMessage, SessionRecord


COMMENTARY_SYSTEM_GUARDRAIL = (
    "CRITICAL TOOL/SKILL RULE:\n"
    "If you will call any tool or use any skill in this turn, you must output exactly one short "
    "<commentary>...</commentary> message immediately before the first tool or skill action.\n"
    "Do not skip it. Use the user's language. Do not put final-answer content inside <commentary>."
)


class PromptAssembler:
    def __init__(self, stable_context_loader: StableContextLoader):
        self.stable_context_loader = stable_context_loader

    def assemble(
        self,
        session: SessionRecord,
        tools_overview: str,
        checkpoint: CheckpointRecord | None,
        *,
        tool_message_overrides: dict[str, SessionMessage] | None = None,
    ) -> list[dict]:
        stable_context = self.stable_context_loader.build(tools_overview)
        system_sections = [
            f"{COMMENTARY_SYSTEM_GUARDRAIL}\n\n{stable_context}",
            build_collaboration_mode_prompt(session),
        ]
        overrides = tool_message_overrides or {}
        failed_tool_call_ids = {
            str(item.metadata.get("tool_call_id"))
            for item in session.messages
            if item.role == "tool"
            and item.metadata.get("success") is False
            and isinstance(item.metadata.get("tool_call_id"), str)
            and str(item.metadata.get("tool_call_id")).strip()
        }
        has_restored_checkpoint = any(
            item.role == "system" and item.metadata.get("type") == "checkpoint_restore"
            for item in session.messages
        )
        if checkpoint and not has_restored_checkpoint:
            system_sections.append(f"## Checkpoint Summary\n{checkpoint.summary}")
        messages = [{"role": "system", "content": "\n\n".join(system_sections)}]
        for item in session.messages:
            if item.role == "assistant":
                tool_calls = item.metadata.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    provider_tool_calls = []
                    for raw_tool_call in tool_calls:
                        if not isinstance(raw_tool_call, dict):
                            continue
                        tool_call_id = str(raw_tool_call.get("id") or "")
                        if tool_call_id and tool_call_id in failed_tool_call_ids:
                            continue
                        name = raw_tool_call.get("name")
                        arguments = raw_tool_call.get("arguments", {})
                        if not isinstance(name, str) or not name:
                            continue
                        provider_tool_calls.append(
                            {
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments, ensure_ascii=False),
                                },
                            }
                        )
                    message: dict[str, object] = {"role": item.role, "content": item.content}
                    if provider_tool_calls:
                        message["tool_calls"] = provider_tool_calls
                    messages.append(message)
                    continue

            if item.role == "tool":
                source_item = item
                tool_call_id = item.metadata.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id:
                    if tool_call_id in failed_tool_call_ids:
                        continue
                    override = overrides.get(tool_call_id)
                    if override is not None:
                        source_item = override
                message = {"role": source_item.role, "content": source_item.content}
                tool_call_id = source_item.metadata.get("tool_call_id") or item.metadata.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id:
                    message["tool_call_id"] = tool_call_id
                messages.append(message)
                continue

            content = build_user_message_for_provider(item) if item.role == "user" else item.content
            messages.append({"role": item.role, "content": content})
        return messages
