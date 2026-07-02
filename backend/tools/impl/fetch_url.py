from __future__ import annotations

import json
import importlib.util
import re
from dataclasses import dataclass
from html import unescape as html_unescape
from typing import Any
from urllib.parse import urlparse

import httpx

try:
    from bs4 import BeautifulSoup, Comment
    from bs4.element import Tag
except ImportError:  # pragma: no cover - exercised via runtime import fallback
    BeautifulSoup = None
    Comment = None
    Tag = Any

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
MAX_RESPONSE_CHARS = 14_000
MAX_RESPONSE_BYTES = 2_000_000
MIN_CONTENT_CHARS = 220
NOISE_HINT_RE = re.compile(
    r"(cookie|banner|modal|popup|nav|footer|header|sidebar|share|social|promo|newsletter|signup|subscribe|"
    r"related|recommend|breadcrumb|comment|advert|ads|outbrain|taboola)",
    re.IGNORECASE,
)
CONTENT_HINT_RE = re.compile(r"(article|content|post|story|entry|main|body|text|read)", re.IGNORECASE)
BLOCK_PAGE_RE = re.compile(
    r"(just a moment|attention required|verify you are human|enable javascript and cookies|"
    r"checking if the site connection is secure|access denied|captcha|cf-challenge|cloudflare)",
    re.IGNORECASE,
)
MULTISPACE_RE = re.compile(r"[ \t]+")
THREE_OR_MORE_NEWLINES_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class ExtractedPage:
    requested_url: str
    final_url: str
    canonical_url: str | None
    status_code: int
    content_type: str
    title: str | None
    site_name: str | None
    description: str | None
    published_at: str | None
    extraction_method: str
    text: str
    word_count: int
    text_truncated: bool
    response_truncated: bool
    bytes_downloaded: int


class FetchUrlTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="fetch_url",
            description=(
                "Fetch a URL over HTTP(S), follow redirects, and return the extracted main text of the page "
                "with reduced HTML noise."
            ),
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
            risk_level="medium",
            approval_behavior="safe",
            timeout_seconds=30,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        requested_url = str(arguments["url"]).strip()
        normalized_url = _normalize_url(requested_url)
        if normalized_url is None:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "validation_error",
                summary="url 必须是合法的 http 或 https 地址",
            )

        try:
            async with _build_client(self.meta.timeout_seconds) as client:
                response = await client.get(normalized_url)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "timeout_error",
                summary=f"抓取超时：{normalized_url}",
                retryable=True,
                metadata={"url": normalized_url, "error": str(exc)},
            )
        except httpx.HTTPStatusError as exc:
            return _build_http_status_error_result(self.meta.name, normalized_url, exc.response)
        except httpx.RequestError as exc:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "network_error",
                summary=f"网络请求失败：{normalized_url}（{exc}）",
                retryable=True,
                metadata={"url": normalized_url, "error": str(exc)},
            )
        except httpx.HTTPError as exc:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "network_error",
                summary=f"抓取失败：{normalized_url}（{exc}）",
                retryable=True,
                metadata={"url": normalized_url, "error": str(exc)},
            )

        content_type = response.headers.get("content-type", "").strip()
        raw_bytes = response.content
        response_truncated = len(raw_bytes) > MAX_RESPONSE_BYTES
        if response_truncated:
            raw_bytes = raw_bytes[:MAX_RESPONSE_BYTES]

        if not _is_textual_response(content_type, raw_bytes):
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "validation_error",
                summary=f"目标 URL 返回了不适合直接阅读的内容类型：{content_type or 'unknown'}",
                metadata={
                    "url": normalized_url,
                    "final_url": str(response.url),
                    "content_type": content_type or "unknown",
                    "bytes": len(raw_bytes),
                    "status_code": response.status_code,
                },
            )

        text_body = _decode_response_text(response, raw_bytes)
        final_url = str(response.url)
        final_content_type = content_type or "text/plain"

        if _looks_like_block_page(text_body):
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "network_error",
                summary=f"目标站点返回了验证或拦截页面，无法提取正文：{final_url}",
                retryable=False,
                metadata={
                    "url": normalized_url,
                    "final_url": final_url,
                    "content_type": final_content_type,
                    "bytes": len(raw_bytes),
                    "status_code": response.status_code,
                },
            )

        page = _extract_page(
            requested_url=normalized_url,
            final_url=final_url,
            status_code=response.status_code,
            content_type=final_content_type,
            body=text_body,
            bytes_downloaded=len(raw_bytes),
            response_truncated=response_truncated,
        )
        model_output = _build_model_output(page)
        persisted_output = _build_persisted_output(page)
        page_label = page.title or _display_host(page.final_url)
        return ToolExecutionResult(
            True,
            self.meta.name,
            "fetch",
            summary=f"已提取 {page_label} 的网页正文",
            stdout=model_output,
            metadata={
                "url": normalized_url,
                "final_url": page.final_url,
                "content_type": page.content_type,
                "bytes": page.bytes_downloaded,
                "status_code": page.status_code,
                "title": page.title,
                "site_name": page.site_name,
                "word_count": page.word_count,
                "extraction_method": page.extraction_method,
                "response_truncated": page.response_truncated,
                "text_truncated": page.text_truncated,
            },
            persisted_output=persisted_output,
        )


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [FetchUrlTool()]


