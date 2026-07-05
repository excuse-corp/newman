# Newman 架构说明

本文说明 Newman 的整体架构、核心模块和主要运行流程。它不是逐行实现说明，而是帮助开发者理解：

- 请求从哪里进入 Newman
- Runtime 如何组织会话、Prompt、工具和模型调用
- 文件、插件、技能、MCP、Scheduler、Channels 如何接入
- 哪些状态会持久化，哪些只是运行时状态

相关文档：

- [API 文档](Newman_API_v1.md)
- [上下文压缩说明](context_compression.md)
- [飞书接入指南](feishu_cc_connect_codex_reusable_solution.md)

## 1. 总体架构

```text
用户 / 前端 / 飞书 / Scheduler
        ↓
FastAPI Routes / ChannelService
        ↓
Session + Runtime State
        ↓
RunLoop
        ├── PromptAssembler
        ├── Provider
        ├── ToolRouter / ToolOrchestrator
        ├── ApprovalPolicy
        ├── Sandbox
        └── Hooks
        ↓
Session Store / Audit Log / Usage / Checkpoint / Evolution
```

核心分层：

- **接口层**：FastAPI REST、SSE、飞书 Channel SDK、legacy webhook。
- **运行时层**：`NewmanRuntime`、`RunLoop`、Prompt 拼装、工具编排、模型调用。
- **能力层**：内置工具、插件、技能、MCP server、Scheduler、Channels。
- **状态层**：sessions、audit logs、usage、checkpoints、memory、evolution runs。
- **前端层**：React 工作台，通过 REST + SSE 展示会话、工具执行、审批、文件、配置和运行状态。

## 2. 主要代码入口

| 模块 | 作用 |
| --- | --- |
| `backend/api/app.py` | 创建 FastAPI app，挂载 runtime、scheduler、channels 和路由 |
| `backend/runtime/run_loop.py` | 主运行时与单轮对话主循环 |
| `backend/runtime/prompt_assembler.py` | 拼装系统上下文、历史消息、checkpoint 和工具说明 |
| `backend/tools/` | 工具定义、路由、审批、执行和权限控制 |
| `backend/plugin_runtime/` | 插件扫描、manifest、hooks、插件内 skill / MCP 配置 |
| `backend/skill_runtime/` | Skill 注册与 `SKILLS_SNAPSHOT.md` 同步 |
| `backend/mcp/` | MCP server 注册、连接、资源和工具适配 |
| `backend/channels/` | 飞书 / 企业微信等外部渠道接入 |
| `backend/scheduler/` | 定时任务、运行记录和告警 |
| `backend/evolution/` | 自进化分析、文件操作、验证和回滚 |
| `frontend/` | Web 工作台 |

## 3. 启动阶段

`create_app()` 在服务进程启动时执行一次，后续请求共享同一个 `app.state.runtime`。

启动时主要步骤：

1. `get_settings()` 加载配置。
2. 创建 `NewmanRuntime`。
3. 创建 `SchedulerEngine`。
4. 创建 `ChannelEventBroker`。
5. 创建 `ChannelService`。
6. 注册 FastAPI middleware 和 routes。
7. startup 阶段执行：
   - `runtime.reload_ecosystem()`
   - `scheduler.refresh_schedule()`
   - `scheduler.start()`
   - `channels.start()`

`NewmanRuntime` 初始化的核心组件：

```text
NewmanRuntime
├── provider              # LLM provider
├── session_store         # 会话持久化
├── thread_manager        # 会话创建、恢复、删除
├── checkpoints           # 上下文压缩 checkpoint
├── prompt_assembler      # Prompt 拼装
├── registry              # ToolRegistry
├── router                # ToolRouter
├── orchestrator          # ToolOrchestrator
├── approvals             # 工具审批状态
├── plugin_service        # 插件服务
├── skill_registry        # 技能注册表
├── mcp_registry          # MCP server 注册表
├── hook_manager          # 插件 hooks
├── scheduler_store       # 定时任务存储
├── subagent_manager      # 多 Agent 运行管理
├── evolution_service     # 自进化
└── exec_sandbox          # 终端沙箱
```

## 4. 运行时生态加载

`reload_ecosystem()` 负责刷新插件、技能、工具和 MCP 能力。

执行内容：

1. 扫描 `plugins/`。
2. 同步 `skills/` 和插件内 skills。
3. 生成 `SKILLS_SNAPSHOT.md`。
4. 注册内置工具。
5. 注册插件和 MCP 工具。
6. 重建 `ToolRouter`。

触发时机：

- 服务启动时。
- 每轮用户消息开始时。
- 插件、skills、tools 目录被工具修改后。
- 插件 / 工具 / skill 相关 API 执行 rescan、enable、disable、import、upload 后。

设计意图：

- 本地新增或修改插件、技能后，不需要重启服务。
- LLM 下一轮会看到新的 skill snapshot 和工具列表。
- 工具执行中修改扩展目录时，可以在当前任务内热加载。

## 5. 输入入口

Newman 有四类主要输入入口。

### 5.1 Web 前端

```text
POST /api/sessions/{session_id}/messages
        ↓
messages.send_message()
        ↓
runtime.handle_message()
        ↓
RunLoop
```

特点：

- 返回 `text/event-stream`。
- 支持文本、图片和附件。
- 支持本轮审批模式。
- 同一 session 同时只允许一个活跃回合。
- 前端通过 SSE 获取实时回答、工具事件、审批请求和最终结果。

### 5.2 飞书 Channel

```text
飞书消息
        ↓
FeishuChannelTransport
        ↓
ChannelService
        ↓
runtime.handle_message()
        ↓
飞书回复
```

特点：

- 推荐使用官方 Python Channel SDK 长连接。
- 不依赖公网 webhook。
- ChannelService 负责用户、群、日期到 Newman session 的映射。
- 飞书入站默认更偏向自动执行，避免任务卡在 Web 页面审批。
- 外部渠道事件通过 `/api/channels/events/stream` 给前端感知。

### 5.3 Scheduler

```text
SchedulerEngine
        ↓
ScheduledTask.action
        ↓
session_message / background_task
        ↓
runtime.handle_message()
```

特点：

- 使用 cron + timezone 描述触发时间。
- 任务可绑定已有 session，也可作为后台任务运行。
- 会检查目标 session 是否已有活跃 Web 回合，避免同一 session 并发执行。

### 5.4 管理 API

管理 API 不一定进入 RunLoop，例如：

- Auth / Bootstrap
- Config reload
- Workspace 文件浏览
- Plugins / Tools / Skills
- MCP server 管理
- Evolution run / rollback
- Scheduler task 管理

这些接口通常直接操作 runtime、store 或配置文件。

## 6. 单轮 Web 消息流程

```text
用户发送消息
        ↓
解析 content / attachments / approval_mode / environment_context
        ↓
检查 session 是否已有活跃任务
        ↓
创建 SSE event queue
        ↓
保存附件并写入 user message metadata
        ↓
runtime.handle_message()
        ↓
持续 emit SSE 事件
        ↓
保存最终 assistant message
        ↓
stream_completed
```

关键状态：

- `active_message_runs`：进程内活跃任务表。
- `request_id`：HTTP 请求追踪 ID。
- `turn_id`：单轮对话 ID，用于聚合消息、工具和事件。
- `approval_mode`：本轮工具审批策略。
- `environment_context`：浏览器或前端传入的运行环境上下文。

## 7. RunLoop 主循环

`runtime.handle_message()` 是对话执行入口。核心循环可以概括为：

```text
handle_message()
        ↓
写入 user message
        ↓
SessionStart hooks
        ↓
while tool_depth < max_tool_depth:
    reload skill snapshot
    maybe checkpoint compact
    assemble prompt
    build provider tool schemas
    call provider stream
    if invalid tool calls:
        inject feedback and continue
    if tool calls:
        execute tools
        append tool messages
        continue
    else:
        decide final / continue / blocked / awaiting_user
        break
        ↓
保存 assistant final message
        ↓
SessionEnd hooks
```

RunLoop 的职责：

- 控制模型调用和工具调用的循环。
- 在工具调用前保证用户能看到可理解的行动说明。
- 处理无效工具名、工具失败、审批等待、用户中断和工具上限。
- 在最终回答前做完成度判断，避免模型只说“我去做”但没有真正完成。
- 在长会话接近上下文上限时触发压缩。

## 8. Prompt 组成

Prompt 由 `PromptAssembler` 拼装，通常包含：

1. Stable Context
   - `Newman.md`
   - `USER.md`
   - `MEMORY.md`
   - `SKILLS_SNAPSHOT.md`
   - `TOOLS_SNAPSHOT.md`
