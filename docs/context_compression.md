# Newman 上下文压缩与上下文占用说明

本文档描述 Newman 当前已经落地的上下文占用统计、自动压缩、手动压缩和 checkpoint 恢复行为。

这不是未来方案草稿，而是实现对齐文档。若本文与代码冲突，以以下实现为准：

- `backend/memory/compressor.py`
- `backend/runtime/run_loop.py`
- `backend/runtime/prompt_assembler.py`
- `backend/api/routes/sessions.py`

---

## 1. 目标

当前实现同时服务三件事：

- 给前端返回稳定、可解释的 `context_usage`
- 在主模型请求发出前，基于“下一次 prompt 预计有多大”执行预检
- 在不删除完整 transcript 的前提下，把旧上下文压缩成可继续工作的 handoff summary

---

## 2. `context_usage` 的核心口径

### 2.1 三个预算字段

当前预算由 `build_context_compaction_budget()` 统一计算：

```text
effective_context_window = model.context_window * 95%
auto_compact_limit = effective_context_window
soft_compact_limit = auto_compact_limit * runtime.context_compress_threshold
```

默认值：

- `EFFECTIVE_CONTEXT_WINDOW_PERCENT = 95`
- `runtime.context_compress_threshold = 0.85`

说明：

- `effective_context_window` 是当前所有压力值的统一分母
- `auto_compact_limit` 目前等于 `effective_context_window`，保留这个字段名是为了兼容前端和 API
- `soft_compact_limit` 是提前启动压缩的软阈值

例如：

```text
configured context_window = 200000
effective_context_window = 190000
auto_compact_limit = 190000
soft_compact_limit = 161500
```

### 2.2 `confirmed_*` 字段

`confirmed_*` 代表最近一次真实主模型请求里“已经确认发生”的 prompt 占用。

来源：

- `usage_store.latest_context_record(session_id)`

筛选条件：

- `counts_toward_context_window = true`
- `usage_available = true`
- 按 `created_at DESC` 取最新一条

当前只取：

- `input_tokens` 作为 `confirmed_prompt_tokens`
- `request_kind` 作为 `confirmed_request_kind`
- `created_at` 作为 `confirmed_recorded_at`

不把 `output_tokens` 混进 `confirmed_prompt_tokens`。

对应压力值：

```text
confirmed_pressure = confirmed_prompt_tokens / effective_context_window
```

### 2.3 `projected_*` 字段

`projected_*` 代表“如果现在立刻再发一次主模型请求”，运行时预计这次 prompt 会有多大。

它先计算完整组装 prompt 的估算值：

```text
assembled_estimate = estimate_tokens(assembled_messages)
```

然后在存在最近一次真实 usage 记录时，尝试再算一条“确认值 + 增量”的保守估算：

```text
incremental_projection =
  confirmed_prompt_tokens
  + estimate_tokens(delta_messages_since_latest_record)
```

最终规则不是二选一，而是“优先取更安全的较大值”：

- 默认 `projected_next_prompt_tokens = assembled_estimate`
- 只有当 `incremental_projection >= assembled_estimate` 时，才切换为 `confirmed_plus_delta`

因此当前实现可以理解为：

```text
projected_next_prompt_tokens = max(assembled_estimate, confirmed_plus_delta_if_valid)
```

只是 `projection_source` 只会返回两种值：

- `assembled_prompt_estimate`
- `confirmed_plus_delta`

### 2.4 `confirmed_plus_delta` 何时可用

只有最近 usage 记录没有被上下文重写“打断”时，才会使用增量账本。

当前实现里的失效条件只有两类：

1. 最新 checkpoint 创建时间晚于最近 usage 记录，且该 checkpoint 仍处于激活状态
2. `last_microcompact_at` 晚于最近 usage 记录

注意：

- 旧文档里提过 `stable context` 或 `tools_overview` 变化会直接使锚点失效，但当前代码没有单独维护这类失效标记
- 这类变化仍会被 `assembled_prompt_estimate` 路径覆盖，所以不会低估，只是通常不会命中 `confirmed_plus_delta`

### 2.5 `delta_messages` 当前包含什么

