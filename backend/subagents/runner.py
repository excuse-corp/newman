from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Awaitable
from uuid import uuid4

from backend.config.schema import AppConfig
from backend.providers.base import BaseProvider, ProviderError, ProviderResponse, TokenUsage, ToolCall
from backend.runtime.result_normalizer import normalize_result
from backend.sessions.models import SessionMessage, SessionRecord, utc_now
from backend.sessions.session_store import SessionStore
from backend.subagents.cancellation import CancellationRegistry
from backend.subagents.events import model_call_completed_payload, tool_event_payload
from backend.subagents.locks import FileLockManager, FileLockTimeout, path_lock_key, workspace_mutation_lock_key
from backend.subagents.models import FileChange, FileConflict, SubagentTask, TerminalCommand, UsageSummary
from backend.subagents.report import AgentReportParseError, degraded_agent_report, parse_agent_report
from backend.subagents.store import MultiAgentStore
from backend.tools.permission_context import PermissionContext
from backend.tools.result import ToolExecutionResult
from backend.tools.router import analyze_terminal_command
from backend.tools.workspace_fs import build_path_access_policy, resolve_requested_path, resolve_writable_path
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore

if TYPE_CHECKING:
    from backend.tools.orchestrator import ToolOrchestrator
    from backend.tools.registry import ToolRegistry
    from backend.tools.router import ToolRouter


EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]

PLAIN_TEXT_REPORT_FORMAT = [
    "Scope: one sentence describing the exact scope you handled.",
    "Result: the answer or key findings for that scope.",
    "Key files: relevant file paths, or None.",
    "Files changed: files you changed, or None.",
    "Issues: blockers, review findings, or None.",
    "Risks: residual risks or uncertainty, or None.",
    "Next steps: concrete follow-up actions, or None.",
]
REPORT_REPAIR_PROMPT = "\n".join(
    [
        "Your previous response was missing the expected final report structure.",
        "Do not call tools. Return only the final report using exactly these labels:",
        *PLAIN_TEXT_REPORT_FORMAT,
        "Do not return JSON. Do not use a code block.",
    ]
)


class SubagentStop(Exception):
    def __init__(
        self,
        *,
        reason: str,
        task_status: str,
        summary: str,
        risks: list[str] | None = None,
        recommended_next_steps: list[str] | None = None,
    ):
        self.reason = reason
        self.task_status = task_status
        self.summary = summary
        self.risks = risks or []
        self.recommended_next_steps = recommended_next_steps or []
        super().__init__(summary)


