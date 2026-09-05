from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from backend.providers.base import ProviderResponse
from backend.runtime.workflow_state import (
    TURN_OUTCOME_ANSWERED,
    TURN_OUTCOME_AWAITING_USER,
    TURN_OUTCOME_BLOCKED,
)
from backend.tools.result import ToolExecutionResult


TurnStepAction = Literal["continue", "finalize", "finalize_blocked", "finalize_failed"]

MAX_RECOVERY_ATTEMPTS = 2
MAX_FINALIZATION_ATTEMPTS = 1

INCOMPLETE_ACTION_PATTERNS = (
    re.compile(r"^\s*(?:老板|好的老板|收到|明白了)?[，,:：\s]*(?:让我|我先|我来|我继续|我会|我将).*(?:看看|查查|检查|确认|修复|处理|生成|制作|创建|执行|运行|调用)", re.I),
    re.compile(r"(?:让我|我先|我来).*(?:重新生成|直接用|修复|处理|生成|制作|创建|执行|运行|调用)", re.I),
    re.compile(
        r"^\s*我(?:先|来|再|继续|会|将)?\s*(?:直接|马上|现在|接下来|去)?\s*"
        r"(?:试试|看看|找找|查找|查询|确认|定位|检查|处理)",
        re.I,
    ),
    re.compile(r"^\s*(?:先|继续|接下来).*(?:试试|看看|找找|查找|查询|确认|定位|检查|处理)", re.I),
    re.compile(r"(?:这次|现在|接下来|下一步).*?(?:我|我们).*?(?:重试|再试|执行|运行|调用|生成|传入|处理)", re.I),
    re.compile(r"(?:这次|现在|接下来|下一步)[，,:：\s]*(?:重试|再试|执行|运行|调用|生成|传入|处理)", re.I),
    re.compile(r"(?:我|我们)(?:会|将|准备|打算|需要).*?(?:重试|再试|执行|运行|调用|生成|传入|处理)", re.I),
    re.compile(r"允许的路径范围内.*(?:找|查|确认|定位)", re.I),
    re.compile(r"^(?:I'?ll|I will|Let me|I can|I am going to)\s+.*(?:check|look|search|try|retry|run|execute|call|generate|inspect|find)", re.I),
)
INCOMPLETE_FOLLOWUP_ACTION_PATTERNS = (
    re.compile(
        r"(?:^|[。！？.!?\n，,；;]\s*)"
        r"(?:现在|接下来|下一步|这次)?[，,:：\s]*"
        r"(?:让我|我(?:先|来|再|继续|会|将|准备|打算|需要|要)|我们(?:先|来|再|继续|会|将|准备|打算|需要|要))"
        r"[^。！？.!?\n]{0,180}"
        r"(?:尝试|试试|重试|再试|测试|验证|执行|运行|调用|读取|检查|确认|定位|排查|处理|生成|创建|修改|修复)",
        re.I,
    ),
)
INCOMPLETE_ACTION_MAX_CHARS = 120
INCOMPLETE_FOLLOWUP_ACTION_MAX_CHARS = 700

