from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from copy import deepcopy
from json import JSONDecodeError
from typing import Any

import httpx

from backend.config.schema import ModelConfig
from backend.providers.base import BaseProvider, ProviderChunk, ProviderError, ProviderResponse, TokenUsage, ToolCall, ToolCallDelta
from backend.providers.token_estimator import estimate_message_tokens


OPENAI_COMPATIBLE_MODEL_PROFILES: dict[str, dict[str, Any]] = {
    "mimo-v2.5": {
        "reasoning": {
            "field": "reasoning_content",
            "replay_required": True,
        }
    }
}
OPENAI_COMPATIBLE_MODEL_PROFILE_PREFIXES: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "deepseek",
        {
            "provider": {
                "stream_idle_timeout_seconds": 300.0,
            },
            "messages": {
                "system_role_policy": "system_first_only",
            }
        },
    ),
)
DEFAULT_REASONING_CONTENT_FIELD = "reasoning_content"
DEFAULT_REASONING_RESPONSE_FIELDS = (
    DEFAULT_REASONING_CONTENT_FIELD,
    "reasoning",
)
INTERNAL_MESSAGE_KEYS = {"provider_state"}
RUNTIME_SYSTEM_NOTE_PREFIX = "Runtime system note:\n\n"
STREAM_DEBUG_SAMPLE_LIMIT = 6
STREAM_DEBUG_PREVIEW_CHARS = 160


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, config: ModelConfig):
        self.config = config

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        if not self.config.endpoint:
            raise ProviderError("openai_compatible", "configuration_error", "OpenAI-compatible provider requires endpoint")

        payload = _build_payload(self.config, messages, tools, stream=False, **kwargs)
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.config.endpoint.rstrip('/')}/chat/completions",
                    headers=_build_auth_headers(self.config.api_key),
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("openai_compatible", "timeout_error", "OpenAI-compatible request timed out", True) from exc
        except httpx.HTTPStatusError as exc:
            raise _http_error("openai_compatible", exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("openai_compatible", "network_error", f"OpenAI-compatible request failed: {exc}", True) from exc
        except JSONDecodeError as exc:
            raise ProviderError("openai_compatible", "response_parse_error", "OpenAI-compatible response JSON invalid") from exc

        try:
            choice = body["choices"][0]
            message = choice["message"]
            usage = _parse_usage(body.get("usage", {}))
            tool_calls = _parse_openai_tool_calls(message.get("tool_calls") or [])
            return ProviderResponse(
                content=message.get("content") or "",
                tool_calls=tool_calls,
                usage=usage,
                model=body.get("model", self.config.model),
                finish_reason=choice.get("finish_reason", "stop"),
                provider_state=_extract_response_provider_state(self.config, message),
            )
        except (KeyError, IndexError, TypeError, ValueError, JSONDecodeError) as exc:
            raise ProviderError("openai_compatible", "response_parse_error", f"OpenAI-compatible response malformed: {exc}") from exc

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProviderChunk]:
        if not self.config.endpoint:
            raise ProviderError("openai_compatible", "configuration_error", "OpenAI-compatible provider requires endpoint")

        payload = _build_payload(self.config, messages, tools, stream=True, **kwargs)
        partial_tool_calls: dict[int, dict[str, str]] = {}
        provider_state: dict[str, Any] = {}
        finish_reason = "stop"
        saw_done = False
        saw_content = False
        stream_debug_samples: list[dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=_streaming_http_timeout(self.config)) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.endpoint.rstrip('/')}/chat/completions",
                    headers=_build_auth_headers(self.config.api_key),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for data in _iter_sse_json(
                        response,
                        first_event_timeout_seconds=max(float(self.config.timeout), 1.0),
                        idle_timeout_seconds=_streaming_idle_timeout_seconds(self.config),
                    ):
                        if data == "[DONE]":
                            saw_done = True
                            break
                        if not isinstance(data, dict):
                            continue
                        choice = (data.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        usage = _parse_usage(data.get("usage", {})) if isinstance(data.get("usage"), dict) else None
                        _record_stream_debug_sample(self.config, choice, delta, stream_debug_samples)
                        _accumulate_response_provider_state(self.config, delta, provider_state)
                        if content := delta.get("content"):
                            saw_content = True
                            yield ProviderChunk(type="text", delta=str(content), finish_reason=choice.get("finish_reason"))
                        for tool_call in delta.get("tool_calls", []) or []:
                            index = int(tool_call.get("index", 0))
                            current = partial_tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            call_id = None
                            name = None
                            arguments_delta = ""
                            if tool_call.get("id"):
                                call_id = str(tool_call["id"])
                                current["id"] = call_id
                            function = tool_call.get("function") or {}
                            if function.get("name"):
                                name = str(function["name"])
                                current["name"] = name
                            if function.get("arguments"):
                                arguments_delta = str(function["arguments"])
                                current["arguments"] += arguments_delta
                            if call_id or name or arguments_delta:
                                yield ProviderChunk(
                                    type="tool_call_delta",
                                    tool_call_delta=ToolCallDelta(
                                        index=index,
                                        id=current["id"] or call_id,
                                        name=current["name"] or name,
                                        arguments_delta=arguments_delta,
                                    ),
                                    finish_reason=choice.get("finish_reason"),
                                )
                        if choice.get("finish_reason") is not None:
                            finish_reason = str(choice["finish_reason"])
                        if usage and usage.total_tokens > 0:
                            yield ProviderChunk(type="usage", usage=usage, finish_reason=finish_reason)
        except httpx.TimeoutException as exc:
            raise ProviderError("openai_compatible", "timeout_error", "OpenAI-compatible streaming request timed out", True) from exc
        except httpx.HTTPStatusError as exc:
            await _consume_error_response(exc.response)
            raise _http_error("openai_compatible", exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("openai_compatible", "network_error", f"OpenAI-compatible streaming failed: {exc}", True) from exc

        if not saw_done:
            raise ProviderError(
                "openai_compatible",
                "stream_incomplete",
                "OpenAI-compatible stream ended before [DONE] was received",
                True,
                details={"finish_reason": finish_reason},
            )

        if not saw_content and not partial_tool_calls:
            debug_payload = _build_stream_debug_payload(
                finish_reason=finish_reason,
                provider_state=provider_state,
                stream_debug_samples=stream_debug_samples,
            )
            if debug_payload:
                provider_state["_stream_debug"] = debug_payload
        if provider_state:
            yield ProviderChunk(type="provider_state", provider_state=provider_state)
        for index in sorted(partial_tool_calls):
            item = partial_tool_calls[index]
            try:
                arguments = json.loads(item["arguments"] or "{}")
            except JSONDecodeError as exc:
                invalid_name = item["name"] or "__invalid_tool_call__"
                yield ProviderChunk(
                    type="tool_call",
                    tool_call=ToolCall(
                        id=item["id"] or f"tool_{index}",
                        name=invalid_name,
                        arguments={
                            "__parse_error__": True,
                            "__raw_arguments__": item["arguments"],
                            "__error__": str(exc),
                        },
                    ),
                    finish_reason="invalid_tool_call",
                )
                continue
            yield ProviderChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id=item["id"] or f"tool_{index}",
                    name=item["name"],
                    arguments=arguments,
                ),
            )
        yield ProviderChunk(type="done", finish_reason=finish_reason)

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return estimate_message_tokens(_prepare_messages_for_payload(self.config, messages), model=self.config.model)


