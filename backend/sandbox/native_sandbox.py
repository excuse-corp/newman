from __future__ import annotations

import asyncio
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from backend.config.schema import SandboxConfig
from backend.sandbox.linux_bwrap import build_bwrap_command, resolve_bwrap_executable
from backend.sandbox.resource_limits import ResourceLimits
from backend.sandbox.workspace_mount import resolve_workspace
from backend.tools.base import ToolOutputEmitter
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import PathAccessPolicy, coerce_path_access_policy


READ_CHUNK_SIZE = 2048
STREAM_TRUNCATED_NOTICE = "\n...[输出已截断]\n"


@dataclass(frozen=True)
class SandboxHealth:
    enabled: bool
    backend: str
    mode: str
    platform: str
    platform_supported: bool
    available: bool
    network_access: bool


@dataclass
class _StreamCapture:
    limit_bytes: int
    total_bytes: int = 0
    emitted_bytes: int = 0
    truncate_notice_emitted: bool = False
    prefix: bytearray = field(default_factory=bytearray)
    suffix: bytearray = field(default_factory=bytearray)

    def append(self, chunk: bytes) -> bytes:
        self.total_bytes += len(chunk)
        if self.limit_bytes > 0 and len(self.prefix) < self.limit_bytes:
            take = min(self.limit_bytes - len(self.prefix), len(chunk))
            self.prefix.extend(chunk[:take])

        if self.limit_bytes > 0:
            if len(chunk) >= self.limit_bytes:
                self.suffix = bytearray(chunk[-self.limit_bytes :])
            else:
                overflow = max(0, len(self.suffix) + len(chunk) - self.limit_bytes)
                if overflow:
                    del self.suffix[:overflow]
                self.suffix.extend(chunk)

        if self.limit_bytes <= 0 or self.emitted_bytes >= self.limit_bytes:
            return b""

        remaining = self.limit_bytes - self.emitted_bytes
        streamed = chunk[:remaining]
        self.emitted_bytes += len(streamed)
        return streamed

    def should_emit_notice(self) -> bool:
        return self.total_bytes > self.limit_bytes >= 0 and not self.truncate_notice_emitted

    def render_text(self) -> str:
        if self.total_bytes == 0 or self.limit_bytes <= 0:
            return ""
        if self.total_bytes <= self.limit_bytes:
            return bytes(self.prefix).decode("utf-8", errors="replace")

        segment = max(self.limit_bytes // 3, 1)
        head = bytes(self.prefix[:segment]).decode("utf-8", errors="replace").strip()
        tail = bytes(self.suffix[-segment:]).decode("utf-8", errors="replace").strip()
        if not head:
            return tail
        if not tail or head == tail:
            return head
        return f"{head}\n...\n{tail}"


class NativeSandbox:
    def __init__(
        self,
        workspace: Path,
        limits: ResourceLimits,
        config: SandboxConfig,
        path_policy: PathAccessPolicy | Path | None = None,
    ):
        self.workspace = resolve_workspace(workspace)
        self.limits = limits
        self.config = config
        self.path_policy = coerce_path_access_policy(path_policy or workspace)
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

    async def execute_shell(
        self,
        command: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        if not self.config.enabled or self.config.mode == "danger-full-access":
            result = await self._execute_direct(command, emit_output=emit_output)
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

        result = await self._execute_bwrap(command, emit_output=emit_output)
        result.metadata.update(
            {
                "sandboxed": True,
                "sandbox_backend": self.config.backend,
                "sandbox_mode": self.config.mode,
            }
        )
        return result

    async def _execute_direct(
        self,
        command: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if emit_output is not None:
                return await self._stream_process_output(
                    proc,
                    emit_output=emit_output,
                    timeout_summary="终端执行超时",
                )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.limits.timeout_seconds)
        except asyncio.TimeoutError:
            await _cleanup_process(proc)
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="timeout_error",
                summary="终端执行超时",
                retryable=True,
            )
        except asyncio.CancelledError:
            await _cleanup_process(proc)
            raise

        return _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)

    async def _execute_bwrap(
        self,
        command: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        readable_roots = self._resolve_readable_roots()
        writable_roots = self._resolve_writable_roots()
        protected_roots = self._resolve_protected_roots()
        argv = build_bwrap_command(
            bwrap_executable=self._bwrap_executable or "bwrap",
            workspace=self.workspace,
            readable_roots=readable_roots,
            writable_roots=writable_roots,
            protected_roots=protected_roots,
            mode=self.config.mode,
            network_access=self.config.network_access,
            command=command,
        )
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if emit_output is not None:
                return await self._stream_process_output(
                    proc,
                    emit_output=emit_output,
                    timeout_summary="Linux 原生沙箱执行超时",
                )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.limits.timeout_seconds)
        except asyncio.TimeoutError:
            await _cleanup_process(proc)
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="timeout_error",
                summary="Linux 原生沙箱执行超时",
                retryable=True,
            )
        except asyncio.CancelledError:
            await _cleanup_process(proc)
            raise

        return _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)

    async def _stream_process_output(
        self,
        proc: asyncio.subprocess.Process,
        *,
        emit_output: ToolOutputEmitter,
        timeout_summary: str,
    ) -> ToolExecutionResult:
        stdout_capture = _StreamCapture(self.limits.output_limit_bytes)
        stderr_capture = _StreamCapture(self.limits.output_limit_bytes)
        stdout_task = asyncio.create_task(
            _pump_output_stream(proc.stdout, "stdout", stdout_capture, emit_output)
        )
        stderr_task = asyncio.create_task(
            _pump_output_stream(proc.stderr, "stderr", stderr_capture, emit_output)
        )

        try:
            return_code = await asyncio.wait_for(proc.wait(), timeout=self.limits.timeout_seconds)
            await asyncio.gather(stdout_task, stderr_task)
        except asyncio.TimeoutError:
            await _terminate_streaming_process(proc)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="timeout_error",
                summary=timeout_summary,
                retryable=True,
            )
        except asyncio.CancelledError:
            await _terminate_streaming_process(proc)
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise

        return _result_from_stream_captures(return_code, stdout_capture, stderr_capture)

    def _resolve_readable_roots(self) -> list[Path]:
        return list(self.path_policy.readable_roots)

    def _resolve_writable_roots(self) -> list[Path]:
        if self.config.mode != "workspace-write":
            return []
        roots: list[Path] = []
        roots.extend(self.path_policy.writable_roots)
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

    def _resolve_protected_roots(self) -> list[Path]:
        return [path for path in self.path_policy.protected_roots if path.exists()]


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


