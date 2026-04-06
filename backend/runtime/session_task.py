from __future__ import annotations

from dataclasses import dataclass

from backend.sessions.models import SessionRecord
from backend.tools.permission_context import PermissionContext


@dataclass
class SessionTask:
    session: SessionRecord
    permission_context: PermissionContext
    tool_depth: int = 0
