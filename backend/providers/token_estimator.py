from __future__ import annotations

from typing import Any

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency fallback
    tiktoken = None


DEFAULT_MODEL = "gpt-4o-mini"


def estimate_message_tokens(messages: list[dict], model: str | None = None) -> int:
    if tiktoken is not None:
        encoding = _encoding_for_model(model)
        total = 0
        for message in messages:
            total += 4
            for key, value in message.items():
                total += len(encoding.encode(_stringify_content(value)))
                if key == "name":
                    total += 1
        return max(1, total + 2)
    return _fallback_estimate(messages)


def _fallback_estimate(messages: list[dict[str, Any]]) -> int:
    total_chars = 0
    for message in messages:
        content = message.get("content", "")
        total_chars += len(_stringify_content(content))
        total_chars += len(str(message.get("role", "")))
    return max(1, total_chars // 4)


def _encoding_for_model(model: str | None):
    target = model or DEFAULT_MODEL
    try:
        return tiktoken.encoding_for_model(target)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "image_url":
                    parts.append(str(item.get("image_url", "")))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)
