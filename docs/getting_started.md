# Newman 新用户部署与接入手册

本文是 Newman 的新用户默认入口，面向第一次部署 Newman 的用户，目标是从空机器或新目录启动到“能打开工作台、能发起对话、能接入飞书”。

如果你是从仓库首页进入，建议先按本文顺序完成部署、模型配置和基础验证，再继续阅读 API 或机制文档。

Newman 有两种部署方式：

- Docker 部署：推荐给新机器、稳定运行、少改代码的场景。
- 本地开发部署：推荐给需要改代码、联调后端/前端、查看本地日志的场景。

## 1. 部署前准备

### 1.1 基础依赖

Docker 部署需要：

- Docker
- Docker Compose
- 能访问模型服务 endpoint

本地开发部署需要：

- Conda
- Node.js 20
- Python 3.11
- PostgreSQL，或直接使用项目脚本启动本地 PostgreSQL

### 1.2 需要提前准备的配置

至少准备一个可用的 OpenAI-compatible 模型服务：

- `NEWMAN_MODELS_PRIMARY_ENDPOINT`
- `NEWMAN_MODELS_PRIMARY_API_KEY`
- `NEWMAN_MODELS_PRIMARY_MODEL`
- `NEWMAN_MODELS_MULTIMODAL_ENDPOINT`
- `NEWMAN_MODELS_MULTIMODAL_API_KEY`
- `NEWMAN_MODELS_MULTIMODAL_MODEL`

如果要使用飞书，还需要：

- 飞书自建应用的 `app_id`
- 飞书自建应用的 `app_secret`
- 官方 `lark-cli` 安装和授权

## 2. Docker 部署

Docker 是新用户优先推荐路径。

### 2.1 准备环境变量

在项目根目录执行：

```bash
cp .env.docker.example .env.docker
```

编辑 `.env.docker`，至少填入模型配置：

```dotenv
NEWMAN_MODELS_PRIMARY_TYPE=openai_compatible
NEWMAN_MODELS_PRIMARY_MODEL=gpt-4.1-mini
NEWMAN_MODELS_PRIMARY_ENDPOINT=https://api.openai.com/v1
NEWMAN_MODELS_PRIMARY_API_KEY=your_api_key_here

NEWMAN_MODELS_MULTIMODAL_TYPE=openai_compatible
NEWMAN_MODELS_MULTIMODAL_MODEL=gpt-4.1
NEWMAN_MODELS_MULTIMODAL_ENDPOINT=https://api.openai.com/v1
NEWMAN_MODELS_MULTIMODAL_API_KEY=your_api_key_here
```

如果 endpoint 在宿主机本地，容器内不要写 `127.0.0.1`，改用：

```dotenv
NEWMAN_MODELS_PRIMARY_ENDPOINT=http://host.docker.internal:8001/v1
```

### 2.2 启动

```bash
docker compose build
docker compose up -d
```

默认地址：

- 前端工作台：`http://127.0.0.1:17775`
- 后端 API：`http://127.0.0.1:18005`
- 后端 OpenAPI 文档：`http://127.0.0.1:18005/docs`

### 2.3 常用命令

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
docker compose down
docker compose up -d --build
```

如果需要改端口：

```bash
NEWMAN_FRONTEND_PORT=7775 NEWMAN_BACKEND_PORT=8005 docker compose up -d --build
```

## 3. 本地开发部署

### 3.1 创建环境

```bash
conda env create -f environment.yml
conda activate newman
```

### 3.2 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 3.3 准备环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入模型配置：

```dotenv
NEWMAN_MODELS_PRIMARY_TYPE=openai_compatible
NEWMAN_MODELS_PRIMARY_MODEL=gpt-4.1-mini
NEWMAN_MODELS_PRIMARY_ENDPOINT=https://api.openai.com/v1
NEWMAN_MODELS_PRIMARY_API_KEY=your_api_key_here

NEWMAN_MODELS_MULTIMODAL_TYPE=openai_compatible
NEWMAN_MODELS_MULTIMODAL_MODEL=gpt-4.1
NEWMAN_MODELS_MULTIMODAL_ENDPOINT=https://api.openai.com/v1
NEWMAN_MODELS_MULTIMODAL_API_KEY=your_api_key_here
```

### 3.4 启动

```bash
./scripts/dev/start_services.sh
```

默认地址：

- 前端工作台：`http://127.0.0.1:7775`
- 后端 API：`http://127.0.0.1:8005`
- 后端 OpenAPI 文档：`http://127.0.0.1:8005/docs`
- Newman PostgreSQL：`127.0.0.1:65437`

常用脚本：

```bash
./scripts/dev/status_services.sh
./scripts/dev/restart_services.sh
./scripts/dev/stop_services.sh
```

这些脚本应在宿主机 shell 中运行，不要放在 PID namespace 沙箱里控制主机服务。

## 4. 配置规则

Newman 配置优先级从高到低：

1. 环境变量
2. `~/.newman/config.yaml`
3. 项目根目录 `newman.yaml`
4. `backend/config/defaults.yaml`

