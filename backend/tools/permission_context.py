from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PermissionContext:
    deny_rules: set[str] = field(default_factory=set)

    def can_expose(self, tool_name: str) -> bool:
        return tool_name not in self.deny_rules
