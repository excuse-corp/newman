# Newman Multiagent / Subagent 设计方案

日期：2026-05-31
修订：2026-06-01（补充异常路径、并发安全、生命周期与一致性约束）

## 1. 目标

Newman 需要支持主 Agent 将任务委派给一个或多个临时 subagent 执行。工具名固定为 `multiagent`。

核心目标：

1. 主 Agent 保留工作流规划和编排权。
2. `multiagent` 每次调用创建一个 `MultiAgentRun`。
3. 一个 `MultiAgentRun` 可以包含一个或多个临时 `SubagentTask`。
4. Subagent 拥有独立 child session、任务状态、工具权限、执行日志和最终报告。
5. Subagent 可以读文件、写文件、编辑文件和使用终端，但必须复用 Newman 现有审批、沙箱、路径权限和审计链路。
6. 前端右侧抽屉可以实时看到 multiagent run 和每个 subagent 的运行状态。
7. MVP 不做 subagent 之间自由通信，也不允许 subagent 递归调用 `multiagent`。
8. MVP 不允许多个 subagent 在同一时间写同一个文件；检测到并发写入同一路径时，后到的写入进入等待或被阻断，由主 Agent 决定重试或改派。
9. 所有正常路径和异常路径（max_turns 耗尽、报告解析失败、取消、锁等待）都必须有明确定义，保证返回给主 Agent 的 `AgentReport` / `MultiAgentReport` 始终是 schema 合法的结构化数据，绝不抛异常中断整个 run。

典型工作流：

```text
主 Agent 规划
  -> multiagent 启动 subagent x
  <- x report 返回主 Agent

主 Agent 基于 x 结果继续规划
  -> multiagent 启动 subagent y
  <- y report 返回主 Agent

主 Agent 基于 x/y 结果继续规划
  -> multiagent 并行启动 subagent m 和 n
  <- m/n reports 聚合返回主 Agent

主 Agent 汇总并完成用户任务
```

## 2. 核心原则

1. Subagent 是任务执行单元，不是长期在线自治成员。
2. 主 Agent 是唯一编排者。
3. `multiagent` 是统一任务调度入口，不直接承载所有运行逻辑。
4. 每个 subagent 必须有明确任务 ID、child session、工具权限快照和 transcript。
5. 默认采用 fresh context，不继承主会话完整上下文。
6. 主 Agent 必须在 subagent prompt 中写清背景、目标、范围、约束和输出格式。
7. Subagent 结果和完整 transcript 分离：结果给主 Agent 消费，transcript 用于审计和 UI 查看。
8. 所有工具调用都必须经过 Newman 的 tool policy、approval policy、sandbox 和 path permission。
9. P0 不支持递归 subagent、subagent 点对点通信、fork context 和长期 teammate。
10. `multiagent` 是执行工具，不是计划工具；它可以执行计划中的某一步，但不拥有、不自动修改主会话 plan。
11. **失败安全（fail-safe）优先于功能完整**：任何异常都必须收敛为一个合法的降级报告，而不是异常或卡死。run 的资源（锁、子进程）必须在任何退出路径上都被释放/回收。
12. **task_id 是唯一稳定主键**：所有跨 run 引用（transcript、SSE、审计、API、UI 选中态）一律以 `task_id` 为准。`name` 仅用于人类可读展示，作用域限单 run 内唯一。

## 3. 总体架构

```text
Main RunLoop
  -> multiagent tool
      -> MultiAgentManager
          -> MultiAgentRun
              -> SubagentTask A
              -> SubagentTask B
              -> SubagentTask C
          -> SubagentRunner
              -> child session
              -> provider loop
              -> Newman ToolRegistry / ToolRouter / ToolOrchestrator
              -> ApprovalPolicy / Sandbox / PathPermission
          -> FileLockManager        # per-file / workspace 写锁，全局有序获取
  <- MultiAgentReport
```

建议新增模块：

```text
backend/subagents/
  models.py          # MultiAgentRun / SubagentTask / AgentReport 等模型
  store.py           # run/task 持久化
  manager.py         # 创建、取消、查询 run/task
  runner.py          # 单个 subagent 执行循环
  events.py          # SSE payload 规范
  definitions.py     # 可选 Agent Definition / template
  locks.py           # FileLockManager：全局有序文件写锁与 workspace mutation lock
  report.py          # AgentReport 抽取与降级兜底
```

`backend/runtime/run_loop.py` 只保留接入点，不承载 multiagent 的核心业务逻辑。

## 4. Agent Definition 与临时 Agent Instance

Subagent 是临时创建的运行实例，但系统可以提供可选的 Agent Definition。

