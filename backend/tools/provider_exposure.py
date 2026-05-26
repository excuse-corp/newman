from __future__ import annotations

import re

CORE_TOOL_GROUP = "core"
EDITING_TOOL_GROUP = "editing"
EXECUTION_TOOL_GROUP = "execution"
KNOWLEDGE_TOOL_GROUP = "knowledge"
NETWORK_TOOL_GROUP = "network"

DEFAULT_PROVIDER_TOOL_GROUPS = {CORE_TOOL_GROUP}
DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS = {
    CORE_TOOL_GROUP,
    EDITING_TOOL_GROUP,
    EXECUTION_TOOL_GROUP,
}

_KNOWLEDGE_HINTS = (
    "知识库",
    "文档",
    "资料",
    "手册",
    "wiki",
    "README",
    "readme",
    "PRD",
    "prd",
    "规范",
    "说明书",
)

_NETWORK_HINTS = (
    "联网",
    "搜索",
    "网页",
    "网站",
    "链接",
    "接口",
    "抓取",
    "请求",
    "api",
    "google",
    "search",
    "url",
    "fetch",
    "web",
)
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def infer_provider_tool_groups(user_content: str | None) -> set[str]:
    groups = set(DEFAULT_INTERACTIVE_PROVIDER_TOOL_GROUPS)
    if not user_content:
        return groups

    normalized = user_content.casefold()

    if _contains_any(normalized, _KNOWLEDGE_HINTS):
        groups.add(KNOWLEDGE_TOOL_GROUP)

    if _contains_any(normalized, _NETWORK_HINTS) or _URL_RE.search(user_content):
        groups.add(NETWORK_TOOL_GROUP)

    return groups


def _contains_any(text: str, candidates: tuple[str, ...]) -> bool:
    lowered_candidates = (candidate.casefold() for candidate in candidates)
    return any(candidate in text for candidate in lowered_candidates)
