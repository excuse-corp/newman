# User Scheduled Tasks MVP PRD

> Newman 产品 PRD草案  
> 目标：把现有 `scheduler` 底座提升为“用户可创建、可管理、可追踪”的定时任务能力，并尽量复用现有 session / runtime / audit / frontend / channels 体系。

---

## 1. 背景

Newman 当前已经具备一套基础调度能力：

- 后端已有 `backend/scheduler/`，支持 5 段 cron、任务持久化、重试与告警
- 任务可执行两类动作：
  - `session_message`：向已有会话注入一条消息
  - `background_task`：创建一个后台会话并执行
- API 已提供 `/api/scheduler/tasks`、`/api/scheduler/alerts`

但这套能力目前仍偏“系统底座”，主要缺口在产品层：

- 没有面向用户的创建入口和管理页面
- 与现有会话流、审计流、审批流、频道流的融合不完整
- 对“用户任务”最关键的时区、可追踪性、失败可见性定义不足
- 当前调度执行使用 `_noop_emit`，缺少对审计/事件回放的沉淀

因此需要定义一个用户定时任务 MVP，把“能定时跑”变成“用户可以放心用的定时能力”。

---

## 2. 产品目标

MVP 目标：

1. 用户可以创建定时任务，让 Newman 在指定时间自动执行一段 prompt。
2. 定时任务能复用现有会话和后台会话能力，不引入第二套执行引擎。
3. 任务执行结果要能回到现有产品主路径中被看见：
   - 进入已有会话
   - 或生成新的后台会话
   - 并保留事件/审计痕迹
4. 任务失败、任务需要审批、任务被禁用等异常状态要可见、可定位。

一句话定义：

> 用户定时任务 = “长期存在的触发规则” + “每次触发后进入现有 Newman 对话执行链路”。

---

## 3. MVP 范围

### 3.1 包含

- 创建、查看、启用、禁用、删除、立即执行定时任务
- 两种执行模式：
  - 继续某个已有会话
  - 新建后台会话执行
- 时区支持
- 基于 cron 的分钟级调度
- 与现有 Session、Audit、Settings Reload、Channels、Approval 的集成规则
- 前端任务管理页
- 从当前会话快捷创建任务

### 3.2 不包含

- 自然语言自动解析定时表达式
- 秒级调度
- 多步骤工作流编排
- 跨实例分布式调度
- 主动向飞书/企微外发定时消息
- 复杂任务依赖关系、任务 DAG、条件分支

---

## 4. 用户场景

### 场景 A：在当前会话里定时继续

用户在一个“日报会话”里已经调好 prompt，希望 Newman 每个工作日 18:00 自动继续这个会话，生成当天日报。

期望：

- 不创建一堆新会话
- 结果直接出现在原会话里
- 用户打开这个会话就能看到这次自动运行的痕迹和结果

### 场景 B：新建后台会话定时跑

用户希望每天早上 9:00 自动生成“项目巡检摘要”，但不希望污染当前正在使用的聊天会话。

期望：

- 自动创建后台会话
- 在会话列表里能找到这些自动化结果
- 失败时能看到告警

### 场景 C：为 channel 来源会话挂任务

某个会话最初来自飞书/企微 webhook，用户想基于该会话上下文创建定时任务。

MVP 期望：

- 允许绑定该 session 作为目标会话
- 结果先沉淀到 Newman 会话内
- 不承诺主动外发回 IM 平台

---

## 5. 与现有能力的融合原则

### 5.1 与 Runtime 融合

- 定时任务不新增独立执行器
- 仍统一走 `NewmanRuntime.handle_message(...)`
- 调度器只负责“何时触发”和“将什么 prompt 注入哪里”

### 5.2 与 Session 融合

- 已有会话模式：向目标 session 注入一条带调度元数据的 user message
- 后台会话模式：复用现有 `thread_manager.create_or_restore(...)`，创建带 `background: true` 的会话

### 5.3 与 Audit / Event 融合

