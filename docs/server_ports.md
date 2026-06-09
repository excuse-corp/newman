# 服务器端口清单

> 更新日期: 2026-06-01

## 对外服务（绑定 0.0.0.0）

| 端口 | 进程 | 项目 | 说明 |
|------|------|------|------|
| 22 | sshd | 系统 | SSH 远程登录 |
| 80 | nginx | 系统 | HTTP 默认站点（默认配置，未做反代） |
| 5943 | proxyserver | EDR | 安全代理服务 |
| 5999 | AntiVirusServic | EDR | 杀毒服务 |
| 7530 | python http.server | Envoys | Web 静态文件服务 (`/root/Envoys/apps/web`) |
| 7775 | vite (node) | **Newman** | 前端开发服务器（脚本管理，`--strictPort`） |
| 7776 | vite (node) | Fileman | 前端开发服务器 (`/root/fileman/frontend`) |
| 8005 | uvicorn | **Newman** | 后端 API (`backend.main:app`) |
| 9510 | uvicorn | Envoys | 后端 API (`/root/Envoys/apps/api`) |
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
| 3337 | ESControl / edr-watch | EDR 安全监控 |
| 4444 | geckodriver | Firefox WebDriver（自动化测试） |
| 5432 | postgres | PostgreSQL（系统级） |
| 6379 | redis-server | Redis 缓存 |
| 33223 | node | MCP Server |
| 33539 | containerd | Docker 容器运行时 |
| 42217 | node | MCP Server |
| 43431 | node | MCP Server |
| 49932 | node | MCP Server |
| 61630 | node | MCP Server |
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
| Envoys | 7530 | 9510 | - |
| Teable | 13000 | - | PostgreSQL 15432 (Docker) |