def _result_from_stream_captures(
    return_code: int | None,
    stdout: _StreamCapture,
    stderr: _StreamCapture,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        success=return_code == 0,
        tool="sandbox",
        action="execute",
        category="success" if return_code == 0 else "runtime_exception",
        exit_code=return_code,
        summary="执行成功" if return_code == 0 else "执行失败",
        stdout=stdout.render_text(),
        stderr=stderr.render_text(),
        retryable=return_code != 0,
    )


async def _cleanup_process(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    with suppress(ProcessLookupError):
        proc.kill()
    with suppress(Exception):
        await proc.communicate()


async def _terminate_streaming_process(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    with suppress(ProcessLookupError):
        proc.kill()
    with suppress(Exception):
        await proc.wait()


async def _pump_output_stream(
    stream: asyncio.StreamReader | None,
    stream_name: str,
    capture: _StreamCapture,
    emit_output: ToolOutputEmitter,
) -> None:
    if stream is None:
        return

    while True:
        chunk = await stream.read(READ_CHUNK_SIZE)
        if not chunk:
            break

        streamed = capture.append(chunk)
        if streamed:
            text = streamed.decode("utf-8", errors="replace")
            if text:
                await emit_output(stream_name, text)

        if capture.should_emit_notice():
            capture.truncate_notice_emitted = True
            await emit_output(stream_name, STREAM_TRUNCATED_NOTICE)


def _clip(text: str, limit: int) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[-limit // 3 :]
    return f"{head}\n...\n{tail}"
