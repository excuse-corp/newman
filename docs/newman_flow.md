# Newman 完整流程梳理

## 一、总览

```
用户输入 / 飞书入站消息
        ↓
API 路由 / ChannelService
        ↓
Session 管理 → RunLoop 主循环 → Provider 调用 → 工具执行
                                      ↓             ↑
                               无 tool_calls 时判定收口
                               有 tool_calls 时循环执行
        ↓
SSE / 飞书 Channel SDK 回复 / 持久化 assistant message
```

---

## 二、启动阶段

### 2.1 应用初始化 (`api/app.py`)

> **触发时机**：`create_app()` 在 **uvicorn 启动时执行一次**，不是每次用户发言。后续所有请求共享同一个 `app.state.runtime` 实例。

```python
def create_app() -> FastAPI:
    settings = get_settings()                          # 加载配置（一次性）
    app.state.runtime = NewmanRuntime(settings)        # 初始化运行时（一次性）
    app.state.scheduler = SchedulerEngine(...)         # 初始化定时任务（一次性）
    app.state.channels = ChannelService(...)           # 初始化通道服务（一次性）
    app.state.channel_events = ChannelEventBroker(...) # 外部渠道事件流（一次性）
```

`NewmanRuntime.__init__` 初始化所有核心组件：

```
NewmanRuntime
├── provider                 # LLM 提供商（OpenAI 兼容等）
├── session_store            # Session 持久化存储
├── thread_manager           # 会话生命周期管理
├── checkpoints              # 上下文压缩 checkpoint 存储
├── memory_extractor         # 用户偏好提取器（兼容旧 USER.md 流程）
├── stable_context           # 稳定上下文加载器（Newman.md / USER.md / MEMORY.md / SKILLS_SNAPSHOT.md / TOOLS_SNAPSHOT.md）
├── prompt_assembler         # Prompt 拼装器
├── plugin_service           # 插件服务
├── skill_registry           # 技能注册表
├── evolution_store          # 自进化运行记录、快照与事件日志
├── evolution_service        # 自进化分析、应用、验证与回滚
├── hook_manager             # 钩子管理器
├── mcp_registry             # MCP 服务器注册表
├── registry                 # 工具注册表（ToolRegistry）
├── router                   # 工具路由器（ToolRouter）
├── orchestrator             # 工具编排器（ToolOrchestrator）
└── exec_sandbox             # 沙箱（NativeSandbox / bwrap）
```

ChannelService 初始化：

```
ChannelService
├── FeishuChannelTransport   # 飞书官方 Python Channel SDK 长连接
├── ChannelSessionStore      # 飞书 chat/user/date → Newman session 映射
├── channel event broker     # 前端订阅 /api/channels/events/stream
└── legacy webhook channels  # feishu/wecom webhook 基线
```

FastAPI 生命周期启动后会调用 `ChannelService.start()`，当 `channels.feishu.enabled=true` 且
`transport=channel_sdk` 时，后端会建立飞书长连接。飞书用户发消息不走
`POST /api/sessions/{session_id}/messages`，而是由 SDK 回调进入 `ChannelService.handle_transport_message()`。

启动时调用 `reload_ecosystem()`：
1. `plugin_service.reload()` — 扫描 `plugins/` 目录
2. `skill_registry.sync_snapshot()` — 生成 `SKILLS_SNAPSHOT.md`
3. `_build_registry()` — 注册内置工具 + 插件 MCP 工具
4. 创建 `ToolRouter`

> **触发时机**：`create_app()` / `NewmanRuntime.__init__()` 只在 **服务进程启动时执行一次**（uvicorn 加载模块时）。之后不会重复。

### 2.2 `reload_ecosystem()` 触发时机

`reload_ecosystem()` 是插件/技能/工具热加载的核心，执行上述 4 步。它有 **3 个触发点**：

```
触发点 1：服务启动时（一次性）
──────────────────────────────────
  NewmanRuntime.__init__()
  └── self.reload_ecosystem()              # run_loop.py:586

触发点 2：每次用户发消息时
──────────────────────────────────
  handle_message()                         # run_loop.py:722
  └── self.reload_ecosystem()              # run_loop.py:735  ← 每轮对话开头

触发点 3：工具执行导致文件变更时（热加载）
──────────────────────────────────
  run_loop.py:1059-1074
  ├── write_file/edit_file 成功
  │   └── 路径在 plugins/skills/tools 目录？ → reload_ecosystem()
  └── terminal 成功
      └── 命令修改了上述目录？ → reload_ecosystem()
```

