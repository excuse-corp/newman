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
from backend.memory.compressor import estimate_pressure, summarize_messages
from backend.memory.memory_extract import MemoryExtractor
from backend.memory.stable_context import StableContextLoader
from backend.plugin_runtime.service import PluginService
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
from backend.tools.permission_context import PermissionContext
from backend.tools.registry import ToolRegistry
from backend.tools.router import ToolRouter
from backend.sandbox.docker_sandbox import DockerSandbox
from backend.sandbox.resource_limits import ResourceLimits


EventEmitter = Callable[[str, dict], Awaitable[None]]


class NewmanRuntime:
    def __init__(self, settings: AppConfig):
        self.settings = settings
        self.provider = build_provider(settings.provider)
        self.session_store = SessionStore(settings.paths.sessions_dir)
        self.thread_manager = ThreadManager(self.session_store)
        self.checkpoints = CheckpointStore(settings.paths.sessions_dir)
        self.memory_extractor = MemoryExtractor(
            self.provider,
            settings.provider.type,
            self.session_store,
            self.checkpoints,
            settings.paths.memory_dir / "USER.md",
            settings.paths.memory_dir / "MEMORY.md",
            settings.paths.workspace / "backend" / "config" / "prompts" / "mem_extract.md",
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
        self.reload_ecosystem()

    def reload_ecosystem(self) -> None:
        self.plugin_service.reload()
        self.skill_registry.sync_snapshot()
        self.registry = self._build_registry(self.settings.paths.workspace)
        self.router = ToolRouter(self.registry, self.settings)

    def schedule_previous_session_extraction(self, exclude_session_id: str) -> dict[str, object]:
        previous = self.session_store.latest(exclude_session_ids={exclude_session_id}, require_messages=True)
        if previous is None:
            return {
                "scheduled": False,
                "trigger": "new_session_created",
                "source_session_id": None,
                "reason": "no_previous_session",
            }
        return self.schedule_memory_extraction(previous.session_id, "new_session_created")

    def schedule_memory_extraction(self, session_id: str, trigger: str) -> dict[str, object]:
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
            cpu_limit=self.settings.sandbox.cpu_limit,
            memory_limit=self.settings.sandbox.memory_limit,
            timeout_seconds=self.settings.sandbox.timeout,
            output_limit_bytes=self.settings.sandbox.output_limit_bytes,
        )
        sandbox = DockerSandbox(workspace=workspace, limits=limits, enabled=self.settings.sandbox.enabled)
        knowledge_base = KnowledgeBaseService(self.settings.paths.knowledge_dir, workspace)
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

    async def handle_message(self, session_id: str, content: str, emit: EventEmitter) -> None:
        session = self.session_store.get(session_id)
        user_message = SessionMessage(id=uuid4().hex, role="user", content=content)
        session.messages.append(user_message)
        self.session_store.save(session)
        await self._emit_hooks("SessionStart", emit, session_id=session.session_id, content=content)

        task = SessionTask(session=session, permission_context=PermissionContext())
        await self._maybe_checkpoint(task, emit)

        for _ in range(self.settings.runtime.max_tool_depth):
            self.skill_registry.sync_snapshot()
            assembled = self.prompt_assembler.assemble(
                task.session,
                self.registry.describe(),
                json.dumps(self.settings.approval.model_dump(mode="json"), ensure_ascii=False),
                self.checkpoints.get(task.session.session_id),
            )

            response = await self.provider.chat(
                assembled,
                tools=self.registry.tools_for_provider(task.permission_context),
            )

            if not response.tool_calls:
                assistant_message = SessionMessage(id=uuid4().hex, role="assistant", content=response.content)
                task.session.messages.append(assistant_message)
                self.session_store.save(task.session)
                await emit("assistant_delta", {"content": response.content, "model": response.model})
                await emit(
                    "final_response",
                    {
                        "session_id": task.session.session_id,
                        "content": response.content,
                        "finish_reason": response.finish_reason,
                    },
                )
                if self.memory_extractor.looks_like_explicit_persistence_signal(content):
                    self.schedule_memory_extraction(task.session.session_id, "explicit_user_request")
                await self._emit_hooks(
                    "SessionEnd",
                    emit,
                    session_id=task.session.session_id,
                    finish_reason=response.finish_reason,
                )
                return

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
                result = await self.orchestrator.execute(tool, tool_call.arguments, task.session.session_id, emit, extra_reasons)
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
                            "tool": result.tool,
                            "category": result.category,
                            "success": result.success,
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
                if not result.success:
                    await emit(
                        "tool_error_feedback",
                        {
                            "tool": result.tool,
                            "category": result.category,
                            "error_code": result.error_code,
                            "severity": result.severity,
                            "summary": result.summary,
                            "retryable": result.retryable,
                            "attempt_count": result.attempt_count,
                        },
                    )
                    feedback = self.feedback_writer.build(result)
                    task.session.messages.append(
                        SessionMessage(id=uuid4().hex, role="system", content=feedback, metadata={"type": "tool_error_feedback"})
                    )
                    self.session_store.save(task.session)

            if task.tool_depth >= self.settings.runtime.max_tool_depth:
                await emit(
                    "error",
                    {
                        "code": "RUNTIME_MAX_TOOL_DEPTH",
                        "message": "工具调用深度达到上限",
                    },
                )
                return

        await emit("error", {"code": "RUNTIME_EXIT", "message": "RunLoop 未能正常完成"})

    async def _emit_hooks(self, event: str, emit: EventEmitter, **data) -> None:
        for message in self.hook_manager.messages_for(event):
            await emit("hook_triggered", {"event": event, "message": message, "context": data})

    async def _maybe_checkpoint(self, task: SessionTask, emit: EventEmitter) -> None:
        assembled = self.prompt_assembler.assemble(
            task.session,
            self.registry.describe(),
            json.dumps(self.settings.approval.model_dump(mode="json"), ensure_ascii=False),
            self.checkpoints.get(task.session.session_id),
        )
        pressure = estimate_pressure(self.provider, assembled)
        if pressure < self.settings.runtime.context_compress_threshold:
            return
        summary = summarize_messages(task.session)
        if not summary:
            return
        preserve_recent = 4
        task.session.messages = task.session.messages[-preserve_recent:]
        self.session_store.save(task.session)
        checkpoint = self.checkpoints.save(task.session.session_id, summary, [0, max(0, len(task.session.messages) - preserve_recent)])
        await emit(
            "checkpoint_created",
            {
                "session_id": task.session.session_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "summary": checkpoint.summary,
            },
        )
