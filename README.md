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

推荐直接按下面两条命令创建并进入环境：

```bash
cd /root/newman
conda env create -f environment.yml
conda activate newman
```

说明：

- `environment.yml` 会创建名为 `newman` 的 Conda 环境
- 其中已经包含 `-e ./backend`，所以会自动按开发模式安装 `backend/pyproject.toml` 中声明的后端依赖
- 一般情况下，不需要再额外手动执行一次 `pip install -e ./backend`
- 如需增量安装依赖，统一在 `newman` 环境中执行

如果前端依赖还没安装，再执行一次：

```bash
cd /root/newman/frontend
npm install
```

### 最推荐启动方式

本项目最省事的启动命令是：

```bash
cd /root/newman
conda activate newman
./scripts/dev/start_services.sh
```

它会在后台常驻启动：

- PostgreSQL
- 后端 API
- 前端工作台

### 本地 PostgreSQL

```bash
./scripts/dev/start_postgres.sh
```

默认会在本机启动：

- PostgreSQL: `127.0.0.1:65437`
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

这里要特别说明两点：

- `~/.newman/config.yaml` 默认不存在；只有你想给“这台机器上的所有 Newman 项目”做全局配置时，才需要自己创建
- 项目根目录 `newman.yaml` 也默认不存在；只有你想给“当前这个项目”单独覆盖配置时，才需要自己创建

也就是说，这两个文件没有也完全正常，Newman 仍然可以直接启动。

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

最常见的本地开发做法是：

1. 先保持 `backend/config/defaults.yaml` 不动
2. 只在项目根目录 `.env` 里覆盖你真的需要改的几个值

例如：

```env
NEWMAN_SERVER_PORT=8005
NEWMAN_RAG_POSTGRES_DSN=postgresql://postgres@127.0.0.1:65437/newman
```

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
- PostgreSQL：文档元数据、chunk 映射、检索统计、引用记录
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

### 一键后台启动

```bash
cd /root/newman
conda activate newman
./scripts/dev/start_services.sh
```

启动后访问：

- Frontend: `http://127.0.0.1:7775`
- Backend API: `http://127.0.0.1:8005`
- Backend Docs: `http://127.0.0.1:8005/docs`
- OpenAPI JSON: `http://127.0.0.1:8005/openapi.json`
- PostgreSQL: `127.0.0.1:65437`

日志与 PID 文件位置：

- 日志目录：`backend_data/run/logs/`
- PID 文件：`backend_data/run/backend.pid`、`backend_data/run/frontend.pid`

停止命令：

```bash
cd /root/newman
./scripts/dev/stop_services.sh
```

### 手动分开启动

先启动 PostgreSQL：

```bash
cd /root/newman
conda activate newman
./scripts/dev/start_postgres.sh
```

再启动后端：

```bash
cd /root/newman
conda activate newman
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8005
```

最后启动前端：

```bash
cd /root/newman/frontend
npm run dev -- --host 0.0.0.0 --port 7775 --strictPort
```

### 启动排错

如果 PostgreSQL 相关脚本报错，优先按下面顺序重试：

```bash
cd /root/newman
./scripts/dev/stop_services.sh
./scripts/dev/start_services.sh
```

如果仍有问题，再单独看 PostgreSQL：

```bash
cd /root/newman
./scripts/dev/start_postgres.sh
```

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
