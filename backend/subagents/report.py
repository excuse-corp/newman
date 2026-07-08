from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from backend.subagents.models import (
    AgentReport,
    FileConflict,
    FileOverlap,
    FileWriteRecord,
    MultiAgentReport,
    MultiAgentRun,
    SubagentTask,
    UsageSummary,
)


JSON_CODE_BLOCK_RE = re.compile(r"```(?:json|agent_report)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)
SECTION_HEADER_RE = re.compile(
    r"^(scope|summary|result|key files|files changed|issues|risks|next steps)\s*:\s*(.*)$",
    re.IGNORECASE,
)
LIST_ITEM_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s*(.+)$")
MAX_DEGRADED_SUMMARY_CHARS = 2000


class AgentReportParseError(ValueError):
    pass


def parse_agent_report(text: str, task: SubagentTask) -> AgentReport:
    stripped = (text or "").strip()
    if not stripped:
        raise AgentReportParseError("empty report")

    errors: list[str] = []
    for candidate in _iter_json_candidates(stripped):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if not isinstance(payload, dict):
            errors.append("report payload is not an object")
            continue
        normalized = _normalize_report_payload(payload, task)
        try:
            return AgentReport.model_validate(normalized)
        except ValidationError as exc:
            errors.append(str(exc))
            continue

    plain_payload = _parse_plain_text_report(stripped, task)
    if plain_payload is not None:
        try:
            return AgentReport.model_validate(plain_payload)
        except ValidationError as exc:
            errors.append(str(exc))

    raise AgentReportParseError("; ".join(errors) or "no usable report found")


def degraded_agent_report(
    task: SubagentTask,
    *,
    status: str | None = None,
    reason: str,
    summary: str | None = None,
    risks: list[str] | None = None,
    recommended_next_steps: list[str] | None = None,
) -> AgentReport:
    resolved_status = _coerce_report_status(status or task.status)
    resolved_summary = _truncate_summary(
        summary
        or task.error
        or task.current_activity
        or f"Subagent {task.name} ended with status {resolved_status}."
    )
    return AgentReport(
        task_id=task.task_id,
        name=task.name,
        status=resolved_status,
        summary=resolved_summary,
        findings=[],
        files_changed=list(task.file_changes),
        commands_run=list(task.terminal_commands),
        artifacts=[],
        risks=risks or [_default_risk_for_reason(reason)],
        recommended_next_steps=recommended_next_steps or [_default_next_step_for_reason(reason)],
        transcript_ref=task.transcript_ref,
        usage_summary=task.usage_summary,
        degraded=True,
        degraded_reason=reason,
    )


def aggregate_multiagent_report(
    run: MultiAgentRun,
    tasks: list[SubagentTask],
    *,
    summary: str | None = None,
) -> MultiAgentReport:
    reports = [
        task.result
        if task.result is not None
        else degraded_agent_report(task, reason=_degraded_reason_for_task(task))
        for task in tasks
    ]
    failed_agents = [
        report.task_id
        for report in reports
        if report.status != "completed"
    ]
    status = _aggregate_run_status(run, reports, failed_agents)
    usage = UsageSummary()
    for report in reports:
        usage = usage.add(report.usage_summary)
    return MultiAgentReport(
        run_id=run.run_id,
        status=status,
        summary=summary or _aggregate_summary(status, reports),
        agent_reports=reports,
        failed_agents=failed_agents,
        file_overlaps=_aggregate_file_overlaps(reports),
        file_conflicts=_aggregate_file_conflicts(tasks),
        usage_summary=usage,
        recommended_next_steps=_aggregate_next_steps(reports),
    )


def aggregate_current_usage_summary(tasks: list[SubagentTask]) -> UsageSummary:
    usage = UsageSummary()
    for task in tasks:
        usage = usage.add(task.usage_summary)
    return usage


def _iter_json_candidates(text: str) -> list[str]:
    candidates = [match.group(1).strip() for match in JSON_CODE_BLOCK_RE.finditer(text or "")]
    stripped = (text or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    return candidates


def _normalize_report_payload(payload: dict[str, Any], task: SubagentTask) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["task_id"] = str(normalized.get("task_id") or task.task_id)
    normalized["name"] = str(normalized.get("name") or task.name)
    normalized["status"] = _coerce_report_status(normalized.get("status") or _default_report_status(task))
    normalized["summary"] = str(normalized.get("summary") or "").strip() or "Subagent completed without summary."
    normalized["transcript_ref"] = str(normalized.get("transcript_ref") or task.transcript_ref)
    normalized["usage_summary"] = _normalize_usage_summary(normalized.get("usage_summary"), task)
    normalized["findings"] = _normalize_findings(normalized.get("findings"))
    # Runtime data is authoritative for file mutations and command execution.
    normalized["files_changed"] = [item.model_dump(mode="json") for item in task.file_changes]
    normalized["commands_run"] = [item.model_dump(mode="json") for item in task.terminal_commands]
    normalized["artifacts"] = _normalize_artifacts(normalized.get("artifacts"))
    normalized["risks"] = _normalize_string_list(normalized.get("risks"), preferred_keys=("description", "detail", "summary", "title", "text"))
    normalized["recommended_next_steps"] = _normalize_string_list(
        normalized.get("recommended_next_steps"),
        preferred_keys=("action", "detail", "description", "summary", "title", "text"),
        prefix_keys=("priority",),
    )
    normalized["degraded"] = _coerce_bool(normalized.get("degraded"), default=False)
    normalized["degraded_reason"] = _optional_string(normalized.get("degraded_reason"))
    return normalized


def _coerce_report_status(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"completed", "failed", "cancelled", "timed_out", "report_invalid"}:
        return text
    aliases = {
        "done": "completed",
        "success": "completed",
        "ok": "completed",
        "error": "failed",
        "blocked": "failed",
        "canceled": "cancelled",
        "timeout": "timed_out",
        "invalid": "report_invalid",
    }
    if text in aliases:
        return aliases[text]
    return "failed"


def _default_report_status(task: SubagentTask) -> str:
    if task.status in {"completed", "failed", "cancelled", "timed_out", "report_invalid"}:
        return _coerce_report_status(task.status)
    return "completed"


def _parse_plain_text_report(text: str, task: SubagentTask) -> dict[str, Any] | None:
    sections, saw_labels = _split_plain_text_sections(text)
    if saw_labels:
        summary = (
            _join_section(sections["summary"])
            or _join_section(sections["result"])
            or _join_section(sections["scope"])
            or _truncate_summary(text)
        )
        findings = [
            {"title": item, "detail": "", "severity": "medium"}
            for item in _extract_section_items(sections["issues"])
        ]
        artifacts = [
            {"path": item, "kind": "file"}
            for item in _extract_section_items(sections["key files"])
        ]
        payload = {
            "summary": summary,
            "findings": findings,
            "artifacts": artifacts,
            "risks": _extract_section_items(sections["risks"]),
            "recommended_next_steps": _extract_section_items(sections["next steps"]),
            "status": _default_report_status(task),
        }
        return _normalize_report_payload(payload, task)

    if not text.strip():
        return None
    return _normalize_report_payload(
        {
            "summary": _truncate_summary(text),
            "status": _default_report_status(task),
        },
        task,
    )


def _split_plain_text_sections(text: str) -> tuple[dict[str, list[str]], bool]:
    sections = {
        "scope": [],
        "summary": [],
        "result": [],
        "key files": [],
        "files changed": [],
        "issues": [],
        "risks": [],
        "next steps": [],
    }
    current: str | None = None
    saw_labels = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = SECTION_HEADER_RE.match(line.strip())
        if match:
            current = match.group(1).lower()
            inline = match.group(2).strip()
            if inline:
                sections[current].append(inline)
            saw_labels = True
            continue
        if current is not None:
            sections[current].append(line)
    return sections, saw_labels


def _join_section(lines: list[str]) -> str:
    parts = [line.strip() for line in lines if line.strip() and not _is_empty_marker(line)]
    return "\n".join(parts).strip()


def _extract_section_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    saw_bullet = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line or _is_empty_marker(line):
            continue
        match = LIST_ITEM_RE.match(line)
        if match:
            items.append(match.group(1).strip())
            saw_bullet = True
            continue
        if saw_bullet and items:
            items[-1] = f"{items[-1]} {line}".strip()
            continue
        items.append(line)
    return items


def _normalize_findings(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                findings.append({"title": text, "detail": "", "severity": "info", "file": None, "line": None})
            continue
        if not isinstance(item, dict):
            continue
        detail = _first_text(item, ("detail", "description", "content", "summary", "text")) or ""
        title = _first_text(item, ("title", "headline", "name", "category", "id"))
        if not title and detail:
            title = detail.splitlines()[0].strip()[:120]
        if not title:
            continue
        findings.append(
            {
                "title": title,
                "detail": detail,
                "severity": _normalize_severity(item.get("severity") or item.get("priority")),
                "file": _optional_string(item.get("file")),
                "line": _normalize_line(item.get("line")),
            }
        )
    return findings


def _normalize_artifacts(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    artifacts: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                artifacts.append({"title": text, "kind": "note", "metadata": {}})
            continue
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        content = _optional_string(item.get("content"))
        if content:
            metadata = dict(metadata)
            metadata.setdefault("content", content)
        artifacts.append(
            {
                "path": _optional_string(item.get("path")),
                "url": _optional_string(item.get("url")),
                "title": _optional_string(item.get("title") or item.get("name")),
                "kind": _optional_string(item.get("kind") or item.get("type")),
                "metadata": metadata,
            }
        )
    return artifacts


def _normalize_usage_summary(raw: object, task: SubagentTask) -> dict[str, Any]:
    normalized = task.usage_summary.model_dump(mode="json")
    if not isinstance(raw, dict):
        return normalized
    for key in ("input_tokens", "output_tokens", "total_tokens", "request_count"):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            normalized[key] = int(value)
    cost = raw.get("cost_usd")
    if isinstance(cost, (int, float)):
        normalized["cost_usd"] = float(cost)
    return normalized


def _normalize_string_list(
    raw: object,
    *,
    preferred_keys: tuple[str, ...],
    prefix_keys: tuple[str, ...] = (),
) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                values.append(text)
            continue
        if not isinstance(item, dict):
            continue
        text = _first_text(item, preferred_keys)
        if not text:
            continue
        prefixes = [str(item[key]).strip() for key in prefix_keys if _optional_string(item.get(key))]
        if prefixes:
            text = f"{' '.join(prefixes)}: {text}"
        values.append(text)
    return values


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _optional_string(payload.get(key))
        if value:
            return value
    return None


def _normalize_severity(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"info", "low", "medium", "high", "critical"}:
        return text
    aliases = {
        "warning": "medium",
        "warn": "medium",
        "error": "high",
        "p0": "critical",
        "p1": "high",
        "p2": "medium",
        "p3": "low",
    }
    return aliases.get(text, "info")


def _normalize_line(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def _is_empty_marker(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"none", "none.", "n/a", "n.a.", "na", "no issues", "no risks", "no next steps"}


def _truncate_summary(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= MAX_DEGRADED_SUMMARY_CHARS:
        return normalized
    return normalized[: MAX_DEGRADED_SUMMARY_CHARS - 1].rstrip() + "..."


def _default_risk_for_reason(reason: str) -> str:
    if reason == "parse_failed":
        return "报告未能结构化，需主 Agent 查看 transcript"
    if reason == "timed_out":
        return "Subagent 超时，结果可能不完整"
    if reason == "cancelled":
        return "Subagent 已取消，结果可能不完整"
    if reason == "max_turns_exhausted":
        return "Subagent 达到最大轮数，结果可能不完整"
    return "Subagent 未能产出正常报告"


def _default_next_step_for_reason(reason: str) -> str:
    if reason == "parse_failed":
        return "查看 transcript_ref 人工判断"
    if reason == "timed_out":
        return "根据 partial 结果决定是否重试或拆分任务"
    if reason == "cancelled":
        return "确认取消原因后决定是否重新派发"
    return "查看 transcript_ref 并决定下一步"


def _degraded_reason_for_task(task: SubagentTask) -> str:
    if task.status == "report_invalid":
        return "parse_failed"
    if task.status == "timed_out":
        return "timed_out"
    if task.status == "cancelled":
        return "cancelled"
    return "missing_report"


def _aggregate_run_status(
    run: MultiAgentRun,
    reports: list[AgentReport],
    failed_agents: list[str],
) -> str:
    if run.status in {"cancelled", "timed_out"} and len(failed_agents) == len(reports):
        return run.status
    if not reports:
        return "failed"
    if not failed_agents:
        return "completed"
    if len(failed_agents) < len(reports):
        return "partial"
    if any(report.status == "timed_out" for report in reports):
        return "timed_out"
    if any(report.status == "cancelled" for report in reports):
        return "cancelled"
    return "failed"


def _aggregate_summary(status: str, reports: list[AgentReport]) -> str:
    completed = sum(1 for report in reports if report.status == "completed")
    total = len(reports)
    if total == 0:
        return "Multiagent run did not create any agent reports."
    return f"Multiagent run {status}: {completed}/{total} agents completed."


def _aggregate_next_steps(reports: list[AgentReport]) -> list[str]:
    steps: list[str] = []
    seen: set[str] = set()
    for report in reports:
        for step in report.recommended_next_steps:
            if step in seen:
                continue
            seen.add(step)
            steps.append(step)
    return steps


def _aggregate_file_overlaps(reports: list[AgentReport]) -> list[FileOverlap]:
    writes_by_path: dict[str, list[FileWriteRecord]] = {}
    for report in reports:
        for change in report.files_changed:
            writes_by_path.setdefault(change.path, []).append(
                FileWriteRecord(
                    task_id=report.task_id,
                    tool=change.tool,
                    at=change.at,
                )
            )
    overlaps = [
        FileOverlap(path=path, writers=sorted(writers, key=lambda item: item.at))
        for path, writers in writes_by_path.items()
        if len({writer.task_id for writer in writers}) > 1
    ]
    overlaps.sort(key=lambda item: item.path)
    return overlaps


def _aggregate_file_conflicts(tasks: list[SubagentTask]) -> list[FileConflict]:
    conflicts: list[FileConflict] = []
    seen: set[tuple[str, str, str | None, str, str]] = set()
    for task in tasks:
        for conflict in task.file_conflicts:
            key = (
                conflict.path,
                conflict.blocked_task_id,
                conflict.holding_task_id,
                conflict.reason,
                conflict.detected_at,
            )
            if key in seen:
                continue
            seen.add(key)
            conflicts.append(conflict)
    conflicts.sort(key=lambda item: (item.detected_at, item.path, item.blocked_task_id))
    return conflicts
