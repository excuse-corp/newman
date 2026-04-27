from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDescriptor:
    code: str
    severity: str
    risk_level: str
    message: str
    recovery_class: str
    recommended_next_step: str


SUCCESS = ErrorDescriptor(
    "NEWMAN-OK-000",
    "info",
    "low",
    "成功",
    "none",
    "Continue with the next planned step.",
)

TOOL_ERROR_MAP = {
    "timeout_error": ErrorDescriptor(
        "NEWMAN-TOOL-001",
        "warning",
        "medium",
        "工具执行超时",
        "recoverable",
        "Check whether the action is temporarily slow, then retry the smallest necessary step.",
    ),
    "validation_error": ErrorDescriptor(
        "NEWMAN-TOOL-002",
        "warning",
        "low",
        "工具输入或目标无效",
        "recoverable",
        "Correct the invalid argument or path, then retry only the failing action.",
    ),
    "permission_error": ErrorDescriptor(
        "NEWMAN-TOOL-003",
        "error",
        "high",
        "工具权限受限",
        "recoverable",
        "Choose a permitted path or lower-risk action, or ask the user for approval.",
    ),
    "command_not_found": ErrorDescriptor(
        "NEWMAN-TOOL-004",
        "warning",
        "medium",
        "命令不存在",
        "recoverable",
        "Verify the command exists in the environment, or use an available alternative.",
    ),
    "user_rejected": ErrorDescriptor(
        "NEWMAN-TOOL-005",
        "warning",
        "medium",
        "审批被拒绝或超时",
        "fatal",
        "Stop this action and wait for explicit user approval or pick a non-privileged alternative.",
    ),
    "runtime_exception": ErrorDescriptor(
        "NEWMAN-TOOL-006",
        "error",
        "high",
        "工具执行异常",
        "fatal",
        "Stop the current action, inspect the error details, and surface the blocker clearly.",
    ),
    "fatal_error": ErrorDescriptor(
        "NEWMAN-TOOL-007",
        "error",
        "critical",
        "工具发生致命错误",
        "fatal",
        "Stop the current round and surface the blocking issue to the user.",
    ),
    "network_error": ErrorDescriptor(
        "NEWMAN-TOOL-008",
        "warning",
        "medium",
        "网络请求失败",
        "recoverable",
        "Wait briefly and retry once; if it still fails, reduce scope or switch strategy.",
    ),
    "auth_error": ErrorDescriptor(
        "NEWMAN-TOOL-009",
        "error",
        "critical",
        "认证失败",
        "fatal",
        "Stop and ask for valid credentials or provider access before continuing.",
    ),
    "configuration_error": ErrorDescriptor(
        "NEWMAN-TOOL-010",
        "error",
        "high",
        "运行配置无效",
        "fatal",
        "Stop and fix the configuration before retrying this round.",
    ),
    "response_parse_error": ErrorDescriptor(
        "NEWMAN-TOOL-011",
        "error",
        "high",
        "上游响应无法解析",
        "fatal",
        "Stop and inspect the upstream response format before continuing.",
    ),
    "rate_limit_error": ErrorDescriptor(
        "NEWMAN-TOOL-012",
        "warning",
        "medium",
        "请求触发频率限制",
        "recoverable",
        "Back off briefly and retry later with a smaller or slower request rate.",
    ),
    "upstream_error": ErrorDescriptor(
        "NEWMAN-TOOL-013",
        "warning",
        "medium",
        "上游服务暂时不可用",
        "recoverable",
        "Retry after a short delay; if the failure repeats, report the upstream outage.",
    ),
    "request_error": ErrorDescriptor(
        "NEWMAN-TOOL-014",
        "error",
        "high",
        "请求被上游拒绝",
        "fatal",
        "Stop and correct the request shape or required parameters before retrying.",
    ),
    "empty_response": ErrorDescriptor(
        "NEWMAN-TOOL-015",
        "warning",
        "medium",
        "主模型响应异常",
        "recoverable",
        "Retry the request; if it keeps returning no content, inspect the gateway and streaming response path.",
    ),
}

DEFAULT_TOOL_ERROR = ErrorDescriptor(
    "NEWMAN-TOOL-999",
    "error",
    "high",
    "未知工具错误",
    "fatal",
    "Stop and inspect the raw output before deciding the next action.",
)

API_ERROR_MAP = {
    "validation": ErrorDescriptor(
        "NEWMAN-API-001",
        "warning",
        "low",
        "请求参数无效",
        "recoverable",
        "Correct the request payload and submit it again.",
    ),
    "not_found": ErrorDescriptor(
        "NEWMAN-API-002",
        "warning",
        "low",
        "请求资源不存在",
        "recoverable",
        "Check the target identifier or path, then retry.",
    ),
    "conflict": ErrorDescriptor(
        "NEWMAN-API-003",
        "warning",
        "medium",
        "请求与当前状态冲突",
        "recoverable",
        "Refresh the current state and retry with the latest data.",
    ),
    "internal": ErrorDescriptor(
        "NEWMAN-API-999",
        "error",
        "high",
        "服务内部错误",
        "fatal",
        "Inspect the server error details before retrying.",
    ),
}


def resolve_tool_error(category: str, success: bool) -> ErrorDescriptor:
    if success:
        return SUCCESS
    return TOOL_ERROR_MAP.get(category, DEFAULT_TOOL_ERROR)


def resolve_api_error(kind: str) -> ErrorDescriptor:
    return API_ERROR_MAP.get(kind, API_ERROR_MAP["internal"])
