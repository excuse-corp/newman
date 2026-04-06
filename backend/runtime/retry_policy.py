from __future__ import annotations

import asyncio

from backend.config.schema import RuntimeConfig
from backend.tools.result import ToolExecutionResult


class RetryPolicy:
    def __init__(self, config: RuntimeConfig):
        self.max_attempts = max(1, config.tool_retry_attempts)
        self.base_backoff_seconds = max(0.0, config.tool_retry_backoff_seconds)

    def should_retry(self, result: ToolExecutionResult, attempt: int) -> bool:
        return result.retryable and attempt < self.max_attempts

    def backoff_seconds(self, attempt: int) -> float:
        return self.base_backoff_seconds * (2 ** max(0, attempt - 1))

    async def wait(self, attempt: int) -> None:
        delay = self.backoff_seconds(attempt)
        if delay > 0:
            await asyncio.sleep(delay)
