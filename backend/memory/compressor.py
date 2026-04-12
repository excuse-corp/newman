from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config.schema import ModelConfig
from backend.providers.base import BaseProvider, ProviderError, TokenUsage
from backend.sessions.models import CheckpointRecord
from backend.sessions.models import SessionMessage
from backend.sessions.models import SessionRecord
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


COMPACTION_PROMPT = (Path(__file__).resolve().parent / "prompts" / "checkpoint_compact.md").read_text(encoding="utf-8")
SUMMARY_MAX_TOKENS = 1_200


@dataclass
class CompressionSummaryResult:
    summary: str
    strategy: str
    source_message_count: int
    model: str | None = None
    usage: TokenUsage | None = None
    fallback_reason: str | None = None


def split_session_messages(
    session: SessionRecord,
    preserve_recent: int = 4,
) -> tuple[list[SessionMessage], list[SessionMessage]]:
    if preserve_recent <= 0:
        return list(session.messages), []
    if len(session.messages) <= preserve_recent:
        return [], list(session.messages)
    return list(session.messages[:-preserve_recent]), list(session.messages[-preserve_recent:])


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


def _normalize_summary_text(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            cleaned = "\n".join(lines[1:-1]).strip()
    return cleaned


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
