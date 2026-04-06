from __future__ import annotations

from backend.runtime.error_codes import resolve_tool_error
from backend.tools.result import ToolExecutionResult


def classify_result(result: ToolExecutionResult) -> str:
    if result.success:
        return "success"
    if result.category and result.category != "success":
        return result.category
    if result.exit_code == 127:
        return "command_not_found"
    if result.exit_code and result.exit_code != 0:
        return "runtime_exception"
    return "fatal_error"


def annotate_result(result: ToolExecutionResult) -> ToolExecutionResult:
    descriptor = resolve_tool_error(result.category, result.success)
    result.error_code = descriptor.code
    result.severity = descriptor.severity
    result.metadata.setdefault("frontend_message", descriptor.message)
    return result
