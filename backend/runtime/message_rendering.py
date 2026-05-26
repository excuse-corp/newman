from __future__ import annotations

from typing import Any
from pathlib import Path

from backend.attachments.service import ATTACHMENT_PROMPT_PER_FILE_CHARS, ATTACHMENT_PROMPT_TOTAL_CHARS

from backend.sessions.models import SessionMessage


_EMPTY_USER_TEXT = "（用户未输入文本，仅上传了附件）"
_FAILED_PARSE_HINT = "附件解析失败，当前不能将该附件内容视为已成功读取。"
_ATTACHMENT_METADATA_HINT = (
    "当前只提供附件元数据，不代表你已经知道附件内容。"
    "如果回答需要附件正文、截图内容或表格内容，先调用 parse_attachment。"
    "不要直接猜测附件内容，也不要直接读取原始上传文件。"
)
_PARSE_CONTEXT_HINT = (
    "以下附件已经由系统完成解析，并作为当前可用上下文提供给你。"
    "对图片附件，不要再说你看不到图片；对文档附件，不要再说你无法读取附件。"
    "如果用户当前问题只是阅读、总结、提取、核对或回答附件现有内容，并且这些解析结果已经足够，你必须直接回答。"
    "禁止为了理解该附件再次调用 search_files、list_dir、read_file、read_file_range 去重新查找或读取上传附件。"
    "不要把附件文件名当作检索关键词。"
    "优先使用下方解析结果回答，不要再去读取原始上传文件。"
    "只有在这里提供的解析结果仍不足以完成任务时，才考虑补充读取解析后的 Markdown 文件。"
)
_ATTACHMENT_EDIT_TERMS = (
    "编辑",
    "修改",
    "改写",
    "改成",
    "更新",
    "新增",
    "添加",
    "补充",
    "追加",
    "插入",
    "删除",
    "移除",
    "替换",
    "填写",
    "填入",
    "写回",
    "保存",
    "导出",
    "生成",
    "重写",
    "拆分",
    "合并",
    "edit",
    "modify",
    "update",
    "add ",
    "append",
    "insert",
    "delete",
    "remove",
    "replace",
    "write back",
    "save as",
    "export",
    "rewrite",
    "split",
    "merge",
)


def get_original_user_content(message: SessionMessage) -> str:
    original = message.metadata.get("original_content")
    if isinstance(original, str):
        return original
    return message.content


def get_multimodal_parse(message: SessionMessage) -> dict[str, Any] | None:
    payload = message.metadata.get("multimodal_parse")
    return payload if isinstance(payload, dict) else None


def get_attachment_analysis(message: SessionMessage) -> dict[str, Any] | None:
    payload = message.metadata.get("attachment_analysis")
    return payload if isinstance(payload, dict) else None


def get_normalized_user_content(message: SessionMessage) -> str:
    attachment_analysis = get_attachment_analysis(message)
    if attachment_analysis and str(attachment_analysis.get("status") or "").strip() in {"completed", "partial"}:
        normalized = attachment_analysis.get("normalized_user_input")
        if isinstance(normalized, str) and normalized.strip():
            return normalized.strip()
    payload = get_multimodal_parse(message)
    if payload and payload.get("status") == "completed":
        normalized = payload.get("normalized_user_input")
        if isinstance(normalized, str) and normalized.strip():
            return normalized.strip()
    return get_original_user_content(message).strip()


def is_attachment_edit_request(content: str | None) -> bool:
    normalized = (content or "").casefold().strip()
    if not normalized:
        return False
    return any(term in normalized for term in _ATTACHMENT_EDIT_TERMS)


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
        return "附件消息"

    original = get_original_user_content(message).strip()
    return original[:24]