推荐分工：

- `.env` / `.env.docker`：模型密钥、飞书密钥、endpoint、token 等敏感或易变配置。
- `newman.yaml`：项目部署配置，例如端口、路径、权限、channel 开关。
- `backend/config/defaults.yaml`：代码内置默认值，不按环境直接修改。

配置修改后：

- Docker 部署通常执行 `docker compose up -d --build` 或重启 backend。
- 本地开发可以执行 `./scripts/dev/restart_services.sh`。
- 也可以在前端配置页或 API 中调用配置 reload，但监听端口这类变化仍需要重启进程。

## 5. 基础验证

Docker 默认后端端口是 `18005`，本地开发默认后端端口是 `8005`。以下命令以本地开发端口为例；Docker 用户把端口替换为 `18005`。

### 5.1 后端健康检查

```bash
curl http://127.0.0.1:8005/healthz
```

预期结果包含：

```json
{
  "ok": true
}
```

### 5.2 运行目录检查

```bash
curl http://127.0.0.1:8005/readyz
```

确认返回里包含：

- `sessions_dir`
- `plugins_dir`
- `skills_dir`
- `channels_dir`

### 5.3 插件检查

```bash
curl http://127.0.0.1:8005/api/plugins
```

如果要用飞书出站能力，确认 `feishu-cli` 插件存在，并且 `preflight.ok=true`。

## 6. 飞书接入

飞书接入分两条链路：

- 飞书 -> Newman：用户在飞书里给机器人发消息，Newman 接收并回复。
- Newman -> 飞书：用户在 Newman 里要求操作飞书文档、表格、消息、任务等。

这两条链路可以分别配置；只需要飞书里和 Newman 对话时，先做“飞书 -> Newman”。需要 Newman 主动操作飞书资源时，再做“Newman -> 飞书”。

### 6.1 飞书 -> Newman

Newman 入站使用官方 Python Channel SDK。它是 Newman 主动向飞书建立长连接，所以内网部署不需要公网 webhook 地址。

在飞书开放平台创建自建应用，并完成：

1. 启用机器人能力。
2. 事件订阅选择“使用长连接接收事件”。
3. 订阅 `im.message.receive_v1`。
4. 开通接收消息、发送消息所需权限。
5. 发布或安装应用到目标企业、测试企业或可见范围。
6. 记录 `app_id` 和 `app_secret`。

`newman.yaml` / `docker/newman.yaml` 默认已经使用：

```yaml
channels:
  feishu:
    enabled: true
    transport: "channel_sdk"
    domain: "https://open.feishu.cn"
    default_turn_approval_mode: "auto_allow"
    require_mention_in_group: true
```

在 `.env` 或 `.env.docker` 填入：

```dotenv
NEWMAN_CHANNELS__FEISHU__APP_ID=cli_xxx
NEWMAN_CHANNELS__FEISHU__APP_SECRET=xxx
```

可选白名单：

```dotenv
NEWMAN_CHANNELS__FEISHU__ALLOWED_CHAT_IDS=oc_xxx,oc_yyy
NEWMAN_CHANNELS__FEISHU__ALLOWED_USER_OPEN_IDS=ou_xxx,ou_yyy
```

群聊默认需要 `@` 机器人才响应。如果要让群里所有消息都触发 Newman：

```dotenv
NEWMAN_CHANNELS__FEISHU__REQUIRE_MENTION_IN_GROUP=false
```

重启后检查状态：

```bash
curl http://127.0.0.1:8005/api/channels/feishu/setup/status
```

关键字段：

- `ok=true`：飞书入站链路可用。
- `status.app_configured=true`：已读取 `app_id` / `app_secret`。
- `status.dependency_available=true`：已安装 `lark-channel-sdk`。
- `status.connected=true`：SDK 长连接已连接。

主动验证连接：

```bash
curl -X POST http://127.0.0.1:8005/api/channels/feishu/setup/validate
```

端到端测试：

```bash
curl -X POST http://127.0.0.1:8005/api/channels/feishu/setup/test
```

执行后，在飞书里给机器人发一条消息。接口会等待并返回是否收到事件。

### 6.2 Newman -> 飞书

Newman 主动操作飞书资源通过 `feishu-cli` 插件调用系统 `lark-cli`。

安装并授权官方 CLI：

```bash
npx @larksuite/cli@latest install
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status
```

Docker 部署时，Compose 会挂载宿主机：

- `~/.lark-cli`
- `~/.local/share/lark-cli`

所以通常在宿主机完成 `lark-cli` 登录即可。

如果希望 Newman 主动发 IM 时默认发给固定用户，可以配置：

```dotenv
NEWMAN_LARK_DEFAULT_IM_USER_ID=ou_xxx
NEWMAN_LARK_DEFAULT_IM_IDENTITY=bot
```

规则：

