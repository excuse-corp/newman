# M07 RAG — 文档解析与知识检索

> Newman 模块 PRD · Phase 2 · 预估 12 工作日

---

## 一、模块目标

实现文档导入、解析、索引、混合检索和引用溯源的完整链路。

---

## 二、功能范围

### ✅ 包含

- 文档解析器（PDF / Word / PPT / Excel / 图片）
- Chunk 切分策略
- Embedding 生成与 Chroma 持久化
- BM25 + Vector 混合检索
- Reranker 重排序（本地部署的 OpenAI-compatible 模型）
- PostgreSQL 元数据存储（文档、chunk 映射、引用记录、统计数据）
- 引用生成（文档名 + 片段位置 + 页码 + 预览）

### ❌ 不包含

- OCR / 多模态解析
- 在线文档协作

---

## 三、前置依赖

- M01 Provider（Embedding 生成）
- PostgreSQL 实例

---

## 四、文件结构

```text
rag/
  parser/
    base.py               # 解析器基类
    pdf_parser.py          # PDF 解析（PyMuPDF + pdfplumber）
    docx_parser.py         # Word 解析（python-docx）
    pptx_parser.py         # PPT 解析（python-pptx）
    xlsx_parser.py         # Excel 解析（openpyxl）
  chunker.py              # Chunk 切分
  embedder.py             # Embedding 生成
  retriever.py            # 混合检索（BM25 + Vector）
  reranker.py             # Reranker 重排序
  citation.py             # 引用生成
  models.py               # 数据模型（ExtractedDoc, Chunk, Citation）
  store.py                # PostgreSQL 元数据存储
```

---

## 五、核心设计

### 处理流程

```text
文档导入 → 文档解析 → Chunk 切分 → Embedding → Chroma 持久化
               ↓
            元数据入 PostgreSQL
               ↓
用户查询 → BM25 + Vector Search → Reranker → 引用生成
```

### 存储职责

| 存储 | 职责 |
|------|------|
| File System | 原始文档和解析产物 |
| Chroma | 向量检索 |
| PostgreSQL | 文档元数据、chunk 映射、引用记录、统计数据 |

### 文档解析技术栈

| 格式 | 工具 |
|------|------|
| PDF | PyMuPDF + pdfplumber |
| Word | python-docx |
| PPT | python-pptx |
| Excel | openpyxl |

### Chunk 切分策略

- 默认 chunk size：512 tokens
- overlap：64 tokens
- 按段落边界优先切分
- 保留元数据（文档名、页码、段落索引）

### 引用输出格式

```json
{
  "doc_name": "报告.pdf",
  "page": 5,
  "chunk_index": 12,
  "snippet": "关键片段预览文本...",
  "score": 0.87
}
```

---

## 六、验收标准

1. 端到端：文档上传 → 解析 → 索引 → 检索 → 引用输出
2. 混合检索结果经 Reranker 重排后 Top-5 相关性显著提升
3. 引用包含文档名、页码、片段预览
4. 支持至少 4 种文档格式（PDF / Word / PPT / Excel）
5. 单文档导入耗时 < 30 秒（100 页 PDF 基准）

---

## 七、技术备注

- Reranker 是本地部署的 OpenAI-compatible 模型（如 bge-reranker）
- BM25 使用 rank_bm25 库，基于内存索引
- Chroma 使用本地持久化模式
- 建议拆为两个子任务：「解析+索引」和「检索+引用」
