from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from json import JSONDecodeError
from pathlib import Path
from typing import Awaitable, Callable, Literal
from urllib.parse import unquote, urlparse
from uuid import uuid4

from backend.config.schema import AppConfig
from backend.evolution.service import EvolutionService
from backend.evolution.store import EvolutionStore
from backend.hooks.hook_manager import HookManager
from backend.mcp.registry import MCPRegistry
from backend.memory.checkpoint_store import CheckpointStore
from backend.memory.compressor import (
    build_context_usage_snapshot,
    build_checkpoint_metadata,
    checkpoint_archived_message_count,
    microcompact_session,
    summarize_messages,
)
from backend.memory.memory_extract import MemoryExtractor
from backend.memory.stable_context import StableContextLoader
from backend.plugin_runtime.service import PluginService
from backend.providers.base import ProviderError, ProviderResponse, TokenUsage, ToolCall, ToolCallDelta
from backend.providers.multimodal import MultimodalAnalyzer
from backend.providers.factory import build_provider
from backend.runtime.collaboration_mode import (
    PLAN_COLLABORATION_MODE,
    get_collaboration_mode,
    get_session_plan,
    is_tool_allowed_in_mode,
)
from backend.runtime.environment_context import build_environment_context
from backend.runtime.feedback_writer import FeedbackWriter
from backend.runtime.message_rendering import get_attachment_analysis, get_normalized_user_content, is_attachment_edit_request
from backend.runtime.output_paths import (
    is_within_session_output_dir,
    is_within_turn_output_dir,
    output_root_dir,
    turn_output_dir,
)
from backend.runtime.prompt_assembler import PromptAssembler
from backend.runtime.result_normalizer import normalize_result
from backend.runtime.session_task import SessionTask
from backend.runtime.thinking_parser import ThinkTagStreamParser
from backend.runtime.turn_completion import TurnStepDecision, decide_turn_step
from backend.runtime.thread_manager import ThreadManager
from backend.runtime.workflow_state import (
    AWAITING_USER_INPUT_METADATA_KEY,
    TURN_OUTCOME_ANSWERED,
    TURN_OUTCOME_ARTIFACT_READY,
    TURN_OUTCOME_AWAITING_USER,
    TURN_OUTCOME_BLOCKED,
    TURN_OUTCOME_FAILED,
    TURN_OUTCOME_TASK_COMPLETED,
    WORKFLOW_STATE_METADATA_KEY,
    build_pending_user_input_reply_metadata,
    build_awaiting_user_input_payload,
    build_workflow_state_payload,
    normalize_turn_outcome,
)
from backend.scheduler.task_store import TaskStore
from backend.sessions.models import SessionMessage, utc_now
from backend.sessions.session_store import SessionStore
from backend.skill_runtime.registry import SkillRegistry
from backend.tools.approval import ApprovalManager
from backend.tools.orchestrator import ToolOrchestrator
from backend.tools.approval_policy import DEFAULT_TURN_APPROVAL_MODE, TurnApprovalMode
from backend.tools.discovery import BuiltinToolContext, load_builtin_tools
from backend.tools.permission_context import PermissionContext
from backend.tools.registry import ToolRegistry
from backend.tools.router import ToolRouter, analyze_terminal_command
from backend.tools.result import ToolExecutionResult
from backend.tools.workspace_fs import build_path_access_policy, resolve_requested_path
from backend.sandbox.native_sandbox import NativeSandbox
from backend.sandbox.resource_limits import ResourceLimits
from backend.usage.recorder import ModelRequestContext, record_model_usage
from backend.usage.store import PostgresModelUsageStore


EventEmitter = Callable[[str, dict], Awaitable[None]]


def _format_path_roots(paths) -> list[str]:
    if not paths:
        return ["- none"]
    return [f"- {path}" for path in paths]


def _provider_tool_schema_names(tools: list[dict[str, object]] | None) -> set[str]:
    names: set[str] = set()
    for schema in tools or []:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str) and name:
                names.add(name)
        name = schema.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _is_provider_tool_name_allowed(name: str | None, allowed_tool_names: set[str]) -> bool:
    if not name:
        return False
    return name in allowed_tool_names


def _dedupe_strings(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


COMMON_PROVIDER_REASONING_STATE_FIELDS = (
    "reasoning_content",
    "reasoning",
    "reasoning_text",
    "thinking_content",
    "thinking",
    "thought_content",
    "thoughts",
    "thought",
    "rationale",
)
PROVIDER_REASONING_FIELD_CAPABILITY_KEYS = (
    "response_field",
    "response_fields",
    "replay_field",
    "replay_fields",
    "field",
    "fields",
    "state_field",
    "state_fields",
)
PROVIDER_REASONING_TEXT_VALUE_KEYS = (
    "content",
    "text",
    "reasoning_content",
    "reasoning",
    "reasoning_text",
    "thinking_content",
    "thinking",
    "thought",
    "thoughts",
    "rationale",
)
PROVIDER_REASONING_KEY_RE = re.compile(r"(?:reasoning|think|thought|rationale|chain_of_thought|cot)", re.IGNORECASE)
NON_REASONING_PROVIDER_STATE_KEYS = frozenset({"finish_reason", "stop_reason"})


def _coerce_provider_reasoning_field_names(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        names: list[str] = []
        for item in value:
            if isinstance(item, str):
                names.append(item)
        return names
    return []


def _configured_provider_reasoning_state_fields(provider_config: object | None) -> list[str]:
    capabilities = getattr(provider_config, "capabilities", None)
    if not isinstance(capabilities, dict):
        return []
    reasoning = capabilities.get("reasoning")
    if not isinstance(reasoning, dict):
        return []

    fields: list[str] = []
    for key in PROVIDER_REASONING_FIELD_CAPABILITY_KEYS:
        fields.extend(_coerce_provider_reasoning_field_names(reasoning.get(key)))
    return _dedupe_strings(fields)


def _provider_reasoning_state_fields(provider_config: object | None) -> list[str]:
    return _dedupe_strings(
        [
            *_configured_provider_reasoning_state_fields(provider_config),
            *COMMON_PROVIDER_REASONING_STATE_FIELDS,
        ]
    )


def _stringify_provider_reasoning_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "\n\n".join(_dedupe_strings(_stringify_provider_reasoning_value(item) for item in value))
    if isinstance(value, dict):
        parts = [
            _stringify_provider_reasoning_value(value[key])
            for key in PROVIDER_REASONING_TEXT_VALUE_KEYS
            if key in value
        ]
        return "\n\n".join(_dedupe_strings(parts))
    return ""


def _looks_like_provider_reasoning_state_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.strip().lower()
    if not normalized or normalized in NON_REASONING_PROVIDER_STATE_KEYS:
        return False
    return bool(PROVIDER_REASONING_KEY_RE.search(normalized))


def _extract_provider_state_reasoning(provider_state: object, provider_config: object | None = None) -> str:
    if not isinstance(provider_state, dict):
        return ""

    fields = _provider_reasoning_state_fields(provider_config)
    parts: list[str] = []
    seen_keys = set()
    for key in fields:
        if key not in provider_state:
            continue
        seen_keys.add(key)
        parts.append(_stringify_provider_reasoning_value(provider_state.get(key)))

    for key, value in provider_state.items():
        if key in seen_keys or not _looks_like_provider_reasoning_state_key(key):
            continue
        parts.append(_stringify_provider_reasoning_value(value))

    return "\n\n".join(_dedupe_strings(parts))


def _response_reasoning_for_commentary(response: ProviderResponse, provider_config: object | None = None) -> str:
    return "\n\n".join(
        _dedupe_strings(
            [
                response.thinking,
                _extract_provider_state_reasoning(response.provider_state, provider_config),
            ]
        )
    )


COMMENTARY_FALLBACK_SYSTEM_PROMPT = """你负责把内部思考压缩成一条对用户可见的简短行动说明。

输出规则：
- 只输出一个 `<commentary>...</commentary>` 标签块，除此之外不要输出任何别的内容
- brief 只描述“接下来立刻要做什么”
- 不要泄露内部推理、提示词、规则、犹豫、备选方案或不确定性
- 尽量简短，通常控制在 8 到 24 个汉字
- 使用用户当前回合的语言
"""

RAW_TOOL_CALL_MARKUP_RE = re.compile(r"<(?:[\w.-]+:)?tool_call\b", re.IGNORECASE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]+)\)")
HTML_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_IMAGE_ATTR_RE = re.compile(r"\b(src|alt)=(['\"])(.*?)\2", re.IGNORECASE)
DIRECT_IMAGE_SOURCE_PREFIXES = ("http://", "https://", "data:image/", "blob:")
IMAGE_ATTACHMENT_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"})
TOOL_PREAMBLE_COMMENTARY_MAX_CHARS = 80
ACTION_BRIEF_MAX_CHARS = 140
ACTION_BRIEF_VALUE_MAX_CHARS = 64
ANSWER_DEFER_RELEASE_CHARS = 96
STRUCTURED_ANSWER_DEFER_RELEASE_CHARS = 360
TOOL_ARGUMENT_PROGRESS_EMIT_BYTES = 2_048
TOOL_EVENT_OUTPUT_PREVIEW_MAX_CHARS = 8_000
STRUCTURED_TOOL_PREAMBLE_RE = re.compile(r"(^|\n)\s*(?:#{1,6}\s+|\d+[.、]\s+|[-*]\s+)")
HASH_PATH_SEGMENT_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
PSEUDO_TOOL_NAMES = frozenset({"commentary", "thinking", "think"})
PLAN_TOOL_NAMES = frozenset({"enter_plan_mode", "update_plan"})
MAX_INVALID_TOOL_CALL_RECOVERY_ATTEMPTS = 1
PLAN_TOOL_INVALID_CALL_RECOVERY_ATTEMPTS = 2
ATTACHMENT_FIRST_REPLY_BLOCKED_TOOLS = frozenset(
    {
        "read_file",
        "read_file_range",
        "list_dir",
        "list_files",
        "search_files",
        "grep",
    }
)


def _build_tool_message_output(result: ToolExecutionResult) -> str:
    if result.tool != "terminal":
        return result.stdout

    outputs = [part for part in [result.stdout.strip(), result.stderr.strip()] if part]
    return "\n".join(outputs)


def _compact_tool_event_output_preview(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= TOOL_EVENT_OUTPUT_PREVIEW_MAX_CHARS:
        return normalized
    return (
        normalized[:TOOL_EVENT_OUTPUT_PREVIEW_MAX_CHARS].rstrip()
        + "\n\n... 输出较长，已截断预览。"
    )


def _build_tool_event_output_preview(result: ToolExecutionResult) -> str:
    for candidate in (result.frontend_message, result.summary):
        if candidate and candidate.strip():
            return _compact_tool_event_output_preview(candidate)
    return _compact_tool_event_output_preview(_build_tool_message_output(result))


def _format_compact_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def _build_tool_argument_progress_summary(tool_name: str | None, argument_bytes: int) -> str:
    tool_label = tool_name or "工具"
    if argument_bytes > 0:
        return f"正在准备 {tool_label} 调用参数（{_format_compact_bytes(argument_bytes)}）"
    return f"正在准备 {tool_label} 调用参数"


def _compact_action_brief(text: str, max_chars: int = ACTION_BRIEF_MAX_CHARS) -> str:
    normalized = " ".join(text.replace("\n", " ").split()).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1]}…"


def _compact_action_value(value: object, max_chars: int = ACTION_BRIEF_VALUE_MAX_CHARS) -> str:
    normalized = " ".join(str(value).replace("\n", " ").split()).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1]}…"


