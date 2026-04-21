from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from backend.config.schema import AppConfig
from backend.mcp.path_guard import validate_mcp_argument_paths
from backend.tools.base import BaseTool
from backend.tools.registry import ToolRegistry
from backend.tools.workspace_fs import build_path_access_policy, classify_path, resolve_requested_path


class ToolRouter:
    def __init__(self, registry: ToolRegistry, settings: AppConfig):
        self.registry = registry
        self.settings = settings
        self.path_policy = build_path_access_policy(settings)

    def route(self, tool_name: str, arguments: dict) -> BaseTool:
        return self.registry.get(tool_name)

    def static_checks(self, tool: BaseTool, arguments: dict) -> list[str]:
        checks: list[str] = []
        if tool.meta.name == "terminal":
            return self._terminal_static_checks(str(arguments.get("command", "")))
        if tool.meta.name.startswith("mcp__"):
            return self._mcp_static_checks(arguments)
        if "path" not in arguments:
            return checks

        tool_name = tool.meta.name
        if tool_name not in {
            "read_file",
            "read_file_range",
            "list_dir",
            "list_files",
            "search_files",
            "grep",
            "write_file",
            "edit_file",
        }:
            return checks

        path = resolve_requested_path(self.path_policy, arguments.get("path"))
        state = classify_path(self.path_policy, path)
        if tool_name in {"write_file", "edit_file"}:
            if state == "protected":
                checks.append("write_protected_path")
            elif state != "writable":
                checks.append("write_outside_writable_paths")
                return checks
            checks.extend(self._managed_path_reasons(path))
            return _dedupe_reasons(checks)

        if state == "protected":
            checks.append("read_protected_path")
        elif state == "forbidden":
            checks.append("read_outside_readable_paths")
        return checks

    def _mcp_static_checks(self, arguments: dict) -> list[str]:
        return validate_mcp_argument_paths(self.path_policy, arguments)

    def _terminal_static_checks(self, command: str) -> list[str]:
        analysis = analyze_terminal_command(command, self.path_policy)
        reasons: list[str] = []
        seen: set[str] = set()
        for match in analysis.path_matches:
            path = match.path
            state = match.state
            if state == "protected":
                reason = (
                    f"{'terminal_write_protected_path' if analysis.mutating else 'terminal_read_protected_path'}:{path}"
                )
            elif state == "forbidden":
                reason = (
                    f"{'terminal_write_outside_writable_paths' if analysis.mutating else 'terminal_read_outside_readable_paths'}:{path}"
                )
            elif state == "readable" and analysis.mutating:
                reason = f"terminal_write_readonly_path:{path}"
            else:
                continue
            if reason in seen:
                continue
            seen.add(reason)
            reasons.append(reason)
        if analysis.mutating:
            for match in analysis.path_matches:
                if match.state == "writable":
                    reasons.extend(self._managed_path_reasons(match.path))
        return _dedupe_reasons(reasons)

    def _managed_path_reasons(self, path: Path) -> list[str]:
        managed_roots = (
            ("maintain_memory", self.settings.paths.memory_dir),
            ("maintain_skill", self.settings.paths.skills_dir),
            ("maintain_plugin", self.settings.paths.plugins_dir),
            ("maintain_tool", (Path(__file__).resolve().parents[1] / "tools")),
        )
        reasons: list[str] = []
        resolved = path.resolve()
        for reason, root in managed_roots:
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                continue
            reasons.append(reason)
        return reasons


@dataclass(frozen=True)
class TerminalPathMatch:
    raw: str
    path: Path
    state: str


@dataclass(frozen=True)
class TerminalCommandAnalysis:
    command: str
    mutating: bool
    path_matches: tuple[TerminalPathMatch, ...]


TERMINAL_WRITE_COMMANDS = {
    "touch",
    "mkdir",
    "rmdir",
    "rm",
    "mv",
    "cp",
    "chmod",
    "chown",
    "tee",
}

TERMINAL_PATH_COMMANDS = {
    "cat",
    "head",
    "tail",
    "ls",
    "tree",
    "find",
    "rg",
    "grep",
    "sed",
    "awk",
    "cut",
    "sort",
    "uniq",
    "wc",
    "stat",
    "du",
    "df",
    "file",
    "touch",
    "mkdir",
    "rmdir",
    "rm",
    "mv",
    "cp",
    "chmod",
    "chown",
    "tee",
    "git",
}

TERMINAL_MUTATION_PATTERNS = (
    " >",
    ">>",
    "touch ",
    "mkdir ",
    "rmdir ",
    "rm ",
    "mv ",
    "cp ",
    "chmod ",
    "chown ",
    "tee ",
    "sed -i",
    "perl -i",
    "git apply",
    "git commit",
    "git push",
    "git reset",
    "git checkout",
    "git clean",
    "npm install",
    "pnpm install",
    "yarn install",
    "pip install",
    "uv pip",
    "cargo build",
    "cargo test",
    "make ",
)


def _shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _looks_like_mutation_command(command: str, first_token: str) -> bool:
    normalized = " ".join(command.lower().split())
    if first_token in TERMINAL_WRITE_COMMANDS:
        return True
    return any(pattern in normalized for pattern in TERMINAL_MUTATION_PATTERNS)


def _command_uses_path_operands(first_token: str) -> bool:
    return first_token in TERMINAL_PATH_COMMANDS


def _looks_like_path_operand(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    if token in {"|", "||", "&&", ";", ">", ">>", "<", "<<", "<<-", "2>", "1>"}:
        return False
    return token.startswith(("/", "./", "../", "~/")) or "/" in token


def _extract_redirection_targets(command: str) -> list[str]:
    targets = re.findall(r"(?:^|\s)(?:\d*>>?|\d*>)([^\s&|;]+)", command)
    if not targets:
        targets = re.findall(r"(?:^|\s)>>?\s*([^\s&|;]+)", command)
    return [target for target in targets if target]


def analyze_terminal_command(command: str, path_policy) -> TerminalCommandAnalysis:
    normalized = command.strip()
    if not normalized:
        return TerminalCommandAnalysis(command=command, mutating=False, path_matches=())

    tokens = _shell_tokens(normalized)
    if not tokens:
        return TerminalCommandAnalysis(command=command, mutating=False, path_matches=())

    first = tokens[0]
    mutating = _looks_like_mutation_command(normalized, first)
    candidates = list(_extract_redirection_targets(normalized))
    if candidates:
        mutating = True
    if _command_uses_path_operands(first):
        candidates.extend(token for token in tokens[1:] if _looks_like_path_operand(token))

    matches: list[TerminalPathMatch] = []
    seen: set[str] = set()
    for raw in candidates:
        path = resolve_requested_path(path_policy, raw)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            TerminalPathMatch(
                raw=raw,
                path=path,
                state=classify_path(path_policy, path),
            )
        )
    return TerminalCommandAnalysis(
        command=command,
        mutating=mutating,
        path_matches=tuple(matches),
    )


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return deduped
