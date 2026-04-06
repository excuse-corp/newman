from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDescriptor:
    code: str
    severity: str
    message: str


SUCCESS = ErrorDescriptor("NEWMAN-OK-000", "info", "成功")

TOOL_ERROR_MAP = {
    "timeout_error": ErrorDescriptor("NEWMAN-TOOL-001", "warning", "工具执行超时"),
    "validation_error": ErrorDescriptor("NEWMAN-TOOL-002", "warning", "工具输入或目标无效"),
    "permission_error": ErrorDescriptor("NEWMAN-TOOL-003", "error", "工具权限受限"),
    "command_not_found": ErrorDescriptor("NEWMAN-TOOL-004", "warning", "命令不存在"),
    "user_rejected": ErrorDescriptor("NEWMAN-TOOL-005", "info", "审批被拒绝或超时"),
    "runtime_exception": ErrorDescriptor("NEWMAN-TOOL-006", "error", "工具执行异常"),
    "fatal_error": ErrorDescriptor("NEWMAN-TOOL-007", "error", "工具发生致命错误"),
}

DEFAULT_TOOL_ERROR = ErrorDescriptor("NEWMAN-TOOL-999", "error", "未知工具错误")

API_ERROR_MAP = {
    "validation": ErrorDescriptor("NEWMAN-API-001", "warning", "请求参数无效"),
    "not_found": ErrorDescriptor("NEWMAN-API-002", "warning", "请求资源不存在"),
    "conflict": ErrorDescriptor("NEWMAN-API-003", "warning", "请求与当前状态冲突"),
    "internal": ErrorDescriptor("NEWMAN-API-999", "error", "服务内部错误"),
}


def resolve_tool_error(category: str, success: bool) -> ErrorDescriptor:
    if success:
        return SUCCESS
    return TOOL_ERROR_MAP.get(category, DEFAULT_TOOL_ERROR)


def resolve_api_error(kind: str) -> ErrorDescriptor:
    return API_ERROR_MAP.get(kind, API_ERROR_MAP["internal"])
