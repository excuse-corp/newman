from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.scheduler.cron_parser import next_run
from backend.scheduler.models import ScheduledTask, TaskAction
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


_ACTIONS = ["list", "add", "update", "remove", "run", "status"]


class SchedulerTool(BaseTool):
    def __init__(self, context: BuiltinToolContext):
        self._context = context
        self.meta = ToolMeta(
            name="schedule",
            description=(
                "Manage scheduled tasks (cron jobs). Supports: list, add, update, remove, run, status.\n\n"
                "- list: List all scheduled tasks\n"
                "- add: Create a new scheduled task (requires name, cron, prompt)\n"
                "- update: Update an existing task (requires task_id, plus fields to change)\n"
                "- remove: Delete a task (requires task_id)\n"
                "- run: Trigger a task immediately (requires task_id)\n"
                "- status: Show scheduler overview (task counts, recent runs)\n\n"
                "Cron expression format: 5 fields — minute hour day-of-month month day-of-week\n"
                "Examples: '0 9 * * *' = daily at 9am, '*/30 * * * *' = every 30 min, '0 0 * * 1' = weekly on Monday"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": _ACTIONS,
                        "description": "The operation to perform.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID (required for update/remove/run).",
                    },
                    "name": {
                        "type": "string",
                        "description": "Task name (required for add).",
                    },
                    "cron": {
                        "type": "string",
                        "description": "Cron expression, 5-field format (required for add, optional for update).",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The prompt to execute on schedule (required for add).",
                    },
                    "timezone": {
                        "type": "string",
                        "description": "Timezone for the cron expression, default UTC. E.g. 'Asia/Shanghai'.",
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "Whether the task is enabled (default true for add).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Human-readable task description.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Bind task to an existing session (for session_message type).",
                    },
                    "max_retries": {
                        "type": "integer",
                        "description": "Max retry count on failure, 0-5 (default 5).",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=30,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        action = arguments.get("action")
        if action not in _ACTIONS:
            return _err("validation_error", f"未知 action: {action}")

        if action == "run":
            return await self._action_run(arguments)
        handler = {
            "list": self._action_list,
            "add": self._action_add,
            "update": self._action_update,
            "remove": self._action_remove,
            "status": self._action_status,
        }[action]
        return handler(arguments)

    # ── list ──────────────────────────────────────────────

    def _action_list(self, args: dict[str, Any]) -> ToolExecutionResult:
        store = self._context.scheduler_store
        if store is None:
            return _err("internal_error", "调度器未初始化")
        tasks = store.list_tasks()
        lines = [_format_task_line(t) for t in tasks]
        summary = f"共 {len(tasks)} 个定时任务"
        stdout = summary + "\n" + "\n".join(lines) if lines else summary
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="list",
            summary=summary,
            stdout=stdout,
            metadata={"tasks": [t.model_dump(mode="json") for t in tasks]},
        )

    # ── add ───────────────────────────────────────────────

    def _action_add(self, args: dict[str, Any]) -> ToolExecutionResult:
        store = self._context.scheduler_store
        if store is None:
            return _err("internal_error", "调度器未初始化")

        name = (args.get("name") or "").strip()
        cron = (args.get("cron") or "").strip()
        prompt = (args.get("prompt") or "").strip()
        if not name:
            return _err("validation_error", "缺少必填参数: name")
        if not cron:
            return _err("validation_error", "缺少必填参数: cron")
        if not prompt:
            return _err("validation_error", "缺少必填参数: prompt")

        timezone_name = (args.get("timezone") or "UTC").strip()
        try:
            next_run_at = next_run(cron, datetime.now(timezone.utc), timezone_name)
        except (ValueError, Exception) as exc:
            return _err("validation_error", f"Cron 表达式非法: {exc}")

        session_id = _optional_str(args.get("session_id"))
        action_type = "session_message" if session_id else "background_task"
        action = TaskAction(type=action_type, prompt=prompt, session_id=session_id)

        max_retries = args.get("max_retries")
        if max_retries is not None:
            max_retries = max(0, min(5, int(max_retries)))
        else:
            max_retries = 5

        task = ScheduledTask(
            task_id=uuid4().hex,
            name=name,
            cron=cron,
            action=action,
            timezone=timezone_name,
            description=_optional_str(args.get("description")),
            enabled=args.get("enabled", True),
            max_retries=max_retries,
            source="chat",
            next_run_at=next_run_at.isoformat(),
        )
        store.upsert(task)
        self._refresh_engine()

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="add",
            summary=f"已创建定时任务: {task.name} ({task.task_id})",
            stdout=_format_task_detail(task),
            metadata={"task": task.model_dump(mode="json")},
        )

    # ── update ────────────────────────────────────────────

    def _action_update(self, args: dict[str, Any]) -> ToolExecutionResult:
        store = self._context.scheduler_store
        if store is None:
            return _err("internal_error", "调度器未初始化")

        task_id = _optional_str(args.get("task_id"))
        if not task_id:
            return _err("validation_error", "缺少必填参数: task_id")
        try:
            task = store.get(task_id)
        except FileNotFoundError:
            return _err("not_found", f"任务不存在: {task_id}")

        updates: dict[str, Any] = {}
        if "name" in args and args["name"] is not None:
            updates["name"] = str(args["name"]).strip()
        if "cron" in args and args["cron"] is not None:
            updates["cron"] = str(args["cron"]).strip()
        if "timezone" in args and args["timezone"] is not None:
            updates["timezone"] = str(args["timezone"]).strip()
        if "description" in args:
            updates["description"] = _optional_str(args.get("description"))
        if "enabled" in args and args["enabled"] is not None:
            updates["enabled"] = bool(args["enabled"])
        if "max_retries" in args and args["max_retries"] is not None:
            updates["max_retries"] = max(0, min(5, int(args["max_retries"])))
        if "prompt" in args and args["prompt"] is not None:
            action = task.action.model_copy(update={"prompt": str(args["prompt"]).strip()})
            updates["action"] = action

        merged = task.model_copy(update=updates)
        try:
            next_run_at = next_run(merged.cron, datetime.now(timezone.utc), merged.timezone)
            merged.next_run_at = next_run_at.isoformat()
        except (ValueError, Exception) as exc:
            return _err("validation_error", f"Cron 表达式非法: {exc}")

        store.upsert(merged)
        self._refresh_engine()

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="update",
            summary=f"已更新任务: {merged.name} ({merged.task_id})",
            stdout=_format_task_detail(merged),
            metadata={"task": merged.model_dump(mode="json")},
        )

    # ── remove ────────────────────────────────────────────

    def _action_remove(self, args: dict[str, Any]) -> ToolExecutionResult:
        store = self._context.scheduler_store
        if store is None:
            return _err("internal_error", "调度器未初始化")

        task_id = _optional_str(args.get("task_id"))
        if not task_id:
            return _err("validation_error", "缺少必填参数: task_id")
        try:
            task = store.get(task_id)
        except FileNotFoundError:
            return _err("not_found", f"任务不存在: {task_id}")

        store.delete(task_id)
        self._refresh_engine()

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="remove",
            summary=f"已删除任务: {task.name} ({task_id})",
            stdout=f"已删除定时任务: {task.name}\n任务 ID: {task_id}",
            metadata={"deleted_task_id": task_id, "deleted_task_name": task.name},
        )

    # ── run ───────────────────────────────────────────────

    async def _action_run(self, args: dict[str, Any]) -> ToolExecutionResult:
        task_id = _optional_str(args.get("task_id"))
        if not task_id:
            return _err("validation_error", "缺少必填参数: task_id")

        engine = self._context.scheduler_engine
        if engine is None:
            return _err("internal_error", "调度引擎未初始化，无法立即执行任务")

        try:
            task = await engine.run_now(task_id)
        except FileNotFoundError:
            return _err("not_found", f"任务不存在: {task_id}")
        except Exception as exc:
            return _err("execution_error", f"执行失败: {exc}")

        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="run",
            summary=f"已触发任务: {task.name}，状态: {task.status}",
            stdout=_format_task_detail(task),
            metadata={"task": task.model_dump(mode="json")},
        )

    # ── status ────────────────────────────────────────────

    def _action_status(self, args: dict[str, Any]) -> ToolExecutionResult:
        store = self._context.scheduler_store
        if store is None:
            return _err("internal_error", "调度器未初始化")

        tasks = store.list_tasks()
        total = len(tasks)
        enabled = sum(1 for t in tasks if t.enabled)
        disabled = total - enabled
        running = sum(1 for t in tasks if t.status == "running")
        failed = sum(1 for t in tasks if t.status == "failed")
        completed = sum(1 for t in tasks if t.status == "completed")

        engine = self._context.scheduler_engine
        engine_running = engine is not None and engine._running

        lines = [
            f"调度器状态: {'运行中' if engine_running else '未启动'}",
            f"任务总数: {total}（启用: {enabled}, 禁用: {disabled}）",
            f"运行中: {running} | 已完成: {completed} | 失败: {failed}",
        ]

        recent_runs: list[dict[str, Any]] = []
        if engine is not None:
            try:
                runs = engine.run_store.list_runs(limit=5)
                if runs:
                    lines.append("\n最近 5 次执行:")
                    for r in runs:
                        lines.append(f"  [{r.outcome}] {r.task_id} @ {r.finished_at}")
                        recent_runs.append(r.model_dump(mode="json"))
            except Exception:
                pass

        stdout = "\n".join(lines)
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="status",
            summary=f"调度器{'运行中' if engine_running else '未启动'}，共 {total} 个任务",
            stdout=stdout,
            metadata={
                "total": total,
                "enabled": enabled,
                "disabled": disabled,
                "running": running,
                "completed": completed,
                "failed": failed,
                "engine_running": engine_running,
                "recent_runs": recent_runs,
            },
        )

    # ── helpers ───────────────────────────────────────────

    def _refresh_engine(self) -> None:
        engine = self._context.scheduler_engine
        if engine is not None:
            engine.refresh_schedule()


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v or None


