from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from backend.config.schema import ModelConfig
from backend.providers.base import ProviderResponse
from backend.usage.models import ModelUsageRecord
from backend.usage.store import PostgresModelUsageStore


@dataclass
class ModelRequestContext:
    request_kind: str
    model_config: ModelConfig
    provider_type: str
    streaming: bool
    counts_toward_context_window: bool = False
    session_id: str | None = None
    turn_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def record_model_usage(
    store: PostgresModelUsageStore | None,
    context: ModelRequestContext,
    response: ProviderResponse,
) -> ModelUsageRecord:
    record = ModelUsageRecord(
        request_id=uuid4().hex,
        session_id=context.session_id,
        turn_id=context.turn_id,
        request_kind=context.request_kind,
        counts_toward_context_window=context.counts_toward_context_window,
        streaming=context.streaming,
        provider_type=context.provider_type,
        model=response.model or context.model_config.model,
        context_window=context.model_config.context_window,
        effective_context_window=context.model_config.effective_context_window,
        usage_available=response.usage.total_tokens > 0,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        total_tokens=response.usage.total_tokens,
        finish_reason=response.finish_reason,
        metadata=dict(context.metadata),
    )
    if store is not None:
        try:
            store.record(record)
        except Exception as exc:
            print(f"[usage] failed to persist usage record: {exc}")
    return record
