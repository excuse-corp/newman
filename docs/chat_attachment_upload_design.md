# 对话附件上传与解析功能需求梳理和方案设计

> 更新说明：对话框附件解析现已收口为“用户提交后同步解析，解析完成后再进入后续 runtime 处理”的单阶段流程，不再区分 Stage A / Stage B。

## 1. 背景与目标

当前 Newman 对话框附件能力主要面向图片：前端只选择 PNG/JPEG，后端 `POST /api/sessions/{session_id}/messages` 只读取 multipart 表单中的 `images` 字段，文件保存到 `backend_data/uploads/chat/{session_id}/`，随后进入多模态预解析，并把结果写入 user message 的 `metadata.multimodal_parse`。

本次优化目标是把“对话附件上传与本轮分析”建设为独立能力，并与 RAG 知识库导入、索引、检索明确区分。

目标包括：

- 用户可在对话输入框上传附件，不局限于图片。
- 一次最多上传 5 个附件，单文件最大 20MB。
- 支持图片，以及 Word、Excel、PDF、PPT、Markdown、TXT、JSON、HTML。
- 不支持的格式、超数量、超大小等准入问题要给用户明确反馈。
- 图片沿用当前缩略预览；其他附件展示文件名和格式的缩略卡片。
- 对话附件原件落到 `runtime-workspace`，并按文件来源分目录保存。
- 文件解析链路参考 `/root/fileman/docs/file-parse-scheme.md`，统一产出 Markdown 和定位信息。
- 对话附件只作为当前会话/当前轮上下文，不自动进入 RAG 知识库。

## 2. 范围边界

### 2.1 包含

- 对话框附件选择、校验、移除、发送。
- 附件准入规则和错误反馈。
- 对话附件在 `runtime-workspace` 的目录规划。
- 后端 multipart 接口从 `images` 泛化为 `attachments`。
- 对话附件的保存、元数据记录、解析状态流转。
- 图片、文档、表格、演示文稿、文本类文件的统一解析输出设计。
- prompt 注入策略：把解析摘要或结构化 Markdown 摘要提供给主模型。
- SSE 附件事件从“图片预解析”泛化为“附件解析”。
- 与 RAG 上传和检索链路隔离。

### 2.2 不包含

- 不在本功能中把对话附件自动写入 `rag_documents`、Chroma 或知识库目录。
- 不在本功能中替代 `/api/knowledge/documents/upload`。
- 不把 HTML 附件作为可执行页面直接渲染。
- 不保证 Stage B 增强解析一定在当前 assistant 回复前完成。
- 不实现复杂的版本管理和自动清理策略。

## 3. 支持格式与准入规则

### 3.1 支持格式

| 类型 | 扩展名 | 说明 |
|---|---|---|
| 图片 | `.jpg`、`.jpeg`、`.png`、`.webp` | `.webp` 是否启用取决于多模态 provider 能力；若当前 provider 不支持，应在后端准入配置中关闭 |
| Word | `.doc`、`.docx` | `.doc` 需要先转换为 `.docx` 再解析 |
| Excel | `.xls`、`.xlsx` | `.xls` 需要先转换为 `.xlsx` 再解析 |
| PDF | `.pdf` | 支持文本型 PDF；扫描型 PDF 进入后台增强 |
| PPT | `.ppt`、`.pptx` | `.ppt` 需要先转换为 `.pptx` 再解析 |
| Markdown | `.md` | 作为文本类解析 |
| TXT | `.txt` | 自动识别常见编码 |
| JSON | `.json` | 格式化为可读 Markdown/代码块 |
| HTML | `.html`、`.htm` | 抽取可见文本和基础结构，禁止直接执行脚本 |

> 说明：用户要求“其他格式不行”，因此 CSV、YAML、源码文件等不纳入对话附件准入，即使当前 RAG parser 对部分格式已有支持。

### 3.2 数量与大小

- 单轮最多 5 个附件。
- 单个附件最大 20MB，按 `20 * 1024 * 1024` 字节计算。
- 空文件拒绝上传。
- 前端先校验，后端必须重复校验。
- 后端校验失败时不保存任何本次新上传文件，避免半成功状态。

### 3.3 文件类型判断

准入判断采用“扩展名 allowlist 为主，MIME 和文件头辅助”的策略：

