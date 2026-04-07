from __future__ import annotations

from typing import Any

import httpx

from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult


class FetchUrlTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(
            name="fetch_url",
            description="Fetch a URL over HTTP(S).",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            risk_level="medium",
            requires_approval=False,
            timeout_seconds=20,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        url = arguments["url"]
        try:
            async with httpx.AsyncClient(timeout=self.meta.timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
            return ToolExecutionResult(
                True,
                self.meta.name,
                "fetch",
                summary=f"成功抓取 {url}",
                stdout=response.text[:20_000],
            )
        except httpx.HTTPError as exc:
            return ToolExecutionResult(
                False,
                self.meta.name,
                "fetch",
                "network_error",
                summary=str(exc),
                retryable=True,
            )
