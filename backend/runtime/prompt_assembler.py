from __future__ import annotations

import json

from backend.memory.stable_context import StableContextLoader
from backend.sessions.models import CheckpointRecord, SessionRecord


COMMENTARY_SYSTEM_GUARDRAIL = (
    "CRITICAL TOOL/SKILL RULE:\n"
    "If you will call any tool or use any skill in this turn, you must output exactly one short "
    "<commentary>...</commentary> message immediately before the first tool or skill action.\n"
    "Do not skip it. Use the user's language. Do not put final-answer content inside <commentary>."
)


class PromptAssembler:
    def __init__(self, stable_context_loader: StableContextLoader, workspace_path: str):
        self.stable_context_loader = stable_context_loader
        self.workspace_path = workspace_path

    def assemble(self, session: SessionRecord, tools_overview: str, approval_policy: str, checkpoint: CheckpointRecord | None) -> list[dict]:
        stable_context = self.stable_context_loader.build(tools_overview, approval_policy, self.workspace_path)
        messages = [{"role": "system", "content": f"{COMMENTARY_SYSTEM_GUARDRAIL}\n\n{stable_context}"}]
        has_restored_checkpoint = any(
            item.role == "system" and item.metadata.get("type") == "checkpoint_restore"
            for item in session.messages
        )
        if checkpoint and not has_restored_checkpoint:
            messages.append({"role": "system", "content": f"## Checkpoint Summary\n{checkpoint.summary}"})
        for item in session.messages:
            if item.role == "assistant":
                tool_calls = item.metadata.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    provider_tool_calls = []
                    for raw_tool_call in tool_calls:
                        if not isinstance(raw_tool_call, dict):
                            continue
                        name = raw_tool_call.get("name")
                        arguments = raw_tool_call.get("arguments", {})
                        if not isinstance(name, str) or not name:
                            continue
                        provider_tool_calls.append(
                            {
                                "id": str(raw_tool_call.get("id") or ""),
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
                message = {"role": item.role, "content": item.content}
                tool_call_id = item.metadata.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id:
                    message["tool_call_id"] = tool_call_id
                messages.append(message)
                continue

            messages.append({"role": item.role, "content": item.content})
        return messages
