from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.discovery import BuiltinToolContext
from backend.tools.provider_exposure import NETWORK_TOOL_GROUP
from backend.tools.result import ToolExecutionResult


SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search?engine=google_light"
SERPAPI_ENGINE = "google_light"
SERPAPI_API_KEY_ENV_VARS = ("SERPAPI_API_KEY", "SERPAPI_KEY", "NEWMAN_SERPAPI_API_KEY")


class GoogleSearchTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="google_search",
            description=(
                "Search Google over the network through SerpApi using the google_light engine. "
                "The tool always calls https://serpapi.com/search?engine=google_light and reads the API key from "
                "SERPAPI_API_KEY, SERPAPI_KEY, or NEWMAN_SERPAPI_API_KEY."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "Required search query. Supports normal Google operators such as site:, inurl:, and intitle:.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Alias of q. Accepted for compatibility, but q is preferred.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional geographic location to simulate the search from. Cannot be used together with uule.",
                    },
                    "uule": {
                        "type": "string",
                        "description": "Optional encoded Google location. Cannot be used together with location.",
                    },
                    "google_domain": {
                        "type": "string",
                        "description": "Optional Google domain, such as google.com. Defaults to google.com.",
                    },
                    "gl": {
                        "type": "string",
                        "description": "Optional two-letter country code, such as us or uk.",
                    },
                    "hl": {
                        "type": "string",
                        "description": "Optional two-letter interface language code, such as en or fr.",
                    },
                    "lr": {
                        "type": "string",
                        "description": "Optional language restriction, such as lang_fr|lang_de.",
                    },
                    "safe": {
                        "type": "string",
                        "enum": ["active", "off"],
                        "description": "Optional adult-content filtering level.",
                    },
                    "nfpr": {
                        "type": "integer",
                        "enum": [0, 1],
                        "description": "Optional auto-correction exclusion flag. Use 1 to exclude auto-corrected results.",
                    },
                    "filter": {
                        "type": "integer",
                        "enum": [0, 1],
                        "description": "Optional similar/omitted results filter flag. Defaults to 1 in Google.",
                    },
                    "start": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Optional pagination offset. 0 is the first page, 10 is the second page.",
                    },
                    "device": {
                        "type": "string",
                        "enum": ["desktop", "tablet", "mobile"],
                        "description": "Optional device profile. Defaults to desktop.",
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "Optional. When true, forces SerpApi to fetch a fresh result instead of a cached one.",
                    },
                    "async": {
                        "type": "boolean",
                        "description": "Optional asynchronous submission flag. Cannot be used together with no_cache=true.",
                    },
                    "zero_trace": {
                        "type": "boolean",
                        "description": "Optional enterprise ZeroTrace flag.",
                    },
                    "output": {
                        "type": "string",
                        "enum": ["json", "html"],
                        "description": "Optional output format. Defaults to json.",
                    },
                },
                "additionalProperties": False,
            },
            risk_level="medium",
            approval_behavior="safe",
            timeout_seconds=30,
            provider_group=NETWORK_TOOL_GROUP,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        validation_error = _validate_arguments(arguments)
        if validation_error is not None:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "search",
                "validation_error",
                error_code="invalid_arguments",
                summary=validation_error,
            )

        api_key = _resolve_serpapi_api_key()
        if not api_key:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "search",
                "config_error",
                error_code="missing_api_key",
                summary=(
                    "未找到 SerpApi API Key，请在环境变量或项目根目录 .env 中配置 "
                    "SERPAPI_API_KEY（兼容 SERPAPI_KEY / NEWMAN_SERPAPI_API_KEY）"
                ),
            )

        try:
            client = _build_client(api_key=api_key, timeout=self.meta.timeout_seconds)
        except Exception as exc:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "search",
                "config_error",
                error_code="serpapi_import_error",
                summary=f"无法导入 serpapi 客户端: {exc}",
            )

        params = _build_search_params(arguments)
        try:
            results = await asyncio.to_thread(client.search, params)
        except Exception as exc:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "search",
                "network_error",
                error_code="serpapi_request_failed",
                summary=f"SerpApi 请求失败: {exc}",
                retryable=True,
                metadata={
                    "endpoint": SERPAPI_SEARCH_ENDPOINT,
                    "engine": SERPAPI_ENGINE,
                    "query": params["q"],
                },
            )

        if isinstance(results, str):
            html_output = results[:50_000]
            return ToolExecutionResult(
                True,
                self.meta.name,
                "search",
                summary=f"Google Light 搜索完成，返回 HTML 响应（query={params['q']!r}）",
                stdout=html_output,
                metadata={
                    "endpoint": SERPAPI_SEARCH_ENDPOINT,
                    "engine": SERPAPI_ENGINE,
                    "query": params["q"],
                    "output": "html",
                    "truncated": len(results) > len(html_output),
                },
                persisted_output=_build_persisted_output(params["q"], organic_result_count=None, output_format="html"),
            )

        raw_payload = _coerce_result_payload(results)
        if "error" in raw_payload:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "search",
                "network_error",
                error_code="serpapi_error",
                summary=f"SerpApi 返回错误: {raw_payload['error']}",
                metadata={
                    "endpoint": SERPAPI_SEARCH_ENDPOINT,
                    "engine": SERPAPI_ENGINE,
                    "query": params["q"],
                },
            )

        normalized_payload = _normalize_payload(raw_payload, params)
        organic_results = normalized_payload.get("organic_results") or []
        return ToolExecutionResult(
            True,
            self.meta.name,
            "search",
            summary=f"Google Light 搜索完成，返回 {len(organic_results)} 条自然结果",
            stdout=json.dumps(normalized_payload, ensure_ascii=False, indent=2),
            metadata={
                "endpoint": SERPAPI_SEARCH_ENDPOINT,
                "engine": SERPAPI_ENGINE,
                "query": params["q"],
                "organic_result_count": len(organic_results),
                "output": "json",
            },
            persisted_output=_build_persisted_output(params["q"], organic_result_count=len(organic_results), output_format="json"),
        )