- `NEWMAN_LARK_DEFAULT_IM_USER_ID` 只在 `lark-cli im +messages-send` 没有显式传 `--chat-id` 或 `--user-id` 时生效。
- `NEWMAN_LARK_DEFAULT_IM_IDENTITY` 只在没有显式传 `--as` 时生效。
- 显式传入的目标和身份始终优先。
- `NEWMAN_LARK_DEFAULT_IM_IDENTITY` 只接受 `bot` 或 `user`。

检查插件：

```bash
curl http://127.0.0.1:8005/api/plugins
```

确认：

- `feishu-cli` 插件存在。
- 插件 preflight 能找到 `lark-cli`。
- 插件 preflight 能读取 `~/.lark-cli` 登录态。

## 7. 新用户验收清单

部署完成后，按顺序确认：

- 前端能打开。
- `GET /healthz` 返回 `ok=true`。
- `GET /readyz` 返回运行目录。
- 新建对话能得到模型回复。
- `GET /api/plugins` 能看到已启用插件。
- 如果使用飞书入站，`GET /api/channels/feishu/setup/status` 返回 `ok=true`。
- 如果使用飞书出站，`lark-cli auth status` 显示 bot 或 user 身份可用。
- 在飞书给机器人发消息后，Newman 能创建或复用飞书会话并回复。

## 8. 常见问题

### 8.1 `/healthz` 访问失败

检查：

- 后端进程是否启动。
- 端口是否正确。Docker 默认 `18005`，本地开发默认 `8005`。
- `docker compose logs -f backend` 或 `backend_data/run/logs/backend.log` 中是否有启动错误。

### 8.2 前端能打开，但对话没有回复

检查：

- `.env` / `.env.docker` 中模型 endpoint、model、api key 是否正确。
- 后端日志中是否有模型服务连接错误。
- 模型服务是否兼容 OpenAI Chat Completions 接口。

### 8.3 飞书状态是 `missing_credentials`

`.env` / `.env.docker` 没有填：

```dotenv
NEWMAN_CHANNELS__FEISHU__APP_ID=
NEWMAN_CHANNELS__FEISHU__APP_SECRET=
```

填完后重启 backend 或执行配置 reload。

### 8.4 飞书状态是 `missing_dependency`

当前 Python 环境缺少 `lark-channel-sdk`。本项目后端依赖已经声明该包；如果是手工环境，重新安装后端依赖：

```bash
python -m pip install -e ./backend
```

### 8.5 飞书状态是 `connected=false`

检查：

- `app_id` / `app_secret` 是否来自同一个飞书自建应用。
- 应用是否已发布或安装到目标企业。
- 是否启用了机器人能力。
- 是否订阅了长连接事件 `im.message.receive_v1`。
- Newman 所在机器是否允许出站访问飞书开放平台。

### 8.6 飞书群里发消息无反应

默认群聊需要 `@` 机器人。可以选择：

- 在群里 `@` 机器人发送消息。
- 或配置 `NEWMAN_CHANNELS__FEISHU__REQUIRE_MENTION_IN_GROUP=false`。

还需要确认应用在对应群聊可见，并且没有被 `ALLOWED_CHAT_IDS` 或 `ALLOWED_USER_OPEN_IDS` 白名单拦截。

### 8.7 Newman 主动发飞书消息提示缺少目标或身份

检查：

```dotenv
NEWMAN_LARK_DEFAULT_IM_USER_ID=ou_xxx
NEWMAN_LARK_DEFAULT_IM_IDENTITY=bot
```

或者在任务中明确说明发送目标和使用 `bot` / `user` 身份。

### 8.8 `lark-cli auth status` 显示 user `needs_refresh`

如果 user 身份可用但 token 需要刷新，`lark-cli` 通常会在下一次 user API 调用时自动刷新。若刷新失败，重新执行：

```bash
lark-cli auth login --recommend
```

### 8.9 Docker 容器里找不到宿主机服务

容器内访问宿主机服务不要使用 `127.0.0.1`，应使用：

```text
host.docker.internal
```

例如：

```dotenv
NEWMAN_MODELS_PRIMARY_ENDPOINT=http://host.docker.internal:8001/v1
```

## 9. 日志位置

本地开发脚本日志：

- `backend_data/run/logs/backend.log`
- `backend_data/run/logs/frontend.log`
- `backend_data/run/logs/feishu_cli_channel.log`

Docker 日志：

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f postgres
```

运行期数据：

- `backend_data/sessions`：会话记录。
- `backend_data/memory`：记忆和 skill snapshot。
- `backend_data/audit`：审计日志。
- `backend_data/channels`：渠道状态和飞书 session 映射。
- `backend_data/evolution`：自进化记录。

## 10. 最小可用标准

一个新用户部署可以认为完成，当以下条件都满足：

1. 工作台能打开。
2. `/healthz` 返回 `ok=true`。
3. 新建对话能正常回复。
4. 配置文件和密钥只出现在 `.env` / `.env.docker`，没有写进代码。
5. 如果启用飞书，`/api/channels/feishu/setup/status` 能明确显示 ready 或给出具体失败原因。
6. 如果启用 Newman 主动操作飞书，`lark-cli auth status` 可用，`feishu-cli` 插件 preflight 通过。
