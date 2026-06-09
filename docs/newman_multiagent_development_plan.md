# Newman Multiagent 开发计划

来源：`docs/newman_multiagent_design.md`
日期：2026-06-01

## 1. 计划目标

把 `multiagent` 从设计方案落成可迭代开发任务。P0 的交付物是：主 Agent 可以通过 `multiagent` 同步创建一个 `MultiAgentRun`，调度 1 到 N 个 fresh subagent，复用现有工具审批、沙箱、路径权限和审计链路，前端可以在右侧抽屉观察 run/task 状态，任何异常路径都返回 schema 合法的 `MultiAgentReport`。

本计划默认不做 `background`、`fork context`、subagent 点对点通信、长期 teammate、独立 worktree 和 patch 合并 UI。

## 2. 当前代码落点

| 领域 | 现有落点 | 开发影响 |
| --- | --- | --- |
| 主运行循环 | `backend/runtime/run_loop.py` | 只保留 `multiagent` 接入与可复用 helper；核心逻辑放到 `backend/subagents/` |
| 工具注册 | `backend/tools/discovery.py`、`backend/tools/registry.py` | 新增 `backend/tools/impl/multiagent.py`；需要给工具注入 manager/runtime 能力 |
| 工具执行 | `backend/tools/router.py`、`backend/tools/orchestrator.py` | subagent runner 复用路由、审批、sandbox、静态路径检查 |
| 权限 | `backend/tools/permission_context.py`、`backend/tools/workspace_fs.py` | 扩展为 subagent 工具白名单和 skill 目录强隔离，而不只靠 prompt |
| 会话 | `backend/sessions/models.py`、`backend/sessions/session_store.py` | child session 写入 metadata，并从主列表默认过滤 |
| SSE/API | `backend/api/sse/event_types.py`、`backend/api/routes/sessions.py` | 新增 multiagent 事件类型与 run/task 查询接口 |
| 前端 | `frontend/src/App.tsx`、`frontend/src/styles.css` | 在聊天页增加右侧抽屉，消费 multiagent 事件和查询接口 |
| 测试 | `backend/tests/*` | 增加 subagents 单测、API contract、run loop 集成、权限与锁测试 |

## 3. 分阶段交付

### Phase 0：接口契约与配置基线

预估：1-2 工作日

交付：

- 新增 `backend/subagents/` 包骨架。
- 在 `backend/config/schema.py` 增加 `SubagentsConfig`，至少包含：
  - `enabled`
  - `max_agents_per_run`
  - `default_max_turns`
  - `lock_wait_timeout_seconds`
  - `sequential_context_token_limit`
- 在 `backend/config/defaults.yaml` 写入默认值。
- 定义 P0 状态、事件和报告 schema，先不接真实执行。

验收：

- 配置加载测试覆盖默认值与项目配置覆盖。
- `event_types.py` 中有 multiagent 事件枚举。
- schema 单测可以验证降级报告字段完整。

### Phase 1：核心模型、Store、报告兜底

预估：2 工作日

文件：

- `backend/subagents/models.py`
- `backend/subagents/store.py`
- `backend/subagents/report.py`
- `backend/subagents/events.py`

交付：

- 实现 `MultiAgentRun`、`SubagentTask`、`ToolPolicySnapshot`、`AgentReport`、`MultiAgentReport`、`FileOverlap`、`FileConflict`。
- 实现轻量 JSON store，路径建议为 `backend_data/subagents/runs/{run_id}.json`。
- 实现报告抽取：
  - 优先解析 JSON code block 或显式报告块。
  - 失败后允许 runner 发起一次修复调用。
  - 二次失败构造 `degraded=True` 的合法报告。
- 实现聚合器：根据 task 终态合成 run 状态、failed_agents、overlap/conflict、usage。

验收：

- `report_invalid`、`timed_out`、`cancelled`、`failed` 均能生成合法 `AgentReport`。
- 多 task 聚合时，部分成功部分失败得到 `partial`。
- `task_id` 是所有查询、事件、transcript_ref 的稳定主键。

### Phase 2：multiagent Tool 接入与启动校验

预估：2-3 工作日

文件：

- `backend/tools/impl/multiagent.py`
- `backend/subagents/manager.py`
- `backend/tools/discovery.py`
- `backend/runtime/run_loop.py`

交付：

