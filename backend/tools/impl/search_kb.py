from __future__ import annotations

from typing import Any

from backend.rag.service import KnowledgeBaseService
from backend.tools.base import BaseTool, ToolMeta
from backend.tools.result import ToolExecutionResult


class SearchKnowledgeBaseTool(BaseTool):
    def __init__(self, knowledge_base: KnowledgeBaseService):
        self.knowledge_base = knowledge_base
        self.meta = ToolMeta(
            name="search_knowledge_base",
            description="Search imported knowledge documents and return the most relevant snippets.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
            risk_level="low",
            requires_approval=False,
            timeout_seconds=10,
        )

    async def run(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        query = arguments["query"]
        limit = int(arguments.get("limit", 5))
        hits = self.knowledge_base.search(query, limit=limit)
        if not hits:
            return ToolExecutionResult(
                success=True,
                tool=self.meta.name,
                action="search",
                summary="知识库中没有命中结果",
                stdout="[]",
            )
        return ToolExecutionResult(
            success=True,
            tool=self.meta.name,
            action="search",
            summary=f"命中 {len(hits)} 条知识片段",
            stdout="\n\n".join(
                f"[{index}] {hit.title} score={hit.score} line={hit.line_number}\n{hit.snippet}"
                for index, hit in enumerate(hits, start=1)
            ),
            metadata={"hits": [hit.model_dump(mode='json') for hit in hits]},
        )
