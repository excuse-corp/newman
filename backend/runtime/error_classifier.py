from __future__ import annotations

from backend.runtime.error_codes import resolve_tool_error
from backend.tools.result import ToolExecutionResult


FATAL_RUNTIME_PATTERNS = (
    "未找到 bwrap",
    "无法启用 Linux 原生沙箱",
    "当前平台暂未实现原生沙箱",
    "sandbox crashed",
)


def classify_result(result: ToolExecutionResult) -> str:
    if result.success:
        return "success"
    if result.exit_code == 127:
        return "command_not_found"
    if result.category and result.category != "success":
        return result.category
    if result.exit_code and result.exit_code != 0:
        return "runtime_exception"
    return "fatal_error"


def annotate_result(result: ToolExecutionResult) -> ToolExecutionResult:
    descriptor = resolve_tool_error(result.category, result.success)
    result.error_code = descriptor.code
    result.severity = descriptor.severity
    result.risk_level = descriptor.risk_level
    result.frontend_message = descriptor.message
    result.recovery_class = _resolve_recovery_class(result, descriptor.recovery_class)
    result.recommended_next_step = _resolve_next_step(result, descriptor.recommended_next_step)
    result.metadata.setdefault("frontend_message", result.frontend_message)
    result.metadata.setdefault("risk_level", result.risk_level)
    result.metadata.setdefault("recovery_class", result.recovery_class)
    result.metadata.setdefault("recommended_next_step", result.recommended_next_step)
    return result


def _resolve_recovery_class(result: ToolExecutionResult, default_recovery_class: str) -> str:
    if result.success:
        return "none"
    if result.category != "runtime_exception":
        return default_recovery_class
    if result.exit_code not in (None, 0):
        return "recoverable"

    detail = "\n".join(part for part in [result.summary, result.stderr] if part).lower()
    if any(pattern.lower() in detail for pattern in FATAL_RUNTIME_PATTERNS):
        return "fatal"
    if result.tool.startswith("provider:"):
        return "fatal"
    if "执行异常" in result.summary:
        return "fatal"
    return default_recovery_class


def _resolve_next_step(result: ToolExecutionResult, default_next_step: str) -> str:
    if result.success:
        return default_next_step
    if result.category == "runtime_exception" and result.exit_code not in (None, 0):
        return "Inspect the command output, correct the failing arguments or environment, then retry the smallest needed step."
    if result.recovery_class == "fatal":
        return "Stop this round, summarize the blocker clearly, and wait for user intervention or a configuration fix."
    return default_next_step
