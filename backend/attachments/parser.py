from __future__ import annotations

import html
import importlib.util
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from docx import Document as DocxDocument
from docx.document import Document as DocxDocumentType
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from backend.attachments.models import ParsedAttachment

if TYPE_CHECKING:
    from backend.sandbox.native_sandbox import NativeSandbox


MARKDOWN_BYTE_LIMIT = 10 * 1024 * 1024
CHUNK_CHAR_LIMIT = 6_000


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []
        self._pending_break = False

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style"}:
            self._skip_depth += 1
            return
        if normalized in {"p", "div", "section", "article", "header", "footer", "li", "tr", "br"}:
            self._pending_break = True
        if normalized in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._pending_break = True

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if normalized in {"p", "div", "section", "article", "header", "footer", "li", "tr"}:
            self._pending_break = True

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = re.sub(r"\s+", " ", data).strip()
        if not cleaned:
            return
        if self._pending_break and self._chunks and self._chunks[-1] != "\n":
            self._chunks.append("\n")
        self._chunks.append(cleaned)
        self._pending_break = False

    def get_text(self) -> str:
        text = "".join(self._chunks)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_attachment(path: Path, sandbox: "NativeSandbox | None" = None) -> ParsedAttachment:
    suffix = path.suffix.lower()
    if suffix in {".doc", ".xls", ".ppt"}:
        with TemporaryDirectory(prefix="newman-attachment-convert-") as tmp:
            converted = _convert_legacy_office_document(path, Path(tmp), sandbox=sandbox)
            return parse_attachment(converted, sandbox=sandbox)

    if suffix in {".txt", ".md"}:
        return _parse_textual_attachment(path)
    if suffix == ".json":
        return _parse_json_attachment(path)
    if suffix in {".html", ".htm"}:
        return _parse_html_attachment(path)
    if suffix == ".pdf":
        return _parse_pdf_attachment(path)
    if suffix == ".docx":
        return _parse_docx_attachment(path)
    if suffix == ".xlsx":
        return _parse_xlsx_attachment(path)
    if suffix == ".pptx":
        return _parse_pptx_attachment(path)
    raise ValueError(f"暂不支持解析该文件类型: {suffix or '<none>'}")


def _parse_textual_attachment(path: Path) -> ParsedAttachment:
    content = path.read_text(encoding="utf-8", errors="replace").strip()
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
    markdown_lines = [f"# {path.name}", ""]
    plain_lines: list[str] = []
    if path.suffix.lower() == ".md":
        markdown_lines.append(content or "（空内容）")
        plain_lines.append(content)
    else:
        for index, paragraph in enumerate(paragraphs or [content], start=1):
            if not paragraph:
                continue
            markdown_lines.append(f'<!-- loc: {json.dumps({"para": index, "type": "paragraph"}, ensure_ascii=False)} -->')
            markdown_lines.extend([paragraph, ""])
            plain_lines.append(paragraph)
    markdown = "\n".join(markdown_lines).strip() + "\n"
    return _finalize_parsed_attachment(markdown, "\n\n".join(plain_lines))


def _parse_json_attachment(path: Path) -> ParsedAttachment:
    raw_content = path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(raw_content)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        rendered = raw_content
    markdown = f"# {path.name}\n\n```json\n{rendered.strip()}\n```\n"
    return _finalize_parsed_attachment(markdown, rendered)


def _parse_html_attachment(path: Path) -> ParsedAttachment:
    raw_content = path.read_text(encoding="utf-8", errors="replace")
    parser = _VisibleHTMLParser()
    parser.feed(raw_content)
    visible_text = html.unescape(parser.get_text())
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", visible_text) if block.strip()]
    markdown_lines = [f"# {path.name}", ""]
    plain_lines: list[str] = []
    for index, paragraph in enumerate(paragraphs or [visible_text], start=1):
        if not paragraph:
            continue
        markdown_lines.append(f'<!-- loc: {json.dumps({"para": index, "type": "html_text"}, ensure_ascii=False)} -->')
        markdown_lines.extend([paragraph, ""])
        plain_lines.append(paragraph)
    return _finalize_parsed_attachment("\n".join(markdown_lines).strip() + "\n", "\n\n".join(plain_lines))