**实际效果**：

| 场景 | 何时生效 |
|------|---------|
| 用户放一个新插件到 `plugins/` | 下次发言自动生效 |
| 用户修改了 `SKILL.md` | 下次发言 LLM 看到更新后的技能快照 |
| 中途通过 `write_file` 修改了插件/技能文件 | 当前轮次内热加载生效 |
| 通过前端 API 启用/禁用插件 | 调用 `POST /api/plugins/{name}/enable` 后立即生效（API 内部调用 `reload_ecosystem()`） |

---

## 三、输入入口

### 3.1 创建会话

```
POST /api/sessions
        │
        ▼
ThreadManager.create_or_restore()
        │
        ├── 新建 → SessionStore.create() → 返回 session_id
        │           └── schedule_previous_session_evolution()  # 后台总结上一个会话并自动进化
        └── 恢复 → SessionStore.get(session_id)
```

自进化不会阻塞创建会话响应。`mock` provider 下会跳过调度。

### 3.2 前端发送消息（核心入口）

```
POST /api/sessions/{session_id}/messages
        │
        ▼
send_message()
        │
        ├── 1. 检查是否已有任务在运行（409 冲突）
        ├── 2. 检查定时任务是否占用该会话（409 冲突）
        ├── 3. 解析请求体（content + attachments + approval_mode）
        ├── 4. 创建 event_stream() 协程
        │       │
        │       ├── 保存附件 → AttachmentService.save_uploads()
        │       ├── 分析附件 → attachment_service.analyze_attachments()
        │       └── runtime.handle_message()  ←── 进入 RunLoop
        │
        └── 5. 返回 StreamingResponse (SSE)
                │
                └── 从 event_queue 中读取事件，推送给前端
```

### 3.3 飞书入站消息

飞书入站不经过前端消息 API。当前主路径是官方 Python Channel SDK：

```
飞书用户消息
        │
        ▼
FeishuChannelTransport._handle_message()
        │
        ├── 1. 归一化 ChannelMessage
        ├── 2. 按 event_id/message_id 去重
        ├── 3. 群聊非 @ 消息、白名单外消息直接忽略
        ├── 4. ChannelService.process_transport_message()
        │       ├── 按 app_id/chat_id/sender_open_id/日期查找或创建 Newman session
        │       ├── 防止同一飞书 session 并发运行多个 turn
        │       └── runtime.handle_message(..., turn_approval_mode=auto_allow)
        ├── 5. 超过短等待阈值时先通过 SDK 回复“已收到，正在处理”
        └── 6. runtime 结束后通过 SDK 回复最终内容
```

飞书入站还会写入 channel 级事件流：

```
GET /api/channels/events/stream
```

这条 SSE 用于前端感知外部渠道产生的新会话或新消息；它不是普通会话 turn 的消息流。

### 3.4 SSE 事件流

前端通过 SSE 接收实时事件，关键事件类型：

| 事件 | 含义 |
|------|------|
| `session_created` | 会话创建完成 |
| `attachment_received` | 附件已接收 |
| `attachment_processed` | 附件分析完成 |
| `hook_triggered` | 钩子触发 |
| `commentary_delta` | LLM 正在输出 commentary |
| `commentary_complete` | commentary 输出完成 |
| `assistant_delta` | LLM 正在输出候选回答 |
| `answer_started` | 回答开始 |
| `final_response` | 本轮最终 assistant message 已持久化 |
| `turn_completed` | 本轮结束，携带 finish_reason / turn_outcome |
| `tool_call_started` | 工具调用开始 |
| `tool_call_arguments_delta` | 工具调用参数生成进度 |
| `tool_call_output_delta` | 工具执行实时输出 |
| `tool_call_finished` | 工具调用完成 |
| `tool_approval_request` | 请求用户审批 |
| `tool_approval_resolved` | 审批结果 |
| `tool_retry_scheduled` | 工具重试计划 |
| `skill_used` | 技能被使用 |
| `plan_updated` | 计划更新 |
| `collaboration_mode_changed` | 协作模式变更 |
| `error` | 错误 |
| `turn_interrupted` | 用户中断 |
| `stream_completed` | 流结束 |

补充：

