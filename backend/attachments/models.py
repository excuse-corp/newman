from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    source: str = "user_upload"
    summary: str = ""
    analysis_status: str = "saved"
    parsed_markdown_path: Path | None = None
    parsed_markdown_relative_path: str | None = None
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
            "summary": self.summary,
            "analysis_status": self.analysis_status,
            "warnings": list(self.warnings),
        }
        if self.parsed_markdown_path is not None:
            payload["parsed_markdown_path"] = str(self.parsed_markdown_path)
        if self.parsed_markdown_relative_path is not None:
            payload["parsed_markdown_relative_path"] = self.parsed_markdown_relative_path
        if self.analysis_error:
            payload["analysis_error"] = self.analysis_error
        return payload


@dataclass(slots=True)
class ParsedAttachment:
    markdown: str
    plain_text: str
    warnings: list[str] = field(default_factory=list)