def _parse_pdf_attachment(path: Path) -> ParsedAttachment:
    if _has_module("fitz"):
        try:
            return _parse_pdf_attachment_with_pymupdf(path)
        except Exception:
            pass

    reader = PdfReader(str(path))
    markdown_lines = [f"# {path.name}", ""]
    html_lines = [f"<h1>{html.escape(path.name)}</h1>"]
    plain_lines: list[str] = []
    blocks: list[dict[str, object]] = []
    warnings: list[str] = []
    nonempty_pages = 0
    for page_index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            blocks.append(
                {
                    "type": "page",
                    "page": page_index,
                    "source": "pypdf",
                    "text": "",
                    "needs_ocr": True,
                }
            )
            continue
        nonempty_pages += 1
        markdown_lines.append(f'<!-- loc: {json.dumps({"page": page_index, "type": "page"}, ensure_ascii=False)} -->')
        markdown_lines.extend([f"## Page {page_index}", "", text, ""])
        html_lines.extend([f'<section data-page="{page_index}">', f"<h2>Page {page_index}</h2>", f"<p>{html.escape(text).replace(chr(10), '<br>')}</p>", "</section>"])
        plain_lines.append(text)
        blocks.append(
            {
                "type": "page",
                "page": page_index,
                "source": "pypdf",
                "text": text,
                "needs_ocr": False,
            }
        )
    if len(reader.pages) > 0 and nonempty_pages * 2 < len(reader.pages):
        warnings.append("PDF 可读文本页占比偏低，可能是扫描件，建议后续补做增强解析。")
    markdown = "\n".join(markdown_lines).strip() + "\n"
    plain_text = "\n\n".join(plain_lines)
    structure = {
        "schema_version": "v1",
        "format": "pdf",
        "filename": path.name,
        "parser": "pypdf",
        "page_count": len(reader.pages),
        "nonempty_pages": nonempty_pages,
        "blocks": blocks,
    }
    return _finalize_parsed_attachment(
        markdown,
        plain_text,
        html="\n".join(html_lines),
        structure=structure,
        chunks=_build_chunks(markdown, blocks),
        warnings=warnings,
    )


def _parse_docx_attachment(path: Path) -> ParsedAttachment:
    document = DocxDocument(path)
    markdown_lines = [f"# {path.name}", ""]
    html_lines = [f"<h1>{html.escape(path.name)}</h1>"]
    plain_lines: list[str] = []
    blocks: list[dict[str, object]] = []
    para_index = 0
    table_index = 0
    list_index = 0
    for block in _iter_docx_blocks(document):
        if isinstance(block, DocxParagraph):
            text = block.text.strip()
            if not text:
                continue
            para_index += 1
            style_name = block.style.name if block.style is not None and block.style.name else ""
            heading_level = _docx_heading_level(style_name)
            list_kind = _docx_list_kind(style_name, block)
            formatted_text = _render_docx_runs_markdown(block)
            html_text = _render_docx_runs_html(block)
            block_type = "heading" if heading_level else "list_item" if list_kind else "paragraph"
            loc = {
                "para": para_index,
                "type": block_type,
                "style": style_name or None,
            }
            if heading_level:
                loc["level"] = heading_level
            if list_kind:
                list_index += 1
                loc["list"] = list_index
                loc["list_kind"] = list_kind
            markdown_lines.append(
                f"<!-- loc: {json.dumps(_clean_mapping(loc), ensure_ascii=False)} -->"
            )
            if heading_level:
                markdown_lines.append(f"{'#' * heading_level} {formatted_text or text}")
                html_lines.append(f"<h{heading_level}>{html_text or html.escape(text)}</h{heading_level}>")
            elif list_kind == "ordered":
                markdown_lines.append(f"1. {formatted_text or text}")
                html_lines.append(f"<ol><li>{html_text or html.escape(text)}</li></ol>")
            elif list_kind == "unordered":
                markdown_lines.append(f"- {formatted_text or text}")
                html_lines.append(f"<ul><li>{html_text or html.escape(text)}</li></ul>")
            else:
                markdown_lines.append(formatted_text or text)
                html_lines.append(f"<p>{html_text or html.escape(text)}</p>")
            markdown_lines.append("")
            plain_lines.append(text)
            blocks.append(
                _clean_mapping(
                    {
                        "type": block_type,
                        "para": para_index,
                        "style": style_name or None,
                        "level": heading_level,
                        "list_kind": list_kind,
                        "text": text,
                        "runs": _docx_run_structure(block),
                    }
                )
            )
            continue
        if isinstance(block, DocxTable):
            table_rows = [[cell.text.strip() for cell in row.cells] for row in block.rows]
            if not any(any(cell for cell in row) for row in table_rows):
                continue
            table_index += 1
            markdown_lines.append(f'<!-- loc: {json.dumps({"table": table_index, "type": "table"}, ensure_ascii=False)} -->')
            markdown_lines.extend(_render_markdown_table(table_rows))
            markdown_lines.append("")
            html_lines.append(_render_html_table(table_rows, table_index))
            plain_lines.append("\n".join(" | ".join(cell for cell in row if cell) for row in table_rows if any(cell for cell in row)))
            blocks.append(
                {
                    "type": "table",
                    "table": table_index,
                    "rows": table_rows,
                }
            )
    markdown = "\n".join(markdown_lines).strip() + "\n"
    structure = {
        "schema_version": "v1",
        "format": "docx",
        "filename": path.name,
        "paragraph_count": para_index,
        "table_count": table_index,
        "blocks": blocks,
    }
    return _finalize_parsed_attachment(
        markdown,
        "\n\n".join(plain_lines),
        html="\n".join(html_lines),
        structure=structure,
        chunks=_build_chunks(markdown, blocks),
    )


