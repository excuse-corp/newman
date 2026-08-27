# Newman Agent Notes

## 项目定位

Newman 是本地优先的 AI Agent runtime 和 workbench。核心由 FastAPI 后端、React/Vite 前端、workspace-level skills、plugins、sandbox、subagents、自进化和本地运行数据组成。

## 主要目录

- `backend/`: FastAPI API、运行时循环、工具系统、MCP、sandbox、memory、evolution、plugin/skill runtime。
- `frontend/`: React 18 + Vite + TypeScript 工作台。
- `skills/`: 工作区级 skill，通常包含 `SKILL.md`、脚本、模板和参考资料。
- `plugins/`: 插件目录；默认忽略大部分插件，仅保留允许提交的插件路径。
- `backend_data/`: 本地运行期数据，包含 sessions、memory、audit、evolution、knowledge、scheduler 等，默认不提交。
- `docs/`: API、部署和机制说明。
- `scripts/dev/`: 本地服务启动、停止、重启和状态检查脚本。

## 常用命令

- 源码启动整套服务: `./scripts/dev/start_services.sh`
- 查看服务状态: `./scripts/dev/status_services.sh`
- 重启服务: `./scripts/dev/restart_services.sh`
- 停止服务: `./scripts/dev/stop_services.sh`
- 前端构建检查: `cd frontend && npm run build`
- Docker 启动: `docker compose up -d --build`
- Docker 日志: `docker compose logs -f backend` 或 `docker compose logs -f frontend`

## 开发约定

- 后端需要 Python 3.11+，依赖定义在 `backend/pyproject.toml`，推荐通过 `environment.yml` 创建 `newman` conda 环境。
- 前端依赖在 `frontend/package.json`，构建脚本会先跑 TypeScript build 再跑 Vite build。
- 优先复用现有模块边界和本地 helper，不要为了小改动引入新框架或大范围重构。
- 修改 runtime、tool、sandbox、plugin、skill loader 等共享路径时，要检查调用链和配置兼容性。
- 对用户已有改动保持克制：先读当前文件状态，避免覆盖未提交工作。

## Git 和数据边界

- 不提交 `.env`、`.env.docker`、`backend_data/`、`outputs/`、`frontend/node_modules/`、`frontend/dist/`、`ref/`、`test_runtimespace/` 等本地或生成内容。
- 本文件是本地 agent 备忘录，已加入 `.git/info/exclude`，不要提交到仓库。
- 除非用户明确要求，不要运行 `git add`、`git commit`、`git reset --hard` 或覆盖式 checkout。

## 快速定位建议

- 找文件优先用 `rg --files`，找文本优先用 `rg`。
- 后端入口通常从 `backend/api/app.py`、`backend/runtime/run_loop.py`、`backend/tools/`、`backend/config/` 开始查。
- 前端入口通常从 `frontend/src/App.tsx`、`frontend/src/RootPage.tsx` 和 `frontend/src/pages/` 开始查。
- 配置行为优先参考 `newman.yaml`、`backend/config/defaults.yaml`、`backend/config/schema.py` 和 `backend/config/loader.py`。
