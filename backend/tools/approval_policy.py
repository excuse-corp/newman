from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.config.schema import AppConfig
from backend.tools.base import BaseTool


ApprovalAction = Literal["allow", "ask", "deny"]
TurnApprovalMode = Literal["manual", "auto_approve_level2"]
DEFAULT_TURN_APPROVAL_MODE: TurnApprovalMode = "manual"

SAFE_TERMINAL_PREFIXES = (
    "pwd",
    "ls",
    "tree",
    "cat",
    "head",
    "tail",
    "find ",
    "find\n",
    "rg ",
    "grep ",
    "sed -n",
    "awk ",
    "cut ",
    "sort",
    "uniq",
    "wc",
    "stat",
    "du ",
    "df ",
    "which ",
    "whereis ",
    "file ",
    "ps ",
    "git status",
    "git diff",
    "git show",
    "git log",
    "git branch",
)

TERMINAL_MUTATION_MARKERS = (
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

PROCESS_SPAWN_MARKERS = (
    "nohup ",
    " setsid ",
    "systemctl ",
    "service ",
    "docker run",
    "podman run",
    "uvicorn ",
    "python -m http.server",
    "npm run dev",
    "pnpm dev",
    " &",
)

SHELL_META_MARKERS = ("|", "&&", "||", ";", "$(", "`")


@dataclass
class ApprovalDecision:
    action: ApprovalAction
    reasons: list[str] = field(default_factory=list)
    summary: str = ""


class ApprovalPolicy:
    def __init__(self, settings: AppConfig):
        self.settings = settings

    def evaluate(self, tool: BaseTool, arguments: dict, static_reasons: list[str] | None = None) -> ApprovalDecision:
        reasons = list(static_reasons or [])

        if tool.meta.name == "terminal":
            command = str(arguments.get("command", ""))
            if blocked := self._match_level1_blacklist(command):
                return ApprovalDecision(
                    action="deny",
                    reasons=[f"level1_blacklist:{blocked}"],
                    summary=f"命中 Level 1 黑名单：{blocked}",
                )

            if self.settings.sandbox.mode == "danger-full-access":
                reasons.append("danger_full_access_terminal")

            if self._looks_like_process_spawn(command):
                reasons.append("process_spawn")

            if self._requires_terminal_approval(command):
                reasons.append("terminal_mutation_or_unknown")
            else:
                if tool.meta.requires_approval:
                    return ApprovalDecision(action="ask", reasons=["requires_approval"], summary="工具默认需要审批")
                return ApprovalDecision(action="allow", summary="只读终端命令已自动放行")

        if tool.meta.requires_approval:
            reasons.append("requires_approval")

        ask_reasons = self._filter_level2_reasons(reasons)
        if ask_reasons:
            return ApprovalDecision(
                action="ask",
                reasons=ask_reasons,
                summary="命中 Level 2 风险规则，需人工审批",
            )
        return ApprovalDecision(action="allow", summary="未命中审批条件")

    def _match_level1_blacklist(self, command: str) -> str | None:
        lowered = f" {command.lower()} "
        for pattern in self.settings.approval.level1_blacklist:
            if pattern.lower() in lowered:
                return pattern
        return None

    def _filter_level2_reasons(self, reasons: list[str]) -> list[str]:
        configured = set(self.settings.approval.level2_patterns)
        filtered: list[str] = []
        for reason in reasons:
            base = reason.split(":", 1)[0]
            if reason == "requires_approval" or base in configured:
                if reason not in filtered:
                    filtered.append(reason)
        return filtered

    def _requires_terminal_approval(self, command: str) -> bool:
        normalized = self._normalize(command)
        if not normalized:
            return True
        if any(marker in normalized for marker in TERMINAL_MUTATION_MARKERS):
            return True
        if any(marker in normalized for marker in SHELL_META_MARKERS):
            return True
        return not any(normalized.startswith(prefix) for prefix in SAFE_TERMINAL_PREFIXES)

    def _looks_like_process_spawn(self, command: str) -> bool:
        normalized = self._normalize(command)
        return any(marker in normalized for marker in PROCESS_SPAWN_MARKERS)

    @staticmethod
    def _normalize(command: str) -> str:
        return " ".join(command.strip().lower().split())


def normalize_turn_approval_mode(value: object) -> TurnApprovalMode:
    if value == "auto_approve_level2":
        return "auto_approve_level2"
    return DEFAULT_TURN_APPROVAL_MODE
