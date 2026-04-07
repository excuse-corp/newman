from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.config.schema import SandboxConfig
from backend.sandbox.linux_bwrap import build_bwrap_command, resolve_bwrap_executable
from backend.sandbox.resource_limits import ResourceLimits
from backend.sandbox.workspace_mount import resolve_workspace
from backend.tools.result import ToolExecutionResult


@dataclass(frozen=True)
class SandboxHealth:
    enabled: bool
    backend: str
    mode: str
    platform: str
    platform_supported: bool
    available: bool
    network_access: bool


class NativeSandbox:
    def __init__(self, workspace: Path, limits: ResourceLimits, config: SandboxConfig):
        self.workspace = resolve_workspace(workspace)
        self.limits = limits
        self.config = config
        self.platform = sys.platform
        self._bwrap_executable = resolve_bwrap_executable() if self.platform == "linux" else None

    def health(self) -> SandboxHealth:
        if not self.config.enabled:
            return SandboxHealth(
                enabled=False,
                backend=self.config.backend,
                mode=self.config.mode,
                platform=self.platform,
                platform_supported=self.platform == "linux",
                available=True,
                network_access=self.config.network_access,
            )
        platform_supported = self.platform == "linux"
        available = platform_supported and self._bwrap_executable is not None
        return SandboxHealth(
            enabled=self.config.enabled,
            backend=self.config.backend,
            mode=self.config.mode,
            platform=self.platform,
            platform_supported=platform_supported,
            available=available,
            network_access=self.config.network_access,
        )

    async def execute_shell(self, command: str) -> ToolExecutionResult:
        if not self.config.enabled or self.config.mode == "danger-full-access":
            result = await self._execute_direct(command)
            result.metadata.update(
                {
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                }
            )
            return result

        if self.platform != "linux":
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="runtime_exception",
                summary=f"当前平台暂未实现原生沙箱: {self.platform}",
                metadata={
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                },
            )
        if self._bwrap_executable is None:
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="runtime_exception",
                summary="未找到 bwrap，无法启用 Linux 原生沙箱",
                metadata={
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                },
            )

        result = await self._execute_bwrap(command)
        result.metadata.update(
            {
                "sandboxed": True,
                "sandbox_backend": self.config.backend,
                "sandbox_mode": self.config.mode,
            }
        )
        return result

    async def _execute_direct(self, command: str) -> ToolExecutionResult:
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
                summary="终端执行超时",
                retryable=True,
            )

        return _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)

    async def _execute_bwrap(self, command: str) -> ToolExecutionResult:
        writable_roots = self._resolve_writable_roots()
        argv = build_bwrap_command(
            bwrap_executable=self._bwrap_executable or "bwrap",
            workspace=self.workspace,
            writable_roots=writable_roots,
            mode=self.config.mode,
            network_access=self.config.network_access,
            command=command,
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
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
                summary="Linux 原生沙箱执行超时",
                retryable=True,
            )

        return _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)

    def _resolve_writable_roots(self) -> list[Path]:
        roots: list[Path] = []
        if self.config.mode == "workspace-write":
            roots.append(self.workspace)
        for raw in self.config.writable_roots:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (self.workspace / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if candidate.exists():
                roots.append(candidate)
        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(root)
        return deduped


def _result_from_completed_process(
    return_code: int | None,
    stdout: bytes,
    stderr: bytes,
    output_limit_bytes: int,
) -> ToolExecutionResult:
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    return ToolExecutionResult(
        success=return_code == 0,
        tool="sandbox",
        action="execute",
        category="success" if return_code == 0 else "runtime_exception",
        exit_code=return_code,
        summary="执行成功" if return_code == 0 else "执行失败",
        stdout=_clip(stdout_text, output_limit_bytes),
        stderr=_clip(stderr_text, output_limit_bytes),
        retryable=return_code != 0,
    )


def _clip(text: str, limit: int) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[-limit // 3 :]
    return f"{head}\n...\n{tail}"
