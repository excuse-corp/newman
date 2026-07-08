from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.sessions.models import utc_now


RunMode = Literal["sync", "background"]
RunExecutionMode = Literal["parallel", "sequential"]
ReturnStrategy = Literal["wait_all"]
ContextPolicy = Literal["fresh", "fork"]
RunStatus = Literal[
    "pending",
    "running",
    "waiting_file_lock",
    "waiting_approval",
    "waiting_user_decision",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "timed_out",
]
FailureDecisionPolicy = Literal["ask_user", "continue", "abort"]
FailureDecisionAction = Literal["retry_failed", "continue", "abort"]
TaskStatus = Literal[
    "pending",
    "running",
    "waiting_file_lock",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "report_invalid",
]
AgentReportStatus = Literal["completed", "failed", "cancelled", "timed_out", "report_invalid"]
ApprovalMode = Literal["inherit", "auto_allow", "manual"]
WorkingScope = Literal["shared_workspace"]
FileWriteTool = Literal["write_file", "edit_file", "terminal"]
FileConflictReason = Literal["lock_timeout", "blocked", "concurrent_mutation"]


TERMINAL_TASK_STATUSES: set[str] = {
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "report_invalid",
}


class UsageSummary(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0
    cost_usd: float | None = None

    def add(self, other: "UsageSummary") -> "UsageSummary":
        return UsageSummary(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            request_count=self.request_count + other.request_count,
            cost_usd=_sum_optional_cost(self.cost_usd, other.cost_usd),
        )


class SubagentProgress(BaseModel):
    completed_turns: int = 0
    max_turns: int = 0
    tool_call_count: int = 0
    last_event_at: str | None = None


class SubagentMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    created_at: str = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileChange(BaseModel):
    path: str
    tool: FileWriteTool
    created: bool | None = None
    bytes: int | None = None
    summary: str | None = None
    at: str = Field(default_factory=utc_now)


class TerminalCommand(BaseModel):
    command: str
    pid: int | None = None
    exit_code: int | None = None
    success: bool | None = None
    stdout_preview: str | None = None
    stderr_preview: str | None = None
    started_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None


class Finding(BaseModel):
    title: str
    detail: str = ""
    severity: Literal["info", "low", "medium", "high", "critical"] = "info"
    file: str | None = None
    line: int | None = None


class Artifact(BaseModel):
    path: str | None = None
    url: str | None = None
    title: str | None = None
    kind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolPolicySnapshot(BaseModel):
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allowed_skills: list[str] = Field(default_factory=list)
    denied_skills: list[str] = Field(default_factory=list)
    readable_roots: list[str] = Field(default_factory=list)
    writable_roots: list[str] = Field(default_factory=list)
    protected_roots: list[str] = Field(default_factory=list)
    sandbox_mode: str = ""
    approval_mode: str = "manual"
    permission_context: dict[str, Any] = Field(default_factory=dict)


class AgentReport(BaseModel):
    task_id: str
    name: str
    status: AgentReportStatus
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    files_changed: list[FileChange] = Field(default_factory=list)
    commands_run: list[TerminalCommand] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    transcript_ref: str
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    degraded: bool = False
    degraded_reason: str | None = None

    @model_validator(mode="after")
    def ensure_degraded_reason(self) -> "AgentReport":
        if self.degraded and not self.degraded_reason:
            self.degraded_reason = "degraded"
        return self


class FileWriteRecord(BaseModel):
    task_id: str
    tool: FileWriteTool
    at: str = Field(default_factory=utc_now)


class FileOverlap(BaseModel):
    path: str
    writers: list[FileWriteRecord] = Field(default_factory=list)


class FileConflict(BaseModel):
    path: str
    blocked_task_id: str
    holding_task_id: str | None = None
    reason: FileConflictReason
    detected_at: str = Field(default_factory=utc_now)


class MultiAgentReport(BaseModel):
    run_id: str
    status: RunStatus
    summary: str
    agent_reports: list[AgentReport] = Field(default_factory=list)
    failed_agents: list[str] = Field(default_factory=list)
    file_overlaps: list[FileOverlap] = Field(default_factory=list)
    file_conflicts: list[FileConflict] = Field(default_factory=list)
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    recommended_next_steps: list[str] = Field(default_factory=list)


class MultiAgentRun(BaseModel):
    run_id: str
    parent_session_id: str
    parent_turn_id: str
    mode: RunExecutionMode
    run_mode: RunMode = "sync"
    return_strategy: ReturnStrategy = "wait_all"
    context_policy: ContextPolicy = "fresh"
    on_subagent_failure: FailureDecisionPolicy = "ask_user"
    status: RunStatus = "pending"
    task_ids: list[str] = Field(default_factory=list)
    pending_failure_task_ids: list[str] = Field(default_factory=list)
    failure_decision_requested_at: str | None = None
    failure_decision: FailureDecisionAction | None = None
    failure_decision_resolved_at: str | None = None
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    started_at: str = Field(default_factory=utc_now)
    cancel_requested_at: str | None = None
    cancel_reason: str | None = None
    completed_at: str | None = None
    result: MultiAgentReport | None = None
    error: str | None = None


class SubagentTask(BaseModel):
    task_id: str
    run_id: str
    parent_session_id: str
    parent_turn_id: str
    child_session_id: str
    name: str
    agent_type: str | None = None
    description: str = ""
    assignment_prompt: str
    status: TaskStatus = "pending"
    allowed_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    allowed_skills: list[str] = Field(default_factory=list)
    denied_skills: list[str] = Field(default_factory=list)
    tool_policy_snapshot: ToolPolicySnapshot = Field(default_factory=ToolPolicySnapshot)
    approval_mode: ApprovalMode = "inherit"
    model: str | None = None
    max_turns: int = 200
    working_scope: WorkingScope = "shared_workspace"
    current_activity: str | None = None
    progress: SubagentProgress = Field(default_factory=SubagentProgress)
    pending_messages: list[SubagentMessage] = Field(default_factory=list)
    file_changes: list[FileChange] = Field(default_factory=list)
    file_conflicts: list[FileConflict] = Field(default_factory=list)
    held_locks: list[str] = Field(default_factory=list)
    terminal_commands: list[TerminalCommand] = Field(default_factory=list)
    terminal_pids: list[int] = Field(default_factory=list)
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    result: AgentReport | None = None
    error: str | None = None
    started_at: str | None = None
    cancel_requested_at: str | None = None
    cancel_reason: str | None = None
    completed_at: str | None = None

    @property
    def transcript_ref(self) -> str:
        return f"session://{self.child_session_id}"

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_TASK_STATUSES


class MultiAgentRunRecord(BaseModel):
    run: MultiAgentRun
    tasks: dict[str, SubagentTask] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=utc_now)


def _sum_optional_cost(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return float(left or 0) + float(right or 0)
