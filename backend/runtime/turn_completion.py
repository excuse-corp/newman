from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from backend.providers.base import ProviderResponse
from backend.runtime.workflow_state import (
    TURN_OUTCOME_ANSWERED,
    TURN_OUTCOME_BLOCKED,
)
from backend.tools.result import ToolExecutionResult


TurnStepAction = Literal["continue", "finalize", "finalize_blocked", "finalize_failed", "awaiting_user"]

MAX_FINALIZATION_ATTEMPTS = 1

INCOMPLETE_ACTION_PATTERNS = (
    re.compile(r"^\s*我(?:先|来|再|继续|会|将)?\s*.*(?:试试|看看|找找|查找|查询|确认|定位|检查|处理)", re.I),
    re.compile(r"^\s*(?:先|继续|接下来).*(?:试试|看看|找找|查找|查询|确认|定位|检查|处理)", re.I),
    re.compile(r"允许的路径范围内.*(?:找|查|确认|定位)", re.I),
    re.compile(r"^(?:I'?ll|I will|Let me|I can|I am going to)\s+.*(?:check|look|search|try|inspect|find)", re.I),
)

COMPLETION_SIGNAL_PATTERNS = (
    re.compile(r"(?:位置|路径|目录|文件|日志|原因|失败|受限|权限|阻塞|无法|不能|已经|已|完成|保存在|生成|结果)"),
    re.compile(r"(?:located|path|file|log|reason|failed|blocked|permission|cannot|done|saved|generated|result)", re.I),
)


@dataclass
class TurnProgressState:
    tool_call_count: int = 0
    recoverable_failure_count: int = 0
    fatal_failure_count: int = 0
    last_failure_tool: str | None = None
    last_failure_summary: str | None = None
    last_failure_frontend_message: str | None = None
    has_unresolved_recoverable_failure: bool = False
    finalization_attempts: int = 0
    force_no_tools_next: bool = False
    invalid_tool_call_count: int = 0
    invalid_tool_call_recovery_attempts: int = 0

    def record_tool_result(self, result: ToolExecutionResult) -> None:
        self.tool_call_count += 1
        if result.success:
            return

        self.last_failure_tool = result.tool
        self.last_failure_summary = result.summary
        self.last_failure_frontend_message = result.frontend_message
        if result.recovery_class == "recoverable":
            self.recoverable_failure_count += 1
            self.has_unresolved_recoverable_failure = True
        elif result.recovery_class == "fatal":
            self.fatal_failure_count += 1


@dataclass(frozen=True)
class TurnStepDecision:
    action: TurnStepAction
    reason: str
    final_content: str | None = None
    finish_reason: str = "stop"
    turn_outcome: str = TURN_OUTCOME_ANSWERED
    inject_instruction: str | None = None
    reset_visible_answer: bool = False
    disable_tools_next: bool = False


def final_candidate_from_response(response: ProviderResponse) -> str:
    return response.content.strip() or response.commentary.strip()


def decide_turn_step(response: ProviderResponse, progress: TurnProgressState) -> TurnStepDecision:
    if response.tool_calls:
        return TurnStepDecision(action="continue", reason="tool_calls_present", finish_reason=response.finish_reason)

    candidate = final_candidate_from_response(response)
    gate_reason = final_answer_gate_reason(candidate, progress)
    if gate_reason is None:
        return TurnStepDecision(
            action="finalize",
            reason="final_answer_gate_passed",
            final_content=candidate,
            finish_reason=response.finish_reason,
            turn_outcome=TURN_OUTCOME_ANSWERED,
        )

    if progress.finalization_attempts < MAX_FINALIZATION_ATTEMPTS:
        progress.finalization_attempts += 1
        progress.force_no_tools_next = True
        return TurnStepDecision(
            action="continue",
            reason=gate_reason,
            finish_reason=response.finish_reason,
            inject_instruction=build_finalization_instruction(progress, candidate),
            reset_visible_answer=True,
            disable_tools_next=True,
        )

    return TurnStepDecision(
        action="finalize_blocked",
        reason=gate_reason,
        final_content=build_blocked_fallback(progress, candidate),
        finish_reason="completion_gate_blocked",
        turn_outcome=TURN_OUTCOME_BLOCKED,
    )


def final_answer_gate_reason(candidate: str, progress: TurnProgressState) -> str | None:
    normalized = " ".join(candidate.split()).strip()
    if not normalized:
        return "empty_final_answer"

    if _looks_like_incomplete_action(normalized):
        return "incomplete_action_statement"

    if progress.has_unresolved_recoverable_failure and not _has_completion_signal(normalized):
        return "unresolved_tool_failure_without_result"

    return None


def build_finalization_instruction(progress: TurnProgressState, rejected_answer: str) -> str:
    failure_lines: list[str] = []
    if progress.last_failure_tool:
        failure_lines.append(f"- Tool: {progress.last_failure_tool}")
    if progress.last_failure_frontend_message:
        failure_lines.append(f"- Frontend message: {progress.last_failure_frontend_message}")
    if progress.last_failure_summary:
        failure_lines.append(f"- Summary: {progress.last_failure_summary}")
    failure_block = "\n".join(failure_lines) if failure_lines else "- none"

    rejected = rejected_answer.strip() or "（空）"
    return (
        "你刚才的回复只是行动计划或未完成说明，不能作为最终回答。\n\n"
        "不要再调用任何工具。请只基于当前上下文给用户一个明确收口：\n"
        "1. 已经知道的结果是什么；\n"
        "2. 哪些工具或路径失败了；\n"
        "3. 是否因为权限、路径或上下文限制而无法继续；\n"
        "4. 用户下一步可以怎么做。\n\n"
        "如果已知信息足以回答用户问题，直接回答；如果不足以完成任务，明确标为阻塞，不要说“我继续查找”。\n\n"
        f"被拦截的回复：{rejected}\n\n"
        f"最近一次工具失败：\n{failure_block}"
    )


def build_blocked_fallback(progress: TurnProgressState, rejected_answer: str) -> str:
    lines = ["当前任务没有完成：模型连续返回了行动计划或未收口内容，已阻止将其标记为完成。"]
    if progress.last_failure_tool or progress.last_failure_summary:
        failure = progress.last_failure_summary or "工具执行失败"
        tool = f"{progress.last_failure_tool} " if progress.last_failure_tool else ""
        lines.append(f"最近一次失败：{tool}{failure}")
    if rejected_answer.strip():
        lines.append(f"最后一次无效回复：{rejected_answer.strip()}")
    lines.append("请调整权限、路径或重新发起任务。")
    return "\n".join(lines)


def _looks_like_incomplete_action(text: str) -> bool:
    if len(text) > 120:
        return False
    return any(pattern.search(text) for pattern in INCOMPLETE_ACTION_PATTERNS)


def _has_completion_signal(text: str) -> bool:
    if len(text) >= 80:
        return True
    return any(pattern.search(text) for pattern in COMPLETION_SIGNAL_PATTERNS)
