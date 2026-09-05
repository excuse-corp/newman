# Newman 内置知识库检索方案

## 目标定位

Newman 内置知识库应作为一条独立的长期数据管线实现，不依赖 LlamaIndex，也不复用“聊天附件即时阅读”的生命周期。知识库可以复用现有附件解析能力，但必须由 Newman 自己管理知识库、文档、版本、chunk、权限、任务状态、检索索引和引用。

整体链路：

```text
文件 / 数据源
-> 解析 parser
-> 结构化 blocks
-> chunker
-> embedding
-> Postgres FTS + pgvector
-> hybrid retrieval / rerank
-> knowledge_search tool
-> Agent 带引用回答
```

核心原则：第三方服务只作为解析增强能力，知识库生命周期和检索索引由 Newman 内置能力掌控。

## 后端模块

建议新增 `backend/knowledge/` 作为知识库域模块，避免把长期知识库逻辑散落到聊天附件、runtime 或工具实现中。

```text
backend/knowledge/
├── models.py
├── store.py
├── parsers/
│   ├── __init__.py
│   ├── attachment_parser.py
│   └── mineru.py
├── chunking/
│   ├── __init__.py
│   ├── policies.py
│   └── chunker.py
├── embeddings.py
├── retrieval.py
├── ingestion.py
├── citations.py
└── api/
    └── routes.py
```

### 模块职责

- `models.py`：Pydantic/domain models，包括 `KnowledgeBase`、`Document`、`DocumentVersion`、`Chunk`、`IngestionTask`、`RetrievalRun`。
- `store.py`：Postgres 表初始化和 CRUD，风格可参考现有 `PostgresModelUsageStore`。
- `parsers/`：解析适配层，复用当前 `backend/attachments/parser.py` 的 `parse_attachment()`，并新增 `MineruParserAdapter`。
- `chunking/`：Newman 自研 chunker，第一版只支持 `general`、`table` 两种策略，降低配置复杂度。
- `embeddings.py`：独立 embedding provider，不绑定主聊天模型；配置中补充 `models.embedding`。
- `retrieval.py`：关键词检索、向量检索、融合排序、过滤、相邻 chunk 扩展、引用生成。
- `ingestion.py`：异步 ingestion worker，负责解析、分块、embedding、索引、重试、取消。
- `citations.py`：统一生成 `doc_id`、`version`、`page`、`bbox`、`section`、`chunk_id` 引用。
- `api/routes/knowledge.py`：知识库管理、上传、任务、chunk 管理、检索测试 API。
- `tools/impl/knowledge_search.py`：暴露给 Agent 的内置工具。

## 解析复用

当前 Newman 已有可复用的解析基础：

- `parse_attachment(path, sandbox=None)` 支持 `.txt`、`.md`、`.json`、`.html`、`.pdf`、`.docx`、`.xlsx`、`.pptx`，旧版 `.doc`、`.xls`、`.ppt` 会先用 `soffice` 转换。
- `ParsedAttachment` 已有 `markdown`、`plain_text`、`html`、`structure`、`chunks`、`warnings`，可以作为知识库 parser 的过渡输出。
- PDF 当前优先 PyMuPDF，回退 pypdf；DOCX 能识别 heading/list/table；XLSX/PPTX 也能文本化。
- 现有 `_build_chunks()` 是按空行和约 6000 字符粗切，不适合作为知识库最终 chunker。

建议做法：复用解析能力，不复用最终 chunk。知识库 ingestion 中先把解析结果规范成 `ParsedBlock[]`，再交给新的 token-aware chunker。

### ParsedBlock 过渡模型

```python
class ParsedBlock(BaseModel):
    block_id: str
    type: Literal["heading", "paragraph", "list", "table", "image", "code"]
    text: str
    markdown: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_locator: SourceLocator | None = None
```

`SourceLocator` 需要尽量保留来源定位信息：页码、bbox、章节路径、表格行列、原始 parser 标识等。

### 图片与多模态解析

文件中图片不应被简单丢弃。解析阶段应把图片规范成 `image` 类型的 `ParsedBlock`，并尽量保留页码、bbox、图片序号、文件内路径或临时对象引用。随后由一个可配置的图片理解步骤决定是否调用多模态模型。

建议策略：