在 `confirmed_plus_delta` 路径里，增量估算会包含：

- 最近 usage 记录之后新增的会话消息
- 如果 checkpoint 比该 usage 更新，且当前没有 restore 消息，还会把 `## Checkpoint Summary` 作为一条额外 system 注入估算

### 2.6 其他返回字段

`ContextUsageSnapshot.to_dict()` 当前会返回：

- `effective_context_window`
- `auto_compact_limit`
- `soft_compact_limit`
- `confirmed_prompt_tokens`
- `confirmed_pressure`
- `confirmed_request_kind`
- `confirmed_recorded_at`
- `projected_next_prompt_tokens`
- `projected_pressure`
- `budget_pressure`
- `projection_source`
- `projected_over_soft_limit`
- `projected_over_limit`
- `compaction_stage`
- `compaction_fail_streak`
- `context_irreducible`
- `last_compaction_failure_reason`

其中：

```text
projected_pressure = projected_next_prompt_tokens / effective_context_window
budget_pressure = projected_next_prompt_tokens / auto_compact_limit
```

前端圆环应以 `budget_pressure` 为主。

---

## 3. `assembled_messages` 的真实组成

`projected_next_prompt_tokens` 不是只看 `session.messages`。

在正常运行时，`GET /api/sessions/{id}` 和 RunLoop 预检都会尽量复用 `PromptAssembler`，因此估算基于真实 prompt 组装结果，通常包含：

1. commentary / tool-action / user-input 三段系统护栏
2. stable context
3. collaboration mode prompt
4. workflow state prompt（如果存在）
5. checkpoint summary（仅在 checkpoint 激活且尚未 restore 时注入）
6. 当前对模型可见的会话消息

其中第 6 项不是完整 transcript，而是：

```text
model_visible_session_messages(session, checkpoint)
```

也就是从 checkpoint 已归档前缀之后开始的消息。

如果某些轻量 API 场景下没有可用的 `prompt_assembler`，接口会退回到较简单的估算方式：

- 可选 checkpoint summary
- `model_visible_session_messages`

---

## 4. 自动压缩的触发时机

自动压缩检查发生在“每一次主模型请求发出之前”的预检阶段，而不是只在用户新发消息时检查一次。

当前已经接入的典型入口包括：

- 新用户消息进入后的主回合请求前
- 工具调用之后的续写请求前
- 达到工具上限后的收口回答前
- 致命工具失败后的收口回答前

RunLoop 中统一入口是：

- `RunLoop._maybe_checkpoint()`

---

## 5. 自动压缩的当前执行链路

单次预检里的逻辑如下：

1. 组装当前将要发送的 prompt
2. 计算 `context_usage`
3. 如果 `projected_next_prompt_tokens < soft_compact_limit`：
   - 重置失败状态
   - 直接继续本次主模型请求
4. 否则先执行一次 `microcompact_session()`
5. 重新估算；若已低于软线：
   - 重置失败状态
   - 继续本次主模型请求
6. 若仍不低于软线，则执行一次 `summarize_messages()`
7. 生成或刷新 checkpoint，重新估算
8. 若压缩后仍高于 `auto_compact_limit`：
   - 记录一次失败
   - 由失败计数和 irreducible 状态决定是否继续

重要实现细节：

- 单次 `_maybe_checkpoint()` 只会执行一轮 `microcompact -> checkpoint compact`
- 当前实现不会在同一次预检里无限循环压缩到过线以下
- “压缩动作成功返回”不等于“预算已经降到硬线以内”

---

## 6. 软线、硬线与“是否立刻阻断”

这里最容易和旧设计稿混淆。

### 6.1 软线

当 `projected_next_prompt_tokens >= soft_compact_limit` 时：

- 当前实现会尝试压缩
- 但如果没有可压缩内容，且仍未到硬线，可以直接继续，不会报错

### 6.2 硬线

当 `projected_next_prompt_tokens >= auto_compact_limit` 时，表示已经超过 Newman 当前定义的运行时安全预算。

但当前实现不是“只要还高于硬线就立刻终止本次请求”。

当前真实行为是：