def _parse_xlsx_attachment(path: Path) -> ParsedAttachment:
    workbook = load_workbook(path, data_only=True, read_only=True)
    markdown_lines = [f"# {path.name}", ""]
    plain_lines: list[str] = []
    for worksheet in workbook.worksheets:
        if worksheet.sheet_state != "visible":
            continue
        rows: list[list[str]] = []
        for row in worksheet.iter_rows():
            values = [_stringify_excel_cell(cell.value) for cell in row]
            if any(value for value in values):
                rows.append(values)
        if not rows:
            continue
        markdown_lines.append(f'<!-- loc: {json.dumps({"sheet": worksheet.title, "type": "sheet"}, ensure_ascii=False)} -->')
        markdown_lines.extend([f"## Sheet: {worksheet.title}", ""])
        header = ["row"] + [f"col_{index}" for index in range(1, max(len(row) for row in rows) + 1)]
        table_rows = [header]
        for row_index, row_values in enumerate(rows, start=1):
            table_rows.append([str(row_index), *row_values, *[""] * (len(header) - len(row_values) - 1)])
        markdown_lines.extend(_render_markdown_table(table_rows))
        markdown_lines.append("")
        plain_lines.append(f"{worksheet.title}\n" + "\n".join(" | ".join(row) for row in table_rows[1:]))
    return _finalize_parsed_attachment("\n".join(markdown_lines).strip() + "\n", "\n\n".join(plain_lines))


def _parse_pptx_attachment(path: Path) -> ParsedAttachment:
    presentation = Presentation(path)
    markdown_lines = [f"# {path.name}", ""]
    plain_lines: list[str] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        slide_title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.text else f"Slide {slide_index}"
        markdown_lines.append(f'<!-- loc: {json.dumps({"slide": slide_index, "type": "slide"}, ensure_ascii=False)} -->')
        markdown_lines.extend([f"## Slide {slide_index}: {slide_title}", ""])
        plain_parts: list[str] = [slide_title]
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text and text != slide_title:
                    markdown_lines.append(text)
                    markdown_lines.append("")
                    plain_parts.append(text)
            if getattr(shape, "has_table", False):
                rows = [[cell.text.strip() for cell in row.cells] for row in shape.table.rows]
                if any(any(cell for cell in row) for row in rows):
                    markdown_lines.extend(_render_markdown_table(rows))
                    markdown_lines.append("")
                    plain_parts.append("\n".join(" | ".join(cell for cell in row if cell) for row in rows if any(cell for cell in row)))
        notes_text = _read_slide_notes_text(slide)
        if notes_text:
            markdown_lines.append(f'<!-- loc: {json.dumps({"slide": slide_index, "type": "notes"}, ensure_ascii=False)} -->')
            markdown_lines.extend(["### Notes", "", notes_text, ""])
            plain_parts.append(notes_text)
        plain_lines.append("\n".join(part for part in plain_parts if part))
    return _finalize_parsed_attachment("\n".join(markdown_lines).strip() + "\n", "\n\n".join(plain_lines))


def _iter_docx_blocks(document: DocxDocumentType):
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield DocxParagraph(child, document)
        elif tag == "tbl":
            yield DocxTable(child, document)


