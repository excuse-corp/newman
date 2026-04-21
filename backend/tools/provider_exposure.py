from __future__ import annotations

import re

CORE_TOOL_GROUP = "core"
EDITING_TOOL_GROUP = "editing"
EXECUTION_TOOL_GROUP = "execution"
KNOWLEDGE_TOOL_GROUP = "knowledge"
NETWORK_TOOL_GROUP = "network"

DEFAULT_PROVIDER_TOOL_GROUPS = {CORE_TOOL_GROUP}

_EDITING_HINTS = (
    "修改",
    "改一下",
    "编辑",
    "修复",
    "新增",
    "添加",
    "创建",
    "写入",
    "重构",
    "实现",
    "删除",
    "更新",
    "改成",
    "补一个",
    "fix",
    "modify",
    "edit",
    "update",
    "refactor",
    "implement",
    "create",
    "write",
    "patch",
    "rename",
)

_EXECUTION_HINTS = (
    "终端",
    "命令",
    "shell",
    "bash",
    "运行",
    "执行",
    "测试",
    "构建",
    "编译",
    "安装",
    "日志",
    "报错",
    "失败",
    "调试",
    "debug",
    "test",
    "build",
    "compile",
    "stacktrace",
)

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

_COMMAND_WORD_RE = re.compile(r"\b(npm|pnpm|yarn|pytest|python|pip|uv|git|make|docker|node|go|cargo)\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def infer_provider_tool_groups(user_content: str | None) -> set[str]:
    groups = set(DEFAULT_PROVIDER_TOOL_GROUPS)
    if not user_content:
        return groups

    normalized = user_content.casefold()

    if _contains_any(normalized, _EDITING_HINTS):
        groups.add(EDITING_TOOL_GROUP)
        groups.add(EXECUTION_TOOL_GROUP)

    if _contains_any(normalized, _EXECUTION_HINTS) or _COMMAND_WORD_RE.search(user_content):
        groups.add(EXECUTION_TOOL_GROUP)

    if _contains_any(normalized, _KNOWLEDGE_HINTS):
        groups.add(KNOWLEDGE_TOOL_GROUP)

    if _contains_any(normalized, _NETWORK_HINTS) or _URL_RE.search(user_content):
        groups.add(NETWORK_TOOL_GROUP)

    return groups


def _contains_any(text: str, candidates: tuple[str, ...]) -> bool:
    lowered_candidates = (candidate.casefold() for candidate in candidates)
    return any(candidate in text for candidate in lowered_candidates)