def build_user_message_for_provider(message: SessionMessage) -> str:
    payload = get_attachment_analysis(message) or get_multimodal_parse(message)
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
            lines.append(f"- {_attachment_metadata_line(item)}")
        lines.extend(["", "## Attachment Handling", _ATTACHMENT_METADATA_HINT])
        lines.extend(_attachment_handling_hints(original, attachments))

    if not payload:
        return "\n".join(lines)

    status = str(payload.get("status") or "").strip()
    if status in {"completed", "partial"}:
        lines.extend(["", "## Attachment Context", _PARSE_CONTEXT_HINT])
        if is_attachment_edit_request(original):
            lines.append(
                "但如果当前请求是在编辑、增删、写回、改格式，或基于附件生成新的结果文件，"
                "不要把这些解析片段当作已完成任务；应先使用匹配的 skill，解析结果只作为辅助参考。"
            )
        attachment_summaries = _attachment_summaries(payload.get("attachment_summaries"))
        if attachment_summaries:
            lines.extend(["", "## Attachment Observations"])
            if any(isinstance(item, dict) for item in attachment_summaries):
                for summary_item in attachment_summaries:
                    if not isinstance(summary_item, dict):
                        continue
                    label = _attachment_summary_label(summary_item, attachments)
                    summary = str(summary_item.get("summary") or "").strip()
                    markdown_path = str(summary_item.get("markdown_path") or "").strip()
                    if summary:
                        detail = f"- {label}: {summary}"
                        if markdown_path:
                            detail += f" | parsed_markdown={markdown_path}"
                        lines.append(detail)
                    elif isinstance(summary_item.get("analysis_error"), str) and str(summary_item["analysis_error"]).strip():
                        lines.append(f"- {label}: 解析失败，{str(summary_item['analysis_error']).strip()}")
            else:
                for item, summary in zip(attachments, attachment_summaries, strict=False):
                    label = _attachment_label(item) if item is not None else "附件"
                    lines.append(f"- {label}: {summary}")

        parsed_attachment_blocks = _parsed_attachment_blocks(attachment_summaries, attachments)
        if parsed_attachment_blocks:
            lines.extend(["", "## Parsed Attachment Content"])
            lines.extend(parsed_attachment_blocks)

        task_intent = str(payload.get("task_intent") or "").strip()
        key_facts = _string_list(payload.get("key_facts"))
        ocr_text = _string_list(payload.get("ocr_text"))
        uncertainties = _string_list(payload.get("uncertainties"))
        uncertainties.extend(_string_list(payload.get("warnings")))
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


def _attachment_handling_hints(original: str, attachments: list[dict[str, Any]]) -> list[str]:
    if is_attachment_edit_request(original):
        attachment_types = _attachment_skill_labels(attachments)
        if attachment_types:
            return [
                "当前请求是在编辑、补充、写回或生成基于附件的新结果文件。"
                f"已上传附件包含 {attachment_types}，如果会话里有匹配这类附件或任务的 skill，必须先使用 skill，"
                "不要先把 parse_attachment 当作主路径。",
                "只有在 skill 明确需要补充理解现有内容，或当前没有匹配 skill 时，"
                "才把 parse_attachment 当成辅助步骤。"
                "如果需要选附件，优先使用 attachment_id；用户说“第一个附件”时对应 order_index，"
                "说“第一张图/第一个图片附件”时对应 kind=image 且看 kind_index。",
            ]
        return [
            "当前请求是在编辑、补充、写回或生成基于附件的新结果文件。"
            "如果会话里有匹配这类附件或任务的 skill，必须先使用 skill，不要先把 parse_attachment 当作主路径。",
            "只有在 skill 明确需要补充理解现有内容，或当前没有匹配 skill 时，"
            "才把 parse_attachment 当成辅助步骤。"
            "如果需要选附件，优先使用 attachment_id；用户说“第一个附件”时对应 order_index，"
            "说“第一张图/第一个图片附件”时对应 kind=image 且看 kind_index。",
        ]
    return [
        "当任务只是阅读、总结、提取、核对或回答附件现有内容时，优先使用 attachment_id 精确调用 parse_attachment。"
        "如果用户说“第一个附件”，对应 order_index；如果说“第一张图/第一个图片附件”，对应 kind=image 且看 kind_index。",
    ]