class SubagentRunner:
    def __init__(
        self,
        settings: AppConfig,
        provider: BaseProvider,
        session_store: SessionStore,
        store: MultiAgentStore,
        *,
        usage_store: PostgresModelUsageStore | None = None,
        registry_provider: Callable[[], "ToolRegistry | None"] | None = None,
        router_provider: Callable[[], "ToolRouter | None"] | None = None,
        orchestrator_provider: Callable[[], "ToolOrchestrator | None"] | None = None,
        lock_manager: FileLockManager | None = None,
        cancellation_registry: CancellationRegistry | None = None,
    ):
        self.settings = settings
        self.provider = provider
        self.session_store = session_store
        self.store = store
        self.usage_store = usage_store
        self._registry_provider = registry_provider or (lambda: None)
        self._router_provider = router_provider or (lambda: None)
        self._orchestrator_provider = orchestrator_provider or (lambda: None)
        self.lock_manager = lock_manager
        self.cancellation_registry = cancellation_registry or CancellationRegistry()

    async def run(
        self,
        task: SubagentTask,
        *,
        event_emitter: EventEmitter | None = None,
    ) -> SubagentTask:
        self._raise_if_cancelled(task)
        task.status = "running"
        task.started_at = task.started_at or utc_now()
        task.progress.max_turns = task.max_turns
        task.current_activity = "Creating child session"
        child = self._ensure_child_session(task)
        self.store.save_task(task)

        try:
            response = await self._run_until_report(child, task, event_emitter=event_emitter)

            try:
                report = parse_agent_report(response.content, task)
            except AgentReportParseError:
                report = await self._repair_report(child, task, event_emitter=event_emitter)

            task.result = report
            task.status = report.status
            task.current_activity = "Completed"
            task.completed_at = utc_now()
            self.store.save_task(task)
            return task
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.error = task.error or "Subagent task was cancelled before completion."
            task.current_activity = "Cancelled"
            task.result = task.result or degraded_agent_report(
                task,
                status="cancelled",
                reason="cancelled",
                summary=task.error,
                recommended_next_steps=["Review any partial output and rerun the task only if the work is still needed."],
            )
            task.completed_at = utc_now()
            self.store.save_task(task)
            raise
        except SubagentStop as exc:
            task.status = exc.task_status  # type: ignore[assignment]
            task.error = exc.summary
            task.current_activity = "Stopped by subagent control policy"
            task.result = degraded_agent_report(
                task,
                status=exc.task_status,
                reason=exc.reason,
                summary=exc.summary,
                risks=exc.risks or None,
                recommended_next_steps=exc.recommended_next_steps or None,
            )
            task.completed_at = utc_now()
            self.store.save_task(task)
            return task
        except ProviderError as exc:
            task.status = "failed"
            task.error = exc.message
            task.result = degraded_agent_report(
                task,
                status="failed",
                reason="provider_error",
                summary=exc.message,
                risks=["Provider call failed before the subagent could complete."],
                recommended_next_steps=["Review provider configuration or retry the subagent task."],
            )
            task.completed_at = utc_now()
            self.store.save_task(task)
            return task
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.result = degraded_agent_report(
                task,
                status="failed",
                reason="runner_exception",
                summary=str(exc),
                risks=["Subagent runner raised an unexpected exception."],
                recommended_next_steps=["Inspect the child transcript and backend logs before retrying."],
            )
            task.completed_at = utc_now()
            self.store.save_task(task)
            return task

    async def _repair_report(
        self,
        child: SessionRecord,
        task: SubagentTask,
        *,
        event_emitter: EventEmitter | None,
    ):
        repair_message = SessionMessage(
            id=uuid4().hex,
            role="user",
            content=REPORT_REPAIR_PROMPT,
            metadata={
                "subagent_task_id": task.task_id,
                "multiagent_run_id": task.run_id,
                "phase": "report_repair",
            },
        )
        child.messages.append(repair_message)
        self.session_store.save(child)

        response = await self._call_provider(child, task, is_repair=True, event_emitter=event_emitter)
        child.messages.append(
            self._assistant_message(
                task,
                response.content,
                finish_reason=response.finish_reason,
                metadata={"phase": "report_repair"},
            )
        )
        self.session_store.save(child)
        task.progress.completed_turns += 1

        try:
            return parse_agent_report(response.content, task)
        except AgentReportParseError:
            task.status = "report_invalid"
            return degraded_agent_report(
                task,
                status="report_invalid",
                reason="parse_failed",
                summary=response.content,
            )

    async def _run_until_report(
        self,
        child: SessionRecord,
        task: SubagentTask,
        *,
        event_emitter: EventEmitter | None,
    ) -> ProviderResponse:
        task_turn_limit = max(task.max_turns - 1, 1)
        for _ in range(task_turn_limit):
            response = await self._call_provider(
                child,
                task,
                tools=self._provider_tools(task),
                is_repair=False,
                is_wrapup=False,
                event_emitter=event_emitter,
            )
            task.progress.completed_turns += 1
            if response.tool_calls:
                child.messages.append(self._assistant_tool_call_message(task, response))
                self.session_store.save(child)
                await self._execute_tool_calls(child, task, response.tool_calls, event_emitter=event_emitter)
                continue
            child.messages.append(
                self._assistant_message(
                    task,
                    response.content,
                    finish_reason=response.finish_reason,
                    metadata={"phase": "agent_report"},
                )
            )
            self.session_store.save(child)
            return response

        wrapup_message = SessionMessage(
            id=uuid4().hex,
            role="user",
            content=(
                "You have reached the execution turn limit. Based only on the progress so far, "
                "stop using tools and return the final plain-text report with the required labels."
            ),
            metadata={
                "subagent_task_id": task.task_id,
                "multiagent_run_id": task.run_id,
                "phase": "wrapup_request",
            },
        )
        child.messages.append(wrapup_message)
        self.session_store.save(child)
        response = await self._call_provider(
            child,
            task,
            tools=[],
            is_repair=False,
            is_wrapup=True,
            event_emitter=event_emitter,
        )
        task.progress.completed_turns += 1
        child.messages.append(
            self._assistant_message(
                task,
                response.content,
                finish_reason=response.finish_reason,
                metadata={"phase": "agent_report", "is_wrapup_turn": True},
            )
        )
        self.session_store.save(child)
        return response

    async def _call_provider(
        self,
        child: SessionRecord,
        task: SubagentTask,
        *,
        tools: list[dict[str, object]] | None = None,
        is_repair: bool,
        is_wrapup: bool = False,
        event_emitter: EventEmitter | None = None,
    ) -> ProviderResponse:
        messages = self._provider_messages(child)
        provider_tools = tools or []
        estimated_input_tokens = self.provider.estimate_tokens(messages)
        max_attempts = self._provider_max_attempts()
        for attempt in range(1, max_attempts + 1):
            self._raise_if_cancelled(task)
            task.current_activity = "Calling provider" if attempt == 1 else f"Calling provider (retry {attempt}/{max_attempts})"
            self.store.save_task(task)
            try:
                response = await self._collect_provider_response(messages, provider_tools)
            except ProviderError as exc:
                if not self._should_retry_provider_error(exc, attempt=attempt, max_attempts=max_attempts):
                    raise
                delay = self._provider_retry_delay_seconds(exc, attempt=attempt)
                task.current_activity = f"Provider retry scheduled in {delay:.1f}s"
                self.store.save_task(task)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue

            task.progress.tool_call_count += len(response.tool_calls)
            task.progress.last_event_at = utc_now()
            usage_delta = self._record_usage(
                task,
                messages,
                response,
                tool_schema_count=len(provider_tools),
                is_repair=is_repair,
                is_wrapup=is_wrapup,
                estimated_input_tokens=estimated_input_tokens,
            )
            self.store.save_task(task)
            await self._emit_model_call_completed_event(
                event_emitter,
                task,
                usage_delta,
                tool_schema_count=len(provider_tools),
                is_repair=is_repair,
                is_wrapup=is_wrapup,
                finish_reason=response.finish_reason,
            )
            self._raise_if_cancelled(task)
            return response

        raise ProviderError(self.settings.provider.type, "upstream_error", "Provider retry loop exhausted", True)

    async def _collect_provider_response(
        self,
        messages: list[dict[str, object]],
        provider_tools: list[dict[str, object]],
    ) -> ProviderResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        usage = TokenUsage()
        finish_reason = "stop"

        async def collect() -> None:
            nonlocal finish_reason, usage
            async for chunk in self.provider.chat_stream(messages, tools=provider_tools):
                if chunk.type == "text" and chunk.delta:
                    content_parts.append(chunk.delta)
                elif chunk.type == "tool_call" and chunk.tool_call:
                    tool_calls.append(chunk.tool_call)
                elif chunk.type == "usage" and chunk.usage:
                    usage = chunk.usage
                elif chunk.type == "done":
                    finish_reason = chunk.finish_reason or finish_reason
                    if chunk.usage:
                        usage = chunk.usage

        await collect()

        return ProviderResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            model=self.settings.provider.model,
            finish_reason=finish_reason,
        )

    def _provider_max_attempts(self) -> int:
        retry_attempts = getattr(self.settings.runtime, "provider_retry_attempts", None)
        if retry_attempts is None:
            retry_attempts = getattr(self.settings.runtime, "tool_retry_attempts", 0)
        return max(1, int(retry_attempts) + 1)

    def _should_retry_provider_error(self, error: ProviderError, *, attempt: int, max_attempts: int) -> bool:
        if attempt >= max_attempts:
            return False
        if error.kind == "rate_limit_error":
            return True
        return bool(error.retryable)

    def _provider_retry_delay_seconds(self, error: ProviderError, *, attempt: int) -> float:
        retry_after = _retry_after_seconds(error.details)
        if retry_after is not None:
            return retry_after
        base_delay = getattr(self.settings.runtime, "provider_retry_backoff_seconds", None)
        if base_delay is None:
            base_delay = getattr(self.settings.runtime, "tool_retry_backoff_seconds", 0.0)
        delay = max(0.0, float(base_delay)) * (2 ** max(0, attempt - 1))
        if delay <= 0:
            return 0.0
        return delay + random.uniform(0.0, min(delay, 1.0))

    async def _execute_tool_calls(
        self,
        child: SessionRecord,
        task: SubagentTask,
        tool_calls: list[ToolCall],
        *,
        event_emitter: EventEmitter | None,
    ) -> None:
        for tool_call in tool_calls:
            self._raise_if_cancelled(task)
            task.current_activity = f"Running tool: {tool_call.name}"
            self.store.save_task(task)
            await self._emit_tool_event(event_emitter, task, "tool_call_started", {"tool": tool_call.name, "arguments": tool_call.arguments})
            result = await self._execute_tool_call(task, tool_call, event_emitter=event_emitter)
            result = normalize_result(result)
            self._record_tool_side_effects(task, tool_call, result)
            child.messages.append(self._tool_message(task, tool_call, result))
            self.session_store.save(child)
            self.store.save_task(task)
            await self._emit_tool_event(
                event_emitter,
                task,
                "tool_call_finished",
                {
                    "tool": result.tool,
                    "success": result.success,
                    "category": result.category,
                    "summary": result.summary,
                    "metadata": result.metadata,
                },
            )
            self._raise_if_cancelled(task)

    async def _execute_tool_call(
        self,
        task: SubagentTask,
        tool_call: ToolCall,
        *,
        event_emitter: EventEmitter | None,
    ) -> ToolExecutionResult:
        if tool_call.name not in set(task.allowed_tools):
            return ToolExecutionResult(
                success=False,
                tool=tool_call.name,
                action="execute",
                category="permission_error",
                summary=f"Subagent is not allowed to use tool: {tool_call.name}",
                retryable=False,
            )
        registry = self._registry_provider()
        router = self._router_provider()
        orchestrator = self._orchestrator_provider()
        if registry is None or router is None or orchestrator is None:
            return ToolExecutionResult(
                success=False,
                tool=tool_call.name,
                action="execute",
                category="runtime_error",
                summary="Subagent tool runtime is not configured",
                retryable=False,
            )
        try:
            tool = router.route(tool_call.name, tool_call.arguments)
        except KeyError:
            return ToolExecutionResult(
                success=False,
                tool=tool_call.name,
                action="route",
                category="validation_error",
                summary=f"Tool is not registered: {tool_call.name}",
                retryable=True,
            )

        async def emit(event: str, data: dict) -> None:
            if event == "tool_approval_request":
                await self._emit_tool_event(event_emitter, task, "tool_approval_request", data, outer_event="multiagent_approval_queued")
                return
            await self._emit_tool_event(event_emitter, task, event, data)

        approval_mode = task.tool_policy_snapshot.approval_mode
        if approval_mode not in {"manual", "auto_allow"}:
            approval_mode = "manual"
        extra_reasons = router.static_checks(tool, tool_call.arguments)
        lock_keys = self._lock_keys_for_tool_call(tool_call)
        if not lock_keys or self.lock_manager is None:
            return await orchestrator.execute(
                tool,
                tool_call.arguments,
                task.child_session_id,
                emit,
                tool_call_id=tool_call.id,
                group_id=f"{task.task_id}:group:{task.progress.completed_turns + 1}",
                extra_reasons=extra_reasons,
                turn_approval_mode=approval_mode,  # type: ignore[arg-type]
                turn_id=task.task_id,
            )

        held_keys: list[str] = []
        try:
            task.status = "waiting_file_lock"
            task.current_activity = f"Waiting for file lock: {tool_call.name}"
            self.store.save_task(task)
            async with self.lock_manager.hold(
                lock_keys,
                task_id=task.task_id,
                timeout_seconds=self.settings.subagents.lock_wait_timeout_seconds,
            ) as acquired:
                held_keys = list(acquired)
                task.status = "running"
                task.held_locks.extend(key for key in held_keys if key not in task.held_locks)
                task.current_activity = f"Running tool: {tool_call.name}"
                self.store.save_task(task)
                return await orchestrator.execute(
                    tool,
                    tool_call.arguments,
                    task.child_session_id,
                    emit,
                    tool_call_id=tool_call.id,
                    group_id=f"{task.task_id}:group:{task.progress.completed_turns + 1}",
                    extra_reasons=extra_reasons,
                    turn_approval_mode=approval_mode,  # type: ignore[arg-type]
                    turn_id=task.task_id,
                )
        except FileLockTimeout as exc:
            task.status = "running"
            conflict = FileConflict(
                path=exc.key,
                blocked_task_id=task.task_id,
                holding_task_id=exc.holding_task_id,
                reason="lock_timeout",
            )
            task.file_conflicts.append(conflict)
            self.store.save_task(task)
            return ToolExecutionResult(
                success=False,
                tool=tool_call.name,
                action="file_lock",
                category="lock_timeout",
                summary=str(exc),
                retryable=True,
                metadata={"file_conflict": conflict.model_dump(mode="json")},
            )
        finally:
            if held_keys:
                held_set = set(held_keys)
                task.held_locks = [key for key in task.held_locks if key not in held_set]
                self.store.save_task(task)

    def _provider_tools(self, task: SubagentTask) -> list[dict[str, object]]:
        registry = self._registry_provider()
        if registry is None:
            return []
        allowed = set(task.allowed_tools)
        permission_context = PermissionContext(deny_rules=set(task.denied_tools))
        schemas = registry.tools_for_provider(permission_context)
        return [
            schema
            for schema in schemas
            if self._provider_schema_tool_name(schema) in allowed
        ]

    def _lock_keys_for_tool_call(self, tool_call: ToolCall) -> list[str]:
        policy = build_path_access_policy(self.settings)
        if tool_call.name in {"write_file", "edit_file"}:
            raw_path = tool_call.arguments.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                return []
            return [path_lock_key(resolve_writable_path(policy, raw_path))]
        if tool_call.name != "terminal":
            return []
        command = str(tool_call.arguments.get("command") or "")
        analysis = analyze_terminal_command(command, policy)
        if not analysis.mutating:
            return []
        path_keys = [
            path_lock_key(match.path)
            for match in analysis.path_matches
            if match.state == "writable"
        ]
        if path_keys:
            return path_keys
        return [workspace_mutation_lock_key()]

    def _record_usage(
        self,
        task: SubagentTask,
        messages: list[dict[str, object]],
        response: ProviderResponse,
        *,
        tool_schema_count: int,
        is_repair: bool,
        is_wrapup: bool,
        estimated_input_tokens: int,
    ) -> UsageSummary:
        record = record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="subagent_turn",
                model_config=self.settings.provider,
                provider_type=self.settings.provider.type,
                streaming=True,
                counts_toward_context_window=False,
                session_id=task.child_session_id,
                turn_id=task.task_id,
                metadata={
                    "multiagent_run_id": task.run_id,
                    "subagent_task_id": task.task_id,
                    "agent_name": task.name,
                    "parent_session_id": task.parent_session_id,
                    "child_session_id": task.child_session_id,
                    "parent_turn_id": task.parent_turn_id,
                    "tool_schema_count": tool_schema_count,
                    "is_wrapup_turn": is_wrapup,
                    "is_report_repair": is_repair,
                    "estimated_input_tokens": estimated_input_tokens,
                },
            ),
            response,
        )
        usage = UsageSummary(
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            total_tokens=record.total_tokens,
            request_count=1,
        )
        task.usage_summary = task.usage_summary.add(usage)
        return usage

    async def _emit_model_call_completed_event(
        self,
        event_emitter: EventEmitter | None,
        task: SubagentTask,
        usage_delta: UsageSummary,
        *,
        tool_schema_count: int,
        is_repair: bool,
        is_wrapup: bool,
        finish_reason: str,
    ) -> None:
        if event_emitter is None:
            return
        payload = model_call_completed_payload(
            task,
            usage_delta=usage_delta.model_dump(mode="json"),
            tool_schema_count=tool_schema_count,
            is_repair=is_repair,
            is_wrapup=is_wrapup,
            finish_reason=finish_reason,
            model=self.settings.provider.model,
        )
        try:
            await event_emitter("multiagent_model_call_completed", payload)
        except Exception:
            return None

    def _ensure_child_session(self, task: SubagentTask) -> SessionRecord:
        try:
            child = self.session_store.get(task.child_session_id)
        except FileNotFoundError:
            child = SessionRecord(
                session_id=task.child_session_id,
                title=f"Subagent: {task.name}",
                metadata=self._child_session_metadata(task),
            )
            child.messages.extend(
                [
                    SessionMessage(
                        id=uuid4().hex,
                        role="system",
                        content=self._system_prompt(task),
                        metadata={
                            "subagent_task_id": task.task_id,
                            "multiagent_run_id": task.run_id,
                            "phase": "system",
                        },
                    ),
                    SessionMessage(
                        id=uuid4().hex,
                        role="user",
                        content=task.assignment_prompt,
                        metadata={
                            "subagent_task_id": task.task_id,
                            "multiagent_run_id": task.run_id,
                            "phase": "assignment",
                        },
                    ),
                ]
            )
            self.session_store.save(child)
        return child

    def _child_session_metadata(self, task: SubagentTask) -> dict[str, object]:
        return {
            "subagent": True,
            "parent_session_id": task.parent_session_id,
            "parent_turn_id": task.parent_turn_id,
            "multiagent_run_id": task.run_id,
            "subagent_task_id": task.task_id,
            "agent_name": task.name,
        }

    def _system_prompt(self, task: SubagentTask) -> str:
        return "\n".join(
            [
                "You are a temporary Newman subagent.",
                "Use fresh context and complete only the assigned task.",
                "Use only the tools exposed to you.",
                "Do not ask the user questions.",
                "Do not emit meta-commentary between tool calls.",
                "The parent agent will synthesize the final answer across subagents.",
                "",
                "When you finish, return one concise plain-text report using exactly these labels:",
                *PLAIN_TEXT_REPORT_FORMAT,
                "",
                "Do not return JSON.",
                "Do not wrap the final report in a code block.",
                f"task_id: {task.task_id}",
                f"name: {task.name}",
                f"transcript_ref: {task.transcript_ref}",
            ]
        )

    def _provider_messages(self, child: SessionRecord) -> list[dict[str, object]]:
        return [
            self._provider_message_from_session_message(message)
            for message in child.messages
            if message.role in {"system", "user", "assistant", "tool"}
        ]

    def _provider_message_from_session_message(self, message: SessionMessage) -> dict[str, object]:
        payload: dict[str, object] = {"role": message.role, "content": message.content}
        if message.role == "assistant":
            tool_calls = message.metadata.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": str(item.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(item.get("name") or ""),
                            "arguments": json.dumps(item.get("arguments") or {}, ensure_ascii=False),
                        },
                    }
                    for item in tool_calls
                    if isinstance(item, dict)
                ]
        if message.role == "tool":
            tool_call_id = message.metadata.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id:
                payload["tool_call_id"] = tool_call_id
        return payload

    def _assistant_tool_call_message(self, task: SubagentTask, response: ProviderResponse) -> SessionMessage:
        return self._assistant_message(
            task,
            response.content,
            finish_reason=response.finish_reason,
            metadata={
                "phase": "tool_call",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    }
                    for tool_call in response.tool_calls
                ],
            },
        )

    def _tool_message(self, task: SubagentTask, tool_call: ToolCall, result: ToolExecutionResult) -> SessionMessage:
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part) or result.summary
        return SessionMessage(
            id=uuid4().hex,
            role="tool",
            content=output,
            metadata={
                "subagent_task_id": task.task_id,
                "multiagent_run_id": task.run_id,
                "tool_call_id": tool_call.id,
                "tool": result.tool,
                "arguments": tool_call.arguments,
                "success": result.success,
                "category": result.category,
                "summary": result.summary,
                "error_code": result.error_code,
                "phase": "tool_result",
            },
        )

    def _record_tool_side_effects(self, task: SubagentTask, tool_call: ToolCall, result: ToolExecutionResult) -> None:
        if result.success and result.tool in {"write_file", "edit_file"}:
            path = result.metadata.get("path")
            if isinstance(path, str) and path:
                task.file_changes.append(
                    FileChange(
                        path=path,
                        tool=result.tool,  # type: ignore[arg-type]
                        created=_optional_bool(result.metadata.get("created")),
                        bytes=_optional_int(result.metadata.get("bytes")),
                        summary=result.summary,
                    )
                )
        output_files = result.metadata.get("output_files")
        if result.success and result.tool == "terminal" and isinstance(output_files, list):
            for item in output_files:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if not isinstance(path, str) or not path:
                    continue
                task.file_changes.append(
                    FileChange(
                        path=path,
                        tool="terminal",
                        created=_optional_bool(item.get("created")),
                        bytes=_optional_int(item.get("bytes")),
                        summary=str(item.get("summary") or result.summary),
                    )
                )
        if result.tool == "terminal":
            task.terminal_commands.append(
                TerminalCommand(
                    command=str(tool_call.arguments.get("command") or result.action),
                    exit_code=result.exit_code,
                    success=result.success,
                    stdout_preview=_preview(result.stdout),
                    stderr_preview=_preview(result.stderr),
                    completed_at=utc_now(),
                )
            )

    def _provider_schema_tool_name(self, schema: dict[str, object]) -> str:
        function = schema.get("function") if isinstance(schema, dict) else None
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name") if isinstance(schema, dict) else None
        return name if isinstance(name, str) else ""

    def _assistant_message(
        self,
        task: SubagentTask,
        content: str,
        *,
        finish_reason: str,
        metadata: dict[str, object] | None = None,
    ) -> SessionMessage:
        return SessionMessage(
            id=uuid4().hex,
            role="assistant",
            content=content,
            metadata={
                "subagent_task_id": task.task_id,
                "multiagent_run_id": task.run_id,
                "finish_reason": finish_reason,
                **(metadata or {}),
            },
        )

    def _raise_if_cancelled(self, task: SubagentTask) -> None:
        request = self.cancellation_registry.request_for_task(task)
        if request is None:
            return
        task.cancel_requested_at = task.cancel_requested_at or request.requested_at
        task.cancel_reason = task.cancel_reason or request.reason
        raise SubagentStop(
            reason="cancelled",
            task_status="cancelled",
            summary="Subagent task was cancelled by request.",
            risks=["This subagent was stopped before completion because a cancellation request was accepted."],
            recommended_next_steps=["Review any partial output and rerun the task only if the work is still needed."],
        )

    async def _emit_tool_event(
        self,
        event_emitter: EventEmitter | None,
        task: SubagentTask,
        event: str,
        data: dict[str, Any],
        *,
        outer_event: str = "multiagent_tool_event",
    ) -> None:
        if event_emitter is None:
            return
        try:
            await event_emitter(outer_event, tool_event_payload(task, event, data))
        except Exception:
            return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    return None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _preview(value: str, limit: int = 2000) -> str | None:
    text = value.strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _retry_after_seconds(details: dict[str, Any]) -> float | None:
    for key in ("retry_after_seconds", "retry_after"):
        value = details.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return max(0.0, float(value))
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            try:
                return max(0.0, float(stripped))
            except ValueError:
                continue
    return None
