from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from backend.config.schema import AppConfig
from backend.hooks.hook_manager import HookManager
from backend.mcp.registry import MCPRegistry
from backend.memory.checkpoint_store import CheckpointStore
from backend.memory.compressor import (
    build_checkpoint_metadata,
    estimate_pressure,
    split_session_messages,
    summarize_messages,
)
from backend.memory.memory_extract import MemoryExtractor
from backend.memory.stable_context import StableContextLoader
from backend.plugin_runtime.service import PluginService
from backend.providers.base import ProviderError, ProviderResponse, TokenUsage
from backend.providers.multimodal import MultimodalAnalyzer
from backend.providers.factory import build_provider
from backend.rag.service import KnowledgeBaseService
from backend.runtime.feedback_writer import FeedbackWriter
from backend.runtime.prompt_assembler import PromptAssembler
from backend.runtime.result_normalizer import normalize_result
from backend.runtime.session_task import SessionTask
from backend.runtime.thread_manager import ThreadManager
from backend.scheduler.task_store import TaskStore
from backend.sessions.models import SessionMessage
from backend.sessions.session_store import SessionStore
from backend.skill_runtime.registry import SkillRegistry
from backend.tools.approval import ApprovalManager
from backend.tools.impl.edit_file import EditFileTool
from backend.tools.impl.fetch_url import FetchUrlTool
from backend.tools.impl.list_dir import ListDirectoryTool
from backend.tools.impl.read_file import ReadFileTool
from backend.tools.impl.search_kb import SearchKnowledgeBaseTool
from backend.tools.impl.search_files import SearchFilesTool
from backend.tools.impl.terminal import TerminalTool
from backend.tools.impl.update_plan import UpdatePlanTool
from backend.tools.impl.write_file import WriteFileTool
from backend.tools.orchestrator import ToolOrchestrator
from backend.tools.approval_policy import DEFAULT_TURN_APPROVAL_MODE, TurnApprovalMode
from backend.tools.permission_context import PermissionContext
from backend.tools.registry import ToolRegistry
from backend.tools.router import ToolRouter
from backend.tools.result import ToolExecutionResult
from backend.sandbox.native_sandbox import NativeSandbox
from backend.sandbox.resource_limits import ResourceLimits
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


EventEmitter = Callable[[str, dict], Awaitable[None]]