两者区别：

| 概念 | 含义 |
| --- | --- |
| Agent Definition | 可选模板，描述默认 prompt、工具权限、模型、max turns、适用场景，可包含 `denied_tools` / `denied_skills` |
| Agent Instance | 每次 `multiagent` 调用临时创建的实际运行对象 |

Newman 不要求用户提前注册 agent。主 Agent 可以直接创建临时 agent：

```json
{
  "agents": [
    {
      "name": "runtime-reader",
      "prompt": "分析 backend/runtime/run_loop.py 的工具调用链。",
      "allowed_tools": ["read_file", "search_files"]
    }
  ]
}
```

也可以引用模板：

```json
{
  "agents": [
    {
      "agent_type": "coder",
      "name": "implementation-checker",
      "prompt": "检查 multiagent runner 的实现方案。",
      "allowed_tools": ["read_file", "edit_file", "terminal"]
    }
  ]
}
```

模板只是默认配置来源，最终执行的仍是本次临时 agent instance。

**`denied_tools` / `denied_skills` 的来源**（澄清，见 §6.2 字段）：

1. MVP 入参不直接接受 `denied_tools` / `denied_skills`，主 Agent 通过 `allowed_tools` / `allowed_skills` 做正向授权即可。
2. `SubagentTask.denied_tools` / `denied_skills` 由系统在启动校验阶段填充，来源有三：
   - Agent Definition 模板中声明的默认禁用项；
   - Newman 全局 denylist（如始终禁止 `multiagent`、`request_user_input`）；
   - 由 `allowed_*` 反向计算出的"未授权即禁用"的显式记录，用于审计可读性。
3. 即模型层只需提供 `allowed_*`，`denied_*` 是系统对最终生效策略的固化快照，写入 `ToolPolicySnapshot` 供审计。

## 5. multiagent Tool 设计

工具名：

```text
multiagent
```

MVP 入参：

```json
{
  "mode": "parallel",
  "run_mode": "sync",
  "return_strategy": "wait_all",
  "context_policy": "fresh",
  "agents": [
    {
      "name": "runtime-reader",
      "description": "分析运行循环接入点",
      "prompt": "请分析 backend/runtime/run_loop.py 和 backend/tools 相关模块，找出 multiagent 接入点、风险和建议输出格式。",
      "allowed_tools": ["read_file", "search_files", "terminal"],
      "approval_mode": "inherit",
      "max_turns": 200,
      "working_scope": "shared_workspace"
    },
    {
      "name": "frontend-planner",
      "description": "设计右侧抽屉",
      "prompt": "请检查 frontend 目录结构，设计 multiagent 右侧抽屉的数据流和组件方案。",
      "allowed_tools": ["read_file", "search_files"],
      "approval_mode": "inherit",
      "working_scope": "shared_workspace"
    }
  ]
}
```

字段说明：

| 字段 | MVP 取值 | 说明 |
| --- | --- | --- |
| `mode` | `parallel` / `sequential` | 本次 run 内多个 agent 的执行方式 |
| `run_mode` | `sync` | 同步等待结果；后续扩展 `background` |
| `return_strategy` | `wait_all` | 等所有 agent 到终态后返回 |
| `context_policy` | `fresh` | fresh subagent，不继承主上下文 |
| `agents` | array | 本次临时创建的 subagent 列表 |
| `allowed_tools` | array | 当前 agent 的工具白名单 |
| `approval_mode` | `inherit` / `auto_allow` / `manual` | 当前 agent 的工具审批模式，默认继承主会话本 turn 的审批模式 |
| `max_turns` | integer，可选，默认 200 | 当前 agent 最大模型/工具循环轮数（含强制收尾轮，见 §8.3）。最小 2，最大不超过 Newman 配置的 `subagents.default_max_turns` |
| `working_scope` | `shared_workspace` | MVP 直接操作当前工作区 |

默认约束：

1. `agents` 可包含 1 到 N 个 agent。
2. `agents[].name` 在单个 run 内必须唯一。
3. `allowed_tools` 必须显式给出或由 Agent Definition 展开。
4. Subagent 默认不可见 `multiagent` 工具。
5. Subagent 默认不暴露 `request_user_input`，除非后续明确设计等待人工输入能力。
6. `allowed_tools` 决定 subagent 是否具备某个工具能力；`approval_mode` 只决定执行该工具前是否需要人工确认。
7. `approval_mode` 默认 `inherit`，即继承 Newman 当前 turn 的审批模式；如果主会话是自动通过，subagent 也自动通过；如果主会话是手动确认，subagent 也手动确认。
8. `max_turns` 中必须为强制收尾轮预留至少 1 轮（见 §8.3），即有效任务轮数为 `max_turns - 1`。未显式设置时默认 200。
9. 并发 agent 数量上限建议 MVP 设为可配置上限（如 4），避免模型调用与审批弹窗放大。