- 定时任务执行不能再使用纯 `_noop_emit`
- 即使没有前端实时连接，也要写入 audit log，保证后续 `GET /api/sessions/{session_id}/events` 可回看

### 5.4 与 Approval 融合

- 定时任务默认视为“无人值守”
- 任何需要人工审批的工具调用都不能进入等待态
- MVP 里应将其快速标记为失败，并生成明确告警

补充约束：

- `scheduled_unattended` 在 MVP 中定义为**内部调度执行标志**，不是对外暴露的第三种 `approval_mode` API 枚举
- 对外接口仍沿用现有审批模式枚举；scheduler 在运行时额外携带 `scheduler_run_mode = "unattended"` 或等价内部标记
- 这样可以避免改动所有现有消息接口的 `approval_mode` 类型，同时把“无人值守快速失败”限制在 scheduler 执行路径内

### 5.5 与 Channels 融合

- channel 来源会话可作为定时任务目标 session
- 但因为当前 channel 仅支持 webhook 入站，不支持稳定的主动外发，MVP 不做“定时主动发飞书/企微”

---

## 6. 信息架构与入口

### 6.1 前端一级入口

新增左侧导航页：`Automations / 定时任务`

原因：

- 任务具有长期性，不适合藏在 Settings 深层
- 与会话、Memory、Skills、Files 同级更符合使用频率
- 后续可以平滑扩展到提醒、自动化、定期巡检等更宽泛能力

### 6.2 当前会话快捷入口

在 Chat 页面提供“基于当前会话创建定时任务”的快捷动作，建议挂载在以下位置之一：

- 会话顶部工具栏
- 会话菜单
- composer 辅助动作区

MVP 建议：

- 优先在会话菜单增加“创建定时任务”
- 点击后带上当前 `session_id` 进入任务创建弹窗

### 6.3 后台结果入口

后台会话执行模式触发后：

- 自动创建标题形如 `[Scheduled] {task_name}` 的会话
- 会话列表中显示“自动化”或“后台”标识

---

## 7. 用户功能设计

### 7.1 任务类型

对用户暴露两种类型，内部映射到现有 `TaskAction.type`：

1. `继续当前会话`
   - UI 名称：继续某个会话
   - 内部映射：`session_message`
   - 必填：`session_id`

2. `新建后台会话`
   - UI 名称：后台自动运行
   - 内部映射：`background_task`
   - 不要求 `session_id`

UI 不直接暴露 `session_message` / `background_task` 这样的底层术语。

### 7.2 创建任务表单

字段：

- `任务名称`
- `执行方式`
  - 继续某个会话
  - 新建后台会话
- `目标会话`
  - 仅在“继续某个会话”时展示
- `执行 Prompt`
- `时区`
  - 默认取浏览器时区
  - 若浏览器不可用，回退到系统配置默认值
- `调度方式`
  - 每天
  - 工作日
  - 每周
  - 自定义 cron
- `具体时间`
- `最大重试次数`
- `启用状态`

MVP 交互上建议优先提供结构化表单，再由前端生成 cron；保留“高级模式：自定义 cron”。

补充约束：

- `执行 Prompt` 为必填，不允许保存空 prompt 任务
- 从 Chat 页快捷创建时，可以默认预填最近一条用户消息内容，但用户仍需确认后保存
- “自定义 cron” 仅支持当前内置 parser 可覆盖的子集：
  - 5 段 cron
  - `*`
  - 逗号列表
  - 数值区间
  - `*/N` 步进
- MVP 不支持：
  - 秒字段
  - 月份英文别名
  - 星期英文别名
  - `L` / `W` / `?`

### 7.2.1 时区与 cron 语义

为避免用户理解和实现分叉，MVP 固定以下规则：

- 所有任务都必须保存 `timezone`
- `cron` 表达式按任务自己的 `timezone` 解释，而不是服务器本地时区
- 结构化表单生成的“工作日”语义以**用户所在时区的本地工作日**为准
- 高级模式的 day-of-week 语义采用标准用户认知：
  - `0` 或 `7` = Sunday
  - `1` = Monday
  - `2` = Tuesday
  - `3` = Wednesday
  - `4` = Thursday
  - `5` = Friday
  - `6` = Saturday
