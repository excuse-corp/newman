from __future__ import annotations

import unittest

from backend.providers.openai_compatible import _parse_openai_tool_calls


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_parse_openai_tool_calls_accepts_none(self) -> None:
        self.assertEqual(_parse_openai_tool_calls(None), [])


if __name__ == "__main__":
    unittest.main()