def _docx_heading_level(style_name: str) -> int | None:
    normalized = style_name.strip().lower()
    if not normalized.startswith("heading"):
        return None
    digits = "".join(char for char in normalized if char.isdigit())
    if not digits:
        return 1
    try:
        return max(1, min(int(digits), 6))
    except ValueError:
        return 1


def _docx_list_kind(style_name: str, paragraph: DocxParagraph) -> str | None:
    normalized = style_name.strip().casefold()
    if "number" in normalized or "编号" in normalized:
        return "ordered"
    if "bullet" in normalized or "list paragraph" in normalized or "项目符号" in normalized:
        return "unordered"
    try:
        paragraph_properties = paragraph._p.pPr
        numbering = paragraph_properties.numPr if paragraph_properties is not None else None
        if numbering is not None:
            return "ordered"
    except Exception:
        return None
    return None


def _docx_run_structure(paragraph: DocxParagraph) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    for run in paragraph.runs:
        text = run.text
        if not text:
            continue
        payload: dict[str, object] = {"text": text}
        if run.bold:
            payload["bold"] = True
        if run.italic:
            payload["italic"] = True
        if run.underline:
            payload["underline"] = True
        if run.style is not None and run.style.name:
            payload["style"] = run.style.name
        runs.append(payload)
    return runs


def _render_docx_runs_markdown(paragraph: DocxParagraph) -> str:
    parts: list[str] = []
    for run in paragraph.runs:
        text = run.text
        if not text:
            continue
        escaped = _escape_markdown_inline(text)
        if run.bold:
            escaped = f"**{escaped}**"
        if run.italic:
            escaped = f"*{escaped}*"
        if run.underline:
            escaped = f"<u>{escaped}</u>"
        parts.append(escaped)
    return "".join(parts).strip()


def _render_docx_runs_html(paragraph: DocxParagraph) -> str:
    parts: list[str] = []
    for run in paragraph.runs:
        text = run.text
        if not text:
            continue
        rendered = html.escape(text)
        if run.bold:
            rendered = f"<strong>{rendered}</strong>"
        if run.italic:
            rendered = f"<em>{rendered}</em>"
        if run.underline:
            rendered = f"<u>{rendered}</u>"
        parts.append(rendered)
    return "".join(parts).strip()