def _read_action_argument(arguments: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _format_action_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    normalized = raw_path.strip()
    if not normalized:
        return None
    if len(normalized) <= ACTION_BRIEF_VALUE_MAX_CHARS:
        return normalized
    path = Path(normalized)
    parts = [part for part in path.parts if part not in {path.anchor, "/"}]
    if len(parts) >= 3:
        return f"…/{'/'.join(parts[-3:])}"
    if len(parts) >= 1:
        return f"…/{'/'.join(parts)}"
    return _compact_action_value(normalized)


def _is_hash_path_segment(value: str) -> bool:
    stem = Path(value).stem
    return bool(HASH_PATH_SEGMENT_RE.match(stem))


def _format_internal_action_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    normalized = raw_path.strip().replace("\\", "/")
    if not normalized:
        return None
    if "/parser_outputs/chat/" in f"/{normalized}":
        return "匹配到的解析文档"
    if "/user_uploads/chat/" in f"/{normalized}":
        return "上传附件"

    parts = [part for part in normalized.split("/") if part and part != "."]
    if len(parts) >= 2 and _is_hash_path_segment(parts[-1]) and any(_is_hash_path_segment(part) for part in parts[:-1]):
        return "内部生成文档"
    return None


def _attachment_label_for_action_path(task: SessionTask, raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    target = raw_path.strip()
    if not target:
        return None
    current_turn = task.session.messages[-1] if task.session.messages else None
    for message in reversed(task.session.messages):
        if message.role != "user":
            continue
        if task.turn_id and message.metadata.get("turn_id") != task.turn_id:
            continue
        current_turn = message
        break
    attachments = current_turn.metadata.get("attachments") if current_turn is not None else None
    if not isinstance(attachments, list):
        return None
    for item in attachments:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            continue
        candidates = (
            item.get("path"),
            item.get("workspace_relative_path"),
            item.get("parsed_markdown_path"),
            item.get("parsed_markdown_relative_path"),
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip() == target:
                if candidate == item.get("parsed_markdown_path") or candidate == item.get("parsed_markdown_relative_path"):
                    return f"上传附件「{_compact_action_value(filename, 36)}」的解析结果"
                return f"上传附件「{_compact_action_value(filename, 36)}」"
    return None


def _format_action_path_for_task(raw_path: str | None, task: SessionTask) -> str | None:
    return _attachment_label_for_action_path(task, raw_path) or _format_internal_action_path(raw_path) or _format_action_path(raw_path)


def _format_action_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    normalized = raw_url.strip()
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.netloc:
        path = parsed.path.rstrip("/")
        suffix = ""
        if path and path != "/":
            suffix = _compact_action_value(path, 32)
        return f"{parsed.netloc}{suffix}"
    return _compact_action_value(normalized)


def _brief_prefix_for_task(task: SessionTask) -> str:
    return "我继续" if task.tool_depth > 0 else "我先"


def _build_single_tool_action_brief(tool_call: ToolCall, prefix: str, task: SessionTask) -> str:
    tool_name = tool_call.name
    arguments = tool_call.arguments

    if tool_name == "google_search":
        query = _read_action_argument(arguments, "q", "query")
        if query:
            return f"{prefix}搜索「{_compact_action_value(query)}」相关资料，确认可引用的信息来源。"
        return f"{prefix}搜索相关网页资料，确认可引用的信息来源。"

    if tool_name in {"search_files", "grep"}:
        query = _read_action_argument(arguments, "query", "pattern")
        path = _format_action_path_for_task(_read_action_argument(arguments, "path"), task)
        if query and path and path != ".":
            return f"{prefix}在 {path} 中检索「{_compact_action_value(query)}」，定位相关代码。"
        if query:
            return f"{prefix}在项目里检索「{_compact_action_value(query)}」，定位相关代码。"
        return f"{prefix}检索项目内容，定位相关线索。"

    if tool_name in {"read_file", "read_file_range"}:
        path = _format_action_path_for_task(_read_action_argument(arguments, "path"), task)
        if path:
            return f"{prefix}读取 {path}，确认里面的相关信息。"
        return f"{prefix}读取相关文件，确认里面的可用信息。"

    if tool_name in {"list_dir", "list_files"}:
        path = _format_action_path_for_task(_read_action_argument(arguments, "path"), task) or "当前目录"
        return f"{prefix}查看 {path} 的结构，确认下一步该读哪些内容。"

    if tool_name == "fetch_url":
        target = _format_action_url(_read_action_argument(arguments, "url"))
        if target:
            return f"{prefix}打开 {target} 的网页资料，确认其中可用信息。"
        return f"{prefix}打开网页资料，确认其中可用信息。"

    if tool_name == "terminal":
        command = _read_action_argument(arguments, "command")
        if command:
            return f"{prefix}运行命令「{_compact_action_value(command)}」，确认当前状态。"
        return f"{prefix}运行命令，确认当前状态。"

    if tool_name == "write_file":
        path = _format_action_path_for_task(_read_action_argument(arguments, "path"), task)
        if path:
            return f"{prefix}生成 {path}，把当前结果落到文件里。"
        return f"{prefix}生成对应文件，把当前结果落下来。"

    if tool_name == "edit_file":
        path = _format_action_path_for_task(_read_action_argument(arguments, "path"), task)
        if path:
            return f"{prefix}修改 {path}，把实现调整到目标状态。"
        return f"{prefix}修改对应文件，把实现调整到目标状态。"

    if tool_name == "update_plan":
        return f"{prefix}把已知信息拆成执行步骤，便于按阶段推进。"

    if tool_name == "enter_plan_mode":
        return f"{prefix}更新当前协作流程，确保后续步骤可追踪。"

    return f"{prefix}调用 {tool_name}，获取完成这一步需要的信息。"


def _build_multi_tool_action_brief(tool_calls: list[ToolCall], prefix: str) -> str:
    tool_names = [tool_call.name for tool_call in tool_calls]
    unique_tool_names = list(dict.fromkeys(tool_names))
    if unique_tool_names == ["google_search"]:
        queries = [
            query
            for tool_call in tool_calls
            if (query := _read_action_argument(tool_call.arguments, "q", "query")) is not None
        ]
        if len(queries) >= 2:
            return f"{prefix}用多个关键词搜索公开资料，交叉确认可引用的信息来源。"
        return f"{prefix}并行搜索公开资料，确认可引用的信息来源。"
    if len(unique_tool_names) <= 2:
        labels = " 和 ".join(unique_tool_names)
    else:
        labels = f"{unique_tool_names[0]} 等 {len(unique_tool_names)} 个工具"
    return f"{prefix}并行调用 {labels}，收集完成判断需要的信息。"


def _normalize_markdown_image_destination(raw_destination: str) -> str | None:
    destination = raw_destination.strip()
    if not destination:
        return None
    if destination.startswith("<"):
        closing_index = destination.find(">")
        if closing_index != -1:
            return destination[1:closing_index].strip() or None
    if " " in destination and not destination.startswith("data:image/"):
        destination = destination.split(" ", 1)[0].strip()
    return destination or None


def _extract_assistant_image_references(content: str) -> list[tuple[str, str | None]]:
    references: list[tuple[str, str | None]] = []
    for alt_text, raw_destination in MARKDOWN_IMAGE_RE.findall(content):
        destination = _normalize_markdown_image_destination(raw_destination)
        if destination:
            references.append((destination, alt_text.strip() or None))

    for tag_match in HTML_IMAGE_TAG_RE.finditer(content):
        attributes = {
            name.lower(): value.strip()
            for name, _quote, value in HTML_IMAGE_ATTR_RE.findall(tag_match.group(0))
            if value.strip()
        }
        source = attributes.get("src")
        if source:
            references.append((source, attributes.get("alt") or None))
    return references


def _repair_schema_value(value: object, schema: object) -> object:
    if not isinstance(schema, dict):
        return value

    schema_type = schema.get("type")
    if schema_type == "object" or (
        not schema_type and any(key in schema for key in ("properties", "required", "additionalProperties"))
    ):
        source = value if isinstance(value, dict) else {}
        properties = schema.get("properties")
        known_properties = properties if isinstance(properties, dict) else {}
        repaired: dict[str, object] = {}

        if schema.get("additionalProperties") is not False:
            for key, item in source.items():
                if key not in known_properties:
                    repaired[key] = item

        for key, child_schema in known_properties.items():
            if key in source:
                repaired[key] = _repair_schema_value(source[key], child_schema)

        for key in schema.get("required", []):
            if not isinstance(key, str) or key in repaired:
                continue
            repaired[key] = _schema_placeholder(known_properties.get(key, {}))
        return repaired

    if schema_type == "array":
        items_schema = schema.get("items")
        source_items = value if isinstance(value, list) else []
        repaired_items = [
            _repair_schema_value(item, items_schema) if isinstance(items_schema, dict) else item
            for item in source_items
        ]
        min_items = schema.get("minItems")
        if isinstance(min_items, int):
            while len(repaired_items) < min_items:
                repaired_items.append(_schema_placeholder(items_schema if isinstance(items_schema, dict) else {}))
        return repaired_items

    if schema_type == "string":
        if isinstance(value, str):
            min_length = schema.get("minLength")
            if isinstance(min_length, int) and len(value) < min_length:
                return "x" * min_length
            enum_values = schema.get("enum")
            if isinstance(enum_values, list) and enum_values and value not in enum_values:
                first = enum_values[0]
                return str(first) if isinstance(first, str) else value
            return value
        return _schema_placeholder(schema)

    if schema_type == "boolean":
        return value if isinstance(value, bool) else bool(schema.get("default", False))

    if schema_type == "integer":
        return value if isinstance(value, int) and not isinstance(value, bool) else int(schema.get("default", 0) or 0)

    if schema_type == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        default = schema.get("default", 0)
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            return default
        return 0

    return value


def _schema_placeholder(schema: object) -> object:
    if not isinstance(schema, dict):
        return ""

    default = schema.get("default")
    if default is not None:
        return default

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    schema_type = schema.get("type")
    if schema_type == "object":
        return _repair_schema_value({}, schema)
    if schema_type == "array":
        min_items = schema.get("minItems")
        items_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        required_count = min_items if isinstance(min_items, int) and min_items > 0 else 0
        return [_schema_placeholder(items_schema) for _ in range(required_count)]
    if schema_type == "boolean":
        return False
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0
    if schema_type == "null":
        return None

    min_length = schema.get("minLength")
    if isinstance(min_length, int) and min_length > 0:
        return "x" * min_length
    return ""


class NewmanRuntime:
    def __init__(self, settings: AppConfig):
        self.settings = settings
        self.provider = build_provider(settings.provider)
        self.usage_store = PostgresModelUsageStore(settings.postgres_dsn)
        self.multimodal_analyzer = MultimodalAnalyzer(settings.models.multimodal, self.usage_store)
        self.session_store = SessionStore(settings.paths.sessions_dir)
        self.thread_manager = ThreadManager(self.session_store)
        self.checkpoints = CheckpointStore(settings.paths.sessions_dir)
        self.memory_extractor = MemoryExtractor(
            self.provider,
            settings.provider,
            settings.provider.type,
            self.session_store,
            self.checkpoints,
            settings.paths.memory_dir / "USER.md",
            Path(__file__).resolve().parents[1] / "config" / "prompts" / "mem_extract.md",
            self.usage_store,
        )
        self._background_tasks: set[asyncio.Task] = set()
        self._evolution_sessions_in_progress: set[str] = set()
        self.stable_context = StableContextLoader(settings.paths.memory_dir)
        self.prompt_assembler = PromptAssembler(self.stable_context)
        self.feedback_writer = FeedbackWriter()
        self.approvals = ApprovalManager()
        self.plugin_service = PluginService(
            settings.paths.plugins_dir,
            settings.paths.skills_dir,
            settings.paths.data_dir / "plugin_state.json",
        )
        self.skill_registry = SkillRegistry(self.plugin_service, settings.paths.memory_dir)
        self.evolution_store = EvolutionStore(settings.paths.evolution_dir)
        self.hook_manager = HookManager(self.plugin_service)
        self.mcp_registry = MCPRegistry(settings.paths.mcp_dir / "servers.yaml", workspace=settings.paths.workspace)
        self.scheduler_store = TaskStore(settings.paths.scheduler_dir / "tasks.json")
        self.registry = ToolRegistry()
        self.router = ToolRouter(self.registry, settings)
        self.orchestrator = ToolOrchestrator(settings, self.approvals)
        self.exec_sandbox: NativeSandbox | None = None
        self.evolution_service = EvolutionService(
            settings=settings,
            provider=self.provider,
            model_config=settings.provider,
            provider_type=settings.provider.type,
            session_store=self.session_store,
            checkpoints=self.checkpoints,
            plugin_service=self.plugin_service,
            skill_registry=self.skill_registry,
            store=self.evolution_store,
            reload_ecosystem=self.reload_ecosystem,
            usage_store=self.usage_store,
        )
        self.reload_ecosystem()

    def close(self) -> None:
        self.mcp_registry.close()

    def reload_ecosystem(self) -> None:
        self.plugin_service.reload()
        self.skill_registry.sync_snapshot()
        self.registry = self._build_registry(self.settings.paths.workspace)
        self.router = ToolRouter(self.registry, self.settings)
        self.registry.sync_tool_snapshot(
            spec_dir=self.settings.paths.data_dir / "tool_specs",
            memory_dir=self.settings.paths.memory_dir,
            permission_context=PermissionContext(),
        )

    def _pending_user_input_reply_metadata(self, session_id: str) -> dict[str, object] | None:
        try:
            session = self.session_store.get(session_id)
        except Exception:
            return None
        return build_pending_user_input_reply_metadata(session)

    def _tools_overview(self, task: SessionTask | None = None) -> str:
        sections = []
        workspace = self._workspace_access_overview(task) if task is not None else self._workspace_access_overview()
        if workspace:
            sections.append(workspace)
        resource_overview = self.mcp_registry.describe_resources()
        if resource_overview:
            sections.append(f"## MCP Resources\n{resource_overview}")
        return "\n\n".join(sections)

    def _resolve_tools_overview(self, task: SessionTask | None = None) -> str:
        try:
            return self._tools_overview(task)
        except TypeError:
            return self._tools_overview()

    def _visible_tools_overview(
        self,
        provider_tools: list[dict[str, object]],
        task: SessionTask | None = None,
    ) -> str:
        sections: list[str] = []
        tool_lines: list[str] = []
        for schema in provider_tools:
            if not isinstance(schema, dict):
                continue
            function = schema.get("function")
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            description = function.get("description")
            if isinstance(description, str) and description.strip():
                tool_lines.append(f"- {name}: {description.strip()}")
            else:
                tool_lines.append(f"- {name}")
        if tool_lines:
            sections.append("## Tooling Overview\n" + "\n".join(tool_lines))
        workspace = self._workspace_access_overview(task) if task is not None else self._workspace_access_overview()
        if workspace:
            sections.append(workspace)
        resource_overview = self.mcp_registry.describe_resources()
        if resource_overview:
            sections.append(f"## MCP Resources\n{resource_overview}")
        return "\n\n".join(sections)

    def _workspace_access_overview(self, task: SessionTask | None = None) -> str:
        policy = build_path_access_policy(self.settings)
        output_root = output_root_dir(policy.workspace)
        current_output_dir = self._current_turn_output_dir(task) if task is not None else None
        paths = getattr(self.settings, "paths", None)
        raw_data_dir = getattr(paths, "data_dir", policy.workspace.parent / "backend_data")
        data_dir = raw_data_dir if isinstance(raw_data_dir, Path) else Path(str(raw_data_dir))
        raw_audit_dir = getattr(paths, "audit_dir", data_dir / "audit")
        audit_dir = raw_audit_dir if isinstance(raw_audit_dir, Path) else Path(str(raw_audit_dir))
        output_lines = [f"Per-turn output root for user deliverables: {output_root}"]
        if current_output_dir is not None:
            output_lines.append(f"Current turn output directory for user deliverables: {current_output_dir}")
        else:
            output_lines.append(
                "Current turn output directory pattern for user deliverables: "
                f"{output_root / '{session_id}' / '{turn_id}'}"
            )
        return "\n".join(
            [
                "## Workspace Access",
                f"Runtime workspace (primary operation space): {policy.workspace}",
                *output_lines,
                "",
                "Runtime logs (read-only when permitted by configuration):",
                f"- Backend log: {data_dir / 'run' / 'logs' / 'backend.log'}",
                f"- Frontend log: {data_dir / 'run' / 'logs' / 'frontend.log'}",
                "",
                "Session audit logs are readable when permitted by configuration:",
                f"- {audit_dir / '{session_id}.log'}",
                "",
                "Writable roots:",
                *_format_path_roots(policy.writable_roots),
                "",
                "Readable roots:",
                *_format_path_roots(policy.readable_roots),
                "",
                "Protected roots (do not read or write; these override readable and writable roots):",
                *_format_path_roots(policy.protected_roots),
                "",
                "When creating user-facing files, write them under the current turn output directory unless the user asks for a different path. "
                "Only place final deliverables there; keep helper scripts and intermediate files elsewhere in the workspace. "
                "Use a path relative to the runtime workspace when the target is inside it. "
                "Project maintenance roots such as memory, skills, plugins, or tools are only for their specific maintenance tasks.",
            ]
        )

    def _current_turn_output_dir(self, task: SessionTask | None) -> Path | None:
        if task is None or not task.turn_id:
            return None
        return turn_output_dir(self.settings.paths.workspace, task.session.session_id, task.turn_id)

    def schedule_previous_session_extraction(self, exclude_session_id: str) -> dict[str, object]:
        return self.schedule_previous_session_evolution(exclude_session_id)

    def schedule_previous_session_evolution(self, exclude_session_id: str) -> dict[str, object]:
        previous = self.session_store.latest(exclude_session_ids={exclude_session_id}, require_messages=True)
        if previous is None:
            return {
                "scheduled": False,
                "trigger": "new_session_created",
                "source_session_id": None,
                "reason": "no_previous_session",
            }
        return self.schedule_evolution(previous.session_id, "new_session_created")

    def schedule_turn_interval_evolution(self, session_id: str) -> dict[str, object]:
        evolution_service = getattr(self, "evolution_service", None)
        if evolution_service is None:
            return {
                "scheduled": False,
                "trigger": "turn_interval",
                "source_session_id": session_id,
                "reason": "evolution_service_unavailable",
            }
        try:
            session = self.session_store.get(session_id)
        except FileNotFoundError:
            return {
                "scheduled": False,
                "trigger": "turn_interval",
                "source_session_id": session_id,
                "reason": "session_not_found",
            }
        if not evolution_service.should_run_for_turn_interval(session):
            return {
                "scheduled": False,
                "trigger": "turn_interval",
                "source_session_id": session_id,
                "reason": "turn_interval_not_reached",
            }
        return self.schedule_evolution(session_id, "turn_interval")

    def schedule_evolution(self, session_id: str, trigger: str) -> dict[str, object]:
        if not self.settings.evolution.enabled:
            return {
                "scheduled": False,
                "trigger": trigger,
                "source_session_id": session_id,
                "reason": "evolution_disabled",
            }
        if self.settings.provider.type == "mock":
            return {
                "scheduled": False,
                "trigger": trigger,
                "source_session_id": session_id,
                "reason": "mock_provider",
            }
        if session_id in self._evolution_sessions_in_progress:
            return {
                "scheduled": False,
                "trigger": trigger,
                "source_session_id": session_id,
                "reason": "already_running",
            }
        self._evolution_sessions_in_progress.add(session_id)
        task = asyncio.create_task(self._run_evolution(session_id, trigger))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {
            "scheduled": True,
            "trigger": trigger,
            "source_session_id": session_id,
            "reason": "background_task_started",
        }

    def schedule_user_memory_extraction(self, session_id: str, trigger: str) -> dict[str, object]:
        if self.settings.provider.type == "mock":
            return {
                "scheduled": False,
                "trigger": trigger,
                "source_session_id": session_id,
                "reason": "mock_provider",
            }
        task = asyncio.create_task(self._run_memory_extraction(session_id, trigger))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {
            "scheduled": True,
            "trigger": trigger,
            "source_session_id": session_id,
            "reason": "background_task_started",
        }

    async def _run_memory_extraction(self, session_id: str, trigger: str) -> None:
        try:
            await self.memory_extractor.extract_session(session_id, trigger)
        except Exception as exc:
            print(f"[memory] extraction failed for session {session_id} ({trigger}): {exc}")

    async def _run_evolution(self, session_id: str, trigger: str) -> None:
        try:
            await self.evolution_service.run_for_session(session_id, trigger)  # type: ignore[arg-type]
        except Exception as exc:
            print(f"[evolution] run failed for session {session_id} ({trigger}): {exc}")
        finally:
            self._evolution_sessions_in_progress.discard(session_id)

    def _build_registry(self, workspace: Path) -> ToolRegistry:
        limits = ResourceLimits(
            timeout_seconds=self.settings.sandbox.timeout,
            output_limit_bytes=self.settings.sandbox.output_limit_bytes,
        )
        path_policy = build_path_access_policy(self.settings)
        sandbox = NativeSandbox(
            workspace=workspace,
            limits=limits,
            config=self.settings.sandbox,
            path_policy=path_policy,
        )
        self.exec_sandbox = sandbox
        self.tool_context = BuiltinToolContext(
            path_policy=path_policy,
            sandbox=sandbox,
            session_store=self.session_store,
            multimodal_analyzer=self.multimodal_analyzer,
            scheduler_store=self.scheduler_store,
        )
        tool_context = self.tool_context
        registry = ToolRegistry()
        for tool in load_builtin_tools(tool_context):
            registry.register(tool)
        for tool in self.mcp_registry.build_tools(self.plugin_service.mcp_server_configs()):
            registry.register(tool)
        return registry

    async def handle_message(
        self,
        session_id: str,
        content: str,
        emit: EventEmitter,
        user_metadata: dict[str, object] | None = None,
        turn_approval_mode: TurnApprovalMode = DEFAULT_TURN_APPROVAL_MODE,
        request_id: str | None = None,
        turn_id: str | None = None,
        on_turn_created: Callable[[str], None] | None = None,
        post_user_message: Callable[[SessionTask, SessionMessage, EventEmitter], Awaitable[None]] | None = None,
        scheduler_run_mode: Literal["interactive", "unattended"] = "interactive",
    ) -> None:
        self.reload_ecosystem()
        resolved_turn_id = turn_id or uuid4().hex
        extra_user_metadata = dict(user_metadata or {})
        extra_user_metadata["environment_context"] = build_environment_context(
            extra_user_metadata.get("environment_context")
        )
        pending_reply = self._pending_user_input_reply_metadata(session_id)
        if pending_reply is not None:
            extra_user_metadata["responds_to_awaiting_user_input"] = pending_reply
        user_message = SessionMessage(
            id=resolved_turn_id,
            role="user",
            content=content,
            metadata=self._build_message_metadata(
                turn_id=None,
                request_id=request_id,
                extra=extra_user_metadata,
            ),
        )
        user_message.metadata["turn_id"] = resolved_turn_id
        session = self.session_store.append_message(session_id, user_message)
        if on_turn_created is not None:
            on_turn_created(resolved_turn_id)

        task = SessionTask(session=session, permission_context=PermissionContext(), turn_id=resolved_turn_id)
        turn_emit = self._bind_turn_emitter(emit, task.turn_id)
        if post_user_message is not None:
            await post_user_message(task, user_message, turn_emit)
        current_content = self._current_turn_user_content(task.session, task.turn_id) or content
        await self._emit_hooks("SessionStart", turn_emit, session_id=session.session_id, content=current_content)

        for _ in range(self.settings.runtime.max_tool_depth):
            group_id = task.next_action_group_id()
            self.skill_registry.sync_snapshot()
            checkpoint_ok = await self._maybe_checkpoint(task, turn_emit)
            if checkpoint_ok is False:
                await self._finalize_context_irreducible(task, turn_emit, request_id=request_id)
                return
            if task.progress.force_no_tools_next:
                provider_tools = []
                task.progress.force_no_tools_next = False
            else:
                provider_tools = self._provider_tools_for_turn(task)
            assembled = self._assemble_task_messages(
                task,
                tools_overview=self._resolve_tools_overview(task),
            )

            try:
                response = await self._stream_provider_response_with_retries(
                    assembled,
                    provider_tools,
                    turn_emit,
                    session_id=task.session.session_id,
                    turn_id=task.turn_id,
                    request_kind="session_turn",
                    counts_toward_context_window=True,
                    group_id=group_id,
                    emit_answer_started_event=task.tool_depth > 0,
                )
            except ProviderError as exc:
                result = self._provider_error_result(exc)
                await self._finalize_provider_error(
                    task,
                    turn_emit,
                    result,
                    request_id=request_id,
                    provider=exc.provider,
                    status_code=exc.status_code,
                )
                return

            invalid_tool_action = await self._handle_invalid_provider_tool_calls(
                task,
                response,
                turn_emit,
                request_id=request_id,
                available_tool_names=_provider_tool_schema_names(provider_tools),
            )
            if invalid_tool_action == "continue":
                continue
            if invalid_tool_action == "finalized":
                return

            response = await self._ensure_tool_response_commentary(
                task,
                response,
                turn_emit,
                group_id=group_id,
            )

            decision = decide_turn_step(response, task.progress)

            if decision.action == "continue" and not response.tool_calls:
                await self._handle_completion_gate_continue(
                    task,
                    turn_emit,
                    decision,
                    request_id=request_id,
                )
                continue

            if decision.action == "awaiting_user":
                await self._finalize_awaiting_user_input_from_final_answer(
                    task,
                    turn_emit,
                    decision,
                    request_id=request_id,
                )
                return

            if not response.tool_calls:
                final_content = decision.final_content or ""
                assistant_message = self._build_assistant_message(
                    task,
                    final_content,
                    request_id=request_id,
                    finish_reason=decision.finish_reason,
                    turn_outcome=decision.turn_outcome,
                    extra_metadata={"completion_decision": decision.reason},
                )
                task.session.messages.append(assistant_message)
                self.session_store.save(task.session)
                await self._emit_final_response_message(
                    turn_emit,
                    task,
                    assistant_message,
                    finish_reason=decision.finish_reason,
                )
                await self._emit_hooks(
                    "SessionEnd",
                    turn_emit,
                    session_id=task.session.session_id,
                    finish_reason=decision.finish_reason,
                )
                return

            action_brief = response.commentary.strip()
            assistant_tool_extra = {
                "group_id": group_id,
                "commentary": response.commentary,
                "action_brief": action_brief,
                "phase": "commentary" if response.commentary else "tool_call",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    }
                    for tool_call in response.tool_calls
                ],
            }
            if response.provider_state:
                assistant_tool_extra["provider_state"] = dict(response.provider_state)

            assistant_tool_message = SessionMessage(
                id=uuid4().hex,
                role="assistant",
                content=self._compose_tool_call_assistant_content(response),
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra=assistant_tool_extra,
                ),
            )
            task.session.messages.append(assistant_tool_message)
            self.session_store.save(task.session)

            for tool_call in response.tool_calls:
                task.tool_depth += 1
                skill_usage_payload = self._skill_usage_payload_for_tool_call(tool_call.name, tool_call.arguments)
                if skill_usage_payload is not None:
                    await turn_emit(
                        "skill_used",
                        {
                            "group_id": group_id,
                            "tool_call_id": tool_call.id,
                            "action_brief": action_brief,
                            **skill_usage_payload,
                        },
                    )
                await turn_emit(
                    "tool_call_started",
                    {
                        "group_id": group_id,
                        "tool_call_id": tool_call.id,
                        "tool": tool_call.name,
                        "arguments": tool_call.arguments,
                        "action_brief": action_brief,
                    },
                )
                disallow_reason = self._tool_disallow_reason_for_task(task, tool_call.name)
                if disallow_reason is not None:
                    result = ToolExecutionResult(
                        success=False,
                        tool=tool_call.name,
                        action="execute",
                        category="permission_error",
                        summary=disallow_reason,
                        retryable=False,
                    )
                else:
                    try:
                        tool = self.router.route(tool_call.name, tool_call.arguments)
                    except KeyError:
                        result = ToolExecutionResult(
                            success=False,
                            tool=tool_call.name,
                            action="route",
                            category="validation_error",
                            summary=f"模型返回了当前不可用的工具调用：{tool_call.name}",
                            retryable=True,
                        )
                    else:
                        extra_reasons = self.router.static_checks(tool, tool_call.arguments)
                        await self._emit_hooks(
                            "PreToolUse",
                            turn_emit,
                            session_id=task.session.session_id,
                            tool=tool_call.name,
                            arguments=tool_call.arguments,
                            group_id=group_id,
                        )
                        result = await self.orchestrator.execute(
                            tool,
                            tool_call.arguments,
                            task.session.session_id,
                            turn_emit,
                            tool_call_id=tool_call.id,
                            group_id=group_id,
                            extra_reasons=extra_reasons,
                            turn_approval_mode=turn_approval_mode,
                            turn_id=task.turn_id,
                            scheduler_run_mode=scheduler_run_mode,
                        )
                result = normalize_result(result)
                task.progress.record_tool_result(result)
                metadata_updates = result.metadata.get("session_metadata_updates")
                if isinstance(metadata_updates, dict):
                    task.session.metadata.update(metadata_updates)
                message_updates = result.metadata.get("session_message_updates")
                if isinstance(message_updates, list):
                    self._apply_session_message_updates(task.session, message_updates)
                task.session.messages.append(
                    self._build_tool_session_message(
                        task,
                        result,
                        tool_call_id=tool_call.id,
                        group_id=group_id,
                        action_brief=action_brief,
                        request_id=request_id,
                    )
                )
                self.session_store.save(task.session)
                finished_payload = {
                    "group_id": group_id,
                    "tool_call_id": tool_call.id,
                    "tool": result.tool,
                    "success": result.success,
                    "category": result.category,
                    "error_code": result.error_code,
                    "severity": result.severity,
                    "risk_level": result.risk_level,
                    "recovery_class": result.recovery_class,
                    "frontend_message": result.frontend_message,
                    "recommended_next_step": result.recommended_next_step,
                    "summary": result.summary,
                    "duration_ms": result.duration_ms,
                    "attempt_count": result.attempt_count,
                    "action_brief": action_brief,
                }
                output_preview = _build_tool_event_output_preview(result)
                if output_preview:
                    finished_payload["output_preview"] = output_preview
                changed_path = result.metadata.get("path")
                if isinstance(changed_path, str) and changed_path:
                    finished_payload["path"] = changed_path
                for metadata_key in ("bytes", "content_type", "created", "output_files"):
                    metadata_value = result.metadata.get(metadata_key)
                    if metadata_value is not None:
                        finished_payload[metadata_key] = metadata_value
                await turn_emit(
                    "tool_call_finished",
                    finished_payload,
                )
                if plan_payload := result.metadata.get("plan"):
                    await turn_emit(
                        "plan_updated",
                        {
                            "session_id": task.session.session_id,
                            "plan": plan_payload,
                            "summary": result.summary,
                        },
                    )
                if collaboration_mode_payload := result.metadata.get("collaboration_mode"):
                    await turn_emit(
                        "collaboration_mode_changed",
                        {
                            "session_id": task.session.session_id,
                            "collaboration_mode": collaboration_mode_payload,
                            "summary": result.summary,
                        },
                    )
                if plan_draft_payload := result.metadata.get("plan_draft"):
                    await turn_emit(
                        "plan_draft_updated",
                        {
                            "session_id": task.session.session_id,
                            "plan_draft": plan_draft_payload,
                            "summary": result.summary,
                        },
                    )
                if workflow_state_payload := result.metadata.get(WORKFLOW_STATE_METADATA_KEY):
                    await turn_emit(
                        "workflow_state_changed",
                        {
                            "session_id": task.session.session_id,
                            "workflow_state": workflow_state_payload,
                            "summary": result.summary,
                        },
                    )
                if awaiting_payload := result.metadata.get(AWAITING_USER_INPUT_METADATA_KEY):
                    await turn_emit(
                        "user_input_requested",
                        {
                            "session_id": task.session.session_id,
                            "awaiting_user_input": awaiting_payload,
                            "summary": result.summary,
                        },
                    )
                await self._emit_hooks(
                    "PostToolUse",
                    turn_emit,
                    session_id=task.session.session_id,
                    tool=result.tool,
                    success=result.success,
                    category=result.category,
                    group_id=group_id,
                )
                if result.success and result.tool in {"write_file", "edit_file"}:
                    if isinstance(changed_path, str) and changed_path:
                        if self._should_reload_ecosystem_for_path(changed_path):
                            self.reload_ecosystem()
                        await self._emit_hooks(
                            "FileChanged",
                            turn_emit,
                            session_id=task.session.session_id,
                            tool=result.tool,
                            path=changed_path,
                            group_id=group_id,
                        )
                if result.success and result.tool == "terminal":
                    command = str(tool_call.arguments.get("command", ""))
                    if command and self._should_reload_ecosystem_for_terminal_command(command):
                        self.reload_ecosystem()
                if (
                    result.success
                    and normalize_turn_outcome(result.metadata.get("turn_outcome"), fallback="")
                    == TURN_OUTCOME_AWAITING_USER
                ):
                    await self._finalize_awaiting_user_input(
                        task,
                        turn_emit,
                        result,
                        request_id=request_id,
                    )
                    return
                if not result.success:
                    await self._record_failure_feedback(task, result, turn_emit, request_id=request_id)
                    if result.recovery_class == "fatal":
                        await self._finalize_fatal_tool_error(
                            task,
                            turn_emit,
                            result,
                            request_id=request_id,
                        )
                        return

            if task.tool_depth >= self.settings.runtime.max_tool_depth:
                await self._finalize_tool_limit(task, turn_emit, request_id=request_id)
                return

        await turn_emit("error", {"code": "RUNTIME_EXIT", "message": "RunLoop 未能正常完成"})

    def _should_reload_ecosystem_for_path(self, changed_path: str) -> bool:
        path = Path(changed_path).resolve()
        watched_roots = (
            self.settings.paths.skills_dir.resolve(),
            self.settings.paths.plugins_dir.resolve(),
            (Path(__file__).resolve().parents[1] / "tools").resolve(),
        )
        return any(path.is_relative_to(root) for root in watched_roots)

    def _should_reload_ecosystem_for_terminal_command(self, command: str) -> bool:
        analysis = analyze_terminal_command(command, build_path_access_policy(self.settings))
        if not analysis.mutating:
            return False
        return any(
            match.state == "writable" and self._should_reload_ecosystem_for_path(str(match.path))
            for match in analysis.path_matches
        )

    def _skill_usage_payload_for_tool_call(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object] | None:
        if tool_name not in {"read_file", "read_file_range"}:
            return None
        raw_path = arguments.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None

        try:
            requested_path = resolve_requested_path(build_path_access_policy(self.settings), raw_path)
        except Exception:
            requested_path = Path(raw_path).expanduser()

        try:
            resolved_requested_path = requested_path.resolve()
        except OSError:
            resolved_requested_path = requested_path

        try:
            skills = self.skill_registry.list_skills()
        except Exception:
            return None

        for skill in skills:
            try:
                skill_path = Path(skill.path).resolve()
            except OSError:
                continue
            if skill_path != resolved_requested_path:
                continue
            skill_name = str(skill.name)
            payload: dict[str, object] = {
                "skill_name": skill_name,
                "path": str(skill_path),
                "summary": f"使用 {skill_name} Skill，先读取它的工作说明",
            }
            description = getattr(skill, "description", "")
            if isinstance(description, str) and description.strip():
                payload["description"] = description.strip()
            plugin_name = getattr(skill, "plugin_name", None)
            if isinstance(plugin_name, str) and plugin_name.strip():
                payload["plugin_name"] = plugin_name.strip()
            return payload
        return None

    async def _stream_provider_response(
        self,
        assembled: list[dict[str, object]],
        tools: list[dict[str, object]],
        emit: EventEmitter,
        *,
        session_id: str,
        turn_id: str | None,
        request_kind: str,
        counts_toward_context_window: bool,
        group_id: str | None = None,
        emit_answer_started_event: bool = False,
    ) -> ProviderResponse:
        content_parts: list[str] = []
        thinking_parts: list[str] = []
        commentary_parts: list[str] = []
        tool_calls = []
        invalid_tool_calls = []
        allowed_tool_names = _provider_tool_schema_names(tools)
        invalid_tool_call_indexes: set[int] = set()
        finish_reason = "stop"
        usage = TokenUsage()
        parser = ThinkTagStreamParser()
        commentary_visible = False
        commentary_complete_pending = False
        answer_visible = False
        answer_started_emitted = False
        defer_answer_visibility = bool(tools)
        release_deferred_answer_before_stream_end = not emit_answer_started_event
        deferred_answer_deltas: list[str] = []
        tool_signal_seen = False
        tool_argument_progress: dict[str, dict[str, object]] = {}
        provider_state: dict[str, object] = {}

        async def flush_commentary(*, force: bool = False, delta: str | None = None) -> None:
            nonlocal commentary_visible, commentary_complete_pending
            if not group_id or not commentary_parts:
                return
            if not commentary_visible:
                if not force and not tool_calls:
                    return
                commentary_visible = True
                await emit(
                    "commentary_delta",
                    {
                        "group_id": group_id,
                        "content": "".join(commentary_parts),
                        "delta": "".join(commentary_parts),
                        "model": self.settings.provider.model,
                    },
                )
            elif delta:
                await emit(
                    "commentary_delta",
                    {
                        "group_id": group_id,
                        "content": "".join(commentary_parts),
                        "delta": delta,
                        "model": self.settings.provider.model,
                    },
                )
            if commentary_complete_pending:
                await emit(
                    "commentary_complete",
                    {
                        "group_id": group_id,
                        "content": "".join(commentary_parts),
                        "model": self.settings.provider.model,
                    },
                )
                commentary_complete_pending = False

        async def emit_answer_delta(delta: str) -> None:
            nonlocal commentary_complete_pending, answer_started_emitted, answer_visible
            if emit_answer_started_event and not answer_started_emitted:
                answer_started_emitted = True
                await emit(
                    "answer_started",
                    {
                        "group_id": group_id,
                        "model": self.settings.provider.model,
                    },
                )
            answer_visible = True
            await emit(
                "assistant_delta",
                {
                    "content": "".join(content_parts),
                    "delta": delta,
                    "model": self.settings.provider.model,
                },
            )

        def deferred_answer_release_ready() -> bool:
            raw = "".join(deferred_answer_deltas).strip()
            if not raw:
                return False
            normalized = self._sanitize_commentary_brief(raw)
            if "\n" in raw and STRUCTURED_TOOL_PREAMBLE_RE.search(raw):
                return len(normalized) >= STRUCTURED_ANSWER_DEFER_RELEASE_CHARS
            return len(normalized) >= ANSWER_DEFER_RELEASE_CHARS

        async def flush_deferred_answer(*, force: bool = False) -> None:
            nonlocal answer_started_emitted, answer_visible
            if not deferred_answer_deltas or tool_calls or answer_visible or not "".join(content_parts).strip():
                return
            if not force and (
                not release_deferred_answer_before_stream_end
                or not deferred_answer_release_ready()
            ):
                return
            visible_content_parts: list[str] = []
            for delta in deferred_answer_deltas:
                visible_content_parts.append(delta)
                if not "".join(visible_content_parts).strip():
                    continue
                if emit_answer_started_event and not answer_started_emitted:
                    answer_started_emitted = True
                    await emit(
                        "answer_started",
                        {
                            "group_id": group_id,
                            "model": self.settings.provider.model,
                        },
                    )
                answer_visible = True
                await emit(
                    "assistant_delta",
                    {
                        "content": "".join(visible_content_parts),
                        "delta": delta,
                        "model": self.settings.provider.model,
                    },
                )
            deferred_answer_deltas.clear()

        async def prepare_for_tool_signal() -> None:
            nonlocal answer_visible, answer_started_emitted, commentary_complete_pending, tool_signal_seen
            if tool_signal_seen:
                return
            tool_signal_seen = True
            leaked_answer = self._recover_tool_preamble_commentary("".join(content_parts))
            if answer_visible:
                content_parts.clear()
                deferred_answer_deltas.clear()
                answer_visible = False
                answer_started_emitted = False
                await emit(
                    "assistant_delta",
                    {
                        "content": "",
                        "delta": "",
                        "model": self.settings.provider.model,
                        "reset": True,
                    },
                )
            elif leaked_answer:
                content_parts.clear()
                deferred_answer_deltas.clear()
            elif content_parts:
                content_parts.clear()
                deferred_answer_deltas.clear()
            if leaked_answer and not commentary_parts:
                commentary_parts.append(leaked_answer)
                commentary_complete_pending = True
            await flush_commentary(force=True)

        async def emit_tool_argument_progress(delta: ToolCallDelta) -> None:
            if not group_id:
                return
            pending_key = f"pending:{delta.index}"
            key = delta.id or pending_key
            existing_progress = tool_argument_progress.get(key) or tool_argument_progress.get(pending_key)
            existing_name = (
                existing_progress.get("name")
                if isinstance(existing_progress, dict) and isinstance(existing_progress.get("name"), str)
                else None
            )
            resolved_name = delta.name or existing_name
            if resolved_name and not _is_provider_tool_name_allowed(resolved_name, allowed_tool_names):
                invalid_tool_call_indexes.add(delta.index)
                return
            if delta.index in invalid_tool_call_indexes:
                return
            if not resolved_name:
                return
            if delta.id and pending_key in tool_argument_progress and key not in tool_argument_progress:
                tool_argument_progress[key] = tool_argument_progress.pop(pending_key)
            progress = tool_argument_progress.setdefault(
                key,
                {
                    "id": delta.id or pending_key,
                    "name": resolved_name,
                    "argument_bytes": 0,
                    "last_emit_bytes": -TOOL_ARGUMENT_PROGRESS_EMIT_BYTES,
                    "emitted": False,
                },
            )
            previous_name = progress.get("name") if isinstance(progress.get("name"), str) else None
            if delta.id:
                progress["id"] = delta.id
            if delta.name:
                progress["name"] = delta.name
            if delta.arguments_delta:
                progress["argument_bytes"] = int(progress.get("argument_bytes", 0)) + len(delta.arguments_delta.encode("utf-8"))

            tool_name = progress.get("name") if isinstance(progress.get("name"), str) else None
            argument_bytes = int(progress.get("argument_bytes", 0))
            last_emit_bytes = int(progress.get("last_emit_bytes", -TOOL_ARGUMENT_PROGRESS_EMIT_BYTES))
            should_emit = (
                progress.get("emitted") is not True
                or argument_bytes - last_emit_bytes >= TOOL_ARGUMENT_PROGRESS_EMIT_BYTES
                or (delta.name is not None and delta.name != previous_name)
            )
            if not should_emit:
                return

            progress["emitted"] = True
            progress["last_emit_bytes"] = argument_bytes
            summary = _build_tool_argument_progress_summary(tool_name, argument_bytes)
            await emit(
                "tool_call_arguments_delta",
                {
                    "group_id": group_id,
                    "tool_call_id": progress["id"],
                    "tool": tool_name or "tool",
                    "arguments_bytes": argument_bytes,
                    "summary": summary,
                    "summary_text": summary,
                    "model": self.settings.provider.model,
                },
            )

        async def consume_parse_event(event) -> None:
            nonlocal commentary_complete_pending
            if event.kind == "answer" and event.text:
                content_parts.append(event.text)
                if defer_answer_visibility and not answer_visible:
                    deferred_answer_deltas.append(event.text)
                    await flush_deferred_answer()
                    return
                if not "".join(content_parts).strip():
                    return
                await emit_answer_delta(event.text)
                return
            if event.kind == "thinking" and event.text:
                thinking_parts.append(event.text)
                await emit(
                    "thinking_delta",
                    {
                        "content": "".join(thinking_parts),
                        "delta": event.text,
                        "model": self.settings.provider.model,
                    },
                )
                return
            if event.kind == "thinking_complete":
                await emit(
                    "thinking_complete",
                    {
                        "content": "".join(thinking_parts),
                        "model": self.settings.provider.model,
                    },
                )
                return
            if event.kind == "commentary" and event.text:
                commentary_parts.append(event.text)
                await flush_commentary(delta=event.text)
                return
            if event.kind == "commentary_complete":
                commentary_complete_pending = True
                await flush_commentary()

        try:
            async for chunk in self.provider.chat_stream(assembled, tools=tools):
                if chunk.type == "text" and chunk.delta:
                    for event in parser.feed(chunk.delta):
                        await consume_parse_event(event)
                elif chunk.type == "tool_call_delta" and chunk.tool_call_delta:
                    delta = chunk.tool_call_delta
                    pending_key = f"pending:{delta.index}"
                    key = delta.id or pending_key
                    existing_progress = tool_argument_progress.get(key) or tool_argument_progress.get(pending_key)
                    existing_name = (
                        existing_progress.get("name")
                        if isinstance(existing_progress, dict) and isinstance(existing_progress.get("name"), str)
                        else None
                    )
                    resolved_name = delta.name or existing_name
                    if resolved_name and not _is_provider_tool_name_allowed(resolved_name, allowed_tool_names):
                        invalid_tool_call_indexes.add(delta.index)
                        continue
                    if delta.index in invalid_tool_call_indexes or not resolved_name:
                        continue
                    await prepare_for_tool_signal()
                    await emit_tool_argument_progress(chunk.tool_call_delta)
                elif chunk.type == "tool_call" and chunk.tool_call:
                    if _is_provider_tool_name_allowed(chunk.tool_call.name, allowed_tool_names):
                        await prepare_for_tool_signal()
                        tool_calls.append(chunk.tool_call)
                        await flush_commentary(force=True)
                    else:
                        invalid_tool_call_indexes.add(len(tool_calls) + len(invalid_tool_calls))
                        invalid_tool_calls.append(chunk.tool_call)
                elif chunk.type == "usage" and chunk.usage:
                    usage = chunk.usage
                elif chunk.type == "provider_state" and chunk.provider_state:
                    provider_state.update(chunk.provider_state)
                elif chunk.type == "done":
                    finish_reason = chunk.finish_reason or finish_reason
                    if chunk.usage:
                        usage = chunk.usage
        except ProviderError as exc:
            details = dict(exc.details)
            details.setdefault("partial_thinking_length", len("".join(thinking_parts)))
            details.setdefault("partial_content_length", len("".join(content_parts)))
            details.setdefault("partial_commentary_length", len("".join(commentary_parts)))
            details.setdefault("partial_tool_call_count", len(tool_calls))
            details.setdefault("partial_invalid_tool_call_count", len(invalid_tool_calls))
            details.setdefault("partial_answer_visible", answer_visible)
            details.setdefault("partial_commentary_visible", commentary_visible)
            details.setdefault("partial_tool_signal_seen", tool_signal_seen or bool(tool_argument_progress))
            details.setdefault(
                "partial_response_visible",
                answer_visible or commentary_visible or tool_signal_seen or bool(tool_argument_progress),
            )
            exc.details = details
            raise
        for event in parser.flush():
            await consume_parse_event(event)
        await flush_deferred_answer(force=True)
        await flush_commentary(force=bool(tool_calls))
        thinking = "\n\n".join(
            _dedupe_strings(
                [
                    "".join(thinking_parts),
                    _extract_provider_state_reasoning(
                        provider_state,
                        getattr(getattr(self, "settings", None), "provider", None),
                    ),
                ]
            )
        )
        response = ProviderResponse(
            content="".join(content_parts),
            thinking=thinking,
            commentary="".join(commentary_parts),
            tool_calls=tool_calls,
            invalid_tool_calls=invalid_tool_calls,
            usage=usage,
            model=self.settings.provider.model,
            finish_reason=finish_reason,
            provider_state=provider_state,
        )
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind=request_kind,
                model_config=self.settings.provider,
                provider_type=self.settings.provider.type,
                streaming=True,
                counts_toward_context_window=counts_toward_context_window,
                session_id=session_id,
                turn_id=turn_id,
                metadata={
                    "assembled_message_count": len(assembled),
                    "tool_schema_count": len(tools),
                    "estimated_input_tokens": self.provider.estimate_tokens(assembled),
                    "response_content_length": len(response.content),
                    "response_thinking_length": len(response.thinking),
                    "response_commentary_length": len(response.commentary),
                    "tool_call_count": len(response.tool_calls),
                    "invalid_tool_call_count": len(response.invalid_tool_calls),
                },
            ),
            response,
        )
        return response

    async def _stream_provider_response_with_retries(
        self,
        assembled: list[dict[str, object]],
        tools: list[dict[str, object]],
        emit: EventEmitter,
        *,
        session_id: str,
        turn_id: str | None,
        request_kind: str,
        counts_toward_context_window: bool,
        group_id: str | None = None,
        emit_answer_started_event: bool = False,
    ) -> ProviderResponse:
        max_attempts = self._provider_max_attempts()
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._stream_provider_response(
                    assembled,
                    tools,
                    emit,
                    session_id=session_id,
                    turn_id=turn_id,
                    request_kind=request_kind,
                    counts_toward_context_window=counts_toward_context_window,
                    group_id=group_id,
                    emit_answer_started_event=emit_answer_started_event,
                )
                self._raise_for_empty_provider_response(response)
                return response
            except ProviderError as exc:
                details = dict(exc.details)
                details["attempt_count"] = attempt
                details["max_attempts"] = max_attempts
                partial_response_visible = bool(details.get("partial_response_visible"))
                if partial_response_visible and exc.retryable and attempt < max_attempts:
                    details["retry_suppressed_reason"] = "partial_response_visible"
                    details["retry_suppressed_message"] = "流式响应已向用户释放部分内容，为避免重复片段，本次不在同一条流上自动重试。"
                exc.details = details
                result = self._provider_error_result(exc)
                will_retry = (
                    exc.retryable
                    and result.recovery_class == "recoverable"
                    and attempt < max_attempts
                    and not partial_response_visible
                )
                will_transport_fallback = self._should_attempt_provider_transport_fallback(
                    result,
                    partial_response_visible=partial_response_visible,
                    will_retry=will_retry,
                )
                delay = self._provider_retry_backoff_seconds(attempt) if will_retry else 0.0
                await self._emit_provider_stream_error(
                    emit,
                    result,
                    provider=exc.provider,
                    status_code=exc.status_code,
                    attempt_count=attempt,
                    max_attempts=max_attempts,
                    will_retry=will_retry,
                    delay_seconds=delay,
                    partial_response_visible=partial_response_visible,
                    partial_content_length=_coerce_int(details.get("partial_content_length")),
                    partial_commentary_length=_coerce_int(details.get("partial_commentary_length")),
                    partial_tool_call_count=_coerce_int(details.get("partial_tool_call_count")),
                    will_transport_fallback=will_transport_fallback,
                    group_id=group_id,
                )
                if will_retry:
                    await emit(
                        "provider_retry_scheduled",
                        {
                            **({"group_id": group_id} if group_id else {}),
                            "provider": exc.provider,
                            "attempt": attempt + 1,
                            "delay_seconds": delay,
                            "reason": result.summary,
                            "category": result.category,
                            "strategy": "stream_retry",
                        },
                    )
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue

                if will_transport_fallback:
                    await emit(
                        "provider_fallback_started",
                        {
                            **({"group_id": group_id} if group_id else {}),
                            "provider": exc.provider,
                            "from_category": result.category,
                            "strategy": "non_stream_same_model",
                        },
                    )
                    try:
                        return await self._provider_non_stream_fallback(
                            assembled,
                            tools,
                            session_id=session_id,
                            turn_id=turn_id,
                            request_kind=request_kind,
                            counts_toward_context_window=counts_toward_context_window,
                            stream_error=result,
                        )
                    except ProviderError as fallback_exc:
                        fallback_details = dict(fallback_exc.details)
                        fallback_details.setdefault("transport_fallback_attempted", True)
                        fallback_details.setdefault("transport_fallback_strategy", "non_stream_same_model")
                        fallback_details.setdefault("transport_fallback_from", result.category)
                        fallback_details.setdefault(
                            "transport_fallback_message",
                            "流式失败后已尝试同模型非流式兜底，仍未恢复。",
                        )
                        fallback_exc.details = fallback_details
                        raise

                if not will_retry:
                    raise
        raise ProviderError(
            self.settings.provider.type,
            "upstream_error",
            "主模型重试后仍然无法返回有效响应",
            True,
        )

    def _provider_max_attempts(self) -> int:
        retry_attempts = getattr(self.settings.runtime, "provider_retry_attempts", None)
        if retry_attempts is None:
            retry_attempts = getattr(self.settings.runtime, "tool_retry_attempts", 0)
        return max(1, int(retry_attempts) + 1)

    def _provider_retry_backoff_seconds(self, attempt: int) -> float:
        base_delay = getattr(self.settings.runtime, "provider_retry_backoff_seconds", None)
        if base_delay is None:
            base_delay = getattr(self.settings.runtime, "tool_retry_backoff_seconds", 0.0)
        base_delay = max(0.0, float(base_delay))
        return base_delay * (2 ** max(0, attempt - 1))

    def _raise_for_empty_provider_response(self, response: ProviderResponse) -> None:
        if response.tool_calls:
            return
        if response.invalid_tool_calls:
            return
        if response.content.strip():
            return
        raise ProviderError(
            self.settings.provider.type,
            "empty_response",
            "主模型本次没有返回可展示的最终回答或工具调用，流式响应可能被提前结束或被上游/网关截断",
            True,
            details={
                "finish_reason": response.finish_reason,
                "model": response.model or self.settings.provider.model,
                "commentary_present": bool(response.commentary.strip()),
            },
        )

    async def _ensure_tool_response_commentary(
        self,
        task: SessionTask,
        response: ProviderResponse,
        emit: EventEmitter,
        *,
        group_id: str,
    ) -> ProviderResponse:
        if not response.tool_calls or response.commentary.strip():
            return response

        commentary = await self._generate_commentary_from_thinking(task, response)
        if not commentary:
            commentary = self._build_action_brief_from_tool_calls(task, response)
        if not commentary:
            return response

        response.commentary = commentary
        await emit(
            "commentary_delta",
            {
                "group_id": group_id,
                "content": commentary,
                "delta": commentary,
                "model": response.model or self.settings.provider.model,
            },
        )
        await emit(
            "commentary_complete",
            {
                "group_id": group_id,
                "content": commentary,
                "model": response.model or self.settings.provider.model,
            },
        )
        return response

    def _build_action_brief_from_tool_calls(
        self,
        task: SessionTask,
        response: ProviderResponse,
    ) -> str:
        if not response.tool_calls:
            return ""
        prefix = _brief_prefix_for_task(task)
        if len(response.tool_calls) == 1:
            return _compact_action_brief(_build_single_tool_action_brief(response.tool_calls[0], prefix, task))
        return _compact_action_brief(_build_multi_tool_action_brief(response.tool_calls, prefix))

    async def _handle_completion_gate_continue(
        self,
        task: SessionTask,
        emit: EventEmitter,
        decision: TurnStepDecision,
        *,
        request_id: str | None = None,
    ) -> None:
        if decision.reset_visible_answer:
            await emit(
                "assistant_delta",
                {
                    "content": "",
                    "delta": "",
                    "model": self.settings.provider.model,
                    "reset": True,
                },
            )
        if decision.inject_instruction:
            task.session.messages.append(
                SessionMessage(
                    id=uuid4().hex,
                    role="system",
                    content=decision.inject_instruction,
                    metadata=self._build_message_metadata(
                        task.turn_id,
                        request_id,
                        extra={
                            "type": "completion_gate_feedback",
                            "completion_decision": decision.reason,
                            "disable_tools_next": decision.disable_tools_next,
                        },
                    ),
                )
            )
            self.session_store.save(task.session)
        await emit(
            "completion_gate_feedback",
            {
                "session_id": task.session.session_id,
                "reason": decision.reason,
                "disable_tools_next": decision.disable_tools_next,
            },
        )

    async def _handle_invalid_provider_tool_calls(
        self,
        task: SessionTask,
        response: ProviderResponse,
        emit: EventEmitter,
        *,
        request_id: str | None = None,
        available_tool_names: set[str] | None = None,
    ) -> Literal["continue", "finalized", "none"]:
        if not response.invalid_tool_calls:
            return "none"

        invalid_names = _dedupe_strings(tool_call.name for tool_call in response.invalid_tool_calls)
        task.progress.invalid_tool_call_count += len(response.invalid_tool_calls)
        plan_tool_names_only = bool(invalid_names) and all(name in PLAN_TOOL_NAMES for name in invalid_names)
        disable_tools_next = bool(invalid_names) and all(name in PSEUDO_TOOL_NAMES for name in invalid_names)
        recovery_limit = (
            PLAN_TOOL_INVALID_CALL_RECOVERY_ATTEMPTS
            if plan_tool_names_only
            else MAX_INVALID_TOOL_CALL_RECOVERY_ATTEMPTS
        )

        if task.progress.invalid_tool_call_recovery_attempts < recovery_limit:
            task.progress.invalid_tool_call_recovery_attempts += 1
            if disable_tools_next:
                task.progress.force_no_tools_next = True
            await emit(
                "assistant_delta",
                {
                    "content": "",
                    "delta": "",
                    "model": self.settings.provider.model,
                    "reset": True,
                },
            )
            task.session.messages.append(
                SessionMessage(
                    id=uuid4().hex,
                    role="system",
                    content=self._build_invalid_tool_call_instruction(
                        invalid_names,
                        response,
                        disable_tools_next=disable_tools_next,
                        collaboration_mode=get_collaboration_mode(task.session).mode,
                        available_tool_names=available_tool_names,
                    ),
                    metadata=self._build_message_metadata(
                        task.turn_id,
                        request_id,
                        extra={
                            "type": "invalid_tool_call_feedback",
                            "invalid_tool_names": invalid_names,
                            "disable_tools_next": disable_tools_next,
                        },
                    ),
                )
            )
            self.session_store.save(task.session)
            await emit(
                "completion_gate_feedback",
                {
                    "session_id": task.session.session_id,
                    "reason": "invalid_tool_call",
                    "invalid_tool_names": invalid_names,
                    "disable_tools_next": disable_tools_next,
                },
            )
            return "continue"

        fallback = self._build_invalid_tool_call_fallback(
            invalid_names,
            response,
            available_tool_names=available_tool_names,
        )
        assistant_message = self._build_assistant_message(
            task,
            fallback,
            request_id=request_id,
            finish_reason="invalid_tool_call",
            turn_outcome=TURN_OUTCOME_BLOCKED,
            extra_metadata={
                "completion_decision": "invalid_tool_call",
                "invalid_tool_names": invalid_names,
            },
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason="invalid_tool_call",
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="invalid_tool_call",
        )
        return "finalized"

    def _build_invalid_tool_call_instruction(
        self,
        invalid_names: list[str],
        response: ProviderResponse,
        *,
        disable_tools_next: bool,
        collaboration_mode: str | None = None,
        available_tool_names: set[str] | None = None,
    ) -> str:
        names = ", ".join(invalid_names) if invalid_names else "unknown"
        commentary = response.commentary.strip() or "（空）"
        available_tools_hint = self._format_available_tool_names_hint(available_tool_names)
        available_tools_suffix = f"\n\n{available_tools_hint}" if available_tools_hint else ""
        available_tools_block = f"{available_tools_hint}\n" if available_tools_hint else ""
        if disable_tools_next:
            return (
                "你刚才返回了不可用的工具调用。"
                f"这些名称不是可调用工具：{names}。\n\n"
                "`commentary` / `thinking` 只是文本标签，不是 function/tool；绝对不要调用名为 commentary、thinking 或 think 的工具。\n"
                "下一步不要再调用任何工具。请直接基于当前上下文回答用户问题，并给出明确结果或阻塞原因。\n\n"
                f"刚才的可见行动说明：{commentary}"
            )
        if invalid_names and all(name in PLAN_TOOL_NAMES for name in invalid_names):
            if collaboration_mode == PLAN_COLLABORATION_MODE:
                return (
                    "你刚才调用了当前 Plan mode 下不可用的计划工具："
                    f"{names}。\n\n"
                    "Plan mode 使用 `update_plan` 维护执行 checklist。"
                    "如果还没有 checklist，下一步先调用 `update_plan`；如果已有 checklist，请继续使用当前可用的执行工具，并在步骤变化时用 `update_plan` 更新状态。"
                    f"{available_tools_suffix}"
                )
            return (
                "你刚才调用了当前 Default mode 下不可用的计划工具："
                f"{names}。\n\n"
                "Default mode 不使用 `update_plan`。"
                "如果确实需要可见任务清单，下一步先调用 `enter_plan_mode`；否则直接继续执行，不要重复调用这些计划工具。"
                f"{available_tools_suffix}"
            )
        return (
            "你刚才返回了不可用的工具调用。"
            f"这些名称不在当前可用工具列表中：{names}。\n\n"
            f"{available_tools_block}"
            "如果仍需要工具，请只使用系统提供的真实工具名；如果不需要工具，请直接回答用户。"
        )

    def _build_invalid_tool_call_fallback(
        self,
        invalid_names: list[str],
        response: ProviderResponse,
        *,
        available_tool_names: set[str] | None = None,
    ) -> str:
        names = ", ".join(invalid_names) if invalid_names else "unknown"
        lines = [
            "当前任务没有完成：模型连续返回了不可用的工具调用，已阻止将其标记为完成。",
            f"不可用工具：{names}",
        ]
        available_tools_hint = self._format_available_tool_names_hint(available_tool_names)
        if available_tools_hint:
            lines.append(available_tools_hint)
        if response.commentary.strip():
            lines.append(f"最后一次行动说明：{response.commentary.strip()}")
        lines.append("请重新发起任务，或调整工具提示与模型配置后重试。")
        return "\n".join(lines)

    def _format_available_tool_names_hint(self, available_tool_names: set[str] | None) -> str:
        names = sorted(name for name in available_tool_names or set() if isinstance(name, str) and name)
        if not names:
            return ""
        return f"当前可用工具：{', '.join(names)}。"

    async def _generate_commentary_from_thinking(
        self,
        task: SessionTask,
        response: ProviderResponse,
    ) -> str:
        provider_config = getattr(getattr(self, "settings", None), "provider", None)
        thinking = _response_reasoning_for_commentary(response, provider_config).strip()
        if not thinking:
            return ""
        thinking_excerpt = thinking[:1600]

        user_content = self._current_turn_user_content(task.session, task.turn_id)
        tool_names = ", ".join(tool_call.name for tool_call in response.tool_calls) or "无"
        messages = [
            {"role": "system", "content": COMMENTARY_FALLBACK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请基于下面的信息生成一句工具调用前的 brief。\n\n"
                    f"用户请求：\n{user_content or '（未找到）'}\n\n"
                    f"即将执行的工具：\n{tool_names}\n\n"
                    f"内部思考：\n{thinking_excerpt}"
                ),
            },
        ]
        try:
            fallback = await self.provider.chat(messages, tools=[])
        except ProviderError:
            return ""

        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind="commentary_fallback",
                model_config=self.settings.provider,
                provider_type=self.settings.provider.type,
                streaming=False,
                counts_toward_context_window=False,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                metadata={
                    "tool_names": [tool_call.name for tool_call in response.tool_calls],
                    "thinking_length": len(thinking),
                    "thinking_excerpt_length": len(thinking_excerpt),
                },
            ),
            fallback,
        )

        commentary, answer = self._parse_response_text(fallback.content)
        brief = commentary.strip() or answer.strip()
        return self._sanitize_commentary_brief(brief)

    async def _record_failure_feedback(
        self,
        task: SessionTask,
        result: ToolExecutionResult,
        emit: EventEmitter,
        *,
        request_id: str | None = None,
    ) -> None:
        await emit(
            "tool_error_feedback",
            {
                "tool": result.tool,
                "category": result.category,
                "error_code": result.error_code,
                "severity": result.severity,
                "risk_level": result.risk_level,
                "recovery_class": result.recovery_class,
                "frontend_message": result.frontend_message,
                "summary": result.summary,
                "retryable": result.retryable,
                "attempt_count": result.attempt_count,
                "recommended_next_step": result.recommended_next_step,
            },
        )
        feedback = self.feedback_writer.build(result)
        task.session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=feedback,
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={
                        "type": "tool_error_feedback",
                        "error_code": result.error_code,
                        "severity": result.severity,
                        "risk_level": result.risk_level,
                        "recovery_class": result.recovery_class,
                        "frontend_message": result.frontend_message,
                        "recommended_next_step": result.recommended_next_step,
                    },
                ),
            )
        )
        self.session_store.save(task.session)

    async def _finalize_awaiting_user_input(
        self,
        task: SessionTask,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        request_id: str | None = None,
    ) -> None:
        response_payload = result.metadata.get("assistant_response")
        final_content = ""
        if isinstance(response_payload, dict):
            content = response_payload.get("content")
            if isinstance(content, str):
                final_content = content.strip()
        if not final_content:
            final_content = result.stdout.strip() or result.summary.strip()

        extra_metadata: dict[str, object] = {}
        for metadata_key in (AWAITING_USER_INPUT_METADATA_KEY, WORKFLOW_STATE_METADATA_KEY):
            metadata_value = result.metadata.get(metadata_key)
            if isinstance(metadata_value, dict):
                extra_metadata[metadata_key] = metadata_value

        assistant_message = self._build_assistant_message(
            task,
            final_content,
            request_id=request_id,
            finish_reason="awaiting_user",
            turn_outcome=TURN_OUTCOME_AWAITING_USER,
            extra_metadata=extra_metadata,
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason="awaiting_user",
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="awaiting_user",
        )

    async def _finalize_awaiting_user_input_from_final_answer(
        self,
        task: SessionTask,
        emit: EventEmitter,
        decision: TurnStepDecision,
        *,
        request_id: str | None = None,
    ) -> None:
        final_content = (decision.final_content or "").strip()
        prompt = "请补充这些信息后我继续处理。"
        if final_content:
            content = final_content
        else:
            content = prompt

        awaiting = build_awaiting_user_input_payload(
            kind="free_text",
            prompt=prompt,
            content=content,
            workflow_id=f"turn:{task.turn_id}",
            data={
                "source": "final_answer",
                "completion_decision": decision.reason,
            },
        )
        workflow_state = build_workflow_state_payload(awaiting)
        extra_metadata = {
            AWAITING_USER_INPUT_METADATA_KEY: awaiting,
            WORKFLOW_STATE_METADATA_KEY: workflow_state,
        }
        assistant_message = self._build_assistant_message(
            task,
            content,
            request_id=request_id,
            finish_reason="awaiting_user",
            turn_outcome=TURN_OUTCOME_AWAITING_USER,
            extra_metadata=extra_metadata,
        )
        task.session.messages.append(assistant_message)
        task.session.metadata.update(
            {
                AWAITING_USER_INPUT_METADATA_KEY: awaiting,
                WORKFLOW_STATE_METADATA_KEY: workflow_state,
            }
        )
        self.session_store.save(task.session)
        await emit(
            "workflow_state_changed",
            {
                "session_id": task.session.session_id,
                "workflow_state": workflow_state,
                "summary": content,
            },
        )
        await emit(
            "user_input_requested",
            {
                "session_id": task.session.session_id,
                "awaiting_user_input": awaiting,
                "summary": content,
            },
        )
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason="awaiting_user",
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="awaiting_user",
        )

    async def _finalize_tool_limit(
        self,
        task: SessionTask,
        emit: EventEmitter,
        *,
        request_id: str | None = None,
    ) -> None:
        limit = self.settings.runtime.max_tool_depth
        instruction = (
            f"你已达到当前回合的工具调用上限（{limit} 次）。"
            "禁止继续调用任何工具。请仅基于现有上下文、已有工具结果和 checkpoint 摘要，"
            "给出一个阶段性结论，并明确告诉用户：如果要继续深入处理，请直接输入“继续”。"
        )
        task.session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=instruction,
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={"type": "tool_limit_guard"},
                ),
            )
        )
        self.session_store.save(task.session)
        checkpoint_ok = await self._maybe_checkpoint(task, emit)
        if checkpoint_ok is False:
            await self._finalize_context_irreducible(task, emit, request_id=request_id)
            return

        assembled = self._assemble_task_messages(
            task,
            tools_overview=self._resolve_tools_overview(task),
        )
        try:
            response = await self._stream_provider_response(
                assembled,
                [],
                emit,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                request_kind="tool_limit_finalize",
                counts_toward_context_window=True,
                emit_answer_started_event=task.tool_depth > 0,
            )
            final_content = response.content.strip()
        except ProviderError:
            final_content = (
                f"已达到当前回合的工具调用上限（{limit} 次）。"
                "我先基于已经完成的检查和工具结果停在这里。"
                "如果你要我继续往下处理，请直接输入“继续”。"
            )

        if not final_content:
            final_content = (
                f"已达到当前回合的工具调用上限（{limit} 次）。"
                "我先基于已经完成的检查和工具结果停在这里。"
                "如果你要我继续往下处理，请直接输入“继续”。"
            )

        assistant_message = self._build_assistant_message(
            task,
            final_content,
            request_id=request_id,
            finish_reason="tool_limit_reached",
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason="tool_limit_reached",
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="tool_limit_reached",
        )

    async def _finalize_fatal_tool_error(
        self,
        task: SessionTask,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        request_id: str | None = None,
    ) -> None:
        if result.error_code == "NEWMAN-TOOL-005" or result.category == "user_rejected":
            final_content = self._build_fatal_tool_fallback_message(result)
            assistant_message = self._build_assistant_message(
                task,
                final_content,
                request_id=request_id,
                finish_reason="approval_rejected",
            )
            task.session.messages.append(assistant_message)
            self.session_store.save(task.session)
            await self._emit_final_response_message(
                emit,
                task,
                assistant_message,
                finish_reason="approval_rejected",
            )
            await self._emit_hooks(
                "SessionEnd",
                emit,
                session_id=task.session.session_id,
                finish_reason="approval_rejected",
            )
            return

        instruction = (
            "刚才的工具调用已经确认失败。禁止继续调用任何工具，也不要重复同一个失败动作。"
            "如果不依赖该工具，你仍然可以基于现有上下文直接回答用户原问题，请直接给出最终回答。"
            "如果无法可靠回答，就明确说明阻塞原因、失败工具、关键报错，以及建议用户下一步怎么做。"
            "不要假装工具成功。"
        )
        task.session.messages.append(
            SessionMessage(
                id=uuid4().hex,
                role="system",
                content=instruction,
                metadata=self._build_message_metadata(
                    task.turn_id,
                    request_id,
                    extra={
                        "type": "fatal_tool_finalize",
                        "error_code": result.error_code,
                        "tool": result.tool,
                    },
                ),
            )
        )
        self.session_store.save(task.session)
        checkpoint_ok = await self._maybe_checkpoint(task, emit)
        if checkpoint_ok is False:
            await self._finalize_context_irreducible(task, emit, request_id=request_id)
            return

        assembled = self._assemble_task_messages(
            task,
            tools_overview=self._resolve_tools_overview(task),
        )

        finish_reason = "fatal_tool_error"
        try:
            response = await self._stream_provider_response(
                assembled,
                [],
                emit,
                session_id=task.session.session_id,
                turn_id=task.turn_id,
                request_kind="fatal_tool_finalize",
                counts_toward_context_window=True,
                emit_answer_started_event=task.tool_depth > 0,
            )
            final_content = response.content.strip()
            if response.tool_calls or self._contains_raw_tool_call_markup(final_content):
                final_content = ""
            if response.finish_reason:
                finish_reason = response.finish_reason
        except ProviderError:
            final_content = ""

        if not final_content:
            final_content = self._build_fatal_tool_fallback_message(result)

        assistant_message = self._build_assistant_message(
            task,
            final_content,
            request_id=request_id,
            finish_reason=finish_reason,
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason=finish_reason,
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="fatal_tool_error",
        )

    async def _finalize_provider_error(
        self,
        task: SessionTask,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        request_id: str | None = None,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        max_attempts_raw = result.metadata.get("max_attempts")
        max_attempts = int(max_attempts_raw) if isinstance(max_attempts_raw, int | float) else None
        final_content = self._build_provider_failure_message(
            result,
            attempt_count=result.attempt_count if result.attempt_count > 0 else None,
            max_attempts=max_attempts,
        )
        assistant_message = self._build_assistant_message(
            task,
            final_content,
            request_id=request_id,
            finish_reason="provider_error",
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason="provider_error",
        )
        extra: dict[str, object] = {}
        if provider:
            extra["provider"] = provider
        if status_code is not None:
            extra["status_code"] = status_code
        if result.attempt_count > 0:
            extra["attempt_count"] = result.attempt_count
        if max_attempts is not None:
            extra["max_attempts"] = max_attempts
        await self._emit_fatal_error(
            task,
            emit,
            result,
            finish_reason="provider_error",
            extra=extra,
        )

    def _contains_raw_tool_call_markup(self, text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        if RAW_TOOL_CALL_MARKUP_RE.search(normalized):
            return True
        return "<invoke" in normalized or "<parameter" in normalized

    def _build_fatal_tool_fallback_message(self, result: ToolExecutionResult) -> str:
        if result.error_code == "NEWMAN-TOOL-005" or result.category == "user_rejected":
            return "工具调用申请被用户拒绝或审批超时，当前任务已终止"
        blocker = result.frontend_message or "工具执行失败"
        summary = result.summary.strip() or "没有返回更具体的错误摘要。"
        lines = [
            f"这一步被阻塞了：`{result.tool}` {blocker}。",
            f"原因：{summary}",
        ]
        if result.recommended_next_step:
            lines.append(f"建议：{result.recommended_next_step}")
        lines.append("如果你愿意，我可以先不依赖这个工具，直接基于现有上下文继续回答。")
        return "\n".join(lines)

    async def _finalize_context_irreducible(
        self,
        task: SessionTask,
        emit: EventEmitter,
        *,
        request_id: str | None = None,
    ) -> None:
        final_content = self._build_context_irreducible_message(task)
        assistant_message = self._build_assistant_message(
            task,
            final_content,
            request_id=request_id,
            finish_reason="context_irreducible",
        )
        task.session.messages.append(assistant_message)
        self.session_store.save(task.session)
        await self._emit_final_response_message(
            emit,
            task,
            assistant_message,
            finish_reason="context_irreducible",
        )
        await emit(
            "error",
            {
                "code": "NEWMAN-CONTEXT-001",
                "message": "上下文已无法安全压缩",
                "summary": task.session.metadata.get("last_compaction_failure_reason") or "context_irreducible",
                "category": "context_irreducible",
                "severity": "warning",
                "risk_level": "medium",
                "recovery_class": "user_action_required",
                "retryable": False,
                "recommended_next_step": "Start a new session, split the task, or switch to a model with a larger context window.",
            },
        )
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason="context_irreducible",
        )

    def _build_context_irreducible_message(self, task: SessionTask) -> str:
        reason = task.session.metadata.get("last_compaction_failure_reason")
        reason_text = f"\n原因：{reason}" if isinstance(reason, str) and reason.strip() else ""
        return (
            "当前会话上下文已经超过可安全继续的范围，自动压缩后仍无法腾出足够空间。"
            "我已停止继续调用模型，避免丢失正在进行的工具链或生成不可靠结果。"
            f"{reason_text}\n\n"
            "建议：开启新会话继续、拆分任务，或切换到更大上下文窗口的模型。"
        )

    def _build_provider_failure_message(
        self,
        result: ToolExecutionResult,
        *,
        attempt_count: int | None = None,
        max_attempts: int | None = None,
    ) -> str:
        if result.category == "empty_response":
            headline = "主模型本次响应异常，未返回任何内容，当前无法继续。"
        elif result.category in {"timeout_error", "network_error", "upstream_error"}:
            headline = "主模型连接失败，当前无法继续。"
        elif result.category == "response_parse_error":
            headline = "主模型响应异常，当前无法继续。"
        elif result.category == "auth_error":
            headline = "主模型认证失败，当前无法继续。"
        elif result.category == "configuration_error":
            headline = "主模型配置无效，当前无法继续。"
        else:
            headline = "主模型调用失败，当前无法继续。"

        lines = [headline]
        retries = max(0, (attempt_count or 0) - 1)
        if retries > 0:
            if result.category == "empty_response":
                if max_attempts and attempt_count == max_attempts:
                    lines.append(f"已重试 {retries} 次，本次请求仍然没有拿到有效响应。")
                else:
                    lines.append(f"已重试 {retries} 次。")
            elif max_attempts and attempt_count == max_attempts:
                lines.append(f"已重试 {retries} 次，仍然无法恢复主模型连接。")
            else:
                lines.append(f"已重试 {retries} 次。")

        reason = (result.frontend_message or "").strip()
        summary = result.summary.strip()
        if result.category != "empty_response":
            if reason:
                lines.append(f"原因：{reason}")
            if summary and summary != reason:
                lines.append(f"详情：{summary}")

        if result.category == "empty_response":
            lines.append("建议：稍后重试；如果持续出现，请检查网关日志、流式转发链路，确认响应没有被提前截断。")
        elif result.category in {"timeout_error", "network_error", "upstream_error"}:
            lines.append("建议：稍后重试；如果持续失败，请检查主模型服务状态、网关和网络连通性。")
        elif result.category == "auth_error":
            lines.append("建议：检查主模型 API Key 或上游鉴权配置后再试。")
        elif result.category == "configuration_error":
            lines.append("建议：检查主模型 endpoint、模型名和运行配置后再试。")
        elif result.category == "response_parse_error":
            lines.append("建议：检查上游流式返回格式，确认没有提前截断或返回非法 JSON。")
        elif result.recommended_next_step:
            lines.append(f"建议：{result.recommended_next_step}")
        retry_suppressed_message = result.metadata.get("retry_suppressed_message")
        if isinstance(retry_suppressed_message, str) and retry_suppressed_message.strip():
            lines.append(f"说明：{retry_suppressed_message.strip()}")
        transport_fallback_message = result.metadata.get("transport_fallback_message")
        if isinstance(transport_fallback_message, str) and transport_fallback_message.strip():
            lines.append(f"说明：{transport_fallback_message.strip()}")

        return "\n".join(lines)

    def _compose_tool_call_assistant_content(self, response: ProviderResponse) -> str:
        commentary = response.commentary.strip()
        content = response.content.strip()
        if commentary and content:
            return f"{commentary}\n\n{content}"
        return commentary or content

    def _parse_response_text(self, text: str) -> tuple[str, str]:
        parser = ThinkTagStreamParser()
        commentary_parts: list[str] = []
        answer_parts: list[str] = []
        for event in parser.feed(text):
            if event.kind == "commentary" and event.text:
                commentary_parts.append(event.text)
            elif event.kind == "answer" and event.text:
                answer_parts.append(event.text)
        for event in parser.flush():
            if event.kind == "commentary" and event.text:
                commentary_parts.append(event.text)
            elif event.kind == "answer" and event.text:
                answer_parts.append(event.text)
        return "".join(commentary_parts), "".join(answer_parts)

    def _sanitize_commentary_brief(self, text: str) -> str:
        return " ".join(text.replace("\n", " ").split()).strip()

    def _recover_tool_preamble_commentary(self, text: str) -> str:
        raw = text.strip()
        if not raw:
            return ""
        normalized = self._sanitize_commentary_brief(raw)
        if not normalized:
            return ""
        if "\n" in raw or STRUCTURED_TOOL_PREAMBLE_RE.search(raw):
            return ""
        if len(normalized) > TOOL_PREAMBLE_COMMENTARY_MAX_CHARS:
            return ""
        return normalized

    def _current_turn_user_content(self, session, turn_id: str) -> str:
        current_turn_message = self._current_turn_user_message(session, turn_id)
        if current_turn_message is not None:
            return get_normalized_user_content(current_turn_message)
        for message in reversed(session.messages):
            if message.role == "user":
                return get_normalized_user_content(message)
        return ""

    def _current_turn_user_message(self, session, turn_id: str) -> SessionMessage | None:
        for message in reversed(session.messages):
            if message.role != "user":
                continue
            if message.metadata.get("turn_id") == turn_id:
                return message
        return None

    def _turn_has_attachment_metadata(self, session, turn_id: str) -> bool:
        current_turn_message = self._current_turn_user_message(session, turn_id)
        if current_turn_message is None:
            return False
        raw_attachments = current_turn_message.metadata.get("attachments")
        if not isinstance(raw_attachments, list):
            payload = get_attachment_analysis(current_turn_message)
            if not isinstance(payload, dict):
                return False
            summaries = payload.get("attachment_summaries")
            return isinstance(summaries, list) and any(isinstance(item, dict) for item in summaries)
        return any(isinstance(item, dict) for item in raw_attachments)

    def _turn_has_parsed_attachment_context(self, session, turn_id: str) -> bool:
        current_turn_message = self._current_turn_user_message(session, turn_id)
        if current_turn_message is None:
            return False
        payload = get_attachment_analysis(current_turn_message)
        if not payload:
            return False
        status = str(payload.get("status") or "").strip()
        if status not in {"completed", "partial"}:
            return False
        summaries = payload.get("attachment_summaries")
        if not isinstance(summaries, list):
            return False
        for item in summaries:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "").strip() == "parsed":
                return True
        return False

    def _should_block_file_browsing_tools_for_attachment_turn(self, task: SessionTask) -> bool:
        return task.tool_depth == 0 and self._turn_has_attachment_metadata(task.session, task.turn_id or "")

    def _should_allow_skill_read_for_attachment_turn(self, task: SessionTask) -> bool:
        if not self._should_block_file_browsing_tools_for_attachment_turn(task):
            return False
        user_content = self._current_turn_user_content(task.session, task.turn_id)
        terms = self._skill_relevance_terms(user_content)
        if is_attachment_edit_request(user_content):
            terms.update(self._attachment_skill_hint_terms(task.session, task.turn_id or ""))
        if not terms:
            return False
        skill_registry = getattr(self, "skill_registry", None)
        list_skills = getattr(skill_registry, "list_skills", None)
        if not callable(list_skills):
            return False
        try:
            skills = list_skills()
        except Exception:
            return False
        for skill in skills:
            fields = [
                str(getattr(skill, "name", "") or ""),
                str(getattr(skill, "description", "") or ""),
                str(getattr(skill, "when_to_use", "") or ""),
                str(getattr(skill, "summary", "") or ""),
            ]
            skill_path = getattr(skill, "path", "")
            if isinstance(skill_path, str) and skill_path:
                try:
                    path = Path(skill_path)
                    if path.is_file():
                        fields.append(path.read_text(encoding="utf-8", errors="replace")[:20_000])
                except OSError:
                    pass
            haystack = "\n".join(fields).casefold()
            if any(term in haystack for term in terms):
                return True
        return False

    def _attachment_skill_hint_terms(self, session, turn_id: str) -> set[str]:
        current_turn_message = self._current_turn_user_message(session, turn_id)
        if current_turn_message is None:
            return set()
        raw_attachments = current_turn_message.metadata.get("attachments")
        if not isinstance(raw_attachments, list):
            return set()

        terms: set[str] = set()
        for item in raw_attachments:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().casefold()
            extension = str(item.get("extension") or "").strip().casefold().lstrip(".")
            filename = str(item.get("filename") or "").strip().casefold()
            if kind == "spreadsheet" or extension in {"xls", "xlsx"} or filename.endswith((".xls", ".xlsx")):
                terms.update({"excel", "xlsx", "xls", "spreadsheet", "表格"})
            if kind == "presentation" or extension in {"ppt", "pptx"} or filename.endswith((".ppt", ".pptx")):
                terms.update({"ppt", "pptx", "powerpoint", "presentation", "幻灯片", "演示文稿"})
            if kind == "html" or extension in {"html", "htm"} or filename.endswith((".html", ".htm")):
                terms.add("html")
        return terms

    def _skill_relevance_terms(self, user_content: str | None) -> set[str]:
        normalized = (user_content or "").casefold().strip()
        if not normalized:
            return set()

        terms = {
            match.group(0)
            for match in re.finditer(r"[a-z0-9][a-z0-9_-]{2,}", normalized)
        }
        for match in re.finditer(r"[\u4e00-\u9fff]{3,}", normalized):
            phrase = match.group(0)
            for width in range(3, min(6, len(phrase)) + 1):
                for index in range(0, len(phrase) - width + 1):
                    terms.add(phrase[index : index + width].casefold())
        return terms

    def _assemble_task_messages(
        self,
        task: SessionTask,
        *,
        checkpoint=None,
        tools_overview: str | None = None,
    ) -> list[dict]:
        resolved_checkpoint = checkpoint if checkpoint is not None else self.checkpoints.get(task.session.session_id)
        if tools_overview is None:
            try:
                resolved_tools_overview = self._tools_overview(task)
            except TypeError:
                resolved_tools_overview = self._tools_overview()
        else:
            resolved_tools_overview = tools_overview
        messages = self.prompt_assembler.assemble(
            task.session,
            resolved_tools_overview,
            resolved_checkpoint,
            tool_message_overrides=task.transient_tool_messages,
            include_provider_state=self._should_include_provider_state_for_provider(),
        )
        return self._sanitize_provider_replay_messages(messages)

    def _should_include_provider_state_for_provider(self) -> bool:
        provider = getattr(getattr(self, "settings", None), "provider", None)
        return getattr(provider, "type", None) == "openai_compatible"

    def _provider_tools_for_turn(self, task: SessionTask) -> list[dict[str, object]]:
        mode = get_collaboration_mode(task.session).mode
        plan_missing = mode == PLAN_COLLABORATION_MODE and get_session_plan(task.session) is None
        provider_tools = self.registry.tools_for_provider(task.permission_context)
        filtered_tools = [
            schema
            for schema in provider_tools
            if is_tool_allowed_in_mode(str(schema.get("function", {}).get("name", "")), mode)
        ]
        if plan_missing:
            return [
                schema
                for schema in filtered_tools
                if str(schema.get("function", {}).get("name", "")) == "update_plan"
            ]
        existing_names = {
            str(schema.get("function", {}).get("name", ""))
            for schema in filtered_tools
            if isinstance(schema, dict)
        }
        registry_get = getattr(self.registry, "get", None)
        if callable(registry_get):
            for tool_name in sorted(self._history_referenced_tool_names(task.session)):
                if tool_name in existing_names or not is_tool_allowed_in_mode(tool_name, mode):
                    continue
                if not task.permission_context.can_expose(tool_name):
                    continue
                try:
                    tool = self.registry.get(tool_name)
                except KeyError:
                    continue
                filtered_tools.append(tool.to_provider_schema())
                existing_names.add(tool_name)
        if self._should_block_file_browsing_tools_for_attachment_turn(task):
            blocked_tools = set(ATTACHMENT_FIRST_REPLY_BLOCKED_TOOLS)
            if self._should_allow_skill_read_for_attachment_turn(task):
                blocked_tools.discard("read_file")
            filtered_tools = [
                schema
                for schema in filtered_tools
                if str(schema.get("function", {}).get("name", "")) not in blocked_tools
            ]
        return filtered_tools

    def _is_tool_allowed_for_task(self, task: SessionTask, tool_name: str) -> bool:
        return self._tool_disallow_reason_for_task(task, tool_name) is None

    def _tool_disallow_reason_for_task(self, task: SessionTask, tool_name: str) -> str | None:
        mode = get_collaboration_mode(task.session).mode
        if not is_tool_allowed_in_mode(tool_name, mode):
            return f"{tool_name} 在当前 {mode} 模式下不可用"
        if mode == PLAN_COLLABORATION_MODE and tool_name != "update_plan" and get_session_plan(task.session) is None:
            return f"当前处于计划模式，必须先调用 update_plan 生成 checklist，然后才能使用 {tool_name}"
        return None

    def _history_referenced_tool_names(self, session) -> set[str]:
        tool_names: set[str] = set()
        for message in session.messages:
            if message.role != "assistant":
                continue
            tool_calls = message.metadata.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for raw_tool_call in tool_calls:
                if not isinstance(raw_tool_call, dict):
                    continue
                name = raw_tool_call.get("name")
                if isinstance(name, str) and name:
                    tool_names.add(name)
        return tool_names

    def _sanitize_provider_replay_messages(self, messages: list[dict]) -> list[dict]:
        registry = getattr(self, "registry", None)
        registry_get = getattr(registry, "get", None)
        provider_type = str(getattr(getattr(self, "settings", None), "provider", None).type) if getattr(getattr(self, "settings", None), "provider", None) is not None else ""
        sanitize_tool_calls = callable(registry_get)

        sanitized_messages: list[dict] = []
        seen_system_message = False
        for message in messages:
            if message.get("role") == "system":
                if not seen_system_message:
                    seen_system_message = True
                elif provider_type == "openai_compatible":
                    sanitized_messages.append(
                        {
                            **message,
                            "role": "user",
                            "content": f"Runtime system note:\n\n{message.get('content', '')}",
                        }
                    )
                    continue

            if not sanitize_tool_calls:
                sanitized_messages.append(message)
                continue
            if message.get("role") != "assistant":
                sanitized_messages.append(message)
                continue
            raw_tool_calls = message.get("tool_calls")
            if not isinstance(raw_tool_calls, list) or not raw_tool_calls:
                sanitized_messages.append(message)
                continue

            next_tool_calls: list[dict[str, object]] = []
            message_changed = False
            for raw_tool_call in raw_tool_calls:
                if not isinstance(raw_tool_call, dict):
                    continue
                next_tool_call = dict(raw_tool_call)
                function_payload = raw_tool_call.get("function")
                if not isinstance(function_payload, dict):
                    next_tool_calls.append(next_tool_call)
                    continue

                next_function_payload = dict(function_payload)
                tool_name = next_function_payload.get("name")
                if not isinstance(tool_name, str) or not tool_name:
                    message_changed = True
                    continue
                try:
                    registry_get(tool_name)
                except KeyError:
                    message_changed = True
                    continue
                arguments_raw = next_function_payload.get("arguments")
                repaired_arguments = self._repair_tool_arguments_for_provider_replay(tool_name, arguments_raw)
                if repaired_arguments is not None:
                    next_function_payload["arguments"] = json.dumps(repaired_arguments, ensure_ascii=False)
                    message_changed = True
                next_tool_call["function"] = next_function_payload
                next_tool_calls.append(next_tool_call)

            if message_changed:
                next_message = dict(message)
                if next_tool_calls:
                    next_message["tool_calls"] = next_tool_calls
                else:
                    next_message.pop("tool_calls", None)
                    next_message.pop("provider_state", None)
                sanitized_messages.append(next_message)
            else:
                sanitized_messages.append(message)
        return sanitized_messages

    def _repair_tool_arguments_for_provider_replay(
        self,
        tool_name: object,
        arguments_raw: object,
    ) -> dict[str, object] | None:
        if not isinstance(tool_name, str) or not tool_name:
            return None

        registry = getattr(self, "registry", None)
        if registry is None:
            return None
        try:
            tool = registry.get(tool_name)
        except KeyError:
            return None

        parsed_arguments: object
        if isinstance(arguments_raw, str):
            try:
                parsed_arguments = json.loads(arguments_raw) if arguments_raw.strip() else {}
            except JSONDecodeError:
                parsed_arguments = {}
        else:
            parsed_arguments = arguments_raw

        if not isinstance(parsed_arguments, dict):
            parsed_arguments = {}
        if tool.validate_arguments(parsed_arguments) is None:
            return None

        repaired = _repair_schema_value(parsed_arguments, tool.meta.input_schema)
        if not isinstance(repaired, dict):
            return None
        if tool.validate_arguments(repaired) is not None:
            return None
        return repaired

    def _provider_error_result(self, error: ProviderError) -> ToolExecutionResult:
        attempt_count_raw = error.details.get("attempt_count")
        attempt_count = int(attempt_count_raw) if isinstance(attempt_count_raw, int | float) else 1
        max_attempts_raw = error.details.get("max_attempts")
        result = ToolExecutionResult(
            success=False,
            tool=f"provider:{error.provider}",
            action="chat",
            category=error.kind,
            summary=error.message,
            stderr=json.dumps(
                {
                    "provider": error.provider,
                    "kind": error.kind,
                    "status_code": error.status_code,
                    "details": error.details,
                },
                ensure_ascii=False,
            ),
            retryable=error.retryable,
            attempt_count=attempt_count,
        )
        if isinstance(max_attempts_raw, int | float):
            result.metadata["max_attempts"] = int(max_attempts_raw)
        for key in (
            "partial_response_visible",
            "partial_content_length",
            "partial_commentary_length",
            "partial_tool_call_count",
            "retry_suppressed_reason",
            "retry_suppressed_message",
            "transport_fallback_attempted",
            "transport_fallback_strategy",
            "transport_fallback_from",
            "transport_fallback_message",
        ):
            if key in error.details:
                result.metadata[key] = error.details[key]
        return normalize_result(result)

    async def _emit_provider_stream_error(
        self,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        provider: str,
        status_code: int | None,
        attempt_count: int,
        max_attempts: int,
        will_retry: bool,
        delay_seconds: float,
        partial_response_visible: bool,
        partial_content_length: int | None,
        partial_commentary_length: int | None,
        partial_tool_call_count: int | None,
        will_transport_fallback: bool,
        group_id: str | None = None,
    ) -> None:
        payload = {
            **({"group_id": group_id} if group_id else {}),
            "code": result.error_code,
            "message": result.frontend_message or result.summary,
            "summary": result.summary,
            "provider": provider,
            "tool": result.tool,
            "category": result.category,
            "severity": result.severity,
            "risk_level": result.risk_level,
            "recovery_class": result.recovery_class,
            "retryable": result.retryable,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "will_retry": will_retry,
            "delay_seconds": delay_seconds,
            "will_transport_fallback": will_transport_fallback,
            "partial_response_visible": partial_response_visible,
        }
        if status_code is not None:
            payload["status_code"] = status_code
        if partial_content_length is not None:
            payload["partial_content_length"] = partial_content_length
        if partial_commentary_length is not None:
            payload["partial_commentary_length"] = partial_commentary_length
        if partial_tool_call_count is not None:
            payload["partial_tool_call_count"] = partial_tool_call_count
        retry_suppressed_reason = result.metadata.get("retry_suppressed_reason")
        if isinstance(retry_suppressed_reason, str):
            payload["retry_suppressed_reason"] = retry_suppressed_reason
        retry_suppressed_message = result.metadata.get("retry_suppressed_message")
        if isinstance(retry_suppressed_message, str):
            payload["retry_suppressed_message"] = retry_suppressed_message
        await emit("stream_error", payload)

    async def _provider_non_stream_fallback(
        self,
        assembled: list[dict[str, object]],
        tools: list[dict[str, object]],
        *,
        session_id: str,
        turn_id: str | None,
        request_kind: str,
        counts_toward_context_window: bool,
        stream_error: ToolExecutionResult,
    ) -> ProviderResponse:
        response = await self.provider.chat(assembled, tools=tools)
        self._raise_for_empty_provider_response(response)
        record_model_usage(
            self.usage_store,
            ModelRequestContext(
                request_kind=f"{request_kind}_non_stream_fallback",
                model_config=self.settings.provider,
                provider_type=self.settings.provider.type,
                streaming=False,
                counts_toward_context_window=counts_toward_context_window,
                session_id=session_id,
                turn_id=turn_id,
                metadata={
                    "fallback_strategy": "non_stream_same_model",
                    "stream_error_category": stream_error.category,
                    "stream_error_summary": stream_error.summary,
                    "assembled_message_count": len(assembled),
                    "tool_schema_count": len(tools),
                    "estimated_input_tokens": self.provider.estimate_tokens(assembled),
                    "response_content_length": len(response.content),
                    "response_thinking_length": len(response.thinking),
                    "response_commentary_length": len(response.commentary),
                    "tool_call_count": len(response.tool_calls),
                    "invalid_tool_call_count": len(response.invalid_tool_calls),
                },
            ),
            response,
        )
        return response

    def _should_attempt_provider_transport_fallback(
        self,
        result: ToolExecutionResult,
        *,
        partial_response_visible: bool,
        will_retry: bool,
    ) -> bool:
        if will_retry or partial_response_visible:
            return False
        return result.category == "response_parse_error"

    async def _emit_fatal_error(
        self,
        task: SessionTask,
        emit: EventEmitter,
        result: ToolExecutionResult,
        *,
        finish_reason: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload = {
            "code": result.error_code,
            "message": result.frontend_message or result.summary,
            "summary": result.summary,
            "tool": result.tool,
            "category": result.category,
            "severity": result.severity,
            "risk_level": result.risk_level,
            "recovery_class": result.recovery_class,
            "retryable": result.retryable,
            "recommended_next_step": result.recommended_next_step,
        }
        if extra:
            payload.update(extra)
        if result.attempt_count > 0 and "attempt_count" not in payload:
            payload["attempt_count"] = result.attempt_count
        max_attempts = result.metadata.get("max_attempts")
        if isinstance(max_attempts, int | float) and "max_attempts" not in payload:
            payload["max_attempts"] = int(max_attempts)
        await emit("error", payload)
        await self._emit_hooks(
            "SessionEnd",
            emit,
            session_id=task.session.session_id,
            finish_reason=finish_reason,
        )

    async def _emit_hooks(self, event: str, emit: EventEmitter, **data) -> None:
        group_id = data.get("group_id")
        for message in self.hook_manager.messages_for(event):
            payload = {"event": event, "message": message, "context": data}
            if isinstance(group_id, str) and group_id:
                payload["group_id"] = group_id
            await emit("hook_triggered", payload)
        for message in await self.hook_manager.handler_messages_for(event, data):
            payload = {"event": event, "message": message, "context": data}
            if isinstance(group_id, str) and group_id:
                payload["group_id"] = group_id
            await emit("hook_triggered", payload)
        if event == "SessionEnd":
            session_id = data.get("session_id")
            if isinstance(session_id, str) and session_id and hasattr(self, "evolution_service"):
                self.schedule_turn_interval_evolution(session_id)

    async def _maybe_checkpoint(self, task: SessionTask, emit: EventEmitter) -> bool:
        assembled = self._assemble_task_messages(task)
        latest_record = self._latest_context_record(task.session.session_id)
        checkpoint = self.checkpoints.get(task.session.session_id)
        context_usage = build_context_usage_snapshot(
            self.provider,
            self.settings.provider,
            self.settings.runtime,
            assembled,
            task.session,
            checkpoint,
            latest_record=latest_record,
        )
        projected_next_prompt_tokens = context_usage.projected_next_prompt_tokens
        auto_compact_limit = context_usage.auto_compact_limit
        if projected_next_prompt_tokens < context_usage.soft_compact_limit:
            self._reset_compaction_state(task)
            return True

        hard_over_limit = projected_next_prompt_tokens >= auto_compact_limit

        if hard_over_limit:
            if self._context_irreducible(task):
                return False

            if self._compaction_fail_streak(task) >= self.settings.runtime.context_compaction_max_failures:
                self._mark_compaction_failure(task, irreducible=True, reason="max_failures_reached")
                return False

        preserve_recent = self.settings.runtime.context_compaction_preserve_recent

        original_count = len(task.session.messages)
        microcompact_count = microcompact_session(
            task.session,
            preserve_recent=preserve_recent,
            checkpoint=checkpoint,
            artifact_dir=self._microcompact_artifact_dir(task.session.session_id),
        )
        if microcompact_count:
            task.session.metadata["last_compaction_stage"] = "microcompact"
            task.session.metadata["last_microcompact_at"] = utc_now()
            self.session_store.save(task.session)
            context_usage = build_context_usage_snapshot(
                self.provider,
                self.settings.provider,
                self.settings.runtime,
                self._assemble_task_messages(task, checkpoint=checkpoint),
                task.session,
                checkpoint,
                latest_record=latest_record,
            )
            projected_next_prompt_tokens = context_usage.projected_next_prompt_tokens
            auto_compact_limit = context_usage.auto_compact_limit
            hard_over_limit = projected_next_prompt_tokens >= auto_compact_limit
            if projected_next_prompt_tokens < context_usage.soft_compact_limit:
                self._reset_compaction_state(task)
                return True

        summary_result = await summarize_messages(
            self.provider,
            self.settings.provider,
            self.settings.provider.type,
            task.session,
            preserve_recent=preserve_recent,
            checkpoint=checkpoint,
            usage_store=self.usage_store,
            turn_id=task.turn_id,
            request_kind="context_compaction",
        )
        if not summary_result:
            if not hard_over_limit:
                self._reset_compaction_state(task)
                return True
            self._mark_compaction_failure(task, irreducible=True, reason="nothing_to_compress")
            return False
        archived_message_count = min(
            len(task.session.messages),
            checkpoint_archived_message_count(task.session, checkpoint) + summary_result.source_message_count,
        )
        task.session.metadata["checkpoint_active"] = True
        task.session.metadata["last_compaction_stage"] = "checkpoint_compact"
        self.session_store.save(task.session)
        checkpoint = self.checkpoints.save(
            task.session.session_id,
            summary_result.summary,
            [0, archived_message_count],
            metadata=build_checkpoint_metadata(
                summary_result,
                preserve_recent=preserve_recent,
                compression_level="automatic",
                original_message_count=original_count,
                archived_message_count=archived_message_count,
                microcompact_count=microcompact_count,
            ),
        )
        task.session.metadata["checkpoint_restore_hint"] = checkpoint.checkpoint_id
        self.session_store.save(task.session)
        refreshed_usage = build_context_usage_snapshot(
            self.provider,
            self.settings.provider,
            self.settings.runtime,
            self._assemble_task_messages(task, checkpoint=checkpoint),
            task.session,
            checkpoint,
            latest_record=latest_record,
        )
        if refreshed_usage.projected_next_prompt_tokens >= refreshed_usage.auto_compact_limit:
            self._mark_compaction_failure(task, irreducible=False, reason="post_compaction_still_over_limit")
        else:
            self._reset_compaction_state(task)
        await emit(
            "checkpoint_created",
            {
                "session_id": task.session.session_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "summary": checkpoint.summary,
                "compression_level": checkpoint.metadata.get("compression_level", "automatic"),
                "microcompact_count": microcompact_count,
            },
        )
        return not self._context_irreducible(task)

    def _microcompact_artifact_dir(self, session_id: str) -> Path | None:
        paths = getattr(self.settings, "paths", None)
        sessions_dir = getattr(paths, "sessions_dir", None)
        if sessions_dir is None:
            return None
        return Path(sessions_dir) / "tool_outputs" / session_id

    def _latest_context_record(self, session_id: str):
        if self.usage_store is None:
            return None
        try:
            return self.usage_store.latest_context_record(session_id)
        except Exception:
            return None

    def _compaction_fail_streak(self, task: SessionTask) -> int:
        raw_value = task.session.metadata.get("compaction_fail_streak")
        return raw_value if isinstance(raw_value, int) and raw_value >= 0 else 0

    def _context_irreducible(self, task: SessionTask) -> bool:
        return task.session.metadata.get("context_irreducible") is True

    def _reset_compaction_state(self, task: SessionTask) -> None:
        task.session.metadata["compaction_fail_streak"] = 0
        task.session.metadata["context_irreducible"] = False
        task.session.metadata.pop("last_compaction_failure_reason", None)
        self.session_store.save(task.session)

    def _mark_compaction_failure(self, task: SessionTask, *, irreducible: bool, reason: str) -> None:
        next_fail_streak = self._compaction_fail_streak(task) + 1
        task.session.metadata["compaction_fail_streak"] = next_fail_streak
        task.session.metadata["context_irreducible"] = irreducible or (
            next_fail_streak >= self.settings.runtime.context_compaction_max_failures
        )
        task.session.metadata["last_compaction_failure_reason"] = reason
        self.session_store.save(task.session)

    def _build_message_metadata(
        self,
        turn_id: str | None,
        request_id: str | None,
        *,
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {}
        if turn_id:
            metadata["turn_id"] = turn_id
        if request_id:
            metadata["request_id"] = request_id
        if extra:
            metadata.update(extra)
        return metadata

    def _resolve_assistant_image_path(self, raw_source: str) -> Path | None:
        source = raw_source.strip()
        if not source:
            return None
        if source.startswith(DIRECT_IMAGE_SOURCE_PREFIXES):
            return None
        if source.startswith("file://"):
            source = unquote(urlparse(source).path)
        else:
            source = unquote(source)
        if not source:
            return None

        candidate = Path(source)
        if not candidate.is_absolute():
            workspace = getattr(getattr(self.settings, "paths", None), "workspace", None)
            if not isinstance(workspace, Path):
                return None
            candidate = Path(workspace) / candidate

        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None

        content_type = mimetypes.guess_type(resolved.name)[0] or ""
        if not content_type.startswith("image/") and resolved.suffix.lower() not in IMAGE_ATTACHMENT_SUFFIXES:
            return None
        return resolved

    def _workspace_relative_path(self, target: Path) -> str | None:
        workspace = getattr(getattr(self.settings, "paths", None), "workspace", None)
        if not isinstance(workspace, Path):
            return None
        try:
            return str(target.relative_to(Path(workspace).resolve()))
        except ValueError:
            return None

    def _build_file_attachment(
        self,
        path: Path,
        *,
        summary: str = "",
        seen_paths: set[str],
        source: str = "assistant_output",
    ) -> dict[str, object] | None:
        try:
            resolved = path.resolve()
        except OSError:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None

        path_key = str(resolved)
        if path_key in seen_paths:
            return None
        seen_paths.add(path_key)

        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        suffix = resolved.suffix.lower()
        if content_type.startswith("image/") or suffix in IMAGE_ATTACHMENT_SUFFIXES:
            kind = "image"
        elif suffix in {".html", ".htm"} or content_type == "text/html":
            kind = "html"
            content_type = "text/html"
        else:
            kind = "document"

        return {
            "attachment_id": uuid4().hex,
            "source": source,
            "kind": kind,
            "filename": resolved.name,
            "extension": suffix,
            "content_type": content_type,
            "size_bytes": resolved.stat().st_size,
            "path": str(resolved),
            "workspace_relative_path": self._workspace_relative_path(resolved),
            "summary": summary.strip(),
            "analysis_status": "completed",
        }

    def _build_turn_output_file_attachments(
        self,
        task: SessionTask,
        seen_paths: set[str],
    ) -> list[dict[str, object]]:
        attachments: list[dict[str, object]] = []
        for message in task.session.messages:
            if message.role != "tool":
                continue
            metadata = message.metadata
            if metadata.get("turn_id") != task.turn_id:
                continue
            raw_output_files = metadata.get("output_files")
            if isinstance(raw_output_files, list):
                for raw_item in raw_output_files:
                    if not isinstance(raw_item, dict):
                        continue
                    raw_path = raw_item.get("path")
                    if not isinstance(raw_path, str) or not raw_path.strip():
                        continue
                    if not self._is_session_output_file(task, Path(raw_path)):
                        continue
                    attachment = self._build_file_attachment(
                        Path(raw_path),
                        summary=str(raw_item.get("summary") or metadata.get("summary") or "生成文件"),
                        seen_paths=seen_paths,
                    )
                    if attachment is not None:
                        attachments.append(attachment)
            if metadata.get("success") is not True:
                continue
            if metadata.get("tool") not in {"write_file", "edit_file"}:
                continue
            raw_path = metadata.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            if not self._is_session_output_file(task, Path(raw_path)):
                continue
            attachment = self._build_file_attachment(
                Path(raw_path),
                summary=str(metadata.get("summary") or "生成文件"),
                seen_paths=seen_paths,
            )
            if attachment is not None:
                attachments.append(attachment)
        return attachments

    def _current_turn_awaiting_user_reply(self, task: SessionTask) -> dict[str, object] | None:
        if not task.turn_id:
            return None
        current_user_message = self._current_turn_user_message(task.session, task.turn_id)
        if current_user_message is None:
            return None
        reply_metadata = current_user_message.metadata.get("responds_to_awaiting_user_input")
        return reply_metadata if isinstance(reply_metadata, dict) else None

    @staticmethod
    def _awaiting_user_input_matches_reply(
        awaiting_metadata: dict[str, object],
        reply_metadata: dict[str, object],
    ) -> bool:
        awaiting_request_id = awaiting_metadata.get("request_id")
        reply_request_id = reply_metadata.get("request_id")
        if isinstance(awaiting_request_id, str) and awaiting_request_id and awaiting_request_id == reply_request_id:
            return True

        awaiting_workflow_id = awaiting_metadata.get("workflow_id")
        reply_workflow_id = reply_metadata.get("workflow_id")
        if isinstance(awaiting_workflow_id, str) and awaiting_workflow_id and awaiting_workflow_id == reply_workflow_id:
            return True

        return False

    def _build_reply_parent_output_attachments(
        self,
        task: SessionTask,
        seen_paths: set[str],
    ) -> list[dict[str, object]]:
        reply_metadata = self._current_turn_awaiting_user_reply(task)
        if reply_metadata is None:
            return []

        attachments: list[dict[str, object]] = []
        for message in reversed(task.session.messages):
            if message.role != "assistant":
                continue
            parent_turn_id = message.metadata.get("turn_id")
            if not isinstance(parent_turn_id, str) or not parent_turn_id or parent_turn_id == task.turn_id:
                continue
            awaiting_metadata = message.metadata.get(AWAITING_USER_INPUT_METADATA_KEY)
            if not isinstance(awaiting_metadata, dict):
                continue
            if not self._awaiting_user_input_matches_reply(awaiting_metadata, reply_metadata):
                continue

            raw_attachments = message.metadata.get("attachments")
            if not isinstance(raw_attachments, list):
                continue
            for raw_attachment in raw_attachments:
                if not isinstance(raw_attachment, dict):
                    continue
                if raw_attachment.get("source") != "assistant_output":
                    continue
                raw_path = raw_attachment.get("path")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    continue
                path = Path(raw_path)
                if not is_within_turn_output_dir(
                    path,
                    self.settings.paths.workspace,
                    task.session.session_id,
                    parent_turn_id,
                ):
                    continue
                attachment = self._build_file_attachment(
                    path,
                    summary=str(raw_attachment.get("summary") or "生成文件"),
                    seen_paths=seen_paths,
                )
                if attachment is not None:
                    attachments.append(attachment)

            if attachments:
                return attachments

        return attachments

    def _build_assistant_attachments(self, task: SessionTask, content: str) -> list[dict[str, object]]:
        attachments: list[dict[str, object]] = []
        seen_paths: set[str] = set()

        for source, alt_text in _extract_assistant_image_references(content):
            path = self._resolve_assistant_image_path(source)
            if path is None:
                continue

            attachment = self._build_file_attachment(
                path,
                summary=alt_text or "",
                seen_paths=seen_paths,
            )
            if attachment is not None:
                attachments.append(attachment)

        attachments.extend(self._build_turn_output_file_attachments(task, seen_paths))
        attachments.extend(self._build_reply_parent_output_attachments(task, seen_paths))
        return attachments

    def _is_session_output_file(self, task: SessionTask, path: Path) -> bool:
        return is_within_session_output_dir(
            path,
            self.settings.paths.workspace,
            task.session.session_id,
        )

    def _build_assistant_message(
        self,
        task: SessionTask,
        content: str,
        *,
        request_id: str | None,
        finish_reason: str,
        turn_outcome: str | None = None,
        extra_metadata: dict[str, object] | None = None,
    ) -> SessionMessage:
        attachments = self._build_assistant_attachments(task, content)
        resolved_outcome = self._resolve_turn_outcome(
            finish_reason=finish_reason,
            attachments=attachments,
            explicit=turn_outcome,
        )
        extra: dict[str, object] = {
            "finish_reason": finish_reason,
            "turn_outcome": resolved_outcome,
        }
        if extra_metadata:
            extra.update(extra_metadata)
        if attachments:
            extra["attachments"] = attachments
        return SessionMessage(
            id=uuid4().hex,
            role="assistant",
            content=content,
            metadata=self._build_message_metadata(
                task.turn_id,
                request_id,
                extra=extra,
            ),
        )

    def _resolve_turn_outcome(
        self,
        *,
        finish_reason: str,
        attachments: list[dict[str, object]] | None = None,
        explicit: str | None = None,
    ) -> str:
        if explicit:
            return normalize_turn_outcome(explicit, fallback=TURN_OUTCOME_ANSWERED)
        if finish_reason == "awaiting_user":
            return TURN_OUTCOME_AWAITING_USER
        if finish_reason in {"provider_error", "fatal_tool_error", "approval_rejected"}:
            return TURN_OUTCOME_FAILED
        if finish_reason in {"tool_limit_reached", "context_irreducible"}:
            return TURN_OUTCOME_BLOCKED
        if attachments:
            return TURN_OUTCOME_ARTIFACT_READY
        return TURN_OUTCOME_ANSWERED

    async def _emit_final_response_message(
        self,
        emit: EventEmitter,
        task: SessionTask,
        assistant_message: SessionMessage,
        *,
        finish_reason: str,
    ) -> None:
        turn_outcome = normalize_turn_outcome(
            assistant_message.metadata.get("turn_outcome"),
            fallback=self._resolve_turn_outcome(
                finish_reason=finish_reason,
                attachments=assistant_message.metadata.get("attachments")
                if isinstance(assistant_message.metadata.get("attachments"), list)
                else None,
            ),
        )
        self._clear_resolved_awaiting_user_input(task, turn_outcome)

        payload: dict[str, object] = {
            "session_id": task.session.session_id,
            "content": assistant_message.content,
            "finish_reason": finish_reason,
            "turn_outcome": turn_outcome,
            "message_id": assistant_message.id,
            "created_at": assistant_message.created_at,
        }
        attachments = assistant_message.metadata.get("attachments")
        if isinstance(attachments, list) and attachments:
            payload["attachments"] = attachments
        for metadata_key in (AWAITING_USER_INPUT_METADATA_KEY, WORKFLOW_STATE_METADATA_KEY):
            metadata_value = assistant_message.metadata.get(metadata_key)
            if isinstance(metadata_value, dict):
                payload[metadata_key] = metadata_value
        await emit("final_response", payload)
        completed_payload: dict[str, object] = {
            "session_id": task.session.session_id,
            "finish_reason": finish_reason,
            "turn_outcome": turn_outcome,
            "message_id": assistant_message.id,
            "created_at": assistant_message.created_at,
        }
        for metadata_key in (AWAITING_USER_INPUT_METADATA_KEY, WORKFLOW_STATE_METADATA_KEY):
            metadata_value = assistant_message.metadata.get(metadata_key)
            if isinstance(metadata_value, dict):
                completed_payload[metadata_key] = metadata_value
        await emit("turn_completed", completed_payload)

    def _clear_resolved_awaiting_user_input(self, task: SessionTask, turn_outcome: str) -> None:
        if turn_outcome == TURN_OUTCOME_AWAITING_USER:
            return
        if self._current_turn_awaiting_user_reply(task) is None:
            return
        task.session.metadata.pop(AWAITING_USER_INPUT_METADATA_KEY, None)
        workflow_state = task.session.metadata.get(WORKFLOW_STATE_METADATA_KEY)
        if isinstance(workflow_state, dict):
            next_state = dict(workflow_state)
            next_state.pop("awaiting", None)
            if turn_outcome == TURN_OUTCOME_ARTIFACT_READY:
                next_state["status"] = "artifact_ready"
            elif turn_outcome == TURN_OUTCOME_TASK_COMPLETED:
                next_state["status"] = "completed"
            elif turn_outcome == TURN_OUTCOME_BLOCKED:
                next_state["status"] = "blocked"
            elif turn_outcome == TURN_OUTCOME_FAILED:
                next_state["status"] = "failed"
            else:
                next_state["status"] = "running"
            next_state["updated_at"] = utc_now()
            task.session.metadata[WORKFLOW_STATE_METADATA_KEY] = next_state
        self.session_store.save(task.session)

    def _build_tool_session_message(
        self,
        task: SessionTask,
        result: ToolExecutionResult,
        *,
        tool_call_id: str,
        group_id: str,
        action_brief: str,
        request_id: str | None,
    ) -> SessionMessage:
        model_output = _build_tool_message_output(result) or result.summary
        persisted_output = result.persisted_output if result.persisted_output is not None else model_output
        metadata = {
            "turn_id": task.turn_id,
            **({"request_id": request_id} if request_id else {}),
            "group_id": group_id,
            "tool_call_id": tool_call_id,
            "tool": result.tool,
            "action_brief": action_brief,
            "category": result.category,
            "success": result.success,
            "error_code": result.error_code,
            "severity": result.severity,
            "risk_level": result.risk_level,
            "recovery_class": result.recovery_class,
            "frontend_message": result.frontend_message,
            "summary": result.summary,
            "recommended_next_step": result.recommended_next_step,
            "content_persisted": persisted_output == model_output,
        }
        for metadata_key in ("path", "bytes", "content_type", "created", "replacements", "output_files"):
            metadata_value = result.metadata.get(metadata_key)
            if metadata_value is not None:
                metadata[metadata_key] = metadata_value
        if persisted_output != model_output:
            task.transient_tool_messages[tool_call_id] = SessionMessage(
                id=uuid4().hex,
                role="tool",
                content=model_output,
                metadata=dict(metadata),
            )
        else:
            task.transient_tool_messages.pop(tool_call_id, None)
        return SessionMessage(
            id=uuid4().hex,
            role="tool",
            content=persisted_output,
            metadata=dict(metadata),
        )

    def _bind_turn_emitter(self, emit: EventEmitter, turn_id: str | None) -> EventEmitter:
        async def emit_with_turn(event: str, data: dict) -> None:
            payload = dict(data)
            if turn_id and "turn_id" not in payload:
                payload["turn_id"] = turn_id
            await emit(event, payload)

        return emit_with_turn

    def _apply_session_message_updates(self, session, updates: list[object]) -> None:
        for raw_update in updates:
            if not isinstance(raw_update, dict):
                continue
            message_id = str(raw_update.get("message_id") or "").strip()
            if not message_id:
                continue
            for message in session.messages:
                if message.id != message_id:
                    continue
                content = raw_update.get("content")
                if isinstance(content, str):
                    message.content = content
                metadata = raw_update.get("metadata")
                if isinstance(metadata, dict):
                    message.metadata = dict(metadata)
                break


def _coerce_int(value: object) -> int | None:
    if isinstance(value, int | float):
        return int(value)
    return None