## 6. 数据模型

### 6.1 MultiAgentRun

```python
class MultiAgentRun:
    run_id: str
    parent_session_id: str
    parent_turn_id: str
    mode: Literal["parallel", "sequential"]
    run_mode: Literal["sync", "background"]
    return_strategy: Literal["wait_all"]
    context_policy: Literal["fresh", "fork"]
    status: Literal[
        "pending",
        "running",
        "waiting_file_lock",
        "waiting_approval",
        "completed",
        "partial",          # 部分 agent 成功、部分失败/取消
        "failed",
        "cancelled",
        "timed_out",
    ]
    task_ids: list[str]
    usage_summary: "UsageSummary"
    started_at: str
    completed_at: str | None
    result: "MultiAgentReport | None"
    error: str | None
```

### 6.2 SubagentTask

```python
class SubagentTask:
    task_id: str                       # 唯一稳定主键，跨 run 引用一律用它
    run_id: str
    parent_session_id: str
    parent_turn_id: str
    child_session_id: str
    name: str                          # 仅人类可读，单 run 内唯一
    agent_type: str | None
    description: str
    assignment_prompt: str
    status: Literal[
        "pending",
        "running",
        "waiting_file_lock",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "report_invalid",              # 执行结束但报告抽取失败的降级终态
    ]
    allowed_tools: list[str]
    denied_tools: list[str]            # 系统填充，来源见 §4
    allowed_skills: list[str]
    denied_skills: list[str]           # 系统填充，来源见 §4
    tool_policy_snapshot: "ToolPolicySnapshot"
    approval_mode: Literal["inherit", "auto_allow", "manual"]
    model: str | None
    max_turns: int
    current_activity: str | None
    progress: "SubagentProgress"
    pending_messages: list["SubagentMessage"]
    file_changes: list["FileChange"]
    held_locks: list[str]              # 当前持有的文件/workspace 锁，cancel/结束时据此释放
    terminal_commands: list["TerminalCommand"]
    terminal_pids: list[int]           # 运行中子进程，cancel/结束时回收
    usage_summary: "UsageSummary"
    result: "AgentReport | None"       # 任何终态都保证非 None（含降级报告）
    error: str | None
    started_at: str | None
    completed_at: str | None
```

### 6.3 ToolPolicySnapshot

```python
class ToolPolicySnapshot:
    allowed_tools: list[str]
    denied_tools: list[str]
    allowed_skills: list[str]
    denied_skills: list[str]
    readable_roots: list[str]
    writable_roots: list[str]
    protected_roots: list[str]
    sandbox_mode: str
    approval_mode: str
    permission_context: dict[str, object]
```

启动时保存快照，避免后续配置变化影响审计。

### 6.4 AgentReport

```python
class AgentReport:
    task_id: str
    name: str
    status: Literal["completed", "failed", "cancelled", "timed_out", "report_invalid"]
    summary: str
    findings: list["Finding"]
    files_changed: list["FileChange"]
    commands_run: list["TerminalCommand"]
    artifacts: list["Artifact"]
    risks: list[str]
    recommended_next_steps: list[str]
    transcript_ref: str
    usage_summary: "UsageSummary"
    degraded: bool                      # True 表示该报告是兜底/降级生成，非模型结构化输出
    degraded_reason: str | None         # 如 "max_turns_exhausted" / "parse_failed" / "cancelled" / "timed_out"
```

### 6.5 MultiAgentReport

```python
class MultiAgentReport:
    run_id: str
    status: str
    summary: str
    agent_reports: list[AgentReport]
    failed_agents: list[str]            # 存 task_id
    file_overlaps: list["FileOverlap"]  # 同一文件被多个 task 先后写（非冲突，仅需主 Agent 关注）
    file_conflicts: list["FileConflict"]# 真正的冲突（如锁等待超时被阻断的写入）
    usage_summary: "UsageSummary"
    recommended_next_steps: list[str]
```

### 6.6 FileOverlap / FileConflict（统一术语）

文档此前混用 `FileConflict` 与 `FileOverlap`，现明确区分：