def _err(category: str, message: str) -> ToolExecutionResult:
    return ToolExecutionResult(
        success=False,
        tool="schedule",
        action="error",
        category=category,
        summary=message,
        stdout=message,
    )


def _format_task_line(task: ScheduledTask) -> str:
    status_icon = {
        "pending": "[待执行]",
        "running": "[运行中]",
        "completed": "[已完成]",
        "failed": "[失败]",
        "disabled": "[已禁用]",
    }.get(task.status, "[未知]")
    enabled_tag = "" if task.enabled else " (已禁用)"
    next_run = task.next_run_at or "无"
    return f"  {status_icon} {task.name}{enabled_tag} | cron: {task.cron} | 下次: {next_run} | ID: {task.task_id}"


def _format_task_detail(task: ScheduledTask) -> str:
    lines = [
        f"任务名称: {task.name}",
        f"任务 ID: {task.task_id}",
        f"Cron: {task.cron} [{task.timezone}]",
        f"状态: {task.status}",
        f"启用: {'是' if task.enabled else '否'}",
        f"提示词: {task.action.prompt}",
        f"类型: {task.action.type}",
    ]
    if task.description:
        lines.append(f"描述: {task.description}")
    if task.next_run_at:
        lines.append(f"下次执行: {task.next_run_at}")
    if task.last_run_at:
        lines.append(f"上次执行: {task.last_run_at}")
    if task.last_run_outcome:
        lines.append(f"上次结果: {task.last_run_outcome}")
    lines.append(f"执行次数: {task.run_count}")
    lines.append(f"失败次数: {task.failure_count}")
    return "\n".join(lines)


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [SchedulerTool(context)]