- 不能只信任浏览器传来的 `content_type`。
- 文件名要做 basename 提取和危险字符清理，禁止路径穿越。
- Office 文件按扩展名和 zip/复合文档文件头辅助判断。
- HTML 只作为文本解析输入，不允许在当前页面直接注入渲染。

## 4. 用户体验要求

### 4.1 输入框附件选择

前端文件输入框使用新的 accept 范围：

```text
image/png,image/jpeg,image/webp,
.doc,.docx,.xls,.xlsx,.pdf,.ppt,.pptx,.md,.txt,.json,.html,.htm
```

交互要求：

- 选择附件后立即展示在输入框上方或输入框内部的附件区。
- 图片继续展示 50px 级别缩略图。
- 非图片展示文件卡片：文件格式 badge、文件名、可选大小。
- 卡片右上角保留移除按钮。
- 发送中禁用新增和移除附件。
- 附件区最多展示 5 个，超出时拒绝新增并提示。

### 4.2 错误反馈文案

前端校验和后端返回要映射成用户可理解的中文提示：

| 场景 | 推荐文案 |
|---|---|
| 数量超过 5 个 | `一次最多上传 5 个附件，请移除多余文件后重试` |
| 单文件超过 20MB | `《{filename}》超过 20MB，无法上传` |
| 不支持格式 | `《{filename}》格式不支持。支持图片、Word、Excel、PDF、PPT、MD、TXT、JSON、HTML` |
| 空文件 | `《{filename}》为空文件，无法上传` |
| 保存失败 | `附件保存失败，请重试` |
| 解析失败 | `《{filename}》解析失败，当前回复将不使用该附件内容` |
| 全部附件解析失败且用户未输入文本 | `附件解析失败，请更换文件或稍后重试` |

准入错误应阻断发送；解析错误可按单文件降级处理，并通过消息流反馈。

## 5. Runtime Workspace 目录规划

对话附件不再保存到 `backend_data/uploads/chat`，新文件应落到 `paths.workspace` 指向的 `runtime-workspace`。建议目录如下：

```text
{runtime-workspace}/
├── user_uploads/
│   └── chat/
│       └── {session_id}/
│           └── {turn_id}/
│               ├── originals/
│               │   └── {attachment_id}.{ext}
│               └── manifest.json
├── parser_outputs/
│   └── chat/
│       └── {session_id}/
│           └── {turn_id}/
│               ├── {attachment_id}.stage-a.md
│               ├── {attachment_id}.final.md
│               └── assets/
├── system_generated/
│   └── chat/
│       └── {session_id}/
│           └── {turn_id}/
└── temp/
    └── uploads/
```

目录职责：

- `user_uploads/`：用户直接上传的原件。
- `parser_outputs/`：系统解析生成的 Markdown、定位信息、解析中间产物。
- `system_generated/`：assistant 或工具在会话中生成的文件。
- `temp/`：上传临时文件、转换临时文件，完成后可迁移或保留为排错材料。

保存要求：

- 原件文件名使用 `{attachment_id}.{ext}`，避免重名和路径问题。
- 原始文件名只保存在 metadata 和 manifest 中。
- 每个 turn 独立目录，便于审计和后续引用。
- 后端返回给前端的路径应同时包含绝对路径和 workspace 相对路径，前端展示优先使用相对路径。
- 老会话中的 `backend_data/uploads/chat` 路径继续兼容读取，但新上传不再写入旧目录。

## 6. 后端接口设计

### 6.1 消息发送接口

沿用：

```http
POST /api/sessions/{session_id}/messages
```

