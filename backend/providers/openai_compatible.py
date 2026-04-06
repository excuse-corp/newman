from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from backend.config.schema import ProviderConfig
from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse, TokenUsage, ToolCall
from backend.providers.token_estimator import estimate_message_tokens


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self.config = config

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        if not self.config.endpoint:
            raise ValueError("OpenAI-compatible provider requires endpoint")

        payload = {
          "model": self.config.model,
          "messages": messages,
          "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
          "temperature": kwargs.get("temperature", self.config.temperature),
          "stream": False,
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.config.timeout) as client:
            response = await client.post(
                f"{self.config.endpoint.rstrip('/')}/chat/completions",
                headers=_build_auth_headers(self.config.api_key),
                json=payload,
            )
            response.raise_for_status()
            body = response.json()

        choice = body["choices"][0]
        message = choice["message"]
        tool_calls = [
            ToolCall(
                id=tool["id"],
                name=tool["function"]["name"],
                arguments=json.loads(tool["function"]["arguments"] or "{}"),
            )
            for tool in message.get("tool_calls", [])
        ]
        usage_raw = body.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return ProviderResponse(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            usage=usage,
            model=body.get("model", self.config.model),
            finish_reason=choice.get("finish_reason", "stop"),
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
        for tool_call in response.tool_calls:
            yield ProviderChunk(type="tool_call", tool_call=tool_call)
        yield ProviderChunk(type="done", finish_reason=response.finish_reason)

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return estimate_message_tokens(messages)


def _build_auth_headers(api_key: str | None) -> dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}