- 新增 `multiagent` 工具 schema，支持设计稿 P0 入参。
- 调整 `BuiltinToolContext`，让 `multiagent` 工具能拿到 `MultiAgentManager`。
- `NewmanRuntime.__init__` 初始化 `self.subagent_manager`，`reload_ecosystem()` 注册工具时传入。
- `MultiAgentManager` 完成启动前校验：
  - mode/run_mode/return_strategy/context_policy。
  - agent 数量、name 唯一、`2 <= max_turns <= default_max_turns`，默认 `max_turns=200`。
  - 工具存在性校验。
  - 全局 denylist：`multiagent`、`request_user_input`。
  - 计算 allowed/denied tools 和 skills，固化 `ToolPolicySnapshot`。
- 校验失败直接返回 `failed MultiAgentReport`，不创建 child session。

验收：

- 主 Agent 可看到 `multiagent`，subagent 不可看到 `multiagent`。
- 非法入参不抛异常，返回结构化失败报告。
- Plan mode 下仍遵循现有工具可用性规则。

### Phase 3：child session 与 SubagentRunner 最小闭环

预估：3-4 工作日

文件：

- `backend/subagents/runner.py`
- `backend/runtime/run_loop.py`
- `backend/sessions/session_store.py`
- `backend/sessions/models.py`

交付：

- 每个 subagent 创建 child session：
  - `metadata.subagent=true`
  - `parent_session_id`
  - `parent_turn_id`
  - `multiagent_run_id`
  - `subagent_task_id`
  - `agent_name`
- `SessionStore.list()` 默认过滤 child session。
- runner fresh context：
  - 构建 subagent system prompt。
  - 写入 assignment prompt。
  - 调用 provider。
  - 按 `max_turns - 1` 执行，最后一轮强制 wrap-up 且禁用工具。
- 先实现 no-tool final report，再接工具调用。

验收：

- 单 agent、无工具调用能完整返回 `completed AgentReport`。
- `transcript_ref=session://{child_session_id}` 可查询对应 session。
- 删除主 session 时 child session 一并清理或归档。

### Phase 4：工具调用复用、审批、权限与审计

预估：4-5 工作日

文件：

- `backend/subagents/runner.py`
- `backend/subagents/locks.py`
- `backend/tools/orchestrator.py`
- `backend/tools/router.py`
- `backend/tools/permission_context.py`

交付：

- runner 复用 `ToolRouter.static_checks()` 和 `ToolOrchestrator.execute()`。
- subagent provider tools 只渲染 allowed_tools 白名单。
- `approval_mode: inherit | auto_allow | manual` 映射到现有 `TurnApprovalMode`。
- 所有 subagent 工具事件写入 child session，并桥接为 parent turn 的 multiagent SSE。
- 实现 `FileLockManager`：
  - `write_file` / `edit_file` 单文件锁。
  - 多路径按字典序获取。
  - terminal 可识别写路径时锁目标路径；不可识别 mutating terminal 时锁 workspace mutation。
  - 锁等待超时生成 `FileConflict(reason="lock_timeout")`。
- 在 `finally` 中释放 held_locks，并回收 terminal 子进程记录。

验收：

- manual + parallel 时多个审批请求可以并存，拒绝单个工具调用不影响其他 task。
- 同一路径并发写入被串行化或变成 `FileConflict`，不会死锁。
- 成功串行写同一文件生成 `FileOverlap`。
- 不暴露 token budget、task timeout、run timeout；usage 只用于审计、报告和前端展示，不作为硬停止条件。

### Phase 5：parallel/sequential Manager 编排

预估：2 工作日

文件：

- `backend/subagents/manager.py`
- `backend/subagents/store.py`

交付：

- `parallel`：按配置并发上限调度，`wait_all` 聚合所有终态。
- `sequential`：A 完成后机械拼接前序 `summary` 和截断 findings 到 B 的 assignment prompt。
- 支持按 `run_id` 或 `task_id` cancel：
  - 安全边界生效。
  - 资源回收。
  - task/run 终态与报告一致。

验收：

- parallel 中一个 task 失败不会中止其他 task。
- sequential 的后续 prompt 可看到前序 summary。
- cancel 单 task 不影响其他 task；cancel run 终止所有运行中 task。

### Phase 6：API/SSE 与前端右侧抽屉

预估：4-5 工作日

后端文件：

- `backend/api/routes/subagents.py`
- `backend/api/app.py`
- `backend/api/sse/event_types.py`

前端文件：

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- 可选拆分：`frontend/src/chat/MultiagentDrawer.tsx`

后端交付：

