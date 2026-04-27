# User Scheduled Tasks MVP Implementation Breakdown

> 配套文档  
> 对应 PRD：`docs/prds/User_Scheduled_Tasks_MVP_PRD.md`  
> 目标：把 PRD 拆成可执行的后端、前端、API、测试任务清单，并明确建议实施顺序。

---

## 1. 拆解原则

本次实现遵循 3 个原则：

1. 不新造独立执行引擎，继续复用 `NewmanRuntime.handle_message(...)`
2. 先补“运行正确性”，再补“用户体验”
3. 优先让现有 `scheduler` 从“可运行”变成“可对用户负责”

因此整体顺序建议是：

1. 后端执行正确性
2. API 扩展
3. 前端任务页
4. 会话内可见性
5. 测试和验收

---

## 2. 建议实施顺序

### Phase A：后端底座补齐

目标：

- 先保证调度不会双跑、不会审批卡死、不会时区跑偏

包含：

- 时区语义
- 并发互斥
- 失效会话处理
- 轻量 run 记录
- 离线 audit emit

### Phase B：API 能力补齐

目标：

- 让前端有稳定接口可接

包含：

- 编辑任务
- 读取 run 记录
- 列表字段补全
- summary / human schedule

### Phase C：前端任务管理页

目标：

- 提供创建、查看、编辑、启停、删除、立即执行

包含：

- Automations 页面
- 创建/编辑弹窗
- 告警列表
- 会话快捷创建入口

### Phase D：会话融合与验收

目标：

- 让用户能在会话流中看见自动化结果与来源

包含：

- 会话列表打标
- timeline / system meta 展示
- 事件回放验证

---

## 3. 后端任务清单

## 3.1 数据模型扩展

涉及文件：

- `backend/scheduler/models.py`
- `backend/sessions/models.py`

任务：

- 在 `ScheduledTask` 增加字段：
  - `timezone`
  - `description`
  - `last_run_session_id`
  - `last_run_turn_id`
  - `last_success_at`
  - `failure_count`
  - `last_run_outcome`
  - `last_skip_reason`
  - `source`
- 新增 `SchedulerRunRecord`
  - `run_id`
  - `task_id`
  - `trigger_kind`
  - `outcome`
  - `scheduled_for`
  - `started_at`
  - `finished_at`
  - `session_id`
  - `turn_id`
  - `message`
- 扩展 `SessionSummary`
  - `background: bool = False`
  - `scheduled: bool = False`
  - `trigger_type: str | None = None`

完成标准：

- 新增字段可序列化、反序列化
- 旧数据文件缺字段时仍能兼容读取

## 3.2 Run Store

建议新增文件：

- `backend/scheduler/run_store.py`

任务：

- 新增 `SchedulerRunStore`
- 支持：
  - `append(run)`
  - `list_runs(task_id, limit=N)`
  - 裁剪历史记录
- 存储位置：
  - `backend_data/scheduler/runs.json`
  - 或 `backend_data/scheduler/runs.jsonl`

建议：

- MVP 优先用 `json` 数组文件，复用当前 `task_store.py` / `alert_store.py` 风格
- 若担心未来增长，再切 `jsonl`

完成标准：

- 可以查询某个任务最近 N 次运行
- `skipped_conflict` 和 `failed` 都有记录

## 3.3 Cron 与时区

涉及文件：

- `backend/scheduler/cron_parser.py`
- `backend/scheduler/scheduler_engine.py`

任务：

- 调整 cron 解释逻辑，使其按任务 `timezone` 计算
- 对 day-of-week 语义做统一：
  - `0` / `7` = Sunday
  - `1` = Monday
  - ...
  - `6` = Saturday
- 新增输入校验能力：
  - 支持 5 段 cron
  - 支持 `*` / 列表 / 区间 / `*/N`
  - 明确拒绝 `L` / `W` / `?` / 英文别名
- 明确 DST 处理：
  - spring forward 缺失时刻跳过
  - fall back 重复时刻只执行一次

实现建议：

- 不要直接继续用 `datetime.weekday()` 的裸值对外暴露
- 在 parser 层单独做 weekday 映射

完成标准：

- “工作日 9:00”在不同时区下 next run 正确
- parser 单元测试覆盖 weekday 语义

## 3.4 Scheduler 并发与互斥

涉及文件：

- `backend/scheduler/scheduler_engine.py`
- `backend/api/app.py`
- `backend/api/routes/messages.py`

任务：

- 增加 task 级别互斥：
  - 同一 `task_id` 运行中时，新的 cron 命中或 run-now 请求要被拒绝
- 增加 session 级别互斥检查：
  - `session_message` 模式下注入前检查目标 session 是否已有活跃 run
- 结果写入 run 记录：
  - `skipped_conflict`
- 视实现方式复用或查询 `app.state.active_message_runs`

实现建议：

- 不要依赖 `_already_ran_this_minute()` 作为并发保护
- `_already_ran_this_minute()` 只解决一分钟内重复命中，不解决长任务重入

