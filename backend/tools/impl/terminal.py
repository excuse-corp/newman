from __future__ import annotations

from typing import Any

from backend.sandbox.docker_sandbox import DockerSandbox
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult


class TerminalTool(BaseTool):
    def __init__(self, sandbox: DockerSandbox):
        self.sandbox = sandbox
        self.meta = ToolMeta(
            name="terminal",
            description="Execute a shell command inside the sandbox.",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            risk_level="high",
            requires_approval=True,
            timeout_seconds=sandbox.limits.timeout_seconds,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        result = await self.sandbox.execute_shell(arguments["command"])
        result.tool = self.meta.name
        result.action = arguments["command"]
        return result