COMPLETION_SIGNAL_PATTERNS = (
    re.compile(r"(?:位置|路径|目录|文件|日志|原因|失败|受限|权限|阻塞|无法|不能|已经|已|完成|保存在|生成|结果)"),
    re.compile(r"(?:located|path|file|log|reason|failed|blocked|permission|cannot|done|saved|generated|result)", re.I),
)
RECOVERABLE_FAILURE_GATE_REASONS = frozenset(
    {
        "empty_final_answer",
        "incomplete_action_statement",
        "unresolved_tool_failure_without_result",
    }
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
    recoverable_recovery_attempts: int = 0
    finalization_attempts: int = 0
    force_no_tools_next: bool = False
    invalid_tool_call_count: int = 0
    invalid_tool_call_recovery_attempts: int = 0

    def record_tool_result(self, result: ToolExecutionResult) -> None:
        self.tool_call_count += 1
        if result.success:
            self.finalization_attempts = 0
            success_kind = _successful_result_kind(result)
            if success_kind == "resolved":
                self.last_failure_tool = None
                self.last_failure_summary = None
                self.last_failure_frontend_message = None
                self.has_unresolved_recoverable_failure = False
                self.recoverable_recovery_attempts = 0
            elif success_kind == "progress":
                self.recoverable_recovery_attempts = 0
            return

        self.last_failure_tool = result.tool
        self.last_failure_summary = result.summary
        self.last_failure_frontend_message = result.frontend_message
        if result.recovery_class == "recoverable":
            self.recoverable_failure_count += 1
            self.has_unresolved_recoverable_failure = True
            self.recoverable_recovery_attempts = 0
            self.finalization_attempts = 0
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

    if (
        progress.has_unresolved_recoverable_failure
        and gate_reason in RECOVERABLE_FAILURE_GATE_REASONS
        and progress.recoverable_recovery_attempts < MAX_RECOVERY_ATTEMPTS
    ):
        progress.recoverable_recovery_attempts += 1
        return TurnStepDecision(
            action="continue",
            reason=f"recoverable_failure_recovery:{gate_reason}",
            finish_reason=response.finish_reason,
            inject_instruction=build_recovery_instruction(progress, candidate),
            reset_visible_answer=True,
            disable_tools_next=False,
        )

    if progress.finalization_attempts < MAX_FINALIZATION_ATTEMPTS:
        progress.finalization_attempts += 1
        return TurnStepDecision(
            action="continue",
            reason=gate_reason,
            finish_reason=response.finish_reason,
            inject_instruction=build_finalization_instruction(progress, candidate),
            reset_visible_answer=True,
            disable_tools_next=False,
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


def build_recovery_instruction(progress: TurnProgressState, rejected_answer: str) -> str:
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
        "最近一次工具失败仍然属于可恢复问题，你刚才的回复没有提供可交付结果。\n\n"
        "继续推进任务，可以继续调用工具，但不要重复同一个失败动作（相同命令、相同路径、相同参数或同一个已知无效步骤）。\n"
        "优先选择下面几种恢复方式之一：\n"
        "1. 调整参数、路径或范围后重试一个更小的验证步骤；\n"
        "2. 改用其他工具或其他信息来源；\n"
        "3. 如果现有上下文已经足够，直接给用户最终结论。\n\n"
        "如果下一轮仍然拿不到结果，请明确说明阻塞点，不要只说“我继续查找”。\n\n"
        f"被拦截的回复：{rejected}\n\n"
        f"最近一次工具失败：\n{failure_block}"
    )


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
    exhausted_recovery = (
        progress.has_unresolved_recoverable_failure
        and progress.recoverable_recovery_attempts >= MAX_RECOVERY_ATTEMPTS
    )
    preface = "最近一次可恢复失败在多次恢复尝试后仍未形成结果。\n\n" if exhausted_recovery else ""
    return (
        f"{preface}你刚才的回复只是行动计划或未完成说明，不能作为最终回答。\n\n"
        "如果还需要执行工具、修改文件、重新生成结果或补验证，请直接继续推进，不要把下一步计划当成最终回答。\n"
        "如果现有上下文已经足够收口，请明确写出：\n"
        "1. 已经知道的结果是什么；\n"
        "2. 哪些工具或路径失败了；\n"
        "3. 是否因为权限、路径或上下文限制而无法继续；\n"
        "4. 用户下一步可以怎么做。\n\n"
        "如果仍未完成，就继续执行；如果确实无法继续，再明确标为阻塞，不要只说“我继续查找”。\n\n"
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
    if len(text) <= INCOMPLETE_ACTION_MAX_CHARS and any(
        pattern.search(text) for pattern in INCOMPLETE_ACTION_PATTERNS
    ):
        return True
    if len(text) <= INCOMPLETE_FOLLOWUP_ACTION_MAX_CHARS and any(
        pattern.search(text) for pattern in INCOMPLETE_FOLLOWUP_ACTION_PATTERNS
    ):
        return True
    return False


def _has_completion_signal(text: str) -> bool:
    if len(text) >= 80:
        return True
    return any(pattern.search(text) for pattern in COMPLETION_SIGNAL_PATTERNS)


def _successful_result_kind(result: ToolExecutionResult) -> Literal["diagnostic", "progress", "resolved"]:
    if str(result.metadata.get("turn_outcome") or "").strip() == TURN_OUTCOME_AWAITING_USER:
        return "resolved"
    if result.metadata.get("output_files"):
        return "resolved"
    if result.tool in {"write_file", "edit_file"}:
        return "progress"
    if result.tool == "terminal" and any(result.metadata.get(key) is not None for key in ("path", "created", "bytes", "content_type")):
        return "progress"
    return "diagnostic"