2. 工具、技能和用户输入护栏。
3. collaboration mode prompt。
4. workflow state prompt。
5. checkpoint summary。
6. 当前模型可见的 session messages。

注意：

- `session.messages` 是完整 transcript。
- 模型可见消息可能会跳过 checkpoint 已归档前缀。
- 上下文压缩只改变 prompt 可见范围，不删除完整 transcript。
- `context_usage` 衡量的是下一次请求的预计 prompt 占用，详见 [上下文压缩说明](context_compression.md)。

## 9. Provider 调用

RunLoop 调用 provider 的流式接口，输出会被拆成多类事件：

```text
provider.chat_stream(messages, tools)
        ↓
content tokens       -> assistant_delta
commentary tokens    -> commentary_delta
thinking tokens      -> 内部解析
tool call deltas     -> tool_call_arguments_delta
tool calls           -> 后续工具执行
usage                -> usage store
finish_reason        -> 终态判断
```

ProviderResponse 主要包含：

- `content`
- `commentary`
- `thinking`
- `tool_calls`
- `invalid_tool_calls`
- `usage`
- `provider_state`
- `finish_reason`

## 10. 工具执行架构

工具执行由 `ToolRouter` 和 `ToolOrchestrator` 协作完成。

```text
tool_call
        ↓
ToolRouter.route()
        ↓
static checks
        ↓
PreToolUse hook
        ↓
ToolOrchestrator.execute()
        ├── validate_arguments()
        ├── ApprovalPolicy.evaluate()
        ├── tool.run_streaming()
        └── RetryPolicy
        ↓
normalize result
        ↓
append tool SessionMessage
        ↓
PostToolUse hook
        ↓
FileChanged hook / reload_ecosystem
```

工具来源：

- 内置工具：`backend/tools/impl/`
- 插件 MCP 工具
- 外部 MCP server 工具

工具执行前的安全控制：

- 参数校验。
- 路径权限检查。
- 终端命令风险分析。
- MCP 参数路径校验。
- 审批策略。
- 沙箱限制。

工具执行结果会写入：

- SSE 事件。
- session tool message。
- audit log。
- usage / retry / error metadata。

## 11. 审批与沙箱

审批策略按工具、命令风险和本轮 `approval_mode` 决定。

常见结果：

- `allow`：直接执行。
- `ask`：发出 `tool_approval_request`，等待用户 approve / reject。
- `deny`：直接拒绝执行。

终端工具在 Linux 下优先走 bubblewrap 沙箱：

```text
terminal
        ↓
analyze_terminal_command()
        ↓
NativeSandbox / linux_bwrap
        ↓
subprocess
```

沙箱会根据配置挂载：

- workspace 可写根。
- 只读根。
- protected roots。
- 临时目录。
- 网络隔离策略。

## 12. Turn 决策与终态

模型返回后，RunLoop 会判断下一步：

```text
invalid tool call -> 注入反馈，继续
有 tool_calls -> 执行工具，继续
无 tool_calls -> 判断是否可以收口
```

最终可能进入：

- `finalize`：正常完成。
- `finalize_blocked`：明确阻塞后收口。
- `awaiting_user`：等待用户补充输入。
- `tool_limit`：达到工具调用上限，输出阶段性结果。
- `fatal_tool_error`：工具致命失败后收口。
- `provider_error`：模型调用失败。
- `context_irreducible`：上下文无法继续压缩。

前端展示上应以 `final_response` 为最终回答信号，`answer_started` 只表示候选回答开始。

## 13. 状态与持久化

主要持久化位置：

| 数据 | 位置 |
| --- | --- |
| Session transcript | `backend_data/sessions/` |
| Audit log | `backend_data/audit/{session_id}.log` |
| Tool output archive | `backend_data/sessions/tool_outputs/` |
| Memory | `backend_data/memory/` |
| Checkpoint | session 相关 checkpoint 存储 |
| Usage | PostgreSQL `model_usage_records` |
| Scheduler | `backend_data/scheduler/` |
| Channels | `backend_data/channels/` |
| Evolution | `backend_data/evolution/` |
| Plugin state | `backend_data/plugin_state.json` |

`SessionMessage` 是核心 transcript 单位：

```text
SessionMessage
├── id
├── role: system | user | assistant | tool
├── content
├── created_at
└── metadata
    ├── turn_id
    ├── request_id
    ├── group_id
    ├── tool_call_id
    ├── approval_mode
    ├── attachments
    ├── success
    ├── category
    └── ...
```

