from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import asyncio
from typing import TYPE_CHECKING, Any, Awaitable
from uuid import uuid4

from backend.config.schema import AppConfig
from backend.sessions.models import utc_now
from backend.subagents.cancellation import CancellationRegistry, CancellationRequest
from backend.subagents.events import (
    failure_decision_required_payload,
    failure_decision_resolved_payload,
    run_event_payload,
    task_event_payload,
)
from backend.subagents.models import (
    AgentReport,
    MultiAgentReport,
    MultiAgentRun,
    SubagentTask,
    UsageSummary,
    ToolPolicySnapshot,
)
from backend.subagents.report import aggregate_multiagent_report, degraded_agent_report
from backend.subagents.store import MultiAgentStore
from backend.tools.workspace_fs import build_path_access_policy

if TYPE_CHECKING:
    from backend.subagents.runner import SubagentRunner


EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]

GLOBAL_DENIED_TOOLS = {"multiagent", "request_user_input"}
VALID_MODES = {"parallel", "sequential"}
VALID_RUN_MODES = {"sync"}
VALID_RETURN_STRATEGIES = {"wait_all"}
VALID_CONTEXT_POLICIES = {"fresh"}
VALID_FAILURE_POLICIES = {"ask_user", "continue", "abort"}
VALID_APPROVAL_MODES = {"inherit", "auto_allow", "manual"}
VALID_WORKING_SCOPES = {"shared_workspace"}
SEQUENTIAL_CONTEXT_MARKER = "Sequential context from previous subagents:"

TOOL_USAGE_HINTS: dict[str, list[str]] = {
    "write_file": [
        "required `path`, `content`; optional `overwrite`.",
        "`path` is a writable workspace file path; do not use `filename` or `file_path`.",
        "`content` is the entire file content string; do not use `body` or `text`.",
        'example `{"path": "relative/path.txt", "content": "file text", "overwrite": true}`.',
    ],
    "edit_file": [
        "required `path`, `edits`.",
        "`edits` is an array of exact replacements with `old_text`, `new_text`, optional `replace_all`.",
        'example `{"path": "relative/path.txt", "edits": [{"old_text": "before", "new_text": "after", "replace_all": false}]}`.',
    ],
    "read_file": [
        "required `path`.",
        "Use only for small complete file reads; use `read_file_range` for large text files.",
        'example `{"path": "relative/path.txt"}`.',
    ],
    "read_file_range": [
        "required `path`, `offset`, `limit`.",
        "`offset` is a 1-based line number; `limit` is the maximum lines to return.",
        'example `{"path": "relative/path.txt", "offset": 1, "limit": 80}`.',
    ],
    "search_files": [
        "required `query`; optional `path`, `glob`, `regex`, `case_sensitive`, `max_results`, `show_hidden`.",
        "Use `query` for the text or regex pattern; do not use `pattern` unless the schema says so.",
        'example `{"query": "needle", "path": ".", "glob": "*.py", "max_results": 20}`.',
    ],
    "grep": [
        "alias of `search_files`.",
        "required `query`; optional `path`, `glob`, `regex`, `case_sensitive`, `max_results`, `show_hidden`.",
        'example `{"query": "needle", "path": ".", "glob": "*.py", "max_results": 20}`.',
    ],
    "list_dir": [
        "optional `path`, `recursive`, `max_depth`, `limit`, `show_hidden`.",
        "`path` must be a readable directory, not a file.",
        'example `{"path": ".", "recursive": false, "limit": 120}`.',
    ],
    "list_files": [
        "alias of `list_dir`.",
        "optional `path`, `recursive`, `max_depth`, `limit`, `show_hidden`.",
        'example `{"path": ".", "recursive": false, "limit": 120}`.',
    ],
    "terminal": [
        "required `command`.",
        "Run one shell command string in the configured sandbox; prefer file tools for simple reads/writes.",
        'example `{"command": "pwd"}`.',
    ],
}


@dataclass(frozen=True)
class ValidatedAgentSpec:
    name: str
    description: str
    prompt: str
    agent_type: str | None
    allowed_tools: list[str]
    denied_tools: list[str]
    allowed_skills: list[str]
    denied_skills: list[str]
    approval_mode: str
    effective_approval_mode: str
    model: str | None
    max_turns: int
    working_scope: str
    tool_policy_snapshot: ToolPolicySnapshot


@dataclass(frozen=True)
class ValidatedMultiAgentRequest:
    run_id: str
    mode: str
    run_mode: str
    return_strategy: str
    context_policy: str
    on_subagent_failure: str
    agents: list[ValidatedAgentSpec]


class MultiAgentValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class CancelOutcome:
    accepted: bool
    message: str
    run: MultiAgentRun | None = None
    task: SubagentTask | None = None


@dataclass(frozen=True)
class FailureDecisionOutcome:
    accepted: bool
    message: str
    run: MultiAgentRun
    tasks: list[SubagentTask]


