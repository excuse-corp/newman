from __future__ import annotations

import json
from collections.abc import AsyncIterator
from json import JSONDecodeError
from typing import Any

import httpx

from backend.config.schema import ModelConfig
from backend.providers.base import BaseProvider, ProviderChunk, ProviderError, ProviderResponse, TokenUsage, ToolCall
from backend.providers.token_estimator import estimate_message_tokens


class AnthropicCompatibleProvider(BaseProvider):
    def __init__(self, config: ModelConfig):
        self.config = config

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        if not self.config.endpoint:
            raise ProviderError("anthropic_compatible", "configuration_error", "Anthropic-compatible provider requires endpoint")

        payload = _build_payload(self.config, messages, tools, stream=False, **kwargs)
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.config.endpoint.rstrip('/')}/messages",
                    headers=_build_auth_headers(self.config.api_key),
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("anthropic_compatible", "timeout_error", "Anthropic-compatible request timed out", True) from exc
        except httpx.HTTPStatusError as exc:
            raise _http_error("anthropic_compatible", exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("anthropic_compatible", "network_error", f"Anthropic-compatible request failed: {exc}", True) from exc
        except JSONDecodeError as exc:
            raise ProviderError("anthropic_compatible", "response_parse_error", "Anthropic-compatible response JSON invalid") from exc

        try:
            content_blocks = body.get("content", [])
            text_parts = [block.get("text", "") for block in content_blocks if block.get("type") == "text"]
            tool_calls = _parse_anthropic_tool_calls(content_blocks)
            usage_raw = body.get("usage", {})
            return ProviderResponse(
                content="".join(text_parts),
                tool_calls=tool_calls,
                usage=TokenUsage(
                    input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
                    output_tokens=int(usage_raw.get("output_tokens", 0) or 0),
                    total_tokens=int(usage_raw.get("input_tokens", 0) or 0) + int(usage_raw.get("output_tokens", 0) or 0),
                ),
                model=body.get("model", self.config.model),
                finish_reason=body.get("stop_reason", "stop"),
            )
        except (TypeError, ValueError, JSONDecodeError) as exc:
            raise ProviderError("anthropic_compatible", "response_parse_error", f"Anthropic-compatible response malformed: {exc}") from exc

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProviderChunk]:
        if not self.config.endpoint:
            raise ProviderError("anthropic_compatible", "configuration_error", "Anthropic-compatible provider requires endpoint")

        payload = _build_payload(self.config, messages, tools, stream=True, **kwargs)
        content_parts: list[str] = []
        tool_buffers: dict[int, dict[str, str]] = {}
        finish_reason = "stop"

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.config.endpoint.rstrip('/')}/messages",
                    headers=_build_auth_headers(self.config.api_key),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for event, data in _iter_sse_events(response):
                        if event == "content_block_start":
                            index = int(data.get("index", 0))
                            block = data.get("content_block") or {}
                            if block.get("type") == "tool_use":
                                tool_buffers[index] = {
                                    "id": str(block.get("id", "")),
                                    "name": str(block.get("name", "")),
                                    "input": json.dumps(block.get("input", {}), ensure_ascii=False)
                                    if isinstance(block.get("input"), dict)
                                    else str(block.get("input", "")),
                                }
                        elif event == "content_block_delta":
                            index = int(data.get("index", 0))
                            delta = data.get("delta") or {}
                            if delta.get("type") == "text_delta":
                                text = str(delta.get("text", ""))
                                if text:
                                    content_parts.append(text)
                                    yield ProviderChunk(type="text", delta=text)
                            elif delta.get("type") == "input_json_delta":
                                current = tool_buffers.setdefault(index, {"id": "", "name": "", "input": ""})
                                current["input"] += str(delta.get("partial_json", ""))
                        elif event == "message_delta":
                            delta = data.get("delta") or {}
                            if delta.get("stop_reason"):
                                finish_reason = str(delta["stop_reason"])
                        elif event == "message_stop":
                            break
        except httpx.TimeoutException as exc:
            raise ProviderError("anthropic_compatible", "timeout_error", "Anthropic-compatible streaming request timed out", True) from exc
        except httpx.HTTPStatusError as exc:
            raise _http_error("anthropic_compatible", exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("anthropic_compatible", "network_error", f"Anthropic-compatible streaming failed: {exc}", True) from exc

        for index in sorted(tool_buffers):
            item = tool_buffers[index]
            try:
                arguments = json.loads(item["input"] or "{}")
            except JSONDecodeError as exc:
                raise ProviderError("anthropic_compatible", "response_parse_error", f"Anthropic-compatible tool input invalid: {exc}") from exc
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
        return estimate_message_tokens(messages, model=self.config.model)


def _build_payload(
    config: ModelConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    stream: bool,
    **kwargs: Any,
) -> dict[str, Any]:
    system_messages = [msg["content"] for msg in messages if msg.get("role") == "system"]
    non_system = [msg for msg in messages if msg.get("role") != "system"]
    payload = {
        "model": config.model,
        "system": "\n\n".join(system_messages),
        "messages": non_system,
        "max_tokens": kwargs.get("max_tokens", config.max_tokens),
        "temperature": kwargs.get("temperature", config.temperature),
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    return payload


def _parse_anthropic_tool_calls(content_blocks: list[dict[str, Any]]) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        if block.get("type") != "tool_use":
            continue
        arguments = block.get("input", {})
        if not isinstance(arguments, dict):
            raise ValueError("Anthropic tool_use input must be an object")
        tool_calls.append(
            ToolCall(
                id=str(block.get("id", "")),
                name=str(block.get("name", "")),
                arguments=arguments,
            )
        )
    return tool_calls


async def _iter_sse_events(response: httpx.Response) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    current_event = "message"
    async for line in response.aiter_lines():
        if not line:
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except JSONDecodeError as exc:
            raise ProviderError("anthropic_compatible", "response_parse_error", f"Anthropic-compatible stream payload invalid: {exc}") from exc
        yield current_event, data


def _http_error(provider: str, exc: httpx.HTTPStatusError) -> ProviderError:
    status_code = exc.response.status_code
    if status_code in {401, 403}:
        return ProviderError(provider, "auth_error", f"{provider} authentication failed", False, status_code=status_code)
    if status_code == 429:
        return ProviderError(provider, "rate_limit_error", f"{provider} rate limited", True, status_code=status_code)
    if status_code >= 500:
        return ProviderError(provider, "upstream_error", f"{provider} upstream server error", True, status_code=status_code)
    return ProviderError(provider, "request_error", f"{provider} request failed with status {status_code}", False, status_code=status_code)


def _build_auth_headers(api_key: str | None) -> dict[str, str]:
    headers = {"anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers
