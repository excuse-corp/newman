from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Awaitable, Callable

from backend.config.schema import AppConfig
from backend.runtime.retry_policy import RetryPolicy
from backend.tools.approval import ApprovalManager
from backend.tools.base import BaseTool
from backend.tools.result import ToolExecutionResult


EventEmitter = Callable[[str, dict], Awaitable[None]]


class ToolOrchestrator:
    def __init__(self, settings: AppConfig, approvals: ApprovalManager):
        self.settings = settings
        self.approvals = approvals
        self.retry_policy = RetryPolicy(settings.runtime)

    async def execute(
        self,
        tool: BaseTool,
        arguments: dict,
        session_id: str,
        emit: EventEmitter,
        extra_reasons: list[str] | None = None,
    ) -> ToolExecutionResult:
        reasons = list(extra_reasons or [])
        requires_approval = tool.meta.requires_approval or bool(reasons)
        if requires_approval:
            request = self.approvals.create(
                session_id=session_id,
                tool_name=tool.meta.name,
                arguments=arguments,
                reason=", ".join(reasons) or "requires_approval",
            )
            await emit(
                "tool_approval_request",
                {
                    "approval_request_id": request.approval_request_id,
                    "tool": tool.meta.name,
                    "arguments": arguments,
                    "reason": request.reason,
                    "timeout_seconds": self.settings.approval.timeout_seconds,
                },
            )
            try:
                approved = await self.approvals.wait(request.approval_request_id, self.settings.approval.timeout_seconds)
            except asyncio.TimeoutError:
                self.approvals.discard(request.approval_request_id)
                approved = False
            else:
                self.approvals.discard(request.approval_request_id)
            await emit(
                "tool_approval_resolved",
                {
                    "approval_request_id": request.approval_request_id,
                    "tool": tool.meta.name,
                    "approved": approved,
                },
            )
            if not approved:
                return ToolExecutionResult(
                    success=False,
                    tool=tool.meta.name,
                    action="approval",
                    category="user_rejected",
                    summary="用户拒绝或审批超时",
                    retryable=False,
                )

        attempt = 1
        while True:
            started = perf_counter()
            try:
                result = await asyncio.wait_for(
                    tool.run(arguments, session_id=session_id),
                    timeout=tool.meta.timeout_seconds,
                )
            except asyncio.TimeoutError:
                result = ToolExecutionResult(
                    success=False,
                    tool=tool.meta.name,
                    action="execute",
                    category="timeout_error",
                    summary=f"{tool.meta.name} 执行超时",
                    retryable=True,
                )
            except Exception as exc:
                result = ToolExecutionResult(
                    success=False,
                    tool=tool.meta.name,
                    action="execute",
                    category="runtime_exception",
                    summary=f"{tool.meta.name} 执行异常: {exc}",
                    stderr=str(exc),
                )
            result.duration_ms = int((perf_counter() - started) * 1000)
            result.attempt_count = attempt

            if not self.retry_policy.should_retry(result, attempt):
                return result

            delay = self.retry_policy.backoff_seconds(attempt)
            await emit(
                "tool_retry_scheduled",
                {
                    "tool": tool.meta.name,
                    "attempt": attempt + 1,
                    "delay_seconds": delay,
                    "reason": result.summary,
                },
            )
            await self.retry_policy.wait(attempt)
            attempt += 1