- `answer_started` 只表示已经开始释放正式回答候选，不是完成信号。
- 若候选回答随后被判定为未完成，后端会发送 `assistant_delta` 且 `reset=true`，前端需要清空临时回答。
- `final_response` 才是前端展示最终回答和对齐持久化 assistant message 的主信号。

---

## 四、RunLoop 主循环

### 4.1 入口：`handle_message()`

```
handle_message(session_id, content, emit, ...)
        │
        ├── 1. reload_ecosystem()           # 每轮重新加载插件/工具
        ├── 2. 创建 user SessionMessage     # 写入用户消息
        ├── 3. session_store.append_message()
        ├── 4. 创建 SessionTask             # 本轮任务上下文
        ├── 5. emit_hooks("SessionStart")   # 触发会话开始钩子
        │
        └── 6. 进入主循环 ─────────────────────────────────────┐
                                                              │
            ┌─────────────────────────────────────────────────┘
            │
            ▼
    ┌──────────────────────────────────────┐
    │  for _ in range(max_tool_depth):     │  ← 最多 N 轮工具调用
    │                                      │
    │  ┌─ 1. skill_registry.sync_snapshot  │
    │  ├─ 2. _maybe_checkpoint()           │  ← 上下文压缩检查
    │  ├─ 3. _assemble_task_messages()     │  ← 拼装 prompt
    │  ├─ 4. _provider_tools_for_turn()    │  ← 获取可用工具列表
    │  │                                  │
    │  ├─ 5. _stream_provider_response()   │  ← 调用 LLM
    │  │                                  │
    │  ├─ 6. invalid tool call recovery    │  ← 模型调用不存在工具时回灌纠偏
    │  │                                  │
    │  ├─ 7. ensure commentary             │  ← 工具调用前补齐可见行动说明
    │  │                                  │
    │  ├─ 8. decide_turn_step()            │  ← 继续/结束/阻塞
    │  ├─ 8.5 completion judge（可选）     │  ← 执行型任务的 finalize 再校验
    │  │                                  │
    │  ├─── [无工具调用] → finalize → return│
    │  │                                  │
    │  ├─ 9. 逐个执行工具调用              │
    │  │   ├── 权限检查                    │
    │  │   ├── 路由到工具                  │
    │  │   ├── static_checks              │
    │  │   ├── emit PreToolUse hook        │
    │  │   ├── orchestrator.execute()      │
    │  │   ├── emit PostToolUse hook       │
    │  │   ├── FileChanged hook            │
    │  │   └── 热加载检查                  │
    │  │                                  │
    │  └─ 8. 回到循环顶部                  │
    │                                      │
    └──────────────────────────────────────┘
```

### 4.2 Prompt 拼装：`_assemble_task_messages()`

```
PromptAssembler.assemble()
        │
        ├── 1. stable_context.build(tools_overview)
        │       ├── Newman.md          # 系统人设与规则
        │       ├── USER.md            # 用户画像
        │       ├── SKILLS_SNAPSHOT.md # 可用技能列表
        │       └── tools_overview     # 工具描述 + 路径权限
        │
        ├── 2. COMMENTARY_SYSTEM_GUARDRAIL   # 工具/技能前必须有 commentary
        ├── 3. TOOL_ACTION_SYSTEM_GUARDRAIL  # 需要继续动工具时不能假装 finalize
        ├── 4. USER_INPUT_SYSTEM_GUARDRAIL   # 需要用户确认时必须走 request_user_input
        ├── 5. collaboration_mode_prompt     # 协作模式（default/plan）
        ├── 6. workflow_state_prompt         # 工作流状态
        ├── 7. checkpoint summary            # 上下文压缩摘要
        │
        └── 8. 拼装历史消息
                ├── system message  ← 上述所有内容合并
                ├── assistant messages（含 tool_calls）
                ├── tool messages
                └── user messages
```

### 4.3 LLM 调用：`_stream_provider_response()`

```
_stream_provider_response(assembled, tools, emit, ...)
        │
        ├── provider.chat_stream(messages, tools)  # 调用 LLM 流式 API
        │       │
        │       └── 流式返回 token
        │           ├── content tokens      → emit("assistant_delta")
        │           ├── thinking tokens     → 解析 <think> 标签
        │           ├── commentary tokens   → emit("commentary_delta")
        │           ├── tool_call_delta      → emit("tool_call_arguments_delta")
        │           └── tool_call            → ProviderResponse.tool_calls
        │
        └── 返回 ProviderResponse
                ├── content: str           # 最终回答
                ├── commentary: str        # 过程说明
                ├── thinking: str          # 思考过程
                ├── tool_calls: list       # 工具调用列表
                ├── invalid_tool_calls: list
                ├── usage: TokenUsage      # token 用量
                ├── provider_state: dict    # provider 特有状态，如 reasoning replay 字段
                └── finish_reason: str     # 结束原因
```

