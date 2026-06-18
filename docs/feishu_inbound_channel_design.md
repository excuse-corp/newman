# Feishu Inbound Channel Design

> 目标：让用户在飞书中给 Newman 发送消息，Newman 能在同一会话中处理并回复。本文只覆盖飞书 -> Newman 的入站通道，不覆盖 Newman 主动使用飞书文档、表格、任务等工具能力。

## 1. 结论

飞书入站通道优先使用官方 Python Channel SDK，而不是 `lark-cli event consume`，也不再建议单独维护 Node sidecar。

原因：

- Newman 后端本身就是 Python。
- 飞书已经提供 Python 版 Channel SDK，可以直接在 Newman 进程内建立长连接。
- 内网部署时只需要 Newman 主动出站访问飞书，不需要公网回调地址。
- 省掉 sidecar 之后，配置、状态、重载、日志和启停都能统一进 Newman。

推荐架构：

```text
Feishu App
  ↓ WebSocket long connection
Newman Backend (Python + Channel SDK)
  ↓ channel transport
session/runtime/audit
  ↓ reply/send via Channel SDK
Feishu user
```

## 2. 当前实现状态

当前仓库已经落地飞书入站主链路：

- [backend/channels/feishu_transport.py](/root/newman/backend/channels/feishu_transport.py:54)：通过官方 Python Channel SDK 建立长连接、接收事件、做去重和回复。
- [backend/channels/service.py](/root/newman/backend/channels/service.py:26)：把飞书消息映射到 Newman 会话并调用 runtime。
- [backend/api/routes/channels.py](/root/newman/backend/api/routes/channels.py:1)：提供状态、验证和测试接口。
- 配置入口是 `channels.feishu.*`，敏感项优先放 `.env` / `.env.docker`。

会话策略已经按天聚合：

```text
feishu:{app_id}:{chat_id}:{sender_open_id}:{YYYY-MM-DD}
```

当天第一次收到某个飞书会话/用户的消息时创建 Newman 会话；后续当天消息复用该会话。会话标题格式：

```text
飞书 · {首条消息摘要} · {YYYY-MM-DD}
```

默认 `default_turn_approval_mode` 为 `auto_allow`，用于避免飞书入站任务卡在 Newman 页面审批上。

## 3. 范围

### 3.1 本期包含

- 飞书私聊机器人发消息给 Newman
- 飞书群聊中 `@` 机器人发消息给 Newman
- Newman 基于 `app_id` / `chat_id` / `sender_id` / 日期建立和复用 session
- Newman 生成最终回复后，直接回复到飞书原消息或原会话
- 内网部署下的长连接接入、状态管理、去重、限速和失败重试

### 3.2 本期不包含

- Newman 主动使用飞书文档、表格、任务等能力
- 飞书文档评论、卡片交互、审批、会议、妙记等其他入口
- 图片、文件、语音等非文本消息处理
- 多租户
- 流式消息卡片和复杂交互 UI

第一版先把“文本对话跑通”。

## 4. 目标架构

### 4.1 组件划分

```text
backend/channels/
  inbound_models.py
  inbound_service.py
  feishu_transport.py
  feishu_dedup.py

backend/api/routes/
  channels.py
```

职责划分：

- `FeishuChannelTransport`
  - 在 Newman 进程内启动官方 Python Channel SDK
  - 建立 WebSocket 长连接
  - 订阅并接收 `im.message.receive_v1`
  - 过滤群聊非 `@` 消息
  - 对飞书原始事件做轻量归一化
  - 做事件去重
  - 调 Newman runtime
  - 按返回结果调用飞书 reply/send

- `Newman Backend`
  - 负责 session 映射
  - 调 runtime 执行消息轮次
  - 记录 audit / sessions / errors
  - 对外暴露统一状态

### 4.2 为什么不再走 sidecar

不再建议 `Node sidecar -> HTTP -> Python backend`，原因：

- 多一个进程，多一层配置和状态面
- 需要内部鉴权和桥接接口
- reload 和排障会变复杂
- Newman 当前没有必须通过独立 sidecar 才能解决的约束

## 5. 消息流

```text
1. 用户给飞书机器人发消息
2. Python Channel SDK 收到 `im.message.receive_v1`
3. transport 过滤不支持的消息和非 @ 群消息
4. transport 归一化为 ChannelInboundMessage
5. Newman 查找或创建 session
6. Newman 调 runtime.handle_message(...)
7. Newman 返回 final response
8. transport 调飞书 reply/send
9. 用户在飞书看到回复
```

