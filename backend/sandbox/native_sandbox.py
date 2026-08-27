from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping
from uuid import uuid4

from backend.config.schema import SandboxConfig
from backend.sandbox.linux_bwrap import build_bwrap_argv, build_bwrap_command, resolve_bwrap_executable
from backend.sandbox.environment import sanitize_environment
from backend.sandbox.resource_limits import ResourceLimits
from backend.sandbox.workspace_mount import resolve_workspace
from backend.tools.base import ToolOutputEmitter
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import PathAccessPolicy, coerce_path_access_policy


READ_CHUNK_SIZE = 2048
STREAM_TRUNCATED_NOTICE = "\n...[输出已截断]\n"
BWRAP_RUNNER_ERROR_PREFIXES = (
    "bwrap: can't find source path",
    "bwrap: creating new namespace failed",
    "bwrap: setting up uid map",
    "bwrap: execvp",
    "bwrap: setting up user namespace",
)


@dataclass(frozen=True)
class SandboxHealth:
    configured: bool
    enabled: bool
    backend: str
    selected_backend: str
    mode: str
    platform: str
    platform_supported: bool
    available: bool
    network_access: bool
    file_enforcement: str = "unsupported"
    network_enforcement: str = "unsupported"
    process_enforcement: str = "unsupported"
    resource_enforcement: str = "unsupported"
    probe_ok: bool | None = None
    probe_error: str = ""