multipart 字段调整：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content` | string | 用户输入文本，可为空 |
| `attachments` | file[] | 新的通用附件字段 |
| `images` | file[] | 兼容旧字段，内部合并到 attachments |
| `approval_mode` | string | 保持现有逻辑 |

后端逻辑：

1. 解析 JSON 或 multipart 请求。
2. 收集 `attachments` 和兼容字段 `images`。
3. 执行数量、大小、扩展名、空文件校验。
4. 生成 `turn_id` 和 `attachment_id`。
5. 保存原件到 `runtime-workspace/user_uploads/chat/{session_id}/{turn_id}/originals/`。
6. 写入 `manifest.json`。
7. 创建 user message，metadata 中记录附件状态。
8. 发送 `attachment_received` SSE。
9. 调用附件解析服务。
10. 更新 user message metadata。
11. 发送 `attachment_processed` SSE。
12. 调用主模型处理本轮消息。

### 6.2 上传内容读取接口

当前 `GET /api/workspace/upload-content?path=...` 只允许读取 `backend_data/uploads/chat`。需要调整为：

- 新增 `GET /api/workspace/attachment-content?path=...`，只允许读取 `runtime-workspace/user_uploads` 和必要的 `parser_outputs`。
- 旧的 `/upload-content` 保留兼容老图片消息。
- 对图片返回 inline 预览。
- 对 PDF 可返回 inline 或 download，按前端能力决定。
- 对 Office/JSON/HTML/TXT 默认不直接渲染，只用于下载或受控预览。

## 7. 元数据模型

在 user message 的 `metadata` 中新增通用附件结构，逐步替代只面向图片的 `multimodal_parse`。

```json
{
  "original_content": "请总结附件",
  "input_modalities": ["text", "image", "document"],
  "attachments": [
    {
      "attachment_id": "att_xxx",
      "source": "user_upload",
      "kind": "pdf",
      "filename": "report.pdf",
      "extension": ".pdf",
      "content_type": "application/pdf",
      "size_bytes": 1048576,
      "path": "/data/newman/runtime_workspace/user_uploads/chat/{session_id}/{turn_id}/originals/att_xxx.pdf",
      "workspace_relative_path": "user_uploads/chat/{session_id}/{turn_id}/originals/att_xxx.pdf",
      "analysis_status": "parsed",
      "parser_stage": "stage_a",
      "parsed_markdown_path": "/data/newman/runtime_workspace/parser_outputs/chat/{session_id}/{turn_id}/att_xxx.stage-a.md",
      "parsed_markdown_relative_path": "parser_outputs/chat/{session_id}/{turn_id}/att_xxx.stage-a.md",
      "summary": "文件包含 Q1 销售数据和区域对比。",
      "warnings": []
    }
  ],
  "attachment_analysis": {
    "schema_version": "v1",
    "status": "completed",
    "normalized_user_input": "请基于 report.pdf 的解析内容总结重点",
    "attachment_summaries": [
      {
        "attachment_id": "att_xxx",
        "status": "parsed",
        "summary": "文件包含 Q1 销售数据和区域对比。",
        "markdown_path": "/data/newman/runtime_workspace/parser_outputs/chat/{session_id}/{turn_id}/att_xxx.stage-a.md",
        "quality": "usable",
        "warnings": []
      }
    ]
  }
}
```

兼容策略：

- 旧图片消息继续读取 `metadata.multimodal_parse`。
- 新消息统一写 `metadata.attachment_analysis`。
- 对图片可额外同步写一份 `multimodal_parse`，避免现有 prompt 和标题生成逻辑立即失效。
- `build_user_message_for_provider` 优先读取 `attachment_analysis`，不存在时 fallback 到 `multimodal_parse`。

## 8. 附件解析服务设计

新增独立服务，例如：

```text
backend/attachments/
├── models.py
├── service.py
├── validation.py
├── storage.py
└── parser.py
```

该服务不放在 `backend/rag/` 下，避免职责混淆。

### 8.1 职责

- `validation.py`：附件数量、大小、扩展名、MIME、空文件校验。
- `storage.py`：保存原件、写 manifest、返回 workspace 路径。
- `parser.py`：按文件类型调度解析器。
- `service.py`：串联保存、解析、metadata 生成、错误归一化。

### 8.2 解析流程

参考 FileMan 方案，采用 Stage A + Stage B：

```text
上传接收
  ↓
准入检查
  ↓
保存原件到 runtime-workspace/user_uploads
  ↓
Stage A 基础解析
  ↓
生成 stage-a Markdown + 定位信息
  ↓
质量门禁
  ↓
主模型使用 stage-a 摘要/片段回答
  ↓
Stage B 后台增强
  ↓