- 未来实现需补齐当前 parser，使其与上述用户语义一致；不能直接沿用 `datetime.weekday()` 的原始编号暴露给用户

DST 规则：

- 定时任务遵循“所选时区下的 wall-clock time”
- 春令时跳时导致本地时刻不存在时，该次触发跳过，不补跑
- 秋令时回拨导致本地时刻重复时，仅触发一次

### 7.3 任务列表

列表字段：

- 任务名称
- 执行方式
- 绑定会话 / 后台
- 时区
- 下次执行时间
- 最近执行时间
- 最近状态
- 运行次数
- 最近错误摘要
- 启用开关

每项支持：

- 立即执行
- 编辑
- 启用 / 禁用
- 删除

### 7.4 任务详情

MVP 可先用 Drawer 或弹窗展示：

- 原始 prompt
- cron / 结构化调度描述
- 最近一次执行落到哪个 session
- 最近错误
- 创建时间 / 更新时间

---

## 8. 与现有会话流的具体融合

### 8.1 注入到已有会话

任务触发时，调度器向目标 session 注入一条系统生成的 user message。

该消息需写入 metadata：

- `trigger_type = "scheduled_task"`
- `scheduled_task_id`
- `scheduled_run_id`
- `scheduled_task_name`
- `scheduled = true`
- `scheduler_run_mode = "unattended"`

用户在会话中看到的效果：

- 这次运行像一次真实回合
- 但 timeline / system meta 中明确显示“由定时任务触发”

### 8.2 新建后台会话

后台执行时：

- 创建 session 标题：`[Scheduled] {task_name}`
- `session.metadata` 增加：
  - `background = true`
  - `trigger_type = "scheduled_task"`
  - `scheduled_task_id`
  - `scheduled_task_name`

### 8.3 会话列表展示

对后台调度生成的 session，前端在会话列表中显示一个轻量标签：

- `自动化`
- 或 `后台`

避免用户将其与普通人工会话混淆。

这意味着不仅前端要改，后端 `SessionSummary` / `/api/sessions` 也需要补充可直接消费的摘要字段，至少包含：

- `background: bool`
- `scheduled: bool`
- `trigger_type: str | None`

MVP 不要求把完整 `metadata` 全量下发到会话列表，但必须提供足够让前端打标的 summary 字段。

### 8.4 并发与互斥规则

MVP 必须明确以下运行规则，避免自动回合与人工回合互相打架：

1. **同一任务不可并发运行**
- 如果某个 `task_id` 已在执行中，再次命中 cron 或用户点击“立即执行”
- 新触发应直接返回 / 记录为 `skipped_conflict`
- 不创建第二个并发执行实例

2. **继续已有会话模式不可抢占活跃会话**
- 如果目标 session 当前已有活跃消息流或其他定时任务执行中
- 本次触发不应直接插入并发回合
- MVP 规则：本次触发记为 `skipped_conflict`
- 该结果写入 run 记录，并生成一条 `warning` 级 alert

3. **后台会话模式也不允许同一任务重入**
- 即使后台模式每次都会创建新 session，只要同一个任务上一次执行尚未结束
- 新的一次触发仍然记为 `skipped_conflict`
- 不允许因为执行时间长而无限并发扩散

4. **MVP 不做延迟队列 / 自动补跑**
- 因并发冲突被跳过的触发不会自动排队到稍后执行
- 用户如需补跑，可手动点击“立即执行”

该规则的目标是保证系统行为可预测，也与现有前台会话“同一会话已有任务在运行则拒绝并发”的约束保持一致。

### 8.5 失效会话绑定

对于 `继续已有会话` 模式，还需定义目标会话失效后的行为：

- 若绑定的 `session_id` 已不存在
- 本次执行不进入普通重试逻辑
- 系统应：
  - 将任务自动置为 `disabled`
  - 写入 `error` 级 alert
  - 在任务详情中标记“需重新绑定会话”