def _build_payload(
    config: ModelConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    stream: bool,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "messages": _prepare_messages_for_payload(config, messages),
        "max_tokens": kwargs.get("max_tokens", config.max_tokens),
        "temperature": kwargs.get("temperature", config.temperature),
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if tools:
        payload["tools"] = tools
    response_format = kwargs.get("response_format")
    if isinstance(response_format, dict):
        payload["response_format"] = response_format
    return payload


def _streaming_http_timeout(config: ModelConfig) -> httpx.Timeout:
    total_timeout = max(float(config.timeout), 1.0)
    return httpx.Timeout(total_timeout, connect=min(total_timeout, 10.0), read=None, write=total_timeout, pool=total_timeout)


def _streaming_idle_timeout_seconds(config: ModelConfig) -> float | None:
    capabilities = _model_capabilities(config)
    provider = capabilities.get("provider")
    if isinstance(provider, dict):
        raw = provider.get("stream_idle_timeout_seconds")
        parsed = _positive_timeout_or_none(raw)
        if parsed is not None:
            return parsed
    return max(float(config.timeout), 1.0)


def _positive_timeout_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() == "none":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def _prepare_messages_for_payload(config: ModelConfig, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replay_fields = _reasoning_replay_fields(config)
    prepared: list[dict[str, Any]] = []
    for message in messages:
        next_message = {key: value for key, value in message.items() if key not in INTERNAL_MESSAGE_KEYS}
        if replay_fields and _message_has_tool_calls(message):
            provider_state = message.get("provider_state")
            for replay_field in replay_fields:
                value = ""
                if isinstance(provider_state, dict):
                    raw_value = provider_state.get(replay_field)
                    if raw_value is not None:
                        value = str(raw_value)
                next_message[replay_field] = value
        prepared.append(next_message)
    return _normalize_messages_for_payload(config, prepared)


def _message_has_tool_calls(message: dict[str, Any]) -> bool:
    return message.get("role") == "assistant" and isinstance(message.get("tool_calls"), list) and bool(message.get("tool_calls"))


def _model_capabilities(config: ModelConfig) -> dict[str, Any]:
    profile = _model_profile(config.model)
    capabilities = _deep_merge_dicts(profile, config.capabilities if isinstance(config.capabilities, dict) else {})
    return capabilities


def _model_profile(model_name: str) -> dict[str, Any]:
    exact_profile = OPENAI_COMPATIBLE_MODEL_PROFILES.get(model_name)
    if isinstance(exact_profile, dict):
        return exact_profile
    normalized = model_name.strip().lower()
    for prefix, profile in OPENAI_COMPATIBLE_MODEL_PROFILE_PREFIXES:
        if normalized.startswith(prefix):
            return profile
    return {}


def _deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_messages_for_payload(config: ModelConfig, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if _system_role_policy(config) != "system_first_only":
        return messages

    normalized: list[dict[str, Any]] = []
    deferred_messages: list[dict[str, Any]] = []
    pending_tool_call_ids: set[str] = set()
    seen_system_message = False

    for message in messages:
        next_message = dict(message)

        if _message_has_tool_calls(next_message):
            if deferred_messages:
                normalized.extend(deferred_messages)
                deferred_messages = []
            normalized.append(next_message)
            pending_tool_call_ids = _assistant_tool_call_ids(next_message)
            continue

        if pending_tool_call_ids:
            if next_message.get("role") == "tool":
                normalized.append(next_message)
                tool_call_id = next_message.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id in pending_tool_call_ids:
                    pending_tool_call_ids.remove(tool_call_id)
                if not pending_tool_call_ids and deferred_messages:
                    normalized.extend(deferred_messages)
                    deferred_messages = []
                continue

            deferred_messages.append(_coerce_runtime_system_note(next_message))
            continue

        if next_message.get("role") != "system":
            normalized.append(next_message)
            continue

        if not seen_system_message:
            seen_system_message = True
            normalized.append(next_message)
            continue

        normalized.append(_coerce_runtime_system_note(next_message))

    if deferred_messages:
        normalized.extend(deferred_messages)
    return _drop_incomplete_tool_call_turns(normalized)


def _system_role_policy(config: ModelConfig) -> str:
    capabilities = _model_capabilities(config)
    direct_policy = capabilities.get("system_role_policy")
    if isinstance(direct_policy, str) and direct_policy.strip():
        return direct_policy.strip().lower()
    messages_capabilities = capabilities.get("messages")
    if isinstance(messages_capabilities, dict):
        nested_policy = messages_capabilities.get("system_role_policy")
        if isinstance(nested_policy, str) and nested_policy.strip():
            return nested_policy.strip().lower()
    return ""


def _assistant_tool_call_ids(message: dict[str, Any]) -> set[str]:
    if not _message_has_tool_calls(message):
        return set()
    ids: set[str] = set()
    for raw_tool_call in message.get("tool_calls") or []:
        if not isinstance(raw_tool_call, dict):
            continue
        tool_call_id = raw_tool_call.get("id")
        if isinstance(tool_call_id, str) and tool_call_id:
            ids.add(tool_call_id)
    return ids


def _drop_incomplete_tool_call_turns(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    index = 0
    total = len(messages)
    while index < total:
        message = messages[index]
        if not _message_has_tool_calls(message):
            normalized.append(message)
            index += 1
            continue

        pending_ids = _assistant_tool_call_ids(message)
        if not pending_ids:
            normalized.append(message)
            index += 1
            continue

        block: list[dict[str, Any]] = [message]
        cursor = index + 1
        while cursor < total:
            next_message = messages[cursor]
            if next_message.get("role") == "tool":
                tool_call_id = next_message.get("tool_call_id")
                block.append(next_message)
                if isinstance(tool_call_id, str) and tool_call_id in pending_ids:
                    pending_ids.remove(tool_call_id)
                cursor += 1
                if not pending_ids:
                    break
                continue
            break

        if pending_ids:
            index = cursor
            continue

        normalized.extend(block)
        index = cursor
    return normalized


def _coerce_runtime_system_note(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("role") != "system":
        return message
    content = message.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False) if content is not None else ""
    return {
        **message,
        "role": "user",
        "content": f"{RUNTIME_SYSTEM_NOTE_PREFIX}{content}",
    }


def _coerce_reasoning_field_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if isinstance(item, str)]
    return []


def _dedupe_reasoning_field_names(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        field = value.strip()
        if not field or field in seen:
            continue
        seen.add(field)
        result.append(field)
    return result


def _reasoning_replay_fields(config: ModelConfig) -> list[str]:
    reasoning = _model_capabilities(config).get("reasoning")
    if not isinstance(reasoning, dict) or not bool(reasoning.get("replay_required")):
        return []
    fields: list[str] = []
    for key in ("replay_field", "replay_fields", "field", "fields"):
        fields.extend(_coerce_reasoning_field_names(reasoning.get(key)))
    if not fields:
        fields.append(DEFAULT_REASONING_CONTENT_FIELD)
    return _dedupe_reasoning_field_names(fields)


def _reasoning_response_fields(config: ModelConfig) -> set[str]:
    fields = set(DEFAULT_REASONING_RESPONSE_FIELDS)
    reasoning = _model_capabilities(config).get("reasoning")
    if isinstance(reasoning, dict):
        for key in ("response_field", "response_fields", "replay_field", "replay_fields", "field", "fields"):
            for field in _coerce_reasoning_field_names(reasoning.get(key)):
                if field.strip():
                    fields.add(field.strip())
    return fields


def _truncate_stream_debug_value(value: Any, limit: int = STREAM_DEBUG_PREVIEW_CHARS) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _record_stream_debug_sample(
    config: ModelConfig,
    choice: dict[str, Any],
    delta: dict[str, Any],
    samples: list[dict[str, Any]],
) -> None:
    if len(samples) >= STREAM_DEBUG_SAMPLE_LIMIT:
        return

    sample: dict[str, Any] = {
        "finish_reason": choice.get("finish_reason"),
        "choice_keys": sorted(str(key) for key in choice.keys()),
        "delta_keys": sorted(str(key) for key in delta.keys()),
    }

    reasoning_fields: dict[str, dict[str, Any]] = {}
    for field in sorted(_reasoning_response_fields(config)):
        if field not in delta:
            continue
        value = delta.get(field)
        reasoning_fields[field] = {
            "type": type(value).__name__,
            "preview": _truncate_stream_debug_value(value),
            "length": len(str(value or "")),
        }
    if reasoning_fields:
        sample["reasoning_fields"] = reasoning_fields

    content = delta.get("content")
    if content is not None:
        sample["content_type"] = type(content).__name__
        sample["content_preview"] = _truncate_stream_debug_value(content)
        sample["content_length"] = len(str(content or ""))

    tool_calls = delta.get("tool_calls")
    if isinstance(tool_calls, list):
        sample["tool_call_count"] = len(tool_calls)

    samples.append(sample)


def _build_stream_debug_payload(
    *,
    finish_reason: str,
    provider_state: dict[str, Any],
    stream_debug_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "finish_reason": finish_reason,
        "provider_state_keys": sorted(str(key) for key in provider_state.keys() if not str(key).startswith("_")),
    }
    if stream_debug_samples:
        payload["samples"] = stream_debug_samples
    return payload


def _extract_response_provider_state(config: ModelConfig, message: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    _accumulate_response_provider_state(config, message, state)
    return state


def _accumulate_response_provider_state(config: ModelConfig, delta: dict[str, Any], state: dict[str, Any]) -> None:
    for field in _reasoning_response_fields(config):
        if field not in delta:
            continue
        value = delta.get(field)
        existing = state.get(field)
        if isinstance(existing, str):
            state[field] = existing + str(value or "")
        else:
            state[field] = str(value or "")


def _parse_usage(usage_raw: dict[str, Any]) -> TokenUsage:
    return TokenUsage(
        input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        total_tokens=int(usage_raw.get("total_tokens", 0) or 0),
    )


def _parse_openai_tool_calls(raw_calls: list[dict[str, Any]] | None) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for tool in raw_calls or []:
        tool_calls.append(
            ToolCall(
                id=str(tool["id"]),
                name=str(tool["function"]["name"]),
                arguments=json.loads(tool["function"].get("arguments") or "{}"),
            )
        )
    return tool_calls


async def _iter_sse_json(
    response: httpx.Response,
    *,
    first_event_timeout_seconds: float | None,
    idle_timeout_seconds: float | None,
) -> AsyncIterator[dict[str, Any] | str]:
    iterator = response.aiter_lines().__aiter__()
    saw_any_line = False
    while True:
        timeout_seconds = first_event_timeout_seconds if not saw_any_line else idle_timeout_seconds
        try:
            if timeout_seconds is None:
                line = await iterator.__anext__()
            else:
                line = await asyncio.wait_for(iterator.__anext__(), timeout=timeout_seconds)
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError as exc:
            raise ProviderError(
                "openai_compatible",
                "timeout_error",
                "OpenAI-compatible streaming request timed out",
                True,
                details={
                    "timeout_phase": "first_event" if not saw_any_line else "idle",
                    "timeout_seconds": timeout_seconds,
                },
            ) from exc

        saw_any_line = True
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        if payload == "[DONE]":
            yield payload
            continue
        try:
            yield json.loads(payload)
        except JSONDecodeError as exc:
            raise ProviderError("openai_compatible", "response_parse_error", f"OpenAI-compatible stream payload invalid: {exc}") from exc


def _http_error(provider: str, exc: httpx.HTTPStatusError) -> ProviderError:
    status_code = exc.response.status_code
    details = _response_error_details(exc.response)
    if status_code in {401, 403}:
        return ProviderError(provider, "auth_error", f"{provider} authentication failed", False, status_code=status_code, details=details)
    if status_code == 429:
        return ProviderError(provider, "rate_limit_error", f"{provider} rate limited", True, status_code=status_code, details=details)
    if status_code >= 500:
        return ProviderError(provider, "upstream_error", f"{provider} upstream server error", True, status_code=status_code, details=details)
    return ProviderError(provider, "request_error", f"{provider} request failed with status {status_code}", False, status_code=status_code, details=details)


def _response_error_details(response: httpx.Response) -> dict[str, Any]:
    details = _rate_limit_header_details(response.headers)
    try:
        text = response.text.strip()
    except httpx.ResponseNotRead:
        return details
    if text:
        details["response_text"] = text[:2_000]
    return details


def _rate_limit_header_details(headers: httpx.Headers) -> dict[str, Any]:
    details: dict[str, Any] = {}
    rate_limit_headers: dict[str, str] = {}
    for key, value in headers.items():
        normalized = key.lower()
        if normalized == "retry-after":
            details["retry_after"] = value
            try:
                details["retry_after_seconds"] = max(0.0, float(value.strip()))
            except ValueError:
                pass
        if normalized.startswith("x-ratelimit-"):
            rate_limit_headers[normalized] = value
    if rate_limit_headers:
        details["rate_limit_headers"] = rate_limit_headers
    return details


async def _consume_error_response(response: httpx.Response) -> None:
    try:
        await response.aread()
    except (httpx.StreamError, RuntimeError):
        return


def _build_auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}
