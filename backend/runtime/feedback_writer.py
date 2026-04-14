from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from backend.providers.token_estimator import estimate_message_tokens
from backend.tools.result import ToolExecutionResult


MAX_FEEDBACK_TOKENS = 500
INITIAL_SUMMARY_LIMIT = 500
INITIAL_OUTPUT_LIMIT = 1200


class FeedbackWriter:
    def __init__(self):
        template_path = Path(__file__).resolve().parents[1] / "config" / "prompts" / "error_feedback.md"
        self.template = Template(template_path.read_text(encoding="utf-8"))

    def build(self, result: ToolExecutionResult) -> str:
        summary = _clip_text(result.summary, INITIAL_SUMMARY_LIMIT)
        key_output = _clip_text(result.stderr or result.stdout or result.summary, INITIAL_OUTPUT_LIMIT)
        rendered = self._render(result, summary=summary, key_output=key_output)
        if estimate_message_tokens([{"role": "system", "content": rendered}]) <= MAX_FEEDBACK_TOKENS:
            return rendered

        for summary_limit, output_limit in ((360, 900), (240, 600), (180, 360), (120, 180)):
            rendered = self._render(
                result,
                summary=_clip_text(summary, summary_limit),
                key_output=_clip_text(key_output, output_limit),
            )
            if estimate_message_tokens([{"role": "system", "content": rendered}]) <= MAX_FEEDBACK_TOKENS:
                return rendered

        return self._render(
            result,
            summary=_clip_text(summary, 120),
            key_output=_clip_text(key_output, 120),
        )

    def _render(self, result: ToolExecutionResult, *, summary: str, key_output: str) -> str:
        return self.template.render(
            tool=result.tool,
            action=result.action,
            category=result.category,
            error_code=result.error_code,
            severity=result.severity,
            risk_level=result.risk_level,
            recovery_class=result.recovery_class,
            exit_code=result.exit_code,
            retryable=result.retryable,
            attempt_count=result.attempt_count,
            frontend_message=result.frontend_message,
            summary=summary,
            key_output=key_output,
            recommended_next_step=result.recommended_next_step,
        )


def _clip_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 12)]}\n...[truncated]"
