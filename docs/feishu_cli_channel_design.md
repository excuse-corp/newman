# Feishu CLI / Plugin Integration Design

> 目标：明确飞书入站和飞书能力调用的分工。飞书 -> Newman 的消息入口走官方 Channel SDK；Newman 主动操作飞书时走 `feishu-cli` 插件复用官方 `lark-cli` Agent Skills。

## 1. 结论

当前实现拆成两条链路：

- **Channel 入站链路**：飞书作为 Newman 的对话入口。Newman 后端使用官方 Python Channel SDK 建立长连接，接收 `im.message.receive_v1`，转换为 Newman session 消息，再通过 SDK 回复飞书。
- **Plugin Skills 链路**：飞书 CLI 作为 Newman 的外部能力。用户在 Newman 中要求创建文档、写表格、操作多维表格、建任务、发消息时，模型读取插件内官方 `lark-*` skills，并通过 `terminal` 调用系统里的 `lark-cli`。

在 Newman 内部，飞书入站不是 Skill；飞书能力调用也不需要先封装为固定 Newman tool。当前采用插件内 skills + terminal：

| 层级 | 职责 |
| --- | --- |
| Channel Transport | 负责长期接收飞书事件、幂等、session 映射、回复 |
| Plugin Skill | 负责告诉模型何时使用飞书、如何选择官方 `lark-*` skill |
| Terminal | 负责执行 `lark-cli ...` 命令 |
| Plugin | 负责打包官方 skills、权限声明、可写目录和运行前检查 |

旧的 `lark-cli event consume` 入站方案只保留为 legacy/dev-only，不作为新部署推荐方案。

## 2. 总体架构

```text
飞书用户消息
  ↓
Python Channel SDK
  ↓
FeishuChannelTransport
  ↓
ChannelService session mapping
  ↓
Newman Runtime
  ↓
Channel SDK reply/send
  ↓
飞书用户收到回复
```

Newman 主动操作飞书的插件链路：

```text
用户要求 Newman 使用飞书做任务
  ↓
Skill Router / plugin skill snapshot
  ↓
lark-* Agent Skill
  ↓
terminal 执行 lark-cli ...
  ↓
结构化结果：url / token / message_id / task_id
  ↓
Newman 回复用户
```

## 2.1 当前保留的插件 Skills

`feishu-cli` 插件只保留当前高价值 skills，避免 skill snapshot 过长：

- `lark-shared`
- `lark-im`
- `lark-doc`
- `lark-drive`
- `lark-sheets`
- `lark-base`
- `lark-task`
- `lark-whiteboard`

其中 `lark-shared` 负责认证、身份和权限说明；`lark-im` 已约束为先读 `lark-shared`，并在 user 身份调用前检查 `needs_refresh`。

## 2.2 运行环境要求

Newman 主动调用飞书 CLI 时，运行 Newman 后端的环境需要满足：

- 能在 `PATH` 中找到 `lark-cli`，或通过插件配置指定命令路径。
- 已完成 `lark-cli config init --new` 和 `lark-cli auth login --recommend`。
- Newman 的 terminal/sandbox 能读取 `~/.lark-cli`，插件已声明该目录为 writable root。
- Docker 场景需要把宿主机 `~/.lark-cli` 和 `~/.local/share/lark-cli` 挂载进容器。
- 如需默认发送给某个用户，可配置 `NEWMAN_LARK_DEFAULT_IM_USER_ID`；不配置时应在任务中显式给出目标。

以下章节保留旧 CLI channel 抽象，作为未来企业微信 CLI provider 或调试方案参考，不代表当前推荐实现。

## 3. 统一抽象

### 3.1 Provider 接口

```python
class CliChannelProvider(Protocol):
    name: str

    def auth_check_command(self) -> list[str]: ...
    def event_consumers(self) -> list[CliConsumerSpec]: ...
    def parse_event(self, raw: dict) -> ChannelInboundMessage | None: ...
    def build_reply_command(self, reply: ChannelReply) -> list[str]: ...
    def build_send_command(self, message: ChannelOutboundMessage) -> list[str]: ...
```

