from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from backend.sandbox.models import ConfinedArgv, PreparedSandboxInvocation, SandboxPolicy, SandboxRunRequest, SandboxRunResult
from backend.sandbox.native_sandbox import SandboxUnavailableError
from backend.sandbox.environment import sanitize_environment
from backend.sandbox.classifier import matches_denial_signature, matches_runner_failure
from backend.tools.base import ToolOutputEmitter
from backend.tools.result import ToolExecutionResult


@dataclass(frozen=True)
class SandboxStdioProcess:
    process: asyncio.subprocess.Process
    argv: tuple[str, ...]
    cwd: Path
    sandboxed: bool
    metadata: Mapping[str, object]
    filtered_env: tuple[str, ...] = ()
    cleanup: Callable[[], Awaitable[None]] | None = None
    process_group: bool = False

    async def terminate(self) -> None:
        try:
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    await _cleanup_process(self.process, process_group=self.process_group)
        finally:
            await _run_cleanup(self.cleanup)


class SandboxProcessRunner:
    """Migration-period v2 runner facade backed by NativeSandbox.

    New local process entrypoints should depend on this exact-argv API. During
    the refactor, it delegates to the existing NativeSandbox implementation so
    terminal/plugin callers keep their proven behavior while stdio-style callers
    can share policy metadata and fail-closed preparation.
    """

    def __init__(self, native_sandbox, provider=None):
        self._native = native_sandbox
        self._provider = provider

    async def run_argv(self, request: SandboxRunRequest) -> SandboxRunResult:
        _validate_exact_argv(request.argv)
        if self._provider is not None:
            return await self._run_provider_argv(request)
        result: ToolExecutionResult = await self._native.execute_argv(
            list(request.argv),
            env=request.env,
            stdin_text=_stdin_text(request.stdin),
            extra_readable_roots=request.policy.readable_roots,
            extra_writable_roots=request.policy.writable_roots,
        )
        return _to_run_result(result)

    async def run_argv_tool_result(
        self,
        request: SandboxRunRequest,
        *,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        _validate_exact_argv(request.argv)
        if self._provider is None:
            return await self._native.execute_argv(
                list(request.argv),
                emit_output=emit_output,
                env=request.env,
                stdin_text=_stdin_text(request.stdin),
                extra_readable_roots=request.policy.readable_roots,
                extra_writable_roots=request.policy.writable_roots,
            )
        result = await self._run_provider_argv(request)
        if emit_output is not None:
            if result.stdout:
                await emit_output("stdout", result.stdout.decode("utf-8", errors="replace"))
            if result.stderr:
                await emit_output("stderr", result.stderr.decode("utf-8", errors="replace"))
        return _to_tool_result(result)

    async def run_shell_tool_result(
        self,
        command: str,
        policy: SandboxPolicy,
        *,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        if self._provider is None:
            return await self._native.execute_shell(command, emit_output=emit_output)
        shell = "/usr/bin/bash" if Path("/usr/bin/bash").exists() else "bash"
        return await self.run_argv_tool_result(
            SandboxRunRequest(
                argv=(shell, "--noprofile", "--norc", "-lc", command),
                policy=policy,
            ),
            emit_output=emit_output,
        )

    async def start_stdio(self, request: SandboxRunRequest) -> SandboxStdioProcess:
        _validate_exact_argv(request.argv)
        if self._provider is not None:
            return await self._start_provider_stdio(request)
        argv, env, cwd, sandboxed, filtered_env = self.prepare_argv(request.argv, request.policy, request.env)
        metadata = self._native.execution_metadata(
            sandboxed=sandboxed,
            mode=request.policy.mode,
            cwd=cwd,
            network_access=request.policy.network_access,
            runner_started=True,
            extra_readable_roots=request.policy.readable_roots,
            extra_writable_roots=request.policy.writable_roots,
            provider_detail="linux_bwrap" if sandboxed else "unsandboxed",
        )
        metadata["sandbox_env_filtered"] = filtered_env
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return SandboxStdioProcess(
            process=proc,
            argv=tuple(argv),
            cwd=cwd,
            sandboxed=sandboxed,
            metadata=metadata,
            filtered_env=tuple(filtered_env),
        )

    async def _run_provider_argv(self, request: SandboxRunRequest) -> SandboxRunResult:
        try:
            prepared, filtered_env = self._prepare_provider_invocation(request)
        except SandboxUnavailableError as exc:
            return _provider_failure_result(
                exc.code,
                exc.detail,
                request,
                backend=getattr(self._provider, "name", "unknown"),
            )
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *prepared.argv,
                cwd=str(prepared.cwd),
                env=dict(prepared.env),
                stdin=asyncio.subprocess.PIPE if request.stdin is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=prepared.preexec_fn,
                start_new_session=prepared.start_new_session,
            )
            communicate = process.communicate(request.stdin)
            if request.policy.timeout_seconds is not None:
                stdout, stderr = await asyncio.wait_for(communicate, timeout=request.policy.timeout_seconds)
            else:
                stdout, stderr = await communicate
        except asyncio.TimeoutError:
            await _cleanup_process(process, process_group=prepared.start_new_session)
            metadata = _provider_metadata(prepared, filtered_env, runner_started=True)
            metadata["sandbox_error_code"] = "SANDBOX_TIMEOUT"
            result = SandboxRunResult(
                returncode=None,
                stdout=b"",
                stderr=b"sandboxed process timed out",
                error_code="SANDBOX_TIMEOUT",
                error_message="sandboxed process timed out",
                metadata=metadata,
            )
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            await _cleanup_process(process, process_group=prepared.start_new_session)
            metadata = _provider_metadata(prepared, filtered_env, runner_started=False)
            metadata.update(
                {
                    "runner_failed": True,
                    "sandbox_runner_failed": True,
                    "sandbox_error_code": "SANDBOX_RUNNER_FAILED",
                }
            )
            result = SandboxRunResult(
                returncode=None,
                stdout=b"",
                stderr=str(exc).encode("utf-8", errors="replace"),
                error_code="SANDBOX_RUNNER_FAILED",
                error_message="sandbox runner failed before command execution",
                metadata=metadata,
            )
        else:
            metadata = _provider_metadata(prepared, filtered_env, runner_started=True)
            error_code, error_message = _provider_exit_error(prepared, process.returncode, stderr, metadata)
            result = SandboxRunResult(
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                error_code=error_code,
                error_message=error_message,
                metadata=metadata,
            )
        finally:
            await _run_cleanup(prepared.cleanup)
        return result

    async def _start_provider_stdio(self, request: SandboxRunRequest) -> SandboxStdioProcess:
        prepared, filtered_env = self._prepare_provider_invocation(request)
        try:
            process = await asyncio.create_subprocess_exec(
                *prepared.argv,
                cwd=str(prepared.cwd),
                env=dict(prepared.env),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=prepared.preexec_fn,
                start_new_session=prepared.start_new_session,
            )
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            await _run_cleanup(prepared.cleanup)
            raise SandboxUnavailableError("SANDBOX_RUNNER_FAILED", str(exc)) from exc
        return SandboxStdioProcess(
            process=process,
            argv=tuple(prepared.argv),
            cwd=prepared.cwd,
            sandboxed=prepared.file_enforcement != "unsupported",
            metadata=_provider_metadata(prepared, filtered_env, runner_started=True),
            filtered_env=tuple(filtered_env),
            cleanup=prepared.cleanup,
            process_group=prepared.start_new_session,
        )

    def _prepare_provider_invocation(
        self,
        request: SandboxRunRequest,
    ) -> tuple[PreparedSandboxInvocation, list[str]]:
        prepare = getattr(self._provider, "prepare", None)
        if callable(prepare):
            prepared = prepare(request.argv, request.policy, request.env)
            filtered_env = list(prepared.metadata.get("sandbox_env_filtered", ()))
            return prepared, filtered_env

        confined: ConfinedArgv = self._provider.confine(request.argv, request.policy)
        env, filtered_env = sanitize_environment(
            request.env,
            allowlist=request.policy.env_allowlist,
            workspace=request.policy.workspace_root,
        )
        prepared = PreparedSandboxInvocation(
            argv=confined.argv,
            env=env,
            cwd=request.policy.cwd,
            backend=confined.backend,
            file_enforcement=confined.file_enforcement,
            network_enforcement=confined.network_enforcement,
            process_visibility_enforcement=confined.process_visibility_enforcement,
            process_lifecycle_enforcement=confined.process_lifecycle_enforcement,
            resource_enforcement=confined.resource_enforcement,
            denial_signatures=confined.denial_signatures,
            runner_failure_rules=confined.runner_failure_rules,
            notes=confined.notes,
            metadata=confined.metadata,
            preexec_fn=confined.preexec_fn,
        )
        return prepared, filtered_env

    def prepare_argv(
        self,
        argv: tuple[str, ...],
        policy: SandboxPolicy,
        env: Mapping[str, str] | None = None,
    ) -> tuple[list[str], dict[str, str], Path, bool, list[str]]:
        _validate_exact_argv(argv)
        return self._native.prepare_argv(
            argv,
            env=env,
            cwd=policy.cwd,
            mode=policy.mode,
            network_access=policy.network_access,
            extra_readable_roots=policy.readable_roots,
            extra_writable_roots=policy.writable_roots,
        )


def _validate_exact_argv(argv: tuple[str, ...]) -> None:
    if not argv:
        raise ValueError("sandbox runner requires exact argv")
    if any(not isinstance(item, str) or item == "" for item in argv):
        raise ValueError("sandbox runner argv entries must be non-empty strings")


def _stdin_text(stdin: bytes | None) -> str | None:
    if stdin is None:
        return None
    return stdin.decode("utf-8", errors="replace")


def _to_run_result(result: ToolExecutionResult) -> SandboxRunResult:
    return SandboxRunResult(
        returncode=result.exit_code,
        stdout=result.stdout.encode("utf-8"),
        stderr=result.stderr.encode("utf-8"),
        error_code=result.error_code or None,
        error_message=result.summary if not result.success else None,
        metadata=result.metadata,
    )


def _to_tool_result(result: SandboxRunResult) -> ToolExecutionResult:
    success = result.returncode == 0 and not result.error_code
    return ToolExecutionResult(
        success=success,
        tool="sandbox",
        action="execute",
        category="success" if success else "runtime_exception",
        error_code=result.error_code or "",
        exit_code=result.returncode,
        summary="执行成功" if success else (result.error_message or "执行失败"),
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
        retryable=not success,
        metadata=dict(result.metadata),
    )


def _provider_metadata(confined, filtered_env: list[str], *, runner_started: bool) -> dict[str, object]:
    process_visibility = getattr(confined, "process_visibility_enforcement", "unsupported")
    process_lifecycle = getattr(confined, "process_lifecycle_enforcement", "unsupported")
    process_enforcement = getattr(confined, "process_enforcement", None) or _combined_process_enforcement(
        process_visibility,
        process_lifecycle,
    )
    metadata = dict(getattr(confined, "metadata", {}) or {})
    metadata.update({
        "sandboxed": confined.file_enforcement != "unsupported",
        "sandbox_backend": confined.backend,
        "backend": confined.backend,
        "file_enforcement": confined.file_enforcement,
        "network_enforcement": confined.network_enforcement,
        "process_enforcement": process_enforcement,
        "process_visibility_enforcement": process_visibility,
        "process_lifecycle_enforcement": process_lifecycle,
        "resource_enforcement": confined.resource_enforcement,
        "runner_started": runner_started,
        "runner_failed": False,
        "sandbox_runner_failed": False,
        "sandbox_denied": False,
        "sandbox_escalated": False,
        "sandbox_env_filtered": filtered_env,
        "provider_detail": "; ".join(confined.notes),
    })
    return metadata


def _combined_process_enforcement(visibility: str, lifecycle: str) -> str:
    if visibility == lifecycle:
        return visibility
    if "partial" in {visibility, lifecycle}:
        return "partial"
    if "full" in {visibility, lifecycle}:
        return "partial"
    return "unsupported"


def _provider_exit_error(
    confined,
    returncode: int | None,
    stderr: bytes,
    metadata: dict[str, object],
) -> tuple[str | None, str | None]:
    if returncode == 0:
        return None, None
    stderr_text = stderr.decode("utf-8", errors="replace")
    if matches_runner_failure(returncode, stderr_text, tuple(getattr(confined, "runner_failure_rules", ()))):
        metadata.update(
            {
                "runner_failed": True,
                "sandbox_runner_failed": True,
                "sandbox_error_code": "SANDBOX_RUNNER_FAILED",
            }
        )
        return "SANDBOX_RUNNER_FAILED", "sandbox runner failed before command execution"
    if matches_denial_signature(stderr_text, tuple(getattr(confined, "denial_signatures", ()))):
        metadata.update(
            {
                "sandbox_denied": True,
                "sandbox_error_code": "SANDBOX_DENIED",
            }
        )
        return "SANDBOX_DENIED", stderr_text
    return "COMMAND_FAILED", stderr_text


def _provider_failure_result(code: str, detail: str, request: SandboxRunRequest, *, backend: str) -> SandboxRunResult:
    return SandboxRunResult(
        returncode=None,
        stdout=b"",
        stderr=detail.encode("utf-8", errors="replace"),
        error_code=code,
        error_message=detail,
        metadata={
            "sandboxed": False,
            "sandbox_backend": backend,
            "backend": backend,
            "sandbox_mode": request.policy.mode,
            "file_enforcement": "unsupported",
            "network_enforcement": "unsupported",
            "process_enforcement": "unsupported",
            "process_visibility_enforcement": "unsupported",
            "process_lifecycle_enforcement": "unsupported",
            "resource_enforcement": "unsupported",
            "runner_started": False,
            "runner_failed": True,
            "sandbox_runner_failed": True,
            "sandbox_denied": False,
            "sandbox_escalated": False,
            "sandbox_error_code": code,
        },
    )


async def _cleanup_process(process: asyncio.subprocess.Process | None, *, process_group: bool = False) -> None:
    if process is None or process.returncode is not None:
        return
    try:
        if process_group and os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    await process.communicate()


async def _run_cleanup(cleanup: Callable[[], Awaitable[None]] | None) -> None:
    if cleanup is None:
        return
    try:
        await cleanup()
    except Exception:
        # Cleanup failures must not mask the command or runner failure. Providers
        # should surface persistent cleanup problems in health/audit paths.
        return
