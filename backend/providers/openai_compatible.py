from __future__ import annotations

import json
from collections.abc import AsyncIterator
from json import JSONDecodeError
from typing import Any

import httpx

from backend.config.schema import ModelConfig
from backend.providers.base import BaseProvider, ProviderChunk, ProviderError, ProviderResponse, TokenUsage, ToolCall
from backend.providers.token_estimator import estimate_message_tokens


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
                        if content := delta.get("content"):
                            yield ProviderChunk(type="text", delta=str(content), finish_reason=choice.get("finish_reason"))
                        for tool_call in delta.get("tool_calls", []) or []:
                            index = int(tool_call.get("index", 0))
                            current = partial_tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                            if tool_call.get("id"):
                                current["id"] = str(tool_call["id"])
                            function = tool_call.get("function") or {}
                            if function.get("name"):
                                current["name"] = str(function["name"])
                            if function.get("arguments"):
                                current["arguments"] += str(function["arguments"])
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
        return estimate_message_tokens(messages, model=self.config.model)


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
        "messages": messages,
        "max_tokens": kwargs.get("max_tokens", config.max_tokens),
        "temperature": kwargs.get("temperature", config.temperature),
        "stream": stream,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
    if tools:
        payload["tools"] = tools
    return payload


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