飞书 provider 只处理飞书字段和 `lark-cli` 命令。Newman 主流程只处理统一模型。

### 3.2 入站消息模型

```python
class ChannelInboundMessage(BaseModel):
    platform: str              # feishu / wecom
    transport: str             # cli
    account_id: str | None     # app/profile/corp id
    event_id: str | None
    message_id: str | None
    conversation_id: str
    sender_id: str
    text: str
    message_type: str = "text"
    reply_target: dict
    raw: dict
```

飞书的 `reply_target` 示例：

```json
{
  "mode": "reply",
  "message_id": "om_xxx",
  "chat_id": "oc_xxx"
}
```

企业微信 CLI provider 以后可以把同一字段映射成企业微信自己的会话、消息或用户标识。

## 4. 飞书 Provider MVP

### 4.1 入站监听

```bash
lark-cli event consume im.message.receive_v1 --as bot
```

约束：

- 这是阻塞式长跑命令。
- stdout 输出 NDJSON 事件。
- stderr 会输出 ready marker，例如 `[event] ready event_key=im.message.receive_v1`。
- 无界监听时不能让 stdin 直接 EOF，否则进程会优雅退出。
- 停止时优先 SIGTERM 或关闭 stdin，避免 `kill -9`。

### 4.2 回复命令

优先回复原消息：

```bash
lark-cli im +messages-reply --as bot --message-id "om_xxx" --text "..."
```

无法回复原消息时，降级为发送到 chat：

```bash
lark-cli im +messages-send --as bot --chat-id "oc_xxx" --text "..."
```

### 4.3 Tool wrapper 与 MCP 分层

参考 Teable 插件的接入方式，飞书能力采用“核心内置 Tool + 长尾 MCP”的混合方案：

- **内置 Tool**：只放高频、强约束、需要稳定 schema、审批、审计和限速的动作。
- **MCP Tool**：承载 `lark-cli` 的长尾命令，按需激活，不默认把所有能力暴露给模型。
- **Skill**：指导模型优先使用内置 Tool；只有内置 Tool 覆盖不了时才查看和激活飞书 MCP 工具。

第一批内置 6 个 Newman tools：

| Tool | 覆盖能力 | 风险 |
| --- | --- | --- |
| `feishu_auth` | 检查 `lark-cli auth status`、当前身份和权限状态 | low |
| `feishu_message` | 发送或回复消息，内部支持 `send` / `reply` action | medium |
| `feishu_doc` | 创建、读取、更新文档，返回文档 token 和 URL | medium |
| `feishu_sheet` | 读取、写入、追加电子表格数据，返回表格 URL 或更新摘要 | medium |
| `feishu_base` | 操作多维表格，包括 base、table、field、record、view 等核心数据动作 | medium |
| `feishu_task` | 创建、查询、更新任务，返回任务 ID 或 URL | medium |

暂不提供默认启用的裸 `feishu_cli_run`。如果需要调试，可放到 MCP 或管理员专用工具中，并默认禁用。

长尾能力建议通过 `plugins/feishu_cli/mcp/feishu_cli_mcp_server.py` 暴露，例如：

- 日历；
- 通讯录；
- Wiki / Drive；
- 邮箱；
- 视频会议 / 妙记；
- 审批；
- OKR；
- 飞书项目或其他低频域。

Tool wrapper 必须使用 argv list 执行，不能拼 shell 字符串。所有副作用工具默认走审批或至少审计。

## 5. 回复内容规划

短任务直接回复最终结果：

```text
已完成。

结果：
...
```

长任务先 ACK，再异步回复最终结果：

```text
已收到，正在处理：整理本周会议纪要。
完成后我会在这里回复。
```

完成后：

```text
已完成：本周会议纪要已整理。

产物：
- 飞书文档：https://...
- 关联任务：https://...

摘要：
...
```

失败时：

```text
未完成。

原因：飞书 CLI 缺少 docs:doc:write 权限。
处理方式：请重新授权 lark-cli，授权后我可以继续。
```

需要确认时：

```text
这个操作会向群聊发送消息。请回复“确认发送”继续。
```

群聊默认只响应：

- 私聊机器人；
- 群里明确 @ 机器人；
- 消息以配置的前缀开头，例如 `Newman ...`。

## 6. 进程管理

CLI Channel Transport 需要独立 supervisor：

- Newman 启动时拉起 consumer。
- 等待 ready marker。
- 持续读取 stdout，每行按 NDJSON 解析。
- stderr 写入 channel 日志。
- 进程异常退出后指数退避重启。
- Newman 停止时优雅停止 consumer。
- 不使用 `kill -9` 停止 `lark-cli event consume`。
- 对每个 EventKey 单独启动 consumer；多个 EventKey 可共享 provider 配置。

状态建议：

| 状态 | 含义 |
| --- | --- |
| `disabled` | 未启用 |
| `starting` | 子进程已启动但未 ready |
| `ready` | 已监听事件 |
| `retrying` | 异常退出，等待重启 |
| `failed` | 多次重启失败 |
| `stopped` | 已停止 |

## 7. 幂等、队列与限速

入站按“至少一次投递”处理：

- 幂等键优先级：`event_id` > `message_id` > `platform:conversation_id:sender_id:create_time`。
- 已处理事件写入 `backend_data/channels/cli/<provider>/dedup`。
- 重复事件不再次触发 Newman runtime，但可以记录审计日志。

出站走队列：

- 回复、发消息、建文档、写表格都进入统一调用节流。
- 每次发送带 idempotency key，例如 `newman:{session_id}:{message_id}`。
- 遇到 `429`、频控错误码或网络错误时延迟重试。
- 重试必须有最大次数和死信记录。

## 8. 调用次数和频控

飞书 CLI 本身是封装层，真实请求仍然会落到飞书 OpenAPI 或事件长连接：

- `event consume` 持有 WSS 长连接，主要消耗连接资源，不应按每条消息主动轮询。
- `im +messages-reply`、`im +messages-send`、文档、表格、日程、任务等都会调用飞书 OpenAPI，受接口频控限制。
- 飞书 OpenAPI 通常按“应用、租户、接口、时间窗口”限流；不同接口的阈值不同，设计上不能写死单一值。
- 企业自建应用可能存在月度 API 调用量上限或套餐差异，应以飞书开放平台后台和官方公告为准。
- 自定义机器人 webhook 另有独立频控；本方案主链路使用企业自建应用机器人，不把自定义机器人作为对话入口。

Newman 侧必须提供可配置限速：

```yaml
channels:
  cli:
    providers:
      feishu:
        rate_limit:
          outbound_per_second: 3
          outbound_per_minute: 80
          retry_max_attempts: 5
          retry_initial_backoff_seconds: 2
          retry_max_backoff_seconds: 120
```

健康检查不应高频调用远程 API。优先使用本地进程状态、ready marker、最近事件时间和最近成功发送时间。

## 9. 网络与部署要求

内网部署可用。CLI 长连接模式不要求 Newman 有公网 IP、域名或开放入站端口。

需要：

- Newman 所在机器能出站访问飞书开放平台；
- HTTPS/WSS 443 可用；
- DNS 能解析飞书相关域名；
- 公司代理或防火墙允许 WebSocket 长连接；
- Docker 部署时持久化 `lark-cli` 配置和登录态。

如果内网完全不能出公网，需要增加企业代理、relay/gateway 或改回 webhook + 公网入口方案。

## 10. 配置建议

最终后端配置建议：

