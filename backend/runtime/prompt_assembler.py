from __future__ import annotations

from backend.memory.stable_context import StableContextLoader
from backend.sessions.models import CheckpointRecord, SessionRecord


class PromptAssembler:
    def __init__(self, stable_context_loader: StableContextLoader, workspace_path: str):
        self.stable_context_loader = stable_context_loader
        self.workspace_path = workspace_path

    def assemble(self, session: SessionRecord, tools_overview: str, approval_policy: str, checkpoint: CheckpointRecord | None) -> list[dict]:
        stable_context = self.stable_context_loader.build(tools_overview, approval_policy, self.workspace_path)
        messages = [{"role": "system", "content": stable_context}]
        if checkpoint:
            messages.append({"role": "system", "content": f"## Checkpoint Summary\n{checkpoint.summary}"})
        for item in session.messages:
            messages.append({"role": item.role, "content": item.content})
        return messages