class SandboxUnavailableError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


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
        extra_readable_roots: list[Path] | tuple[Path, ...] | None = None,
    ):
        self.workspace = resolve_workspace(workspace)
        self.limits = limits
        self.config = config
        self.path_policy = coerce_path_access_policy(path_policy or workspace)
        self.extra_readable_roots = tuple(Path(path).resolve() for path in (extra_readable_roots or ()))
        self.platform = sys.platform
        self._bwrap_executable = (
            resolve_bwrap_executable()
            if self.platform == "linux" and self.config.backend in {"auto", "linux_bwrap"}
            else None
        )
        self._probe_result: tuple[bool, str] | None = None

    def health(self) -> SandboxHealth:
        if not self.config.enabled:
            return SandboxHealth(
                configured=True,
                enabled=False,
                backend=self.config.backend,
                selected_backend="none",
                mode=self.config.mode,
                platform=self.platform,
                platform_supported=self.platform == "linux",
                available=False,
                network_access=self.config.network_access,
                probe_ok=None,
                probe_error="sandbox disabled",
            )
        platform_supported = self.platform == "linux"
        probe_ok = False
        probe_error = ""
        if platform_supported and self._bwrap_executable is not None:
            probe_ok, probe_error = self._functional_probe()
        available = platform_supported and self._bwrap_executable is not None and probe_ok and self.config.mode != "danger-full-access"
        selected_backend = "linux_bwrap" if platform_supported and self._bwrap_executable is not None else "none"
        file_enforcement = "full" if available else "unsupported"
        network_enforcement = "full" if available else "unsupported"
        process_enforcement = "full" if available else "unsupported"
        resource_enforcement = "partial" if available else "unsupported"
        return SandboxHealth(
            configured=True,
            enabled=self.config.enabled,
            backend=self.config.backend,
            selected_backend=selected_backend,
            mode=self.config.mode,
            platform=self.platform,
            platform_supported=platform_supported,
            available=available,
            network_access=self.config.network_access,
            file_enforcement=file_enforcement,
            network_enforcement=network_enforcement,
            process_enforcement=process_enforcement,
            resource_enforcement=resource_enforcement,
            probe_ok=probe_ok,
            probe_error=probe_error,
        )

    def _functional_probe(self) -> tuple[bool, str]:
        if self._probe_result is not None:
            return self._probe_result
        if self._bwrap_executable is None:
            self._probe_result = (False, "bwrap executable not found")
            return self._probe_result

        try:
            readable_roots = self._resolve_readable_roots()
            writable_roots = self._resolve_writable_roots()
            argv = build_bwrap_command(
                bwrap_executable=self._bwrap_executable,
                workspace=self.workspace,
                readable_roots=readable_roots,
                writable_roots=writable_roots,
                protected_roots=self._resolve_protected_roots(),
                mode=self.config.mode,
                network_access=self.config.network_access,
                command="true",
            )
            env, _filtered = sanitize_environment(
                allowlist=self.config.env_allowlist,
                workspace=self.workspace,
            )
            completed = subprocess.run(
                argv,
                cwd=str(self.workspace),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.config.probe_timeout_ms / 1000,
                check=False,
                text=True,
            )
        except subprocess.TimeoutExpired:
            self._probe_result = (False, "functional probe timed out")
        except OSError as exc:
            self._probe_result = (False, str(exc))
        else:
            if completed.returncode == 0:
                self._probe_result = (True, "")
            else:
                detail = (completed.stderr or completed.stdout or "probe exited non-zero").strip()
                self._probe_result = (False, detail[:500])
        return self._probe_result

    def prepare_argv(
        self,
        argv: Iterable[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        mode: str | None = None,
        network_access: bool | None = None,
        extra_readable_roots: Iterable[Path] | None = None,
        extra_writable_roots: Iterable[Path] | None = None,
    ) -> tuple[list[str], dict[str, str], Path, bool, list[str]]:
        """Build an exact argv/env/cwd tuple for a local child process.

        Long-lived processes such as stdio MCP servers cannot use
        ``execute_argv`` because their pipes remain open across requests. They
        still go through this same confinement path.
        """

        command_argv = [str(item) for item in argv]
        if not command_argv:
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", "缺少可执行命令")
        prepared_env, filtered_env = sanitize_environment(
            env,
            allowlist=self.config.env_allowlist,
            workspace=self.workspace,
        )
        effective_cwd = (cwd or self.workspace).resolve()
        if not effective_cwd.exists() or not effective_cwd.is_dir():
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", f"cwd 不存在或不是目录: {effective_cwd}")
        effective_mode = mode or self.config.mode
        effective_network = self.config.network_access if network_access is None else network_access
        if not self.config.enabled or effective_mode == "danger-full-access":
            return command_argv, prepared_env, effective_cwd, False, filtered_env
        if self.platform != "linux" or self._bwrap_executable is None:
            raise SandboxUnavailableError("SANDBOX_UNAVAILABLE", "当前平台或 bwrap 不支持受限本地进程")
        probe_ok, probe_error = self._functional_probe()
        if not probe_ok:
            raise SandboxUnavailableError("SANDBOX_PROBE_FAILED", probe_error or "bwrap functional probe failed")

        readable_roots = self._resolve_readable_roots(extra_readable_roots)
        writable_roots = self._resolve_writable_roots(extra_writable_roots, mode=effective_mode)
        if not _path_is_within_any(effective_cwd, [*readable_roots, *writable_roots]):
            raise SandboxUnavailableError("SANDBOX_INVALID_POLICY", f"cwd 不在沙箱可见目录内: {effective_cwd}")

        wrapped = build_bwrap_argv(
            bwrap_executable=self._bwrap_executable,
            workspace=effective_cwd,
            readable_roots=readable_roots,
            writable_roots=writable_roots,
            protected_roots=self._resolve_protected_roots(),
            mode=effective_mode,
            network_access=effective_network,
            argv=command_argv,
        )
        return wrapped, prepared_env, effective_cwd, True, filtered_env

    def execution_metadata(
        self,
        *,
        sandboxed: bool,
        mode: str | None = None,
        cwd: Path | None = None,
        network_access: bool | None = None,
        runner_started: bool = False,
        runner_failed: bool = False,
        sandbox_denied: bool = False,
        sandbox_escalated: bool = False,
        extra_readable_roots: Iterable[Path] | None = None,
        extra_writable_roots: Iterable[Path] | None = None,
        invocation_id: str | None = None,
        provider_detail: str = "",
    ) -> dict[str, object]:
        effective_mode = mode or self.config.mode
        effective_network = self.config.network_access if network_access is None else network_access
        backend = self.config.backend if sandboxed else ("none" if effective_mode == "danger-full-access" else self.config.backend)
        policy_hash = self._policy_hash(
            mode=effective_mode,
            cwd=cwd or self.workspace,
            network_access=effective_network,
            extra_readable_roots=extra_readable_roots,
            extra_writable_roots=extra_writable_roots,
        )
        if sandboxed:
            file_enforcement = "full"
            network_enforcement = "full"
            process_enforcement = "full"
        else:
            file_enforcement = "unsupported"
            network_enforcement = "unsupported"
            process_enforcement = "unsupported"
        return {
            "sandboxed": sandboxed,
            "backend": backend,
            "mode": effective_mode,
            "sandbox_backend": backend,
            "sandbox_mode": effective_mode,
            "file_enforcement": file_enforcement,
            "network_enforcement": network_enforcement,
            "process_enforcement": process_enforcement,
            "resource_enforcement": "partial" if sandboxed else "unsupported",
            "runner_started": runner_started,
            "runner_failed": runner_failed,
            "sandbox_runner_failed": runner_failed,
            "sandbox_denied": sandbox_denied,
            "sandbox_escalated": sandbox_escalated,
            "invocation_id": invocation_id or uuid4().hex,
            "policy_hash": policy_hash,
            "provider_detail": provider_detail or ("linux_bwrap" if sandboxed else "unsandboxed"),
        }

    def _policy_hash(
        self,
        *,
        mode: str,
        cwd: Path,
        network_access: bool,
        extra_readable_roots: Iterable[Path] | None = None,
        extra_writable_roots: Iterable[Path] | None = None,
    ) -> str:
        readable_roots = _canonical_roots(
            [
                self.workspace,
                self.path_policy.workspace,
                self.path_policy.browse_root,
                self.path_policy.output_root,
                *self.path_policy.readable_roots,
                *self.extra_readable_roots,
                *(extra_readable_roots or ()),
            ]
        )
        writable_inputs: list[Path] = []
        if mode == "workspace-write":
            writable_inputs.extend(self.path_policy.writable_roots)
            for raw in self.config.writable_roots:
                path = Path(raw)
                writable_inputs.append((self.workspace / path) if not path.is_absolute() else path)
            writable_inputs.extend(extra_writable_roots or ())
        payload = {
            "backend": self.config.backend,
            "mode": mode,
            "workspace": str(self.workspace.resolve()),
            "cwd": str(Path(cwd).resolve()),
            "network_access": network_access,
            "allow_partial_enforcement": self.config.allow_partial_enforcement,
            "readable_roots": readable_roots,
            "writable_roots": _canonical_roots(writable_inputs),
            "protected_roots": _canonical_roots(self.path_policy.protected_roots),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def execute_shell(
        self,
        command: str,
        emit_output: ToolOutputEmitter | None = None,
        *,
        force_unsandboxed: bool = False,
    ) -> ToolExecutionResult:
        invocation_id = uuid4().hex
        if force_unsandboxed or not self.config.enabled or self.config.mode == "danger-full-access":
            result = await self._execute_direct(command, emit_output=emit_output)
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=True,
                    sandbox_escalated=force_unsandboxed,
                    invocation_id=invocation_id,
                ),
            )
            if force_unsandboxed:
                result.metadata["sandbox_escalated"] = True
                result.metadata["sandbox_mode"] = "unsandboxed-retry"
            return result

        if self.platform != "linux":
            result = ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="runtime_exception",
                error_code="SANDBOX_UNAVAILABLE",
                summary=f"当前平台暂未实现原生沙箱: {self.platform}",
                metadata={
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                    "sandbox_runner_failed": True,
                    "sandbox_error_code": "SANDBOX_UNAVAILABLE",
                },
            )
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=False,
                    runner_failed=True,
                    invocation_id=invocation_id,
                    provider_detail=self.platform,
                ),
            )
            return result
        if self._bwrap_executable is None:
            result = ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="runtime_exception",
                error_code="SANDBOX_UNAVAILABLE",
                summary="未找到 bwrap，无法启用 Linux 原生沙箱",
                metadata={
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                    "sandbox_runner_failed": True,
                    "sandbox_error_code": "SANDBOX_UNAVAILABLE",
                },
            )
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=False,
                    runner_failed=True,
                    invocation_id=invocation_id,
                    provider_detail="bwrap missing",
                ),
            )
            return result

        probe_ok, probe_error = self._functional_probe()
        if not probe_ok:
            result = _sandbox_unavailable_result(
                code="SANDBOX_PROBE_FAILED",
                detail=probe_error or "bwrap functional probe failed",
                backend=self.config.backend,
                mode=self.config.mode,
            )
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=False,
                    runner_failed=True,
                    invocation_id=invocation_id,
                    provider_detail=probe_error or "probe failed",
                ),
            )
            return result

        _normalized_env, filtered_env = sanitize_environment(
            allowlist=self.config.env_allowlist,
            workspace=self.workspace,
        )
        result = await self._execute_bwrap(command, emit_output=emit_output)
        _merge_sandbox_metadata(
            result,
            self.execution_metadata(
                sandboxed=True,
                runner_started=True,
                runner_failed=bool(result.metadata.get("sandbox_runner_failed")),
                invocation_id=invocation_id,
                provider_detail="linux_bwrap",
            ),
            filtered_env=filtered_env,
        )
        return result

    async def execute_argv(
        self,
        argv: list[str],
        emit_output: ToolOutputEmitter | None = None,
        *,
        force_unsandboxed: bool = False,
        env: Mapping[str, str] | None = None,
        stdin_text: str | None = None,
        extra_readable_roots: Iterable[Path] | None = None,
        extra_writable_roots: Iterable[Path] | None = None,
    ) -> ToolExecutionResult:
        invocation_id = uuid4().hex
        if not argv:
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="validation_error",
                summary="缺少可执行命令",
                retryable=False,
            )

        normalized_env, filtered_env = sanitize_environment(
            env,
            allowlist=self.config.env_allowlist,
            workspace=self.workspace,
        )
        stdin_bytes = stdin_text.encode("utf-8") if stdin_text is not None else None

        if force_unsandboxed or not self.config.enabled or self.config.mode == "danger-full-access":
            result = await self._execute_direct_argv(argv, emit_output=emit_output, env=normalized_env, stdin_bytes=stdin_bytes)
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=True,
                    sandbox_escalated=force_unsandboxed,
                    invocation_id=invocation_id,
                ),
                filtered_env=filtered_env,
            )
            if force_unsandboxed:
                result.metadata["sandbox_escalated"] = True
                result.metadata["sandbox_mode"] = "unsandboxed-retry"
            return result

        if self.platform != "linux":
            result = ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="runtime_exception",
                error_code="SANDBOX_UNAVAILABLE",
                summary=f"当前平台暂未实现原生沙箱: {self.platform}",
                metadata={
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                    "sandbox_runner_failed": True,
                    "sandbox_error_code": "SANDBOX_UNAVAILABLE",
                },
            )
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=False,
                    runner_failed=True,
                    invocation_id=invocation_id,
                    provider_detail=self.platform,
                ),
            )
            return result
        if self._bwrap_executable is None:
            result = ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="runtime_exception",
                error_code="SANDBOX_UNAVAILABLE",
                summary="未找到 bwrap，无法启用 Linux 原生沙箱",
                metadata={
                    "sandboxed": False,
                    "sandbox_backend": self.config.backend,
                    "sandbox_mode": self.config.mode,
                    "sandbox_runner_failed": True,
                    "sandbox_error_code": "SANDBOX_UNAVAILABLE",
                },
            )
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=False,
                    runner_failed=True,
                    invocation_id=invocation_id,
                    provider_detail="bwrap missing",
                ),
            )
            return result

        probe_ok, probe_error = self._functional_probe()
        if not probe_ok:
            result = _sandbox_unavailable_result(
                code="SANDBOX_PROBE_FAILED",
                detail=probe_error or "bwrap functional probe failed",
                backend=self.config.backend,
                mode=self.config.mode,
            )
            _merge_sandbox_metadata(
                result,
                self.execution_metadata(
                    sandboxed=False,
                    runner_started=False,
                    runner_failed=True,
                    invocation_id=invocation_id,
                    provider_detail=probe_error or "probe failed",
                ),
            )
            return result

        result = await self._execute_bwrap_argv(
            argv,
            emit_output=emit_output,
            env=normalized_env,
            stdin_bytes=stdin_bytes,
            extra_readable_roots=extra_readable_roots,
            extra_writable_roots=extra_writable_roots,
        )
        _merge_sandbox_metadata(
            result,
            self.execution_metadata(
                sandboxed=True,
                runner_started=True,
                runner_failed=bool(result.metadata.get("sandbox_runner_failed")),
                extra_readable_roots=extra_readable_roots,
                extra_writable_roots=extra_writable_roots,
                invocation_id=invocation_id,
                provider_detail="linux_bwrap",
            ),
            filtered_env=filtered_env,
        )
        return result

    async def _execute_direct(
        self,
        command: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        proc: asyncio.subprocess.Process | None = None
        try:
            env, filtered_env = sanitize_environment(
                allowlist=self.config.env_allowlist,
                workspace=self.workspace,
            )
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if emit_output is not None:
                result = await self._stream_process_output(
                    proc,
                    emit_output=emit_output,
                    timeout_summary="终端执行超时",
                )
                result.metadata["sandbox_env_filtered"] = filtered_env
                return result
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

        result = _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)
        result.metadata["sandbox_env_filtered"] = filtered_env
        return result

    async def _execute_direct_argv(
        self,
        argv: list[str],
        *,
        emit_output: ToolOutputEmitter | None = None,
        env: Mapping[str, str] | None = None,
        stdin_bytes: bytes | None = None,
    ) -> ToolExecutionResult:
        proc: asyncio.subprocess.Process | None = None
        filtered_env: list[str] = []
        try:
            if env is None:
                prepared_env, filtered_env = sanitize_environment(
                    allowlist=self.config.env_allowlist,
                    workspace=self.workspace,
                )
            else:
                prepared_env = dict(env)
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.workspace),
                env=prepared_env,
                stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if emit_output is not None:
                stdin_task = _start_stdin_pump(proc, stdin_bytes)
                result = await self._stream_process_output(
                    proc,
                    emit_output=emit_output,
                    timeout_summary="命令执行超时",
                    stdin_task=stdin_task,
                )
                result.metadata["sandbox_env_filtered"] = filtered_env
                return result
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_bytes), timeout=self.limits.timeout_seconds)
        except asyncio.TimeoutError:
            await _cleanup_process(proc)
            return ToolExecutionResult(
                success=False,
                tool="sandbox",
                action="execute",
                category="timeout_error",
                summary="命令执行超时",
                retryable=True,
            )
        except asyncio.CancelledError:
            await _cleanup_process(proc)
            raise

        result = _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)
        result.metadata["sandbox_env_filtered"] = filtered_env
        return result

    async def _execute_bwrap(
        self,
        command: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        proc: asyncio.subprocess.Process | None = None
        try:
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
            env, _filtered = sanitize_environment(
                allowlist=self.config.env_allowlist,
                workspace=self.workspace,
            )
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.workspace),
                env=dict(env) if env is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if emit_output is not None:
                return await self._stream_process_output(
                    proc,
                    emit_output=emit_output,
                    timeout_summary="Linux 原生沙箱执行超时",
                    classify_bwrap=True,
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
        except OSError as exc:
            return _sandbox_runner_failure(exc)

        return _classify_bwrap_result(
            _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)
        )

    async def _execute_bwrap_argv(
        self,
        command_argv: list[str],
        *,
        emit_output: ToolOutputEmitter | None = None,
        env: Mapping[str, str] | None = None,
        stdin_bytes: bytes | None = None,
        extra_readable_roots: Iterable[Path] | None = None,
        extra_writable_roots: Iterable[Path] | None = None,
    ) -> ToolExecutionResult:
        proc: asyncio.subprocess.Process | None = None
        try:
            readable_roots = self._resolve_readable_roots(extra_readable_roots)
            writable_roots = self._resolve_writable_roots(extra_writable_roots)
            protected_roots = self._resolve_protected_roots()
            argv = build_bwrap_argv(
                bwrap_executable=self._bwrap_executable or "bwrap",
                workspace=self.workspace,
                readable_roots=readable_roots,
                writable_roots=writable_roots,
                protected_roots=protected_roots,
                mode=self.config.mode,
                network_access=self.config.network_access,
                argv=command_argv,
            )
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.workspace),
                env=dict(env) if env is not None else None,
                stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if emit_output is not None:
                stdin_task = _start_stdin_pump(proc, stdin_bytes)
                return await self._stream_process_output(
                    proc,
                    emit_output=emit_output,
                    timeout_summary="Linux 原生沙箱执行超时",
                    stdin_task=stdin_task,
                    classify_bwrap=True,
                )
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_bytes), timeout=self.limits.timeout_seconds)
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
        except OSError as exc:
            return _sandbox_runner_failure(exc)

        return _classify_bwrap_result(
            _result_from_completed_process(proc.returncode, stdout, stderr, self.limits.output_limit_bytes)
        )

    async def _stream_process_output(
        self,
        proc: asyncio.subprocess.Process,
        *,
        emit_output: ToolOutputEmitter,
        timeout_summary: str,
        stdin_task: asyncio.Task[None] | None = None,
        classify_bwrap: bool = False,
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
            await asyncio.gather(*(task for task in (stdin_task, stdout_task, stderr_task) if task is not None))
        except asyncio.TimeoutError:
            await _terminate_streaming_process(proc)
            tasks = [task for task in (stdin_task, stdout_task, stderr_task) if task is not None]
            await asyncio.gather(*tasks, return_exceptions=True)
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
            if stdin_task is not None:
                stdin_task.cancel()
            stdout_task.cancel()
            stderr_task.cancel()
            tasks = [task for task in (stdin_task, stdout_task, stderr_task) if task is not None]
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        result = _result_from_stream_captures(return_code, stdout_capture, stderr_capture)
        return _classify_bwrap_result(result) if classify_bwrap else result

    def _resolve_readable_roots(self, extra_roots: Iterable[Path] | None = None) -> list[Path]:
        roots = list(self.path_policy.readable_roots)
        roots.extend(path for path in self.extra_readable_roots if path.exists())
        if extra_roots is not None:
            roots.extend(Path(path).resolve() for path in extra_roots if Path(path).exists())
        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root.resolve())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(root.resolve())
        return deduped

    def _resolve_writable_roots(
        self,
        extra_roots: Iterable[Path] | None = None,
        *,
        mode: str | None = None,
    ) -> list[Path]:
        if (mode or self.config.mode) != "workspace-write":
            return []
        roots: list[Path] = []
        roots.extend(self.path_policy.writable_roots)
        for raw in self.config.writable_roots:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (self.workspace / candidate).resolve()
            else:
                candidate = candidate.resolve()
            roots.append(candidate)
        if extra_roots is not None:
            roots.extend(Path(path).resolve() for path in extra_roots)
        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            root = root.resolve()
            # bwrap rejects a bind source that does not exist. Materialize
            # configured writable directories before constructing argv so a
            # fresh workspace fails closed only for real policy errors.
            if not root.exists():
                root.mkdir(parents=True, exist_ok=True)
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


