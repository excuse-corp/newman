from __future__ import annotations

from backend.runtime.error_classifier import annotate_result, classify_result
from backend.tools.result import ToolExecutionResult


def normalize_result(result: ToolExecutionResult) -> ToolExecutionResult:
    result.category = classify_result(result)
    return annotate_result(result)
