from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from backend.config.schema import ModelConfig
from backend.config.schema import RuntimeConfig
from backend.providers.base import BaseProvider, ProviderError, TokenUsage
from backend.runtime.message_rendering import build_user_message_for_provider
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
class MessageSegment:
    start: int
    end: int
    key: str


@dataclass(frozen=True)
class ContextCompactionBudget:
    effective_context_window: int
    auto_compact_limit: int
    soft_compact_limit: int


@dataclass(frozen=True)
class ContextUsageSnapshot:
    effective_context_window: int
    auto_compact_limit: int
    soft_compact_limit: int
    projected_next_prompt_tokens: int
    projected_pressure: float
    budget_pressure: float
    projection_source: str
    confirmed_prompt_tokens: int | None = None
    confirmed_pressure: float | None = None
    confirmed_request_kind: str | None = None
    confirmed_recorded_at: str | None = None
    projected_over_soft_limit: bool = False
    projected_over_limit: bool = False
    compaction_stage: str | None = None
    compaction_fail_streak: int = 0
    context_irreducible: bool = False
    last_compaction_failure_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "effective_context_window": self.effective_context_window,
            "auto_compact_limit": self.auto_compact_limit,
            "soft_compact_limit": self.soft_compact_limit,
            "confirmed_prompt_tokens": self.confirmed_prompt_tokens,
            "confirmed_pressure": self.confirmed_pressure,
            "confirmed_request_kind": self.confirmed_request_kind,
            "confirmed_recorded_at": self.confirmed_recorded_at,
            "projected_next_prompt_tokens": self.projected_next_prompt_tokens,
            "projected_pressure": self.projected_pressure,
            "budget_pressure": self.budget_pressure,
            "projection_source": self.projection_source,
            "projected_over_soft_limit": self.projected_over_soft_limit,
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
    return _split_message_list(list(session.messages), preserve_recent=preserve_recent)


