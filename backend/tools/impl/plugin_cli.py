from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from backend.plugin_runtime.models import PluginCLIConfirmationProtocolConfig, ResolvedPluginCLICommand
from backend.sessions.models import SessionRecord
from backend.tools.base import BaseTool, ToolMeta, ToolOutputEmitter
from backend.tools.discovery import BuiltinToolContext
from backend.tools.result import ToolExecutionResult


READONLY_VERB_MARKERS = (
    "list",
    "search",
    "get",
    "fetch",
    "query",
    "preview",
    "download",
    "read",
    "status",
    "show",
    "mget",
    "detail",
    "export",
)
MUTATING_VERB_MARKERS = (
    "create",
    "update",
    "delete",
    "remove",
    "insert",
    "upload",
    "send",
    "reply",
    "write",
    "set",
    "move",
    "copy",
    "import",
    "assign",
    "add",
    "reopen",
    "complete",
    "comment",
    "replace",
    "init",
    "login",
    "subscribe",
    "unsubscribe",
    "leave",
    "join",
    "cancel",
)
LARK_DEFAULT_IM_USER_ID_ENV = "NEWMAN_LARK_DEFAULT_IM_USER_ID"


class PluginCLICommandTool(BaseTool):
    def __init__(self, command: ResolvedPluginCLICommand, sandbox, session_store=None) -> None:
        self.command = command
        self.sandbox = sandbox
        self.session_store = session_store
        properties: dict[str, Any] = {
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Only the argv tail after the executable. Do not repeat the executable itself.",
            },
        }
        if command.allow_stdin:
            properties["stdin"] = {
                "type": "string",
                "description": "Optional UTF-8 stdin payload passed directly to the command.",
            }
        if command.confirmation_flag:
            properties["confirm"] = {
                "type": "boolean",
                "description": (
                    f"Append `{command.confirmation_flag}` for high-risk commands after explicit user approval."
                ),
            }

        description = command.description.strip() or (
            f"Run the approved `{command.executable}` wrapper from plugin `{command.plugin_name}` "
            "using structured argv instead of a shell string."
        )
        allowed_paths = sorted({*command.readable_roots, *command.writable_roots}) or None
        self.meta = ToolMeta(
            name=command.tool_name,
            description=description,
            input_schema={
                "type": "object",
                "properties": properties,
                "required": ["args"],
                "additionalProperties": False,
            },
            risk_level="high" if command.approval_behavior == "confirmable" else "medium",
            approval_behavior=command.approval_behavior,
            timeout_seconds=command.timeout_seconds,
            allowed_paths=allowed_paths,
        )

    def validate_arguments(self, arguments: Any) -> str | None:
        error = super().validate_arguments(arguments)
        if error is not None:
            return error
        if not isinstance(arguments, dict):
            return None
        args = arguments.get("args")
        if not isinstance(args, list):
            return None
        executable_name = Path(self.command.executable).name
        if args and str(args[0]).strip() in {self.command.executable, executable_name}:
            return "args 不要包含可执行文件本身，只传它后面的参数"
        if arguments.get("confirm") and not self.command.confirmation_flag:
            return "当前命令未声明 confirm 能力"
        if not self.command.allow_stdin and arguments.get("stdin") is not None:
            return "当前命令不接受 stdin"
        return None

    def static_checks(self, arguments: dict[str, Any]) -> list[str]:
        if self.command.approval_behavior == "confirmable":
            return []
        args = _coerce_args(arguments)
        return [] if _is_readonly_invocation(args, self.command.readonly_prefixes) else ["plugin_cli_mutating"]

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        return await self._execute(arguments, session_id=session_id)

    async def run_streaming(
        self,
        arguments: dict[str, Any],
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        return await self._execute(arguments, session_id=session_id, emit_output=emit_output)

    async def _execute(
        self,
        arguments: dict[str, Any],
        *,
        session_id: str,
        emit_output: ToolOutputEmitter | None = None,
    ) -> ToolExecutionResult:
        args = _coerce_args(arguments)
        preflight_metadata: dict[str, Any] = {}
        args, default_im_user_id = _apply_default_lark_im_recipient(args, self.command.env)
        if default_im_user_id is not None:
            preflight_metadata["plugin_cli_default_im_user_id"] = default_im_user_id
        preflight_error = await self._run_preflight(args, session_id=session_id, metadata=preflight_metadata)
        if preflight_error is not None:
            preflight_error.tool = self.meta.name
            preflight_error.metadata.update(preflight_metadata)
            return preflight_error

        argv = [self.command.executable, *self.command.default_args, *args]
        confirm = bool(arguments.get("confirm"))
        if confirm and self.command.confirmation_flag:
            argv.append(self.command.confirmation_flag)

        stdin_text = arguments.get("stdin")
        result = await self.sandbox.execute_argv(
            argv,
            emit_output=emit_output,
            env=self.command.env,
            stdin_text=stdin_text if isinstance(stdin_text, str) else None,
            extra_readable_roots=[Path(path) for path in self.command.readable_roots],
            extra_writable_roots=[Path(path) for path in self.command.writable_roots],
        )
        result.tool = self.meta.name
        result.action = shlex.join(argv)
        result.metadata.update(
            {
                "plugin_name": self.command.plugin_name,
                "plugin_tool_name": self.command.tool_name,
                "plugin_executable": self.command.executable,
                "plugin_argv": argv,
                "plugin_command_readonly": _is_readonly_invocation(args, self.command.readonly_prefixes),
                **preflight_metadata,
            }
        )
        _decorate_confirmation_required(result, self.command)
        return result

    async def _run_preflight(
        self,
        args: list[str],
        *,
        session_id: str,
        metadata: dict[str, Any],
    ) -> ToolExecutionResult | None:
        if not _is_feishu_cli_command(self.command):
            return None

        if _is_lark_im_invocation(args):
            shared_check = self._ensure_lark_shared_read(session_id)
            if shared_check is not None:
                return shared_check
            metadata["plugin_cli_lark_shared_verified"] = True

        if _uses_explicit_user_identity(args) and not _is_auth_status_invocation(args):
            status_result = await self._run_auth_status()
            if not status_result.success:
                status_result.summary = "执行 user 身份命令前的 lark-cli auth status 检查失败"
                status_result.metadata["plugin_cli_auth_status_preflight"] = True
                return status_result

            payload = _parse_json_object(status_result.stdout) or _parse_json_object(status_result.stderr)
            if payload is None:
                return ToolExecutionResult(
                    success=False,
                    tool=self.meta.name,
                    action="lark-cli auth status",
                    category="response_parse_error",
                    summary="无法解析 lark-cli auth status 输出，无法判断 user token 是否需要刷新",
                    retryable=False,
                    stdout=status_result.stdout,
                    stderr=status_result.stderr,
                    metadata={"plugin_cli_auth_status_preflight": True},
                )

            user_identity = _extract_user_identity(payload)
            if user_identity is None:
                return ToolExecutionResult(
                    success=False,
                    tool=self.meta.name,
                    action="lark-cli auth status",
                    category="auth_error",
                    summary="lark-cli user 身份不可用；请先完成用户授权或检查当前登录状态",
                    retryable=False,
                    stdout=status_result.stdout,
                    stderr=status_result.stderr,
                    metadata={"plugin_cli_auth_status_preflight": True},
                )

            metadata.update(
                {
                    "plugin_cli_auth_status_preflight": True,
                    "plugin_cli_user_identity_status": user_identity.get("status"),
                    "plugin_cli_user_identity_token_status": user_identity.get("tokenStatus"),
                }
            )

            if _identity_needs_refresh(user_identity):
                metadata["plugin_cli_user_identity_needs_refresh"] = True
                lark_cli_root = Path("~/.lark-cli").expanduser()
                if not _path_is_writable_via_roots(lark_cli_root, self.command.writable_roots):
                    return ToolExecutionResult(
                        success=False,
                        tool=self.meta.name,
                        action="lark-cli auth status",
                        category="configuration_error",
                        summary=(
                            "lark-cli user 身份需要刷新 token，但插件沙箱未给 ~/.lark-cli 写权限；"
                            "请为 feishu-cli 插件补 writable_roots 后再重试"
                        ),
                        retryable=False,
                        stdout=status_result.stdout,
                        stderr=status_result.stderr,
                        metadata={
                            "plugin_cli_auth_status_preflight": True,
                            "plugin_cli_user_identity_needs_refresh": True,
                        },
                    )

        return None

    def _ensure_lark_shared_read(self, session_id: str) -> ToolExecutionResult | None:
        if self.session_store is None:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="session_preflight",
                category="validation_error",
                summary="当前运行时无法校验 lark-shared 前置条件；使用 lark-im 相关命令前必须先读取 lark-shared/SKILL.md",
                retryable=False,
            )
        try:
            session = self.session_store.get(session_id)
        except FileNotFoundError:
            return ToolExecutionResult(
                success=False,
                tool=self.meta.name,
                action="session_preflight",
                category="validation_error",
                summary="当前会话不存在，无法校验 lark-shared 前置条件",
                retryable=False,
            )
        if _session_has_completed_lark_shared_read(session):
            return None
        return ToolExecutionResult(
            success=False,
            tool=self.meta.name,
            action="session_preflight",
            category="validation_error",
            summary="使用 lark-im 相关命令前，必须先读取 lark-shared/SKILL.md 并完成其认证前置步骤",
            retryable=False,
        )

    async def _run_auth_status(self) -> ToolExecutionResult:
        result = await self.sandbox.execute_argv(
            [self.command.executable, "auth", "status"],
            env=self.command.env,
            extra_readable_roots=[Path(path) for path in self.command.readable_roots],
            extra_writable_roots=[Path(path) for path in self.command.writable_roots],
        )
        result.tool = self.meta.name
        result.action = "lark-cli auth status"
        return result


