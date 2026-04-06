from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from backend.config.schema import ProviderConfig
from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse, TokenUsage
from backend.providers.token_estimator import estimate_message_tokens


class AnthropicCompatibleProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self.config = config

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        if not self.config.endpoint:
            raise ValueError("Anthropic-compatible provider requires endpoint")

        system_messages = [msg["content"] for msg in messages if msg.get("role") == "system"]
        non_system = [msg for msg in messages if msg.get("role") != "system"]
        payload = {
            "model": self.config.model,
            "system": "\n\n".join(system_messages),
            "messages": non_system,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.config.endpoint.rstrip('/')}/messages",
                headers=_build_auth_headers(self.config.api_key),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        content_blocks = body.get("content", [])
        text_parts = [block.get("text", "") for block in content_blocks if block.get("type") == "text"]
        usage_raw = body.get("usage", {})
        return ProviderResponse(
            content="".join(text_parts),
            usage=TokenUsage(
                input_tokens=usage_raw.get("input_tokens", 0),
                output_tokens=usage_raw.get("output_tokens", 0),
                total_tokens=usage_raw.get("input_tokens", 0) + usage_raw.get("output_tokens", 0),
            ),
            model=body.get("model", self.config.model),
            finish_reason=body.get("stop_reason", "stop"),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProviderChunk]:
        response = await self.chat(messages, tools=tools, **kwargs)
        if response.content:
            yield ProviderChunk(type="text", delta=response.content, finish_reason=response.finish_reason)
        yield ProviderChunk(type="done", finish_reason=response.finish_reason)

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return estimate_message_tokens(messages)


def _build_auth_headers(api_key: str | None) -> dict[str, str]:
    headers = {"anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers
