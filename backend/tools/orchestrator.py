from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
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
from backend.tools.workspace_fs import build_path_access_policy
from backend.sandbox.approval_tokens import EscalationTokenError, EscalationTokenStore


EventEmitter = Callable[[str, dict], Awaitable[None]]


class ToolOrchestrator:
    def __init__(
        self,
        settings: AppConfig,
        approvals: ApprovalManager,
        escalation_tokens: EscalationTokenStore | None = None,
    ):
        self.settings = settings
        self.approvals = approvals
        self.retry_policy = RetryPolicy(settings.runtime)
        self.approval_policy = ApprovalPolicy(settings)
        self.escalation_tokens = escalation_tokens or EscalationTokenStore()

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
            turn_approval_mode=turn_approval_mode,
            emit=emit,
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
        turn_approval_mode: TurnApprovalMode = DEFAULT_TURN_APPROVAL_MODE,
        emit: EventEmitter | None = None,
    ) -> dict:
        if tool.meta.name == "multiagent":
            prepared = dict(arguments)
            if turn_id:
                prepared["__parent_turn_id"] = turn_id
            prepared["__turn_approval_mode"] = turn_approval_mode
            if emit is not None:
                prepared["__multiagent_event_emitter"] = emit
            return prepared
        if tool.meta.name != "terminal" or not turn_id:
            return arguments
        policy = build_path_access_policy(self.settings)
        output_dir = turn_output_dir(policy.output_root, session_id, turn_id)
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
            metadata={"approval_stage": "preflight"},
        )
        await emit(
            "tool_approval_request",
            {
                "approval_request_id": approval_request.approval_request_id,
                "tool": tool.meta.name,
                "arguments": arguments,
                "reason": approval_request.reason,
                "metadata": approval_request.metadata,
                "summary": request,
                "timeout_seconds": self.settings.approval.timeout_seconds,
            },
        )
        if scheduler_run_mode == "unattended":
            self.approvals.discard(approval_request.approval_request_id, resolved_approved=False)
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
        self.approvals.discard(approval_request.approval_request_id, resolved_approved=approved)
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

            run = tool.run_streaming(
                arguments,
                session_id=session_id,
                emit_output=emit_tool_output if tool_call_id else None,
            )
            if tool.meta.timeout_seconds is None:
                result = await run
            else:
                result = await asyncio.wait_for(run, timeout=tool.meta.timeout_seconds)
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
        approval_metadata = _sandbox_escalation_metadata(
            self.settings,
            tool=tool,
            display_arguments=display_arguments,
            result=result,
            session_id=session_id,
            tool_call_id=tool_call_id,
            turn_id=turn_id,
        )
        approval_request_id: str | None = None
        escalation_token_id: str | None = None

        if scheduler_run_mode == "unattended":
            return ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="approval",
                category="permission_error",
                error_code="SANDBOX_ESCALATION_DENIED_UNATTENDED",
                summary="当前为无人值守定时任务，无法批准无沙箱重试",
                retryable=False,
                metadata={
                    "approval_stage": "sandbox_escalation",
                    "sandbox_escalation_available": True,
                    "sandbox_escalation_reason": reason,
                    "sandbox_escalation_summary": summary,
                    "sandbox_escalation_denied": True,
                    "sandbox_error_code": "SANDBOX_ESCALATION_DENIED_UNATTENDED",
                    **approval_metadata,
                },
            )

        if turn_approval_mode == "auto_allow":
            if not self.settings.sandbox.allow_automatic_full_access:
                return ToolExecutionResult(
                    success=False,
                    tool=tool.meta.name,
                    action="approval",
                    category="permission_error",
                    error_code="SANDBOX_ESCALATION_DENIED",
                    summary="auto_allow 不会自动批准沙箱升级；需要显式批准或部署配置 allow_automatic_full_access=true",
                    retryable=False,
                    metadata={
                        "approval_stage": "sandbox_escalation",
                        "sandbox_escalation_available": True,
                        "sandbox_escalation_reason": reason,
                        "sandbox_escalation_summary": summary,
                        "sandbox_escalation_denied": True,
                        "sandbox_error_code": "SANDBOX_ESCALATION_DENIED",
                        **approval_metadata,
                    },
                )
            approved = True
        else:
            approval_request = self.approvals.create(
                session_id=session_id,
                tool_name=tool.meta.name,
                arguments=display_arguments,
                reason=reason,
                turn_id=turn_id,
                metadata=approval_metadata,
            )
            approval_request_id = approval_request.approval_request_id
            expires_at_epoch = approval_request.created_at + self.settings.approval.timeout_seconds
            expires_at = datetime.fromtimestamp(expires_at_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
            approval_metadata.update(
                {
                    "approval_request_id": approval_request_id,
                    "expires_at": expires_at,
                    "expires_at_epoch": expires_at_epoch,
                }
            )
            approval_request.metadata.update(approval_metadata)
            token_bindings = _sandbox_token_bindings(approval_metadata, approval_request_id)
            token = self.escalation_tokens.issue(
                token_bindings,
                ttl_seconds=self.settings.approval.timeout_seconds,
                metadata={"approval_request_id": approval_request_id},
            )
            escalation_token_id = token.token_id
            approval_metadata.update(
                {
                    "escalation_token_id": token.token_id,
                    "escalation_token_expires_at": token.expires_at,
                }
            )
            approval_request.metadata.update(approval_metadata)
            await emit(
                "tool_approval_request",
                {
                    "approval_request_id": approval_request_id,
                    "tool": tool.meta.name,
                    "arguments": display_arguments,
                    "reason": approval_request.reason,
                    "metadata": approval_request.metadata,
                    **approval_request.metadata,
                    "summary": summary,
                    "timeout_seconds": self.settings.approval.timeout_seconds,
                },
            )

        if escalation_token_id is None:
            token_bindings = _sandbox_token_bindings(approval_metadata, approval_request_id)
            token = self.escalation_tokens.issue(
                token_bindings,
                ttl_seconds=self.settings.approval.timeout_seconds,
                metadata={"approval_request_id": approval_request_id},
            )
            escalation_token_id = token.token_id
            approval_metadata.update(
                {
                    "escalation_token_id": token.token_id,
                    "escalation_token_expires_at": token.expires_at,
                }
            )

        if approval_request_id:
            try:
                approved = await self.approvals.wait(
                    approval_request_id,
                    self.settings.approval.timeout_seconds,
                )
            except asyncio.TimeoutError:
                approved = False
            except asyncio.CancelledError:
                self.approvals.discard(approval_request_id)
                raise
            self.approvals.discard(approval_request_id, resolved_approved=approved)
            await emit(
                "tool_approval_resolved",
                {
                    "approval_request_id": approval_request_id,
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
                error_code="SANDBOX_ESCALATION_DENIED",
                summary="用户拒绝或审批超时，未执行无沙箱重试",
                retryable=False,
                metadata={
                    "approval_stage": "sandbox_escalation",
                    "sandbox_escalation_available": True,
                    "sandbox_escalation_reason": reason,
                    "sandbox_escalation_summary": summary,
                    "sandbox_escalation_denied": True,
                    "sandbox_error_code": "SANDBOX_ESCALATION_DENIED",
                    **approval_metadata,
                },
            )

        try:
            self.escalation_tokens.consume(
                escalation_token_id or "",
                _sandbox_token_bindings(approval_metadata, approval_request_id),
            )
        except EscalationTokenError as exc:
            return ToolExecutionResult(
                success=False,
                tool=tool.meta.name,
                action="approval",
                category="permission_error",
                error_code=exc.error_code,
                summary="沙箱升级令牌无效，未执行无沙箱重试",
                retryable=False,
                metadata={
                    "approval_stage": "sandbox_escalation",
                    "sandbox_escalation_available": True,
                    "sandbox_escalation_denied": True,
                    "sandbox_error_code": exc.error_code,
                    **approval_metadata,
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
                "approval_request_id": approval_request_id,
                **approval_metadata,
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

            run = tool.run_streaming_escalated(
                arguments,
                session_id=session_id,
                emit_output=emit_tool_output if tool_call_id else None,
            )
            if tool.meta.timeout_seconds is None:
                result = await run
            else:
                result = await asyncio.wait_for(run, timeout=tool.meta.timeout_seconds)
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


def _sandbox_escalation_metadata(
    settings: AppConfig,
    *,
    tool: BaseTool,
    display_arguments: dict,
    result: ToolExecutionResult,
    session_id: str,
    tool_call_id: str | None,
    turn_id: str | None,
) -> dict[str, object]:
    command = str(display_arguments.get("command") or "") if isinstance(display_arguments, dict) else ""
    argv_sha256 = hashlib.sha256(command.encode("utf-8")).hexdigest() if command else _stable_payload_hash(display_arguments)
    preview = command if command else json.dumps(display_arguments, ensure_ascii=False, sort_keys=True)
    workspace_root = str(settings.paths.workspace.resolve())
    writable_roots = [str(path.resolve()) for path in getattr(settings.permissions, "writable_paths", [])]
    return {
        "approval_stage": "sandbox_escalation",
        "session_id": session_id,
        "turn_id": turn_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool.meta.name,
        "requested_mode": "danger-full-access",
        "effective_mode_before": settings.sandbox.mode,
        "argv_sha256": argv_sha256,
        "command_preview": preview[:300],
        "policy_hash": result.metadata.get("policy_hash"),
        "sandbox_invocation_id": result.metadata.get("invocation_id"),
        "workspace_root": workspace_root,
        "writable_roots": writable_roots,
    }


def _sandbox_token_bindings(metadata: dict[str, object], approval_request_id: str | None) -> dict[str, object]:
    """Return exactly the invocation fields that an escalation grant covers."""

    return {
        "approval_request_id": approval_request_id,
        "session_id": metadata.get("session_id"),
        "turn_id": metadata.get("turn_id"),
        "tool_call_id": metadata.get("tool_call_id"),
        "tool_name": metadata.get("tool_name"),
        "argv_sha256": metadata.get("argv_sha256"),
        "policy_hash": metadata.get("policy_hash"),
        "sandbox_invocation_id": metadata.get("sandbox_invocation_id"),
        "workspace_root": metadata.get("workspace_root"),
        "writable_roots": metadata.get("writable_roots"),
    }


def _stable_payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