def _coerce_args(arguments: dict[str, Any]) -> list[str]:
    args = arguments.get("args")
    if not isinstance(args, list):
        return []
    return [str(item) for item in args]


def _is_feishu_cli_command(command: ResolvedPluginCLICommand) -> bool:
    return command.plugin_name == "feishu-cli" and Path(command.executable).name == "lark-cli"


def _is_lark_im_invocation(args: list[str]) -> bool:
    lowered = [item.strip().lower() for item in args if str(item).strip()]
    return bool(lowered) and lowered[0] == "im"


def _is_lark_im_messages_send_invocation(args: list[str]) -> bool:
    lowered = [item.strip().lower() for item in args if str(item).strip()]
    return lowered[:2] == ["im", "+messages-send"]


def _apply_default_lark_im_recipient(args: list[str], env: dict[str, str]) -> tuple[list[str], str | None]:
    if not _is_lark_im_messages_send_invocation(args):
        return args, None
    lowered = [item.strip().lower() for item in args]
    if "--chat-id" in lowered or "--user-id" in lowered:
        return args, None
    default_user_id = str(env.get(LARK_DEFAULT_IM_USER_ID_ENV, "")).strip()
    if not default_user_id or not default_user_id.startswith("ou_"):
        return args, None
    return [*args, "--user-id", default_user_id], default_user_id


