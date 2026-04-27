from __future__ import annotations

from typing import Any

from backend.sessions.models import SessionMessage


_EMPTY_USER_TEXT = "（用户未输入文本，仅上传了附件）"
_FAILED_PARSE_HINT = "附件预解析失败，当前不能将附件内容视为已成功读取。"
_PARSE_CONTEXT_HINT = (
    "以下附件观察结果已经由系统完成预解析，并作为当前可用上下文提供给你。"
    "只要下方没有明确写“解析失败”，就不要再说你看不到图片、无法查看附件，"
    "也不要为了重新看图再去调用 read_file。"
)


def get_original_user_content(message: SessionMessage) -> str:
    original = message.metadata.get("original_content")
    if isinstance(original, str):
        return original
    return message.content


def get_multimodal_parse(message: SessionMessage) -> dict[str, Any] | None:
    payload = message.metadata.get("multimodal_parse")
    return payload if isinstance(payload, dict) else None


def get_normalized_user_content(message: SessionMessage) -> str:
    payload = get_multimodal_parse(message)
    if payload and payload.get("status") == "completed":
        normalized = payload.get("normalized_user_input")
        if isinstance(normalized, str) and normalized.strip():
            return normalized.strip()
    return get_original_user_content(message).strip()


def build_user_message_title(message: SessionMessage) -> str:
    normalized = get_normalized_user_content(message)
    if normalized:
        return normalized[:24]

    attachments = _attachment_items(message)
    if attachments:
        first = attachments[0]
        filename = first.get("filename")
        if isinstance(filename, str) and filename.strip():
            return filename.strip()[:24]
        return "图片消息"

    original = get_original_user_content(message).strip()
    return original[:24]


def build_user_message_for_provider(message: SessionMessage) -> str:
    payload = get_multimodal_parse(message)
    attachments = _attachment_items(message)
    original = get_original_user_content(message).strip()

    if not attachments and not payload:
        return message.content

    lines = [
        "## User Original Request",
        original or _EMPTY_USER_TEXT,
    ]

    if attachments:
        lines.extend(["", "## Uploaded Attachments"])
        for item in attachments:
            lines.append(f"- {_attachment_label(item)}")

    if not payload:
        return "\n".join(lines)

    status = str(payload.get("status") or "").strip()
    if status == "completed":
        lines.extend(["", "## Attachment Context", _PARSE_CONTEXT_HINT])
        attachment_summaries = _string_list(payload.get("attachment_summaries"))
        if attachment_summaries:
            lines.extend(["", "## Attachment Observations"])
            for item, summary in zip(attachments, attachment_summaries, strict=False):
                label = _attachment_label(item) if item is not None else "附件"
                lines.append(f"- {label}: {summary}")

        task_intent = str(payload.get("task_intent") or "").strip()
        key_facts = _string_list(payload.get("key_facts"))
        ocr_text = _string_list(payload.get("ocr_text"))
        uncertainties = _string_list(payload.get("uncertainties"))
        normalized = str(payload.get("normalized_user_input") or "").strip()

        lines.extend(["", "## Multimodal Parse"])
        if task_intent:
            lines.append(f"- Task intent: {task_intent}")
        if key_facts:
            lines.append("- Key facts:")
            for item in key_facts:
                lines.append(f"  - {item}")
        if ocr_text:
            lines.append("- OCR text:")
            for item in ocr_text:
                lines.append(f"  - {item}")
        if uncertainties:
            lines.append("- Uncertainties:")
            for item in uncertainties:
                lines.append(f"  - {item}")
        if normalized:
            lines.extend(["", "## Normalized User Input", normalized])
        return "\n".join(lines)

    lines.extend(["", "## Multimodal Parse Status", f"- {_FAILED_PARSE_HINT}"])
    frontend_message = str(payload.get("frontend_message") or "").strip()
    if frontend_message:
        lines.append(f"- Detail: {frontend_message}")
    return "\n".join(lines)


def _attachment_items(message: SessionMessage) -> list[dict[str, Any]]:
    raw = message.metadata.get("attachments")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _attachment_label(item: dict[str, Any]) -> str:
    filename = item.get("filename")
    content_type = item.get("content_type")
    base = str(filename).strip() if isinstance(filename, str) and filename.strip() else "附件"
    if isinstance(content_type, str) and content_type.strip():
        return f"{base} ({content_type.strip()})"
    return base


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned:
                normalized.append(cleaned)
    return normalized