---

## 五、工具执行流程

### 5.1 单个工具调用链

```
tool_call (from LLM response)
        │
        ├── 1. skill_usage_payload_for_tool_call()
        │       └── 检测是否在读取 SKILL.md（技能使用追踪）
        │
        ├── 2. emit("tool_call_started")
        │
        ├── 3. _tool_disallow_reason_for_task()
        │       └── 检查工具是否被禁用
        │
        ├── 4. router.route(tool_name, arguments)
        │       └── 从 ToolRegistry 获取工具实例
        │
        ├── 5. router.static_checks(tool, arguments)
        │       │
        │       ├── terminal 工具：
        │       │   └── analyze_terminal_command()
        │       │       ├── 解析命令中的路径
        │       │       ├── classify_path() → writable/readable/protected/forbidden
        │       │       └── 检测是否为 mutation 命令
        │       │
        │       ├── 文件工具（read_file/write_file/...）：
        │       │   └── classify_path(path_policy, path)
        │       │
        │       └── MCP 工具：
        │           └── validate_mcp_argument_paths()
        │
        ├── 6. emit("PreToolUse", hook)
        │
        ├── 7. orchestrator.execute(tool, arguments, ...)
        │       │
        │       ├── a. tool.validate_arguments()     # 参数校验
        │       ├── b. approval_policy.evaluate()    # 审批策略
        │       │       ├── "deny"  → 拒绝执行
        │       │       ├── "ask"   → 请求用户审批
        │       │       │              ├── emit("tool_approval_request")
        │       │       │              ├── await approvals.wait()
        │       │       │              └── emit("tool_approval_resolved")
        │       │       └── "allow" → 直接执行
        │       │
        │       ├── c. tool.run_streaming(arguments, session_id, emit_output)
        │       │       │
        │       │       ├── 内置工具：直接执行
        │       │       │   └── terminal → sandbox.execute_shell(command)
        │       │       │       │
        │       │       │       ├── bwrap 沙箱模式：
        │       │       │       │   └── build_bwrap_command() → subprocess
        │       │       │       │       ├── --unshare-net     （网络隔离）
        │       │       │       │       ├── --ro-bind         （只读挂载）
        │       │       │       │       ├── --bind            （可写挂载）
        │       │       │       │       └── --tmpfs           （保护路径）
        │       │       │       │
        │       │       │       └── danger-full-access 模式：
        │       │       │           └── 直接 subprocess
        │       │       │
        │       │       └── MCP 工具：通过 MCP 协议调用
        │       │
        │       └── d. 重试策略（RetryPolicy）
        │               └── 失败时自动重试，emit("tool_retry_scheduled")
        │
        ├── 8. normalize_result(result)
        │
        ├── 9. result → SessionMessage（tool role）
        │       └── _build_tool_session_message()
        │           ├── content = stdout + stderr（terminal）或 stdout（其他）
        │           └── metadata = { success, category, tool, ... }
        │
        ├── 10. emit("tool_call_finished")
        │
        ├── 11. emit("PostToolUse", hook)
        │
        ├── 12. 热加载检查
        │       ├── write_file/edit_file 成功 → 检查路径是否在 plugins/skills/tools 目录
        │       └── terminal 成功 → 检查命令是否修改了上述目录
        │       └── 如果是 → reload_ecosystem()
        │
        └── 13. 失败处理 / 进度状态更新
                ├── recovery_class == "recoverable" → 记录，继续循环
                ├── recovery_class == "fatal"       → _finalize_fatal_tool_error()
                └── turn_outcome == "awaiting_user"  → _finalize_awaiting_user_input()
```

`TurnProgressState` 现在会区分 3 类“成功”：

- `diagnostic_success`：例如读错误日志、打印出报错行，只说明拿到了诊断信息，不会清除未解决失败状态
- `progress_success`：例如 `write_file` / `edit_file` 成功，或者 `terminal` 明确写出了路径/文件，只说明任务在推进
- `resolved_success`：例如产生 `output_files`，或 `request_user_input` 进入 `awaiting_user`，这时才会清除 `has_unresolved_recoverable_failure`

