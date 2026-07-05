# Newman 端口说明

> 更新日期：2026-07-05

本文只维护 Newman 项目自身使用的端口。服务器上其他系统服务、临时 MCP server、数据库或反向代理端口不在本文范围内。

相关配置来源：

- `docker-compose.yml`
- `scripts/dev/common.sh`
- `scripts/dev/start_services.sh`
- `scripts/dev/start_postgres.sh`
- `frontend/vite.config.ts`
- `backend/config/defaults.yaml`

## 1. Docker 部署端口

Docker 是 Windows 用户推荐部署方式。

| 服务 | 宿主机端口 | 容器端口 | 默认地址 | 说明 |
| --- | ---: | ---: | --- | --- |
| Frontend | `17775` | `80` | `http://127.0.0.1:17775` | Nginx 静态前端 |
| Backend API | `18005` | `8005` | `http://127.0.0.1:18005` | FastAPI 服务 |
| Backend Docs | `18005` | `8005` | `http://127.0.0.1:18005/docs` | OpenAPI 文档 |
| PostgreSQL | 不暴露 | `5432` | Compose 内部访问 | `backend` 通过服务名 `postgres` 访问 |

端口来源：

```yaml
frontend:
  ports:
    - "${NEWMAN_FRONTEND_PORT:-17775}:80"

backend:
  ports:
    - "${NEWMAN_BACKEND_PORT:-18005}:8005"
```

常用启动：

```bash
docker compose up -d --build
```

自定义 Docker 对外端口：

```bash
NEWMAN_FRONTEND_PORT=7775 NEWMAN_BACKEND_PORT=8005 docker compose up -d --build
```

Windows PowerShell 写法：

```powershell
$env:NEWMAN_FRONTEND_PORT="7775"
$env:NEWMAN_BACKEND_PORT="8005"
docker compose up -d --build
```

注意：

- Docker 模式下，后端容器内部始终监听 `8005`。
- Docker 模式下，PostgreSQL 默认只在 Compose 网络内部暴露，不占用宿主机 `65437`。
- 容器访问宿主机服务时使用 `host.docker.internal`，不要写 `127.0.0.1`。

## 2. 源码开发端口

源码部署是 macOS / Linux 推荐方式。

| 服务 | 默认端口 | 默认地址 | 环境变量 | 说明 |
| --- | ---: | --- | --- | --- |
| Frontend dev server | `7775` | `http://127.0.0.1:7775` | `NEWMAN_FRONTEND_PORT` | Vite，启用 `--strictPort` |
| Backend API | `8005` | `http://127.0.0.1:8005` | `NEWMAN_BACKEND_PORT` | Uvicorn / FastAPI |
| Backend Docs | `8005` | `http://127.0.0.1:8005/docs` | `NEWMAN_BACKEND_PORT` | OpenAPI 文档 |
| PostgreSQL | `65437` | `127.0.0.1:65437` | `NEWMAN_PG_PORT` | 本地开发专用 PostgreSQL |

启动脚本：

```bash
./scripts/dev/start_services.sh
```

脚本默认值来自 `scripts/dev/common.sh`：

```bash
NEWMAN_BACKEND_HOST=0.0.0.0
NEWMAN_BACKEND_PORT=8005
NEWMAN_FRONTEND_HOST=0.0.0.0
NEWMAN_FRONTEND_PORT=7775
NEWMAN_PG_PORT=65437
```

Vite 默认把 API 代理到：

```text
http://127.0.0.1:8005
```

如需覆盖前端代理目标：

```bash
VITE_API_PROXY=http://127.0.0.1:8005 npm run dev
```

## 3. 模式对比

| 模式 | 前端访问 | 后端访问 | PostgreSQL |
| --- | --- | --- | --- |
| Docker | `127.0.0.1:17775` | `127.0.0.1:18005` | Compose 内部 `postgres:5432` |
| 源码开发 | `127.0.0.1:7775` | `127.0.0.1:8005` | `127.0.0.1:65437` |

选择建议：

- Windows：优先 Docker，使用 `17775 / 18005`。
- macOS / Linux：优先源码开发，使用 `7775 / 8005 / 65437`。
- 需要让 Docker 端口和源码端口一致时，可设置 `NEWMAN_FRONTEND_PORT=7775`、`NEWMAN_BACKEND_PORT=8005`。

## 4. 外部服务端口

Newman 可能访问外部服务，但这些端口不由 Newman 管理。

常见例子：

| 服务 | 示例地址 | 说明 |
| --- | --- | --- |
| 模型服务 | `https://api.example.com/v1` | 在 `.env` / `.env.docker` 配置 |
| 宿主机模型服务 | `http://host.docker.internal:8001/v1` | Docker 容器访问宿主机服务 |
| Teable | `http://host.docker.internal:13000` | 可选外部表格服务 |
| 飞书开放平台 | `https://open.feishu.cn` | Channel SDK / lark-cli 使用 |

## 5. 端口排查

查看源码开发服务状态：

```bash
./scripts/dev/status_services.sh
```

查看 Docker 服务状态：

```bash
docker compose ps
```

Linux / macOS 查端口占用：

```bash
lsof -iTCP:8005 -sTCP:LISTEN
lsof -iTCP:7775 -sTCP:LISTEN
lsof -iTCP:65437 -sTCP:LISTEN
```

Windows PowerShell 查端口占用：

```powershell
netstat -ano | findstr :18005
netstat -ano | findstr :17775
```

常见冲突处理：

- `7775` 被占用：源码前端不会自动换端口，因为 Vite 使用 `--strictPort`。
- `8005` 被占用：修改 `NEWMAN_BACKEND_PORT`，并同步前端 `VITE_API_PROXY`。
- `65437` 被占用：修改 `NEWMAN_PG_PORT`，并确保后端 DSN 使用同一端口。
- Docker 的 `17775 / 18005` 被占用：设置 `NEWMAN_FRONTEND_PORT` / `NEWMAN_BACKEND_PORT` 后重新 `docker compose up -d`。
