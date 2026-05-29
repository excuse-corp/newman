from __future__ import annotations

import mimetypes
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.sandbox.native_sandbox import NativeSandbox
from backend.tools.base import BaseTool, ToolMeta, ToolOutputEmitter
from backend.tools.discovery import BuiltinToolContext
from backend.tools.router import analyze_terminal_command
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import (
    PathAccessPolicy,
    classify_path,
    display_path,
    iter_workspace_files,
    resolve_requested_path,
)

_FILE_NOT_FOUND_PATTERN = re.compile(r"No such file or directory")
_LIKELY_PATH_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{1,12}$")
_SHELL_OPERATOR_TOKENS = {"|", "||", "&&", ";", ">", ">>", "<", "<<", "<<-", "2>", "1>"}


@dataclass(frozen=True)
class _FileSnapshot:
    exists: bool
    size_bytes: int | None
    mtime_ns: int | None


class TerminalTool(BaseTool):
    def __init__(self, sandbox: NativeSandbox, path_policy: PathAccessPolicy | None = None):
        self.sandbox = sandbox
        self.policy = path_policy
        self._writable_roots = list(path_policy.writable_roots) if path_policy else []
        allowed = [str(p) for p in self._writable_roots] if self._writable_roots else []
        self.meta = ToolMeta(
            name="terminal",
            description="Execute a shell command inside the native sandbox.",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            risk_level="high",
            timeout_seconds=sandbox.limits.timeout_seconds,
            approval_behavior="confirmable",
            allowed_paths=allowed or None,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        return await self._execute_command(
            arguments["command"],
            turn_output_dir=_coerce_turn_output_dir(arguments.get("__turn_output_dir")),
        )

    async def run_streaming(
        self,
        arguments: dict[str, Any],
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        return await self._execute_command(
            arguments["command"],
            emit_output=emit_output,
            turn_output_dir=_coerce_turn_output_dir(arguments.get("__turn_output_dir")),
        )

    async def run_streaming_escalated(
        self,
        arguments: dict[str, Any],
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        return await self._execute_command(
            arguments["command"],
            emit_output=emit_output,
            force_unsandboxed=True,
            turn_output_dir=_coerce_turn_output_dir(arguments.get("__turn_output_dir")),
        )

    async def _execute_command(
        self,
        command: str,
        *,
        emit_output: ToolOutputEmitter | None = None,
        force_unsandboxed: bool = False,
        turn_output_dir: Path | None = None,
    ) -> ToolExecutionResult:
        if turn_output_dir is not None:
            turn_output_dir.mkdir(parents=True, exist_ok=True)
        output_candidates_before = _collect_output_candidates(command, self.policy, turn_output_dir=turn_output_dir)
        before = _snapshot_files(output_candidates_before)
        result = await self.sandbox.execute_shell(
            command,
            emit_output=emit_output,
            force_unsandboxed=force_unsandboxed,
        )
        result.tool = self.meta.name
        result.action = command
        result = _enrich_file_not_found(result, self._writable_roots)
        output_candidates_after = _collect_output_candidates(command, self.policy, turn_output_dir=turn_output_dir)
        _record_output_files(
            result,
            _merge_candidate_paths(output_candidates_before, output_candidates_after),
            before,
            self.policy,
        )
        return result


def _enrich_file_not_found(
    result: ToolExecutionResult, writable_roots: list[Path]
) -> ToolExecutionResult:
    if result.success:
        return result
    stderr = result.stderr or ""
    if not _FILE_NOT_FOUND_PATTERN.search(stderr):
        return result
    roots_str = ", ".join(str(p) for p in writable_roots)
    hint = (
        f"\n\n[路径提示] 文件或目录不存在，可能是因为路径不在沙箱可写范围内。"
        f"沙箱可写路径: {roots_str}。"
        f"请将文件写入上述可写路径之一。"
    )
    result.stderr = stderr + hint
    return result


def _record_output_files(
    result: ToolExecutionResult,
    candidates: tuple[Path, ...],
    before: dict[str, _FileSnapshot],
    policy: PathAccessPolicy | None,
) -> None:
    output_files: list[dict[str, Any]] = []
    for candidate in candidates:
        key = str(candidate.resolve())
        current = _snapshot_file(candidate)
        previous = before.get(key, _FileSnapshot(False, None, None))
        if not current.exists:
            continue
        if previous.exists and previous.size_bytes == current.size_bytes and previous.mtime_ns == current.mtime_ns:
            continue

        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        payload: dict[str, Any] = {
            "path": key,
            "bytes": current.size_bytes,
            "content_type": content_type,
            "created": not previous.exists,
            "summary": (
                f"终端命令生成文件 {display_path(policy, candidate) if policy is not None else candidate.name}"
                if not previous.exists
                else f"终端命令更新文件 {display_path(policy, candidate) if policy is not None else candidate.name}"
            ),
        }
        if policy is not None:
            try:
                payload["workspace_relative_path"] = str(candidate.resolve().relative_to(policy.workspace.resolve()))
            except ValueError:
                pass
        output_files.append(payload)

    if not output_files:
        return
    output_files.sort(key=lambda item: str(item.get("path", "")))
    result.metadata["output_files"] = output_files
    if len(output_files) == 1:
        first = output_files[0]
        for key in ("path", "bytes", "content_type", "created"):
            value = first.get(key)
            if value is not None and key not in result.metadata:
                result.metadata[key] = value


def _snapshot_files(candidates: tuple[Path, ...]) -> dict[str, _FileSnapshot]:
    snapshots: dict[str, _FileSnapshot] = {}
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            continue
        snapshots[key] = _snapshot_file(candidate)
    return snapshots


def _snapshot_file(path: Path) -> _FileSnapshot:
    try:
        resolved = path.resolve()
    except OSError:
        return _FileSnapshot(False, None, None)
    if not resolved.exists() or not resolved.is_file():
        return _FileSnapshot(False, None, None)
    stat = resolved.stat()
    return _FileSnapshot(True, stat.st_size, stat.st_mtime_ns)


def _collect_output_candidates(
    command: str,
    policy: PathAccessPolicy | None,
    *,
    turn_output_dir: Path | None = None,
) -> tuple[Path, ...]:
    if policy is None:
        return ()
    analysis = analyze_terminal_command(command, policy)

    candidates: dict[str, Path] = {}
    for candidate in _list_primary_output_files(policy, turn_output_dir=turn_output_dir):
        candidates[str(candidate.resolve())] = candidate.resolve()

    for match in analysis.path_matches:
        if match.state != "writable":
            continue
        candidates[str(match.path.resolve())] = match.path.resolve()

    tokens = _split_command_tokens(command)
    for index, token in enumerate(tokens):
        if index == 0 and "=" not in token:
            continue
        for raw in _token_path_candidates(token, policy.workspace):
            path = resolve_requested_path(policy, raw)
            if classify_path(policy, path) != "writable":
                continue
            try:
                resolved = path.resolve()
            except OSError:
                continue
            candidates[str(resolved)] = resolved

    return tuple(sorted(candidates.values(), key=str))


def _list_primary_output_files(policy: PathAccessPolicy, *, turn_output_dir: Path | None = None) -> tuple[Path, ...]:
    output_dir = turn_output_dir or (policy.workspace / "outputs")
    if not output_dir.exists():
        return ()
    try:
        return tuple(iter_workspace_files(output_dir, policy.workspace, include_hidden=False))
    except OSError:
        return ()


def _coerce_turn_output_dir(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _merge_candidate_paths(*groups: tuple[Path, ...]) -> tuple[Path, ...]:
    merged: dict[str, Path] = {}
    for group in groups:
        for candidate in group:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            merged[str(resolved)] = resolved
    return tuple(sorted(merged.values(), key=str))


def _split_command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _token_path_candidates(token: str, workspace: Path) -> list[str]:
    raw_candidates = [token]
    if "=" in token and not token.startswith(("http://", "https://")):
        _prefix, value = token.split("=", 1)
        raw_candidates.append(value)

    candidates: list[str] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        value = raw.strip()
        if not value or value in _SHELL_OPERATOR_TOKENS or value.startswith("-"):
            continue
        if not _looks_like_filesystem_token(value, workspace):
            continue
        if value in seen:
            continue
        seen.add(value)
        candidates.append(value)
    return candidates


def _looks_like_filesystem_token(token: str, workspace: Path) -> bool:
    if token.startswith(("/", "./", "../", "~/")) or "/" in token:
        return True
    candidate = (workspace / token).resolve()
    if candidate.exists():
        return True
    return bool(_LIKELY_PATH_SUFFIX_RE.search(token))


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [TerminalTool(context.sandbox, context.path_policy)]