def _sandbox_runner_failure(exc: OSError) -> ToolExecutionResult:
    return ToolExecutionResult(
        success=False,
        tool="sandbox",
        action="execute",
        category="runtime_exception",
        error_code="SANDBOX_RUNNER_FAILED",
        summary="沙箱 runner 启动失败，未执行无沙箱重试",
        stderr=str(exc),
        retryable=False,
        metadata={
            "sandbox_runner_failed": True,
            "sandbox_error_code": "SANDBOX_RUNNER_FAILED",
        },
    )


def _sandbox_unavailable_result(*, code: str, detail: str, backend: str, mode: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        success=False,
        tool="sandbox",
        action="execute",
        category="runtime_exception",
        error_code=code,
        summary=detail,
        retryable=False,
        metadata={
            "sandboxed": False,
            "sandbox_backend": backend,
            "sandbox_mode": mode,
            "sandbox_runner_failed": True,
            "sandbox_error_code": code,
        },
    )


def _classify_bwrap_result(result: ToolExecutionResult) -> ToolExecutionResult:
    if result.success:
        return result
    first_line = next((line.strip().lower() for line in result.stderr.splitlines() if line.strip()), "")
    if any(first_line.startswith(prefix) for prefix in BWRAP_RUNNER_ERROR_PREFIXES):
        result.error_code = "SANDBOX_RUNNER_FAILED"
        result.retryable = False
        result.metadata.update(
            {
                "sandbox_runner_failed": True,
                "sandbox_error_code": "SANDBOX_RUNNER_FAILED",
            }
        )
    return result


