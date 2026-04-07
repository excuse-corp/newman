# Newman

本仓库包含 Newman 的本地优先后端、前端工作台，以及运行期数据目录。

## 目录说明

- `backend/`：FastAPI 后端与运行时逻辑
- `frontend/`：前端工作台
- `backend_data/`：运行期数据，默认不提交
- `plugins/`：插件目录
- `skills/`：工作区级技能目录
- `docs/`：PRD 与 API 文档

## 环境准备

### Conda 环境

```bash
conda env create -f environment.yml
conda activate newman
```

如需增量安装依赖，统一在 `newman` 环境中执行。

首次进入仓库后的推荐顺序：

```bash
conda activate newman
./scripts/dev/start_postgres.sh
uvicorn backend.main:app --reload
```

### 本地 PostgreSQL

```bash
./scripts/dev/start_postgres.sh
```

默认会在本机启动：

- PostgreSQL: `127.0.0.1:54329`
- Database: `newman`
- Username: `postgres`
- Auth: 本地开发默认为 `trust`

停止命令：

```bash
./scripts/dev/stop_postgres.sh
```

### 前端

```bash
cd frontend
npm install
```

## 配置

Newman 按以下优先级加载配置：

1. 环境变量
2. `~/.newman/config.yaml`
3. 项目根目录 `newman.yaml`（可选，默认不存在）
4. `backend/config/defaults.yaml`

项目根目录 `.env` 和 `~/.newman/.env` 中以 `NEWMAN_` 开头的变量也会自动加载。可先复制：

```bash
cp .env.example .env
```

常见变量示例：

- `NEWMAN_MODELS_PRIMARY_TYPE`
- `NEWMAN_MODELS_PRIMARY_MODEL`
- `NEWMAN_MODELS_MULTIMODAL_MODEL`
- `NEWMAN_MODELS_EMBEDDING_MODEL`
- `NEWMAN_MODELS_RERANKER_MODEL`
- `NEWMAN_RAG_POSTGRES_DSN`
- `NEWMAN_RAG_CHROMA_COLLECTION`
- `NEWMAN_PATHS_CHROMA_DIR`
- `NEWMAN_SERVER_PORT`
- `NEWMAN_SANDBOX_ENABLED`
- `NEWMAN_SANDBOX_MODE`
- `NEWMAN_PATHS_WORKSPACE`

模型配置现已拆为 4 个槽位：

- `models.primary`：主 LLM，负责文本输出、工具调用等主链路
- `models.multimodal`：多模态模型，预留给图片理解等能力
- `models.embedding`：Embedding 模型，预留给向量化
- `models.reranker`：Reranker 模型，预留给 RAG 重排序

兼容说明：

- 历史配置里的 `provider.*` 仍会自动映射到 `models.primary.*`
- 历史环境变量 `NEWMAN_PROVIDER_*` 也仍兼容，但新配置建议统一改为 `NEWMAN_MODELS_PRIMARY_*`

RAG 当前按 PRD 目标落地为：

- File System：原始文档与解析产物
- PostgreSQL：文档元数据、chunk 映射、检索统计
- Chroma：向量索引与向量检索

Linux 原生沙箱默认配置示例：

```yaml
sandbox:
  enabled: true
  backend: "linux_bwrap"
  mode: "workspace-write"
  network_access: false
  writable_roots: []
```

## 启动

### 启动后端

```bash
conda activate newman
uvicorn backend.main:app --reload
```

默认地址：

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`

### 启动前端

```bash
cd frontend
npm run dev
```

默认地址：

- Frontend: `http://localhost:5173`

## 常用文件

- 后端依赖：`backend/pyproject.toml`
- 默认配置：`backend/config/defaults.yaml`
- API 文档：`docs/Newman_API_v1.md`
- 稳定记忆：`backend_data/memory/`

## 说明

- `requirements.txt` 当前未单独维护，因为后端依赖已由 `backend/pyproject.toml` 管理。
- `backend_data/` 属于运行时数据目录，默认通过 `.gitignore` 忽略。

## 当前待办

- `anthropic_compatible` Provider 目前未把工具调用结果解析回 `tool_calls`，切到该 Provider 时工具链路未完全生效。
- 飞书/企微 Channel 的 `send_response` 目前还是占位实现，Webhook 入站可用，但平台回发消息未真正落地。
- 插件 Hook 模型里声明了 `FileChanged` 事件，但运行时当前还没有发出该事件。