完成标准：

- 同一任务不会双跑
- 正在人工聊天的 session 不会被并发插入自动回合

## 3.5 失效会话处理

涉及文件：

- `backend/scheduler/scheduler_engine.py`

任务：

- `session_message` 模式下，如果 `session_id` 不存在：
  - 本次运行结果记为 `skipped_missing_session` 或 `failed`
  - 任务自动 `disabled`
  - 写 alert
  - 写 run 记录

完成标准：

- 不进入普通瞬时重试
- 用户在任务详情可看见“需重新绑定会话”

## 3.6 无人值守审批快速失败

涉及文件：

- `backend/scheduler/scheduler_engine.py`
- `backend/runtime/run_loop.py`
- `backend/tools/approval.py`
- `backend/tools/approval_policy.py`

任务：

- 在 scheduler 调用 runtime 时传入内部执行标志
  - 例如 `scheduler_run_mode="unattended"`
- 一旦出现 `tool_approval_request`
  - 不进入等待
  - 立即终止本次执行
  - 写 alert / run record
- 确保不会在 `ApprovalManager` 残留 pending request

实现建议：

- 不要改现有对外 `approval_mode` 枚举
- 把差异逻辑限制在 scheduler 路径或 runtime 内部判断

完成标准：

- 需要审批的任务不会卡住
- pending approvals 列表没有悬空条目

## 3.7 离线 Audit Emit

涉及文件：

- `backend/scheduler/scheduler_engine.py`
- `backend/api/sse/event_emitter.py`
- 可视情况新增 `backend/scheduler/offline_emitter.py`

任务：

- 为 scheduler 增加离线事件写入器
- 复用：
  - `build_event_payload(...)`
  - 现有 audit log 格式
- 写入事件：
  - `scheduled_task_triggered`
  - `scheduled_task_completed`
  - `scheduled_task_failed`
  - `scheduled_task_skipped`
  - 以及 runtime 执行过程中原有事件

实现建议：

- 后台会话模式要先创建 session，再写 trigger 事件
- 每次运行要带 `scheduled_run_id`

完成标准：

- 用户事后打开会话时，可在 `/api/sessions/{id}/events` 中看到调度运行痕迹

## 3.8 Session Summary 打标

涉及文件：

- `backend/sessions/models.py`
- `backend/sessions/session_store.py`
- `backend/api/routes/sessions.py`

任务：

- `/api/sessions` 返回摘要中补充：
  - `background`
  - `scheduled`
  - `trigger_type`
- 后台 session 创建时写入 metadata
- `session_message` 模式下，如果会话由定时任务运行过，也可以考虑打 `scheduled=true`

完成标准：

- 前端不需要额外拉详情也能决定是否打“自动化/后台”标签

---

## 4. API 变更清单

## 4.1 修改现有接口

### `GET /api/scheduler/tasks`

新增返回字段：

- `timezone`
- `description`
- `last_run_session_id`
- `last_run_turn_id`
- `last_success_at`
- `failure_count`
- `last_run_outcome`
- `last_skip_reason`
- `source`
- `human_schedule`

### `POST /api/scheduler/tasks`

新增请求字段：

- `timezone`
- `description`
- `source`

新增校验：

- `prompt` 不能为空
- `timezone` 必须是合法 IANA 时区
- `session_message` 模式下 `session_id` 必须存在
- 若绑定 channel session，需要前端显式确认

### `POST /api/scheduler/tasks/{task_id}/run`

新增行为：

- 若任务当前正在运行，返回 `409`
- 若任务绑定会话已失效，返回错误并写 run record

## 4.2 新增接口

### `PATCH /api/scheduler/tasks/{task_id}`

用途：

- 编辑任务

可编辑字段：

- `name`
- `prompt`
- `session_id`
- `cron`
- `timezone`
- `description`
- `max_retries`
- `enabled`

### `GET /api/scheduler/tasks/{task_id}/runs`

用途：

- 获取最近运行记录

查询参数：

- `limit`

返回：

- run record 列表

## 4.3 会话接口变更

### `GET /api/sessions`

摘要项新增：

- `background`
- `scheduled`
- `trigger_type`

### `GET /api/sessions/{session_id}/events`

无需新增接口，但要确保 scheduler 离线执行事件能出现在这里。

---

## 5. 前端任务清单

## 5.1 新增一级页面

涉及文件：

- `frontend/src/App.tsx`
- 建议新增 `frontend/src/pages/AutomationsPage.tsx`
- 建议新增 `frontend/src/pages/automations.css`

任务：

- 左侧导航新增 `Automations`
- 页面内容包括：
  - 顶部说明
  - 新建任务按钮
  - 任务列表
  - 任务详情 Drawer / 弹窗
  - Alerts 区域

完成标准：

- 用户可独立进入定时任务页

## 5.2 任务列表

任务：