```python
class FileOverlap:
    """同一文件在一个 run 内被多个 subagent 先后（非并发）修改。
    属于正常但需主 Agent 关注的情况，不计为失败。"""
    path: str
    writers: list["FileWriteRecord"]    # 按时间排序的写入记录

class FileConflict:
    """真正的冲突：并发写同一路径且无法串行化，
    或锁等待超时导致某次写入被阻断/失败。"""
    path: str
    blocked_task_id: str
    holding_task_id: str | None
    reason: Literal["lock_timeout", "blocked", "concurrent_mutation"]
    detected_at: str

class FileWriteRecord:
    task_id: str
    tool: Literal["write_file", "edit_file", "terminal"]
    at: str
```

判定原则：成功串行化的多次写入 → `FileOverlap`；因锁等待超时或无法串行而被阻断/失败的写入 → `FileConflict`。主 Agent 据 `file_overlaps` 决定是否复查，据 `file_conflicts` 决定是否重试或改派。

## 7. Skill / Tool 暴露策略

每个 subagent 只能看到 Newman 当前 tools 和 skills 的子集。

Tools：

1. `allowed_tools` 是工具能力白名单。
2. `denied_tools` 是系统填充的额外禁用列表（来源见 §4）。
3. Newman 全局禁用规则始终优先，例如 MVP 禁止 subagent 看到 `multiagent`。
4. provider tools 只渲染过滤后的 schema。

Skills：

1. `allowed_skills` 是 skill 白名单。
2. `denied_skills` 是系统填充的额外禁用列表。
3. Subagent stable context 中只渲染过滤后的 skills snapshot。
4. **未授权 skill 的隔离必须是强制的，不能只靠 prompt 约定。** 即使 subagent 拥有 `read_file` 能力，也必须在 tool policy / path permission 层拦截对未授权 `SKILL.md`（及其目录）的读取，使其落在 `readable_roots` 之外或显式列入受保护路径。仅在 prompt 中"建议不要读"是不可靠的安全边界。

工具能力和审批模式是两层概念：

```text
allowed_tools / allowed_skills = 这个 subagent 有没有能力使用
approval_mode = 使用能力时是否需要人工确认
```

`approval_mode` 默认 `inherit`，继承主会话当前 turn 的审批模式。即主会话是自动通过，则 subagent 也是自动通过；主会话是手动确认，则 subagent 也需要手动确认。无论是否自动通过，sandbox、path permission、protected roots 和工具白名单都不能被绕过。

## 8. 运行流程

### 8.1 启动前校验

`multiagent` 接收请求后：

1. 校验 `mode`、`run_mode`、`return_strategy`、`context_policy`。
2. 校验各 agent 的 `max_turns`（≥2，需为收尾轮留 1，默认和上限均为 `subagents.default_max_turns`，默认值 200）。
3. 校验 agent 数量（≤ 并发上限）和名称唯一性。
4. 展开可选 Agent Definition。
5. 计算每个 agent 的工具集合，并反算 `denied_tools` / `denied_skills`。
6. 应用全局 denylist，例如禁止 `multiagent` 递归、禁止 `request_user_input`。
7. 校验工具是否存在。
8. 生成 `ToolPolicySnapshot`。
9. 创建 `MultiAgentRun` 和 `SubagentTask` 记录。

校验失败时直接返回 `failed` 的 `MultiAgentReport`，不创建任何 child session。

### 8.2 创建 child session

每个 subagent 创建独立 child session：

```text
SessionRecord.metadata:
  subagent: true
  parent_session_id: ...
  parent_turn_id: ...
  multiagent_run_id: ...
  subagent_task_id: ...
  agent_name: ...
```

child session 用于保存完整 transcript，主会话只接收最终 `AgentReport`。

**生命周期与可见性：**

1. 带 `subagent: true` 的 child session **默认从用户主 session 列表过滤**，不污染主列表。
2. `transcript_ref` 格式约定为 `session://{child_session_id}`，前端抽屉与审计据此定位完整 transcript。
3. child session 与主 session 同生命周期归档；用户删除主 session 时，其下所有 child session 一并归档/清理。
4. child session 不可被主 Agent 直接续写，仅供只读查看与审计。

### 8.3 执行循环

`SubagentRunner` 驱动单个 subagent：

1. 构建 subagent system prompt。
2. 写入 assignment prompt 作为初始 user message。
3. 根据 `allowed_tools` 过滤 provider tools。
4. 调用 provider（每轮前检查取消请求，并记录 usage）。
5. 如果模型请求工具：
   - 经 `ToolRouter` 路由。
   - 经 `ToolOrchestrator` 执行。
   - 复用 approval、sandbox、path permission。
   - 写类工具按 §9.1 获取文件锁。
   - 工具结果写入 child session。
   - 更新 task progress、task logs、file changes、terminal commands、held_locks、terminal_pids、usage。