---

## 六、Turn 决策：`decide_turn_step()`

LLM 返回后，系统先做硬分支，再做收口判断：

```
ProviderResponse
        │
        ├── 有 invalid_tool_calls？
        │   └── YES → 注入 invalid_tool_call_feedback 后继续
        │           ├── commentary/thinking/think 伪工具 → 下一轮禁用工具直接回答一次
        │           └── 其他不存在工具 → 要求只使用当前可用工具
        │
        ├── 有 tool_calls？
        │   └── YES → "continue"（继续执行工具）
        │
        └── NO → 这段文本只是候选 assistant 回答，必须判断是否允许收口
                │
                ├── final_answer_gate_reason()
                │   ├── 空回答 → "empty_final_answer"
                │   ├── 看起来像未完成的行动 → "incomplete_action_statement"
                │   ├── 有未解决的工具失败且无完成信号 → "unresolved_tool_failure_without_result"
                │   └── 通过 → None（有效回答）
                │
                ├── gate 通过 → tentative "finalize"
                │   │
                │   └── 若当前用户请求属于执行型任务
                │       且本轮没有明确产物证据、回答里也没有可解析的本地附件
                │       → 进入 LLM completion judge
                │           ├── final    → finalize
                │           ├── continue → 注入指令继续做，工具保持可用
                │           ├── blocked  → finalize_blocked
                │           └── ask_user → 下一轮必须调用 request_user_input
                │
                ├── gate 未通过 + 可恢复失败尚未耗尽
                │   └── "continue" + recovery_instruction
                │       └── 可以继续调用工具，但不要重复同一个已知失败动作
                │
                ├── gate 未通过 + 首次 finalization retry
                │   └── "continue" + finalization_instruction
                │       └── 工具仍然可用，不再强制 force_no_tools_next
                │
                └── gate 未通过 + 重试额度耗尽
                    └── "finalize_blocked"（强制结束，标记为阻塞）
```

当前完成判断仍是“确定性 gate + 可选 LLM judge”的组合：

- 确定性 gate 位于 `backend/runtime/turn_completion.py`，主要负责拦截空回答、明显行动说明和未解决工具失败。
- LLM completion judge 位于 `backend/runtime/run_loop.py`，只在本地 gate 认为可 finalize 且用户请求看起来像执行型任务时触发。
- judge 返回 `continue` / `ask_user` 时，后端会发送 `assistant_delta(reset=true)` 撤回已经流出的候选回答，再把反馈作为 system message 注入下一轮。
- `answer_started` 只是候选回答开始，不代表已经完成；`final_response` 才代表最终 assistant message 已持久化。

---

## 七、终态分支

```
RunLoop 结束的 7 种方式：

1. finalize（正常结束）
   └── LLM 返回有效最终回答 → 保存 assistant message → emit("final_response") → emit("turn_completed") → emit("SessionEnd")
                                      └── 达到 20 个 user turn 时后台 schedule_evolution("turn_interval")

2. finalize_blocked（收口被拦截）
   └── LLM 连续返回无效回答，或 completion judge 判定当前已明确阻塞 → 输出阻塞信息

3. awaiting_user（等待用户输入）
   └── 工具返回 turn_outcome=awaiting_user，或 completion judge 要求改走 request_user_input → 暂停等待

4. tool_limit（工具调用上限）
   └── tool_depth >= max_tool_depth → 注入指令要求给出阶段性结论，finish_reason="tool_limit_reached"

5. fatal_tool_error（致命工具错误）
   └── 工具返回 recovery_class="fatal" → 尝试无工具收口或使用 fallback 说明原因

6. provider_error（LLM 提供商错误）
   └── API 调用失败 → 保存 provider failure assistant message，并 emit("error")

7. context_irreducible（上下文不可压缩）
   └── 上下文溢出且无法压缩 → 输出溢出提示
```

所有正常终态都会持久化一条 `role="assistant"` 的 SessionMessage；工具调用过程中的行动说明则以
`role="assistant"` 且 `metadata.tool_calls` 记录，用于下一轮 prompt 恢复工具协议，不作为最终回答展示。

---

## 八、Session 管理

### 8.1 数据模型

