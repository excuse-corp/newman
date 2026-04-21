from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.tools.impl.google_search import GoogleSearchTool, _resolve_serpapi_api_key


class _FakeSerpResults(dict):
    def as_dict(self):
        return dict(self)


class _FakeClient:
    last_init: dict | None = None
    last_params: dict | None = None

    def __init__(self, *, api_key=None, timeout=None):
        type(self).last_init = {"api_key": api_key, "timeout": timeout}

    def search(self, params):
        type(self).last_params = params
        return _FakeSerpResults(
            {
                "search_metadata": {"status": "Success"},
                "search_information": {"total_results": 2},
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Coffee Roasters",
                        "link": "https://example.com/coffee",
                        "snippet": "Coffee beans and brewing guides.",
                    },
                    {
                        "position": 2,
                        "title": "Coffee Beans",
                        "link": "https://example.com/beans",
                        "snippet": "Single-origin beans.",
                    },
                ],
            }
        )


fake_serpapi = types.ModuleType("serpapi")
fake_serpapi.Client = _FakeClient
sys.modules.setdefault("serpapi", fake_serpapi)


class GoogleSearchToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_uses_google_light_and_returns_structured_json(self) -> None:
        tool = GoogleSearchTool()
        with patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}, clear=True):
            result = await tool.run(
                {
                    "q": "Coffee",
                    "location": "Austin, Texas, United States",
                    "gl": "us",
                    "hl": "en",
                },
                "session-1",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.metadata["organic_result_count"], 2)
        self.assertEqual(_FakeClient.last_init, {"api_key": "test-key", "timeout": 30})
        self.assertEqual(
            _FakeClient.last_params,
            {
                "engine": "google_light",
                "q": "Coffee",
                "google_domain": "google.com",
                "output": "json",
                "location": "Austin, Texas, United States",
                "gl": "us",
                "hl": "en",
            },
        )
        self.assertIn('"organic_results"', result.stdout)
        self.assertIn('"endpoint": "https://serpapi.com/search?engine=google_light"', result.stdout)

    async def test_search_accepts_query_alias_for_compatibility(self) -> None:
        tool = GoogleSearchTool()
        with patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}, clear=True):
            result = await tool.run(
                {
                    "query": "Manchester United latest news",
                    "gl": "us",
                    "hl": "en",
                },
                "session-alias",
            )

        self.assertTrue(result.success)
        self.assertEqual(
            _FakeClient.last_params,
            {
                "engine": "google_light",
                "q": "Manchester United latest news",
                "google_domain": "google.com",
                "output": "json",
                "gl": "us",
                "hl": "en",
            },
        )

    async def test_rejects_location_and_uule_at_the_same_time(self) -> None:
        tool = GoogleSearchTool()
        result = await tool.run(
            {
                "q": "Coffee",
                "location": "Austin, Texas, United States",
                "uule": "w+CAIQICINVW5pdGVkIFN0YXRlcw",
            },
            "session-2",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.category, "validation_error")
        self.assertEqual(result.summary, "location 和 uule 不能同时提供")

    async def test_returns_config_error_when_api_key_is_missing(self) -> None:
        tool = GoogleSearchTool()
        with patch.dict(os.environ, {}, clear=True):
            with patch("backend.tools.impl.google_search._read_dotenv", return_value={}):
                result = await tool.run({"q": "Coffee"}, "session-3")

        self.assertFalse(result.success)
        self.assertEqual(result.category, "config_error")
        self.assertEqual(result.error_code, "missing_api_key")

    async def test_returns_validation_error_when_both_q_and_query_are_missing(self) -> None:
        tool = GoogleSearchTool()
        result = await tool.run({}, "session-missing-query")

        self.assertFalse(result.success)
        self.assertEqual(result.category, "validation_error")
        self.assertEqual(result.summary, "q 或 query 不能为空")

    async def test_returns_html_output_when_requested(self) -> None:
        class _HtmlClient:
            def __init__(self, *, api_key=None, timeout=None):
                pass

            def search(self, params):
                return "<html><body>coffee</body></html>"

        tool = GoogleSearchTool()
        with patch.dict(os.environ, {"SERPAPI_API_KEY": "test-key"}, clear=True):
            with patch("backend.tools.impl.google_search._build_client", return_value=_HtmlClient()):
                result = await tool.run({"q": "Coffee", "output": "html"}, "session-4")

        self.assertTrue(result.success)
        self.assertEqual(result.metadata["output"], "html")
        self.assertEqual(result.stdout, "<html><body>coffee</body></html>")


class SerpApiKeyResolutionTests(unittest.TestCase):
    def test_resolves_api_key_from_project_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            (root / ".env").write_text("SERPAPI_API_KEY=from-project-dotenv\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                api_key = _resolve_serpapi_api_key(project_root=root, home_dir=home)

        self.assertEqual(api_key, "from-project-dotenv")

    def test_env_variable_has_priority_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            (root / ".env").write_text("SERPAPI_API_KEY=from-project-dotenv\n", encoding="utf-8")

            with patch.dict(os.environ, {"SERPAPI_API_KEY": "from-env"}, clear=True):
                api_key = _resolve_serpapi_api_key(project_root=root, home_dir=home)

        self.assertEqual(api_key, "from-env")


if __name__ == "__main__":
    unittest.main()
