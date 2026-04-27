from __future__ import annotations

from typing import Literal

from backend.sessions.models import ApprovedPlan, SessionCollaborationMode, SessionPlan, SessionPlanDraft, SessionRecord


CollaborationModeName = Literal["default", "plan"]

DEFAULT_COLLABORATION_MODE: CollaborationModeName = "default"
PLAN_COLLABORATION_MODE: CollaborationModeName = "plan"

PLAN_MODE_BLOCKED_TOOLS = frozenset({"enter_plan_mode", "update_plan_draft", "exit_plan_mode"})

DEFAULT_MODE_BLOCKED_TOOLS = frozenset({"update_plan_draft", "exit_plan_mode"})

COLLABORATION_MODE_DEFAULT_PROMPT = """## Collaboration Mode
当前处于 Default mode。

- 简单任务直接回答或直接实施。
- 普通的多步任务，可以直接使用 `update_plan` 维护实施中的 checklist，但不是每轮都必须使用。
- 只有在任务复杂、需要拆解成可持续跟踪的待办清单时，才调用 `enter_plan_mode`。
- 不要为了简单任务进入 Plan mode。
"""

COLLABORATION_MODE_PLAN_PROMPT = """## Collaboration Mode
当前处于 Plan mode。

- 这个模式用于把复杂任务拆成 checklist，并边执行边更新进度。
- 进入后先调用 `update_plan`，把当前目标拆成简洁、可执行的待办清单。
- 然后按清单逐步实施；任一时刻至多只有一个步骤是 `in_progress`。
- 允许使用正常的实施工具，但这些动作都应该服务当前步骤。
- 完成一步后，立刻调用 `update_plan` 将该项标记为 `completed`，并把下一项推进为 `in_progress`。
- 如果暂时无法继续，调用 `update_plan` 将当前步骤标记为 `blocked`，并在 `explanation` 中写清阻塞原因。
- 如果目标变化，可以重排或改写未完成步骤；除非用户明确取消，否则保留已完成项。
- 不要调用 `update_plan_draft` 或 `exit_plan_mode`；旧草案流不再是这个模式的主链路。
"""


def get_collaboration_mode(session: SessionRecord) -> SessionCollaborationMode:
    raw_mode = session.metadata.get("collaboration_mode")
    if isinstance(raw_mode, dict):
        try:
            return SessionCollaborationMode.model_validate(raw_mode)
        except Exception:
            pass
    return SessionCollaborationMode()


def get_plan_draft(session: SessionRecord) -> SessionPlanDraft | None:
    raw_draft = session.metadata.get("plan_draft")
    if not isinstance(raw_draft, dict):
        return None
    try:
        return SessionPlanDraft.model_validate(raw_draft)
    except Exception:
        return None


def get_approved_plan(session: SessionRecord) -> ApprovedPlan | None:
    raw_plan = session.metadata.get("approved_plan")
    if not isinstance(raw_plan, dict):
        return None
    try:
        return ApprovedPlan.model_validate(raw_plan)
    except Exception:
        return None


def get_session_plan(session: SessionRecord) -> SessionPlan | None:
    raw_plan = session.metadata.get("plan")
    if not isinstance(raw_plan, dict):
        return None
    try:
        return SessionPlan.model_validate(raw_plan)
    except Exception:
        return None


def build_collaboration_mode_payload(
    mode: CollaborationModeName,
    *,
    source: Literal["manual", "tool"],
) -> dict[str, object]:
    return SessionCollaborationMode(mode=mode, source=source).model_dump(mode="json")


def build_plan_draft_payload(markdown: str, *, status: Literal["draft", "awaiting_approval", "approved"] = "draft") -> dict[str, object]:
    return SessionPlanDraft(markdown=markdown, status=status).model_dump(mode="json")


def build_approved_plan_payload(markdown: str) -> dict[str, object]:
    return ApprovedPlan(markdown=markdown).model_dump(mode="json")


def is_tool_allowed_in_mode(tool_name: str, mode: CollaborationModeName) -> bool:
    if mode == PLAN_COLLABORATION_MODE:
        return tool_name not in PLAN_MODE_BLOCKED_TOOLS
    return tool_name not in DEFAULT_MODE_BLOCKED_TOOLS


def build_current_plan_section(plan: SessionPlan) -> str:
    lines = ["## Current Checklist"]
    if plan.explanation:
        lines.append(plan.explanation)
    for index, step in enumerate(plan.steps, start=1):
        lines.append(f"{index}. [{step.status}] {step.step}")
    if plan.current_step:
        lines.append(f"当前步骤：{plan.current_step}")
    return "\n".join(lines)


def build_collaboration_mode_prompt(session: SessionRecord) -> str:
    mode = get_collaboration_mode(session)
    sections = [COLLABORATION_MODE_DEFAULT_PROMPT if mode.mode == DEFAULT_COLLABORATION_MODE else COLLABORATION_MODE_PLAN_PROMPT]
    plan = get_session_plan(session)

    if mode.mode == PLAN_COLLABORATION_MODE:
        if plan is not None:
            sections.append(build_current_plan_section(plan))
        return "\n\n".join(sections)

    return "\n\n".join(sections)