def _build_client(timeout_seconds: int | None) -> httpx.AsyncClient:
    timeout = httpx.Timeout(timeout_seconds or 30, connect=10.0)
    return httpx.AsyncClient(
        timeout=timeout,
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
        http2=importlib.util.find_spec("h2") is not None,
    )


def _normalize_url(raw_url: str) -> str | None:
    candidate = raw_url.strip()
    if not candidate:
        return None
    if "://" not in candidate and re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}([/:?#]|$)", candidate):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.geturl()


def _build_http_status_error_result(tool_name: str, requested_url: str, response: httpx.Response) -> ToolExecutionResult:
    status_code = response.status_code
    final_url = str(response.url)
    content_type = response.headers.get("content-type", "").strip() or "unknown"
    retryable = status_code in {408, 409, 425, 429} or status_code >= 500
    category = "network_error"
    if status_code == 404:
        category = "validation_error"
    elif status_code == 429:
        category = "rate_limit_error"
    elif status_code >= 500:
        category = "upstream_error"

    status_label = f"{status_code} {response.reason_phrase}".strip()
    if status_code == 403:
        detail = "目标站点拒绝访问（可能存在 Cloudflare 或其他反爬策略）"
    elif status_code == 404:
        detail = "目标页面不存在"
    elif status_code == 429:
        detail = "目标站点触发了频率限制"
    elif status_code >= 500:
        detail = "目标站点暂时不可用"
    else:
        detail = "目标站点返回了错误状态"

    return ToolExecutionResult(
        False,
        tool_name,
        "fetch",
        category,
        summary=f"{detail}：{status_label}，URL={final_url}",
        retryable=retryable,
        metadata={
            "url": requested_url,
            "final_url": final_url,
            "content_type": content_type,
            "status_code": status_code,
        },
    )


def _is_textual_response(content_type: str, raw_bytes: bytes) -> bool:
    normalized = content_type.lower()
    if not normalized:
        return not _looks_binary(raw_bytes)
    if normalized.startswith("text/"):
        return True
    allowed_prefixes = (
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/rss+xml",
        "application/atom+xml",
    )
    return normalized.startswith(allowed_prefixes)


def _looks_binary(raw_bytes: bytes) -> bool:
    if not raw_bytes:
        return False
    sample = raw_bytes[:2048]
    if b"\x00" in sample:
        return True
    non_text = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return non_text / max(len(sample), 1) > 0.2


def _decode_response_text(response: httpx.Response, raw_bytes: bytes) -> str:
    encodings: list[str] = []
    if response.encoding:
        encodings.append(response.encoding)
    header_content_type = response.headers.get("content-type", "")
    header_match = re.search(r"charset=([A-Za-z0-9._-]+)", header_content_type, re.IGNORECASE)
    if header_match:
        encodings.append(header_match.group(1))
    encodings.extend(["utf-8", "utf-16", "latin-1"])

    seen: set[str] = set()
    for encoding in encodings:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _looks_like_block_page(text: str) -> bool:
    head = text[:4000]
    return bool(BLOCK_PAGE_RE.search(head))


def _extract_page(
    *,
    requested_url: str,
    final_url: str,
    status_code: int,
    content_type: str,
    body: str,
    bytes_downloaded: int,
    response_truncated: bool,
) -> ExtractedPage:
    normalized_type = content_type.lower()
    if "html" not in normalized_type and "xml" not in normalized_type:
        text = _clip_text(_normalize_text(body), MAX_RESPONSE_CHARS)
        return ExtractedPage(
            requested_url=requested_url,
            final_url=final_url,
            canonical_url=None,
            status_code=status_code,
            content_type=content_type,
            title=None,
            site_name=_display_host(final_url),
            description=None,
            published_at=None,
            extraction_method="plain_text",
            text=text,
            word_count=_word_count(text),
            text_truncated=len(_normalize_text(body)) > len(text),
            response_truncated=response_truncated,
            bytes_downloaded=bytes_downloaded,
        )

    if BeautifulSoup is None:
        text = _clip_text(_normalize_text(_strip_html_fallback(body)), MAX_RESPONSE_CHARS)
        return ExtractedPage(
            requested_url=requested_url,
            final_url=final_url,
            canonical_url=None,
            status_code=status_code,
            content_type=content_type,
            title=_extract_title_fallback(body),
            site_name=_display_host(final_url),
            description=None,
            published_at=None,
            extraction_method="html_text_fallback",
            text=text,
            word_count=_word_count(text),
            text_truncated=len(_normalize_text(_strip_html_fallback(body))) > len(text),
            response_truncated=response_truncated,
            bytes_downloaded=bytes_downloaded,
        )

    soup = BeautifulSoup(body, "html.parser")
    title = _first_non_empty(
        _meta_content(soup, property_name="og:title"),
        _meta_content(soup, name="twitter:title"),
        soup.title.get_text(" ", strip=True) if soup.title else None,
        soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None,
    )
    description = _first_non_empty(
        _meta_content(soup, property_name="og:description"),
        _meta_content(soup, name="description"),
        _meta_content(soup, name="twitter:description"),
    )
    site_name = _first_non_empty(
        _meta_content(soup, property_name="og:site_name"),
        _display_host(final_url),
    )
    published_at = _first_non_empty(
        _meta_content(soup, property_name="article:published_time"),
        _meta_content(soup, name="pubdate"),
        _meta_content(soup, name="publishdate"),
        _meta_content(soup, name="date"),
    )
    canonical_url = _extract_canonical_url(soup)

    working = BeautifulSoup(body, "html.parser")
    _remove_noise(working)
    content_root, extraction_method = _pick_content_root(working)
    extracted_text = _normalize_text(content_root.get_text("\n", strip=True))
    if len(extracted_text) < MIN_CONTENT_CHARS:
        fallback_root = working.body or working
        extracted_text = _normalize_text(fallback_root.get_text("\n", strip=True))
        extraction_method = "body_fallback"
    clipped_text = _clip_text(extracted_text, MAX_RESPONSE_CHARS)
    return ExtractedPage(
        requested_url=requested_url,
        final_url=final_url,
        canonical_url=canonical_url,
        status_code=status_code,
        content_type=content_type,
        title=title,
        site_name=site_name,
        description=description,
        published_at=published_at,
        extraction_method=extraction_method,
        text=clipped_text,
        word_count=_word_count(clipped_text),
        text_truncated=len(extracted_text) > len(clipped_text),
        response_truncated=response_truncated,
        bytes_downloaded=bytes_downloaded,
    )


def _meta_content(soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None) -> str | None:
    selector: dict[str, str] = {}
    if property_name:
        selector["property"] = property_name
    if name:
        selector["name"] = name
    tag = soup.find("meta", attrs=selector)
    if tag is None:
        return None
    content = tag.get("content")
    return _clean_inline_text(content)


def _extract_canonical_url(soup: BeautifulSoup) -> str | None:
    tag = soup.find("link", rel=lambda value: isinstance(value, str) and value.lower() == "canonical")
    if tag is None:
        return None
    href = tag.get("href")
    return href.strip() if isinstance(href, str) and href.strip() else None


def _remove_noise(soup: BeautifulSoup) -> None:
    for comment in soup.find_all(string=lambda item: Comment is not None and isinstance(item, Comment)):
        comment.extract()

    for tag_name in ("script", "style", "noscript", "template", "svg", "canvas", "iframe", "form", "button", "input"):
        for node in soup.find_all(tag_name):
            node.decompose()

    for node in soup.find_all(True):
        if node.name in {"nav", "footer", "header", "aside"}:
            node.decompose()
            continue
        marker = " ".join(
            [
                node.get("id", "") if isinstance(node.get("id"), str) else "",
                " ".join(node.get("class", [])) if isinstance(node.get("class"), list) else "",
            ]
        ).strip()
        if marker and NOISE_HINT_RE.search(marker) and not CONTENT_HINT_RE.search(marker):
            node.decompose()
            continue

    for node in list(soup.find_all(["div", "section", "ul", "ol"])):
        text = _normalize_text(node.get_text(" ", strip=True))
        if not text:
            node.decompose()
            continue
        link_text = _normalize_text(" ".join(link.get_text(" ", strip=True) for link in node.find_all("a")))
        if not link_text:
            continue
        link_density = len(link_text) / max(len(text), 1)
        if link_density > 0.6 and len(text) < 1200:
            node.decompose()


def _pick_content_root(soup: BeautifulSoup) -> tuple[Tag, str]:
    article = _longest_useful_tag(soup.find_all("article"))
    if article is not None:
        return article, "article"

    main = _longest_useful_tag(soup.find_all("main"))
    if main is not None:
        return main, "main"

    body = soup.body or soup
    candidates = [body, *body.find_all(["section", "div"], limit=250)]
    scored: list[tuple[int, Tag]] = []
    for candidate in candidates:
        if not isinstance(candidate, Tag):
            continue
        text = _normalize_text(candidate.get_text("\n", strip=True))
        if len(text) < MIN_CONTENT_CHARS:
            continue
        paragraph_count = len(
            [
                node
                for node in candidate.find_all(["p", "li"], recursive=True)
                if len(_normalize_text(node.get_text(" ", strip=True))) >= 40
            ]
        )
        link_text = _normalize_text(" ".join(link.get_text(" ", strip=True) for link in candidate.find_all("a")))
        link_density = len(link_text) / max(len(text), 1)
        marker = " ".join(
            [
                candidate.get("id", "") if isinstance(candidate.get("id"), str) else "",
                " ".join(candidate.get("class", [])) if isinstance(candidate.get("class"), list) else "",
            ]
        )
        bonus = 0
        if candidate.name in {"article", "main"}:
            bonus += 400
        if CONTENT_HINT_RE.search(marker):
            bonus += 300
        score = len(text) + min(paragraph_count, 20) * 120 + bonus - int(link_density * 1000)
        scored.append((score, candidate))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1], "heuristic"
    return body, "body"


def _longest_useful_tag(nodes: list[Tag]) -> Tag | None:
    candidates = []
    for node in nodes:
        text = _normalize_text(node.get_text("\n", strip=True))
        if len(text) >= MIN_CONTENT_CHARS:
            candidates.append((len(text), node))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _clean_inline_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = MULTISPACE_RE.sub(" ", value).strip()
    return cleaned or None


def _normalize_text(value: str) -> str:
    lines = [MULTISPACE_RE.sub(" ", part).strip() for part in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized = "\n".join(line for line in lines if line)
    return THREE_OR_MORE_NEWLINES_RE.sub("\n\n", normalized).strip()


def _clip_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    boundary = value.rfind("\n", 0, limit)
    if boundary < limit * 0.6:
        boundary = value.rfind(" ", 0, limit)
    if boundary < limit * 0.6:
        boundary = limit
    return value[:boundary].rstrip() + "\n\n[正文过长，已截断]"


def _word_count(value: str) -> int:
    return len(re.findall(r"\S+", value))


def _display_host(url: str) -> str:
    host = urlparse(url).netloc
    return host or url


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        cleaned = _clean_inline_text(value)
        if cleaned:
            return cleaned
    return None


def _build_model_output(page: ExtractedPage) -> str:
    lines = [
        f"URL: {page.final_url}",
    ]
    if page.requested_url != page.final_url:
        lines.append(f"Requested URL: {page.requested_url}")
    if page.canonical_url and page.canonical_url != page.final_url:
        lines.append(f"Canonical URL: {page.canonical_url}")
    if page.title:
        lines.append(f"Title: {page.title}")
    if page.site_name:
        lines.append(f"Site: {page.site_name}")
    if page.published_at:
        lines.append(f"Published At: {page.published_at}")
    if page.description:
        lines.append(f"Description: {page.description}")
    lines.extend(
        [
            f"Content Type: {page.content_type}",
            f"Extraction: {page.extraction_method}",
            f"Word Count: {page.word_count}",
            "",
            "Main Text:",
            page.text or "[未提取到可用正文]",
        ]
    )
    if page.response_truncated:
        lines.append("\n[响应体超过大小限制，已截断后再提取]")
    return "\n".join(lines)


def _build_persisted_output(page: ExtractedPage) -> str:
    payload = {
        "summary": "Fetched URL and extracted main text; raw page text omitted from persisted history",
        "url": page.final_url,
        "requestedUrl": page.requested_url,
        "canonicalUrl": page.canonical_url,
        "title": page.title,
        "siteName": page.site_name,
        "publishedAt": page.published_at,
        "description": page.description,
        "contentType": page.content_type,
        "statusCode": page.status_code,
        "wordCount": page.word_count,
        "extractionMethod": page.extraction_method,
        "responseTruncated": page.response_truncated,
        "textTruncated": page.text_truncated,
        "textPersisted": False,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _strip_html_fallback(body: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>", " ", body)
    without_tags = re.sub(r"(?s)<[^>]+>", "\n", without_scripts)
    return html_unescape(without_tags)


def _extract_title_fallback(body: str) -> str | None:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body)
    if not match:
        return None
    return _clean_inline_text(html_unescape(match.group(1)))
