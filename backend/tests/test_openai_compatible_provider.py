from __future__ import annotations

import unittest

import httpx

from backend.providers.openai_compatible import _consume_error_response, _http_error, _parse_openai_tool_calls


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