def split_session_messages_for_checkpoint(
    session: SessionRecord,
    preserve_recent: int = 4,
    checkpoint: CheckpointRecord | None = None,
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    archived_count = checkpoint_archived_message_count(session, checkpoint)
    return _split_message_list(list(session.messages)[archived_count:], preserve_recent=preserve_recent)


def model_visible_session_messages(
    session: SessionRecord,
    checkpoint: CheckpointRecord | None = None,
) -> list[SessionMessage]:
    return list(session.messages)[checkpoint_archived_message_count(session, checkpoint) :]


def checkpoint_archived_message_count(session: SessionRecord, checkpoint: CheckpointRecord | None) -> int:
    if not checkpoint or session.metadata.get("checkpoint_active") is not True:
        return 0
    if checkpoint.metadata.get("transcript_retained") is not True:
        return 0
    if len(checkpoint.turn_range) >= 2 and isinstance(checkpoint.turn_range[1], int):
        return min(max(checkpoint.turn_range[1], 0), len(session.messages))
    raw_count = checkpoint.metadata.get("compressed_message_count")
    if isinstance(raw_count, int):
        return min(max(raw_count, 0), len(session.messages))
    return 0


def _split_message_list(
    messages: list[SessionMessage],
    preserve_recent: int = 4,
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    if preserve_recent <= 0:
        return messages, []
    segments = _build_message_segments(messages)
    if len(segments) <= preserve_recent:
        return [], messages

    preserve_segment_start = max(len(segments) - preserve_recent, 0)
    preserve_start = segments[preserve_segment_start].start

    return messages[:preserve_start], messages[preserve_start:]


def microcompact_session(
    session: SessionRecord,
    preserve_recent: int = 4,
    *,
    checkpoint: CheckpointRecord | None = None,
    artifact_dir: Path | None = None,
) -> int:
    messages_to_compact, _ = split_session_messages_for_checkpoint(
        session,
        preserve_recent=preserve_recent,
        checkpoint=checkpoint,
    )
    compactable_ids = {message.id for message in messages_to_compact}
    compacted_count = 0
    for message in session.messages:
        if message.id not in compactable_ids or message.role != "tool":
            continue
        replacement = _build_microcompact_tool_content(message)
        if not replacement or replacement == message.content:
            continue
        artifact_ref = _write_microcompact_artifact(message, artifact_dir)
        if artifact_ref:
            replacement = _build_microcompact_tool_content(message, artifact_ref=artifact_ref) or replacement
            message.metadata["microcompact_artifact_ref"] = artifact_ref
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
    head, preserved_recent_messages = split_session_messages_for_checkpoint(
        session,
        preserve_recent=preserve_recent,
        checkpoint=checkpoint,
    )
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
    archived_message_count: int | None = None,
    microcompact_count: int = 0,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "preserve_recent": preserve_recent,
        "preserve_unit": "segment",
        "compression_level": compression_level,
        "original_message_count": original_message_count,
        "compressed_message_count": archived_message_count if archived_message_count is not None else result.source_message_count,
        "newly_compressed_message_count": result.source_message_count,
        "transcript_retained": True,
        "summary_strategy": result.strategy,
        "compact_boundary": {
            "type": "checkpoint_archived_prefix",
            "message_count": archived_message_count if archived_message_count is not None else result.source_message_count,
        },
    }
    if microcompact_count:
        metadata["microcompact_count"] = microcompact_count
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
    auto_compact_limit = max(effective_context_window, 1)
    soft_threshold = min(max(float(runtime_config.context_compress_threshold), 0.0), 1.0)
    soft_compact_limit = max(int(auto_compact_limit * soft_threshold), 1)
    return ContextCompactionBudget(
        effective_context_window=effective_context_window,
        auto_compact_limit=auto_compact_limit,
        soft_compact_limit=soft_compact_limit,
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
        if not _context_rewrite_invalidates_confirmed_context(session, checkpoint, latest_record):
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
    budget_pressure = (
        projected_next_prompt_tokens / budget.auto_compact_limit
        if budget.auto_compact_limit
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
        soft_compact_limit=budget.soft_compact_limit,
        confirmed_prompt_tokens=confirmed_prompt_tokens,
        confirmed_pressure=confirmed_pressure,
        confirmed_request_kind=confirmed_request_kind,
        confirmed_recorded_at=confirmed_recorded_at,
        projected_next_prompt_tokens=projected_next_prompt_tokens,
        projected_pressure=projected_pressure,
        budget_pressure=budget_pressure,
        projection_source=projection_source,
        projected_over_soft_limit=projected_next_prompt_tokens >= budget.soft_compact_limit,
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
        },
        "existing_checkpoint_summary": checkpoint.summary if checkpoint and checkpoint.summary.strip() else "",
        "messages_to_compact": [_serialize_message(message) for message in messages_to_compact],
        "preserved_recent_messages": [_serialize_message(message) for message in preserved_recent_messages],
    }


def _serialize_message(message: SessionMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
    }
    metadata = _compaction_metadata_for_message(message)
    if metadata:
        payload["metadata"] = metadata
    return payload


def _compaction_metadata_for_message(message: SessionMessage) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    message_type = message.metadata.get("type")
    if isinstance(message_type, str) and message_type:
        metadata["type"] = message_type

    attachments = _compaction_attachment_descriptors(message.metadata.get("attachments"))
    if attachments:
        metadata["attachments"] = attachments

    if message.role == "assistant":
        tool_call_names = _compaction_tool_call_names(message.metadata.get("tool_calls"))
        if tool_call_names:
            metadata["tool_calls"] = tool_call_names
        finish_reason = message.metadata.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason:
            metadata["finish_reason"] = finish_reason
        turn_outcome = message.metadata.get("turn_outcome")
        if isinstance(turn_outcome, str) and turn_outcome:
            metadata["turn_outcome"] = turn_outcome
        return metadata

    if message.role == "tool":
        for key in (
            "tool",
            "success",
            "summary",
            "frontend_message",
            "recommended_next_step",
            "error_code",
            "recovery_class",
            "path",
            "microcompact_artifact_ref",
            "microcompact_strategy",
        ):
            value = message.metadata.get(key)
            if isinstance(value, bool):
                metadata[key] = value
                continue
            if isinstance(value, str) and value:
                metadata[key] = value
        for key in ("microcompact_original_length",):
            value = message.metadata.get(key)
            if isinstance(value, int):
                metadata[key] = value
        return metadata

    return metadata


def _compaction_tool_call_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _compaction_attachment_descriptors(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    descriptors: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        descriptor: dict[str, str] = {}
        for key in ("name", "content_type", "kind"):
            field = item.get(key)
            if isinstance(field, str) and field:
                descriptor[key] = field
        if descriptor:
            descriptors.append(descriptor)
    return descriptors


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


def _context_rewrite_invalidates_confirmed_context(
    session: SessionRecord,
    checkpoint: CheckpointRecord | None,
    latest_record: ModelUsageRecord,
) -> bool:
    if checkpoint_archived_message_count(session, checkpoint) <= 0:
        checkpoint_invalidates = False
    else:
        checkpoint_created_at = _parse_timestamp(checkpoint.created_at if checkpoint else None)
        latest_recorded_at = _parse_timestamp(latest_record.created_at)
        checkpoint_invalidates = bool(
            checkpoint_created_at is not None
            and latest_recorded_at is not None
            and checkpoint_created_at > latest_recorded_at
        )
    if checkpoint_invalidates:
        return True

    latest_recorded_at = _parse_timestamp(latest_record.created_at)
    microcompact_at = _parse_timestamp(str(session.metadata.get("last_microcompact_at") or ""))
    return bool(microcompact_at is not None and latest_recorded_at is not None and microcompact_at > latest_recorded_at)


def _build_message_segments(messages: list[SessionMessage]) -> list[MessageSegment]:
    segments: list[MessageSegment] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group_id = _message_group_id(message)
        if group_id:
            end = index + 1
            while end < len(messages) and _message_group_id(messages[end]) == group_id:
                end += 1
            segments.append(MessageSegment(start=index, end=end, key=f"group:{group_id}"))
            index = end
            continue

        tool_call_ids = _assistant_tool_call_ids(message)
        if message.role == "assistant" and tool_call_ids:
            remaining = set(tool_call_ids)
            end = index + 1
            while end < len(messages):
                candidate_tool_call_id = _message_tool_call_id(messages[end])
                if messages[end].role != "tool" or candidate_tool_call_id not in remaining:
                    break
                remaining.discard(candidate_tool_call_id)
                end += 1
                if not remaining:
                    break
            segments.append(MessageSegment(start=index, end=end, key=f"tool_calls:{','.join(tool_call_ids)}"))
            index = end
            continue

        tool_call_id = _message_tool_call_id(message)
        if message.role == "tool" and tool_call_id:
            segments.append(MessageSegment(start=index, end=index + 1, key=f"tool:{tool_call_id}"))
            index += 1
            continue

        segments.append(MessageSegment(start=index, end=index + 1, key=f"message:{message.id}"))
        index += 1
    return segments


def _assistant_tool_call_ids(message: SessionMessage) -> list[str]:
    tool_calls = message.metadata.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    ids: list[str] = []
    for raw_tool_call in tool_calls:
        if not isinstance(raw_tool_call, dict):
            continue
        tool_call_id = raw_tool_call.get("id")
        if isinstance(tool_call_id, str) and tool_call_id.strip():
            ids.append(tool_call_id)
    return ids


def _message_tool_call_id(message: SessionMessage) -> str | None:
    tool_call_id = message.metadata.get("tool_call_id")
    return tool_call_id if isinstance(tool_call_id, str) and tool_call_id else None


def _normalize_summary_text(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    return cleaned


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

    if message.role == "user":
        return {"role": "user", "content": build_user_message_for_provider(message)}

    return {"role": message.role, "content": message.content}


def _build_microcompact_tool_content(message: SessionMessage, *, artifact_ref: str | None = None) -> str | None:
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
    if artifact_ref:
        parts.append(f"Original output archived at: {artifact_ref}.")
    if frontend_message:
        parts.append(frontend_message.strip())
    elif preview:
        parts.append(f"Preview: {preview}")
    if recommended_next_step:
        parts.append(f"Next: {recommended_next_step.strip()}")
    elif preview and frontend_message:
        parts.append(f"Preview: {preview}")
    return " ".join(part for part in parts if part).strip()


def _write_microcompact_artifact(message: SessionMessage, artifact_dir: Path | None) -> str | None:
    if artifact_dir is None or not message.content:
        return None
    digest = sha256(message.content.encode("utf-8", errors="replace")).hexdigest()[:24]
    safe_message_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in message.id)[:80]
    filename = f"{safe_message_id or 'message'}_{digest}.txt"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / filename
    if not artifact_path.exists():
        artifact_path.write_text(message.content, encoding="utf-8")
    return str(artifact_path)


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