def _build_client(*, api_key: str, timeout: int):
    import serpapi

    return serpapi.Client(api_key=api_key, timeout=timeout)


def _coerce_result_payload(results: Any) -> dict[str, Any]:
    if hasattr(results, "as_dict"):
        payload = results.as_dict()
    elif isinstance(results, Mapping):
        payload = dict(results)
    elif isinstance(results, dict):
        payload = results
    else:
        payload = {"raw": str(results)}
    return payload


def _normalize_payload(payload: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return {
        "endpoint": SERPAPI_SEARCH_ENDPOINT,
        "engine": SERPAPI_ENGINE,
        "request": {
            key: value
            for key, value in params.items()
            if key
            in {
                "q",
                "location",
                "uule",
                "google_domain",
                "gl",
                "hl",
                "lr",
                "safe",
                "nfpr",
                "filter",
                "start",
                "device",
                "no_cache",
                "async",
                "zero_trace",
                "output",
            }
        },
        "search_metadata": payload.get("search_metadata", {}),
        "search_information": payload.get("search_information", {}),
        "answer_box": payload.get("answer_box"),
        "knowledge_graph": payload.get("knowledge_graph"),
        "top_stories": payload.get("top_stories", []),
        "related_questions": payload.get("related_questions", []),
        "organic_results": payload.get("organic_results", []),
        "related_searches": payload.get("related_searches", []),
        "serpapi_pagination": payload.get("serpapi_pagination", {}),
    }


def _build_search_params(arguments: dict[str, Any]) -> dict[str, Any]:
    query = _resolve_query(arguments)
    params: dict[str, Any] = {
        "engine": SERPAPI_ENGINE,
        "q": query,
        "google_domain": arguments.get("google_domain") or "google.com",
        "output": arguments.get("output") or "json",
    }
    for key in (
        "location",
        "uule",
        "gl",
        "hl",
        "lr",
        "safe",
        "nfpr",
        "filter",
        "start",
        "device",
        "no_cache",
        "async",
        "zero_trace",
    ):
        value = arguments.get(key)
        if value is None or value == "":
            continue
        params[key] = value
    return params


def _validate_arguments(arguments: dict[str, Any]) -> str | None:
    query = _resolve_query(arguments)
    if not query:
        return "q 或 query 不能为空"
    if arguments.get("location") and arguments.get("uule"):
        return "location 和 uule 不能同时提供"
    if arguments.get("no_cache") and arguments.get("async"):
        return "no_cache=true 和 async=true 不能同时使用"
    return None


def _resolve_query(arguments: dict[str, Any]) -> str:
    raw_query = arguments.get("q")
    if raw_query is None or str(raw_query).strip() == "":
        raw_query = arguments.get("query")
    return str(raw_query or "").strip()


def _resolve_serpapi_api_key(project_root: Path | None = None, home_dir: Path | None = None) -> str | None:
    for env_key in SERPAPI_API_KEY_ENV_VARS:
        value = os.getenv(env_key)
        if value:
            return value

    root = project_root or Path(__file__).resolve().parents[3]
    home = home_dir or Path.home()
    for dotenv_path in (root / ".env", home / ".newman" / ".env"):
        dotenv_values = _read_dotenv(dotenv_path)
        for env_key in SERPAPI_API_KEY_ENV_VARS:
            value = dotenv_values.get(env_key)
            if value:
                return value
    return None


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _build_persisted_output(query: str, *, organic_result_count: int | None, output_format: str) -> str:
    payload = {
        "summary": "Google search completed; raw content omitted from persisted history",
        "engine": SERPAPI_ENGINE,
        "endpoint": SERPAPI_SEARCH_ENDPOINT,
        "query": query,
        "output": output_format,
        "organicResultCount": organic_result_count,
        "contentPersisted": False,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_tools(context: BuiltinToolContext) -> list[BaseTool]:
    return [GoogleSearchTool()]
