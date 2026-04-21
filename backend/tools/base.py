from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from backend.tools.result import ToolExecutionResult


ToolOutputEmitter = Callable[[str, str], Awaitable[None]]
ApprovalBehavior = Literal["safe", "confirmable"]


@dataclass
class ToolMeta:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: Literal["low", "medium", "high", "critical"]
    timeout_seconds: int
    approval_behavior: ApprovalBehavior = "safe"
    requires_approval: bool | None = None
    allowed_paths: list[str] | None = None
    provider_group: str = "core"
    alias_of: str | None = None

    def __post_init__(self) -> None:
        if self.requires_approval is not None:
            self.approval_behavior = "confirmable" if self.requires_approval else "safe"
        self.requires_approval = self.approval_behavior == "confirmable"


class BaseTool(ABC):
    meta: ToolMeta

    @abstractmethod
    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        raise NotImplementedError

    def validate_arguments(self, arguments: Any) -> str | None:
        return _validate_schema_value(arguments, self.meta.input_schema, "参数")

    async def run_streaming(
        self,
        arguments: dict[str, Any],
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        return await self.run(arguments, session_id)

    def to_provider_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.meta.name,
                "description": self.meta.description,
                "parameters": self.meta.input_schema,
            },
        }


def _validate_schema_value(value: Any, schema: Any, path: str) -> str | None:
    if not isinstance(schema, dict):
        return None

    schema_types = _schema_types(schema)
    if schema_types and not any(_matches_json_type(value, schema_type) for schema_type in schema_types):
        return f"{path} 必须是{_describe_types(schema_types)}"

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        return f"{path} 必须是 {', '.join(repr(item) for item in enum_values)} 之一"

    if isinstance(value, dict) and _should_validate_object(schema, schema_types):
        properties = schema.get("properties")
        known_properties = properties if isinstance(properties, dict) else {}

        for key in schema.get("required", []):
            if isinstance(key, str) and key not in value:
                return f"缺少必填参数: {_format_child_path(path, key)}"

        if schema.get("additionalProperties") is False:
            unknown_keys = [key for key in value if key not in known_properties]
            if unknown_keys:
                unknown_keys.sort()
                return f"存在未定义参数: {', '.join(_format_child_path(path, key) for key in unknown_keys)}"

        for key, child_schema in known_properties.items():
            if key not in value:
                continue
            error = _validate_schema_value(value[key], child_schema, _format_child_path(path, key))
            if error is not None:
                return error

    if isinstance(value, list) and _should_validate_array(schema, schema_types):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            return f"{path} 至少需要 {min_items} 项"

        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value, start=1):
                error = _validate_schema_value(item, item_schema, f"{path}[{index}]")
                if error is not None:
                    return error

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return f"{path} 至少需要 {min_length} 个字符"

    return None


def _schema_types(schema: dict[str, Any]) -> tuple[str, ...]:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return (schema_type,)
    if isinstance(schema_type, list):
        return tuple(item for item in schema_type if isinstance(item, str))
    return ()


def _matches_json_type(value: Any, schema_type: str) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "null":
        return value is None
    return True


def _describe_types(schema_types: tuple[str, ...]) -> str:
    labels = {
        "string": "字符串",
        "integer": "整数",
        "number": "数字",
        "boolean": "布尔值",
        "object": "对象",
        "array": "数组",
        "null": "null",
    }
    return " / ".join(labels.get(item, item) for item in schema_types)


def _should_validate_object(schema: dict[str, Any], schema_types: tuple[str, ...]) -> bool:
    return "object" in schema_types or (
        not schema_types and any(key in schema for key in ("properties", "required", "additionalProperties"))
    )


def _should_validate_array(schema: dict[str, Any], schema_types: tuple[str, ...]) -> bool:
    return "array" in schema_types or (not schema_types and "items" in schema)


def _format_child_path(path: str, key: str) -> str:
    if path == "参数":
        return key
    return f"{path}.{key}"
