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

### 后端

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ./backend
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

- `NEWMAN_PROVIDER_TYPE`
- `NEWMAN_PROVIDER_MODEL`
- `NEWMAN_PROVIDER_ENDPOINT`
- `NEWMAN_PROVIDER_API_KEY`
- `NEWMAN_SERVER_PORT`

## 启动

### 启动后端

```bash
source .venv/bin/activate
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