def _escape_markdown_inline(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _render_markdown_table(rows: list[list[str]]) -> list[str]:
    width = max(len(row) for row in rows) if rows else 0
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    if not normalized_rows:
        return []
    header = normalized_rows[0]
    separator = ["---"] * width
    lines = [
        "| " + " | ".join(cell or " " for cell in header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in normalized_rows[1:]:
        lines.append("| " + " | ".join(cell or " " for cell in row) + " |")
    return lines


def _render_html_table(rows: list[list[str]], table_index: int) -> str:
    html_rows: list[str] = [f'<table data-table="{table_index}">']
    for row_index, row in enumerate(rows):
        tag = "th" if row_index == 0 else "td"
        cells = "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in row)
        html_rows.append(f"<tr>{cells}</tr>")
    html_rows.append("</table>")
    return "\n".join(html_rows)


def _parse_pdf_attachment_with_pymupdf(path: Path) -> ParsedAttachment:
    import fitz  # type: ignore[import-not-found]

    document = fitz.open(str(path))
    markdown_lines = [f"# {path.name}", ""]
    html_lines = [f"<h1>{html.escape(path.name)}</h1>"]
    plain_lines: list[str] = []
    blocks: list[dict[str, object]] = []
    warnings: list[str] = []
    nonempty_pages = 0

    for page_index, page in enumerate(document, start=1):
        page_dict = page.get_text("dict")
        page_blocks = page_dict.get("blocks", []) if isinstance(page_dict, dict) else []
        markdown_lines.append(f'<!-- loc: {json.dumps({"page": page_index, "type": "page"}, ensure_ascii=False)} -->')
        markdown_lines.extend([f"## Page {page_index}", ""])
        html_lines.append(f'<section data-page="{page_index}">')
        html_lines.append(f"<h2>Page {page_index}</h2>")
        page_text_parts: list[str] = []
        page_has_text = False

        for block_index, block in enumerate(page_blocks, start=1):
            if not isinstance(block, dict) or block.get("type") != 0:
                continue
            block_text_parts: list[str] = []
            spans_meta: list[dict[str, object]] = []
            font_sizes: list[float] = []
            font_flags: list[int] = []
            for line in block.get("lines", []):
                if not isinstance(line, dict):
                    continue
                line_parts: list[str] = []
                for span in line.get("spans", []):
                    if not isinstance(span, dict):
                        continue
                    span_text = str(span.get("text") or "")
                    if not span_text.strip():
                        continue
                    size = _coerce_float(span.get("size"))
                    flags = _coerce_int(span.get("flags"))
                    if size is not None:
                        font_sizes.append(size)
                    if flags is not None:
                        font_flags.append(flags)
                    line_parts.append(span_text)
                    spans_meta.append(
                        _clean_mapping(
                            {
                                "text": span_text,
                                "font": span.get("font"),
                                "size": size,
                                "flags": flags,
                                "bbox": _normalize_bbox(span.get("bbox")),
                            }
                        )
                    )
                if line_parts:
                    block_text_parts.append("".join(line_parts).strip())
            block_text = "\n".join(part for part in block_text_parts if part).strip()
            if not block_text:
                continue
            page_has_text = True
            bbox = _normalize_bbox(block.get("bbox"))
            max_size = max(font_sizes) if font_sizes else None
            avg_size = sum(font_sizes) / len(font_sizes) if font_sizes else None
            is_heading = bool(max_size and max_size >= 14)
            loc = _clean_mapping(
                {
                    "page": page_index,
                    "block": block_index,
                    "type": "heading" if is_heading else "paragraph",
                    "bbox": bbox,
                    "font_size": round(max_size, 2) if max_size else None,
                    "source": "pymupdf",
                }
            )
            markdown_lines.append(f"<!-- loc: {json.dumps(loc, ensure_ascii=False)} -->")
            if is_heading:
                markdown_lines.append(f"### {block_text}")
                html_lines.append(f"<h3>{html.escape(block_text).replace(chr(10), '<br>')}</h3>")
            else:
                markdown_lines.append(block_text)
                html_lines.append(f"<p>{html.escape(block_text).replace(chr(10), '<br>')}</p>")
            markdown_lines.append("")
            page_text_parts.append(block_text)
            blocks.append(
                _clean_mapping(
                    {
                        "type": "heading" if is_heading else "paragraph",
                        "page": page_index,
                        "block": block_index,
                        "source": "pymupdf",
                        "bbox": bbox,
                        "font_size": round(avg_size, 2) if avg_size else None,
                        "max_font_size": round(max_size, 2) if max_size else None,
                        "text": block_text,
                        "spans": spans_meta,
                        "needs_ocr": False,
                    }
                )
            )
        if page_has_text:
            nonempty_pages += 1
            plain_lines.append("\n".join(page_text_parts))
        else:
            blocks.append(
                {
                    "type": "page",
                    "page": page_index,
                    "source": "pymupdf",
                    "text": "",
                    "needs_ocr": True,
                }
            )
        html_lines.append("</section>")

    if len(document) > 0 and nonempty_pages * 2 < len(document):
        warnings.append("PDF 可读文本页占比偏低，可能是扫描件，建议后续补做 OCR。")
    markdown = "\n".join(markdown_lines).strip() + "\n"
    structure = {
        "schema_version": "v1",
        "format": "pdf",
        "filename": path.name,
        "parser": "pymupdf",
        "page_count": len(document),
        "nonempty_pages": nonempty_pages,
        "blocks": blocks,
    }
    document.close()
    return _finalize_parsed_attachment(
        markdown,
        "\n\n".join(plain_lines),
        html="\n".join(html_lines),
        structure=structure,
        chunks=_build_chunks(markdown, blocks),
        warnings=warnings,
    )


def _stringify_excel_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_slide_notes_text(slide) -> str:
    try:
        if not slide.has_notes_slide:
            return ""
        text = slide.notes_slide.notes_text_frame.text or ""
        return text.strip()
    except Exception:
        return ""


def _convert_legacy_office_document(
    path: Path,
    output_dir: Path,
    *,
    sandbox: "NativeSandbox | None" = None,
) -> Path:
    target_extension = {
        ".doc": "docx",
        ".xls": "xlsx",
        ".ppt": "pptx",
    }[path.suffix.lower()]
    command = [
        "soffice",
        "--headless",
        "--convert-to",
        target_extension,
        "--outdir",
        str(output_dir),
        str(path),
    ]
    try:
        run_command = command
        run_env = None
        run_cwd = str(output_dir)
        if sandbox is not None:
            from backend.sandbox.native_sandbox import SandboxUnavailableError

            try:
                run_command, run_env, prepared_cwd, _sandboxed, _filtered = sandbox.prepare_argv(
                    command,
                    cwd=output_dir,
                    mode="workspace-write",
                    network_access=False,
                    extra_readable_roots=[path.parent],
                    extra_writable_roots=[output_dir],
                )
            except SandboxUnavailableError as exc:
                raise ValueError(f"{path.name} 转换失败：Office 沙箱不可用 ({exc.code})") from exc
            run_cwd = str(prepared_cwd)
        subprocess.run(
            run_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
            timeout=120,
            env=run_env,
            cwd=run_cwd,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"{path.name} 转换失败，无法解析旧版 Office 文件") from exc
    converted = output_dir / f"{path.stem}.{target_extension}"
    if not converted.exists():
        matches = list(output_dir.glob(f"*.{target_extension}"))
        if not matches:
            raise ValueError(f"{path.name} 转换失败，无法找到转换结果")
        converted = matches[0]
    return converted.resolve()


def _build_chunks(markdown: str, blocks: list[dict[str, object]]) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    current_parts: list[str] = []
    current_locs: list[dict[str, object]] = []
    current_len = 0
    block_lookup = _block_lookup_by_text(blocks)

    for raw_block in re.split(r"\n{2,}", markdown.strip()):
        block = raw_block.strip()
        if not block:
            continue
        block_len = len(block)
        if current_parts and current_len + block_len + 2 > CHUNK_CHAR_LIMIT:
            chunks.append(_chunk_payload(len(chunks) + 1, current_parts, current_locs))
            current_parts = []
            current_locs = []
            current_len = 0
        current_parts.append(block)
        current_len += block_len + 2
        loc = _match_block_loc(block, block_lookup)
        if loc:
            current_locs.append(loc)
    if current_parts:
        chunks.append(_chunk_payload(len(chunks) + 1, current_parts, current_locs))
    return chunks


def _chunk_payload(index: int, parts: list[str], locs: list[dict[str, object]]) -> dict[str, object]:
    text = "\n\n".join(parts).strip()
    return {
        "chunk_index": index,
        "char_count": len(text),
        "locations": locs,
        "text": text,
    }


def _block_lookup_by_text(blocks: list[dict[str, object]]) -> list[tuple[str, dict[str, object]]]:
    lookup: list[tuple[str, dict[str, object]]] = []
    for block in blocks:
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        loc = {
            key: value
            for key, value in block.items()
            if key in {"type", "page", "block", "para", "table", "style", "level", "bbox", "source", "needs_ocr"}
        }
        lookup.append((text[:120], _clean_mapping(loc)))
    return lookup


def _match_block_loc(block: str, lookup: list[tuple[str, dict[str, object]]]) -> dict[str, object] | None:
    for text, loc in lookup:
        if text and text in block:
            return loc
    return None


def _clean_mapping(payload: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if value is not None and value != [] and value != {}}


def _normalize_bbox(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    normalized: list[float] = []
    for item in value:
        number = _coerce_float(item)
        if number is None:
            return None
        normalized.append(round(number, 2))
    return normalized


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _finalize_parsed_attachment(
    markdown: str,
    plain_text: str,
    *,
    html: str | None = None,
    structure: dict[str, object] | None = None,
    chunks: list[dict[str, object]] | None = None,
    warnings: list[str] | None = None,
) -> ParsedAttachment:
    normalized_markdown = markdown.strip() + "\n"
    if len(normalized_markdown.encode("utf-8")) > MARKDOWN_BYTE_LIMIT:
        raise ValueError("解析结果过大，当前附件不适合直接注入对话上下文")
    meaningful_text = re.sub(r"\s+", " ", plain_text).strip()
    if len(meaningful_text) < 8:
        raise ValueError("正文抽取不足，当前附件无法形成稳定解析结果")
    return ParsedAttachment(
        markdown=normalized_markdown,
        plain_text=meaningful_text,
        html=html.strip() + "\n" if isinstance(html, str) and html.strip() else None,
        structure=structure,
        chunks=chunks or _build_chunks(normalized_markdown, []),
        warnings=warnings or [],
    )
