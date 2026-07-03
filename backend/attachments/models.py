from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SavedAttachment:
    attachment_id: str
    kind: str
    filename: str
    extension: str
    content_type: str
    size_bytes: int
    path: Path
    workspace_relative_path: str
    uploaded_at: str = field(default_factory=utc_now)
    order_index: int = 0
    kind_index: int = 0
    source: str = "user_upload"
    summary: str = ""
    analysis_status: str = "saved"
    parsed_markdown_path: Path | None = None
    parsed_markdown_relative_path: str | None = None
    parsed_html_path: Path | None = None
    parsed_html_relative_path: str | None = None
    parsed_structure_path: Path | None = None
    parsed_structure_relative_path: str | None = None
    parsed_chunks_path: Path | None = None
    parsed_chunks_relative_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    analysis_error: str | None = None

    def to_metadata(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "attachment_id": self.attachment_id,
            "source": self.source,
            "kind": self.kind,
            "filename": self.filename,
            "extension": self.extension,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "path": str(self.path),
            "workspace_relative_path": self.workspace_relative_path,
            "uploaded_at": self.uploaded_at,
            "order_index": self.order_index,
            "kind_index": self.kind_index,
            "summary": self.summary,
            "analysis_status": self.analysis_status,
            "warnings": list(self.warnings),
        }
        if self.parsed_markdown_path is not None:
            payload["parsed_markdown_path"] = str(self.parsed_markdown_path)
        if self.parsed_markdown_relative_path is not None:
            payload["parsed_markdown_relative_path"] = self.parsed_markdown_relative_path
        if self.parsed_html_path is not None:
            payload["parsed_html_path"] = str(self.parsed_html_path)
        if self.parsed_html_relative_path is not None:
            payload["parsed_html_relative_path"] = self.parsed_html_relative_path
        if self.parsed_structure_path is not None:
            payload["parsed_structure_path"] = str(self.parsed_structure_path)
        if self.parsed_structure_relative_path is not None:
            payload["parsed_structure_relative_path"] = self.parsed_structure_relative_path
        if self.parsed_chunks_path is not None:
            payload["parsed_chunks_path"] = str(self.parsed_chunks_path)
        if self.parsed_chunks_relative_path is not None:
            payload["parsed_chunks_relative_path"] = self.parsed_chunks_relative_path
        if self.analysis_error:
            payload["analysis_error"] = self.analysis_error
        return payload


@dataclass(slots=True)
class ParsedAttachment:
    markdown: str
    plain_text: str
    html: str | None = None
    structure: dict[str, object] | None = None
    chunks: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
