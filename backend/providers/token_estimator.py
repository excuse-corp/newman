from __future__ import annotations


def estimate_message_tokens(messages: list[dict]) -> int:
    total_chars = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            total_chars += sum(len(str(item)) for item in content)
        else:
            total_chars += len(str(content))
    return max(1, total_chars // 4)
