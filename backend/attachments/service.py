from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from uuid import uuid4

from starlette.datastructures import UploadFile

from backend.attachments.models import ParsedAttachment, SavedAttachment
from backend.attachments.parser import parse_attachment
from backend.providers.base import ProviderError


MAX_ATTACHMENTS_PER_TURN = 5
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_SUFFIXES = {".doc", ".docx", ".pdf"}
SPREADSHEET_SUFFIXES = {".xls", ".xlsx"}
PRESENTATION_SUFFIXES = {".ppt", ".pptx"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".html", ".htm"}
ALLOWED_ATTACHMENT_SUFFIXES = IMAGE_SUFFIXES | DOCUMENT_SUFFIXES | SPREADSHEET_SUFFIXES | PRESENTATION_SUFFIXES | TEXT_SUFFIXES
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_SUMMARY_LIMIT = 240
ATTACHMENT_PROMPT_TOTAL_CHARS = 12_000
ATTACHMENT_PROMPT_PER_FILE_CHARS = 4_000


class AttachmentService:
    def __init__(self, workspace_root: Path, multimodal_analyzer) -> None:
        self.workspace_root = workspace_root.resolve()
        self.multimodal_analyzer = multimodal_analyzer

    async def save_uploads(self, session_id: str, turn_id: str, uploads: list[UploadFile]) -> list[SavedAttachment]:
        self._validate_upload_count(uploads)
        originals_dir, _outputs_dir = self._turn_dirs(session_id, turn_id)
        originals_dir.mkdir(parents=True, exist_ok=True)

        saved: list[SavedAttachment] = []
        for upload in uploads:
            filename = _normalize_filename(upload.filename)
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED_ATTACHMENT_SUFFIXES:
                raise ValueError(
                    f"《{filename}》格式不支持。支持图片、Word、Excel、PDF、PPT、MD、TXT、JSON、HTML"
                )
            data = await upload.read()
            if not data:
                raise ValueError(f"《{filename}》为空文件，无法上传")
            if len(data) > MAX_ATTACHMENT_BYTES:
                raise ValueError(f"《{filename}》超过 20MB，无法上传")
            if suffix in IMAGE_SUFFIXES and upload.content_type and upload.content_type not in IMAGE_CONTENT_TYPES:
                raise ValueError(f"《{filename}》图片格式不支持，仅支持 PNG、JPEG、WEBP")
            attachment_id = uuid4().hex
            target = originals_dir / f"{attachment_id}{suffix}"
            target.write_bytes(data)
            content_type = upload.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            saved.append(
                SavedAttachment(
                    attachment_id=attachment_id,
                    kind=_infer_attachment_kind(suffix),
                    filename=filename,
                    extension=suffix,
                    content_type=content_type,
                    size_bytes=len(data),
                    path=target,
                    workspace_relative_path=self._relative_path(target),
                )
            )
        self._write_manifest(session_id, turn_id, saved)
        return saved

    async def analyze_attachments(
        self,
        content: str,
        attachments: list[SavedAttachment],
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[dict[str, object], dict[str, object] | None, dict[str, str] | None]:
        outputs_dir = self._turn_dirs(session_id, turn_id)[1]
        outputs_dir.mkdir(parents=True, exist_ok=True)

        image_attachments = [item for item in attachments if item.extension in IMAGE_SUFFIXES]
        multimodal_parse: dict[str, object] | None = None
        multimodal_failure: dict[str, str] | None = None
        if image_attachments:
            multimodal_parse, multimodal_failure = await self._parse_images(
                content,
                image_attachments,
                outputs_dir,
                session_id=session_id,
                turn_id=turn_id,
            )

        for attachment in attachments:
            if attachment.extension in IMAGE_SUFFIXES:
                continue
            try:
                parsed = parse_attachment(attachment.path)
            except Exception as exc:
                attachment.analysis_status = "failed"
                attachment.summary = f"附件解析失败：{str(exc) or exc.__class__.__name__}"
                attachment.analysis_error = str(exc) or exc.__class__.__name__
                continue
            self._apply_parsed_attachment(attachment, parsed, outputs_dir)

        self._write_manifest(session_id, turn_id, attachments)
        attachment_analysis = self._build_attachment_analysis(content, attachments, multimodal_parse)
        return attachment_analysis, multimodal_parse, multimodal_failure

    def serialize(self, attachments: list[SavedAttachment]) -> list[dict[str, object]]:
        return [item.to_metadata() for item in attachments]

    def build_event_files(self, attachments: list[SavedAttachment]) -> list[dict[str, object]]:
        files: list[dict[str, object]] = []
        for item in attachments:
            payload: dict[str, object] = {
                "attachment_id": item.attachment_id,
                "filename": item.filename,
                "kind": item.kind,
                "extension": item.extension,
                "size_bytes": item.size_bytes,
                "summary": item.summary,
                "analysis_status": item.analysis_status,
            }
            if item.analysis_error:
                payload["analysis_error"] = item.analysis_error
            files.append(payload)
        return files

    def build_failure_warning(self, attachments: list[SavedAttachment]) -> str:
        lines = [
            "## Uploaded Attachments Warning",
            "以下附件解析失败，当前回合不要把它们当作已成功读取的上下文。",
        ]
        for item in attachments:
            if item.analysis_status != "failed":
                continue
            lines.append(f"- {item.filename}: {item.analysis_error or item.summary or '解析失败'}")
        return "\n".join(lines)

    def _apply_parsed_attachment(self, attachment: SavedAttachment, parsed: ParsedAttachment, outputs_dir: Path) -> None:
        markdown_path = outputs_dir / f"{attachment.attachment_id}.md"
        markdown_path.write_text(parsed.markdown, encoding="utf-8")
        attachment.summary = _build_summary(parsed.plain_text)
        attachment.analysis_status = "parsed"
        attachment.parsed_markdown_path = markdown_path
        attachment.parsed_markdown_relative_path = self._relative_path(markdown_path)
        attachment.warnings = list(parsed.warnings)
        attachment.analysis_error = None

    async def _parse_images(
        self,
        content: str,
        attachments: list[SavedAttachment],
        outputs_dir: Path,
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[dict[str, object] | None, dict[str, str] | None]:
        try:
            parsed = await self.multimodal_analyzer.parse_user_input(
                content,
                [item.path for item in attachments],
                session_id=session_id,
                turn_id=turn_id,
            )
        except ProviderError as exc:
            failure = _build_multimodal_failure(exc)
            for item in attachments:
                item.analysis_status = "failed"
                item.summary = f"附件解析失败：{failure['frontend_message']}"
                item.analysis_error = failure["frontend_message"]
            return _build_failed_image_parse(failure), failure
        except Exception as exc:
            failure = _build_multimodal_failure(exc)
            for item in attachments:
                item.analysis_status = "failed"
                item.summary = f"附件解析失败：{failure['frontend_message']}"
                item.analysis_error = failure["frontend_message"]
            return _build_failed_image_parse(failure), failure

        attachment_summaries = parsed.get("attachment_summaries")
        if not isinstance(attachment_summaries, list):
            attachment_summaries = []
        ocr_text = parsed.get("ocr_text")
        if not isinstance(ocr_text, list):
            ocr_text = []
        for index, item in enumerate(attachments):
            summary = ""
            if index < len(attachment_summaries):
                summary = str(attachment_summaries[index]).strip()
            item.summary = summary or "未获得可用图片分析结果。"
            item.analysis_status = "parsed"
            item.analysis_error = None
            markdown_path = outputs_dir / f"{item.attachment_id}.md"
            markdown = _render_image_markdown(item.filename, item.summary, ocr_text)
            markdown_path.write_text(markdown, encoding="utf-8")
            item.parsed_markdown_path = markdown_path
            item.parsed_markdown_relative_path = self._relative_path(markdown_path)
        return parsed, None

    def _build_attachment_analysis(
        self,
        content: str,
        attachments: list[SavedAttachment],
        multimodal_parse: dict[str, object] | None,
    ) -> dict[str, object]:
        completed = [item for item in attachments if item.analysis_status == "parsed"]
        failed = [item for item in attachments if item.analysis_status == "failed"]
        status = "completed"
        if completed and failed:
            status = "partial"
        elif not completed:
            status = "failed"
        normalized = content.strip()
        if not normalized:
            normalized = "请阅读已上传附件并基于附件内容回答用户请求。"
        if multimodal_parse and isinstance(multimodal_parse.get("normalized_user_input"), str):
            image_normalized = str(multimodal_parse.get("normalized_user_input") or "").strip()
            if image_normalized and not content.strip() and len(attachments) == len([item for item in attachments if item.extension in IMAGE_SUFFIXES]):
                normalized = image_normalized
        attachment_summaries = [
            {
                "attachment_id": item.attachment_id,
                "filename": item.filename,
                "kind": item.kind,
                "status": item.analysis_status,
                "summary": item.summary,
                "markdown_path": str(item.parsed_markdown_path) if item.parsed_markdown_path is not None else None,
                "warnings": list(item.warnings),
                "analysis_error": item.analysis_error,
            }
            for item in attachments
        ]
        warnings = [item.analysis_error for item in failed if item.analysis_error]
        warnings.extend(self._build_prompt_budget_warnings(attachments))
        return {
            "schema_version": "v1",
            "status": status,
            "normalized_user_input": normalized,
            "attachment_summaries": attachment_summaries,
            "warnings": warnings,
        }

    def _build_prompt_budget_warnings(self, attachments: list[SavedAttachment]) -> list[str]:
        warnings: list[str] = []
        total_chars = 0
        oversized_files: list[str] = []
        for item in attachments:
            if item.parsed_markdown_path is None or not item.parsed_markdown_path.exists():
                continue
            try:
                content = item.parsed_markdown_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            content_length = len(content)
            total_chars += content_length
            if content_length > ATTACHMENT_PROMPT_PER_FILE_CHARS:
                oversized_files.append(item.filename)
        if oversized_files:
            warnings.append(
                f"以下附件解析内容较长，当前轮仅注入部分片段：{', '.join(oversized_files)}"
            )
        if total_chars > ATTACHMENT_PROMPT_TOTAL_CHARS:
            warnings.append("本轮附件解析总内容超出上下文预算，当前轮仅注入部分片段。")
        return warnings

    def _write_manifest(self, session_id: str, turn_id: str, attachments: list[SavedAttachment]) -> None:
        originals_dir, _outputs_dir = self._turn_dirs(session_id, turn_id)
        manifest_path = originals_dir.parent / "manifest.json"
        manifest = {
            "session_id": session_id,
            "turn_id": turn_id,
            "attachments": [item.to_metadata() for item in attachments],
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _validate_upload_count(self, uploads: list[UploadFile]) -> None:
        if len(uploads) > MAX_ATTACHMENTS_PER_TURN:
            raise ValueError("一次最多上传 5 个附件，请移除多余文件后重试")

    def _turn_dirs(self, session_id: str, turn_id: str) -> tuple[Path, Path]:
        base = self.workspace_root
        originals = base / "user_uploads" / "chat" / session_id / turn_id / "originals"
        outputs = base / "parser_outputs" / "chat" / session_id / turn_id
        return originals, outputs

    def _relative_path(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.workspace_root))


def _normalize_filename(value: str | None) -> str:
    raw = (value or "attachment").strip()
    basename = Path(raw).name
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff ]+", "_", basename).strip(" .")
    return cleaned or "attachment"


def _infer_attachment_kind(suffix: str) -> str:
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in DOCUMENT_SUFFIXES:
        return "document"
    if suffix in SPREADSHEET_SUFFIXES:
        return "spreadsheet"
    if suffix in PRESENTATION_SUFFIXES:
        return "presentation"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".json":
        return "json"
    return "text"


def _build_summary(content: str) -> str:
    cleaned = re.sub(r"\s+", " ", content).strip()
    if not cleaned:
        return "未获得可用解析结果。"
    if len(cleaned) <= _SUMMARY_LIMIT:
        return cleaned
    return f"{cleaned[:_SUMMARY_LIMIT - 1].rstrip()}…"


def _render_image_markdown(filename: str, summary: str, ocr_text: list[object]) -> str:
    lines = [f"# {filename}", "", summary or "未获得可用图片分析结果。", ""]
    normalized_ocr = [str(item).strip() for item in ocr_text if isinstance(item, str) and str(item).strip()]
    if normalized_ocr:
        lines.extend(["## OCR", ""])
        for item in normalized_ocr:
            lines.append(item)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _build_multimodal_failure(exc: Exception) -> dict[str, str]:
    if isinstance(exc, ProviderError):
        category = exc.kind
        detail = exc.message
    else:
        category = "runtime_exception"
        detail = str(exc) or exc.__class__.__name__
    frontend_message = "附件解析超时，已跳过图片内容解析" if category == "timeout_error" else "附件解析失败，已跳过图片内容解析"
    return {
        "category": category,
        "summary": detail,
        "frontend_message": frontend_message,
    }


def _build_failed_image_parse(failure: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": "v1",
        "status": "failed",
        "normalized_user_input": "",
        "task_intent": "",
        "key_facts": [],
        "ocr_text": [],
        "uncertainties": [failure["frontend_message"]],
        "attachment_summaries": [],
        "frontend_message": failure["frontend_message"],
        "summary": failure["summary"],
        "category": failure["category"],
    }
