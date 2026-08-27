from __future__ import annotations

import hmac
import json
import threading
from dataclasses import dataclass, field
from time import time
from typing import Any, Mapping
from uuid import uuid4


class EscalationTokenError(RuntimeError):
    """Raised when an escalation token cannot be used safely."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class EscalationToken:
    token_id: str
    bindings: dict[str, Any]
    issued_at: float
    expires_at: float
    consumed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class EscalationTokenStore:
    """Process-local, atomic single-use store for sandbox escalation grants.

    ApprovalManager is intentionally in-memory today. Keeping token state in a
    separate store makes the consume boundary explicit and gives a future
    persistent worker an obvious replacement point without weakening the
    binding checks.
    """

    def __init__(self, *, clock=time, max_tokens: int = 4096, consumed_retention_seconds: float = 300):
        if max_tokens < 1:
            raise ValueError("escalation token max_tokens must be positive")
        if consumed_retention_seconds < 0:
            raise ValueError("escalation token consumed retention must be non-negative")
        self._clock = clock
        self._max_tokens = int(max_tokens)
        self._consumed_retention_seconds = float(consumed_retention_seconds)
        self._tokens: dict[str, EscalationToken] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        bindings: Mapping[str, Any],
        *,
        ttl_seconds: float,
        metadata: Mapping[str, Any] | None = None,
    ) -> EscalationToken:
        if ttl_seconds <= 0:
            raise ValueError("escalation token ttl must be positive")
        now = float(self._clock())
        token = EscalationToken(
            token_id=uuid4().hex,
            bindings=dict(bindings),
            issued_at=now,
            expires_at=now + float(ttl_seconds),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._purge_locked(now)
            if len(self._tokens) >= self._max_tokens:
                self._evict_consumed_for_capacity_locked()
            if len(self._tokens) >= self._max_tokens:
                raise EscalationTokenError(
                    "SANDBOX_ESCALATION_TOKEN_CAPACITY_EXCEEDED",
                    "sandbox escalation token store capacity exceeded",
                )
            self._tokens[token.token_id] = token
        return token

    def consume(self, token_id: str, bindings: Mapping[str, Any]) -> EscalationToken:
        now = float(self._clock())
        with self._lock:
            token = self._tokens.get(token_id)
            if token is None:
                raise EscalationTokenError(
                    "SANDBOX_ESCALATION_TOKEN_INVALID",
                    "sandbox escalation token is unknown or expired",
                )
            if token.consumed_at is not None:
                raise EscalationTokenError(
                    "SANDBOX_ESCALATION_TOKEN_ALREADY_CONSUMED",
                    "sandbox escalation token was already consumed",
                )
            if now >= token.expires_at:
                self._tokens.pop(token_id, None)
                raise EscalationTokenError(
                    "SANDBOX_ESCALATION_TOKEN_EXPIRED",
                    "sandbox escalation token has expired",
                )
            self._purge_locked(now)
            if not _bindings_match(token.bindings, bindings):
                raise EscalationTokenError(
                    "SANDBOX_ESCALATION_TOKEN_MISMATCH",
                    "sandbox escalation token does not match this invocation",
                )
            token.consumed_at = now
            return token

    def get(self, token_id: str) -> EscalationToken | None:
        with self._lock:
            self._purge_locked(float(self._clock()))
            token = self._tokens.get(token_id)
            if token is None or token.consumed_at is not None:
                return None
            return token

    def _purge_locked(self, now: float) -> None:
        for token_id, token in list(self._tokens.items()):
            consumed_expired = (
                token.consumed_at is not None
                and token.consumed_at + self._consumed_retention_seconds <= now
            )
            if token.expires_at <= now or consumed_expired:
                self._tokens.pop(token_id, None)

    def _evict_consumed_for_capacity_locked(self) -> None:
        consumed = sorted(
            (
                (token.consumed_at or token.expires_at, token_id)
                for token_id, token in self._tokens.items()
                if token.consumed_at is not None
            )
        )
        for _timestamp, token_id in consumed:
            if len(self._tokens) < self._max_tokens:
                return
            self._tokens.pop(token_id, None)


def _bindings_match(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    """Compare canonical JSON so nested roots and nulls cannot be bypassed."""

    expected_payload = json.dumps(dict(expected), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    actual_payload = json.dumps(dict(actual), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.compare_digest(expected_payload, actual_payload)
