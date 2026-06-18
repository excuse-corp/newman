# Feishu Setup Guide

本文是新部署 Newman 时打通飞书的最小操作清单。飞书接入分两条链路：

- 飞书 -> Newman：用户在飞书里给机器人发消息，Newman 接收并回复。使用官方 Python Channel SDK。
- Newman -> 飞书：用户在 Newman 里要求操作飞书文档、消息、表格等。使用 `feishu-cli` 插件和系统 `lark-cli`。

## 1. 飞书开放平台准备

在飞书开放平台创建一个自建应用，并完成：

1. 启用机器人能力。
2. 事件订阅选择“使用长连接接收事件”。
3. 订阅 `im.message.receive_v1`。
4. 按开放平台提示开通接收消息、发送消息所需权限。
5. 发布或安装应用到目标企业、测试企业或可见范围。
6. 记录应用凭证：
   - `app_id`
   - `app_secret`

Newman 在内网也可以使用这条链路，因为后端是主动向飞书建立出站长连接，不需要公网回调地址。

## 2. 配置 Newman

`newman.yaml` 保留非敏感配置：

```yaml
channels:
  feishu:
    enabled: true
    transport: "channel_sdk"
    domain: "https://open.feishu.cn"
    default_turn_approval_mode: "auto_allow"
    require_mention_in_group: true
    allowed_chat_ids: []
    allowed_user_open_ids: []
    reply_timeout_seconds: 20
    dedup_ttl_seconds: 600
```

`.env` 或 `.env.docker` 填应用凭证：

```dotenv
NEWMAN_CHANNELS__FEISHU__APP_ID=cli_xxx
NEWMAN_CHANNELS__FEISHU__APP_SECRET=xxx
```

可选白名单使用逗号分隔：

```dotenv
NEWMAN_CHANNELS__FEISHU__ALLOWED_CHAT_IDS=oc_xxx,oc_yyy
NEWMAN_CHANNELS__FEISHU__ALLOWED_USER_OPEN_IDS=ou_xxx,ou_yyy
```

群聊默认需要 `@` 机器人才响应；如果要让群聊里所有消息都触发 Newman，可以配置：

```dotenv
NEWMAN_CHANNELS__FEISHU__REQUIRE_MENTION_IN_GROUP=false
```

## 3. 启动与验证

本地开发：

```bash
./scripts/dev/restart_services.sh
```

Docker：

```bash
docker compose up -d --build
```

检查 Newman 是否读到飞书配置：

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

执行后在飞书里给机器人发一条消息，接口会等待并返回是否收到事件。

## 4. Newman 主动操作飞书

如果还需要 Newman 操作飞书文档、表格、消息、任务等，安装并登录官方 CLI：

```bash
npx @larksuite/cli@latest install
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status
```

Docker 部署会挂载宿主机：

- `~/.lark-cli`
- `~/.local/share/lark-cli`

确认插件状态：

```bash
curl http://127.0.0.1:8005/api/plugins
```

`feishu-cli` 插件的 `preflight.ok=true` 表示 Newman 能找到 `lark-cli` 并读取登录态。

## 5. 常见问题

- `missing_credentials`：`.env` / `.env.docker` 没有填 `NEWMAN_CHANNELS__FEISHU__APP_ID` 或 `NEWMAN_CHANNELS__FEISHU__APP_SECRET`。
- `missing_dependency`：当前 Python 环境缺少 `lark-channel-sdk`。
- `not_started`：配置已读取，但后端服务还没重启或 transport 没有启动。
- `connected=false`：优先检查应用凭证、飞书应用是否已发布/安装、内网是否允许出站访问飞书。
- 飞书端发消息无反应：检查是否订阅了 `im.message.receive_v1`，群聊里是否 `@` 了机器人，以及应用是否在对应群/用户可见范围内。
- Newman 页面没有看到新消息：先刷新页面确认；入站链路会写入 Newman 会话，但前端实时展示依赖 channel event 流。

飞书 OpenAPI 和消息发送能力有平台侧频控。Newman 不在本地配置中写死飞书配额，运行时应关注飞书返回的 `429`、权限错误和开放平台控制台的最新限制。
