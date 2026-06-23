# 多代理设计

这份文档描述 Newman 当前代码中的多代理实现，用于补齐 README 里的原有链接。

当前没有独立于实现之外的旧版多代理设计文档；本页以现有代码和接口为准。

## 入口形态

多代理当前以一个内置工具暴露：

- 工具名：`multiagent`
- 实现文件：`backend/tools/impl/multiagent.py`

主 Agent 负责：

- 拆任务
- 指定每个 subagent 的 `prompt`
- 指定 `allowed_tools`
- 汇总最终结论

subagent 负责：

- 在受限工具集下执行明确子任务
- 返回结构化 `MultiAgentReport`

## 当前支持的调用约束

`multiagent` 工具 schema 当前收得比较紧，重点约束如下：

- `mode`
  - `parallel`
  - `sequential`
- `run_mode`
  - 目前只支持 `sync`
- `return_strategy`
  - 目前只支持 `wait_all`
- `context_policy`
  - 目前只支持 `fresh`
- `working_scope`
  - 目前只支持 `shared_workspace`

每个 agent 至少要提供：

- `name`
- `prompt`
- `allowed_tools`

可选项包括：

- `agent_type`
- `description`
- `allowed_skills`
- `approval_mode`
- `model`
- `max_turns`

## 运行时关系

每个 subagent 会创建独立 child session，并带上父任务关联元数据，例如：

- `subagent = true`
- `parent_session_id`
- `parent_turn_id`
- `multiagent_run_id`
- `subagent_task_id`
- `agent_name`

这些 child session 默认不进入普通主会话列表，但仍用于审计、排障和 transcript 追踪。

## 当前 REST 接口

### Session 维度

- `GET /api/sessions/{session_id}/multiagent-runs`
  - 查看某个父 session 关联的 multiagent run 列表

### Run / Task 维度

- `GET /api/multiagent/runs/{run_id}`
- `GET /api/multiagent/tasks/{task_id}`
- `POST /api/multiagent/runs/{run_id}/cancel`
- `POST /api/multiagent/tasks/{task_id}/cancel`

## 关键实现文件

- `backend/tools/impl/multiagent.py`
  - 工具 schema 与调用入口
- `backend/subagents/manager.py`
  - run / task 编排与状态管理
- `backend/subagents/runner.py`
  - 单个 subagent 的执行循环
- `backend/subagents/models.py`
  - 数据模型
- `backend/subagents/store.py`
  - 持久化
- `backend/api/routes/subagents.py`
  - 多代理 REST 接口

## 当前边界

当前实现更适合“清晰、可并行、边界明确”的子任务，不适合：

- 模糊探索后再即时改计划的长链协商
- 需要跨 agent 高频共享上下文的协作
- 依赖未授权工具或超出 `allowed_tools` 的执行

如果需要更完整的系统运行链路，可结合阅读：

- [newman_flow.md](newman_flow.md)
- [Newman_API_v1.md](Newman_API_v1.md)
