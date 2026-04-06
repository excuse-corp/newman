# RAG

当前已落地的是 Phase 2 基线能力：

- 本地文本类文档导入
- 文件级持久化清单 `backend_data/knowledge/index.json`
- 词法检索与片段返回
- `search_knowledge_base` 工具接入
- `/api/knowledge/documents` 与 `/api/knowledge/search` 接口

暂未实现：

- PDF / Word / PPT / Excel 解析
- 向量索引与混合检索
- Reranker
- 引用页码与精确 chunk 溯源