## 6. 统一消息模型

建议新增：

```python
class ChannelInboundMessage(BaseModel):
    platform: str                  # "feishu"
    transport: str                 # "channel_sdk"
    tenant_key: str | None = None
    app_id: str | None = None
    event_id: str
    message_id: str
    chat_id: str
    thread_id: str | None = None
    sender_open_id: str
    sender_union_id: str | None = None
    chat_type: str | None = None   # p2p / group / topic
    is_mention: bool = False
    text: str
    raw: dict
```

回复模型：

```python
class ChannelOutboundReply(BaseModel):
    mode: str = "reply"            # reply / send
    message_id: str | None = None
    chat_id: str | None = None
    text: str
```

## 7. Newman 侧实现

### 7.1 Session 映射

飞书入站当前使用按天聚合的 key：

```text
feishu:{app_id}:{chat_id}:{sender_open_id}:{YYYY-MM-DD}
```

这样可以：

- 不同飞书应用混用 session
- 同一天同一个飞书会话复用上下文
- 第二天自然新建 Newman 会话，避免长期会话膨胀

### 7.2 处理策略

第一版只处理：

- `message_type == text`
- 私聊消息
- 群聊中明确 `@` 机器人的文本消息

第一版忽略：

- 图片
- 文件
- 表情事件
- doc comment
- card action

### 7.3 失败策略

Newman 内部处理失败时，返回统一兜底文案：

```text
我收到消息了，但这次处理失败。请稍后重试。
```

不要把 traceback 或内部错误直接回给飞书用户。

## 8. Transport 设计

### 8.1 运行方式

transport 作为 Newman 后端的一部分启动和停止，由 `ChannelService` 或独立 manager 管理。

### 8.2 transport 需要做的事

1. 读取配置：
   - `FEISHU_APP_ID`
   - `FEISHU_APP_SECRET`
   - `FEISHU_REQUIRE_MENTION`
   - `FEISHU_ALLOWED_CHAT_IDS`
2. 启动 Python Channel SDK 并建立 WebSocket 长连接
3. 订阅 `im.message.receive_v1`
4. 对每条事件提取：
   - `event_id`
   - `message_id`
   - `chat_id`
   - `thread_id`
   - `sender_open_id`
   - 文本内容
   - 是否 `@` 机器人
5. 用 `event_id` 做去重
6. 直接调用 Newman runtime
7. 根据返回调用飞书 `reply/send`
8. 对 `429`、网络抖动、飞书瞬时错误做指数退避

### 8.3 transport 不负责

- Newman session 业务逻辑
- Newman runtime 调度策略
- 飞书工具调用
- 长文本总结或业务生成

它只做“连接层”和“消息搬运层”。

### 8.4 自检与联调接口

Newman 后端应提供三类自检接口，方便新部署用户自助接入：

- `GET /api/channels/feishu/setup/status`
  - 返回当前配置是否完整
  - 返回 transport 是否已启动、是否已连接、最近一次事件时间和最近错误
- `POST /api/channels/feishu/setup/validate`
  - 触发一次飞书连接探测
  - 用于确认 `app_id/app_secret` 和网络链路可用
- `POST /api/channels/feishu/setup/test`
  - 在用户从飞书侧手动发送测试消息后等待事件到达
  - 用于确认“飞书 -> Newman -> 回复”闭环

## 9. 配置设计

建议扩展配置：

```yaml
channels:
  feishu:
    enabled: true
    transport: "channel_sdk"
    app_id: null
    app_secret: null
    domain: "https://open.feishu.cn"
    default_turn_approval_mode: "auto_allow"
    require_mention_in_group: true
    allowed_chat_ids: []
    allowed_user_open_ids: []
    reply_timeout_seconds: 20
    dedup_ttl_seconds: 600
```

说明：

- `transport`: 区分 `webhook` 和 `channel_sdk`
- `default_turn_approval_mode`: 飞书入站轮次的审批模式，默认 `auto_allow`
- `require_mention_in_group`: 默认打开，避免机器人在群里乱响应
- `allowed_chat_ids` / `allowed_user_open_ids`: 可选白名单
- `reply_timeout_seconds`: Newman 内部处理超时后返回兜底文案

敏感值优先放 `.env`：