6. 正常结束条件：模型给出最终回答，或达到 `max_turns - 1` 后进入强制收尾轮。
7. **报告产出（关键，覆盖所有路径）：**
   - **正常结束**：从最终 assistant message 抽取 `AgentReport`。
   - **`max_turns` 即将耗尽**（已用至 `max_turns - 1`）：强制追加一轮收尾调用，prompt 固定为"基于已有进展，按 AgentReport 格式输出最终报告，不要再调用工具"，并在该轮禁用所有工具 schema。该收尾轮占用预留的最后 1 轮。
   - **抽取失败 / schema 不合法**：见 §8.5 报告兜底，构造 `degraded=True` 的降级报告，task 状态置为 `report_invalid`，**不抛异常**。
   - **取消**：构造对应 `degraded` 报告（见 §13.2），保留 partial 的 file_changes 与 commands_run。
8. 更新 task 状态和 run 状态。在任何退出路径上，runner 必须在 `finally` 中释放该 task 的 `held_locks` 并回收 `terminal_pids`（见 §8.6）。

### 8.4 文件锁等待

1. MVP 不暴露 run/task wall-clock timeout，也不使用 token budget 截断 subagent。
2. 写类工具仍受 `lock_wait_timeout_seconds` 保护；等待文件锁超时会生成 `FileConflict(reason="lock_timeout")`，但不作为 subagent 任务的通用 timeout。
3. 正在运行的 terminal 子进程在取消或 runner 中止时按 §8.6 回收。

### 8.5 报告抽取与兜底

从 assistant 自由文本抽取结构化 `AgentReport` 必然有失败率，必须有确定性兜底：

1. 优先解析模型输出的结构化报告块（约定用明确分隔标记或 JSON code block）。
2. 解析失败时，**重试至多 1 次**：追加一条提示"上次输出无法解析为 AgentReport，请仅输出合法报告"，且该修复轮不调用工具。
3. 二次仍失败：构造降级报告
   ```text
   AgentReport(
     status="report_invalid",
     summary=<最后一条 assistant 文本截断至 N 字>,
     findings=[], risks=["报告未能结构化，需主 Agent 查看 transcript"],
     recommended_next_steps=["查看 transcript_ref 人工判断"],
     transcript_ref="session://...",
     degraded=True, degraded_reason="parse_failed",
   )
   ```
   task 置 `report_invalid`（视为非成功但非崩溃终态）。
4. 兜底报告绝不抛异常，绝不中断同 run 内其他 agent，也不阻塞 `wait_all` 聚合。

### 8.6 取消 / 中止时的资源回收

任何导致 task 提前结束的路径（用户 cancel、致命错误）都走统一回收：

1. 触发 runner abort（在安全边界生效，见 §13.2）。
2. **释放锁**：强制释放该 task `held_locks` 中的所有文件锁与 workspace mutation lock，唤醒 `waiting_file_lock` 的其他 task。
3. **回收子进程**：对 `terminal_pids` 中未结束的进程先 `SIGTERM`，宽限后 `SIGKILL`，记录最终 exit 状态到对应 `TerminalCommand`。
4. **保留 partial**：已发生的 `FileChange`、`TerminalCommand` 照常记录并进入报告。
5. 产出对应 `degraded` 报告并推送 SSE、写审计。

### 8.7 parallel 与 sequential

`parallel`：

```text
同时启动 A/B/C（受并发上限约束）
写操作经 FileLockManager 全局有序获取锁（见 §9.1）
等待所有 task 到终态（含降级终态）
聚合 MultiAgentReport
返回主 Agent
```

`sequential`：

```text
启动 A
拿到 A report（含降级报告）
由 MultiAgentManager 机械地将 A report 的 summary（及可选 findings 摘要）拼接进 B 的 assignment prompt
启动 B
重复直到结束
聚合 MultiAgentReport
返回主 Agent
```

**重要澄清**：本次 run 为 `run_mode: sync`，主 Agent 此刻阻塞在工具调用中，无法介入。因此 sequential 的上下文注入由 `MultiAgentManager` **机械拼接**完成，不存在主 Agent 的智能判断：

1. 注入内容默认仅为前序 agent 的 `summary`；若配置允许，可附加截断后的 `findings`，总长度受上限约束（如 ≤ 2K tokens）。
2. 这不是 A 与 B 直接通信，A 只把结果交还 Newman。
3. 若需主 Agent 的智能判断来决定下一步，应改用**多次 `multiagent` 调用串联**（见 §11），而非单次 run 内的 sequential。

MVP 中，主 Agent 更常通过多次 `multiagent` 调用串联复杂工作流。`sequential` 只适合同一次 run 内非常明确、无需智能判断的流水线。

