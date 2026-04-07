from __future__ import annotations

import unittest

from backend.config.schema import ModelConfig
from backend.rag.citation import build_citation, format_citation_label
from backend.rag.models import KnowledgeChunk, KnowledgeDocument
from backend.rag.reranker import Reranker


class CitationTests(unittest.TestCase):
    def test_build_citation_keeps_required_fields(self) -> None:
        document = KnowledgeDocument(
            document_id="doc-1",
            title="Report.pdf",
            source_path="/tmp/Report.pdf",
            stored_path="/data/Report.pdf",
            size_bytes=1024,
            parser="pdf",
            page_count=10,
            chunk_count=1,
        )
        chunk = KnowledgeChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            title="Report.pdf",
            text="Important content " * 30,
            token_count=120,
            page_number=5,
            chunk_index=12,
            location_label="page 5",
        )

        citation = build_citation(document, chunk)

        self.assertEqual(citation.title, "Report.pdf")
        self.assertEqual(citation.page_number, 5)
        self.assertEqual(citation.chunk_index, 12)
        self.assertTrue(citation.snippet.startswith("Important content"))
        self.assertIn("page 5", format_citation_label(citation))


class RerankerTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_reranker_returns_initial_scores(self) -> None:
        reranker = Reranker(ModelConfig(type="mock", model="mock-reranker"))
        chunk = KnowledgeChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            title="Report.pdf",
            text="Some content",
            token_count=10,
            chunk_index=0,
        )

        scores = await reranker.rerank("report", [chunk], {"chunk-1": 0.73})

        self.assertEqual(scores, {"chunk-1": 0.73})

    async def test_non_openai_reranker_falls_back_to_initial_scores(self) -> None:
        reranker = Reranker(ModelConfig(type="anthropic_compatible", model="anthropic-reranker"))
        chunk = KnowledgeChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            title="Report.pdf",
            text="Some content",
            token_count=10,
            chunk_index=0,
        )

        scores = await reranker.rerank("report", [chunk], {"chunk-1": 0.41})

        self.assertEqual(scores, {"chunk-1": 0.41})


if __name__ == "__main__":
    unittest.main()