```
SessionRecord
├── session_id: str
├── title: str
├── created_at / updated_at
├── messages: list[SessionMessage]
│       │
│       ├── role: system | user | assistant | tool
│       ├── content: str
│       └── metadata: dict
│           ├── turn_id          # 所属轮次
│           ├── request_id       # 请求 ID
│           ├── group_id         # 动作组 ID
│           ├── tool_call_id     # 工具调用 ID
│           ├── success          # 工具是否成功
│           ├── category         # 结果分类
│           ├── attachments      # 附件信息
│           └── ...
│
└── metadata: dict
    ├── plan                   # 执行计划
    ├── collaboration_mode     # 协作模式
    ├── checkpoint_active      # 是否有活跃 checkpoint
    └── ...
```

### 8.2 持久化

- Session 文件：`backend_data/sessions/{date}_{session_id}.json`
- 审计日志：`backend_data/audit/{session_id}.log`（每行一个 JSON 事件）
- Checkpoint：与 session 同目录，压缩后的上下文摘要
- Evolution：`backend_data/evolution/runs/*.json`、`snapshots/`、`events.jsonl`

### 8.3 上下文压缩

当消息过多导致上下文溢出时：

```
_maybe_checkpoint()
        │
        ├── build_context_usage_snapshot()  # 计算当前上下文用量
        │
        ├── 用量 < 上限 → 跳过
        │
        └── 用量 >= 上限
            │
            ├── microcompact_session()  # 先压缩旧工具输出
            ├── summarize_messages()  # LLM 总结历史消息
            ├── 保留最近 N 个 segment
            ├── 生成 CheckpointRecord（含摘要）
            └── 后续 prompt 中注入 checkpoint summary
```

---

## 九、钩子系统

```
Hook 生命周期：
                        ┌─────────────────────────────┐
                        │         SessionStart         │ ← 每轮对话开始
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │         PreToolUse           │ ← 工具执行前
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │     工具执行 (execute)       │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │        PostToolUse           │ ← 工具执行后
                        └──────────────┬──────────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
        ┌─────────▼─────────┐ ┌────────▼────────┐ ┌────────▼────────┐
        │    FileChanged     │ │  继续下一轮循环  │ │   SessionEnd    │
        │ (文件变更时触发)    │ │                 │ │  (对话结束时)   │
        └───────────────────┘ └─────────────────┘ └─────────────────┘
```

钩子触发方式：
- **静态消息**：`plugin.yaml` 中的 `message` 字段，直接注入事件流
- **动态处理**：`handler` 指向的 Python 脚本，通过子进程执行，stdin 传入 JSON，stdout 读取输出

---

## 十、插件与技能

### 10.1 插件加载

```
reload_ecosystem()
        │
        ├── PluginLoader.scan()
        │   └── 遍历 plugins/ 目录
        │       ├── 读取 plugin.yaml → PluginManifest
        │       ├── 验证路径（skills/hooks/ui 是否存在）
        │       └── 发现 skills/ 下的 SKILL.md
        │
        ├── PluginRegistry（启用/禁用状态）
        │   └── backend_data/plugin_state.json
        │
        └── 注册 MCP 工具到 ToolRegistry
```

### 10.2 技能注入

```
Skill → SKILLS_SNAPSHOT.md → system prompt

LLM 看到：
  ## Skills
  ### Available skills
  - research_booster: Use this skill when... (file: /path/to/SKILL.md)
  ### How to use skills
  - 先读取 SKILL.md，再按指示执行
```

---

## 十一、自进化

### 11.1 触发点

```
新建 session
  └── schedule_previous_session_evolution()
        └── 后台总结上一个非空 session

SessionEnd
  └── 当前 session 用户 turn 数距离上次 evolution >= 20
        └── schedule_evolution(trigger="turn_interval")
```

### 11.2 执行链路

```
EvolutionService.run_for_session()
        │
        ├── 构造 EvolutionContext
        │   ├── trigger / session 元数据
        │   ├── checkpoint summary
        │   ├── 上次 evolution 后的消息 + 少量重叠上下文
        │   ├── MEMORY.md / USER.md
        │   ├── 最近 evolution run 摘要
        │   └── skill 列表
        │
        ├── LLM 分析
        │   ├── memory_updates
        │   └── skill_update_requests
        │
        ├── 自动写 MEMORY.md
        │
        ├── 对每个 skill 读取目录文本文件
        │   └── LLM 输出 file_operations
        │
        ├── 保存快照并应用文件操作
        ├── parse / py_compile / reload_ecosystem 验证
        ├── 失败自动回滚
        └── 写入 backend_data/evolution/runs/{run_id}.json
```