## 9. 写文件与终端策略

Subagent 可以使用：

```text
read_file
read_file_range
list_dir
search_files
write_file
edit_file
terminal
fetch_url
google_search
```

但必须满足：

1. 工具必须出现在当前 agent 的 `allowed_tools` 中。
2. 工具审批模式默认继承主会话当前 turn 的审批模式。
3. 当主会话是自动通过时，subagent 默认自动通过；当主会话是手动确认时，subagent 默认手动确认。
4. 即使自动通过，`terminal` 仍不能绕过 Newman 的 sandbox、path permission、protected roots 和全局安全策略。
5. 高风险终端命令在手动确认模式下继续走 Newman 现有审批链路。
6. 写文件和编辑文件必须记录 `FileChange`。
7. 终端命令必须记录 `TerminalCommand`（含 pid 与 exit code）。
8. MVP 不允许多个 subagent 同一时间写同一个文件。
9. 多个 subagent 先后修改同一文件时记录 `FileOverlap`；因锁等待超时被阻断的写入记录 `FileConflict`（术语区分见 §6.6）。
10. 所有工具调用事件必须进入 task log 和 SSE。
11. **读类工具的可见范围受 `readable_roots` 约束**：`list_dir`、`search_files` 的遍历结果必须按 `readable_roots` 裁剪，落在范围外的目录/文件不可见。fresh context 的隔离意义不能被全工作区遍历绕过。

### 9.1 同一文件并发写入（全局有序锁，避免死锁）

MVP 采用 per-file write lock，并通过**全局有序获取**避免死锁：

1. 当 subagent 准备执行 `write_file` 或 `edit_file` 时，根据 `path` 向 `FileLockManager` 获取文件级写锁。
2. 同一时刻只有一个 subagent 可以写同一路径。
3. **单次工具调用只允许持有单一文件锁。** 一次 `write_file` / `edit_file` 只锁其目标路径，工具返回即释放，不跨工具调用持锁。这从结构上消除了"持 A 求 B"的循环等待。
4. 若某操作确需同时锁定多个路径（如批量写），必须按路径**字典序**一次性排序获取全部锁，全部成功才执行，任一失败则释放已获取的锁并退避重试。字典序保证全局获取顺序一致，不会死锁。
5. 若另一个 subagent 同时请求写同一路径，状态进入 `waiting_file_lock`；等待超过 `lock_wait_timeout_seconds`（默认 30s）则返回**可恢复错误**，记录 `FileConflict(reason="lock_timeout")`，由主 Agent 决定重试或改派。
6. `terminal` 若被识别为会写某路径，也尝试获取对应文件锁（单锁规则同上）。
7. `terminal` 若是 mutating 但无法识别具体路径，则获取 **workspace mutation lock**（全局唯一），避免与其他写操作交叉；该锁同样有等待超时。
8. 写锁释放后，后续 subagent 可继续写同一文件，但必须记录该文件已被其他 agent 修改过（`FileOverlap`）。
9. **死锁/活锁防护**：因 §9.1.3 的单锁规则与 §9.1.4 的字典序规则，系统不会进入循环等待；等待超时进一步保证不会无限活锁。

这意味着：

```text
允许多个 subagent 在同一个 run 内先后修改同一文件   -> FileOverlap
不允许多个 subagent 在同一时间并发写同一文件         -> 串行化或 FileConflict
循环等待被结构性消除（单锁 + 字典序 + 超时）
```

最终 `MultiAgentReport` 需要列出 `file_overlaps` 与 `file_conflicts`，由主 Agent 判断是否需要检查、回滚或补测。

MVP 使用 `shared_workspace`：

```text
subagent 直接按 Newman 当前路径权限读写工作区
读遍历受 readable_roots 裁剪，写受 writable_roots / protected_roots 约束
```

后续扩展：

```text
scratch_dir      # 写入 backend_data/agent_runs/{task_id}
git_worktree     # 每个 coder agent 独立 worktree
patch_mode       # subagent 只产出 patch，由主 Agent 合并
```

## 10. multiagent 与 update_plan 的关系

`multiagent` 和 `update_plan` 是不同层级的工具。

```text
update_plan = 主 Agent 的计划展示工具
multiagent = 主 Agent 的任务执行工具
```

`update_plan`：

1. 更新主 session metadata 中的 checklist。
2. 面向用户展示主 Agent 的执行计划。
3. 不创建 subagent。
4. 不执行任务。
5. 不并发。

`multiagent`：