- 拉取 `/api/scheduler/tasks`
- 展示字段：
  - 名称
  - 执行方式
  - 绑定会话 / 后台
  - 时区
  - human schedule
  - 下次执行
  - 最近执行
  - 最近状态
  - 最近错误
- 每项支持：
  - 启停
  - 编辑
  - 删除
  - 立即执行

完成标准：

- 列表无须进入详情也能完成日常管理

## 5.3 新建 / 编辑任务弹窗

任务：

- 结构化表单
- 支持模式：
  - 每天
  - 工作日
  - 每周
  - 自定义 cron
- 支持执行方式：
  - 继续某个会话
  - 新建后台会话
- Prompt 必填
- 自定义 cron 高级模式
- channel session 二次确认

建议交互：

- 普通模式优先展示“时间 + 周期”
- 高级模式再暴露 cron 输入框
- 预览生成后的 `human_schedule`

完成标准：

- 不要求用户理解底层 `session_message` / `background_task`

## 5.4 Chat 页快捷创建入口

涉及文件：

- `frontend/src/App.tsx`

任务：

- 在当前会话菜单里增加 `创建定时任务`
- 默认带上：
  - `session_id`
  - 最近一条用户消息作为 prompt 初值
- 跳转方式可选：
  - 打开全局弹窗
  - 切到 Automations 页面并带预填参数

完成标准：

- 用户无需手动复制 session 或 prompt

## 5.5 会话列表打标

涉及文件：

- `frontend/src/App.tsx`

任务：

- 根据 `GET /api/sessions` 的摘要字段给 session row 打标
- 标签示例：
  - `自动化`
  - `后台`

完成标准：

- 用户能快速区分人工会话与调度生成会话

## 5.6 会话内可见性

任务：

- 当回合来自定时任务时，在 timeline / system meta 中展示：
  - `定时任务触发：...`
  - `自动化运行完成`
  - `自动化运行失败：需要人工审批`
- 对 `scheduled_task_skipped` 这类未形成实际回合的事件，不强插空消息气泡

完成标准：

- 用户能理解这不是手工发送的消息

## 5.7 告警与运行记录

任务：

- 告警区拉取 `/api/scheduler/alerts`
- 详情区拉取 `/api/scheduler/tasks/{task_id}/runs`
- 在详情中展示最近几次运行：
  - 成功
  - 失败
  - skipped_conflict
  - skipped_missing_session

完成标准：

- 用户不必翻 audit log 才能看懂最近发生了什么

---

## 6. 测试任务清单

## 6.1 后端单元测试

涉及文件：

- `backend/tests/test_scheduler.py`
- 可新增：
  - `backend/tests/test_scheduler_runs.py`
  - `backend/tests/test_scheduler_timezone.py`

需要覆盖：

- cron weekday 语义
- timezone next_run 计算
- DST 行为
- task 重入冲突
- session busy 冲突
- 失效 session 自动禁用
- 无人值守审批快速失败
- run record 写入
- alert 写入

## 6.2 API 合约测试

涉及文件：

- `backend/tests/test_api_contracts.py`

需要覆盖：

- 创建任务带 timezone
- patch 编辑
- 获取 runs
- run-now 冲突返回 `409`
- `/api/sessions` 摘要新增打标字段

## 6.3 前端验收测试

建议至少覆盖手工联调清单：

1. 从 Automations 页新建后台任务
2. 从当前会话快捷创建“继续当前会话”任务
3. 绑定已删除 session 后触发失败并自动禁用
4. 目标会话忙时触发 `skipped_conflict`
5. task 详情能看到最近运行记录
6. 后台生成的 session 在会话列表有标签

---

## 7. 建议的最小交付批次

## Batch 1：只做后端正确性

交付：

- 模型扩展
- 时区语义
- 并发互斥
- 失效 session 处理
- run store
- 离线 audit emit

结果：

- API 即使还没补 UI，也已经够稳定可用

## Batch 2：补 API 与管理页

交付：

- patch / runs 接口
- Automations 页面
- 任务 CRUD
- alerts + runs 展示

结果：

- 用户可完整管理任务

## Batch 3：补会话融合体验

交付：

- Chat 页快捷创建
- 会话列表打标
- timeline / system meta 识别定时任务

结果：

- 产品体验从“能用”变成“自然”

---

## 8. 当前可立即开工的任务顺序

建议按下面顺序直接排开发：

1. `backend/scheduler/models.py`
2. `backend/scheduler/run_store.py`
3. `backend/scheduler/cron_parser.py`
4. `backend/scheduler/scheduler_engine.py`
5. `backend/api/routes/scheduler.py`
6. `backend/sessions/models.py`
7. `backend/sessions/session_store.py`
8. `backend/tests/test_scheduler.py`
9. `frontend/src/pages/AutomationsPage.tsx`
10. `frontend/src/App.tsx`

这个顺序的好处是：

- 先锁死数据和执行语义
- 再暴露 API
- 最后做 UI，避免前端反复跟着后端返工