- 默认不对所有图片无差别调用多模态模型，避免成本、延迟和隐私风险不可控。
- 对扫描页、图表、架构图、截图、流程图、包含明显文字但 OCR 不完整的图片，调用多模态模型生成可检索文本。
- 多模态结果写回 `ParsedBlock.text` 或 `metadata.image_understanding`，例如 `caption`、`ocr_text`、`chart_summary`、`table_markdown`、`confidence`。
- 图片解析结果参与 chunk 和 embedding，但引用仍指向原始文档、页码、bbox 或图片 locator。
- 如果多模态模型失败，应保留原始 `image` block 和 warning，不阻塞整个文档 ingestion。

图片 block 示例：

```json
{
  "block_id": "img_0003",
  "type": "image",
  "text": "图中展示了系统的 ingestion 流程：上传、解析、分块、embedding、索引和检索。",
  "metadata": {
    "image_understanding": {
      "model": "configured-multimodal-model",
      "caption": "系统 ingestion 流程图",
      "ocr_text": "upload -> parse -> chunk -> embed -> index -> retrieve",
      "confidence": 0.86
    }
  },
  "source_locator": {
    "page": 4,
    "bbox": [72, 120, 520, 380],
    "image_index": 3
  }
}
```

## MinerU 接入

本地 MinerU 服务作为增强解析器使用，尤其适合 PDF、扫描件、复杂表格和版式文档。

已验证能力：

- `/health` 正常，版本 `3.1.1`。
- `/file_parse` 可用。
- `backend=hybrid-auto-engine` 对 PDF 能返回 `md_content`、`content_list`、`bbox`、`page_idx`。
- `backend=pipeline` 对简单 PDF 有空结果风险，因此 PDF 默认建议 `hybrid-auto-engine`。

### 配置建议

```yaml
knowledge:
  parsing:
    mineru:
      enabled: true
      base_url: "http://10.175.207.82:8000"
      backend: "hybrid-auto-engine"
      parse_method: "auto"
      timeout_seconds: 300
      return_md: true
      return_content_list: true
      return_images: false  # image_understanding 启用且走 MinerU 时可按需打开
    image_understanding:
      enabled: false
      mode: "meaningful_only"
      multimodal_model: null
      timeout_seconds: 120
      max_images_per_document: 50
      store_extracted_images: false
```

说明：当 `image_understanding.enabled=true` 时，PDF 或版式解析器需要能提供图片 bytes、页面裁剪图或图片引用。MinerU 可作为图片和 bbox 来源之一；Newman 本地 parser 也可以用 PyMuPDF / office parser 提取嵌入图片或页面区域。

### 解析优先级

| 文件类型 / 场景 | 默认解析器 | Fallback |
| --- | --- | --- |
| PDF、扫描件、复杂表格、版式文档 | MinerU | Newman 本地 parser |
| TXT、MD、JSON、简单 HTML | Newman 本地 parser | 无需 MinerU |
| MinerU 超时、失败或返回空 | Newman 本地 parser | 记录 warning |

MinerU 失败不应阻塞整个 ingestion。任务应记录解析告警，并继续使用本地 parser 产物完成导入。

## Chunk 方案

第一版 chunk policy 不照搬 RAGFlow 的完整复杂策略，只提供 `general` 和 `table` 两类可解释、可运营的策略。FAQ、短文档、配置说明等场景先归入 `general`，避免过早暴露过多模式。

### Chunk Policy

| 策略 | 适用场景 | 默认行为 |
| --- | --- | --- |
| `general` | 普通文档、PDF、DOCX、HTML、FAQ、短文档 | 结构块聚合；默认 512 tokens，软范围 300-800，硬上限 1000-1200，overlap 8%-15%；参数必须允许用户在 KB 设置中调整 |
| `table` | XLSX、HTML 表格、PDF 表格 | 按行或小批行切；列支持 `indexing` / `metadata` / `both` |

### General 参数

`general` 是默认策略，参数需要在知识库设置页暴露给用户调整，并保存到 KB 或文档级 ingest 配置中。

| 参数 | 默认值 | 建议范围 | 说明 |
| --- | --- | --- | --- |
| `target_tokens` | `512` | `200-1200` | 目标 chunk 大小 |
| `min_tokens` | `300` | `100-800` | 低于该值时优先与相邻结构块合并 |
| `max_tokens` | `1000` | `400-1600` | 硬上限，避免超长 chunk 进入 embedding |
| `overlap_ratio` | `0.1` | `0-0.2` | 相邻 chunk 重叠比例 |
| `respect_headings` | `true` | `true/false` | 优先不跨章节合并 |
| `delimiter` | `null` | 自定义文本 | 可选分隔符，配合 `delimiter_then_pack` 使用 |