1. 创建 `MultiAgentRun`。
2. 创建一个或多个 `SubagentTask`。
3. 真实执行模型和工具循环。
4. 返回结构化报告。
5. 产生 child sessions、task logs、usage、文件变更和终端记录。

二者关系：

1. 主 Agent 可以先用 `update_plan` 给用户展示计划。
2. 主 Agent 可以用 `multiagent` 执行计划中的某一步或多步。
3. `multiagent` 不自动修改 plan。
4. `multiagent` 返回后，主 Agent 可以再调用 `update_plan` 标记步骤完成或调整后续计划。
5. Plan mode 下，`multiagent` 和其他执行工具一样，应在计划存在后才能使用。

## 11. 多 Agent 通信

MVP 采用主控式通信：

```text
主 Agent -> multiagent -> Subagent A/B/C
Subagent A/B/C -> AgentReport -> 主 Agent
主 Agent 决定下一步
```

不支持：

```text
Subagent A <-> Subagent B
Subagent A -> multiagent -> Subagent C
```

原因：

1. 权限和责任链更清晰。
2. token 和工具调用更容易归因。
3. transcript 和审计更稳定。
4. 避免递归和无限扩散。

如果 x 的结果要给 y：

1. x report 返回主 Agent。
2. 主 Agent 在下一次 `multiagent` 调用中将 x 的关键结论写入 y 的 prompt。
3. y 作为新的临时 subagent 执行。

（注意区分：单次 run 内的 sequential 注入是机械拼接，见 §8.7；跨 run 的串联才有主 Agent 的智能判断。）

## 12. 前端右侧抽屉

右侧抽屉按 `parent_turn_id` 展示多个 `MultiAgentRun`。所有选中态、引用均以 `task_id` 为主键，`name` 仅作展示。

示例：

```text
Multiagent Runs
  Run 1: x
    x completed

  Run 2: y
    y running

  Run 3: m+n
    m waiting_approval
    n completed
```

选中 run 展示：

1. run 状态（含 `partial` / `timed_out`）。
2. mode / run_mode / return_strategy。
3. agents 列表。
4. 聚合结果。
5. 失败 agent。
6. 文件 overlap 与 conflict（分区展示）。
7. 累计 usage，供审计、报告和前端展示。

选中 agent 展示：

1. child session transcript（经 `transcript_ref` 加载）。
2. 当前活动。
3. 工具调用 timeline。
4. terminal stdout/stderr。
5. 文件变更。
6. usage summary。
7. final report（含 `degraded` 标记，降级报告需明显标注原因）。

### 12.1 manual + parallel 的审批聚合

`approval_mode: manual` 与 `mode: parallel` 同时存在时，多个 subagent 可能同时触发审批，是高频真实场景。MVP 审批呈现规则：

1. 审批以**队列**形式聚合在抽屉的统一审批区，每条标注来源 `task_id` / `name` 与待执行工具摘要。
2. 支持逐条批准/拒绝；MVP 可选支持"全部批准"，但**不提供"全部拒绝即终止 run"**之外的批量副作用。
3. 单个 subagent 的审批被拒绝：该工具调用按"被拒"返回给该 subagent（其可调整策略或结束），**不影响**其他并行 subagent。
4. 等待审批的 task 状态为 `waiting_approval`；审批自身仍沿用 Newman 工具审批超时。
5. 审批弹窗数量受并发上限约束，避免一次涌出过多。

## 13. 任务输出、停止与补充消息

### 13.1 输出查询

前端和后续工具可以通过 `task_id` 查询：

1. 当前状态。
2. 最终结果。
3. transcript 引用。
4. 工具调用和文件变更。

MVP 前端通过 API 查询，不一定暴露模型工具。

### 13.2 停止任务

取消流程：

1. 用户或系统请求 cancel（按 `task_id`，或对整个 `run_id`）。
2. `MultiAgentManager` 找到运行中 task。
3. 在安全边界触发 runner abort（当前模型调用结束后或工具调用边界后，不在流式响应中间硬中断）。
4. 走 §8.6 统一资源回收：释放该 task 所有 `held_locks`、回收 `terminal_pids`、保留 partial `FileChange` / `TerminalCommand`。
5. 状态变为 `cancelled`，产出 `degraded` 报告（`degraded_reason="cancelled"`）。
6. 推送 SSE。
7. 写入审计日志。

取消单个 task 不影响同 run 内其他 task；取消整个 run 则对所有运行中 task 重复上述流程，run 置 `cancelled` 或 `partial`（若已有成功 agent）。

### 13.3 补充消息

MVP 不做运行中任意 SendMessage，但数据模型预留：

```python
pending_messages: list[SubagentMessage]
```

