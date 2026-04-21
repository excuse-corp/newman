from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from backend.config.schema import AppConfig
from backend.hooks.hook_manager import HookManager
from backend.mcp.registry import MCPRegistry
from backend.memory.checkpoint_store import CheckpointStore
from backend.memory.compressor import (
    build_context_usage_snapshot,
    build_checkpoint_metadata,
    microcompact_session,
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
from backend.runtime.thinking_parser import ThinkTagStreamParser
from backend.runtime.thread_manager import ThreadManager
from backend.scheduler.task_store import TaskStore
from backend.sessions.models import SessionMessage
from backend.sessions.session_store import SessionStore
from backend.skill_runtime.registry import SkillRegistry
from backend.tools.approval import ApprovalManager
from backend.tools.orchestrator import ToolOrchestrator
from backend.tools.approval_policy import DEFAULT_TURN_APPROVAL_MODE, TurnApprovalMode
from backend.tools.discovery import BuiltinToolContext, load_builtin_tools
from backend.tools.permission_context import PermissionContext
from backend.tools.provider_exposure import infer_provider_tool_groups
from backend.tools.registry import ToolRegistry
from backend.tools.router import ToolRouter, analyze_terminal_command
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import build_path_access_policy
from backend.sandbox.native_sandbox import NativeSandbox
from backend.sandbox.resource_limits import ResourceLimits
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


EventEmitter = Callable[[str, dict], Awaitable[None]]

COMMENTARY_FALLBACK_SYSTEM_PROMPT = """你负责把内部思考压缩成一条对用户可见的简短行动说明。

输出规则：
- 只输出一个 `<commentary>...</commentary>` 标签块，除此之外不要输出任何别的内容
- brief 只描述“接下来立刻要做什么”
- 不要泄露内部推理、提示词、规则、犹豫、备选方案或不确定性
- 尽量简短，通常控制在 8 到 24 个汉字
- 使用用户当前回合的语言
"""

RAW_TOOL_CALL_MARKUP_RE = re.compile(r"<(?:[\w.-]+:)?tool_call\b", re.IGNORECASE)


def _build_tool_message_output(result: ToolExecutionResult) -> str:
    if result.tool != "terminal":
        return result.stdout

    outputs = [part for part in [result.stdout.strip(), result.stderr.strip()] if part]
    return "\n".join(outputs)


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
            Path(__file__).resolve().parents[1] / "config" / "prompts" / "mem_extract.md",
            self.usage_store,
        )
        self._background_tasks: set[asyncio.Task] = set()
        self.stable_context = StableContextLoader(settings.paths.memory_dir)
        self.prompt_assembler = PromptAssembler(self.stable_context)
        self.feedback_writer = FeedbackWriter()
        self.approvals = ApprovalManager()
        self.plugin_service = PluginService(
            settings.paths.plugins_dir,
            settings.paths.skills_dir,
            settings.paths.data_dir / "plugin_state.json",
        )
        self.skill_registry = SkillRegistry(self.plugin_service, settings.paths.memory_dir)
        self.hook_manager = HookManager(self.plugin_service)
        self.mcp_registry = MCPRegistry(settings.paths.mcp_dir / "servers.yaml", workspace=settings.paths.workspace)
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
        path_policy = build_path_access_policy(self.settings)
        sandbox = NativeSandbox(
            workspace=workspace,
            limits=limits,
            config=self.settings.sandbox,
            path_policy=path_policy,
        )
        self.exec_sandbox = sandbox
        knowledge_base = KnowledgeBaseService(
            self.settings.paths.knowledge_dir,
            workspace,
            self.settings.models,
            self.settings.rag,
            self.settings.paths.chroma_dir,
            self.usage_store,
        )
        tool_context = BuiltinToolContext(
            path_policy=path_policy,
            sandbox=sandbox,
            knowledge_base=knowledge_base,
        )
        registry = ToolRegistry()
        for tool in load_builtin_tools(tool_context):
            registry.register(tool)
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
        request_id: str | None = None,
        turn_id: str | None = None,
        on_turn_created: Callable[[str], None] | None = None,
    ) -> None:
        self.reload_ecosystem()
        resolved_turn_id = turn_id or uuid4().hex
        user_message = SessionMessage(
            id=resolved_turn_id,
            role="user",
            content=content,
            metadata=self._build_message_metadata(
                turn_id=None,
                request_id=request_id,
                extra=user_metadata or {},
            ),
        )
        user_message.metadata["turn_id"] = resolved_turn_id
        session = self.session_store.append_message(session_id, user_message)
        if on_turn_created is not None:
            on_turn_created(resolved_turn_id)

        task = SessionTask(session=session, permission_context=PermissionContext(), turn_id=resolved_turn_id)
        turn_emit = self._bind_turn_emitter(emit, task.turn_id)
        await self._emit_hooks("SessionStart", turn_emit, session_id=session.session_id, content=content)
        provider_feedback_attempted = False

        for _ in range(self.settings.runtime.max_tool_depth):
            group_id = task.next_action_group_id()
            self.skill_registry.sync_snapshot()
            await self._maybe_checkpoint(task, turn_emit)
            assembled = self._assemble_task_messages(task)
            provider_tools = self._provider_tools_for_turn(task)

            try:
                response = await self._stream_provider_response(
                    assembled,
                    provider_tools,
                    turn_emit,
                    session_id=task.session.session_id,
                    turn_id=task.turn_id,
                    request_kind="session_turn",
                    counts_toward_context_window=True,
                    group_id=group_id,
                    emit_answer_started=task.tool_depth > 0,
                )
            except ProviderError as exc:
                result = self._provider_error_result(exc)
                await self._record_failure_feedback(task, result, turn_emit, request_id=request_id)
                if exc.retryable and result.recovery_class == "recoverable" and not provider_feedback_attempted:
                    provider_feedback_attempted = True
                    continue
                await self._emit_fatal_error(
                    task,
                    turn_emit,
                    result,
                    finish_reason="provider_error",
                    extra={"provider": exc.provider, "status_code": exc.status_code},
                )
                return

            response = await self._ensure_tool_response_commentary(
                task,
                response,
                turn_emit,
                group_id=group_id,
            )

            if not response.tool_calls:
                final_content = response.content or response.commentary
                assistant_message = SessionMessage(
                    id=uuid4().hex,
                    role="assistant",
                    content=final_content,
                    metadata=self._build_message_metadata(
                        task.turn_id,
                        request_id,
                        extra={"finish_reason": response.finish_reason},
                    ),
                )
                task.session.messages.append(assistant_message)
                self.session_store.save(task.session)
                await turn_emit(
                    "final_response",
                    {
                        "session_id": task.session.session_id,
                        "content": final_content,
                        "finish_reason": response.finish_reason,
                        "message_id": assistant_message.id,
                        "created_at": assistant_message.created_at,
                    },
                )
                if self.memory_extractor.looks_like_explicit_persistence_signal(content):
                    self.schedule_user_memory_extraction(task.session.session_id, "explicit_user_request")
                await self._emit_hooks(
                    "SessionEnd",
                    turn_emit,
                    session_id=task.session.session_id,
                    finish_reason=response.finish_reason,
                )
                return

            assistant_tool_message = SessionMessage(
                id=uuid4().hex,
                role="assistant",
                content=self._compose_tool_call_assistant_content(response),
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={
                        "group_id": group_id,
                        "commentary": response.commentary,
                        "phase": "commentary" if response.commentary else "tool_call",
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            }
                            for tool_call in response.tool_calls
                        ]
                    },
                ),
            )
            task.session.messages.append(assistant_tool_message)
            self.session_store.save(task.session)

            for tool_call in response.tool_calls:
                task.tool_depth += 1
                tool = self.router.route(tool_call.name, tool_call.arguments)
                extra_reasons = self.router.static_checks(tool, tool_call.arguments)
                await self._emit_hooks(
                    "PreToolUse",
                    turn_emit,
                    session_id=task.session.session_id,
                    tool=tool_call.name,
                    arguments=tool_call.arguments,
                    group_id=group_id,
                )
                await turn_emit(
                    "tool_call_started",
                    {
                        "group_id": group_id,
                        "tool_call_id": tool_call.id,
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                )
                result = await self.orchestrator.execute(
                    tool,
                    tool_call.arguments,
                    task.session.session_id,
                    turn_emit,
                    tool_call_id=tool_call.id,
                    group_id=group_id,
                    extra_reasons=extra_reasons,
                    turn_approval_mode=turn_approval_mode,
                    turn_id=task.turn_id,
                )
                result = normalize_result(result)
                metadata_updates = result.metadata.get("session_metadata_updates")
                if isinstance(metadata_updates, dict):
                    task.session.metadata.update(metadata_updates)
                task.session.messages.append(
                    self._build_tool_session_message(
                        task,
                        result,
                        tool_call_id=tool_call.id,
                        group_id=group_id,
                        request_id=request_id,
                    )
                )
                self.session_store.save(task.session)
                await turn_emit(
                    "tool_call_finished",
                    {
                        "group_id": group_id,
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
                    await turn_emit(
                        "plan_updated",
                        {
                            "session_id": task.session.session_id,
                            "plan": plan_payload,
                            "summary": result.summary,
                        },
                    )
                await self._emit_hooks(
                    "PostToolUse",
                    turn_emit,
                    session_id=task.session.session_id,
                    tool=result.tool,
                    success=result.success,
                    category=result.category,
                    group_id=group_id,
                )
                if result.success and result.tool in {"write_file", "edit_file"}:
                    changed_path = result.metadata.get("path")
                    if isinstance(changed_path, str) and changed_path:
                        if self._should_reload_ecosystem_for_path(changed_path):
                            self.reload_ecosystem()
                        await self._emit_hooks(
                            "FileChanged",
                            turn_emit,
                            session_id=task.session.session_id,
                            tool=result.tool,
                            path=changed_path,
                            group_id=group_id,
                        )
                if result.success and result.tool == "terminal":
                    command = str(tool_call.arguments.get("command", ""))
                    if command and self._should_reload_ecosystem_for_terminal_command(command):
                        self.reload_ecosystem()
                if not result.success:
                    await self._record_failure_feedback(task, result, turn_emit, request_id=request_id)
                    if result.recovery_class == "fatal":
                        await self._finalize_fatal_tool_error(
                            task,
                            turn_emit,
                            result,
                            request_id=request_id,
                        )
                        return

            if task.tool_depth >= self.settings.runtime.max_tool_depth:
                await self._finalize_tool_limit(task, turn_emit, request_id=request_id)
                return

        await turn_emit("error", {"code": "RUNTIME_EXIT", "message": "RunLoop 未能正常完成"})

    def _should_reload_ecosystem_for_path(self, changed_path: str) -> bool:
        path = Path(changed_path).resolve()
        watched_roots = (
            self.settings.paths.skills_dir.resolve(),
            self.settings.paths.plugins_dir.resolve(),
            (Path(__file__).resolve().parents[1] / "tools").resolve(),
        )
        return any(path.is_relative_to(root) for root in watched_roots)

    def _should_reload_ecosystem_for_terminal_command(self, command: str) -> bool:
        analysis = analyze_terminal_command(command, build_path_access_policy(self.settings))
        if not analysis.mutating:
            return False
        return any(
            match.state == "writable" and self._should_reload_ecosystem_for_path(str(match.path))
            for match in analysis.path_matches
        )

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
        group_id: str | None = None,
        emit_answer_started: bool = False,
    ) -> ProviderResponse:
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        commentary_parts: list[str] = []
        tool_calls = []
        finish_reason = "stop"
        usage = TokenUsage()
        parser = ThinkTagStreamParser()
        commentary_visible = False
        commentary_complete_pending = False
        answer_visible = False
        answer_started_emitted = False
        buffer_answer_until_done = emit_answer_started and bool(tools)

        async def flush_commentary(*, force: bool = False, delta: str | None = None) -> None:
            nonlocal commentary_visible, commentary_complete_pending
            if not group_id or not commentary_parts:
                return
            if not commentary_visible:
                if not force and not tool_calls:
                    return
                commentary_visible = True
                await emit(
                    "commentary_delta",
                    {
                        "group_id": group_id,
                        "content": "".join(commentary_parts),
                        "delta": "".join(commentary_parts),
                        "model": self.settings.provider.model,
                    },
                )
            elif delta:
                await emit(
                    "commentary_delta",
                    {
                        "group_id": group_id,
                        "content": "".join(commentary_parts),
                        "delta": delta,
                        "model": self.settings.provider.model,
                    },
                )
            if commentary_complete_pending:
                await emit(
                    "commentary_complete",
                    {
                        "group_id": group_id,
                        "content": "".join(commentary_parts),
                        "model": self.settings.provider.model,
                    },
                )
                commentary_complete_pending = False

        async def consume_parse_event(event) -> None:
            nonlocal commentary_complete_pending, answer_visible, answer_started_emitted
            if event.kind == "answer" and event.text:
                content_parts.append(event.text)
                if not "".join(content_parts).strip():
                    return
                if buffer_answer_until_done:
                    return
                if emit_answer_started and not answer_started_emitted:
                    answer_started_emitted = True
                    await emit(
                        "answer_started",
                        {
                            "group_id": group_id,
                            "model": self.settings.provider.model,
                        },
                    )
                answer_visible = True
                await emit(
                    "assistant_delta",
                    {
                        "content": "".join(content_parts),
                        "delta": event.text,
                        "model": self.settings.provider.model,
                    },
                )
                return
            if event.kind == "thinking" and event.text:
                thinking_parts.append(event.text)
                await emit(
                    "thinking_delta",
                    {
                        "content": "".join(thinking_parts),
                        "delta": event.text,
                        "model": self.settings.provider.model,
                    },
                )
                return
            if event.kind == "thinking_complete":
                await emit(
                    "thinking_complete",
                    {
                        "content": "".join(thinking_parts),
                        "model": self.settings.provider.model,
                    },
                )
                return
            if event.kind == "commentary" and event.text:
                commentary_parts.append(event.text)
                await flush_commentary(delta=event.text)
                return
            if event.kind == "commentary_complete":
                commentary_complete_pending = True
                await flush_commentary()

        async for chunk in self.provider.chat_stream(assembled, tools=tools):
            if chunk.type == "text" and chunk.delta:
                for event in parser.feed(chunk.delta):
                    await consume_parse_event(event)
            elif chunk.type == "tool_call" and chunk.tool_call:
                leaked_answer = self._sanitize_commentary_brief("".join(content_parts))
                if answer_visible:
                    content_parts.clear()
                    answer_visible = False
                    await emit(
                        "assistant_delta",
                        {
                            "content": "",
                            "delta": "",
                            "model": self.settings.provider.model,
                            "reset": True,
                        },
                    )
                elif leaked_answer:
                    content_parts.clear()
                if leaked_answer and not commentary_parts:
                    commentary_parts.append(leaked_answer)
                    commentary_complete_pending = True
                tool_calls.append(chunk.tool_call)
                await flush_commentary(force=True)
            elif chunk.type == "usage" and chunk.usage:
                usage = chunk.usage
            elif chunk.type == "done":
                finish_reason = chunk.finish_reason or finish_reason
                if chunk.usage:
                    usage = chunk.usage
        for event in parser.flush():
            await consume_parse_event(event)
        if buffer_answer_until_done and not tool_calls and "".join(content_parts).strip():
            if emit_answer_started and not answer_started_emitted:
                answer_started_emitted = True
                await emit(
                    "answer_started",
                    {
                        "group_id": group_id,
                        "model": self.settings.provider.model,
                    },
                )
            answer_visible = True
            await emit(
                "assistant_delta",
                {
                    "content": "".join(content_parts),
                    "delta": "".join(content_parts),
                    "model": self.settings.provider.model,
                },
            )
        await flush_commentary(force=bool(tool_calls))
        response = ProviderResponse(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
            commentary="".join(commentary_parts),
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
                    "response_thinking_length": len(response.thinking),
                    "response_commentary_length": len(response.commentary),
                    "tool_call_count": len(response.tool_calls),
                },
            ),
            response,
        )
        return response

    async def _ensure_tool_response_commentary(
        self,
        task: SessionTask,
        response: ProviderResponse,
        emit: EventEmitter,
        *,
        group_id: str,
    ) -> ProviderResponse:
        if not response.tool_calls or response.commentary.strip():
            return response

        commentary = await self._generate_commentary_from_thinking(task, response)
        if not commentary:
            return response

        response.commentary = commentary
        await emit(
            "commentary_delta",
            {
                "group_id": group_id,
                "content": commentary,
                "delta": commentary,
                "model": response.model or self.settings.provider.model,
            },
        )
        await emit(
            "commentary_complete",
            {
                "group_id": group_id,
                "content": commentary,
                "model": response.model or self.settings.provider.model,
            },
        )
        return response

    async def _generate_commentary_from_thinking(
        self,
        task: SessionTask,
        response: ProviderResponse,
    ) -> str:
        thinking = response.thinking.strip()
        if not thinking:
            return ""
        thinking_excerpt = thinking[:1600]

        user_content = self._current_turn_user_content(task.session, task.turn_id)
        tool_names = ", ".join(tool_call.name for tool_call in response.tool_calls) or "无"
        messages = [
            {"role": "system", "content": COMMENTARY_FALLBACK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请基于下面的信息生成一句工具调用前的 brief。\n\n"
                    f"用户请求：\n{user_content or '（未找到）'}\n\n"
                    f"即将执行的工具：\n{tool_names}\n\n"
                    f"内部思考：\n{thinking_excerpt}"
                ),
            },
        ]
        try:
            fallback = await self.provider.chat(messages, tools=[])
        except ProviderError:
            return ""

        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="commentary_fallback",
                model_config=self.settings.provider,
                provider_type=self.settings.provider.type,
                streaming=False,
                counts_toward_context_window=False,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                metadata={
                    "tool_names": [tool_call.name for tool_call in response.tool_calls],
                    "thinking_length": len(thinking),
                    "thinking_excerpt_length": len(thinking_excerpt),
                },
            ),
            fallback,
        )

        commentary, answer = self._parse_response_text(fallback.content)
        brief = commentary.strip() or answer.strip()
        return self._sanitize_commentary_brief(brief)

    async def _record_failure_feedback(
        self,
        task: SessionTask,
        result: ToolExecutionResult,
        emit: EventEmitter,
        *,
        request_id: str | None = None,
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
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={
                        "type": "tool_error_feedback",
                        "error_code": result.error_code,
                        "severity": result.severity,
                        "risk_level": result.risk_level,
                        "recovery_class": result.recovery_class,
                        "frontend_message": result.frontend_message,
                        "recommended_next_step": result.recommended_next_step,
                    },
                ),
            )
        )
        self.session_store.save(task.session)

    async def _finalize_tool_limit(
        self,
        task: SessionTask,
        emit: EventEmitter,
        *,
        request_id: str | None = None,
    ) -> None:
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
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={"type": "tool_limit_guard"},
                ),
            )
        )
        self.session_store.save(task.session)
        await self._maybe_checkpoint(task, emit)

        assembled = self._assemble_task_messages(task)
        try:
            response = await self._stream_provider_response(
                assembled,
                [],
                emit,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                request_kind="tool_limit_finalize",
                counts_toward_context_window=True,
                emit_answer_started=task.tool_depth > 0,
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

        assistant_message = SessionMessage(
            id=uuid4().hex,
            role="assistant",
            content=final_content,
            metadata=self._build_message_metadata(
                task.turn_id,
                request_id,
                extra={"finish_reason": "tool_limit_reached"},
            ),
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await emit(
            "final_response",
            {
                "session_id": task.session.session_id,
                "content": final_content,
                "finish_reason": "tool_limit_reached",
                "message_id": assistant_message.id,
                "created_at": assistant_message.created_at,
            },
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="tool_limit_reached",
        )

    async def _finalize_fatal_tool_error(
        self,
        task: SessionTask,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        request_id: str | None = None,
    ) -> None:
        instruction = (
            "刚才的工具调用已经确认失败。禁止继续调用任何工具，也不要重复同一个失败动作。"
            "如果不依赖该工具，你仍然可以基于现有上下文直接回答用户原问题，请直接给出最终回答。"
            "如果无法可靠回答，就明确说明阻塞原因、失败工具、关键报错，以及建议用户下一步怎么做。"
            "不要假装工具成功。"
        )
        task.session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=instruction,
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={
                        "type": "fatal_tool_finalize",
                        "error_code": result.error_code,
                        "tool": result.tool,
                    },
                ),
            )
        )
        self.session_store.save(task.session)
        await self._maybe_checkpoint(task, emit)

        assembled = self._assemble_task_messages(task)

        finish_reason = "fatal_tool_error"
        try:
            response = await self._stream_provider_response(
                assembled,
                [],
                emit,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                request_kind="fatal_tool_finalize",
                counts_toward_context_window=True,
                emit_answer_started=task.tool_depth > 0,
            )
            final_content = response.content.strip()
            if response.tool_calls or self._contains_raw_tool_call_markup(final_content):
                final_content = ""
            if response.finish_reason:
                finish_reason = response.finish_reason
        except ProviderError:
            final_content = ""

        if not final_content:
            final_content = self._build_fatal_tool_fallback_message(result)

        assistant_message = SessionMessage(
            id=uuid4().hex,
            role="assistant",
            content=final_content,
            metadata=self._build_message_metadata(
                task.turn_id,
                request_id,
                extra={"finish_reason": finish_reason},
            ),
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await emit(
            "final_response",
            {
                "session_id": task.session.session_id,
                "content": final_content,
                "finish_reason": finish_reason,
                "message_id": assistant_message.id,
                "created_at": assistant_message.created_at,
            },
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="fatal_tool_error",
        )

    def _contains_raw_tool_call_markup(self, text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        if RAW_TOOL_CALL_MARKUP_RE.search(normalized):
            return True
        return "<invoke" in normalized or "<parameter" in normalized

    def _build_fatal_tool_fallback_message(self, result: ToolExecutionResult) -> str:
        if result.error_code == "NEWMAN-TOOL-005" or result.category == "user_rejected":
            return "工具调用申请被用户拒绝或审批超时，当前任务已终止"
        blocker = result.frontend_message or "工具执行失败"
        summary = result.summary.strip() or "没有返回更具体的错误摘要。"
        lines = [
            f"这一步被阻塞了：`{result.tool}` {blocker}。",
            f"原因：{summary}",
        ]
        if result.recommended_next_step:
            lines.append(f"建议：{result.recommended_next_step}")
        lines.append("如果你愿意，我可以先不依赖这个工具，直接基于现有上下文继续回答。")
        return "\n".join(lines)

    def _compose_tool_call_assistant_content(self, response: ProviderResponse) -> str:
        commentary = response.commentary.strip()
        content = response.content.strip()
        if commentary and content:
            return f"{commentary}\n\n{content}"
        return commentary or content

    def _parse_response_text(self, text: str) -> tuple[str, str]:
        parser = ThinkTagStreamParser()
        commentary_parts: list[str] = []
        answer_parts: list[str] = []
        for event in parser.feed(text):
            if event.kind == "commentary" and event.text:
                commentary_parts.append(event.text)
            elif event.kind == "answer" and event.text:
                answer_parts.append(event.text)
        for event in parser.flush():
            if event.kind == "commentary" and event.text:
                commentary_parts.append(event.text)
            elif event.kind == "answer" and event.text:
                answer_parts.append(event.text)
        return "".join(commentary_parts), "".join(answer_parts)

    def _sanitize_commentary_brief(self, text: str) -> str:
        return " ".join(text.replace("\n", " ").split()).strip()

    def _current_turn_user_content(self, session, turn_id: str) -> str:
        for message in reversed(session.messages):
            if message.role != "user":
                continue
            if message.metadata.get("turn_id") == turn_id:
                return message.content
        for message in reversed(session.messages):
            if message.role == "user":
                return message.content
        return ""

    def _assemble_task_messages(
        self,
        task: SessionTask,
        *,
        checkpoint=None,
    ) -> list[dict]:
        resolved_checkpoint = checkpoint if checkpoint is not None else self.checkpoints.get(task.session.session_id)
        return self.prompt_assembler.assemble(
            task.session,
            self._tools_overview(),
            resolved_checkpoint,
            tool_message_overrides=task.transient_tool_messages,
        )

    def _provider_tools_for_turn(self, task: SessionTask) -> list[dict[str, object]]:
        user_content = self._current_turn_user_content(task.session, task.turn_id)
        active_groups = infer_provider_tool_groups(user_content)
        return self.registry.tools_for_provider(task.permission_context, active_groups=active_groups)

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
        group_id = data.get("group_id")
        for message in self.hook_manager.messages_for(event):
            payload = {"event": event, "message": message, "context": data}
            if isinstance(group_id, str) and group_id:
                payload["group_id"] = group_id
            await emit("hook_triggered", payload)
        for message in await self.hook_manager.handler_messages_for(event, data):
            payload = {"event": event, "message": message, "context": data}
            if isinstance(group_id, str) and group_id:
                payload["group_id"] = group_id
            await emit("hook_triggered", payload)

    async def _maybe_checkpoint(self, task: SessionTask, emit: EventEmitter) -> None:
        assembled = self._assemble_task_messages(task)
        latest_record = self._latest_context_record(task.session.session_id)
        context_usage = build_context_usage_snapshot(
            self.provider,
            self.settings.provider,
            self.settings.runtime,
            assembled,
            task.session,
            self.checkpoints.get(task.session.session_id),
            latest_record=latest_record,
        )
        projected_next_prompt_tokens = context_usage.projected_next_prompt_tokens
        auto_compact_limit = context_usage.auto_compact_limit
        if projected_next_prompt_tokens < auto_compact_limit:
            self._reset_compaction_state(task)
            return

        if self._compaction_fail_streak(task) >= self.settings.runtime.context_compaction_max_failures:
            self._mark_compaction_failure(task, irreducible=True, reason="max_failures_reached")
            return

        critical = context_usage.projected_pressure >= self.settings.runtime.context_critical_threshold
        preserve_recent = self.settings.runtime.context_compaction_preserve_recent
        microcompact_count = microcompact_session(task.session, preserve_recent=preserve_recent)
        if microcompact_count > 0:
            task.session.metadata["last_compaction_stage"] = "microcompact"
            self.session_store.save(task.session)
            microcompact_usage = build_context_usage_snapshot(
                self.provider,
                self.settings.provider,
                self.settings.runtime,
                self._assemble_task_messages(task),
                task.session,
                self.checkpoints.get(task.session.session_id),
                latest_record=latest_record,
            )
            if microcompact_usage.projected_next_prompt_tokens < microcompact_usage.auto_compact_limit:
                self._reset_compaction_state(task)
                return

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
            self._mark_compaction_failure(task, irreducible=True, reason="nothing_to_compress")
            return
        _, preserved_messages = split_session_messages(task.session, preserve_recent=preserve_recent)
        task.session.messages = preserved_messages
        task.session.metadata["checkpoint_active"] = True
        task.session.metadata["last_compaction_stage"] = "checkpoint_compact"
        self.session_store.save(task.session)
        checkpoint = self.checkpoints.save(
            task.session.session_id,
            summary_result.summary,
            [0, max(0, original_count - len(preserved_messages))],
            metadata=build_checkpoint_metadata(
                summary_result,
                preserve_recent=preserve_recent,
                compression_level="critical" if critical else "normal",
                original_message_count=original_count,
            ),
        )
        task.session.metadata["checkpoint_restore_hint"] = checkpoint.checkpoint_id
        self.session_store.save(task.session)
        refreshed_usage = build_context_usage_snapshot(
            self.provider,
            self.settings.provider,
            self.settings.runtime,
            self._assemble_task_messages(task, checkpoint=checkpoint),
            task.session,
            checkpoint,
            latest_record=latest_record,
        )
        if refreshed_usage.projected_next_prompt_tokens >= refreshed_usage.auto_compact_limit:
            self._mark_compaction_failure(task, irreducible=False, reason="post_compaction_still_over_limit")
        else:
            self._reset_compaction_state(task)
        await emit(
            "checkpoint_created",
            {
                "session_id": task.session.session_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "summary": checkpoint.summary,
                "compression_level": checkpoint.metadata.get("compression_level", "normal"),
            },
        )

    def _latest_context_record(self, session_id: str):
        if self.usage_store is None:
            return None
        try:
            return self.usage_store.latest_context_record(session_id)
        except Exception:
            return None

    def _compaction_fail_streak(self, task: SessionTask) -> int:
        raw_value = task.session.metadata.get("compaction_fail_streak")
        return raw_value if isinstance(raw_value, int) and raw_value >= 0 else 0

    def _reset_compaction_state(self, task: SessionTask) -> None:
        task.session.metadata["compaction_fail_streak"] = 0
        task.session.metadata["context_irreducible"] = False
        task.session.metadata.pop("last_compaction_failure_reason", None)
        self.session_store.save(task.session)

    def _mark_compaction_failure(self, task: SessionTask, *, irreducible: bool, reason: str) -> None:
        next_fail_streak = self._compaction_fail_streak(task) + 1
        task.session.metadata["compaction_fail_streak"] = next_fail_streak
        task.session.metadata["context_irreducible"] = irreducible or (
            next_fail_streak >= self.settings.runtime.context_compaction_max_failures
        )
        task.session.metadata["last_compaction_failure_reason"] = reason
        self.session_store.save(task.session)

    def _build_message_metadata(
        self,
        turn_id: str | None,
        request_id: str | None,
        *,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {}
        if turn_id:
            metadata["turn_id"] = turn_id
        if request_id:
            metadata["request_id"] = request_id
        if extra:
            metadata.update(extra)
        return metadata

    def _build_tool_session_message(
        self,
        task: SessionTask,
        result: ToolExecutionResult,
        *,
        tool_call_id: str,
        group_id: str,
        request_id: str | None,
    ) -> SessionMessage:
        model_output = _build_tool_message_output(result) or result.summary
        persisted_output = result.persisted_output if result.persisted_output is not None else model_output
        metadata = {
            "turn_id": task.turn_id,
            **({"request_id": request_id} if request_id else {}),
            "group_id": group_id,
            "tool_call_id": tool_call_id,
            "tool": result.tool,
            "category": result.category,
            "success": result.success,
            "error_code": result.error_code,
            "severity": result.severity,
            "risk_level": result.risk_level,
            "recovery_class": result.recovery_class,
            "frontend_message": result.frontend_message,
            "recommended_next_step": result.recommended_next_step,
            "content_persisted": persisted_output == model_output,
        }
        if persisted_output != model_output:
            task.transient_tool_messages[tool_call_id] = SessionMessage(
                id=uuid4().hex,
                role="tool",
                content=model_output,
                metadata=dict(metadata),
            )
        else:
            task.transient_tool_messages.pop(tool_call_id, None)
        return SessionMessage(
            id=uuid4().hex,
            role="tool",
            content=persisted_output,
            metadata=dict(metadata),
        )

    def _bind_turn_emitter(self, emit: EventEmitter, turn_id: str | None) -> EventEmitter:
        async def emit_with_turn(event: str, data: dict) -> None:
            payload = dict(data)
            if turn_id and "turn_id" not in payload:
                payload["turn_id"] = turn_id
            await emit(event, payload)

        return emit_with_turn