```dotenv
NEWMAN_CHANNELS__FEISHU__APP_ID=cli_xxx
NEWMAN_CHANNELS__FEISHU__APP_SECRET=xxx
NEWMAN_CHANNELS__FEISHU__ALLOWED_CHAT_IDS=oc_xxx,oc_yyy
NEWMAN_CHANNELS__FEISHU__ALLOWED_USER_OPEN_IDS=ou_xxx,ou_yyy
```

项目级 `newman.yaml` 保留非敏感项：

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

### 9.1 依赖

后端需要新增 Python 依赖：

- `lark-channel-sdk`

不要为飞书入站再额外引入 Node 运行时依赖。

## 10. 数据与状态

建议新增：

```text
backend_data/channels/feishu_channel/
  dedup.jsonl
  transport_state.json
```

`dedup.jsonl` 记录近期 `event_id` / `message_id`，避免飞书重投或 Newman 重启后重复处理。

状态建议暴露到：

```text
GET /api/channels/status
```

新增字段：

- `transport`
- `connected`
- `last_event_at`
- `last_error`
- `dedup_cache_size`

## 11. 启停与重载

不需要单独的 sidecar 脚本，但需要让 Newman 自己管理 transport 生命周期。

要求：

- backend 启动后自动初始化 Feishu transport
- `POST /api/config/reload` 后重建 transport
- backend 停止时优雅关闭 transport
- transport 状态写入日志和 `status`

需要同步更新：

- [backend/api/routes/config.py](/root/newman/backend/api/routes/config.py:89)
- [scripts/dev/start_services.sh](/root/newman/scripts/dev/start_services.sh:1)
- [scripts/dev/stop_services.sh](/root/newman/scripts/dev/stop_services.sh:1)
- [scripts/dev/status_services.sh](/root/newman/scripts/dev/status_services.sh:1)

## 12. 面向新部署用户的自助接入优化

如果目标是“以后任何新部署 Newman 的用户，都可以靠配置或一个引导完成飞书打通”，需要补三层能力。

新用户可以直接先看 [飞书接入配置清单](./feishu_setup.md)，再看本设计文档里的状态接口和实现细节。

### 12.1 配置层优化

对用户只暴露最小配置面：

- `channels.feishu.enabled`
- `channels.feishu.transport`
- `channels.feishu.domain`
- `channels.feishu.require_mention_in_group`
- `channels.feishu.allowed_chat_ids`
- `channels.feishu.allowed_user_open_ids`
- `channels.feishu.reply_timeout_seconds`
- `channels.feishu.dedup_ttl_seconds`

敏感值只保留 2 个：

- `app_id`
- `app_secret`

这两项优先走 `.env`，便于部署且不易误提交。

### 12.2 引导层优化

建议新增“飞书接入引导”，优先做 Web 配置页引导。

Newman 已有配置读写和 reload 接口：

- [backend/api/routes/config.py](/root/newman/backend/api/routes/config.py:31)

引导最少应覆盖：

1. 说明飞书开放平台需要做什么
2. 收集 `app_id` / `app_secret`
3. 写入 `newman.yaml` 和 `.env`
4. 触发 `POST /api/config/reload`
5. 做连通性与权限检查
6. 给出“下一步去飞书里发一条测试消息”的明确提示

### 12.3 验证层优化

建议新增：

```text
GET /api/channels/feishu/setup/status
POST /api/channels/feishu/setup/validate
POST /api/channels/feishu/setup/test
```

建议职责：

- `setup/status`
  - 当前是否配置了 `app_id` / `app_secret`
  - transport 是否已启动
  - transport 是否已连接飞书
  - 最近一条事件时间
  - 最近错误

- `setup/validate`
  - 调飞书 bot info / auth 相关接口
  - 检查基本凭证是否可用
  - 检查长连接是否成功建立
  - 检查必需权限是否缺失

- `setup/test`
  - 让用户在飞书给机器人发送 `ping`
  - 服务侧等待一小段时间确认是否收到事件
  - 返回“已收到测试消息”或“未收到，请检查事件订阅/安装范围”

### 12.4 用户可见状态文案

至少区分：

- `not_configured`
- `configured_not_reloaded`
- `transport_stopped`
- `connecting`
- `connected`
- `auth_failed`
- `permission_missing`
- `event_not_received`

### 12.5 为什么需要这些优化

