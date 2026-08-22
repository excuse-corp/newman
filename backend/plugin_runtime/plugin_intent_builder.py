from __future__ import annotations

import re
import shlex

from .draft_models import PluginCommandSpec, PluginEnvironmentSpec, PluginSkillSpec, PluginSpec
from .plugin_builder import normalize_plugin_name


FIELD_ALIASES = {
    "name": ("plugin name", "插件名称", "插件名", "名称", "name"),
    "version": ("version", "版本"),
    "description": ("description", "描述", "用途", "purpose"),
    "tool_name": ("tool_name", "tool name", "工具名", "工具名称", "tool"),
    "command": ("executable", "command", "cli", "命令", "可执行命令"),
    "readable_roots": ("readable_roots", "readable roots", "读取路径", "只读路径"),
    "writable_roots": ("writable_roots", "writable roots", "写入路径", "可写路径"),
}

CHINESE_NAME_HINTS = {
    "飞书": "lark",
    "审批": "approval",
    "日历": "calendar",
    "会议": "meeting",
    "邮件": "mail",
    "云盘": "drive",
    "文档": "docs",
    "搜索": "search",
    "报告": "report",
    "插件": "plugin",
    "工具": "tool",
}

NAME_STOPWORDS = {
    "create",
    "plugin",
    "skill",
    "tool",
    "with",
    "for",
    "that",
    "this",
    "please",
    "build",
    "make",
    "newman",
}

SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "APP_ID", "APP_SECRET")


def build_plugin_spec_from_intent(intent: str) -> PluginSpec:
    text = intent.strip()
    if len(text) < 8:
        raise ValueError("自然语言需求太短，无法生成插件草稿")

    plugin_name = _derive_plugin_name(text)
    description = _field_value(text, "description") or _summary(text)
    version = _field_value(text, "version") or "0.1.0"
    env_names = _extract_environment_names(text)
    readable_roots = _path_list(_field_value(text, "readable_roots"))
    writable_roots = _path_list(_field_value(text, "writable_roots"))
    command = _build_command(text, plugin_name, env_names, readable_roots, writable_roots)

    skill = PluginSkillSpec(
        name=f"{plugin_name}-workflow",
        description=f"Guidance for {description[:220]}",
        when_to_use=f"Use when the user asks for: {description[:220]}",
        body_markdown=_skill_body(text, description, command is not None),
    )

    return PluginSpec(
        name=plugin_name,
        version=version,
        description=description,
        skills=[skill],
        commands=[command] if command else [],
        environment=[
            PluginEnvironmentSpec(
                name=name,
                required=True,
                secret=any(hint in name for hint in SECRET_ENV_HINTS),
                description=f"Environment variable referenced by {plugin_name}.",
            )
            for name in env_names
        ],
    )


def _derive_plugin_name(text: str) -> str:
    explicit = _field_value(text, "name")
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)

    backtick = re.search(r"`([^`\n]{2,80})`", text)
    if backtick:
        candidates.append(backtick.group(1))

    ascii_words = [
        word.lower()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,30}", text)
        if word.lower() not in NAME_STOPWORDS
    ]
    if ascii_words:
        candidates.append("-".join(ascii_words[:3]))

    hinted = [value for key, value in CHINESE_NAME_HINTS.items() if key in text]
    if hinted:
        candidates.append("-".join(dict.fromkeys(hinted[:3])))

    for candidate in candidates:
        try:
            return normalize_plugin_name(candidate)
        except ValueError:
            continue
    return "custom-plugin"


def _build_command(
    text: str,
    plugin_name: str,
    env_names: list[str],
    readable_roots: list[str],
    writable_roots: list[str],
) -> PluginCommandSpec | None:
    raw_command = _field_value(text, "command")
    if not raw_command:
        return None
    try:
        parts = shlex.split(raw_command)
    except ValueError:
        parts = raw_command.split()
    if not parts:
        return None

    tool_name = _field_value(text, "tool_name") or f"{plugin_name.replace('-', '_')}_cli"
    approval_behavior = "confirmable" if _looks_mutating(text) or writable_roots else "safe"
    return PluginCommandSpec(
        tool_name=_normalize_tool_name(tool_name),
        executable=parts[0],
        description=_summary(text),
        default_args=parts[1:],
        approval_behavior=approval_behavior,
        readonly_prefixes=[],
        readable_roots=readable_roots,
        writable_roots=writable_roots,
        env={name: name for name in env_names},
    )


def _field_value(text: str, field: str) -> str | None:
    aliases = FIELD_ALIASES[field]
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    pattern = re.compile(rf"(?im)^\s*(?:[-*]\s*)?(?:{alias_pattern})\s*[:：=]\s*(.+?)\s*$")
    match = pattern.search(text)
    if not match:
        return None
    return _clean_inline(match.group(1))


def _clean_inline(value: str) -> str:
    cleaned = value.strip().strip("`'\"")
    return re.split(r"\s+#", cleaned, maxsplit=1)[0].strip()


def _summary(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    first = re.split(r"[。.!?]\s*", compact, maxsplit=1)[0].strip()
    return (first or compact)[:500]


def _extract_environment_names(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for name in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text):
        if any(hint in name for hint in SECRET_ENV_HINTS):
            seen[name] = None
    return list(seen)[:32]


def _path_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，]\s*", value) if item.strip()]


def _normalize_tool_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"plugin_{normalized or 'tool'}"
    return normalized[:64]


def _looks_mutating(text: str) -> bool:
    return bool(re.search(r"(?i)\b(write|delete|update|create|modify|apply|send|post|put|patch)\b|写入|删除|修改|创建|发送|更新", text))


def _skill_body(intent: str, description: str, has_command: bool) -> str:
    steps = [
        "Confirm the user's concrete objective and required inputs.",
        "Ask for missing environment variables or credentials by name, never by secret value.",
        "Summarize the completed action and any follow-up needed.",
    ]
    if has_command:
        steps.insert(1, "Use the plugin CLI tool only when the request needs the packaged executable capability.")
    rendered_steps = "".join(f"{index}. {step}\n" for index, step in enumerate(steps, start=1))
    return (
        "# Goal\n\n"
        f"{description}\n\n"
        "# Workflow\n\n"
        f"{rendered_steps}\n"
        "# Source Request\n\n"
        f"{intent.rstrip()}\n"
    )
