from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from backend.sandbox.resource_limits import ResourceLimits
from backend.sandbox.workspace_mount import resolve_workspace
from backend.tools.result import ToolExecutionResult


class DockerSandbox:
    def __init__(self, workspace: Path, limits: ResourceLimits, enabled: bool = False):
        self.workspace = resolve_workspace(workspace)
        self.limits = limits
        self.enabled = enabled

    async def execute_shell(self, command: str) -> ToolExecutionResult:
        return await self._execute(command, shell=True)

    async def execute_python(self, code: str) -> ToolExecutionResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.limits.timeout_seconds)
        except asyncio.TimeoutError:
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="python",
                category="timeout_error",
                summary="Python 执行超时",
                retryable=True,
            )

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        return ToolExecutionResult(
            success=proc.returncode == 0,
            tool="sandbox",
            action="python",
            category="success" if proc.returncode == 0 else "runtime_exception",
            exit_code=proc.returncode,
            summary="执行成功" if proc.returncode == 0 else "执行失败",
            stdout=_clip(stdout_text, self.limits.output_limit_bytes),
            stderr=_clip(stderr_text, self.limits.output_limit_bytes),
            retryable=proc.returncode != 0,
        )

    async def _execute(self, command: str, shell: bool) -> ToolExecutionResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.limits.timeout_seconds)
        except asyncio.TimeoutError:
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="timeout_error",
                summary="沙箱执行超时",
                retryable=True,
            )

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        clipped_stdout = _clip(stdout_text, self.limits.output_limit_bytes)
        clipped_stderr = _clip(stderr_text, self.limits.output_limit_bytes)
        return ToolExecutionResult(
            success=proc.returncode == 0,
            tool="sandbox",
            action="execute",
            category="success" if proc.returncode == 0 else "runtime_exception",
            exit_code=proc.returncode,
            summary="执行成功" if proc.returncode == 0 else "执行失败",
            stdout=clipped_stdout,
            stderr=clipped_stderr,
            retryable=proc.returncode != 0,
        )


def _clip(text: str, limit: int) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[-limit // 3 :]
    return f"{head}\n...\n{tail}"
