from __future__ import annotations

import unittest

import httpx

from backend.config.schema import ModelConfig
from backend.providers.openai_compatible import (
    _build_payload,
    _consume_error_response,
    _extract_response_provider_state,
    _http_error,
    _parse_openai_tool_calls,
)


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_parse_openai_tool_calls_accepts_none(self) -> None:
        self.assertEqual(_parse_openai_tool_calls(None), [])

    def test_http_error_keeps_response_body_preview(self) -> None:
        request = httpx.Request("POST", "https://example.com/chat/completions")
        response = httpx.Response(400, text='{"error":"bad request"}', request=request)
        exc = httpx.HTTPStatusError("bad request", request=request, response=response)

        error = _http_error("openai_compatible", exc)

        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.details["response_text"], '{"error":"bad request"}')

    def test_http_error_handles_unread_streaming_response(self) -> None:
        request = httpx.Request("POST", "https://example.com/chat/completions")
        response = httpx.Response(400, request=request, stream=httpx.ByteStream(b'{"error":"bad request"}'))
        exc = httpx.HTTPStatusError("bad request", request=request, response=response)

        error = _http_error("openai_compatible", exc)

        self.assertEqual(error.status_code, 400)
        self.assertEqual(error.details, {})

    def test_extract_response_provider_state_keeps_reasoning_content(self) -> None:
        config = ModelConfig(type="openai_compatible", model="mimo-v2.5")

        state = _extract_response_provider_state(config, {"content": "ok", "reasoning_content": "需要先调用工具"})

        self.assertEqual(state, {"reasoning_content": "需要先调用工具"})

    def test_build_payload_replays_reasoning_content_for_profiled_tool_call(self) -> None:
        config = ModelConfig(type="openai_compatible", model="mimo-v2.5")
        payload = _build_payload(
            config,
            [
                {"role": "user", "content": "读 README"},
                {
                    "role": "assistant",
                    "content": "我先读取 README。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                        }
                    ],
                    "provider_state": {"reasoning_content": "需要读取文件后再回答"},
                },
            ],
            tools=[],
            stream=False,
        )

        assistant_message = payload["messages"][1]
        self.assertEqual(assistant_message["reasoning_content"], "需要读取文件后再回答")
        self.assertNotIn("provider_state", assistant_message)

    def test_build_payload_adds_empty_reasoning_content_for_legacy_profiled_tool_call(self) -> None:
        config = ModelConfig(type="openai_compatible", model="mimo-v2.5")
        payload = _build_payload(
            config,
            [
                {"role": "user", "content": "读 README"},
                {
                    "role": "assistant",
                    "content": "我先读取 README。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                        }
                    ],
                },
            ],
            tools=[],
            stream=False,
        )

        self.assertEqual(payload["messages"][1]["reasoning_content"], "")

    def test_build_payload_does_not_replay_reasoning_content_for_unprofiled_model(self) -> None:
        config = ModelConfig(type="openai_compatible", model="generic-model")
        payload = _build_payload(
            config,
            [
                {
                    "role": "assistant",
                    "content": "我先读取 README。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                        }
                    ],
                    "provider_state": {"reasoning_content": "内部状态"},
                }
            ],
            tools=[],
            stream=False,
        )

        assistant_message = payload["messages"][0]
        self.assertNotIn("reasoning_content", assistant_message)
        self.assertNotIn("provider_state", assistant_message)

    def test_build_payload_can_replay_reasoning_content_from_configured_capability(self) -> None:
        config = ModelConfig(
            type="openai_compatible",
            model="generic-model",
            capabilities={"reasoning": {"field": "reasoning_content", "replay_required": True}},
        )
        payload = _build_payload(
            config,
            [
                {
                    "role": "assistant",
                    "content": "我先调用工具。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                    "provider_state": {"reasoning_content": "配置驱动的回放"},
                }
            ],
            tools=[],
            stream=False,
        )

        self.assertEqual(payload["messages"][0]["reasoning_content"], "配置驱动的回放")

    def test_build_payload_allows_config_to_disable_profiled_reasoning_replay(self) -> None:
        config = ModelConfig(
            type="openai_compatible",
            model="mimo-v2.5",
            capabilities={"reasoning": {"replay_required": False}},
        )
        payload = _build_payload(
            config,
            [
                {
                    "role": "assistant",
                    "content": "我先调用工具。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ],
                    "provider_state": {"reasoning_content": "不应回放"},
                }
            ],
            tools=[],
            stream=False,
        )

        self.assertNotIn("reasoning_content", payload["messages"][0])


class OpenAICompatibleProviderAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_consume_error_response_reads_stream_body_for_preview(self) -> None:
        request = httpx.Request("POST", "https://example.com/chat/completions")
        response = httpx.Response(400, request=request, stream=httpx.ByteStream(b'{"error":"bad request"}'))
        exc = httpx.HTTPStatusError("bad request", request=request, response=response)

        await _consume_error_response(response)
        error = _http_error("openai_compatible", exc)

        self.assertEqual(error.details["response_text"], '{"error":"bad request"}')


if __name__ == "__main__":
    unittest.main()