原因：

- 这是配置错误，不是瞬时执行失败
- 如果继续按普通失败重试，会制造无意义噪音

---

## 9. 与现有 Audit / Event / 回放能力的融合

### 9.1 核心要求

当前 `SchedulerEngine` 直接传 `_noop_emit`，这对系统可运行，但对用户不可用。

MVP 要求：

- 定时任务执行必须生成标准事件流
- 即使没有 SSE 客户端，也要写入现有 audit 文件

### 9.2 设计方式

为 scheduler 增加“离线事件 emit”：

- 不向前端实时推送
- 但复用 `build_event_payload(...)` 和现有 audit 写入格式
- 将事件写到对应 session 的 audit log

补充要求：

- 离线 emit 也要生成 `request_id` 的等价字段或 `scheduled_run_id`
- 保证这次定时触发的事件在 audit 中可以被完整串起来
- 对后台新 session 模式，应先创建 session，再写入 `scheduled_task_triggered` 事件，避免出现“事件存在但 session 不存在”的回放断层

效果：

- 用户之后打开会话时，`/api/sessions/{session_id}/events` 能看到历史触发过程
- 前端无需专门造第二套“任务执行记录”

### 9.3 最低可见事件

MVP 至少保留：

- `commentary_*`
- `tool_call_*`
- `tool_error_feedback`
- `final_response`
- `stream_completed`
- 新增 `scheduled_task_triggered`
- 新增 `scheduled_task_completed`
- 新增 `scheduled_task_failed`
- 可选但推荐新增 `scheduled_task_skipped`

其中 `scheduled_task_skipped` 主要用于表达：

- 会话繁忙
- 任务自身仍在运行
- 绑定 session 已失效

---

## 10. 与 Approval / 权限体系的融合

### 10.1 问题

现有 Newman 支持审批流；但定时任务触发时通常没有用户在线。

如果继续沿用普通手动审批：

- 任务会卡住
- 用户也不会在当下看到审批弹窗

### 10.2 MVP 规则

新增一种内部调度执行语义：`scheduled_unattended`

行为：

- 一旦运行过程中产生 `tool_approval_request`
- 立即终止该次任务
- 任务状态置为 `failed`
- 告警信息明确写成：
  - `scheduled task requires manual approval`
  - 或中文版本 `定时任务触发了需人工审批的工具调用，已自动终止`

实现要求：

- 不扩展 `/api/sessions/{id}/messages` 对外可传的 `approval_mode` 枚举
- 在 scheduler 调用 runtime 时，通过单独的内部标志触发 fail-fast 行为
- 审批请求不进入 `ApprovalManager.wait(...)` 的等待态
- 不在 pending approvals 列表中留下无法处理的悬空审批请求

### 10.3 安全原则

MVP 不做：

- 静默自动批准高风险工具
- 将定时任务和人工审批混跑

这样可以避免“用户设置了定时任务，结果后台自动执行了高风险 terminal / edit 操作”的安全风险。

---

## 11. 与 Channels 的融合

### 11.1 支持什么

- 如果某个 session 本身来自 `feishu` / `wecom`，用户可以把它作为“继续某个会话”的目标
- 执行结果会进入该 Newman session

### 11.2 不支持什么

MVP 不支持：

- 到点后主动推送消息到飞书 / 企微
- 为 channel 直接配置“定时外发任务”

原因：

- 当前 `ChannelService` 仍是“入站 webhook -> Newman -> 标准化响应 payload”模式
- 尚未落地稳定的主动发送链路、鉴权续期和失败补偿

### 11.3 用户感知说明

在任务创建界面中，如果选中的 session 带有 `channel` 元数据，可提示：

> 当前任务会继续写入该 Newman 会话，但不会主动把结果推送回 IM。

MVP 建议把这条提示升级为**显式确认**：

- 用户首次为 channel session 创建任务时，需要勾选
  - `我理解该任务只会写入 Newman，不会自动回推到飞书/企微`