def _uses_explicit_user_identity(args: list[str]) -> bool:
    lowered = [item.strip().lower() for item in args]
    for index, token in enumerate(lowered):
        if token == "--as" and index + 1 < len(lowered):
            return lowered[index + 1] == "user"
    return False


def _is_auth_status_invocation(args: list[str]) -> bool:
    lowered = [item.strip().lower() for item in args if str(item).strip()]
    return lowered[:2] == ["auth", "status"]


def _session_has_completed_lark_shared_read(session: SessionRecord) -> bool:
    lark_shared_skill_reads = _completed_lark_shared_skill_reads(session)
    for message in session.messages:
        if message.role != "tool":
            continue
        tool_name = str(message.metadata.get("tool", "")).strip()
        if tool_name == "read_file" and _is_lark_shared_skill_path(message.metadata.get("path")):
            return True
        if (
            tool_name == "lark_cli_skill"
            and bool(message.metadata.get("success"))
            and _tool_call_matches(message.metadata.get("tool_call_id"), lark_shared_skill_reads)
        ):
            return True
    return False


def _completed_lark_shared_skill_reads(session: SessionRecord) -> set[str]:
    matching_ids: set[str] = set()
    for message in session.messages:
        if message.role != "assistant":
            continue
        tool_calls = message.metadata.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            if str(tool_call.get("name", "")).strip() != "lark_cli_skill":
                continue
            tool_call_id = str(tool_call.get("id", "")).strip()
            if not tool_call_id:
                continue
            arguments = tool_call.get("arguments")
            if _is_lark_shared_skill_read_args(arguments):
                matching_ids.add(tool_call_id)
    return matching_ids


def _is_lark_shared_skill_read_args(arguments: object) -> bool:
    if not isinstance(arguments, dict):
        return False
    args = arguments.get("args")
    if not isinstance(args, list) or len(args) < 2:
        return False
    normalized = [str(item).strip().lower() for item in args if str(item).strip()]
    return normalized[:2] == ["read", "lark-shared"]


def _tool_call_matches(value: object, candidates: set[str]) -> bool:
    if not candidates or not isinstance(value, str):
        return False
    return value.strip() in candidates


def _is_lark_shared_skill_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parts = _normalized_path_parts(value)
    return len(parts) >= 2 and parts[-2:] == ("lark-shared", "SKILL.md")