1. 如果预检一开始就高于硬线，且 session 已标记为 `context_irreducible`，直接阻断
2. 如果预检一开始就高于硬线，且 `compaction_fail_streak >= runtime.context_compaction_max_failures`，会把本次状态升级为 irreducible 并阻断
3. 如果本轮压缩后仍高于硬线，会记录失败原因 `post_compaction_still_over_limit`
4. 只有当失败次数累计到阈值，或者命中 `nothing_to_compress` 这类不可恢复场景，后续预检才会真正阻断并收口为 `context_irreducible`

默认阈值：

- `runtime.context_compaction_max_failures = 3`

因此应把当前 `auto_compact_limit` 理解为：

- Newman 的运行时安全预算线
- 不是 provider 的绝对物理 context hard limit

---

## 7. 失败状态与 `context_irreducible`

当前 session 会维护以下状态：

- `compaction_fail_streak`
- `context_irreducible`
- `last_compaction_failure_reason`
- `last_compaction_stage`

失败计数在以下场景会增长：

1. 预检已高于硬线，且已经达到最大失败次数：
   - `reason = "max_failures_reached"`
2. 已高于硬线，但没有任何可归档内容：
   - `reason = "nothing_to_compress"`
3. checkpoint 压缩完成后仍高于硬线：
   - `reason = "post_compaction_still_over_limit"`

会重置失败状态的场景：

- 当前估算低于软线
- microcompact 后已低于软线
- checkpoint 压缩后估算已低于硬线

一旦进入 irreducible，RunLoop 会：

- 停止继续发起该次主模型请求
- 生成一条最终 assistant 消息
- 追加 `error` 事件，错误码为 `NEWMAN-CONTEXT-001`

默认对用户的建议是：

- 开启新会话
- 拆分任务
- 切换到更大上下文窗口模型

---

## 8. transcript 与 prompt 可见范围是两套概念

当前实现明确区分：

- `session.messages`：完整 transcript，给 UI、审计和恢复使用
- prompt 可见消息：只给模型看的“未归档部分”

`checkpoint compact` 不会删除 `session.messages` 里的旧消息。

它做的是：

1. 生成 `checkpoint.summary`
2. 记录一个“已归档前缀边界”
3. 后续 prompt 组装只从边界之后开始取消息

归档边界由以下逻辑读取：

- `checkpoint.turn_range[1]`
- 或 `checkpoint.metadata["compressed_message_count"]`

但只有在以下条件同时满足时才生效：

- 存在 checkpoint
- `session.metadata["checkpoint_active"] is True`
- `checkpoint.metadata["transcript_retained"] is True`

---

## 9. 压缩保留单位是 segment，不是完整 turn

当前实现不是“保留最近 N 个 turn”，而是“保留最近 N 个 segment”。

默认：

- `runtime.context_compaction_preserve_recent = 4`

segment 切分规则来自 `_build_message_segments()`：

1. 若消息有 `group_id`，则连续同 `group_id` 的消息归为一个 segment
2. 若 assistant 消息带 `tool_calls`，则它和后面连续、且 `tool_call_id` 能匹配到这些 call 的 tool 消息归为一个 segment
3. 若某条 tool 消息自身有 `tool_call_id` 但不属于上面的连续配对，则它单独成段
4. 其余 user / assistant / system 消息各自单独成段

这样做有两个直接效果：

- 不会把一个 tool 调用链切成前后两半
- 同一 `turn_id` 内较早、已闭合的工作片段仍然可以被归档

因此当前实现能够处理：

- “整个长 turn 都在同一个 `turn_id` 下，但前半段已经可以压缩”的情况

---

## 10. `tool output microcompact`

这是第一层、成本最低的压缩。

### 10.1 作用范围

`microcompact_session()` 只处理“当前可归档前缀”里的 `role="tool"` 消息：

- 不处理最近保留尾部
- 不处理已经落在 checkpoint 已归档边界之前的消息之外的部分
- 不处理非 `tool` 消息

### 10.2 触发条件

当前单条工具消息只有在以下任一条件满足时才会改写：

1. 归一化后的 `message.content` 长度至少 `600` 字符
2. 有 `frontend_message`
3. 有 `recommended_next_step`