### General 切分方式

RAGFlow 值得借鉴的是“先结构解析、再按 delimiter/token 合并、chunk 可运营”。Newman 应避免隐式行为，例如 wrapped delimiter 直接绕过 token size。第一版 `general` 只暴露两个切分方式：

- `delimiter_then_pack`：先按 delimiter 切分，再按 token size 聚合。
- `size_only`：只按 token size 滑窗切分。

`delimiter_only`、`parent_child` 等更细策略可作为后续增强能力，不进入第一版用户配置。

### Chunk 数据结构

每个 chunk 至少保留以下字段：

```json
{
  "chunk_id": "...",
  "kb_id": "...",
  "document_id": "...",
  "version_id": "...",
  "parent_chunk_id": null,
  "chunk_index": 1,
  "content": "...",
  "metadata": {},
  "source_locator": {
    "page": 1,
    "bbox": [89, 65, 406, 79],
    "section_path": ["..."],
    "table_row": null
  },
  "enabled": true,
  "content_hash": "..."
}
```

## 索引与检索

不使用 LlamaIndex 时，第一版建议直接使用 Postgres：

- `chunks.content_tsvector`：Postgres full-text search。
- `chunks.embedding vector(n)`：pgvector 向量索引。
- `chunks.metadata JSONB`：过滤条件。
- `enabled`、`status`、`version`：严格过滤，避免删除或禁用内容被召回。
- 融合策略：先做 FTS candidates + vector candidates，再用 RRF 或加权归一化融合。

### 默认检索参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `top_k` | `8` | 返回给 Agent 或 Retrieval Test 的结果数 |
| `candidate_k` | `80-200` | FTS 和 vector 各自候选池大小 |
| `similarity_threshold` | `0.2` | 初始阈值，后续通过 Retrieval Test 调参 |
| `vector_weight` | `0.6-0.7` | 中文语义检索偏向 vector |
| `rerank` | `false` | 第一版关闭，后续再接 reranker |

### Retrieval Pipeline

```text
query
-> normalize / optional rewrite
-> FTS candidates
-> vector candidates
-> metadata/status/version filters
-> RRF or weighted fusion
-> optional neighbor expansion
-> optional rerank
-> citation generation
-> return SearchResult[]
```

## API 设计

API 路径保持 Newman 现有风格：`/api/<domain>`。

### Knowledge Bases

```http
GET    /api/knowledge/bases
POST   /api/knowledge/bases
GET    /api/knowledge/bases/{kb_id}
PATCH  /api/knowledge/bases/{kb_id}
```

### Documents

```http
POST   /api/knowledge/bases/{kb_id}/documents
GET    /api/knowledge/bases/{kb_id}/documents
GET    /api/knowledge/documents/{document_id}
DELETE /api/knowledge/documents/{document_id}
```

### Ingestion Tasks

```http
GET    /api/knowledge/tasks/{task_id}
POST   /api/knowledge/tasks/{task_id}/retry
POST   /api/knowledge/tasks/{task_id}/cancel
```

### Chunks

```http
GET    /api/knowledge/documents/{document_id}/chunks
PATCH  /api/knowledge/chunks/{chunk_id}
POST   /api/knowledge/chunks/{chunk_id}/disable
POST   /api/knowledge/chunks/{chunk_id}/enable
DELETE /api/knowledge/chunks/{chunk_id}
```

### Search And Retrieval Tests

```http
POST   /api/knowledge/bases/{kb_id}/search
POST   /api/knowledge/bases/{kb_id}/retrieval-tests
```

## Agent 工具

新增内置工具 `knowledge_search`，通过 `BuiltinToolContext` 注入 knowledge service；注册点可沿用当前工具发现机制扩展。

### Tool Schema

```json
{
  "query": "string",
  "knowledge_base_ids": ["string"],
  "top_k": 8,
  "filters": {},
  "include_citations": true
}
```

### 工具约束

- 不默认搜索所有知识库。
- 由会话显式选择 KB，或由用户明确指定 KB。
- 工具返回内容必须包含稳定引用信息，供 Agent 回答时带引用。
- 检索时严格过滤禁用、删除、非当前版本或无权限 chunk。