- 新增查询接口：
  - `GET /api/sessions/{session_id}/multiagent-runs?turn_id=...`
  - `GET /api/multiagent/runs/{run_id}`
  - `GET /api/multiagent/tasks/{task_id}`
  - `POST /api/multiagent/runs/{run_id}/cancel`
  - `POST /api/multiagent/tasks/{task_id}/cancel`
- SSE 新增事件建议：
  - `multiagent_run_started`
  - `multiagent_run_updated`
  - `multiagent_task_started`
  - `multiagent_task_updated`
  - `multiagent_tool_event`
  - `multiagent_approval_queued`
  - `multiagent_run_completed`

前端交付：

- 聊天页右侧抽屉按 parent turn 展示 run 列表。
- run 详情展示 status、mode、usage、failed_agents、file_overlaps、file_conflicts。
- task 详情展示 current_activity、timeline、terminal output、file changes、usage、final report。
- 降级报告明确展示 `degraded_reason`。
- manual + parallel 审批队列显示来源 task_id/name，复用现有 approve/reject API。

验收：

- 刷新页面后可以从 API 还原历史 run/task。
- 实时运行时可以通过 SSE 更新抽屉状态。
- child session 不出现在主会话列表，但 transcript 可从 task 详情打开。

### Phase 7：测试、回归与文档收口

预估：3-4 工作日

测试范围：

- `backend/tests/test_subagents_models.py`
- `backend/tests/test_subagents_report.py`
- `backend/tests/test_subagents_locks.py`
- `backend/tests/test_multiagent_tool.py`
- `backend/tests/test_subagent_runner.py`
- `backend/tests/test_multiagent_api.py`
- 扩展 `backend/tests/test_run_loop.py`
- 扩展 `backend/tests/test_api_contracts.py`
- 前端建议补充组件级测试或最少手工验收脚本。

必须覆盖：

- 启动前校验失败。
- 单 agent 成功。
- parallel 部分失败得到 `partial`。
- sequential 前序 summary 注入。
- max_turns wrap-up。
- 报告解析失败并降级。
- cancel task / cancel run。
- 同路径并发写锁等待超时。
- subagent 不可调用 `multiagent` / `request_user_input`。
- 未授权 skill 目录不可读。
- child session 不出现在普通 session list。

## 4. 建议开发顺序

1. 先合入 Phase 0-1，建立 schema、store、report 兜底和测试基线。
2. 再合入 Phase 2，让 `multiagent` 工具可以完成参数校验并返回结构化失败/空运行报告。
3. 然后做 Phase 3 的 no-tool runner，拿到最小端到端闭环。
4. 在 Phase 4 接工具执行、审批、usage 记录和锁，这是 P0 风险最高的部分，拆小 PR。
5. Phase 5 完成并发/串行 manager 编排。
6. Phase 6 做 API/SSE 和前端抽屉；前端可以先用后端 mock run 数据开发。
7. Phase 7 做异常路径补齐、回归、文档更新。

## 5. 关键工程风险

1. `run_loop.py` 已经承担大量职责，subagent 执行循环如果直接复制会迅速膨胀。建议先抽出可复用 helper 或让 runner 显式依赖 runtime 的窄接口。
2. 现有 `PermissionContext` 只有 deny_rules，无法表达 readable/writable roots 或 skill 目录隔离。P0 要把 skill 隔离放到 policy 层，否则安全边界不成立。
3. terminal 子进程 pid 当前不直接暴露给 orchestrator。若 P0 必须精确回收 terminal_pids，需要扩展 sandbox/terminal result metadata。
4. manual + parallel 会放大审批事件数量。后端事件必须包含 `run_id`、`task_id`、`agent_name`，前端才能正确聚合。
5. 当前 session list 未过滤 `metadata.subagent`，需要同步更新 API 和前端假设，避免 child session 污染主列表。

## 6. P0 完成定义

- `multiagent` 工具可被主 Agent 调用，并返回 schema 合法的 `MultiAgentReport`。
- 一个 run 可同步执行多个 fresh subagent，支持 parallel/sequential。
- 每个 subagent 有 child session、task 状态、工具权限快照、usage、工具日志和最终报告。
- allowed_tools/allowed_skills 强制生效，subagent 不能递归调用 `multiagent`。
- 读写、terminal、审批、sandbox、路径权限沿用 Newman 现有链路。
- 并发写同一路径不会同时发生；冲突和 overlap 进入报告。
- cancel、max_turns、报告解析失败均产出降级报告；锁等待超时进入 `FileConflict`。
- 前端右侧抽屉可实时查看 run/task，并可刷新恢复。
- 后端单测和 API contract 覆盖主要正常/异常路径。