并且：

- 已做过 `microcompact_applied` 的消息不会重复处理

### 10.3 改写结果

工具消息正文会被替换成一条短摘要，格式大致为：

```text
[Microcompact tool output] {tool_name} {status}.
Original output archived at: {artifact_ref}.
{frontend_message 或 Preview}
Next: {recommended_next_step}
```

其中：

- `Preview` 最长约 240 字符
- `status` 来自 `success` 布尔值

### 10.4 落盘归档

如果运行时存在 `sessions_dir`，原始工具输出会尽量落到：

```text
backend_data/sessions/tool_outputs/{session_id}/
```

并把绝对路径写入：

- `message.metadata["microcompact_artifact_ref"]`

同时还会写入：

- `microcompact_applied = true`
- `microcompact_strategy = "tool_output_digest"`
- `microcompact_original_length`

只要本轮有至少一条 tool 消息被改写，session 级别还会记录：

- `last_compaction_stage = "microcompact"`
- `last_microcompact_at = utc_now()`

---

## 11. `checkpoint compact`

这是第二层压缩，也是当前真正改变 prompt 历史范围的动作。

### 11.1 输入材料

`summarize_messages()` 会发给压缩模型一个 JSON 负载，包含四部分：

- `session`
- `existing_checkpoint_summary`
- `messages_to_compact`
- `preserved_recent_messages`

含义：

- `existing_checkpoint_summary`：已有 checkpoint 摘要
- `messages_to_compact`：本轮准备归档掉的历史前缀
- `preserved_recent_messages`：压缩后仍会原样保留在 prompt 里的最近消息

### 11.2 摘要目标

压缩提示词在 `backend/memory/prompts/checkpoint_compact.md` 中，核心要求是生成 handoff summary，保留：

- 当前进展
- 关键决策
- 重要约束和用户偏好
- 下一步待做事项
- 继续工作所需的关键引用

并明确排除：

- tool-by-tool 流水
- 文件读写流水
- memory 维护记录
- workflow/request/turn/group 等内部 ID
- 已完成但不再重要的分支过程
- 噪声填充材料

### 11.3 对历史消息做了什么裁剪

传给压缩模型的 message payload 不是完整 metadata 原样透传，而是做过脱噪：

- user 消息只保留附件描述符等必要外部信息
- assistant 消息只保留 tool 名称、finish_reason、turn_outcome 等少量关键字段
- tool 消息只保留 `tool/success/summary/frontend_message/recommended_next_step/path/error_code/...` 这类仍可能影响后续工作的字段

这一步的目标是：

- 让 handoff summary 聚焦耐久上下文
- 避免把内部运行时噪声重新灌回摘要

### 11.4 生成成功时

若 provider 不是 `MockProvider`，且返回了非空摘要：

- `summary_strategy = "llm_handoff_summary"`

checkpoint metadata 里会记录：

- `preserve_recent`
- `preserve_unit = "segment"`
- `compression_level`
- `original_message_count`
- `compressed_message_count`
- `newly_compressed_message_count`
- `transcript_retained = true`
- `compact_boundary`
- `microcompact_count`（如果本轮发生过）
- `summary_model`（如果 provider 返回）
- `summary_usage`（如果 provider 返回 usage）

### 11.5 回退策略

以下场景会退回结构化归档摘要：

1. 当前 provider 是 `MockProvider`
2. provider 抛出 `ProviderError`
3. provider 返回空摘要

这时：

- `summary_strategy = "fallback_archived_snapshot"`
- `fallback_reason` 会写入 metadata
- 新摘要会保留旧 checkpoint summary，并附加 `## Archived Message Snapshot`

换句话说，回退不是“压缩失败就什么都不做”，而是使用一个更机械但稳定的归档摘要。

### 11.6 保存后的边界语义

checkpoint 保存时会写：

```text
turn_range = [0, archived_message_count]
```

这表示：

- prompt 应跳过前 `archived_message_count` 条 transcript 消息
- transcript 仍然完整保留

同时 session 会设置：

- `checkpoint_active = true`
- `checkpoint_restore_hint = checkpoint_id`
- `last_compaction_stage = "checkpoint_compact"`