def _attachment_skill_labels(attachments: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for item in attachments:
        label = _attachment_skill_label(item)
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return "、".join(labels)


def _attachment_skill_label(item: dict[str, Any]) -> str | None:
    kind = str(item.get("kind") or "").strip().casefold()
    extension = str(item.get("extension") or "").strip().casefold().lstrip(".")
    if kind == "spreadsheet" or extension in {"xls", "xlsx"}:
        return "spreadsheet/excel 附件"
    if kind == "presentation" or extension in {"ppt", "pptx"}:
        return "presentation/ppt 附件"
    if kind == "document" or extension in {"doc", "docx"}:
        return "document/word 附件"
    if kind == "html" or extension in {"html", "htm"}:
        return "html 附件"
    if kind == "json" or extension == "json":
        return "json 附件"
    if kind == "text" or extension in {"md", "txt"}:
        return "text 附件"
    if kind == "image":
        return "image 附件"
    return None


def _attachment_label(item: dict[str, Any]) -> str:
    filename = item.get("filename")
    content_type = item.get("content_type")
    base = str(filename).strip() if isinstance(filename, str) and filename.strip() else "附件"
    if isinstance(content_type, str) and content_type.strip():
        return f"{base} ({content_type.strip()})"
    return base


def _attachment_metadata_line(item: dict[str, Any]) -> str:
    label = _attachment_label(item)
    details: list[str] = []
    attachment_id = str(item.get("attachment_id") or "").strip()
    if attachment_id:
        details.append(f"attachment_id={attachment_id}")
    kind = str(item.get("kind") or "").strip()
    if kind:
        details.append(f"kind={kind}")
    order_index = _coerce_positive_int(item.get("order_index"))
    if order_index is not None:
        details.append(f"order_index={order_index}")
    kind_index = _coerce_positive_int(item.get("kind_index"))
    if kind_index is not None:
        details.append(f"kind_index={kind_index}")
    uploaded_at = str(item.get("uploaded_at") or "").strip()
    if uploaded_at:
        details.append(f"uploaded_at={uploaded_at}")
    size_bytes = _coerce_positive_int(item.get("size_bytes"))
    if size_bytes is not None:
        details.append(f"size_bytes={size_bytes}")
    analysis_status = str(item.get("analysis_status") or "").strip()
    if analysis_status:
        details.append(f"analysis_status={analysis_status}")
    path = str(item.get("path") or "").strip()
    if path:
        details.append(f"path={path}")
    if not details:
        return label
    return f"{label} | " + " | ".join(details)


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


def _attachment_summaries(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return value


def _attachment_summary_label(summary_item: dict[str, Any], attachments: list[dict[str, Any]]) -> str:
    attachment_id = summary_item.get("attachment_id")
    if isinstance(attachment_id, str):
        for item in attachments:
            if item.get("attachment_id") == attachment_id:
                return _attachment_label(item)
    filename = summary_item.get("filename")
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    return "附件"


def _parsed_attachment_blocks(summary_items: list[Any], attachments: list[dict[str, Any]]) -> list[str]:
    if not summary_items:
        return []

    remaining_budget = ATTACHMENT_PROMPT_TOTAL_CHARS
    blocks: list[str] = []
    truncated_any = False

    for summary_item in summary_items:
        if not isinstance(summary_item, dict):
            continue
        markdown_path = summary_item.get("markdown_path")
        if not isinstance(markdown_path, str) or not markdown_path.strip():
            continue
        parsed = _read_parsed_attachment_excerpt(Path(markdown_path), remaining_budget)
        if parsed is None:
            continue
        excerpt, consumed_chars, truncated = parsed
        if not excerpt:
            continue
        label = _attachment_summary_label(summary_item, attachments)
        blocks.extend([f"### {label}", "", excerpt, ""])
        remaining_budget = max(0, remaining_budget - consumed_chars)
        truncated_any = truncated_any or truncated
        if remaining_budget <= 0:
            truncated_any = True
            break

    if not blocks:
        return []
    if truncated_any:
        blocks.insert(0, "以下仅注入适配当前轮上下文预算的附件解析片段。")
        blocks.insert(1, "")
    return blocks


def _read_parsed_attachment_excerpt(path: Path, remaining_budget: int) -> tuple[str, int, bool] | None:
    if remaining_budget <= 0 or not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not content:
        return None
    limit = max(0, min(ATTACHMENT_PROMPT_PER_FILE_CHARS, remaining_budget))
    if limit <= 0:
        return None
    if len(content) <= limit:
        return content, len(content), False
    excerpt = content[: max(limit - 1, 1)].rstrip()
    return f"{excerpt}…", min(len(content), limit), True


def _coerce_positive_int(value: object) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 1 else None
