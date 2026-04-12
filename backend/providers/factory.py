from __future__ import annotations

from typing import Any, AsyncIterator
from uuid import uuid4

from backend.config.schema import ModelConfig
from backend.providers.anthropic_compatible import AnthropicCompatibleProvider
from backend.providers.base import BaseProvider, ProviderChunk, ProviderResponse, TokenUsage, ToolCall
from backend.providers.openai_compatible import OpenAICompatibleProvider
from backend.providers.token_estimator import estimate_message_tokens


class MockProvider(BaseProvider):
    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs: Any) -> ProviderResponse:
        last_message = messages[-1] if messages else {}
        if last_message.get("role") == "tool":
            tool_output = str(last_message.get("content", "")).strip()
            return ProviderResponse(
                content=f"[mock] 工具执行完成，结果摘要如下：{tool_output[:240]}",
                usage=TokenUsage(input_tokens=estimate_message_tokens(messages, model="mock")),
                model="mock",
                finish_reason="stop",
            )

        last_user = next((msg for msg in reversed(messages) if msg.get("role") == "user"), {})
        text = str(last_user.get("content", "")).strip()
        if text.startswith("/tool "):
            parts = text.split(" ", 2)
            tool_name = parts[1]
            arguments = {}
            if len(parts) > 2 and parts[2].strip():
                import json

                arguments = json.loads(parts[2])
            return ProviderResponse(
                content="",
                tool_calls=[ToolCall(id=f"tool_{uuid4().hex[:8]}", name=tool_name, arguments=arguments)],
                usage=TokenUsage(input_tokens=estimate_message_tokens(messages, model="mock")),
                model="mock",
                finish_reason="tool_calls",
            )
        return ProviderResponse(
            content=f"[mock] Newman 已收到你的消息：{text or '空输入'}",
            usage=TokenUsage(
                input_tokens=estimate_message_tokens(messages, model="mock"),
                output_tokens=max(1, len(text) // 4),
            ),
            model="mock",
            finish_reason="stop",
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
        if response.usage.total_tokens > 0:
            yield ProviderChunk(type="usage", usage=response.usage, finish_reason=response.finish_reason)
        yield ProviderChunk(type="done", finish_reason=response.finish_reason)

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        return estimate_message_tokens(messages, model="mock")


def build_provider(config: ModelConfig) -> BaseProvider:
    if config.type == "mock":
        return MockProvider()
    if config.type == "openai_compatible":
        return OpenAICompatibleProvider(config)
    if config.type == "anthropic_compatible":
        return AnthropicCompatibleProvider(config)
    raise ValueError(f"Unsupported provider type: {config.type}")