生成 final Markdown
```

### 8.3 Stage A

Stage A 目标是在当前请求内尽快形成可用上下文：

- 文本类：读取文本、识别编码、按自然段切分。
- JSON：解析后格式化，失败则按文本降级。
- HTML：提取标题、正文文本、表格文本、链接文本；剔除 script/style。
- PDF：优先结构化抽取；失败后基础文本抽取；扫描型 PDF 标记为待增强。
- Word：抽取标题、段落、表格；内嵌图片先占位。
- Excel：按工作表和原始行号生成 Markdown 表格。
- PPT：按幻灯片抽取标题、文本框、表格、备注；图片和图表先占位。
- 图片：沿用当前多模态分析，或接入统一 OCR/视觉描述。

Stage A 产出：

- `{attachment_id}.stage-a.md`
- 附件级 summary
- prompt digest
- 定位信息覆盖率
- warnings

### 8.4 Stage B

Stage B 后台执行增强能力：

- 图片 OCR 或视觉理解。
- PDF 扫描页整页识别。
- Word/PPT 内嵌图片说明补充。
- PPT 文本极少页面整页理解。
- 图表说明补充。

Stage B 产出：

- `{attachment_id}.final.md`
- 更新 manifest 和 message metadata。
- 可选发送 `attachment_enhanced` SSE，若当前会话仍在线。

### 8.5 质量门禁

参考 FileMan 质量口径：

- Stage A 至少要有非空内容块。
- 有效正文过少时标记 warning 或 failed。
- PDF 可读页过少时转扫描型增强，不直接失败。
- Markdown 过大时不直接注入 prompt，只保留路径和摘要。
- 疑似乱码比例过高时标记 warning。

解析失败不等同于上传失败：

- 准入失败：阻断发送。
- 单附件解析失败：保留 metadata，当前回复不使用该附件内容。
- 全部附件解析失败且无文本：阻断主模型或返回明确错误。

## 9. Prompt 注入策略

对话附件解析结果不能无上限塞入 prompt。建议按三层提供上下文：

1. 附件清单：文件名、类型、大小、workspace 相对路径。
2. 解析摘要：每个附件的 summary、解析状态、警告。
3. 片段摘录：在 token budget 内加入 Stage A Markdown 的前若干关键片段。

当解析 Markdown 较大时：

- prompt 中只放摘要和路径。
- 提示模型如需完整内容，可使用 `read_file_range` 读取 `parser_outputs/.../{attachment_id}.stage-a.md`。
- 不把 20MB 原文件内容直接写入 session。

用户原话仍保留在 `metadata.original_content`，展示层继续展示原文，不展示拼接后的附件上下文。

## 10. 与 RAG 的隔离设计

### 10.1 对话附件链路

```text
对话框上传
  → runtime-workspace/user_uploads
  → attachment parser
  → runtime-workspace/parser_outputs
  → user message metadata
  → 当前轮 prompt / 后续会话上下文
```

特点：

- 作用域是当前会话，默认不进入全局知识库。
- 不写 `rag_documents`。
- 不写 Chroma。
- 不通过 `search_knowledge_base` 检索。
- 文件路径在 runtime workspace 内，模型可按权限读取解析产物。

### 10.2 RAG 知识库链路

```text
知识库上传或导入
  → backend_data/uploads/knowledge 或 workspace source
  → KnowledgeBaseService
  → backend_data/knowledge
  → rag_documents / rag_chunks
  → Chroma
  → search_knowledge_base