def _merge_sandbox_metadata(
    result: ToolExecutionResult,
    base_metadata: Mapping[str, object],
    *,
    filtered_env: list[str] | None = None,
) -> ToolExecutionResult:
    existing = dict(result.metadata)
    result.metadata = {**base_metadata, **existing}
    if filtered_env is not None:
        result.metadata["sandbox_env_filtered"] = filtered_env
    if result.metadata.get("sandbox_runner_failed"):
        result.metadata["runner_failed"] = True
    if result.metadata.get("sandbox_error_code") and not result.error_code:
        result.error_code = str(result.metadata["sandbox_error_code"])
    return result


def _canonical_roots(paths: Iterable[Path]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        try:
            value = str(Path(raw).resolve())
        except OSError:
            value = str(Path(raw).absolute())
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return sorted(deduped)


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


def _start_stdin_pump(
    proc: asyncio.subprocess.Process,
    stdin_bytes: bytes | None,
) -> asyncio.Task[None] | None:
    if stdin_bytes is None or proc.stdin is None:
        return None
    return asyncio.create_task(_write_process_input(proc.stdin, stdin_bytes))


async def _write_process_input(
    stream: asyncio.StreamWriter | None,
    stdin_bytes: bytes,
) -> None:
    if stream is None:
        return
    try:
        stream.write(stdin_bytes)
        await stream.drain()
    finally:
        with suppress(Exception):
            stream.close()
        wait_closed = getattr(stream, "wait_closed", None)
        if callable(wait_closed):
            with suppress(Exception):
                await wait_closed()


def _clip(text: str, limit: int) -> str:
    if len(text.encode("utf-8")) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[-limit // 3 :]
    return f"{head}\n...\n{tail}"


def _path_is_within_any(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False