- 未确认前不可保存

---

## 12. 数据模型调整建议

在现有 `ScheduledTask` 基础上建议新增字段：

- `timezone: str`
- `description: str | None`
- `last_run_session_id: str | None`
- `last_run_turn_id: str | None`
- `last_success_at: str | None`
- `failure_count: int = 0`
- `last_run_outcome: Literal["success", "failed", "skipped_conflict", "skipped_missing_session", "approval_blocked"] | None`
- `last_skip_reason: str | None`
- `source: Literal["chat", "automation_page", "api"]`

保留现有字段：

- `task_id`
- `name`
- `cron`
- `action`
- `enabled`
- `max_retries`
- `status`
- `created_at`
- `updated_at`
- `last_run_at`
- `next_run_at`
- `last_error`
- `run_count`

说明：

- 任务规则仍是一条 `ScheduledTask`
- 不引入完整 Job 表作为 MVP 必需项
- 但需要增加**轻量 run 记录**
- 执行历史以 `session + audit + run_record` 共同承载

### 12.1 轻量 Run 记录

为支撑任务详情页、冲突跳过和失败定位，MVP 建议增加 `SchedulerRunRecord`：

- `run_id`
- `task_id`
- `trigger_kind`：`cron` / `manual_run`
- `outcome`
- `scheduled_for`
- `started_at`
- `finished_at`
- `session_id`
- `turn_id`
- `message`

持久化方式：

- 可使用 `backend_data/scheduler/runs.json` 或 `runs.jsonl`
- 按总量裁剪，例如仅保留最近 1000 条

这样既不引入完整任务队列表，也能支撑：

- 任务详情里的“最近几次运行”
- `skipped_conflict` 这类并非失败、但对用户仍然重要的结果可见性

---

## 13. API 调整建议

基于现有 `/api/scheduler` 扩展：

### 保留

- `GET /api/scheduler/tasks`
- `GET /api/scheduler/alerts`
- `POST /api/scheduler/tasks`
- `POST /api/scheduler/tasks/{task_id}/enable`
- `POST /api/scheduler/tasks/{task_id}/disable`
- `POST /api/scheduler/tasks/{task_id}/run`
- `DELETE /api/scheduler/tasks/{task_id}`

### 新增

- `PATCH /api/scheduler/tasks/{task_id}`
  - 编辑名称、prompt、session_id、timezone、cron、max_retries、enabled
- `GET /api/scheduler/tasks/{task_id}/runs`
  - 返回该任务最近 N 次 run record

### 返回字段调整

任务列表建议补充：

- `timezone`
- `last_run_session_id`
- `last_run_turn_id`
- `last_success_at`
- `failure_count`
- `last_run_outcome`
- `human_schedule`

这样前端无需重复做太多 schedule 解释逻辑。

创建 / 编辑阶段必须增加的校验：

- `cron` 语法必须在当前支持子集内
- `timezone` 必须是合法 IANA 时区
- `session_message` 模式下，`session_id` 必须存在
- 若 `session_id` 绑定的是 channel 会话，需要额外确认“不自动外发”

立即执行接口规则：

- 如果任务当前正在运行，应返回 `409`
- 不允许同一任务通过“立即执行”绕过互斥规则

---

## 14. 前端 MVP 设计

### 14.1 页面

新增一级页面：`Automations`

页面结构：

- 顶部：说明 + 新建任务按钮
- 中部：任务列表
- 右侧或弹窗：任务创建 / 编辑表单
- 底部或次级区域：失败告警列表

### 14.2 与现有导航融合

当前前端已有：

- Chat
- Memory
- Skills
- Files
- Settings

MVP 建议新增：

- `Automations`

这样比塞进 Settings 更直接，也与 “长期资产型功能” 的定位一致。

### 14.3 Chat 页快捷操作

在当前会话菜单中增加：

- `创建定时任务`

默认预填：

- 任务类型：继续当前会话
- 目标会话：当前 session
- prompt：默认带上最近一次用户输入，但用户必须确认后保存

