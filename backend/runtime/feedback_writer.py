from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from backend.config.loader import get_settings
from backend.tools.result import ToolExecutionResult


class FeedbackWriter:
    def __init__(self):
        settings = get_settings()
        template_path = settings.paths.workspace / "backend" / "config" / "prompts" / "error_feedback.md"
        self.template = Template(template_path.read_text(encoding="utf-8"))

    def build(self, result: ToolExecutionResult) -> str:
        key_output = result.stderr or result.stdout or result.summary
        return self.template.render(
            tool=result.tool,
            action=result.action,
            category=result.category,
            error_code=result.error_code,
            severity=result.severity,
            exit_code=result.exit_code,
            retryable=result.retryable,
            attempt_count=result.attempt_count,
            summary=result.summary,
            key_output=key_output[:1200],
            recommended_next_step="Inspect the failure and choose the smallest corrective action.",
        )