否则每个新用户都会卡在：

- 不知道配置写到 `newman.yaml` 还是 `.env`
- 不知道改完配置后还要 reload
- 不知道问题出在飞书开放平台还是 Newman 本地
- 不知道自己到底有没有收到事件

## 13. 推荐的自助接入流程

### 13.1 用户视角流程

1. 打开 Newman 的“渠道接入 / 飞书”页面
2. 按页面提示去飞书开放平台创建应用
3. 勾选“机器人能力 + 长连接 + `im.message.receive_v1`”
4. 把 `app_id` / `app_secret` 粘回 Newman
5. 点击“保存并重载”
6. 点击“验证连接”
7. 在飞书里给机器人发测试消息
8. Newman 页面显示“已接入”

### 13.2 系统视角动作

1. 写入 `newman.yaml`
2. 写入 `.env`
3. 调 `POST /api/config/reload`
4. 轮询 `GET /api/channels/status`
5. 调 `setup/validate`
6. 返回明确结果和下一步提示

## 14. 实施顺序

### M1: 跑通最小闭环

- 新增 Python transport 骨架
- 引入 `lark-channel-sdk`
- 建立长连接
- 只接收 `im.message.receive_v1`
- 只处理文本消息
- 建立 session 映射
- 回复纯文本

验收：

- 私聊机器人发送文本，Newman 能回复
- 群里 `@` 机器人发送文本，Newman 能回复
- 重复事件不会重复回消息

### M2: 稳定性

- 去重持久化
- 状态接口
- reload 生命周期管理
- 超时控制
- 错误分类
- 频控重试

### M3: 扩展入口

- thread/topic 更精细路由
- doc comment
- card action
- 流式回复或分段回复

## 15. 你需要准备什么

### 15.1 飞书侧

你需要在飞书开放平台准备一个自建应用，并完成这些动作：

1. 创建应用
2. 开启机器人能力
3. 选择长连接接收事件
4. 订阅 `im.message.receive_v1`
5. 申请消息接收和消息发送相关权限
6. 把应用发布并安装到实际要测试的租户
7. 把机器人加入测试群，或者准备一个和机器人的私聊

如果你计划先做最小闭环，这一步只需要围绕“收文本消息、回文本消息”申请权限，不要一开始申请一堆无关权限。

### 15.2 Newman 部署侧

你需要准备：

1. 一台能出站访问飞书公网的机器
2. Newman backend 正常运行
3. Python 环境可安装 `lark-channel-sdk`
4. 一组配置值：
   - `FEISHU_APP_ID`
   - `FEISHU_APP_SECRET`
5. 确认防火墙或代理不会阻断 WebSocket 长连接

不需要准备：

- 公网 IP
- 公网域名
- 内网穿透
- Node.js sidecar

## 16. 你现在该做什么

按顺序做：

1. 在飞书开放平台创建或确认已有自建应用。
2. 给这个应用开机器人能力。
3. 在事件订阅里切到“长连接”模式。
4. 订阅 `im.message.receive_v1`。
5. 申请并通过消息接收、消息发送所需权限。
6. 把应用安装到你的租户。
7. 准备好：
   - `app_id`
   - `app_secret`
   - 一个测试私聊或测试群
8. 确认 Newman 所在机器能出站访问飞书。

你把这几项准备好后，Newman 这边就可以开始做 M1 实现。

## 17. 风险和约束

- 飞书事件和消息 API 都有频控，回复侧必须按 `429` 和错误码重试。
- 群聊默认必须要求 `@` 机器人，否则噪音太大。
- 会话 key 设计错了会导致不同群、不同话题、不同应用串 session。
- backend 必须暴露独立状态检查，否则排障会很慢。
- 第一版不要碰图片/文件/卡片，先把文本对话跑通。

## 18. 参考

- 飞书 Agent 集成 Channel 说明：<https://open.feishu.cn/document/mcp_open_tools/integrating-agents-with-feishu/integrate-feishu-channel>
- Python Channel SDK：<https://github.com/larksuite/channel-sdk-python/tree/main>
- 使用长连接接收事件：<https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case?lang=zh-CN>
- 接收消息事件 `im.message.receive_v1`：<https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/events/receive>
- 发送消息 API：<https://open.feishu.cn/document/server-docs/im-v1/message/create?lang=zh-CN>
- 飞书 API 频控：<https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control?lang=zh-CN>