def _normalized_path_parts(value: str) -> tuple[str, ...]:
    try:
        return tuple(Path(value).expanduser().resolve().parts)
    except OSError:
        return tuple(Path(value).expanduser().parts)


def _parse_json_object(payload: str) -> dict[str, Any] | None:
    raw = (payload or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_user_identity(payload: dict[str, Any]) -> dict[str, Any] | None:
    identities = payload.get("identities")
    if not isinstance(identities, dict):
        return None
    user_identity = identities.get("user")
    return user_identity if isinstance(user_identity, dict) else None


def _identity_needs_refresh(identity: dict[str, Any]) -> bool:
    status = str(identity.get("status", "")).strip().lower()
    token_status = str(identity.get("tokenStatus", "")).strip().lower()
    return status == "needs_refresh" or token_status == "needs_refresh"


def _path_is_writable_via_roots(target: Path, roots: list[str]) -> bool:
    try:
        resolved_target = target.expanduser().resolve()
    except OSError:
        resolved_target = target.expanduser()
    for raw_root in roots:
        try:
            resolved_root = Path(raw_root).expanduser().resolve()
        except OSError:
            resolved_root = Path(raw_root).expanduser()
        if resolved_target == resolved_root or resolved_target.is_relative_to(resolved_root):
            return True
    return False


def _is_readonly_invocation(args: list[str], readonly_prefixes: list[list[str]]) -> bool:
    lowered = [item.strip().lower() for item in args if str(item).strip()]
    if not lowered:
        return False
    if "--dry-run" in lowered:
        return True
    if _matches_prefix(lowered, readonly_prefixes):
        return True
    if lowered[0] in {"doctor", "schema"}:
        return True
    if lowered[0] == "auth" and len(lowered) >= 2 and lowered[1] in {"status", "qrcode"}:
        return True

    command_tokens = [token.lstrip("+") for token in lowered if token and not token.startswith("-")]
    if any(_looks_like_mutating_token(token) for token in command_tokens):
        return False
    return any(_looks_like_readonly_token(token) for token in command_tokens)


def _matches_prefix(args: list[str], readonly_prefixes: list[list[str]]) -> bool:
    for prefix in readonly_prefixes:
        lowered_prefix = [item.strip().lower() for item in prefix if str(item).strip()]
        if lowered_prefix and args[: len(lowered_prefix)] == lowered_prefix:
            return True
    return False


def _looks_like_readonly_token(token: str) -> bool:
    normalized = token.replace("_", "-")
    return any(marker in normalized for marker in READONLY_VERB_MARKERS)


def _looks_like_mutating_token(token: str) -> bool:
    normalized = token.replace("_", "-")
    return any(marker in normalized for marker in MUTATING_VERB_MARKERS)


def _decorate_confirmation_required(result: ToolExecutionResult, command: ResolvedPluginCLICommand) -> None:
    payload = _parse_confirmation_required(
        result.stderr,
        result.exit_code,
        command.confirmation_protocol,
    )
    if payload is None or not command.confirmation_flag:
        return
    error = payload.get("error")
    risk = error.get("risk") if isinstance(error, dict) else {}
    action = risk.get("action") if isinstance(risk, dict) else None
    result.category = "user_input_required"
    result.retryable = False
    result.summary = "CLI 需要显式确认；征得用户同意后请设置 confirm=true 重试"
    result.recommended_next_step = "征得用户同意后，使用相同参数并设置 confirm=true 重试"
    result.metadata.update(
        {
            "plugin_cli_confirmation_required": True,
            "plugin_cli_confirmation_flag": command.confirmation_flag,
            "plugin_cli_confirmation_action": action,
            "plugin_cli_confirmation_protocol": command.confirmation_protocol.model_dump(mode="json"),
        }
    )


def _parse_confirmation_required(
    stderr: str,
    exit_code: int | None,
    protocol: PluginCLIConfirmationProtocolConfig,
) -> dict[str, Any] | None:
    if exit_code != protocol.exit_code:
        return None
    payload = (stderr or "").strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if not isinstance(error, dict) or error.get("type") != protocol.error_type:
        return None
    return parsed


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    service = getattr(context, "plugin_service", None)
    if service is None:
        return []
    sandbox = getattr(context, "sandbox", None)
    if sandbox is None:
        return []
    session_store = getattr(context, "session_store", None)
    return [PluginCLICommandTool(command, sandbox, session_store=session_store) for command in service.enabled_cli_commands()]
