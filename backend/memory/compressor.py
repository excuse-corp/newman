from __future__ import annotations

from backend.providers.base import BaseProvider
from backend.sessions.models import SessionRecord


def summarize_messages(session: SessionRecord, preserve_recent: int = 4) -> str:
    head = session.messages[:-preserve_recent] if len(session.messages) > preserve_recent else session.messages
    if not head:
        return ""
    lines = []
    for message in head[-8:]:
        content = message.content.strip().replace("\n", " ")
        lines.append(f"- {message.role}: {content[:160]}")
    return "Checkpoint Summary\n" + "\n".join(lines)


def estimate_pressure(provider: BaseProvider, messages: list[dict], max_context_tokens: int = 8_000) -> float:
    return provider.estimate_tokens(messages) / max_context_tokens
