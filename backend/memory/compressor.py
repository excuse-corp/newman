from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.config.schema import ModelConfig
from backend.config.schema import RuntimeConfig
from backend.providers.base import BaseProvider, ProviderError, TokenUsage
from backend.sessions.models import CheckpointRecord
from backend.sessions.models import SessionMessage
from backend.sessions.models import SessionRecord
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.models import ModelUsageRecord
from backend.usage.store import PostgresModelUsageStore


COMPACTION_PROMPT = (Path(__file__).resolve().parent / "prompts" / "checkpoint_compact.md").read_text(encoding="utf-8")
SUMMARY_MAX_TOKENS = 1_200
MICROCOMPACT_TOOL_MIN_CHARS = 600
MICROCOMPACT_TOOL_PREVIEW_CHARS = 240


@dataclass
class CompressionSummaryResult:
    summary: str
    strategy: str
    source_message_count: int
    model: str | None = None
    usage: TokenUsage | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class ContextCompactionBudget:
    effective_context_window: int
    auto_compact_limit: int
    reply_reserve_tokens: int
    compact_reserve_tokens: int
    safety_buffer_tokens: int


@dataclass(frozen=True)
class ContextUsageSnapshot:
    effective_context_window: int
    auto_compact_limit: int
    projected_next_prompt_tokens: int
    projected_pressure: float
    projection_source: str
    confirmed_prompt_tokens: int | None = None
    confirmed_pressure: float | None = None
    confirmed_request_kind: str | None = None
    confirmed_recorded_at: str | None = None
    projected_over_limit: bool = False
    compaction_stage: str | None = None
    compaction_fail_streak: int = 0
    context_irreducible: bool = False
    last_compaction_failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "effective_context_window": self.effective_context_window,
            "auto_compact_limit": self.auto_compact_limit,
            "confirmed_prompt_tokens": self.confirmed_prompt_tokens,
            "confirmed_pressure": self.confirmed_pressure,
            "confirmed_request_kind": self.confirmed_request_kind,
            "confirmed_recorded_at": self.confirmed_recorded_at,
            "projected_next_prompt_tokens": self.projected_next_prompt_tokens,
            "projected_pressure": self.projected_pressure,
            "projection_source": self.projection_source,
            "projected_over_limit": self.projected_over_limit,
            "compaction_stage": self.compaction_stage,
            "compaction_fail_streak": self.compaction_fail_streak,
            "context_irreducible": self.context_irreducible,
            "last_compaction_failure_reason": self.last_compaction_failure_reason,
        }


