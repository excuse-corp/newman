# Newman 上下文压缩方案

本文档定义 Newman 的上下文占用展示、自动压缩触发和会话摘要压缩方案。

目标是同时满足三件事：

- 让 UI 展示稳定、可解释的上下文占用
- 让自动压缩基于“下一次请求是否会超限”来判断
- 让压缩后的历史仍然适合后续多轮继续工作

---

## 1. 核心原则

Newman 将“上下文占用”拆成两套指标：

- `confirmed_prompt_tokens`
- `projected_next_prompt_tokens`

两者的职责不同：

- `confirmed_prompt_tokens` 回答“上一条真实主模型请求，实际输入了多少 token”
- `projected_next_prompt_tokens` 回答“如果现在立刻再发一次主模型请求，下一次 prompt 预计会有多大”

因此：

- UI 主圆环使用 `confirmed_prompt_tokens`
- 自动压缩触发使用 `projected_next_prompt_tokens`

这两套指标分别面向“回看已确认事实”和“前瞻下一次风险”，不混用。

---

## 2. 两套上下文指标

### 2.1 `confirmed_prompt_tokens`

`confirmed_prompt_tokens` 是最近一次计入上下文窗口的真实主模型请求的 `input_tokens`。

它只统计请求输入，不统计输出。

原因是：

- UI 要展示“上一轮真实 prompt 输入有多大”
- 输出 token 不一定会完整回灌到下一轮上下文
- 把 `output_tokens` 混进 UI 主指标，会让占用看起来偏高

对应压力值为：

```text
confirmed_pressure = confirmed_prompt_tokens / effective_context_window
```

### 2.2 `projected_next_prompt_tokens`

`projected_next_prompt_tokens` 是下一次主模型请求预计会发送的 prompt token 数。

它面向“下一轮风险判断”，用于自动压缩和调试。

对应压力值为：

```text
projected_pressure = projected_next_prompt_tokens / effective_context_window
```

### 2.3 `effective_context_window`

有效上下文窗口定义为：

```text
effective_context_window = configured_context_window * 95%
```

它是所有确认值、预测值和压缩预算的统一分母。

---

## 3. UI 展示口径

聊天页上下文圆环展示 `confirmed_prompt_tokens`。

也就是说，圆环回答的是：

```text
上一条真实主模型请求的输入，占有效上下文窗口的多少
```

推荐展示字段：

- `confirmed_prompt_tokens`
- `confirmed_pressure`
- `effective_context_window`

推荐行为：

- 主圆环显示 `confirmed_pressure`
- Tooltip 或调试面板可额外显示 `projected_next_prompt_tokens`
- 当尚无真实 usage 记录时，圆环显示空态 `--`

这样 UI 的语义始终稳定：

- 有记录时，展示已确认值
- 无记录时，不拿估算值冒充已确认值

---

## 4. 自动压缩触发时机

自动压缩检查发生在“每一次主模型请求发出之前”，而不是只在新用户消息进入时检查一次。

凡是会触发主模型继续生成的入口，都执行同一套检查：

- 新用户消息进入后，第一次主模型请求前
- 工具调用结束后，后续续写请求前
- 工具上限收口前
- 其他会重新组装主 prompt 的续轮请求前

检查顺序为：

1. 组装下一次主模型请求的 prompt
2. 计算 `projected_next_prompt_tokens`
3. 与 `auto_compact_limit` 比较
4. 如超限，执行压缩
5. 压缩后重新组装并复检
6. 通过后再发主模型请求

这保证自动压缩始终面向“下一次即将发生的请求”。

---

## 5. 自动压缩采用预算制

自动压缩不直接使用单一百分比阈值，而是使用预算制上限：

```text
auto_compact_limit =
  effective_context_window
  - reply_reserve_tokens
  - compact_reserve_tokens
  - safety_buffer_tokens
```

触发条件为：

```text
if projected_next_prompt_tokens >= auto_compact_limit:
    trigger compact
```

### 5.1 预算项含义

`reply_reserve_tokens`

- 为主回复预留的输出空间

`compact_reserve_tokens`

- 为压缩摘要请求和压缩后摘要注入预留的空间

`safety_buffer_tokens`

- 为 token 估算误差、工具 schema 波动、checkpoint 注入变化等保留的安全边际

### 5.2 默认预算值

`reply_reserve_tokens`

- `effective_context_window >= 64k`：`4096`
- `effective_context_window < 64k`：`2048`

`compact_reserve_tokens`

- 统一为：`2048`