```yaml
channels:
  cli:
    enabled: true
    providers:
      feishu:
        enabled: true
        kind: lark_cli
        binary: "lark-cli"
        identity: "bot"
        profile: "default"
        event_keys:
          - "im.message.receive_v1"
        reply_mode: "reply"
        group_response_policy: "mention_or_prefix"
        mention_required: true
        prefixes:
          - "Newman"
        rate_limit:
          outbound_per_second: 3
          outbound_per_minute: 80
```

开发脚本当前先使用环境变量控制：

```bash
NEWMAN_FEISHU_CLI_CHANNEL_ENABLED=false
NEWMAN_FEISHU_CLI_BIN=lark-cli
NEWMAN_FEISHU_CLI_IDENTITY=bot
NEWMAN_FEISHU_CLI_EVENT_KEY=im.message.receive_v1
```

## 11. 启停脚本约定

新增开发脚本：

| 脚本 | 作用 |
| --- | --- |
| `scripts/dev/start_feishu_cli_channel.sh` | 在开关启用时启动 `lark-cli event consume` |
| `scripts/dev/stop_feishu_cli_channel.sh` | 优雅停止事件消费进程 |
| `scripts/dev/status_feishu_cli_channel.sh` | 查看 PID、日志、事件文件状态 |

主脚本联动：

- `start_services.sh`：后端启动后，如启用则启动飞书 CLI channel。
- `stop_services.sh`：停止后端前先停止飞书 CLI channel。
- `restart_services.sh`：通过 stop/start 间接覆盖。
- `status_services.sh`：展示飞书 CLI channel 状态。

当前脚本只负责管理 `lark-cli event consume` 进程和事件日志。完整 Newman 入站处理还需要实现 `CliChannelSupervisor` 和 provider 解析逻辑。

## 12. 里程碑

### M1：飞书 CLI 事件桥 MVP

- 安装和授权 `lark-cli`。
- 启停脚本能管理 `event consume`。
- 后端实现 `FeishuCliProvider.parse_event()`。
- 文本消息进入 Newman session。
- Newman 使用 `+messages-reply` 回复。
- 基于 `message_id` 幂等。

### M2：工具能力

- 封装 `feishu_auth`、`feishu_message`、`feishu_doc`、`feishu_sheet`、`feishu_base`、`feishu_task` 6 个内置 tools。
- Tool 输出结构化链接和 ID。
- 副作用工具接入审批和审计。
- 增加调用限速和重试队列。

### M3：插件化

- 新增 `plugins/feishu_cli/plugin.yaml`。
- 插件内置一个轻量 `lark-cli` bridge skill，并通过 `lark_cli_skill` 读取 `lark-cli` 二进制内嵌的最新版 skills。
- 插件内嵌 `feishu_cli` MCP server，用于承载 Calendar、Contact、Wiki、Drive、Mail、VC、审批、OKR 等长尾能力。
- 插件声明 required permissions。
- 前端显示 provider 状态和授权提示。

### M4：企业微信兼容

- 新增 `WecomCliProvider`。
- 复用 CLI supervisor、dedup、queue、rate limit。
- 企业微信 provider 只处理命令、事件解析和回复目标映射。

## 13. 验收标准

- Newman 在内网机器上可通过飞书机器人接收消息。
- Newman 能在同一飞书会话中回复。
- 重复事件不会重复触发任务。
- CLI consumer 退出后能自动重启并记录状态。
- 飞书 CLI tools 能创建至少一种飞书产物并返回链接。
- 触发频控时不会丢任务，有延迟重试和可审计失败记录。
- 关闭 Newman 时不会留下无主 `lark-cli event consume` 进程。

## 14. 参考

- 飞书 CLI 仓库：<https://github.com/larksuite/cli>
- `lark-event` Skill：<https://github.com/larksuite/cli/blob/main/skills/lark-event/SKILL.md>
- `lark-im` Skill：<https://github.com/larksuite/cli/blob/main/skills/lark-im/SKILL.md>
- 飞书长连接事件接入说明：<https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case?lang=zh-CN>
- 飞书 API 频控策略：<https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control?lang=zh-CN>