## 前端改动

建议新增完整 `Knowledge` 页面，不把知识库管理塞进现有聊天主界面的大组件里。

```text
frontend/src/pages/KnowledgePage.tsx
frontend/src/pages/KnowledgeBaseDetailPage.tsx
frontend/src/api/knowledge.ts
frontend/src/types/knowledge.ts
```

### 页面结构

```text
Knowledge
├── Knowledge Bases
│   ├── Create / Edit KB
│   └── KB Settings Summary
├── Knowledge Base Detail
│   ├── Documents
│   ├── Upload / Re-ingest
│   ├── Ingestion Tasks
│   ├── Chunks
│   ├── Retrieval Test
│   └── Settings
└── Chat 集成
    ├── 当前会话选择知识库
    └── 引用点击打开 chunk/source preview
```

### 前端能力

- KB 列表：创建、编辑、启用/停用知识库。
- 文档管理：上传、查看版本、重新导入、删除。
- 任务状态：展示 pending/running/ready/failed/cancelled，支持 retry/cancel。
- Chunk 管理：搜索、过滤、展开、编辑、启用/禁用、删除、查看来源。
- Retrieval Test：输入 query，调整 `top_k`、`threshold`、`vector_weight`、`filters`，查看召回 chunk、score、来源。
- Settings：embedding model、chunk policy、`general` 参数、MinerU 开关、图片理解开关、table column roles。
- Chat 集成：在会话顶部或侧栏增加 KB selector；回答引用点击后打开 chunk/source preview。

## FileMan 嵌入 Newman

如果要把 `/root/fileman` 直接嵌进 Newman，建议把 FileMan 当作“可迁移能力实现”和“产品原型”，而不是长期以独立子应用 sidecar 的方式运行。FileMan 已经具备解析、多模态、指纹卡、检索、对话溯源、知识图谱和前端管理界面，但它当前是单用户、本地 SQLite、独立 FastAPI/Vite 应用；Newman 则已有自己的认证、配置、runtime、工具系统、Postgres、前端导航和会话生命周期。

### 集成方式对比

| 方式 | 做法 | 优点 | 问题 | 建议 |
| --- | --- | --- | --- | --- |
| Sidecar 嵌入 | Newman 启动 FileMan 服务，通过 iframe 或反向代理挂到 `/fileman` | 最快可演示，改动少 | 两套后端、两套配置、两套数据、两套权限；Agent 难以原生调用 | 只适合临时过渡或验收演示 |
| 模块化迁移 | 将 FileMan 的解析、多模态、指纹卡、检索、图谱能力迁入 `backend/knowledge/`，前端组件迁到 Newman 页面 | 与 Newman runtime、工具、权限、Postgres 一体化 | 需要做数据模型和 API 适配 | 推荐路径 |
| 重新实现 | 只参考 FileMan PRD，从零按 Newman 架构实现 | 架构最干净 | 浪费已有实现，周期最长 | 不建议第一阶段采用 |

### 推荐策略

推荐采用“模块化迁移 + 分阶段优化”：先把 FileMan 可复用能力嵌入 Newman，跑通闭环；再把存储、检索、权限和前端体验按 Newman 的长期架构优化。

需要迁移的 FileMan 能力：

- `backend/app/parsers/`、`backend/app/core/pipeline.py`：迁到 `backend/knowledge/parsers/`，统一输出 `ParsedBlock[]`。
- `backend/app/parsers/mineru_pdf_backend.py`：改成 `MineruParserAdapter`，使用 Newman 配置体系。
- `backend/app/core/multimodal.py`：迁成可选图片理解模块，复用 Newman 的 `models.multimodal` provider。
- `backend/app/core/file_processing.py`：拆出 ingestion 队列、状态机和进度模型，改写为 `IngestionTask`。
- `backend/app/core/fingerprint.py`、`schema_extractor.py`：作为知识库文档摘要、元数据和后续图谱增强能力保留。
- `backend/app/core/search_engine.py`：保留 BM25/向量融合、别名、词典和解释思路，但底层从 SQLite FTS5 / 内存向量迁到 Postgres FTS / pgvector。
- `backend/app/core/knowledge_graph.py`、`kg_builder.py`：作为第二阶段增强，先不要阻塞 MVP ingestion 和检索。
- `frontend/src/components/files/`、`settings/`、`graph/`：按 Newman 视觉和导航体系重做为 Knowledge 页面组件。