class MultiAgentManager:
    def __init__(
        self,
        settings: AppConfig,
        store: MultiAgentStore,
        *,
        tool_names_provider: Callable[[], set[str]] | None = None,
        skill_names_provider: Callable[[], set[str]] | None = None,
        runner: "SubagentRunner | None" = None,
        cancellation_registry: CancellationRegistry | None = None,
    ):
        self.settings = settings
        self.store = store
        self._tool_names_provider = tool_names_provider or (lambda: set())
        self._skill_names_provider = skill_names_provider or (lambda: set())
        self.runner = runner
        if cancellation_registry is not None:
            self.cancellation_registry = cancellation_registry
        elif runner is not None and hasattr(runner, "cancellation_registry"):
            self.cancellation_registry = runner.cancellation_registry
        else:
            self.cancellation_registry = CancellationRegistry()
        self._active_event_emitters: dict[str, EventEmitter] = {}
        self._active_run_workers: dict[str, asyncio.Task[MultiAgentReport]] = {}
        self._active_task_workers: dict[str, asyncio.Task[SubagentTask]] = {}
        self._active_run_task_ids: dict[str, set[str]] = {}

    async def run_sync(
        self,
        arguments: dict[str, Any],
        *,
        parent_session_id: str,
        parent_turn_id: str,
        turn_approval_mode: str = "manual",
        event_emitter: EventEmitter | None = None,
    ) -> MultiAgentReport:
        try:
            request = self.validate_request(arguments, turn_approval_mode=turn_approval_mode)
        except MultiAgentValidationError as exc:
            return self._validation_failed_report(exc.errors)

        effective_failure_policy = request.on_subagent_failure if event_emitter is not None else "continue"
        run = MultiAgentRun(
            run_id=request.run_id,
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
            mode=request.mode,  # type: ignore[arg-type]
            run_mode=request.run_mode,  # type: ignore[arg-type]
            return_strategy=request.return_strategy,  # type: ignore[arg-type]
            context_policy=request.context_policy,  # type: ignore[arg-type]
            on_subagent_failure=effective_failure_policy,  # type: ignore[arg-type]
            status="running",
        )
        tasks = [
            self._build_task(
                run,
                spec,
                index=index,
            )
            for index, spec in enumerate(request.agents, start=1)
        ]
        run.task_ids = [task.task_id for task in tasks]

        self.store.save_run(run, tasks)
        run_worker = asyncio.current_task()
        if run_worker is not None:
            self._active_run_workers[run.run_id] = run_worker
        try:
            if event_emitter is not None:
                self._active_event_emitters[run.run_id] = event_emitter
                await self._emit_event(event_emitter, "multiagent_run_started", run_event_payload(run))
                for task in tasks:
                    await self._emit_event(event_emitter, "multiagent_task_started", task_event_payload(task))
            if self.runner is None:
                for task in tasks:
                    task.status = "failed"
                    task.started_at = utc_now()
                    task.completed_at = utc_now()
                    task.error = "SubagentRunner is not connected yet."
                    task.result = degraded_agent_report(
                        task,
                        status="failed",
                        reason="runner_not_implemented",
                        summary=(
                            "multiagent request passed validation and was persisted, "
                            "but SubagentRunner execution is not implemented in this runtime."
                        ),
                        risks=["Subagent execution has not run yet."],
                        recommended_next_steps=["Wire SubagentRunner before expecting real subagent execution."],
                    )
                    self.store.save_task(task)
            else:
                tasks = await self._run_tasks(request.mode, tasks, run=run, event_emitter=event_emitter)
                record = self.store.get_record(run.run_id)
                run = record.run
                tasks = list(record.tasks.values())

            report = aggregate_multiagent_report(
                run,
                tasks,
                summary=None if self.runner is not None else "multiagent request validated; SubagentRunner is not connected yet.",
            )
            run.status = report.status
            run.usage_summary = report.usage_summary
            run.completed_at = utc_now()
            run.result = report
            self.store.save_run(run, tasks)
            if event_emitter is not None:
                await self._emit_event(event_emitter, "multiagent_run_completed", run_event_payload(run, include_result=True))
            self._clear_cancellation_requests(run.run_id, tasks)
            return report
        except asyncio.CancelledError:
            self._cancel_registered_run_workers(run.run_id)
            request = self.cancellation_registry.request_run_cancel(run.run_id, reason="parent_interrupted")
            run.cancel_requested_at = run.cancel_requested_at or request.requested_at
            run.cancel_reason = run.cancel_reason or request.reason
            tasks = self._mark_cancelled_tasks(run, tasks, request)
            report = aggregate_multiagent_report(run, tasks)
            run.status = report.status
            run.completed_at = utc_now()
            run.result = report
            run.usage_summary = report.usage_summary
            self.store.save_run(run, tasks)
            self._dispatch_active_event(run.run_id, "multiagent_run_updated", run_event_payload(run, include_result=True))
            for task in tasks:
                self._dispatch_active_event(
                    run.run_id,
                    "multiagent_task_updated",
                    task_event_payload(task, include_result=task.result is not None),
                )
            self._clear_cancellation_requests(run.run_id, tasks)
            raise
        finally:
            self._active_event_emitters.pop(run.run_id, None)
            self._active_run_workers.pop(run.run_id, None)
            self._active_run_task_ids.pop(run.run_id, None)

    def cancel_task(self, task_id: str, *, reason: str = "user_requested") -> CancelOutcome:
        task = self.store.get_task(task_id)
        run = self.store.get_run(task.run_id)
        if task.is_terminal():
            return CancelOutcome(
                accepted=False,
                message="already_completed",
                run=run,
                task=task,
            )

        request = self.cancellation_registry.request_task_cancel(task.task_id, reason=reason)
        updated_task = self._apply_cancel_request(task, request)
        self._cancel_registered_task_worker(task.task_id)
        if not updated_task.is_terminal() and not self._has_active_task_worker(updated_task.task_id):
            updated_task = self._force_cancel_task(updated_task, request)
        self.store.save_task(updated_task)
        self._dispatch_active_event(
            task.run_id,
            "multiagent_task_updated",
            task_event_payload(updated_task, include_result=updated_task.result is not None),
        )
        finalized_run = self._finalize_run_if_terminal(task.run_id)
        return CancelOutcome(
            accepted=True,
            message="cancellation_requested",
            run=finalized_run or run,
            task=updated_task,
        )

    def list_runs(
        self,
        *,
        parent_session_id: str | None = None,
        parent_turn_id: str | None = None,
    ):
        return self.store.list_records(
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
        )

    def get_run_record(self, run_id: str):
        return self.store.get_record(run_id)

    def get_task_record(self, task_id: str):
        return self.store.get_task_record(task_id)

    def cancel_run(self, run_id: str, *, reason: str = "user_requested") -> CancelOutcome:
        record = self.store.get_record(run_id)
        run = record.run
        tasks = list(record.tasks.values())
        if run.status in {"completed", "failed", "partial", "cancelled", "timed_out"} and all(task.is_terminal() for task in tasks):
            return CancelOutcome(
                accepted=False,
                message="already_completed",
                run=run,
            )

        request = self.cancellation_registry.request_run_cancel(run_id, reason=reason)
        run.cancel_requested_at = run.cancel_requested_at or request.requested_at
        run.cancel_reason = run.cancel_reason or request.reason
        changed_tasks: list[SubagentTask] = []
        for task in tasks:
            if task.is_terminal():
                continue
            self._apply_cancel_request(task, request)
            changed_tasks.append(task)
        self._cancel_registered_run_workers(run_id)
        for task in changed_tasks:
            if not task.is_terminal() and not self._has_active_task_worker(task.task_id):
                self._force_cancel_task(task, request)
        self.store.save_run(run, tasks)
        self._dispatch_active_event(run_id, "multiagent_run_updated", run_event_payload(run))
        for task in changed_tasks:
            self._dispatch_active_event(
                run_id,
                "multiagent_task_updated",
                task_event_payload(task, include_result=task.result is not None),
            )
        finalized_run = self._finalize_run_if_terminal(run_id)
        return CancelOutcome(
            accepted=True,
            message="cancellation_requested",
            run=finalized_run or run,
        )

    def cancel_parent_turn(
        self,
        *,
        parent_session_id: str,
        parent_turn_id: str,
        reason: str = "parent_interrupted",
    ) -> list[CancelOutcome]:
        outcomes: list[CancelOutcome] = []
        records = self.store.list_records(
            parent_session_id=parent_session_id,
            parent_turn_id=parent_turn_id,
        )
        for record in records:
            try:
                outcomes.append(self.cancel_run(record.run.run_id, reason=reason))
            except FileNotFoundError:
                continue
        return outcomes

    def resolve_failure_decision(
        self,
        run_id: str,
        *,
        decision: str,
        task_id: str | None = None,
    ) -> FailureDecisionOutcome:
        if decision not in {"retry_failed", "continue", "abort"}:
            raise ValueError("decision must be retry_failed, continue, or abort")
        record = self.store.get_record(run_id)
        run = record.run
        tasks = list(record.tasks.values())
        pending_failure_task_ids = list(run.pending_failure_task_ids)
        if task_id and task_id not in pending_failure_task_ids:
            pending_failure_task_ids.append(task_id)
        if run.status != "waiting_user_decision":
            return FailureDecisionOutcome(False, "run_not_waiting_user_decision", run, tasks)
        if not pending_failure_task_ids:
            return FailureDecisionOutcome(False, "no_pending_failure", run, tasks)

        resolved_at = utc_now()
        run.failure_decision = decision  # type: ignore[assignment]
        run.failure_decision_resolved_at = resolved_at
        run.pending_failure_task_ids = []

        if decision == "abort":
            run.status = "cancelled"
            run.cancel_requested_at = run.cancel_requested_at or resolved_at
            run.cancel_reason = run.cancel_reason or "subagent_failure_aborted_by_user"
            request = self.cancellation_registry.request_run_cancel(run.run_id, reason=run.cancel_reason)
            changed_tasks: list[SubagentTask] = []
            for task in tasks:
                if task.is_terminal():
                    continue
                self._force_cancel_task(task, request)
                changed_tasks.append(task)
            report = aggregate_multiagent_report(run, tasks, summary="Multiagent run aborted after subagent failure.")
            run.status = report.status
            run.completed_at = utc_now()
            run.result = report
            run.usage_summary = report.usage_summary
            self.store.save_run(run, tasks)
            self._dispatch_active_event(
                run.run_id,
                "multiagent_failure_decision_resolved",
                failure_decision_resolved_payload(run, decision=decision, task_ids=pending_failure_task_ids),
            )
            self._dispatch_active_event(run.run_id, "multiagent_run_completed", run_event_payload(run, include_result=True))
            for task in changed_tasks:
                self._dispatch_active_event(
                    run.run_id,
                    "multiagent_task_updated",
                    task_event_payload(task, include_result=task.result is not None),
                )
            self._clear_cancellation_requests(run.run_id, tasks)
            return FailureDecisionOutcome(True, "aborted", run, tasks)

        if decision == "continue":
            run.status = "running"
            self.store.save_run(run, tasks)
            self._dispatch_active_event(
                run.run_id,
                "multiagent_failure_decision_resolved",
                failure_decision_resolved_payload(run, decision=decision, task_ids=pending_failure_task_ids),
            )
            return FailureDecisionOutcome(True, "continued", run, tasks)

        retry_tasks: list[SubagentTask] = []
        tasks_by_id = {task.task_id: task for task in tasks}
        for failed_task_id in pending_failure_task_ids:
            failed_task = tasks_by_id.get(failed_task_id)
            if failed_task is None:
                continue
            retry_task = failed_task.model_copy(deep=True)
            retry_task.task_id = uuid4().hex
            retry_task.child_session_id = uuid4().hex
            retry_task.status = "pending"
            retry_task.current_activity = f"Queued retry for {failed_task.name}"
            retry_task.pending_messages = []
            retry_task.file_changes = []
            retry_task.file_conflicts = []
            retry_task.held_locks = []
            retry_task.terminal_commands = []
            retry_task.terminal_pids = []
            retry_task.usage_summary = UsageSummary()
            retry_task.result = None
            retry_task.error = None
            retry_task.started_at = None
            retry_task.cancel_requested_at = None
            retry_task.cancel_reason = None
            retry_task.completed_at = None
            retry_task.progress.completed_turns = 0
            retry_task.progress.tool_call_count = 0
            retry_task.progress.last_event_at = None
            retry_task.progress.max_turns = failed_task.max_turns
            retry_task.assignment_prompt = "\n\n".join(
                [
                    failed_task.assignment_prompt.rstrip(),
                    f"Retry context: this is a retry of failed subagent task {failed_task.task_id}.",
                    f"Previous failure: {failed_task.error or (failed_task.result.summary if failed_task.result is not None else 'unknown failure')}",
                ]
            )
            retry_tasks.append(retry_task)
        if not retry_tasks:
            return FailureDecisionOutcome(False, "retry_task_not_found", run, tasks)
        run.task_ids.extend(task.task_id for task in retry_tasks)
        run.status = "running"
        tasks.extend(retry_tasks)
        self.store.save_run(run, tasks)
        self._dispatch_active_event(
            run.run_id,
            "multiagent_failure_decision_resolved",
            failure_decision_resolved_payload(run, decision=decision, task_ids=pending_failure_task_ids),
        )
        for task in retry_tasks:
            self._dispatch_active_event(run.run_id, "multiagent_task_started", task_event_payload(task))
        return FailureDecisionOutcome(True, "retry_queued", run, tasks)

    async def _run_tasks(
        self,
        mode: str,
        tasks: list[SubagentTask],
        *,
        run: MultiAgentRun,
        event_emitter: EventEmitter | None = None,
    ) -> list[SubagentTask]:
        if self.runner is None:
            return tasks
        if mode == "sequential":
            completed: list[SubagentTask] = []
            index = 0
            while index < len(tasks):
                if run.status == "waiting_user_decision":
                    decision = await self._wait_for_failure_decision(run.run_id)
                    if decision == "abort":
                        break
                    record = self.store.get_record(run.run_id)
                    run = record.run
                    tasks = list(record.tasks.values())
                    if decision == "retry_failed":
                        completed = [item for item in tasks[:index] if item.is_terminal()]
                task = tasks[index]
                index += 1
                if task.is_terminal():
                    completed.append(task)
                    if event_emitter is not None:
                        await self._emit_event(event_emitter, "multiagent_task_updated", task_event_payload(task, include_result=task.result is not None))
                    continue
                if completed:
                    self._inject_sequential_context(task, completed)
                    self.store.save_task(task)
                completed_task = await self._run_registered_task(
                    task,
                    event_emitter=event_emitter,
                )
                completed.append(completed_task)
                if event_emitter is not None:
                    await self._emit_event(event_emitter, "multiagent_task_updated", task_event_payload(completed_task, include_result=True))
                if self._should_pause_after_failure(run, completed_task):
                    await self._request_failure_decision(run, completed_task, tasks, event_emitter=event_emitter)
                    decision = await self._wait_for_failure_decision(run.run_id)
                    if decision == "abort":
                        break
                    record = self.store.get_record(run.run_id)
                    run = record.run
                    tasks = list(record.tasks.values())
                elif self._should_abort_after_failure(run, completed_task):
                    self._abort_pending_tasks_after_failure(run, tasks, failed_task=completed_task)
                    break
            return completed
        concurrency = max(int(self.settings.subagents.max_parallel_agents), 1)
        semaphore = asyncio.Semaphore(concurrency)

        async def run_task(task: SubagentTask) -> SubagentTask:
            async with semaphore:
                if run.status == "waiting_user_decision":
                    decision = await self._wait_for_failure_decision(run.run_id)
                    if decision == "abort":
                        return self.store.get_task(task.task_id)
                if task.is_terminal():
                    completed_task = task
                else:
                    completed_task = await self._run_registered_task(
                        task,
                        event_emitter=event_emitter,
                    )
                if event_emitter is not None:
                    await self._emit_event(event_emitter, "multiagent_task_updated", task_event_payload(completed_task, include_result=True))
                if self._should_pause_after_failure(run, completed_task):
                    await self._request_failure_decision(run, completed_task, tasks, event_emitter=event_emitter)
                    decision = await self._wait_for_failure_decision(run.run_id)
                    if decision == "abort" and not completed_task.is_terminal():
                        return self.store.get_task(task.task_id)
                elif self._should_abort_after_failure(run, completed_task):
                    self._abort_pending_tasks_after_failure(run, tasks, failed_task=completed_task)
                return completed_task

        completed_tasks = list(await asyncio.gather(*(run_task(task) for task in tasks)))
        record = self.store.get_record(run.run_id)
        return list(record.tasks.values()) if record.tasks else completed_tasks

    async def _run_registered_task(
        self,
        task: SubagentTask,
        *,
        event_emitter: EventEmitter | None,
    ) -> SubagentTask:
        if self.runner is None:
            return task
        worker = asyncio.create_task(
            self.runner.run(task, event_emitter=event_emitter),
            name=f"multiagent-task:{task.task_id}",
        )
        self._active_task_workers[task.task_id] = worker
        self._active_run_task_ids.setdefault(task.run_id, set()).add(task.task_id)
        try:
            return await worker
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return self.store.get_task(task.task_id)
        finally:
            registered = self._active_task_workers.get(task.task_id)
            if registered is worker:
                self._active_task_workers.pop(task.task_id, None)
            task_ids = self._active_run_task_ids.get(task.run_id)
            if task_ids is not None:
                task_ids.discard(task.task_id)
                if not task_ids:
                    self._active_run_task_ids.pop(task.run_id, None)

    def validate_request(self, arguments: dict[str, Any], *, turn_approval_mode: str = "manual") -> ValidatedMultiAgentRequest:
        errors: list[str] = []
        if not self.settings.subagents.enabled:
            errors.append("subagents are disabled by configuration")

        mode = _string_value(arguments.get("mode"), default="parallel")
        run_mode = _string_value(arguments.get("run_mode"), default="sync")
        return_strategy = _string_value(arguments.get("return_strategy"), default="wait_all")
        context_policy = _string_value(arguments.get("context_policy"), default="fresh")
        on_subagent_failure = _string_value(arguments.get("on_subagent_failure"), default="ask_user")
        if mode not in VALID_MODES:
            errors.append(f"mode must be one of {sorted(VALID_MODES)}")
        if run_mode not in VALID_RUN_MODES:
            errors.append("run_mode only supports sync in P0")
        if return_strategy not in VALID_RETURN_STRATEGIES:
            errors.append("return_strategy only supports wait_all in P0")
        if context_policy not in VALID_CONTEXT_POLICIES:
            errors.append("context_policy only supports fresh in P0")
        if on_subagent_failure not in VALID_FAILURE_POLICIES:
            errors.append(f"on_subagent_failure must be one of {sorted(VALID_FAILURE_POLICIES)}")

        unsupported_fields = [field for field in ("run_timeout_seconds", "token_budget") if field in arguments]
        if unsupported_fields:
            errors.append(f"unsupported multiagent fields: {', '.join(unsupported_fields)}")

        raw_agents = arguments.get("agents")
        agents_payload = raw_agents if isinstance(raw_agents, list) else []
        if not isinstance(raw_agents, list):
            errors.append("agents must be an array")
        if len(agents_payload) < 1:
            errors.append("agents must contain at least one agent")
        if len(agents_payload) > self.settings.subagents.max_agents_per_run:
            errors.append(f"agents exceeds max_agents_per_run={self.settings.subagents.max_agents_per_run}")

        names: set[str] = set()
        agents: list[ValidatedAgentSpec] = []
        known_tools = set(self._safe_tool_names())
        known_skills = set(self._safe_skill_names())
        for index, raw_agent in enumerate(agents_payload, start=1):
            if not isinstance(raw_agent, dict):
                errors.append(f"agents[{index}] must be an object")
                continue
            agent = self._validate_agent(
                raw_agent,
                index=index,
                names=names,
                known_tools=known_tools,
                known_skills=known_skills,
                turn_approval_mode=turn_approval_mode,
                errors=errors,
            )
            if agent is not None:
                agents.append(agent)

        if errors:
            raise MultiAgentValidationError(errors)

        return ValidatedMultiAgentRequest(
            run_id=uuid4().hex,
            mode=mode,
            run_mode=run_mode,
            return_strategy=return_strategy,
            context_policy=context_policy,
            on_subagent_failure=on_subagent_failure,
            agents=agents,
        )

    def _validate_agent(
        self,
        raw_agent: dict[str, Any],
        *,
        index: int,
        names: set[str],
        known_tools: set[str],
        known_skills: set[str],
        turn_approval_mode: str,
        errors: list[str],
    ) -> ValidatedAgentSpec | None:
        prefix = f"agents[{index}]"
        name = _string_value(raw_agent.get("name"))
        if not name:
            errors.append(f"{prefix}.name is required")
        elif name in names:
            errors.append(f"{prefix}.name must be unique within the run: {name}")
        else:
            names.add(name)

        prompt = _string_value(raw_agent.get("prompt"))
        if not prompt:
            errors.append(f"{prefix}.prompt is required")

        raw_allowed_tools = raw_agent.get("allowed_tools")
        allowed_tool_names = _string_list(raw_allowed_tools)
        if raw_allowed_tools is None or not allowed_tool_names:
            errors.append(f"{prefix}.allowed_tools must contain at least one tool")
        unknown_tools = sorted(tool for tool in allowed_tool_names if tool not in known_tools)
        if unknown_tools:
            errors.append(f"{prefix}.allowed_tools contains unknown tools: {', '.join(unknown_tools)}")

        effective_allowed_tools = sorted(
            {
                tool
                for tool in allowed_tool_names
                if tool in known_tools and tool not in GLOBAL_DENIED_TOOLS
            }
        )
        if allowed_tool_names and not effective_allowed_tools:
            errors.append(f"{prefix}.allowed_tools has no executable tools after global denylist")

        approval_mode = _string_value(raw_agent.get("approval_mode"), default="auto_allow")
        if approval_mode not in VALID_APPROVAL_MODES:
            errors.append(f"{prefix}.approval_mode must be inherit, auto_allow, or manual")
        effective_approval_mode = turn_approval_mode if approval_mode == "inherit" else approval_mode

        if "task_timeout_seconds" in raw_agent:
            errors.append(f"{prefix}.task_timeout_seconds is not supported")

        max_turns = _positive_int(
            raw_agent.get("max_turns"),
            default=self.settings.subagents.default_max_turns,
            field=f"{prefix}.max_turns",
            errors=errors,
        )
        if max_turns < 2:
            errors.append(f"{prefix}.max_turns must be at least 2")
        elif max_turns > self.settings.subagents.default_max_turns:
            errors.append(f"{prefix}.max_turns must be at most {self.settings.subagents.default_max_turns}")
        working_scope = _string_value(raw_agent.get("working_scope"), default="shared_workspace")
        if working_scope not in VALID_WORKING_SCOPES:
            errors.append(f"{prefix}.working_scope only supports shared_workspace in P0")

        allowed_skills = _string_list(raw_agent.get("allowed_skills"))
        unknown_skills = sorted(skill for skill in allowed_skills if skill not in known_skills)
        if unknown_skills:
            errors.append(f"{prefix}.allowed_skills contains unknown skills: {', '.join(unknown_skills)}")
        effective_allowed_skills = sorted(skill for skill in allowed_skills if skill in known_skills)

        denied_tools = sorted((known_tools - set(effective_allowed_tools)) | GLOBAL_DENIED_TOOLS)
        denied_skills = sorted(known_skills - set(effective_allowed_skills))
        snapshot = self._build_tool_policy_snapshot(
            allowed_tools=effective_allowed_tools,
            denied_tools=denied_tools,
            allowed_skills=effective_allowed_skills,
            denied_skills=denied_skills,
            approval_mode=effective_approval_mode,
        )

        if errors and (not name or not prompt):
            return None
        return ValidatedAgentSpec(
            name=name,
            description=_string_value(raw_agent.get("description")),
            prompt=prompt,
            agent_type=_optional_string(raw_agent.get("agent_type")),
            allowed_tools=effective_allowed_tools,
            denied_tools=denied_tools,
            allowed_skills=effective_allowed_skills,
            denied_skills=denied_skills,
            approval_mode=approval_mode,
            effective_approval_mode=effective_approval_mode,
            model=_optional_string(raw_agent.get("model")),
            max_turns=max_turns,
            working_scope=working_scope,
            tool_policy_snapshot=snapshot,
        )

    def _build_task(self, run: MultiAgentRun, spec: ValidatedAgentSpec, *, index: int) -> SubagentTask:
        task_id = uuid4().hex
        return SubagentTask(
            task_id=task_id,
            run_id=run.run_id,
            parent_session_id=run.parent_session_id,
            parent_turn_id=run.parent_turn_id,
            child_session_id=uuid4().hex,
            name=spec.name,
            agent_type=spec.agent_type,
            description=spec.description,
            assignment_prompt=self._build_assignment_prompt(spec),
            allowed_tools=spec.allowed_tools,
            denied_tools=spec.denied_tools,
            allowed_skills=spec.allowed_skills,
            denied_skills=spec.denied_skills,
            tool_policy_snapshot=spec.tool_policy_snapshot,
            approval_mode=spec.approval_mode,  # type: ignore[arg-type]
            model=spec.model,
            max_turns=spec.max_turns,
            working_scope=spec.working_scope,  # type: ignore[arg-type]
            current_activity=f"Queued as subagent #{index}",
        )

    def _build_assignment_prompt(self, spec: ValidatedAgentSpec) -> str:
        lines = [
            f"You are handling one delegated Newman subtask: {spec.name}.",
            "Complete this task directly from local context using the exposed tools.",
        ]
        if spec.description:
            lines.extend(
                [
                    "",
                    "Task description:",
                    spec.description.strip(),
                ]
            )
        lines.extend(
            [
                "",
                "Primary objective:",
                spec.prompt.rstrip(),
                "",
                "Execution boundaries:",
                "- Stay within this task's scope.",
                "- Use only the exposed tools.",
                "- Make the best reasonable judgment from local context; do not ask the user questions.",
                "- The parent agent will do the final synthesis across subagents.",
                self._allowed_tool_usage_prompt(spec),
                "",
                "Final report format:",
                "Scope: one sentence describing the exact scope you handled.",
                "Result: the answer or key findings for this scope.",
                "Key files: relevant file paths, or None.",
                "Files changed: files you believe you changed, or None.",
                "Issues: risks, blockers, or review findings, or None.",
                "Risks: residual risks or uncertainty, or None.",
                "Next steps: concrete follow-up actions, or None.",
                "",
                "Do not return JSON. Do not wrap the final report in a code block.",
            ]
        )
        return "\n".join(lines)

    def _allowed_tool_usage_prompt(self, spec: ValidatedAgentSpec) -> str:
        allowed_tools = list(dict.fromkeys(spec.allowed_tools))
        if not allowed_tools:
            return ""

        policy = build_path_access_policy(self.settings)
        lines = [
            "",
            "Allowed tool usage:",
            f"- Exposed tools for this subtask: {', '.join(allowed_tools)}.",
            "- Use exactly the parameter names shown by the tool schema and examples; do not invent aliases.",
            "- For file tools, `path` may be workspace-relative or absolute inside the allowed roots.",
        ]
        if policy.readable_roots:
            lines.append("- Readable roots: " + ", ".join(str(path) for path in policy.readable_roots))
        if policy.writable_roots:
            lines.append("- Writable roots: " + ", ".join(str(path) for path in policy.writable_roots))

        for tool_name in allowed_tools:
            hints = TOOL_USAGE_HINTS.get(tool_name)
            if not hints:
                lines.append(f"- {tool_name}: use the provider schema exactly; do not add unsupported parameters.")
                continue
            joined = " ".join(hints)
            lines.append(f"- {tool_name}: {joined}")
        return "\n".join(lines)

    def _build_tool_policy_snapshot(
        self,
        *,
        allowed_tools: list[str],
        denied_tools: list[str],
        allowed_skills: list[str],
        denied_skills: list[str],
        approval_mode: str,
    ) -> ToolPolicySnapshot:
        policy = build_path_access_policy(self.settings)
        return ToolPolicySnapshot(
            allowed_tools=allowed_tools,
            denied_tools=denied_tools,
            allowed_skills=allowed_skills,
            denied_skills=denied_skills,
            readable_roots=[str(path) for path in policy.readable_roots],
            writable_roots=[str(path) for path in policy.writable_roots],
            protected_roots=[str(path) for path in policy.protected_roots],
            sandbox_mode=self.settings.sandbox.mode,
            approval_mode=approval_mode,
            permission_context={"deny_rules": denied_tools},
        )

    def _validation_failed_report(self, errors: list[str]) -> MultiAgentReport:
        run_id = uuid4().hex
        return MultiAgentReport(
            run_id=run_id,
            status="failed",
            summary="multiagent request validation failed: " + "; ".join(errors),
            agent_reports=[],
            failed_agents=[],
            recommended_next_steps=["Fix the multiagent arguments and retry."],
        )

    def _safe_tool_names(self) -> set[str]:
        try:
            return set(self._tool_names_provider())
        except Exception:
            return set()

    def _safe_skill_names(self) -> set[str]:
        try:
            return set(self._skill_names_provider())
        except Exception:
            return set()

    def _apply_cancel_request(self, task: SubagentTask, request: CancellationRequest) -> SubagentTask:
        task.cancel_requested_at = task.cancel_requested_at or request.requested_at
        task.cancel_reason = task.cancel_reason or request.reason
        if task.status == "pending":
            task.status = "cancelled"
            task.current_activity = "Cancelled before execution"
            task.error = "Subagent task was cancelled before execution started."
            task.completed_at = utc_now()
            task.result = degraded_agent_report(
                task,
                status="cancelled",
                reason="cancelled",
                summary="Subagent task was cancelled before execution started.",
            )
        else:
            task.current_activity = "Cancellation requested"
        return task

    def _force_cancel_task(self, task: SubagentTask, request: CancellationRequest) -> SubagentTask:
        self._apply_cancel_request(task, request)
        if task.status != "cancelled":
            task.status = "cancelled"
            task.current_activity = "Cancelled"
            task.error = task.error or "Subagent task was cancelled before completion."
            task.completed_at = task.completed_at or utc_now()
            task.result = task.result or degraded_agent_report(
                task,
                status="cancelled",
                reason="cancelled",
                summary=task.error,
            )
        return task

    def _finalize_run_if_terminal(self, run_id: str) -> MultiAgentRun | None:
        record = self.store.get_record(run_id)
        tasks = list(record.tasks.values())
        if not tasks or not all(task.is_terminal() for task in tasks):
            return None
        run = record.run
        if run.status == "waiting_user_decision":
            return None
        report = aggregate_multiagent_report(run, tasks)
        run.status = report.status
        run.completed_at = run.completed_at or utc_now()
        run.result = report
        run.usage_summary = report.usage_summary
        self.store.save_run(run, tasks)
        self._clear_cancellation_requests(run_id, tasks)
        return run

    def _should_pause_after_failure(self, run: MultiAgentRun, task: SubagentTask) -> bool:
        return run.on_subagent_failure == "ask_user" and task.status in {"failed", "timed_out", "report_invalid"}

    def _should_abort_after_failure(self, run: MultiAgentRun, task: SubagentTask) -> bool:
        return run.on_subagent_failure == "abort" and task.status in {"failed", "timed_out", "report_invalid"}

    def _abort_pending_tasks_after_failure(
        self,
        run: MultiAgentRun,
        tasks: list[SubagentTask],
        *,
        failed_task: SubagentTask,
    ) -> None:
        run.status = "cancelled"
        run.cancel_requested_at = run.cancel_requested_at or utc_now()
        run.cancel_reason = run.cancel_reason or f"subagent_failed:{failed_task.task_id}"
        request = self.cancellation_registry.request_run_cancel(run.run_id, reason=run.cancel_reason)
        changed_tasks: list[SubagentTask] = []
        for task in tasks:
            if task.task_id == failed_task.task_id or task.is_terminal():
                continue
            self._force_cancel_task(task, request)
            changed_tasks.append(task)
        self.store.save_run(run, tasks)
        self._dispatch_active_event(run.run_id, "multiagent_run_updated", run_event_payload(run))
        for task in changed_tasks:
            self._dispatch_active_event(
                run.run_id,
                "multiagent_task_updated",
                task_event_payload(task, include_result=task.result is not None),
            )

    async def _request_failure_decision(
        self,
        run: MultiAgentRun,
        failed_task: SubagentTask,
        tasks: list[SubagentTask],
        *,
        event_emitter: EventEmitter | None,
    ) -> None:
        current = self.store.get_run(run.run_id)
        if current.status == "waiting_user_decision":
            pending = list(dict.fromkeys([*current.pending_failure_task_ids, failed_task.task_id]))
        else:
            pending = [failed_task.task_id]
        current.status = "waiting_user_decision"
        current.pending_failure_task_ids = pending
        current.failure_decision_requested_at = current.failure_decision_requested_at or utc_now()
        current.failure_decision = None
        current.failure_decision_resolved_at = None
        run.status = current.status
        run.pending_failure_task_ids = list(current.pending_failure_task_ids)
        run.failure_decision_requested_at = current.failure_decision_requested_at
        run.failure_decision = None
        run.failure_decision_resolved_at = None
        self.store.save_run(current, tasks)
        payload = failure_decision_required_payload(current, failed_task, tasks)
        if event_emitter is not None:
            await self._emit_event(event_emitter, "multiagent_failure_decision_required", payload)
            await self._emit_event(event_emitter, "multiagent_run_updated", run_event_payload(current))

    async def _wait_for_failure_decision(self, run_id: str) -> str:
        while True:
            await asyncio.sleep(0.2)
            record = self.store.get_record(run_id)
            run = record.run
            if run.status != "waiting_user_decision":
                return run.failure_decision or "continue"
            if run.cancel_requested_at:
                return "abort"

    def _cancel_registered_task_worker(self, task_id: str) -> None:
        worker = self._active_task_workers.get(task_id)
        if worker is not None and not worker.done():
            worker.cancel()

    def _has_active_task_worker(self, task_id: str) -> bool:
        worker = self._active_task_workers.get(task_id)
        return worker is not None and not worker.done()

    def _cancel_registered_run_workers(self, run_id: str) -> None:
        for task_id in tuple(self._active_run_task_ids.get(run_id, set())):
            self._cancel_registered_task_worker(task_id)

    def _clear_cancellation_requests(self, run_id: str, tasks: list[SubagentTask]) -> None:
        self.cancellation_registry.clear_run(run_id)
        for task in tasks:
            self.cancellation_registry.clear_task(task.task_id)

    async def _emit_event(self, emitter: EventEmitter, event: str, payload: dict[str, Any]) -> None:
        try:
            await emitter(event, payload)
        except Exception:
            return None

    def _dispatch_active_event(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        emitter = self._active_event_emitters.get(run_id)
        if emitter is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._emit_event(emitter, event, payload))

    def _inject_sequential_context(self, task: SubagentTask, previous_tasks: list[SubagentTask]) -> None:
        context = self._sequential_context(previous_tasks)
        if not context:
            return
        base_prompt = task.assignment_prompt.rstrip()
        if SEQUENTIAL_CONTEXT_MARKER in base_prompt:
            return
        task.assignment_prompt = "\n\n".join([base_prompt, SEQUENTIAL_CONTEXT_MARKER, context])

    def _mark_cancelled_tasks(
        self,
        run: MultiAgentRun,
        tasks: list[SubagentTask],
        request: CancellationRequest,
    ) -> list[SubagentTask]:
        updated: list[SubagentTask] = []
        for task in tasks:
            if task.is_terminal():
                updated.append(task)
                continue
            self._force_cancel_task(task, request)
            self.store.save_task(task)
            updated.append(task)
        self.store.save_run(run, updated)
        return updated

    def _sequential_context(self, previous_tasks: list[SubagentTask]) -> str:
        lines: list[str] = []
        for previous in previous_tasks:
            report = previous.result or degraded_agent_report(previous, reason="missing_report")
            lines.append(f"- {report.name} [{report.status}]: {_single_line(report.summary)}")
            for finding in report.findings[:3]:
                detail = _single_line(finding.detail)
                finding_text = _single_line(finding.title)
                if detail:
                    finding_text = f"{finding_text} - {detail}"
                lines.append(f"  finding({finding.severity}): {finding_text}")
        return _truncate_context("\n".join(lines), self.settings.subagents.sequential_context_token_limit)


def _string_value(value: object, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    return value.strip() or default


def _optional_string(value: object) -> str | None:
    text = _string_value(value)
    return text or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _positive_int(value: object, *, default: int, field: str, errors: list[str]) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        errors.append(f"{field} must be a positive integer")
        return default
    if number <= 0:
        errors.append(f"{field} must be a positive integer")
        return default
    return number


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _truncate_context(value: str, token_limit: int) -> str:
    max_chars = max(int(token_limit), 1) * 4
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."
