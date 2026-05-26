from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Awaitable, Callable, Literal

from backend.config.schema import AppConfig
from backend.runtime.output_paths import turn_output_dir
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
        scheduler_run_mode: Literal["interactive", "unattended"] = "interactive",
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
            approved = await self._handle_approval_request(
                tool,
                arguments,
                session_id,
                emit,
                request=decision.summary or "requires_approval",
                reason=", ".join(decision.reasons) or "requires_approval",
                turn_id=turn_id,
                scheduler_run_mode=scheduler_run_mode,
            )
            if not approved:
                return ToolExecutionResult(
                    success=False,
                    tool=tool.meta.name,
                    action="approval",
                    category="user_rejected",
                    summary=(
                        "当前为无人值守定时任务，无法等待人工审批"
                        if scheduler_run_mode == "unattended"
                        else "用户拒绝或审批超时"
                    ),
                    retryable=False,
                    metadata={"approval_stage": "preflight", "reasons": decision.reasons},
                )

        execution_arguments = self._prepare_execution_arguments(
            tool,
            arguments,
            session_id=session_id,
            turn_id=turn_id,
        )
        attempt = 1
        while True:
            result = await self._run_tool_once(
                tool,
                execution_arguments,
                session_id,
                emit,
                attempt=attempt,
                tool_call_id=tool_call_id,
                group_id=group_id,
                display_arguments=arguments,
            )
            if not result.success:
                escalated = await self._maybe_run_sandbox_escalation(
                    tool,
                    execution_arguments,
                    arguments,
                    session_id,
                    emit,
                    result,
                    tool_call_id=tool_call_id,
                    group_id=group_id,
                    turn_approval_mode=turn_approval_mode,
                    turn_id=turn_id,
                    scheduler_run_mode=scheduler_run_mode,
                )
                if escalated is not None:
                    return escalated

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

    def _prepare_execution_arguments(
        self,
        tool: BaseTool,
        arguments: dict,
        *,
        session_id: str,
        turn_id: str | None,
    ) -> dict:
        if tool.meta.name != "terminal" or not turn_id:
            return arguments
        output_dir = turn_output_dir(self.settings.paths.workspace, session_id, turn_id)
        prepared = dict(arguments)
        prepared["__turn_output_dir"] = str(output_dir)
        return prepared

    async def _handle_approval_request(
        self,
        tool: BaseTool,
        arguments: dict,
        session_id: str,
        emit: EventEmitter,
        *,
        request: str,
        reason: str,
        turn_id: str | None,
        scheduler_run_mode: Literal["interactive", "unattended"],
    ) -> bool:
        approval_request = self.approvals.create(
            session_id=session_id,
            tool_name=tool.meta.name,
            arguments=arguments,
            reason=reason,
            turn_id=turn_id,
        )
        await emit(
            "tool_approval_request",
            {
                "approval_request_id": approval_request.approval_request_id,
                "tool": tool.meta.name,
                "arguments": arguments,
                "reason": approval_request.reason,
                "summary": request,
                "timeout_seconds": self.settings.approval.timeout_seconds,
            },
        )
        if scheduler_run_mode == "unattended":
            self.approvals.discard(approval_request.approval_request_id)
            await emit(
                "tool_approval_resolved",
                {
                    "approval_request_id": approval_request.approval_request_id,
                    "tool": tool.meta.name,
                    "approved": False,
                },
            )
            return False
        try:
            approved = await self.approvals.wait(approval_request.approval_request_id, self.settings.approval.timeout_seconds)
        except asyncio.TimeoutError:
            approved = False
        except asyncio.CancelledError:
            self.approvals.discard(approval_request.approval_request_id)
            raise
        self.approvals.discard(approval_request.approval_request_id)
        await emit(
            "tool_approval_resolved",
            {
                "approval_request_id": approval_request.approval_request_id,
                "tool": tool.meta.name,
                "approved": approved,
            },
        )
        return approved

    async def _run_tool_once(
        self,
        tool: BaseTool,
        arguments: dict,
        session_id: str,
        emit: EventEmitter,
        *,
        attempt: int,
        tool_call_id: str | None,
        group_id: str | None,
        display_arguments: dict | None = None,
    ) -> ToolExecutionResult:
        started = perf_counter()
        try:
            async def emit_tool_output(stream: str, delta: str) -> None:
                if not tool_call_id:
                    return
                public_arguments = display_arguments if display_arguments is not None else arguments
                raw_path = public_arguments.get("path") if isinstance(public_arguments, dict) else None
                await emit(
                    "tool_call_output_delta",
                    {
                        **({"group_id": group_id} if group_id else {}),
                        "tool_call_id": tool_call_id,
                        "tool": tool.meta.name,
                        "stream": stream,
                        "delta": delta,
                        "arguments": public_arguments,
                        **({"path": raw_path} if isinstance(raw_path, str) and raw_path else {}),
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
        return result

    async def _maybe_run_sandbox_escalation(
        self,
        tool: BaseTool,
        execution_arguments: dict,
        display_arguments: dict,
        session_id: str,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        tool_call_id: str | None,
        group_id: str | None,
        turn_approval_mode: TurnApprovalMode,
        turn_id: str | None,
        scheduler_run_mode: Literal["interactive", "unattended"],
    ) -> ToolExecutionResult | None:
        if tool.meta.name != "terminal":
            return None
        if not result.metadata.get("sandbox_escalation_available"):
            return None

        summary = str(
            result.metadata.get("sandbox_escalation_summary")
            or "Linux 原生沙箱阻止了本次执行，是否允许无沙箱重试一次？"
        )
        reason = str(result.metadata.get("sandbox_escalation_reason") or "sandbox_escalation")

        if scheduler_run_mode == "unattended":
            return ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="approval",
                category="permission_error",
                summary="当前为无人值守定时任务，无法批准无沙箱重试",
                retryable=False,
                metadata={
                    "approval_stage": "sandbox_escalation",
                    "sandbox_escalation_available": True,
                    "sandbox_escalation_reason": reason,
                    "sandbox_escalation_summary": summary,
                },
            )

        if turn_approval_mode == "auto_allow":
            approved = True
        else:
            approval_request = self.approvals.create(
                session_id=session_id,
                tool_name=tool.meta.name,
                arguments=display_arguments,
                reason=reason,
                turn_id=turn_id,
            )
            await emit(
                "tool_approval_request",
                {
                    "approval_request_id": approval_request.approval_request_id,
                    "tool": tool.meta.name,
                    "arguments": display_arguments,
                    "reason": approval_request.reason,
                    "summary": summary,
                    "timeout_seconds": self.settings.approval.timeout_seconds,
                },
            )
            try:
                approved = await self.approvals.wait(
                    approval_request.approval_request_id,
                    self.settings.approval.timeout_seconds,
                )
            except asyncio.TimeoutError:
                approved = False
            except asyncio.CancelledError:
                self.approvals.discard(approval_request.approval_request_id)
                raise
            self.approvals.discard(approval_request.approval_request_id)
            await emit(
                "tool_approval_resolved",
                {
                    "approval_request_id": approval_request.approval_request_id,
                    "tool": tool.meta.name,
                    "approved": approved,
                },
            )

        if not approved:
            return ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="approval",
                category="permission_error",
                summary="用户拒绝或审批超时，未执行无沙箱重试",
                retryable=False,
                metadata={
                    "approval_stage": "sandbox_escalation",
                    "sandbox_escalation_available": True,
                    "sandbox_escalation_reason": reason,
                    "sandbox_escalation_summary": summary,
                },
            )

        await emit(
            "tool_retry_scheduled",
            {
                "tool": tool.meta.name,
                "attempt": result.attempt_count + 1,
                "delay_seconds": 0,
                "reason": summary,
            },
        )

        escalated_run = getattr(tool, "run_streaming_escalated", None)
        if not callable(escalated_run):
            return None
        escalated_result = await self._run_escalated_tool_once(
            tool,
            execution_arguments,
            session_id,
            emit,
            attempt=result.attempt_count + 1,
            tool_call_id=tool_call_id,
            group_id=group_id,
            display_arguments=display_arguments,
        )
        escalated_result.metadata.update(
            {
                "sandbox_escalated": True,
                "sandbox_escalation_available": True,
                "sandbox_escalation_reason": reason,
                "sandbox_escalation_summary": summary,
            }
        )
        if not escalated_result.success:
            escalated_result.summary = f"{summary} 重试后仍失败：{escalated_result.summary}"
        return escalated_result

    async def _run_escalated_tool_once(
        self,
        tool: BaseTool,
        arguments: dict,
        session_id: str,
        emit: EventEmitter,
        *,
        attempt: int,
        tool_call_id: str | None,
        group_id: str | None,
        display_arguments: dict | None = None,
    ) -> ToolExecutionResult:
        started = perf_counter()
        try:
            async def emit_tool_output(stream: str, delta: str) -> None:
                if not tool_call_id:
                    return
                public_arguments = display_arguments if display_arguments is not None else arguments
                raw_path = public_arguments.get("path") if isinstance(public_arguments, dict) else None
                await emit(
                    "tool_call_output_delta",
                    {
                        **({"group_id": group_id} if group_id else {}),
                        "tool_call_id": tool_call_id,
                        "tool": tool.meta.name,
                        "stream": stream,
                        "delta": delta,
                        "arguments": public_arguments,
                        **({"path": raw_path} if isinstance(raw_path, str) and raw_path else {}),
                    },
                )

            result = await asyncio.wait_for(
                tool.run_streaming_escalated(
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
                summary=f"{tool.meta.name} 无沙箱重试超时",
                retryable=True,
            )
        except Exception as exc:
            result = ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="execute",
                category="runtime_exception",
                summary=f"{tool.meta.name} 无沙箱重试异常: {exc}",
                stderr=str(exc),
            )
        result.duration_ms = int((perf_counter() - started) * 1000)
        result.attempt_count = attempt
        return result