`safety_buffer_tokens`

- `effective_context_window >= 128k`：`4096`
- `64k <= effective_context_window < 128k`：`2048`
- `effective_context_window < 64k`：`1024`

### 5.3 预算示例

假设：

- `configured_context_window = 200000`
- `effective_context_window = 190000`

则默认预算为：

```text
reply_reserve_tokens = 4096
compact_reserve_tokens = 2048
safety_buffer_tokens = 4096
```

因此：

```text
auto_compact_limit = 190000 - 4096 - 2048 - 4096 = 179760
```

这时，只有当下一次主请求预计达到 `179760` token 以上时，才触发自动压缩。

---

## 6. `projected_next_prompt_tokens` 的计算

`projected_next_prompt_tokens` 采用“确认值 + 增量估算”的方式计算，并保留完整重组估算作为兜底。

### 6.1 主路径：确认值 + 增量估算

主路径公式为：

```text
projected_next_prompt_tokens =
  confirmed_prompt_tokens
  + estimated_tail_delta_tokens
```

其中：

- `confirmed_prompt_tokens` 取最近一次真实主模型请求的 `input_tokens`
- `estimated_tail_delta_tokens` 估算该请求之后新增、且下一轮会进入 prompt 的上下文增量

增量来源包括：

- 新增用户消息
- 新增 assistant 消息
- 新增 tool 消息
- 新增或刷新的 `checkpoint.summary`
- 其他会进入主 prompt 的历史注入变化

### 6.2 失效条件

以下情况会使“确认值 + 增量估算”失去可靠锚点：

- `stable context` 发生变化
- `tools_overview` 发生变化
- 发生 checkpoint restore / checkpoint 注入方式变化
- 无可用的最近一次真实 usage 记录

遇到这些情况时，直接走完整重组估算。

### 6.3 兜底路径：完整重组估算

兜底公式为：

```text
projected_next_prompt_tokens = estimate_tokens(assembled_prompt)
```

这里的 `assembled_prompt` 包含：

- stable context
- 可选 checkpoint summary
- 当前 `session.messages`
- 与本次请求绑定的工具 schema

这样即使增量账本不可用，也能保证压缩判断安全。

---

## 7. 压缩采用分级策略

Newman 的自动压缩分为三层：

1. `microcompact`
2. `checkpoint compact`
3. `irreducible`

每一层执行后都重新计算 `projected_next_prompt_tokens`，只有仍然超限时才进入下一层。

### 7.1 `microcompact`

`microcompact` 优先处理历史中体积大、但保真要求低的内容。

首要目标是老的工具输出，尤其是：

- 大段终端 stdout
- 大段检索结果
- 大段中间分析文本

`microcompact` 的目标不是生成全局摘要，而是把“旧的胖消息”压成短摘要或引用。

它遵循两个原则：

- 不动最近完整 turn / group
- 不改变当前工作所依赖的最新消息链

### 7.2 `checkpoint compact`

如果 `microcompact` 后仍超限，则执行 `checkpoint compact`。

它会把较早的历史压缩成 `checkpoint.summary`，并保留最近仍需原样工作的消息尾部。

`checkpoint compact` 生成的是 handoff summary，而不是简单拼接日志。

### 7.3 `irreducible`

如果在保留最近必要上下文后仍然超限，则进入 `irreducible` 状态。

这表示：

- 当前上下文已经无法再安全压缩
- 再继续压缩会破坏正在进行的工作链

进入该状态后：

- 停止继续尝试自动压缩
- 返回明确状态给前端和运行时
- 提示用户拆分任务、开启新会话或切换更大窗口模型

---

## 8. 保留策略按 turn / group，而不是按消息条数

压缩保留单位不是“最近 N 条消息”，而是“最近完整工作单元”。

至少保留以下内容：

- 最近完整 `turn_id`
- 最近完整 `group_id`
- 最近一次 assistant tool-calls 与其对应的全部 tool 结果

不能出现以下切法：

- 保留了 tool result，但丢了发起它的 assistant tool-calls
- 保留了 assistant tool-calls，但只保留了部分 tool 结果
- 把同一轮工作链切成前后两半

这样做的目标是保证压缩后仍然保留最小可继续执行单元。

---

## 9. `checkpoint compact` 的输入材料

发送给压缩模型的材料包含四部分：

- `session`
- `existing_checkpoint_summary`
- `messages_to_compact`
- `preserved_recent_messages`

含义如下：