### 14.4 会话内呈现

当某次回合来自定时任务时，在现有 timeline / system meta 区域展示一条轻量说明：

- `定时任务触发：工作日 18:00`
- `自动化运行完成`
- `自动化运行失败：需要人工审批`

尽量复用现有 `system_meta` 风格，避免再造一种特殊气泡。

若本次触发因并发冲突被跳过，不在会话正文中强插一条空回合；该信息只出现在：

- 任务详情最近运行记录
- Alerts 列表
- 或会话事件回放中

---

## 15. 成功指标

MVP 发布后，判定成功的最低标准：

1. 用户可以在前端创建并管理定时任务，无需手工写 JSON。
2. 继续会话模式和后台会话模式都能稳定工作。
3. 用户可在原会话或新后台会话中看到结果。
4. 失败任务可在任务页看到，并能定位最近错误。
5. 遇到审批时任务会失败而不是卡死。
6. 服务重启 / config reload 后，任务仍可继续调度。

---

## 16. 验收标准

### 功能验收

- 可创建每天/工作日/每周/自定义 cron 任务
- 可编辑、启用、禁用、删除、立即执行
- 支持绑定已有 session
- 支持新建后台 session
- 任务列表能展示 next run / last run / 状态 / 错误
- 高级 cron 模式的 weekday 语义与用户文档一致

### 融合验收

- 定时触发进入现有 `runtime.handle_message`
- 触发后结果进入现有 session message 存储
- 事件写入现有 audit log
- `/api/sessions/{session_id}/events` 能回放定时任务产生的事件
- channel 来源 session 可被绑定，但不发生主动外发
- 会话列表能识别并标记后台自动化 session

### 异常验收

- 工具审批请求会被快速终止并告警
- runtime 报错会进入 alerts
- cron / timezone 非法配置会在创建或编辑阶段被拒绝
- 绑定 session 不存在时，任务会自动禁用并要求重新绑定
- 同一任务或同一会话并发冲突时，本次触发会记为 `skipped_conflict`，不会静默双跑

---

## 17. 工程实现建议

优先复用：

- `backend/scheduler/task_store.py`
- `backend/scheduler/scheduler_engine.py`
- `backend/api/routes/scheduler.py`
- `backend/runtime/run_loop.py`
- `backend/api/routes/sessions.py`
- `backend/api/sse/event_emitter.py`
- `frontend/src/App.tsx`

建议新增或调整：

- `backend/scheduler/models.py`
  - 补充 timezone / last_run_session_id 等字段
- `backend/scheduler/scheduler_engine.py`
  - 增加离线 audit emit
  - 增加 approval fail-fast
  - 增加 timezone-aware 匹配
  - 增加 task-level mutex / session-level busy check
- `backend/scheduler/`
  - 视实现方式新增 `run_store.py`
- `backend/api/routes/scheduler.py`
  - 增加 patch/update 能力
- `backend/sessions/models.py`
  - 扩展 `SessionSummary`，支持前端打标
- `frontend/src/pages/`
  - 新增 `AutomationsPage.tsx`
- `frontend/src/App.tsx`
  - 导航加入口
  - 增加会话快捷创建入口

---

## 18. 明确不做但要留接口的后续方向

### P1

- 自然语言创建任务
- 任务模板
- 主动推送飞书/企微
- 任务结果摘要卡片

### P2

- 任务执行历史页
- 任务依赖与工作流编排
- 多实例调度锁
- 任务幂等键与更细粒度补偿

---

## 19. 结论

这次 MVP 的关键不是再做一个更复杂的 scheduler，而是把现有 scheduler 接入 Newman 已有主链路：

- 对用户而言，任务不是一个孤立的后台进程，而是“会自动发生的 Newman 回合”
- 对系统而言，调度器只解决“何时触发”，真正执行继续复用现有 runtime / session / audit / tools / permissions 体系

这样能以最小增量把定时任务做成一个对用户真正可用、对工程侧也可维护的能力。
