from __future__ import annotations

from dataclasses import dataclass

from backend.sessions.models import SessionRecord
from backend.tools.permission_context import PermissionContext


@dataclass
class SessionTask:
    session: SessionRecord
    permission_context: PermissionContext
    turn_id: str | None = None
    tool_depth: int = 0
    action_group_index: int = 0

    def next_action_group_id(self) -> str:
        self.action_group_index += 1
        turn_key = self.turn_id or "turn"
        return f"{turn_key}:group:{self.action_group_index}"