- `existing_checkpoint_summary`：上一版 checkpoint 摘要
- `messages_to_compact`：本轮准备归档的历史消息
- `preserved_recent_messages`：本轮压缩后仍原样保留的最近消息

这使模型能够理解：

- 旧摘要里已经覆盖了什么
- 这次新增要吸收什么
- 哪些消息不会被裁掉，后续还会继续原样存在

因此，新生成的 `checkpoint.summary` 是一份新的 consolidated handoff summary，而不是：

```text
old_summary + delta_text
```

---

## 10. 压缩后的复检

每一轮压缩完成后，都立即执行复检。

复检步骤：

1. 重新组装主 prompt
2. 重新计算 `projected_next_prompt_tokens`
3. 与 `auto_compact_limit` 比较

复检结果有三种：

- 低于上限：继续主模型请求
- 仍高于上限，但还能进入下一层压缩：继续压缩
- 仍高于上限，且已不可再压：进入 `irreducible`

压缩流程不以“压缩动作成功返回”为结束条件，而以“复检通过”为结束条件。

---

## 11. 连续失败熔断

自动压缩维护 `compaction_fail_streak`。

以下情况会累加失败计数：

- 压缩请求报错
- 压缩后复检仍超限，且没有实质性下降
- 多次连续进入无效压缩链

达到熔断阈值后：

- 本 session 停止继续自动压缩尝试
- 进入显式告警状态

这样可以避免在不可恢复的上下文上反复空转。

---

## 12. 手动压缩

接口：

```text
POST /api/sessions/{session_id}/compress
```

手动压缩使用与自动压缩相同的摘要生成和保留策略，但不依赖阈值判断。

流程为：

1. 计算当前可归档前缀和应保留尾部
2. 执行 `checkpoint compact`
3. 压缩后复检
4. 返回新的 checkpoint 和裁剪后的 session

手动压缩的主要用途是：

- 用户主动整理长会话
- 在进入复杂新任务前先收束历史
- 在调试时强制生成新的 handoff summary

---

## 13. `restore-checkpoint`

接口：

```text
POST /api/sessions/{session_id}/restore-checkpoint
```

`restore-checkpoint` 是手动动作，不属于自动压缩链路。

执行后：

- `checkpoint.summary` 被恢复为显式 `system` 消息
- 后续 prompt 组装时不再重复从 checkpoint 文件额外插入同一份 summary

它的作用是让用户或运行时显式把摘要“展开回会话消息流”，而不是生成新的压缩结果。

---

## 14. 会话详情接口返回的上下文字段

推荐 `context_usage` 结构如下：

```json
{
  "effective_context_window": 190000,
  "auto_compact_limit": 179760,
  "confirmed_prompt_tokens": 8200,
  "confirmed_pressure": 0.0431,
  "confirmed_request_kind": "session_turn",
  "confirmed_recorded_at": "2026-04-16T09:30:00Z",
  "projected_next_prompt_tokens": 12140,
  "projected_pressure": 0.0639,
  "projection_source": "confirmed_plus_delta"
}
```

可选补充字段：

- `compaction_stage`
- `compaction_fail_streak`
- `irreducible`

这些字段主要用于调试、可视化和压缩诊断。

---

## 15. 一次完整链路示例

假设：

- 最近一次真实主模型请求 `input_tokens = 10000`
- 之后新增了一条用户消息，估算 `800`
- 新增两条工具结果，合计估算 `2600`
- `checkpoint.summary` 刷新后比上一版多 `500`

则：

```text
confirmed_prompt_tokens = 10000
projected_next_prompt_tokens = 10000 + 800 + 2600 + 500 = 13900
```

如果：

```text
auto_compact_limit = 13000
```

则下一次主模型请求前触发自动压缩。

压缩后重新组装 prompt，再次估算：

```text
projected_next_prompt_tokens = 9100
```

由于：

```text
9100 < 13000
```

所以通过复检，继续主模型请求。

---

## 16. 一句话总结

Newman 的上下文压缩方案可以概括为：

- UI 展示上一条真实主请求的 `confirmed_prompt_tokens`
- 自动压缩依据下一条主请求的 `projected_next_prompt_tokens`
- 压缩阈值使用预算制 `auto_compact_limit`
- 压缩检查发生在每一次主模型请求前
- 压缩保留单位是最近完整 `turn / group`，而不是固定条数消息
- 压缩流程按 `microcompact -> checkpoint compact -> irreducible` 分级执行
- 每次压缩后都必须复检，并通过失败熔断避免无效反复压缩