class NewmanRuntime:
    def __init__(self, settings: AppConfig):
        self.settings = settings
        self.provider = build_provider(settings.provider)
        self.usage_store = PostgresModelUsageStore(settings.rag.postgres_dsn)
        self.multimodal_analyzer = MultimodalAnalyzer(settings.models.multimodal, self.usage_store)
        self.session_store = SessionStore(settings.paths.sessions_dir)
        self.thread_manager = ThreadManager(self.session_store)
        self.checkpoints = CheckpointStore(settings.paths.sessions_dir)
        self.memory_extractor = MemoryExtractor(
            self.provider,
            settings.provider,
            settings.provider.type,
            self.session_store,
            self.checkpoints,
            settings.paths.memory_dir / "USER.md",
            settings.paths.workspace / "backend" / "config" / "prompts" / "mem_extract.md",
            self.usage_store,
        )
        self._background_tasks: set[asyncio.Task] = set()
        self.stable_context = StableContextLoader(settings.paths.memory_dir)
        self.prompt_assembler = PromptAssembler(self.stable_context, str(settings.paths.workspace))
        self.feedback_writer = FeedbackWriter()
        self.approvals = ApprovalManager()
        self.plugin_service = PluginService(
            settings.paths.plugins_dir,
            settings.paths.skills_dir,
            settings.paths.data_dir / "plugin_state.json",
        )
        self.skill_registry = SkillRegistry(self.plugin_service, settings.paths.memory_dir)
        self.hook_manager = HookManager(self.plugin_service)
        self.mcp_registry = MCPRegistry(settings.paths.mcp_dir / "servers.yaml")
        self.scheduler_store = TaskStore(settings.paths.scheduler_dir / "tasks.json")
        self.registry = ToolRegistry()
        self.router = ToolRouter(self.registry, settings)
        self.orchestrator = ToolOrchestrator(settings, self.approvals)
        self.exec_sandbox: NativeSandbox | None = None
        self.reload_ecosystem()

    def close(self) -> None:
        self.mcp_registry.close()

    def reload_ecosystem(self) -> None:
        self.plugin_service.reload()
        self.skill_registry.sync_snapshot()
        self.registry = self._build_registry(self.settings.paths.workspace)
        self.router = ToolRouter(self.registry, self.settings)

    def _tools_overview(self) -> str:
        overview = self.registry.describe()
        resource_overview = self.mcp_registry.describe_resources()
        if resource_overview:
            overview = f"{overview}\n\n## MCP Resources\n{resource_overview}"
        return overview

    def schedule_previous_session_extraction(self, exclude_session_id: str) -> dict[str, object]:
        previous = self.session_store.latest(exclude_session_ids={exclude_session_id}, require_messages=True)
        if previous is None:
            return {
                "scheduled": False,
                "trigger": "new_session_created",
                "source_session_id": None,
                "reason": "no_previous_session",
            }
        return self.schedule_user_memory_extraction(previous.session_id, "new_session_created")

    def schedule_user_memory_extraction(self, session_id: str, trigger: str) -> dict[str, object]:
        if self.settings.provider.type == "mock":
            return {
                "scheduled": False,
                "trigger": trigger,
                "source_session_id": session_id,
                "reason": "mock_provider",
            }
        task = asyncio.create_task(self._run_memory_extraction(session_id, trigger))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {
            "scheduled": True,
            "trigger": trigger,
            "source_session_id": session_id,
            "reason": "background_task_started",
        }

    async def _run_memory_extraction(self, session_id: str, trigger: str) -> None:
        try:
            await self.memory_extractor.extract_session(session_id, trigger)
        except Exception as exc:
            print(f"[memory] extraction failed for session {session_id} ({trigger}): {exc}")

    def _build_registry(self, workspace: Path) -> ToolRegistry:
        limits = ResourceLimits(
            timeout_seconds=self.settings.sandbox.timeout,
            output_limit_bytes=self.settings.sandbox.output_limit_bytes,
        )
        sandbox = NativeSandbox(workspace=workspace, limits=limits, config=self.settings.sandbox)
        self.exec_sandbox = sandbox
        knowledge_base = KnowledgeBaseService(
            self.settings.paths.knowledge_dir,
            workspace,
            self.settings.models,
            self.settings.rag,
            self.settings.paths.chroma_dir,
            self.usage_store,
        )
        registry = ToolRegistry()
        registry.register(ReadFileTool(workspace))
        registry.register(ListDirectoryTool(workspace))
        registry.register(
            ListDirectoryTool(
                workspace,
                name="list_files",
                description="Alias of list_dir. List files and directories inside the workspace.",
            )
        )
        registry.register(SearchFilesTool(workspace))
        registry.register(
            SearchFilesTool(
                workspace,
                name="grep",
                description="Alias of search_files. Search file contents in the workspace and return matching lines.",
            )
        )
        registry.register(FetchUrlTool())
        registry.register(TerminalTool(sandbox))
        registry.register(WriteFileTool(workspace))
        registry.register(EditFileTool(workspace))
        registry.register(UpdatePlanTool())
        registry.register(SearchKnowledgeBaseTool(knowledge_base))
        for tool in self.mcp_registry.build_tools(self.plugin_service.mcp_server_configs()):
            registry.register(tool)
        return registry

    async def handle_message(
        self,
        session_id: str,
        content: str,
        emit: EventEmitter,
        user_metadata: dict[str, object] | None = None,
        turn_approval_mode: TurnApprovalMode = DEFAULT_TURN_APPROVAL_MODE,
    ) -> None:
        self.reload_ecosystem()
        user_message = SessionMessage(id=uuid4().hex, role="user", content=content, metadata=user_metadata or {})
        session = self.session_store.append_message(session_id, user_message)
        await self._emit_hooks("SessionStart", emit, session_id=session.session_id, content=content)

        task = SessionTask(session=session, permission_context=PermissionContext(), turn_id=user_message.id)
        await self._maybe_checkpoint(task, emit)
        provider_feedback_attempted = False

        for _ in range(self.settings.runtime.max_tool_depth):
            self.skill_registry.sync_snapshot()
            assembled = self.prompt_assembler.assemble(
                task.session,
                self._tools_overview(),
                json.dumps(self.settings.approval.model_dump(mode="json"), ensure_ascii=False),
                self.checkpoints.get(task.session.session_id),
            )

            try:
                response = await self._stream_provider_response(
                    assembled,
                    self.registry.tools_for_provider(task.permission_context),
                    emit,
                    session_id=task.session.session_id,
                    turn_id=task.turn_id,
                    request_kind="session_turn",
                    counts_toward_context_window=True,
                )
            except ProviderError as exc:
                result = self._provider_error_result(exc)
                await self._record_failure_feedback(task, result, emit)
                if exc.retryable and result.recovery_class == "recoverable" and not provider_feedback_attempted:
                    provider_feedback_attempted = True
                    continue
                await self._emit_fatal_error(
                    task,
                    emit,
                    result,
                    finish_reason="provider_error",
                    extra={"provider": exc.provider, "status_code": exc.status_code},
                )
                return

            if not response.tool_calls:
                assistant_message = SessionMessage(id=uuid4().hex, role="assistant", content=response.content)
                task.session.messages.append(assistant_message)
                self.session_store.save(task.session)
                await emit(
                    "final_response",
                    {
                        "session_id": task.session.session_id,
                        "content": response.content,
                        "finish_reason": response.finish_reason,
                    },
                )
                if self.memory_extractor.looks_like_explicit_persistence_signal(content):
                    self.schedule_user_memory_extraction(task.session.session_id, "explicit_user_request")
                await self._emit_hooks(
                    "SessionEnd",
                    emit,
                    session_id=task.session.session_id,
                    finish_reason=response.finish_reason,
                )
                return

            assistant_tool_message = SessionMessage(
                id=uuid4().hex,
                role="assistant",
                content=response.content,
                metadata={
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        }
                        for tool_call in response.tool_calls
                    ]
                },
            )
            task.session.messages.append(assistant_tool_message)
            self.session_store.save(task.session)

            for tool_call in response.tool_calls:
                task.tool_depth += 1
                tool = self.router.route(tool_call.name, tool_call.arguments)
                extra_reasons = self.router.static_checks(tool, tool_call.arguments)
                await self._emit_hooks(
                    "PreToolUse",
                    emit,
                    session_id=task.session.session_id,
                    tool=tool_call.name,
                    arguments=tool_call.arguments,
                )
                await emit(
                    "tool_call_started",
                    {
                        "tool_call_id": tool_call.id,
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                )
                result = await self.orchestrator.execute(
                    tool,
                    tool_call.arguments,
                    task.session.session_id,
                    emit,
                    extra_reasons,
                    turn_approval_mode=turn_approval_mode,
                )
                result = normalize_result(result)
                metadata_updates = result.metadata.get("session_metadata_updates")
                if isinstance(metadata_updates, dict):
                    task.session.metadata.update(metadata_updates)
                task.session.messages.append(
                    SessionMessage(
                        id=uuid4().hex,
                        role="tool",
                        content=result.stdout or result.summary,
                        metadata={
                            "tool_call_id": tool_call.id,
                            "tool": result.tool,
                            "category": result.category,
                            "success": result.success,
                            "error_code": result.error_code,
                            "severity": result.severity,
                            "risk_level": result.risk_level,
                            "recovery_class": result.recovery_class,
                            "frontend_message": result.frontend_message,
                            "recommended_next_step": result.recommended_next_step,
                        },
                    )
                )
                self.session_store.save(task.session)
                await emit(
                    "tool_call_finished",
                    {
                        "tool_call_id": tool_call.id,
                        "tool": result.tool,
                        "success": result.success,
                        "category": result.category,
                        "error_code": result.error_code,
                        "severity": result.severity,
                        "risk_level": result.risk_level,
                        "recovery_class": result.recovery_class,
                        "frontend_message": result.frontend_message,
                        "recommended_next_step": result.recommended_next_step,
                        "summary": result.summary,
                        "duration_ms": result.duration_ms,
                        "attempt_count": result.attempt_count,
                    },
                )
                if plan_payload := result.metadata.get("plan"):
                    await emit(
                        "plan_updated",
                        {
                            "session_id": task.session.session_id,
                            "plan": plan_payload,
                            "summary": result.summary,
                        },
                    )
                await self._emit_hooks(
                    "PostToolUse",
                    emit,
                    session_id=task.session.session_id,
                    tool=result.tool,
                    success=result.success,
                    category=result.category,
                )
                if result.success and result.tool in {"write_file", "edit_file"}:
                    changed_path = result.metadata.get("path")
                    if isinstance(changed_path, str) and changed_path:
                        await self._emit_hooks(
                            "FileChanged",
                            emit,
                            session_id=task.session.session_id,
                            tool=result.tool,
                            path=changed_path,
                        )
                if not result.success:
                    await self._record_failure_feedback(task, result, emit)
                    if result.recovery_class == "fatal":
                        await self._emit_fatal_error(
                            task,
                            emit,
                            result,
                            finish_reason="fatal_tool_error",
                        )
                        return

            if task.tool_depth >= self.settings.runtime.max_tool_depth:
                await self._finalize_tool_limit(task, emit)
                return

        await emit("error", {"code": "RUNTIME_EXIT", "message": "RunLoop 未能正常完成"})

    async def _stream_provider_response(
        self,
        assembled: list[dict[str, object]],
        tools: list[dict[str, object]],
        emit: EventEmitter,
        *,
        session_id: str,
        turn_id: str | None,
        request_kind: str,
        counts_toward_context_window: bool,
    ) -> ProviderResponse:
        content_parts: list[str] = []
        tool_calls = []
        finish_reason = "stop"
        usage = TokenUsage()
        async for chunk in self.provider.chat_stream(assembled, tools=tools):
            if chunk.type == "text" and chunk.delta:
                content_parts.append(chunk.delta)
                await emit(
                    "assistant_delta",
                    {
                        "content": "".join(content_parts),
                        "model": self.settings.provider.model,
                    },
                )
            elif chunk.type == "tool_call" and chunk.tool_call:
                tool_calls.append(chunk.tool_call)
            elif chunk.type == "usage" and chunk.usage:
                usage = chunk.usage
            elif chunk.type == "done":
                finish_reason = chunk.finish_reason or finish_reason
                if chunk.usage:
                    usage = chunk.usage
        response = ProviderResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            model=self.settings.provider.model,
            finish_reason=finish_reason,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind=request_kind,
                model_config=self.settings.provider,
                provider_type=self.settings.provider.type,
                streaming=True,
                counts_toward_context_window=counts_toward_context_window,
                session_id=session_id,
                turn_id=turn_id,
                metadata={
                    "assembled_message_count": len(assembled),
                    "tool_schema_count": len(tools),
                    "estimated_input_tokens": self.provider.estimate_tokens(assembled),
                    "response_content_length": len(response.content),
                    "tool_call_count": len(response.tool_calls),
                },
            ),
            response,
        )
        return response

    async def _record_failure_feedback(
        self,
        task: SessionTask,
        result: ToolExecutionResult,
        emit: EventEmitter,
    ) -> None:
        await emit(
            "tool_error_feedback",
            {
                "tool": result.tool,
                "category": result.category,
                "error_code": result.error_code,
                "severity": result.severity,
                "risk_level": result.risk_level,
                "recovery_class": result.recovery_class,
                "frontend_message": result.frontend_message,
                "summary": result.summary,
                "retryable": result.retryable,
                "attempt_count": result.attempt_count,
                "recommended_next_step": result.recommended_next_step,
            },
        )
        feedback = self.feedback_writer.build(result)
        task.session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=feedback,
                metadata={
                    "type": "tool_error_feedback",
                    "error_code": result.error_code,
                    "severity": result.severity,
                    "risk_level": result.risk_level,
                    "recovery_class": result.recovery_class,
                    "frontend_message": result.frontend_message,
                    "recommended_next_step": result.recommended_next_step,
                },
            )
        )
        self.session_store.save(task.session)

    async def _finalize_tool_limit(self, task: SessionTask, emit: EventEmitter) -> None:
        limit = self.settings.runtime.max_tool_depth
        instruction = (
            f"你已达到当前回合的工具调用上限（{limit} 次）。"
            "禁止继续调用任何工具。请仅基于现有上下文、已有工具结果和 checkpoint 摘要，"
            "给出一个阶段性结论，并明确告诉用户：如果要继续深入处理，请直接输入“继续”。"
        )
        task.session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=instruction,
                metadata={"type": "tool_limit_guard"},
            )
        )
        self.session_store.save(task.session)

        assembled = self.prompt_assembler.assemble(
            task.session,
            self._tools_overview(),
            json.dumps(self.settings.approval.model_dump(mode="json"), ensure_ascii=False),
            self.checkpoints.get(task.session.session_id),
        )
        try:
            response = await self._stream_provider_response(
                assembled,
                [],
                emit,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                request_kind="tool_limit_finalize",
                counts_toward_context_window=True,
            )
            final_content = response.content.strip()
        except ProviderError:
            final_content = (
                f"已达到当前回合的工具调用上限（{limit} 次）。"
                "我先基于已经完成的检查和工具结果停在这里。"
                "如果你要我继续往下处理，请直接输入“继续”。"
            )

        if not final_content:
            final_content = (
                f"已达到当前回合的工具调用上限（{limit} 次）。"
                "我先基于已经完成的检查和工具结果停在这里。"
                "如果你要我继续往下处理，请直接输入“继续”。"
            )

        assistant_message = SessionMessage(id=uuid4().hex, role="assistant", content=final_content)
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await emit(
            "final_response",
            {
                "session_id": task.session.session_id,
                "content": final_content,
                "finish_reason": "tool_limit_reached",
            },
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="tool_limit_reached",
        )

    def _provider_error_result(self, error: ProviderError) -> ToolExecutionResult:
        result = ToolExecutionResult(
            success=False,
            tool=f"provider:{error.provider}",
            action="chat",
            category=error.kind,
            summary=error.message,
            stderr=json.dumps(
                {
                    "provider": error.provider,
                    "kind": error.kind,
                    "status_code": error.status_code,
                    "details": error.details,
                },
                ensure_ascii=False,
            ),
            retryable=error.retryable,
        )
        return normalize_result(result)

    async def _emit_fatal_error(
        self,
        task: SessionTask,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        finish_reason: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "code": result.error_code,
            "message": result.frontend_message or result.summary,
            "summary": result.summary,
            "tool": result.tool,
            "category": result.category,
            "severity": result.severity,
            "risk_level": result.risk_level,
            "recovery_class": result.recovery_class,
            "retryable": result.retryable,
            "recommended_next_step": result.recommended_next_step,
        }
        if extra:
            payload.update(extra)
        await emit("error", payload)
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason=finish_reason,
        )

    async def _emit_hooks(self, event: str, emit: EventEmitter, **data) -> None:
        for message in self.hook_manager.messages_for(event):
            await emit("hook_triggered", {"event": event, "message": message, "context": data})
        for message in await self.hook_manager.handler_messages_for(event, data):
            await emit("hook_triggered", {"event": event, "message": message, "context": data})

    async def _maybe_checkpoint(self, task: SessionTask, emit: EventEmitter) -> None:
        assembled = self.prompt_assembler.assemble(
            task.session,
            self._tools_overview(),
            json.dumps(self.settings.approval.model_dump(mode="json"), ensure_ascii=False),
            self.checkpoints.get(task.session.session_id),
        )
        effective_context_window = (
            self.settings.provider.effective_context_window or self.settings.provider.context_window or 8_000
        )
        pressure = estimate_pressure(
            self.provider,
            assembled,
            max_context_tokens=effective_context_window,
        )
        if pressure < self.settings.runtime.context_compress_threshold:
            return
        critical = pressure >= self.settings.runtime.context_critical_threshold
        preserve_recent = 4
        original_count = len(task.session.messages)
        checkpoint = self.checkpoints.get(task.session.session_id)
        summary_result = await summarize_messages(
            self.provider,
            self.settings.provider,
            self.settings.provider.type,
            task.session,
            preserve_recent=preserve_recent,
            checkpoint=checkpoint,
            usage_store=self.usage_store,
            turn_id=task.turn_id,
            request_kind="context_compaction",
        )
        if not summary_result:
            return
        _, preserved_messages = split_session_messages(task.session, preserve_recent=preserve_recent)
        task.session.messages = preserved_messages
        task.session.metadata["checkpoint_active"] = True
        self.session_store.save(task.session)
        checkpoint = self.checkpoints.save(
            task.session.session_id,
            summary_result.summary,
            [0, max(0, original_count - preserve_recent)],
            metadata=build_checkpoint_metadata(
                summary_result,
                preserve_recent=preserve_recent,
                compression_level="critical" if critical else "normal",
                original_message_count=original_count,
            ),
        )
        task.session.metadata["checkpoint_restore_hint"] = checkpoint.checkpoint_id
        self.session_store.save(task.session)
        await emit(
            "checkpoint_created",
            {
                "session_id": task.session.session_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "summary": checkpoint.summary,
                "compression_level": checkpoint.metadata.get("compression_level", "normal"),
            },
        )