不建议直接迁移的部分：

- FileMan 独立 `FastAPI` app、router 汇总和 CORS 配置，应合并到 Newman `backend/api/app.py`。
- FileMan `provider/`，Newman 已有 provider 和 multimodal analyzer，应统一复用 Newman 模型配置。
- FileMan `conversations` 和 `chat_engine`，Newman 已有 runtime 和 session，知识能力应通过 `knowledge_search` tool 接入。
- FileMan SQLite schema，只作为字段参考；Newman 长期存储应使用 Postgres。
- FileMan 前端 `App.tsx`，不应整页搬入；应拆组件并挂到 Newman 现有导航。

### 嵌入后的优化方向

1. 存储优化：SQLite 指纹卡和 FTS5 迁到 Postgres，文档、版本、chunk、任务、引用和图谱状态统一管理。
2. 检索优化：从“文件级指纹卡召回”扩展为“文件级指纹卡 + chunk 级 hybrid retrieval”双层召回。
3. 解析优化：FileMan 的 Markdown 中间层保留，但 ingestion 内部优先使用 `ParsedBlock[]`，避免后续 chunk 和 citation 只能依赖文本标记。
4. 图片优化：图片、图表、扫描件进入 `image` block；多模态只按策略调用，并加上数量、成本和超时限制。
5. Chunk 优化：第一版只保留 `general` 和 `table`，并把 `general` 的 token、overlap、heading、delimiter 参数做成用户可调。
6. Agent 优化：知识库不默认全局搜索，由会话显式选择 KB；`knowledge_search` 返回 chunk、来源和检索解释。
7. 前端优化：保留 FileMan 的上传、任务状态、预览、检索解释体验，但统一到 Newman 的页面、样式、鉴权和会话入口。
8. 运行时优化：ingestion worker 接入 Newman 启停生命周期，重启后可恢复 running/pending 任务。

### 迁移切分建议

第一阶段先做最小闭环：

```text
FileMan parser / MinerU / multimodal
-> Newman ParsedBlock
-> general/table chunker
-> Postgres knowledge store
-> hybrid search API
-> knowledge_search tool
-> Knowledge 页面上传与检索测试
```

第二阶段再迁移 FileMan 的指纹卡、别名词典、候选复核和知识图谱。这样可以避免一开始就把 FileMan 的完整产品形态硬塞进 Newman，导致聊天、知识库、图谱、会话和配置边界同时重构。

## 实施顺序

1. FileMan 梳理：确认可迁移模块、依赖、配置项和当前测试覆盖，避免直接搬入独立 app。
2. 后端基础：配置、Postgres schema、knowledge store、embedding provider、pgvector 部署检查。
3. 解析接入：复用 Newman 本地 parser，迁入 FileMan MinerU 和多模态能力，统一输出 `ParsedBlock[]`。
4. MVP ingestion：上传文档、异步任务、chunk、embedding、索引、状态查询。
5. 检索工具：实现 hybrid retrieval 和 `knowledge_search`，接入 Agent runtime。
6. 前端 MVP：KB 列表、上传、任务状态、chunk 列表、retrieval test。
7. 聊天体验：会话选择 KB、工具调用结果引用、citation 点击预览。
8. 增强能力：迁入 FileMan 指纹卡、别名词典、候选复核、图谱、表格列角色、parent-child、rerank、OCR/图片增强、artifact/TOC。

## 第一版验收标准

- Markdown、PDF、XLSX 至少能导入并完成 `ready` 状态。
- MinerU 失败时能 fallback，不阻塞整个 ingestion。
- 文档图片能保留为 `image` block；启用图片理解时，多模态失败也不阻塞 ingestion。
- Chunk 可定位到文档版本、页码或结构位置。
- 禁用或删除 chunk 后不会再被召回。
- `knowledge_search` 返回稳定、可引用的结果。
- Retrieval Test 能解释为什么召回或没召回。
- 前端能完成“建库 -> 上传 -> 看任务 -> 看 chunk -> 测检索 -> 聊天引用”的闭环。

## 关键取舍

这套方案的关键取舍是：解析能力尽量复用，知识库生命周期和检索索引必须 Newman 自己掌控。这样可以避免把长期知识库状态绑定到聊天附件的短生命周期，也避免将 Newman 的文档版本、权限、chunk 运营、检索解释和引用生成交给第三方框架隐藏处理。