后续如果支持补充消息，读取点必须是安全边界：

1. 当前模型调用结束后。
2. 工具调用边界后。
3. 下一轮 provider 调用前。

不能在模型流式响应中间硬插入状态。

## 14. Usage 与审计

每次 subagent LLM 调用都要进入现有 usage recorder，并实时累加进 task/run 的 `UsageSummary`。

建议 metadata：

```text
request_kind: subagent_turn
multiagent_run_id
subagent_task_id
agent_name
parent_session_id
child_session_id
parent_turn_id
tool_schema_count
is_wrapup_turn        # 是否为 max_turns 收尾轮
```

工具调用审计：

1. 工具名。
2. 参数摘要。
3. success / failure。
4. duration。
5. approval 信息（批准人/拒绝/超时）。
6. sandbox 信息。
7. 文件变更。
8. terminal 命令、pid 和 exit code。
9. 锁获取/释放/等待超时事件。

**配额与停止条件（P0 最低实现）：**

1. P0 不暴露 token budget、run timeout 或 task timeout 给 `multiagent`。
2. Subagent 停止条件以 `max_turns`、模型正常完成、报告解析兜底、取消和致命错误为主。
3. usage 只进入审计、报告和前端展示，不作为硬停止条件。

## 15. MVP 范围

P0 / MVP 应实现：

1. `multiagent` tool。
2. 一次调用创建一个 `MultiAgentRun`。
3. 一个 run 可包含 1 到 N 个临时 subagent（受并发上限约束）。
4. 支持 `mode: parallel | sequential`。
5. 支持 `run_mode: sync`。
6. 支持 `return_strategy: wait_all`。
7. 只支持 `context_policy: fresh`。
8. 每个 subagent 有独立 child session，默认从主列表过滤，与主 session 同生命周期。
9. 每个 subagent 使用 `allowed_tools` 和 `allowed_skills` 控制工具与 skill 能力；未授权 skill 在 path/tool policy 层强制隔离。
10. subagent 审批模式默认继承主会话当前 turn 的审批模式；manual + parallel 走审批队列聚合。
11. 支持读文件、写文件、编辑文件和 terminal；读遍历受 readable_roots 裁剪。
12. 复用 Newman 现有审批、沙箱、路径权限。
13. 禁止 subagent 递归调用 `multiagent`。
14. 使用 per-file write lock + 全局有序获取（单锁 / 字典序）+ 等待超时，结构性避免死锁，MVP 不允许多个 subagent 同一时间写同一文件。
15. 记录 tool policy snapshot、usage、task logs、file changes、terminal commands、锁事件。
16. 前端右侧抽屉展示 run 和 task 状态（含 partial / cancelled / report_invalid）。
17. 最终返回结构化 `MultiAgentReport`，任何异常路径都收敛为合法的降级报告。
18. **异常路径完整覆盖**：max_turns 收尾轮、报告解析兜底、取消、锁等待超时，各自有确定性的降级报告或冲突记录与资源回收。
19. **统一术语 `FileOverlap` vs `FileConflict`** 与对应 schema。

P0 暂缓：

1. fork subagent。
2. background return strategy。
3. subagent 点对点通信。
4. agent teams / swarm。
5. 运行中任意 SendMessage。
6. 自动恢复已停止 agent。
7. 独立 git worktree。
8. patch 合并 UI。
9. 复杂的并发多文件事务（MVP 仅支持单锁 + 字典序批量锁）。

## 16. 后续扩展方向

1. `run_mode: background`：启动后立即返回 run id，完成后通过通知进入主会话。
2. `return_strategy: first_success`：适合搜索和方案探索。
3. `context_policy: fork`：继承主上下文做并行分支探索。
4. `scratch_dir` / `git_worktree`：隔离写入，从根本上消除写锁竞争。
5. `mailbox`：subagent 之间受控通信。
6. `swarm`：长期 teammate 或团队模式。
7. Agent Definition 管理 UI。
8. 更精细的 tool budget / per-tool token budget。
9. 文件冲突解决和 patch review。
10. 审批策略可视化配置（如对特定工具默认 auto_allow）。

## 17. 一句话总结

Newman 的 `multiagent` 应设计为主 Agent 可重复调用的任务调度工具：每次调用创建一个可观测、可审计、可并发的 `MultiAgentRun`，其中每个 subagent 都是临时、隔离、受工具权限约束的任务执行单元；正常与异常路径都被明确定义，任何退出都会释放资源并收敛为 schema 合法的结构化报告；结果通过结构化报告返回主 Agent，完整 transcript 和工具过程保留给前端右侧抽屉和审计系统。
