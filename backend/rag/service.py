from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from rank_bm25 import BM25Okapi

from backend.rag.citation import build_citation
from backend.config.schema import ModelsConfig, RagConfig
from backend.rag.chunker import chunk_segments, estimate_tokens
from backend.rag.embedder import Embedder
from backend.rag.models import KnowledgeChunk, KnowledgeCitationRecord, KnowledgeDocument, KnowledgeSearchHit
from backend.rag.parser import IMAGE_EXTENSIONS, SUPPORTED_EXTENSIONS, detect_content_type, parse_document, parse_image_summary
from backend.rag.reranker import Reranker
from backend.rag.retriever import ChromaVectorStore
from backend.rag.store import PostgresRAGStore
from backend.usage.store import PostgresModelUsageStore


class KnowledgeBaseService:
    def __init__(
        self,
        knowledge_dir: Path,
        workspace: Path,
        models: ModelsConfig,
        rag: RagConfig,
        chroma_dir: Path,
        usage_store: PostgresModelUsageStore | None = None,
    ):
        self.knowledge_dir = knowledge_dir.resolve()
        self.workspace = workspace.resolve()
        self.models = models
        self.rag = rag
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = Embedder(models.embedding)
        self.reranker = Reranker(models.reranker, usage_store)
        self.store = PostgresRAGStore(rag.postgres_dsn)
        self.vector_store = ChromaVectorStore(chroma_dir.resolve(), rag.chroma_collection)

    def list_documents(self) -> list[KnowledgeDocument]:
        return self.store.list_documents()

    async def import_document(self, source_path: str) -> KnowledgeDocument:
        raw_path = Path(source_path)
        source = (self.workspace / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
        return await self.import_file(source, enforce_workspace=True, display_name=source.name, source_reference=str(source))

    async def import_file(
        self,
        source: Path,
        *,
        enforce_workspace: bool = False,
        display_name: str | None = None,
        source_reference: str | None = None,
    ) -> KnowledgeDocument:
        if enforce_workspace and not source.is_relative_to(self.workspace):
            raise ValueError("source_path 必须位于 workspace 内")
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"文档不存在: {source}")
        if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"暂不支持该文件类型: {source.suffix or '<none>'}")
        if source.suffix.lower() in IMAGE_EXTENSIONS:
            raise ValueError("图片知识导入请使用 /api/knowledge/documents/upload，并通过多模态模型解析后再入库")

        title = display_name or source.name
        source_path_value = source_reference or str(source)

        parser_name, segments, page_count = parse_document(source)
        segments = [segment for segment in segments if segment.text.strip()]
        if not segments:
            raise ValueError("文档内容为空，无法导入知识库")

        chunks = chunk_segments(segments)
        chunk_texts = [chunk.text for chunk in chunks]
        embeddings = await self.embedder.embed_texts(chunk_texts)

        existing = self.store.get_document_by_source_path(source_path_value)
        if existing:
            self.vector_store.delete_document(existing.document_id)
            self.store.delete_document(existing.document_id)
            stale_path = Path(existing.stored_path)
            if stale_path.exists():
                stale_path.unlink()

        document_id = uuid4().hex
        stored_name = f"{document_id}_{title}"
        stored_path = self.knowledge_dir / stored_name
        shutil.copyfile(source, stored_path)

        stored_chunks = [
            KnowledgeChunk(
                chunk_id=f"{document_id}_{index}",
                document_id=document_id,
                title=title,
                text=chunk.text,
                token_count=estimate_tokens(chunk.text),
                embedding=embeddings[index],
                page_number=chunk.page_number,
                chunk_index=index,
                location_label=chunk.location_label,
                metadata=dict(chunk.metadata or {}),
            )
            for index, chunk in enumerate(chunks)
        ]

        document = KnowledgeDocument(
            document_id=document_id,
            title=title,
            source_path=source_path_value,
            stored_path=str(stored_path),
            size_bytes=stored_path.stat().st_size,
            content_type=detect_content_type(source),
            parser=parser_name,
            chunk_count=len(stored_chunks),
            page_count=page_count,
        )
        self.store.replace_document(document, stored_chunks)
        self.vector_store.upsert_chunks(stored_chunks)
        return document

    async def import_image_analysis(self, *, source_name: str, source_path: str, summary: str) -> KnowledgeDocument:
        if not summary.strip():
            raise ValueError("图片分析结果为空，无法导入知识库")

        existing = self.store.get_document_by_source_path(source_path)
        if existing:
            self.vector_store.delete_document(existing.document_id)
            self.store.delete_document(existing.document_id)
            stale_path = Path(existing.stored_path)
            if stale_path.exists():
                stale_path.unlink()

        document_id = uuid4().hex
        stored_name = f"{document_id}_{source_name}.md"
        stored_path = self.knowledge_dir / stored_name
        rendered = f"# {source_name}\n\n{summary.strip()}\n"
        stored_path.write_text(rendered, encoding="utf-8")

        segments = parse_image_summary(summary, source_name)
        chunks = chunk_segments(segments) if segments else []
        embeddings = await self.embedder.embed_texts([segment.text for segment in chunks])
        stored_chunks = [
            KnowledgeChunk(
                chunk_id=f"{document_id}_{index}",
                document_id=document_id,
                title=source_name,
                text=segment.text,
                token_count=estimate_tokens(segment.text),
                embedding=embeddings[index],
                page_number=segment.page_number,
                chunk_index=index,
                location_label=segment.location_label,
                metadata=dict(segment.metadata or {}),
            )
            for index, segment in enumerate(chunks)
        ]

        document = KnowledgeDocument(
            document_id=document_id,
            title=source_name,
            source_path=source_path,
            stored_path=str(stored_path),
            size_bytes=stored_path.stat().st_size,
            content_type="text/markdown",
            parser="multimodal-image",
            chunk_count=len(stored_chunks),
        )
        self.store.replace_document(document, stored_chunks)
        self.vector_store.upsert_chunks(stored_chunks)
        return document

    async def search(self, query: str, limit: int = 5) -> list[KnowledgeSearchHit]:
        normalized_query = query.strip()
        if not normalized_query:
            return []

        chunks = self.store.list_chunks()
        if not chunks:
            return []
        documents = {document.document_id: document for document in self.store.list_documents()}

        lexical_scores = self._lexical_scores(normalized_query, chunks)
        lexical_candidates = sorted(chunks, key=lambda chunk: lexical_scores.get(chunk.chunk_id, 0.0), reverse=True)[
            : max(limit, self.rag.lexical_candidate_count)
        ]

        query_embedding = await self.embedder.embed_query(normalized_query)
        vector_results = self.vector_store.query(query_embedding, max(limit, self.rag.vector_candidate_count))
        vector_scores = {str(item["chunk_id"]): max(0.0, 1.0 - float(item["distance"])) for item in vector_results}

        candidate_ids = {chunk.chunk_id for chunk in lexical_candidates}
        candidate_ids.update(vector_scores.keys())
        candidates = self.store.get_chunks_by_ids(candidate_ids)
        if not candidates:
            return []

        initial_scores = {
            chunk.chunk_id: (lexical_scores.get(chunk.chunk_id, 0.0) * 0.55) + (vector_scores.get(chunk.chunk_id, 0.0) * 0.45)
            for chunk in candidates
        }
        ranked_candidates = sorted(candidates, key=lambda item: initial_scores.get(item.chunk_id, 0.0), reverse=True)[
            : max(limit, self.rag.hybrid_candidate_count)
        ]
        rerank_scores = await self.reranker.rerank(normalized_query, ranked_candidates, initial_scores)

        hits: list[KnowledgeSearchHit] = []
        for chunk in sorted(
            ranked_candidates,
            key=lambda item: rerank_scores.get(item.chunk_id, initial_scores.get(item.chunk_id, 0.0)),
            reverse=True,
        ):
            document = documents.get(chunk.document_id)
            if document is None:
                continue
            lexical = lexical_scores.get(chunk.chunk_id, 0.0)
            vector = vector_scores.get(chunk.chunk_id, 0.0)
            rerank = rerank_scores.get(chunk.chunk_id, initial_scores.get(chunk.chunk_id, 0.0))
            citation = build_citation(document, chunk)
            hits.append(
                KnowledgeSearchHit(
                    document_id=document.document_id,
                    title=document.title,
                    stored_path=document.stored_path,
                    snippet=chunk.text[:400],
                    score=round(rerank, 4),
                    lexical_score=round(lexical, 4),
                    vector_score=round(vector, 4),
                    rerank_score=round(rerank, 4),
                    source="hybrid",
                    line_number=chunk.page_number,
                    chunk_id=chunk.chunk_id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    location_label=chunk.location_label,
                    citation=citation,
                )
            )
        top_hits = hits[: max(1, limit)]
        self.store.record_search_stat(normalized_query, len(top_hits), top_hits[0].score if top_hits else 0.0)
        self.store.record_citations(
            [
                KnowledgeCitationRecord(
                    citation_id=uuid4().hex,
                    query=normalized_query,
                    document_id=hit.document_id,
                    chunk_id=hit.chunk_id or "",
                    score=hit.score,
                    rank=index,
                )
                for index, hit in enumerate(top_hits, start=1)
                if hit.chunk_id
            ]
        )
        return top_hits

    def _lexical_scores(self, query: str, chunks: list[KnowledgeChunk]) -> dict[str, float]:
        corpus = [self._tokenize(chunk.text) for chunk in chunks]
        if not corpus:
            return {}
        bm25 = BM25Okapi(corpus)
        query_tokens = self._tokenize(query)
        raw_scores = bm25.get_scores(query_tokens)
        max_score = max(raw_scores) if len(raw_scores) else 0.0
        scores: dict[str, float] = {}
        for chunk, raw_score in zip(chunks, raw_scores, strict=True):
            scores[chunk.chunk_id] = float(raw_score) / float(max_score) if max_score > 0 else 0.0
        return scores

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in "".join(ch if ch.isalnum() else " " for ch in text.lower()).split() if token]