自进化不走工具审批，也不让模型直接调用工具改文件。模型只输出结构化计划和文件操作，真正落盘、验证、回滚由后端确定性执行。

---

## 十二、Channels 与飞书入站

### 12.1 飞书 Channel SDK 链路

```
FeishuChannelTransport
        │
        ├── start()
        │   └── 官方 Python Channel SDK 建立长连接
        │
        ├── 收到 message event
        │   ├── _normalize_message()
        │   ├── dedup.try_record(event_id/message_id)
        │   ├── 过滤群聊非 @ 消息
        │   └── _on_message(ChannelMessage)
        │
        └── _send_response()
            └── SDK send(..., reply_to=message_id)
```

`ChannelService.process_transport_message()` 负责把飞书消息接入 Newman Runtime：

- session key 按 `feishu:{app_id}:{chat_id}:{sender_open_id}:{YYYY-MM-DD}` 聚合；
- 同一个飞书 session 正在运行时，新消息会收到“上一个任务还在处理”；
- 飞书入站默认使用 `default_turn_approval_mode=auto_allow`，避免卡在 Newman 页面审批；
- 处理超过短等待阈值时，先回复“已收到，正在处理，完成后回复。”，最终结果再补发；
- 异常时回复统一兜底文案，不把 traceback 暴露给飞书用户。

### 12.2 Channel 状态与事件

```
GET /api/channels/status
GET /api/channels/feishu/setup/status
POST /api/channels/feishu/setup/validate
POST /api/channels/feishu/setup/test
GET /api/channels/events/stream
```

`/api/channels/events/stream` 是外部渠道事件流，供前端感知飞书入站带来的会话变化；普通对话的
turn 级事件仍走 `POST /api/sessions/{session_id}/messages` 返回的 SSE。

---

## 十三、完整时序图

```
用户                  前端                 API                 RunLoop              LLM               工具/沙箱
 │                    │                   │                    │                   │                    │
 │── 发送消息 ───────→│                   │                    │                   │                    │
 │                    │── POST /messages ─→│                    │                   │                    │
 │                    │                   │── handle_message()─→│                   │                    │
 │                    │                   │                    │── 创建 user msg ──→│                    │
 │                    │                   │                    │── SessionStart ───→│                    │
 │                    │                   │                    │── assemble prompt ─→│                    │
 │                    │                   │                    │── provider.chat_stream() ───────────────→│
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │←──── streaming tokens ──────────────────│
 │                    │                   │←── SSE events ─────│                   │                    │
 │←── 实时显示 ───────│                   │                    │                   │                    │
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │←──── response (content + tool_calls) ───│
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │── decide_turn_step()                    │
 │                    │                   │                    │   (有 tool_calls?)  │                    │
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │── 逐个执行工具 ─────────────────────────→│
 │                    │                   │                    │   ├── PreToolUse hook                    │
 │                    │                   │                    │   ├── orchestrator.execute()             │
 │                    │                   │                    │   │   ├── 参数校验                       │
 │                    │                   │                    │   │   ├── 审批策略                       │
 │                    │                   │                    │   │   └── tool.run_streaming() ─────────→│
 │                    │                   │                    │   │                   │←── result ──────│
 │                    │                   │                    │   ├── PostToolUse hook                   │
 │                    │                   │                    │   └── 保存到 session                    │
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │── 回到循环顶部 ────→│                    │
 │                    │                   │                    │── assemble prompt ─→│                    │
 │                    │                   │                    │── provider.chat_stream() ───────────────→│
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │←──── response (无 tool_calls) ───────────│
 │                    │                   │                    │                   │                    │
 │                    │                   │                    │── completion gate/judge                  │
 │                    │                   │                    │   ├── continue → 回到循环顶部             │
 │                    │                   │                    │   └── final                              │
 │                    │                   │                    │── 保存 assistant message                 │
 │                    │                   │←── final_response ──│                    │
 │                    │                   │←── turn_completed ──│                    │
 │                    │                   │                    │── SessionEnd hook ─→│                    │
 │                    │                   │                    │                   │                    │
 │                    │                   │←── stream_completed─│                   │                    │
 │                    │←── SSE complete ──│                    │                   │                    │
 │←── 显示最终回答 ───│                   │                    │                   │                    │
```
