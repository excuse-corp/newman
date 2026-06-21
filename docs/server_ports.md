# 服务器端口清单

> 更新日期: 2026-06-20

## 对外服务（绑定 0.0.0.0）

| 端口 | 进程 | 项目 | 说明 |
|------|------|------|------|
| 22 | sshd | 系统 | SSH 远程登录 |
| 80 | nginx | 系统 | HTTP 默认站点（反代 soul-distillery） |
| 5521 | nginx | Teable | Teable 反代（→ 127.0.0.1:13000） |
| 5943 | proxyserver | EDR | 安全代理服务 |
| 5999 | AntiVirusServic | EDR | 杀毒服务 |
| 7775 | vite (node) | **Newman** | 前端开发服务器（`--strictPort`） |
| 7776 | vite (node) | Fileman | 前端开发服务器 (`/root/fileman/frontend`) |
| 8005 | uvicorn | **Newman** | 后端 API (`backend.main:app`) |
| 8080 | python | Soul Distillery | 后端 API (`main.py`，conda env: souldistill) |
| 11117 | openclaw-gateway | OpenClaw | Gateway 服务 |
| 13000 | docker-proxy -> teable:3000 | Teable | 表格应用 Web |
| 15432 | docker-proxy -> postgres:5432 | Teable | Teable 数据库 |
| 18080 | uvicorn | Fileman | 后端 API (`/root/fileman/backend`) |
| 35053 | BT-Panel | 宝塔 | 宝塔面板管理 |

## 仅本地监听（127.0.0.1）

| 端口 | 进程 | 说明 |
|------|------|------|
| 53 | systemd-resolve | DNS 解析 |
| 631 | cupsd | 打印服务 |
| 3306 | mysqld | MySQL 数据库 |
| 33060 | mysqld | MySQL X Protocol |
| 3337 | edr-watch | EDR 安全监控 |
| 5432 | postgres | PostgreSQL（系统级） |
| 6379 | redis-server | Redis 缓存 |
| 11119 | openclaw-gateway | OpenClaw Gateway 内部端口 |
| 11120 | openclaw-gateway | OpenClaw Gateway 内部端口 |
| 18080 | uvicorn | Fileman 后端 API |
| 34355 | node | MCP Server |
| 34919 | node | MCP Server |
| 38421 | containerd | Docker 容器运行时 |
| 44180 | node | MCP Server |
| 50301 | node | MCP Server |
| 61043 | node | MCP Server |
| 65437 | postgres | Newman 专用 PostgreSQL |

## Docker 容器

| 容器名 | 镜像 | 端口映射 | 状态 |
|--------|------|----------|------|
| teable-teable-1 | ghcr.io/teableio/teable:latest | 0.0.0.0:13000 -> 3000 | Up |
| teable-teable-db-1 | postgres:15.4 | 0.0.0.0:15432 -> 5432 | Up (healthy) |
| teable-teable-cache-1 | redis:7.2.4 | 6379 (内部) | Up (healthy) |

## 项目服务汇总

| 项目 | 前端端口 | 后端端口 | 数据库 |
|------|----------|----------|--------|
| Newman | 7775 | 8005 | PostgreSQL 65437 / Redis 6379 |
| Fileman | 7776 | 18080 | - |
| Soul Distillery | 80 (nginx) | 8080 | - |
| Teable | 13000 / 5521 (nginx) | - | PostgreSQL 15432 (Docker) |
| OpenClaw | - | 11117 | - |
