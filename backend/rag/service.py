from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from backend.rag.models import KnowledgeDocument, KnowledgeSearchHit


SUPPORTED_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".py",
    ".yaml",
    ".yml",
    ".log",
}


class KnowledgeBaseService:
    def __init__(self, knowledge_dir: Path, workspace: Path):
        self.knowledge_dir = knowledge_dir.resolve()
        self.workspace = workspace.resolve()
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.knowledge_dir / "index.json"

    def list_documents(self) -> list[KnowledgeDocument]:
        return sorted(self._load_manifest(), key=lambda item: item.imported_at, reverse=True)

    def import_document(self, source_path: str) -> KnowledgeDocument:
        raw_path = Path(source_path)
        source = (self.workspace / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
        if not source.is_relative_to(self.workspace):
            raise ValueError("source_path 必须位于 workspace 内")
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"文档不存在: {source}")
        if source.suffix.lower() not in SUPPORTED_TEXT_EXTENSIONS:
            raise ValueError(f"暂不支持该文件类型: {source.suffix or '<none>'}")

        content = source.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            raise ValueError("文档内容为空，无法导入知识库")

        document_id = uuid4().hex
        stored_name = f"{document_id}_{source.name}"
        stored_path = self.knowledge_dir / stored_name
        shutil.copyfile(source, stored_path)

        existing_documents = self._load_manifest()
        manifest: list[KnowledgeDocument] = []
        for item in existing_documents:
            if Path(item.source_path).resolve() == source:
                stale_path = Path(item.stored_path)
                if stale_path.exists():
                    stale_path.unlink()
                continue
            manifest.append(item)
        document = KnowledgeDocument(
            document_id=document_id,
            title=source.name,
            source_path=str(source),
            stored_path=str(stored_path),
            size_bytes=stored_path.stat().st_size,
        )
        manifest.append(document)
        self._save_manifest(manifest)
        return document

    def search(self, query: str, limit: int = 5) -> list[KnowledgeSearchHit]:
        normalized_query = query.strip()
        if not normalized_query:
            return []
        query_tokens = self._tokenize(normalized_query)
        hits: list[KnowledgeSearchHit] = []
        for document in self._load_manifest():
            path = Path(document.stored_path)
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for index, snippet in enumerate(self._candidate_snippets(lines), start=1):
                score = self._score_snippet(snippet, normalized_query, query_tokens)
                if score <= 0:
                    continue
                hits.append(
                    KnowledgeSearchHit(
                        document_id=document.document_id,
                        title=document.title,
                        stored_path=document.stored_path,
                        snippet=snippet[:400],
                        score=round(score, 4),
                        line_number=index,
                    )
                )
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: max(1, limit)]

    def _candidate_snippets(self, lines: list[str]) -> list[str]:
        snippets: list[str] = []
        buffer: list[str] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                if buffer:
                    snippets.append(" ".join(buffer))
                    buffer = []
                continue
            buffer.append(line)
            if len(" ".join(buffer)) >= 280:
                snippets.append(" ".join(buffer))
                buffer = []
        if buffer:
            snippets.append(" ".join(buffer))
        return snippets or [""]

    def _score_snippet(self, snippet: str, raw_query: str, query_tokens: list[str]) -> float:
        haystack = snippet.lower()
        token_hits = sum(haystack.count(token) for token in query_tokens)
        unique_hits = sum(1 for token in set(query_tokens) if token in haystack)
        phrase_bonus = 3 if raw_query.lower() in haystack else 0
        return float(token_hits + unique_hits * 2 + phrase_bonus)

    def _tokenize(self, text: str) -> list[str]:
        return [token for token in re.split(r"\W+", text.lower()) if token]

    def _load_manifest(self) -> list[KnowledgeDocument]:
        if not self.manifest_path.exists():
            return []
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return [KnowledgeDocument.model_validate(item) for item in raw]

    def _save_manifest(self, documents: list[KnowledgeDocument]) -> None:
        payload = [item.model_dump(mode="json") for item in documents]
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