```

特点：

- 作用域是知识库。
- 面向长期检索和引用溯源。
- 需要显式上传到知识库或显式执行“导入知识库”动作。

### 10.3 显式转知识库

后续可以增加“将本附件加入知识库”动作，但必须是显式操作：

- 前端在附件卡片或文件库提供按钮。
- 后端调用 `/api/knowledge/documents/import` 或新的 import-from-attachment 接口。
- 记录来源：`source_path = runtime-workspace/user_uploads/...`。
- RAG 入库后生成新的 knowledge document，不复用对话附件 metadata 作为知识库事实来源。

## 11. 前端改造点

主要文件：

- `frontend/src/App.tsx`
- `frontend/src/chat/MessageContent.tsx`
- `frontend/src/styles.css`

改造内容：

- `composerAttachments` 从图片模型扩展为通用附件模型。
- `appendComposerAttachments` 增加数量、大小、扩展名校验。
- FormData 字段从 `images` 改为 `attachments`，同时不再按 image-only 过滤。
- 选择文件后为图片生成 object URL；非图片不生成图片预览。
- composer 附件区增加文件卡片样式。
- 用户消息气泡里的附件展示从 `aria-label="已上传图片"` 改为 `已上传附件`。
- `MessageContent` 判断 `contentType` 或扩展名：图片展示缩略图；非图片展示格式 badge + 文件名。
- timeline 文案从“图片预解析”改为“附件解析”。
- SSE `attachment_received` 和 `attachment_processed` 的文件摘要展示支持非图片。

## 12. 后端改造点

主要文件：

- `backend/api/routes/messages.py`
- `backend/api/routes/workspace.py`
- `backend/runtime/message_rendering.py`
- 新增 `backend/attachments/`
- 补充 `backend/tests/test_api_contracts.py` 或新增附件测试文件

改造内容：

- 增加通用附件配置常量：
  - `MAX_ATTACHMENTS_PER_TURN = 5`
  - `MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024`
  - `ALLOWED_ATTACHMENT_SUFFIXES`
- `_parse_request_payload` 返回 `attachments`，兼容 `images`。
- `_save_uploads` 拆分为 validation + workspace storage。
- 保存路径改为 `settings.paths.workspace / "user_uploads" / "chat" / session_id / turn_id / "originals"`。
- 附件事件 payload 增加 `kind`、`extension`、`size_bytes`、`analysis_status`。
- `_build_attachment_analysis_failure` 文案从图片泛化为附件。
- `_infer_input_modalities` 支持 document/spreadsheet/presentation/pdf/text/html。
- `message_rendering` 优先读取 `attachment_analysis`。
- workspace 附件读取接口允许读取 runtime workspace 下的附件和解析产物。

## 13. 状态模型

附件状态建议：

| 状态 | 含义 |
|---|---|
| `received` | 后端已接收请求，但尚未保存 |
| `saved` | 原件已保存到 runtime workspace |
| `parsing` | Stage A 解析中 |
| `parsed` | Stage A Markdown 已生成，可用于当前轮 |
| `enhancing` | Stage B 增强解析中 |
| `ready` | final Markdown 已生成 |
| `failed` | 解析失败，当前不可用 |

SSE 事件建议：

- `attachment_received`：保存成功后发送，包含附件清单。
- `attachment_processed`：Stage A 完成后发送，包含每个附件解析状态。
- `attachment_enhanced`：Stage B 完成后可选发送。

## 14. 验收标准

功能验收：

- 用户可在对话框上传图片、Word、Excel、PDF、PPT、MD、TXT、JSON、HTML。
- 一次上传 6 个附件时，前端和后端都能拒绝，并提示最多 5 个。
- 上传超过 20MB 的单文件时，前端和后端都能拒绝，并提示具体文件名。
- 上传不支持格式时，提示具体文件名和支持范围。
- 上传非图片后，输入框和用户消息气泡都展示文件名和格式缩略卡片。
- 新上传原件保存在 `runtime-workspace/user_uploads/...`。
- 解析产物保存在 `runtime-workspace/parser_outputs/...`。
- 对话附件不会出现在 RAG 文档列表，不会写入 `rag_documents` 或 Chroma。
- 当前轮主模型能读取已解析附件摘要，并可通过 `read_file_range` 读取解析 Markdown。
- 图片旧消息仍能预览，旧 `images` 字段接口兼容。

测试验收：

- 后端覆盖数量、大小、格式、空文件、保存路径、metadata、SSE payload。
- 后端覆盖“附件上传不触发 KnowledgeBaseService”的隔离测试。
- 前端覆盖文件选择校验和附件卡片展示。
- 手工验证 PDF、DOCX、XLSX、PPTX、MD、TXT、JSON、HTML、PNG/JPEG 的端到端发送。

## 15. 推荐实施顺序

1. 后端先抽象通用附件模型、准入校验和 runtime-workspace 保存。
2. 前端放开文件选择并完成非图片卡片展示。
3. SSE 和 timeline 文案从图片泛化为附件。
4. 接入 Stage A 解析，先支持文本、JSON、HTML、PDF、DOCX、XLSX、PPTX。
5. 增加旧 Office 格式转换和图片/webp 能力。
6. 接入 Stage B 增强解析和质量门禁。
7. 补齐测试，并验证与 RAG 数据链路隔离。
