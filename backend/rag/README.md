# RAG

当前已落地的是 Phase 2 基线能力：

- 本地文档导入：文本 / PDF / DOCX / PPTX / XLSX
- 文件上传导入与工作区路径导入
- 文档切块与 chunk 持久化
- Embedding 向量化（OpenAI-compatible 或本地哈希回退）
- BM25 + Chroma Vector 混合检索
- Reranker 重排（模型驱动，失败时自动回退）
- 片段引用与位置元数据返回
- PostgreSQL 元数据存储（`rag_documents` / `rag_chunks` / `rag_search_stats` / `rag_citation_records`）
- `search_knowledge_base` 工具接入
- `/api/knowledge/documents` 与 `/api/knowledge/search` 接口

补充能力：

- 图片文件可通过多模态模型先解析后再入库
- Chroma 默认持久化目录为 `backend_data/chroma/`
- reranker 在非 `openai_compatible` 配置下会自动回退到初始混合分数
