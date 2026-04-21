from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Awaitable, Callable

from backend.config.schema import AppConfig
from backend.runtime.retry_policy import RetryPolicy
from backend.tools.approval import ApprovalManager
from backend.tools.approval_policy import (
    ApprovalPolicy,
    DEFAULT_TURN_APPROVAL_MODE,
    TurnApprovalMode,
)
from backend.tools.base import BaseTool
from backend.tools.result import ToolExecutionResult


EventEmitter = Callable[[str, dict], Awaitable[None]]


class ToolOrchestrator:
    def __init__(self, settings: AppConfig, approvals: ApprovalManager):
        self.settings = settings
        self.approvals = approvals
        self.retry_policy = RetryPolicy(settings.runtime)
        self.approval_policy = ApprovalPolicy(settings)

    async def execute(
        self,
        tool: BaseTool,
        arguments: dict,
        session_id: str,
        emit: EventEmitter,
        tool_call_id: str | None = None,
        group_id: str | None = None,
        extra_reasons: list[str] | None = None,
        turn_approval_mode: TurnApprovalMode = DEFAULT_TURN_APPROVAL_MODE,
        turn_id: str | None = None,
    ) -> ToolExecutionResult:
        validation_error = tool.validate_arguments(arguments)
        if validation_error is not None:
            return ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="validation",
                category="validation_error",
                error_code="invalid_arguments",
                summary=validation_error,
                retryable=False,
            )

        decision = self.approval_policy.evaluate(
            tool,
            arguments,
            extra_reasons,
            turn_approval_mode=turn_approval_mode,
        )
        if decision.action == "deny":
            return ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="approval",
                category="permission_error",
                summary=decision.summary or "命中前置审批拒绝规则",
                retryable=False,
                metadata={"approval_stage": "preflight", "reasons": decision.reasons},
            )

        if decision.action == "ask":
            request = self.approvals.create(
                session_id=session_id,
                tool_name=tool.meta.name,
                arguments=arguments,
                reason=", ".join(decision.reasons) or "requires_approval",
                turn_id=turn_id,
            )
            await emit(
                "tool_approval_request",
                {
                    "approval_request_id": request.approval_request_id,
                    "tool": tool.meta.name,
                    "arguments": arguments,
                    "reason": request.reason,
                    "summary": decision.summary,
                    "timeout_seconds": self.settings.approval.timeout_seconds,
                },
            )
            try:
                approved = await self.approvals.wait(request.approval_request_id, self.settings.approval.timeout_seconds)
            except asyncio.TimeoutError:
                approved = False
            except asyncio.CancelledError:
                self.approvals.discard(request.approval_request_id)
                raise
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
                async def emit_tool_output(stream: str, delta: str) -> None:
                    if not tool_call_id:
                        return
                    await emit(
                        "tool_call_output_delta",
                        {
                            **({"group_id": group_id} if group_id else {}),
                            "tool_call_id": tool_call_id,
                            "tool": tool.meta.name,
                            "stream": stream,
                            "delta": delta,
                        },
                    )

                result = await asyncio.wait_for(
                    tool.run_streaming(
                        arguments,
                        session_id=session_id,
                        emit_output=emit_tool_output if tool_call_id else None,
                    ),
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
