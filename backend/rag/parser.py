from __future__ import annotations

import csv
import json
import mimetypes
import re
from io import BytesIO, StringIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

from backend.rag.chunker import RawSegment


SUPPORTED_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".py",
    ".yaml",
    ".yml",
    ".log",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".jpg",
    ".jpeg",
    ".png",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def detect_content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def parse_document(path: Path) -> tuple[str, list[RawSegment], int | None]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        segments = _parse_pdf(path)
        return "pdf", segments, len(segments) or None
    if suffix == ".docx":
        segments = _parse_docx(path)
        return "docx", segments, len(segments) or None
    if suffix == ".pptx":
        segments = _parse_pptx(path)
        return "pptx", segments, len(segments) or None
    if suffix == ".xlsx":
        segments = _parse_xlsx(path)
        return "xlsx", segments, len(segments) or None
    if suffix == ".json":
        return "json", _parse_json(path), None
    if suffix == ".csv":
        return "csv", _parse_csv(path), None
    return "text", _parse_text(path), None


def parse_image_summary(summary: str, filename: str) -> list[RawSegment]:
    text = summary.strip()
    if not text:
        return []
    return [
        RawSegment(
            text=f"Image: {filename}\n{text}",
            location_label="image",
            metadata={"filename": filename},
        )
    ]


def _parse_text(path: Path) -> list[RawSegment]:
    content = path.read_text(encoding="utf-8", errors="replace")
    blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
    return [RawSegment(text=block) for block in blocks] or [RawSegment(text=content.strip())]


def _parse_json(path: Path) -> list[RawSegment]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        rendered = path.read_text(encoding="utf-8", errors="replace")
    return _parse_text_from_string(rendered)


def _parse_csv(path: Path) -> list[RawSegment]:
    rows: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for index, row in enumerate(reader, start=1):
            rows.append(f"row {index}: " + " | ".join(cell.strip() for cell in row))
    return _parse_text_from_string("\n".join(rows))


def _parse_pdf(path: Path) -> list[RawSegment]:
    reader = PdfReader(str(path))
    segments: list[RawSegment] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        segments.append(
            RawSegment(
                text=text,
                page_number=page_index,
                location_label=f"page {page_index}",
                metadata={"page_number": page_index},
            )
        )
    return segments


def _parse_docx(path: Path) -> list[RawSegment]:
    with ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}p"):
            texts = [child.text or "" for child in node.iter() if child.tag.endswith("}t")]
            text = "".join(texts).strip()
            if text:
                paragraphs.append(text)
    return [RawSegment(text=paragraph) for paragraph in paragraphs]


def _parse_pptx(path: Path) -> list[RawSegment]:
    with ZipFile(path) as archive:
        slide_names = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        segments: list[RawSegment] = []
        for index, slide_name in enumerate(slide_names, start=1):
            root = ElementTree.fromstring(archive.read(slide_name))
            texts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
            text = "\n".join(part.strip() for part in texts if part and part.strip()).strip()
            if not text:
                continue
            segments.append(
                RawSegment(
                    text=text,
                    page_number=index,
                    location_label=f"slide {index}",
                    metadata={"page_number": index},
                )
            )
    return segments


def _parse_xlsx(path: Path) -> list[RawSegment]:
    with ZipFile(path) as archive:
        shared_strings = _load_shared_strings(archive)
        sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        segments: list[RawSegment] = []
        for index, sheet_name in enumerate(sheet_names, start=1):
            root = ElementTree.fromstring(archive.read(sheet_name))
            rows: list[str] = []
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                values: list[str] = []
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    values.append(_xlsx_cell_value(cell, shared_strings))
                cleaned = " | ".join(value for value in values if value)
                if cleaned:
                    rows.append(cleaned)
            if rows:
                segments.append(
                    RawSegment(
                        text="\n".join(rows),
                        page_number=index,
                        location_label=f"sheet {index}",
                        metadata={"page_number": index},
                    )
                )
    return segments


def _parse_text_from_string(content: str) -> list[RawSegment]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
    return [RawSegment(text=block) for block in blocks] or [RawSegment(text=content.strip())]


def _load_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.iter():
        if item.tag.endswith("}si"):
            strings.append("".join(child.text or "" for child in item.iter() if child.tag.endswith("}t")))
    return strings


def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = next((child for child in cell if child.tag.endswith("}v")), None)
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text.strip()
    if not raw:
        return ""
    if cell_type == "s":
        index = int(raw)
        return shared_strings[index] if 0 <= index < len(shared_strings) else raw
    return raw
