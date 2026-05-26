from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.attachments.service import (
    ATTACHMENT_PROMPT_PER_FILE_CHARS,
    AttachmentService,
)
from backend.runtime.message_rendering import get_original_user_content
from backend.sessions.models import SessionMessage
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import CORE_TOOL_GROUP
from backend.tools.result import ToolExecutionResult

_ATTACHMENT_KINDS = ["image", "document", "spreadsheet", "presentation", "text", "json", "html"]


class ParseAttachmentTool(BaseTool):
    def __init__(self, context: BuiltinToolContext):
        self.session_store = context.session_store
        self.attachment_service = AttachmentService(context.path_policy.workspace, context.multimodal_analyzer)
        self.meta = ToolMeta(
            name="parse_attachment",
            description=(
                "Parse an uploaded attachment on demand and cache the parsed result for later turns. "
                "Use this when the user asks about an uploaded file's contents. "
                "Prefer attachment_id when the current turn metadata already identifies the target file."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "attachment_id": {
                        "type": "string",
                        "description": "Exact attachment_id from the uploaded attachment metadata.",
                    },
                    "selector": {
                        "type": "object",
                        "properties": {
                            "order_index": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Overall upload order within the current turn, e.g. 1 for the first attachment.",
                            },
                            "kind": {
                                "type": "string",
                                "enum": _ATTACHMENT_KINDS,
                                "description": "Attachment kind, e.g. image, document, spreadsheet.",
                            },
                            "kind_index": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "1-based order within the selected kind, e.g. first image.",
                            },
                            "filename": {
                                "type": "string",
                                "description": "Filename match hint. Exact or substring match is accepted.",
                            },
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
            risk_level="low",
            approval_behavior="safe",
            timeout_seconds=120,
            provider_group=CORE_TOOL_GROUP,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        if self.session_store is None:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="runtime_exception",
                summary="当前运行时未提供 session_store，无法解析附件",
            )

        session = self.session_store.get(session_id)
        selected = self._resolve_target(session, arguments)
        if isinstance(selected, ToolExecutionResult):
            return selected
        user_message, attachment_meta = selected

        attachments = self.attachment_service.restore_many(_attachment_items(user_message))
        target_id = str(attachment_meta.get("attachment_id") or "").strip()
        target_attachment = next((item for item in attachments if item.attachment_id == target_id), None)
        if target_attachment is None:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="validation_error",
                summary="目标附件不存在或元数据已失效",
            )

        turn_id = str(user_message.metadata.get("turn_id") or user_message.id).strip() or user_message.id
        _attachments, attachment_analysis, multimodal_parse, multimodal_failure = await self.attachment_service.parse_selected_attachments(
            get_original_user_content(user_message),
            attachments,
            session_id=session_id,
            turn_id=turn_id,
            target_ids={target_id},
        )
        updated_metadata = dict(user_message.metadata)
        updated_metadata["attachments"] = self.attachment_service.serialize(attachments)
        updated_metadata["attachment_analysis"] = attachment_analysis
        if multimodal_parse is not None:
            updated_metadata["multimodal_parse"] = multimodal_parse

        refreshed = next((item for item in attachments if item.attachment_id == target_id), target_attachment)
        if refreshed.analysis_status != "parsed":
            detail = refreshed.analysis_error
            if not detail and multimodal_failure:
                detail = str(multimodal_failure.get("frontend_message") or "").strip() or None
            summary = f"附件 {refreshed.filename} 解析失败"
            if detail:
                summary = f"{summary}: {detail}"
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="runtime_exception",
                summary=summary,
                stdout=_render_attachment_payload(refreshed, excerpt=""),
                metadata={
                    "session_message_updates": [
                        {
                            "message_id": user_message.id,
                            "content": user_message.content,
                            "metadata": updated_metadata,
                        }
                    ]
                },
            )

        excerpt = _read_excerpt(refreshed.parsed_markdown_path)
        cached = str(attachment_meta.get("analysis_status") or "").strip() == "parsed"
        action = "reuse" if cached else "parse"
        summary = f"已解析附件 {refreshed.filename}" if not cached else f"已返回附件 {refreshed.filename} 的缓存解析结果"
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action=action,
            summary=summary,
            stdout=_render_attachment_payload(refreshed, excerpt=excerpt),
            metadata={
                "session_message_updates": [
                    {
                        "message_id": user_message.id,
                        "content": user_message.content,
                        "metadata": updated_metadata,
                    }
                ]
            },
        )

    def _resolve_target(
        self,
        session,
        arguments: dict[str, Any],
    ) -> tuple[SessionMessage, dict[str, Any]] | ToolExecutionResult:
        attachment_id = str(arguments.get("attachment_id") or "").strip()
        if attachment_id:
            resolved = _find_attachment_by_id(session.messages, attachment_id)
            if resolved is not None:
                return resolved
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="validation_error",
                summary=f"未找到 attachment_id={attachment_id} 对应的附件",
            )

        selector = arguments.get("selector")
        if not isinstance(selector, dict):
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="validation_error",
                summary="parse_attachment 需要 attachment_id 或 selector",
            )

        user_message = _latest_attachment_message(session.messages)
        if user_message is None:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="validation_error",
                summary="当前会话没有可解析的上传附件",
            )
        attachments = _attachment_items(user_message)
        matches = _select_attachments(attachments, selector)
        if not matches:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="validation_error",
                summary=f"没有附件匹配 selector: {_render_selector(selector)}",
            )
        if len(matches) > 1:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="parse",
                category="validation_error",
                summary=f"附件选择不唯一，请改用 attachment_id 或补充 selector: {_render_selector(selector)}",
                stdout=json.dumps(
                    {
                        "status": "ambiguous",
                        "candidates": [_candidate_payload(item) for item in matches],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return user_message, matches[0]


def _attachment_items(message: SessionMessage) -> list[dict[str, Any]]:
    raw = message.metadata.get("attachments")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _latest_attachment_message(messages: list[SessionMessage]) -> SessionMessage | None:
    for message in reversed(messages):
        if message.role != "user":
            continue
        if _attachment_items(message):
            return message
    return None


def _find_attachment_by_id(messages: list[SessionMessage], attachment_id: str) -> tuple[SessionMessage, dict[str, Any]] | None:
    for message in reversed(messages):
        if message.role != "user":
            continue
        for item in _attachment_items(message):
            if str(item.get("attachment_id") or "").strip() == attachment_id:
                return message, item
    return None


def _select_attachments(attachments: list[dict[str, Any]], selector: dict[str, Any]) -> list[dict[str, Any]]:
    matches = list(attachments)
    order_index = _coerce_positive_int(selector.get("order_index"))
    if order_index is not None:
        matches = [item for item in matches if _coerce_positive_int(item.get("order_index")) == order_index]
    kind = str(selector.get("kind") or "").strip()
    if kind:
        matches = [item for item in matches if str(item.get("kind") or "").strip() == kind]
    kind_index = _coerce_positive_int(selector.get("kind_index"))
    if kind_index is not None:
        matches = [item for item in matches if _coerce_positive_int(item.get("kind_index")) == kind_index]
    filename = str(selector.get("filename") or "").strip().casefold()
    if filename:
        matches = [
            item
            for item in matches
            if filename in str(item.get("filename") or "").strip().casefold()
        ]
    return matches


def _coerce_positive_int(value: object) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 1 else None


def _candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "attachment_id": item.get("attachment_id"),
        "filename": item.get("filename"),
        "kind": item.get("kind"),
        "order_index": item.get("order_index"),
        "kind_index": item.get("kind_index"),
        "uploaded_at": item.get("uploaded_at"),
        "analysis_status": item.get("analysis_status"),
    }


def _render_selector(selector: dict[str, Any]) -> str:
    parts: list[str] = []
    order_index = _coerce_positive_int(selector.get("order_index"))
    if order_index is not None:
        parts.append(f"order_index={order_index}")
    kind = str(selector.get("kind") or "").strip()
    if kind:
        parts.append(f"kind={kind}")
    kind_index = _coerce_positive_int(selector.get("kind_index"))
    if kind_index is not None:
        parts.append(f"kind_index={kind_index}")
    filename = str(selector.get("filename") or "").strip()
    if filename:
        parts.append(f"filename~={filename}")
    return ", ".join(parts) or "{}"


def _read_excerpt(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not content:
        return ""
    if len(content) <= ATTACHMENT_PROMPT_PER_FILE_CHARS:
        return content
    return content[: ATTACHMENT_PROMPT_PER_FILE_CHARS - 1].rstrip() + "…"


def _render_attachment_payload(attachment, *, excerpt: str) -> str:
    payload: dict[str, Any] = {
        "attachment_id": attachment.attachment_id,
        "filename": attachment.filename,
        "kind": attachment.kind,
        "uploaded_at": attachment.uploaded_at,
        "order_index": attachment.order_index,
        "kind_index": attachment.kind_index,
        "analysis_status": attachment.analysis_status,
        "summary": attachment.summary,
        "path": str(attachment.path),
    }
    if attachment.parsed_markdown_path is not None:
        payload["parsed_markdown_path"] = str(attachment.parsed_markdown_path)
    if excerpt:
        payload["content_excerpt"] = excerpt
    if attachment.analysis_error:
        payload["analysis_error"] = attachment.analysis_error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    if context.session_store is None or context.multimodal_analyzer is None:
        return []
    return [ParseAttachmentTool(context)]