def split_session_messages(
    session: SessionRecord,
    preserve_recent: int = 4,
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    messages = list(session.messages)
    if preserve_recent <= 0:
        return messages, []
    if len(messages) <= preserve_recent:
        return [], messages

    preserve_start = max(len(messages) - preserve_recent, 0)
    preserved_messages = messages[preserve_start:]
    preserve_turn_ids = {
        turn_id
        for turn_id in (_message_turn_id(message) for message in preserved_messages)
        if turn_id
    }
    preserve_group_ids = {
        group_id
        for group_id in (_message_group_id(message) for message in preserved_messages)
        if group_id
    }

    while preserve_start > 0:
        candidate = messages[preserve_start - 1]
        candidate_turn_id = _message_turn_id(candidate)
        candidate_group_id = _message_group_id(candidate)
        if candidate_turn_id and candidate_turn_id in preserve_turn_ids:
            preserve_start -= 1
            continue
        if candidate_group_id and candidate_group_id in preserve_group_ids:
            preserve_start -= 1
            if candidate_turn_id:
                preserve_turn_ids.add(candidate_turn_id)
            continue
        break

    return messages[:preserve_start], messages[preserve_start:]


def microcompact_session(session: SessionRecord, preserve_recent: int = 4) -> int:
    messages_to_compact, _ = split_session_messages(session, preserve_recent=preserve_recent)
    compactable_ids = {message.id for message in messages_to_compact}
    compacted_count = 0
    for message in session.messages:
        if message.id not in compactable_ids or message.role != "tool":
            continue
        replacement = _build_microcompact_tool_content(message)
        if not replacement or replacement == message.content:
            continue
        message.metadata["microcompact_applied"] = True
        message.metadata["microcompact_strategy"] = "tool_output_digest"
        message.metadata["microcompact_original_length"] = len(message.content)
        message.content = replacement
        compacted_count += 1
    return compacted_count


async def summarize_messages(
    provider: BaseProvider,
    model_config: ModelConfig,
    provider_type: str,
    session: SessionRecord,
    preserve_recent: int = 4,
    checkpoint: CheckpointRecord | None = None,
    usage_store: PostgresModelUsageStore | None = None,
    turn_id: str | None = None,
    request_kind: str = "context_compaction",
) -> CompressionSummaryResult | None:
    head, preserved_recent_messages = split_session_messages(session, preserve_recent=preserve_recent)
    if not head:
        return None

    if provider.__class__.__name__ != "MockProvider":
        try:
            response = await provider.chat(
                [
                    {"role": "system", "content": COMPACTION_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Create a consolidated checkpoint summary for the archived portion of this session.\n"
                            "Return plain Markdown only, with concise section headings when useful.\n"
                            "Do not use code fences.\n\n"
                            f"```json\n{json.dumps(_build_compaction_payload(session, checkpoint, head, preserved_recent_messages), ensure_ascii=False, indent=2)}\n```"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=SUMMARY_MAX_TOKENS,
            )
            record_model_usage(
                usage_store,
                ModelRequestContext(
                    request_kind=request_kind,
                    model_config=model_config,
                    provider_type=provider_type,
                    streaming=False,
                    counts_toward_context_window=False,
                    session_id=session.session_id,
                    turn_id=turn_id,
                    metadata={
                        "messages_to_compact_count": len(head),
                        "preserved_recent_count": len(preserved_recent_messages),
                        "estimated_input_tokens": provider.estimate_tokens(
                            [
                                {"role": "system", "content": COMPACTION_PROMPT},
                                {
                                    "role": "user",
                                    "content": json.dumps(
                                        _build_compaction_payload(
                                            session,
                                            checkpoint,
                                            head,
                                            preserved_recent_messages,
                                        ),
                                        ensure_ascii=False,
                                    ),
                                },
                            ]
                        ),
                    },
                ),
                response,
            )
        except ProviderError as exc:
            fallback = _fallback_summary(head, checkpoint, fallback_reason=f"{exc.provider}:{exc.kind}")
            return fallback if fallback.summary else None

        summary = _normalize_summary_text(response.content)
        if summary:
            return CompressionSummaryResult(
                summary=summary,
                strategy="llm_handoff_summary",
                source_message_count=len(head),
                model=response.model or None,
                usage=response.usage,
            )
        fallback = _fallback_summary(head, checkpoint, fallback_reason="empty_model_summary")
        return fallback if fallback.summary else None

    fallback = _fallback_summary(head, checkpoint, fallback_reason="mock_provider")
    return fallback if fallback.summary else None


def build_checkpoint_metadata(
    result: CompressionSummaryResult,
    *,
    preserve_recent: int,
    compression_level: str,
    original_message_count: int,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "preserve_recent": preserve_recent,
        "compression_level": compression_level,
        "original_message_count": original_message_count,
        "compressed_message_count": result.source_message_count,
        "summary_strategy": result.strategy,
    }
    if result.model:
        metadata["summary_model"] = result.model
    if result.usage:
        metadata["summary_usage"] = {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
        }
    if result.fallback_reason:
        metadata["summary_fallback_reason"] = result.fallback_reason
    return metadata


def estimate_pressure(provider: BaseProvider, messages: list[dict], max_context_tokens: int = 8_000) -> float:
    return provider.estimate_tokens(messages) / max_context_tokens


def build_context_compaction_budget(model_config: ModelConfig, runtime_config: RuntimeConfig) -> ContextCompactionBudget:
    effective_context_window = model_config.effective_context_window or model_config.context_window or 8_000
    reply_reserve_tokens = (
        runtime_config.context_reply_reserve_tokens_large
        if effective_context_window >= 64_000
        else runtime_config.context_reply_reserve_tokens_small
    )
    if effective_context_window >= 128_000:
        safety_buffer_tokens = runtime_config.context_safety_buffer_tokens_large
    elif effective_context_window >= 64_000:
        safety_buffer_tokens = runtime_config.context_safety_buffer_tokens_medium
    else:
        safety_buffer_tokens = runtime_config.context_safety_buffer_tokens_small
    compact_reserve_tokens = runtime_config.context_compact_reserve_tokens
    auto_compact_limit = max(
        effective_context_window - reply_reserve_tokens - compact_reserve_tokens - safety_buffer_tokens,
        1,
    )
    return ContextCompactionBudget(
        effective_context_window=effective_context_window,
        auto_compact_limit=auto_compact_limit,
        reply_reserve_tokens=reply_reserve_tokens,
        compact_reserve_tokens=compact_reserve_tokens,
        safety_buffer_tokens=safety_buffer_tokens,
    )


def build_context_usage_snapshot(
    provider: BaseProvider,
    model_config: ModelConfig,
    runtime_config: RuntimeConfig,
    assembled_messages: list[dict[str, Any]],
    session: SessionRecord,
    checkpoint: CheckpointRecord | None,
    *,
    latest_record: ModelUsageRecord | None = None,
) -> ContextUsageSnapshot:
    budget = build_context_compaction_budget(model_config, runtime_config)
    assembled_estimate = provider.estimate_tokens(assembled_messages)
    projection_source = "assembled_prompt_estimate"
    projected_next_prompt_tokens = assembled_estimate
    confirmed_prompt_tokens: int | None = None
    confirmed_request_kind: str | None = None
    confirmed_recorded_at: str | None = None

    if latest_record and latest_record.input_tokens > 0:
        confirmed_prompt_tokens = latest_record.input_tokens
        confirmed_request_kind = latest_record.request_kind
        confirmed_recorded_at = latest_record.created_at
        incremental_projection = confirmed_prompt_tokens + _estimate_incremental_context_tokens(
            provider,
            session,
            checkpoint,
            latest_record,
        )
        if incremental_projection >= assembled_estimate:
            projected_next_prompt_tokens = incremental_projection
            projection_source = "confirmed_plus_delta"

    confirmed_pressure = (
        confirmed_prompt_tokens / budget.effective_context_window
        if confirmed_prompt_tokens is not None and budget.effective_context_window
        else None
    )
    projected_pressure = (
        projected_next_prompt_tokens / budget.effective_context_window
        if budget.effective_context_window
        else 0.0
    )
    raw_fail_streak = session.metadata.get("compaction_fail_streak")
    compaction_fail_streak = raw_fail_streak if isinstance(raw_fail_streak, int) and raw_fail_streak >= 0 else 0
    compaction_stage = session.metadata.get("last_compaction_stage")
    if not isinstance(compaction_stage, str) or not compaction_stage:
        compaction_stage = None
    raw_irreducible = session.metadata.get("context_irreducible")
    context_irreducible = raw_irreducible is True
    last_compaction_failure_reason = session.metadata.get("last_compaction_failure_reason")
    if not isinstance(last_compaction_failure_reason, str) or not last_compaction_failure_reason:
        last_compaction_failure_reason = None

    return ContextUsageSnapshot(
        effective_context_window=budget.effective_context_window,
        auto_compact_limit=budget.auto_compact_limit,
        confirmed_prompt_tokens=confirmed_prompt_tokens,
        confirmed_pressure=confirmed_pressure,
        confirmed_request_kind=confirmed_request_kind,
        confirmed_recorded_at=confirmed_recorded_at,
        projected_next_prompt_tokens=projected_next_prompt_tokens,
        projected_pressure=projected_pressure,
        projection_source=projection_source,
        projected_over_limit=projected_next_prompt_tokens >= budget.auto_compact_limit,
        compaction_stage=compaction_stage,
        compaction_fail_streak=compaction_fail_streak,
        context_irreducible=context_irreducible,
        last_compaction_failure_reason=last_compaction_failure_reason,
    )


def _build_compaction_payload(
    session: SessionRecord,
    checkpoint: CheckpointRecord | None,
    messages_to_compact: list[SessionMessage],
    preserved_recent_messages: list[SessionMessage],
) -> dict[str, Any]:
    return {
        "session": {
            "session_id": session.session_id,
            "title": session.title,
            "message_count": len(session.messages),
            "metadata": session.metadata,
        },
        "existing_checkpoint_summary": checkpoint.summary if checkpoint and checkpoint.summary.strip() else "",
        "messages_to_compact": [_serialize_message(message) for message in messages_to_compact],
        "preserved_recent_messages": [_serialize_message(message) for message in preserved_recent_messages],
    }


def _serialize_message(message: SessionMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "metadata": message.metadata,
    }


def _estimate_incremental_context_tokens(
    provider: BaseProvider,
    session: SessionRecord,
    checkpoint: CheckpointRecord | None,
    latest_record: ModelUsageRecord,
) -> int:
    anchor = _parse_timestamp(latest_record.created_at)
    if anchor is None:
        return 0

    delta_messages: list[dict[str, Any]] = []
    has_restored_checkpoint = any(
        item.role == "system" and item.metadata.get("type") == "checkpoint_restore"
        for item in session.messages
    )
    checkpoint_anchor = _parse_timestamp(checkpoint.created_at) if checkpoint else None
    if checkpoint and checkpoint_anchor and checkpoint_anchor > anchor and not has_restored_checkpoint:
        delta_messages.append({"role": "system", "content": f"## Checkpoint Summary\n{checkpoint.summary}"})

    for message in session.messages:
        message_timestamp = _parse_timestamp(message.created_at)
        if message_timestamp is None or message_timestamp <= anchor:
            continue
        delta_messages.append(_provider_message_from_session_message(message))

    if not delta_messages:
        return 0
    return provider.estimate_tokens(delta_messages)


def _normalize_summary_text(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    return cleaned


def _message_turn_id(message: SessionMessage) -> str | None:
    turn_id = message.metadata.get("turn_id")
    return turn_id if isinstance(turn_id, str) and turn_id else None


def _message_group_id(message: SessionMessage) -> str | None:
    group_id = message.metadata.get("group_id")
    return group_id if isinstance(group_id, str) and group_id else None


def _provider_message_from_session_message(message: SessionMessage) -> dict[str, Any]:
    if message.role == "assistant":
        tool_calls = message.metadata.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            provider_tool_calls = []
            for raw_tool_call in tool_calls:
                if not isinstance(raw_tool_call, dict):
                    continue
                name = raw_tool_call.get("name")
                arguments = raw_tool_call.get("arguments", {})
                if not isinstance(name, str) or not name:
                    continue
                provider_tool_calls.append(
                    {
                        "id": str(raw_tool_call.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                )
            payload: dict[str, Any] = {"role": "assistant", "content": message.content}
            if provider_tool_calls:
                payload["tool_calls"] = provider_tool_calls
            return payload

    if message.role == "tool":
        payload = {"role": "tool", "content": message.content}
        tool_call_id = message.metadata.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            payload["tool_call_id"] = tool_call_id
        return payload

    return {"role": message.role, "content": message.content}


def _build_microcompact_tool_content(message: SessionMessage) -> str | None:
    if message.metadata.get("microcompact_applied"):
        return None

    normalized_content = " ".join(message.content.strip().split())
    frontend_message = message.metadata.get("frontend_message")
    frontend_message = frontend_message if isinstance(frontend_message, str) and frontend_message.strip() else ""
    recommended_next_step = message.metadata.get("recommended_next_step")
    recommended_next_step = (
        recommended_next_step if isinstance(recommended_next_step, str) and recommended_next_step.strip() else ""
    )
    if len(normalized_content) < MICROCOMPACT_TOOL_MIN_CHARS and not frontend_message and not recommended_next_step:
        return None

    tool_name = message.metadata.get("tool")
    tool_name = tool_name if isinstance(tool_name, str) and tool_name else "tool"
    success = message.metadata.get("success")
    status = "success" if success is True else "failure" if success is False else "completed"
    preview = _truncate_text(normalized_content, MICROCOMPACT_TOOL_PREVIEW_CHARS)

    parts = [f"[Microcompact tool output] {tool_name} {status}."]
    if frontend_message:
        parts.append(frontend_message.strip())
    elif preview:
        parts.append(f"Preview: {preview}")
    if recommended_next_step:
        parts.append(f"Next: {recommended_next_step.strip()}")
    elif preview and frontend_message:
        parts.append(f"Preview: {preview}")
    return " ".join(part for part in parts if part).strip()


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _truncate_text(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3].rstrip() + "..."


def _fallback_summary(
    messages_to_compact: list[SessionMessage],
    checkpoint: CheckpointRecord | None,
    *,
    fallback_reason: str,
) -> CompressionSummaryResult:
    summary_parts: list[str] = []
    if checkpoint and checkpoint.summary.strip():
        summary_parts.append(checkpoint.summary.strip())

    message_lines = []
    for message in messages_to_compact:
        content = " ".join(message.content.strip().split())
        if not content:
            continue
        message_lines.append(f"- {message.role}: {content}")

    if message_lines:
        summary_parts.append("## Archived Message Snapshot\n" + "\n".join(message_lines))

    return CompressionSummaryResult(
        summary="\n\n".join(part for part in summary_parts if part).strip(),
        strategy="fallback_archived_snapshot",
        source_message_count=len(messages_to_compact),
        fallback_reason=fallback_reason,
    )
