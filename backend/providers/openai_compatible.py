from __future__ import annotations

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
DEFAULT_REASONING_CONTENT_FIELD = "reasoning_content"
INTERNAL_MESSAGE_KEYS = {"provider_state"}


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

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.endpoint.rstrip('/')}/chat/completions",
                    headers=_build_auth_headers(self.config.api_key),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for data in _iter_sse_json(response):
                        if data == "[DONE]":
                            break
                        if not isinstance(data, dict):
                            continue
                        choice = (data.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        usage = _parse_usage(data.get("usage", {})) if isinstance(data.get("usage"), dict) else None
                        _accumulate_response_provider_state(self.config, delta, provider_state)
                        if content := delta.get("content"):
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
                        finish_reason = choice.get("finish_reason")
                        if usage and usage.total_tokens > 0:
                            yield ProviderChunk(type="usage", usage=usage, finish_reason=finish_reason)
        except httpx.TimeoutException as exc:
            raise ProviderError("openai_compatible", "timeout_error", "OpenAI-compatible streaming request timed out", True) from exc
        except httpx.HTTPStatusError as exc:
            await _consume_error_response(exc.response)
            raise _http_error("openai_compatible", exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("openai_compatible", "network_error", f"OpenAI-compatible streaming failed: {exc}", True) from exc

        if provider_state:
            yield ProviderChunk(type="provider_state", provider_state=provider_state)
        for index in sorted(partial_tool_calls):
            item = partial_tool_calls[index]
            try:
                arguments = json.loads(item["arguments"] or "{}")
            except JSONDecodeError as exc:
                raise ProviderError("openai_compatible", "response_parse_error", f"OpenAI-compatible tool call arguments invalid: {exc}") from exc
            yield ProviderChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id=item["id"] or f"tool_{index}",
                    name=item["name"],
                    arguments=arguments,
                ),
            )
        yield ProviderChunk(type="done", finish_reason="stop")

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
    return payload


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
    return prepared


def _message_has_tool_calls(message: dict[str, Any]) -> bool:
    return message.get("role") == "assistant" and isinstance(message.get("tool_calls"), list) and bool(message.get("tool_calls"))


def _model_capabilities(config: ModelConfig) -> dict[str, Any]:
    profile = OPENAI_COMPATIBLE_MODEL_PROFILES.get(config.model, {})
    capabilities = _deep_merge_dicts(profile, config.capabilities if isinstance(config.capabilities, dict) else {})
    return capabilities


def _deep_merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


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
    fields = {DEFAULT_REASONING_CONTENT_FIELD}
    reasoning = _model_capabilities(config).get("reasoning")
    if isinstance(reasoning, dict):
        for key in ("response_field", "response_fields", "replay_field", "replay_fields", "field", "fields"):
            for field in _coerce_reasoning_field_names(reasoning.get(key)):
                if field.strip():
                    fields.add(field.strip())
    return fields


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


async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any] | str]:
    async for line in response.aiter_lines():
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
    try:
        text = response.text.strip()
    except httpx.ResponseNotRead:
        return {}
    if not text:
        return {}
    return {"response_text": text[:2_000]}


async def _consume_error_response(response: httpx.Response) -> None:
    try:
        await response.aread()
    except (httpx.StreamError, RuntimeError):
        return


def _build_auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}