---

## 12. 手动压缩接口

接口：

```text
POST /api/sessions/{session_id}/compress
```

当前行为：

1. 读取 session 和现有 checkpoint
2. 先执行一次 `microcompact_session()`
3. 再执行一次 `summarize_messages()`
4. 如果没有任何可归档内容，返回：

```json
{
  "compressed": false,
  "reason": "nothing_to_compress",
  "microcompact_count": 0
}
```

5. 如果成功，保存新的 checkpoint，返回：
   - `compressed: true`
   - `checkpoint`
   - `session`
   - `microcompact_count`

手动压缩和自动压缩的共性：

- 都使用同一套 segment 保留规则
- 都使用同一套 handoff summary 生成逻辑
- 都不删除完整 transcript

手动压缩和自动压缩的差异：

- 手动压缩不依赖软线/硬线阈值判断
- 手动压缩接口本身不额外做“直到过线以下”为止的循环复压

---

## 13. `restore-checkpoint`

接口：

```text
POST /api/sessions/{session_id}/restore-checkpoint
```

这不是“还原旧消息历史”，而是把 checkpoint 摘要显式恢复成一条 system 消息。

当前行为：

1. 读取 checkpoint
2. 构造一条 system 消息：

```text
## Restored From Checkpoint
{checkpoint.summary}
```

3. 删除 session 中已有的旧 `checkpoint_restore` system 消息
4. 把新 restore 消息插入到 `session.messages` 开头
5. 设置：
   - `checkpoint_active = false`
   - `checkpoint_restore_hint = checkpoint_id`

后续 prompt 组装时：

- 如果 session 中已存在 `metadata.type = "checkpoint_restore"` 的 system 消息
- 就不会再额外从 checkpoint 文件重复注入 `## Checkpoint Summary`

因此 restore 的效果是：

- 把摘要显式并入会话消息流
- 关闭“按归档边界跳过旧 transcript”的模式

它不会：

- 重建被归档前缀的原始 prompt 视图
- 逆向恢复 microcompact 前的完整 tool 输出

---

## 14. 前端和 API 的建议口径

聊天页如果展示上下文占用，建议直接使用：

- `budget_pressure` 作为主圆环
- `projected_next_prompt_tokens`
- `auto_compact_limit`
- `soft_compact_limit`
- `confirmed_prompt_tokens`
- `projection_source`
- `projected_over_soft_limit`
- `projected_over_limit`
- `compaction_stage`
- `compaction_fail_streak`
- `context_irreducible`
- `last_compaction_failure_reason`

推荐解释方式：

- 主状态回答“现在如果再发一次请求，会占掉多少预算”
- tooltip 或次级说明回答“上一条真实请求的已确认 prompt 多大”

示例：

```json
{
  "effective_context_window": 190000,
  "auto_compact_limit": 190000,
  "soft_compact_limit": 161500,
  "confirmed_prompt_tokens": 8200,
  "confirmed_pressure": 0.0431,
  "confirmed_request_kind": "session_turn",
  "confirmed_recorded_at": "2026-04-16T09:30:00Z",
  "projected_next_prompt_tokens": 12140,
  "projected_pressure": 0.0639,
  "budget_pressure": 0.0639,
  "projection_source": "confirmed_plus_delta",
  "projected_over_soft_limit": false,
  "projected_over_limit": false,
  "compaction_stage": "checkpoint_compact",
  "compaction_fail_streak": 0,
  "context_irreducible": false,
  "last_compaction_failure_reason": null
}
```

---

## 15. 一句话总结

Newman 当前的上下文压缩实现可以概括为：

- 用 `projected_next_prompt_tokens` 评估“下一次请求”的风险
- 用 `budget_pressure = projected_next_prompt_tokens / auto_compact_limit` 给前端展示主预算占用
- 先 microcompact 老 tool 输出，再把更早历史压成 checkpoint handoff summary
- 保留完整 transcript，只改变模型实际可见的历史范围
- 按 segment 保留最近上下文，而不是按完整 turn 硬切
- 通过失败计数、`context_irreducible` 和 restore 机制，管理无法继续压缩的长会话