## 14. 插件、技能与 MCP

### 插件

插件目录位于 `plugins/`。插件可提供：

- manifest。
- hooks。
- skills。
- MCP server 配置。
- UI 或其他资源。

插件状态由后端记录，可通过 API 启用、禁用、重扫和删除。

### 技能

Skill 会进入 `SKILLS_SNAPSHOT.md`，再注入 Stable Context。

LLM 看到的是技能摘要和使用规则；当任务匹配某个 skill 时，需要先读取对应 `SKILL.md`，再按技能说明执行。

### MCP

MCP server 可来自：

- `backend_data/mcp` 配置。
- 插件 manifest。

MCP registry 负责连接 server、列出 resources、适配 MCP tools，并把工具注册到 ToolRegistry。

## 15. 自进化

自进化用于把真实任务里的可复用经验沉淀到本地运行时。

触发点：

- 新 session 创建时，总结上一个非空 session。
- 长会话累计到指定 user turn 数后，做增量总结。
- 手动调用 evolution API。

执行链路：

```text
EvolutionService.run_for_session()
        ↓
构造上下文：session、checkpoint、memory、skills、历史 evolution
        ↓
LLM 生成 memory_updates / skill_update_requests
        ↓
后端确定性应用文件操作
        ↓
保存快照和 diff
        ↓
验证 parse / py_compile / reload_ecosystem
        ↓
失败回滚，成功记录 run
```

自进化不会让模型直接调用工具改文件；模型只产出结构化建议，落盘、验证和回滚由后端控制。

## 16. Channels 架构

ChannelService 把外部消息转成 Newman 任务。

```text
External Platform
        ↓
Transport
        ↓
ChannelService
        ├── 去重
        ├── 鉴权 / 白名单
        ├── session 映射
        ├── 并发保护
        └── runtime.handle_message()
        ↓
Transport reply
```

飞书主链路：

- `FeishuChannelTransport.start()` 建立长连接。
- 收到消息后归一化为 `ChannelMessage`。
- 过滤群聊非 @ 消息和白名单外消息。
- 根据 app、chat、sender、日期映射 session。
- 调用 Runtime。
- 超过短等待阈值时先回复“已收到，正在处理”。
- 完成后回复最终结果。

## 17. 前端事件模型

前端主要消费两类 SSE。

### 会话 turn 流

来自：

```text
POST /api/sessions/{session_id}/messages
```

用于展示当前用户发起的一轮任务。

常见事件：

- `assistant_delta`
- `commentary_delta`
- `tool_call_started`
- `tool_call_arguments_delta`
- `tool_call_output_delta`
- `tool_call_finished`
- `tool_approval_request`
- `plan_updated`
- `attachment_received`
- `attachment_processed`
- `checkpoint_created`
- `turn_interrupted`
- `final_response`
- `stream_completed`

### 外部 Channel 事件流

来自：

```text
GET /api/channels/events/stream
```

用于感知飞书等外部渠道产生的新会话、新消息或状态变化。

## 18. 典型 Web 时序

```text
用户
 ↓
前端 POST /messages
 ↓
API 创建 SSE worker
 ↓
RunLoop 写入 user message
 ↓
PromptAssembler 拼装 prompt
 ↓
Provider 流式返回
 ↓
如果有 tool_calls：
    工具审批 / 执行 / 写入 tool message
    回到 Provider 下一轮
 ↓
如果无 tool_calls：
    completion gate / judge 判断是否可收口
 ↓
保存 assistant message
 ↓
发送 final_response
 ↓
发送 stream_completed
```

## 19. 关键边界

- `create_app()` 和 `NewmanRuntime.__init__()` 是进程级初始化，不是每次请求执行。
- `reload_ecosystem()` 会较频繁执行，但它只刷新扩展生态，不重建整个 FastAPI app。
- `session.messages` 保留完整 transcript；上下文压缩只影响模型可见历史。
- `thread_isolation` 只隔离上下文，不隔离文件系统。
- 同一 session 同时只允许一个 Web 消息任务运行。
- Scheduler、Channel 和 Web 都可能进入 Runtime，因此需要依赖 session busy check 降低并发冲突。
- 终端沙箱主要面向 Linux；Windows/macOS 源码运行时不是同一套 native sandbox 能力。
- `final_response` 是最终回答信号，`assistant_delta` 只是流式候选内容。
