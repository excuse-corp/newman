# Newman 上下文压缩说明

本文描述 Newman 已落地的上下文占用统计、自动压缩、手动压缩和 checkpoint 恢复行为。若文档与代码不一致，以实现为准：

- `backend/memory/compressor.py`
- `backend/runtime/run_loop.py`
- `backend/runtime/prompt_assembler.py`
- `backend/api/routes/sessions.py`

## 1. 核心目标

上下文压缩服务三件事：

- 给前端返回稳定的 `context_usage`
- 在每次主模型请求前预估下一次 prompt 大小
- 在保留完整 transcript 的前提下，把旧上下文压成可继续工作的 handoff summary

## 2. 预算口径

预算由 `build_context_compaction_budget()` 统一计算：

```text
effective_context_window = model.context_window * 95%
auto_compact_limit = effective_context_window
soft_compact_limit = auto_compact_limit * runtime.context_compress_threshold
```

默认值：

- `EFFECTIVE_CONTEXT_WINDOW_PERCENT = 95`
- `runtime.context_compress_threshold = 0.85`

含义：

- `effective_context_window`：所有压力值的统一分母
- `auto_compact_limit`：运行时安全预算线，目前等于 `effective_context_window`
- `soft_compact_limit`：提前触发压缩的软线

示例：

```text
configured context_window = 200000
effective_context_window = 190000
auto_compact_limit = 190000
soft_compact_limit = 161500
```

## 3. 占用统计

`context_usage` 同时返回确认值和预测值。

### `confirmed_*`

`confirmed_*` 来自最近一次真实主模型请求：

- 数据源：`usage_store.latest_context_record(session_id)`
- 只取 `counts_toward_context_window = true` 且 `usage_available = true` 的最新记录
- `confirmed_prompt_tokens = input_tokens`
- 不把 `output_tokens` 计入 prompt 占用

```text
confirmed_pressure = confirmed_prompt_tokens / effective_context_window
```

### `projected_*`

`projected_*` 表示“现在再发一次主模型请求”的预计 prompt 大小。

运行时会先估算完整组装后的 prompt：

```text
assembled_estimate = estimate_tokens(assembled_messages)
```

如果最近 usage 记录仍可作为锚点，还会估算：

```text
confirmed_plus_delta =
  confirmed_prompt_tokens
  + estimate_tokens(delta_messages_since_latest_record)
```

最终取更保守的较大值：

```text
projected_next_prompt_tokens = max(assembled_estimate, confirmed_plus_delta_if_valid)
```

`confirmed_plus_delta` 仅在锚点未被上下文重写打断时可用。当前失效条件包括：

- 最新激活 checkpoint 晚于最近 usage 记录
- `last_microcompact_at` 晚于最近 usage 记录

压力值：

```text
projected_pressure = projected_next_prompt_tokens / effective_context_window
budget_pressure = projected_next_prompt_tokens / auto_compact_limit
```

前端主圆环建议使用 `budget_pressure`。

## 4. Prompt 估算范围

`projected_next_prompt_tokens` 不是只看 `session.messages`，而是尽量复用真实 `PromptAssembler` 的结果，通常包含：

- commentary / tool-action / user-input 系统护栏
- stable context
- collaboration mode prompt
- workflow state prompt
- checkpoint summary（仅在 checkpoint 激活且尚未 restore 时注入）
- 当前模型可见的会话消息

模型可见消息来自：

```text
model_visible_session_messages(session, checkpoint)
```

也就是跳过 checkpoint 已归档前缀后的消息。轻量 API 场景无法使用 `PromptAssembler` 时，会退回到 checkpoint summary + model-visible messages 的估算。

## 5. 自动压缩时机

自动压缩在每次主模型请求发出前预检，不只在用户发新消息时触发。

典型入口：

- 新用户消息后的主回合请求
- 工具调用后的续写请求
- 工具上限后的收口回答
- 致命工具失败后的收口回答

统一入口：

```text
RunLoop._maybe_checkpoint()
```

## 6. 自动压缩流程

单次预检流程：

1. 组装即将发送的 prompt
2. 计算 `context_usage`
3. 若低于 `soft_compact_limit`，重置失败状态并继续
4. 否则执行 `microcompact_session()`
5. 重新估算；若低于软线，重置失败状态并继续
6. 否则执行 `summarize_messages()` 生成或刷新 checkpoint
7. 再次估算；若仍高于 `auto_compact_limit`，记录失败

注意：

- 单次 `_maybe_checkpoint()` 只执行一轮 `microcompact -> checkpoint compact`
- 当前不会在同一次预检里无限循环压缩
- “压缩动作成功”不等于“预算一定已降到硬线以内”

## 7. 软线、硬线和阻断

`soft_compact_limit` 是提前压缩线：

- 超过软线会尝试压缩
- 若没有可压缩内容且仍低于硬线，可以继续请求

`auto_compact_limit` 是 Newman 的运行时安全预算线，不是 provider 的物理 hard limit。

高于硬线后并不一定立刻阻断。当前行为：

- 预检开始时已高于硬线，且 session 已是 `context_irreducible`：阻断
- 预检开始时已高于硬线，且失败次数达到 `runtime.context_compaction_max_failures`：标记 irreducible 并阻断
- 本轮压缩后仍高于硬线：记录 `post_compaction_still_over_limit`
- 命中 `nothing_to_compress` 等不可恢复场景，后续会进入阻断

默认最大失败次数：

```text
runtime.context_compaction_max_failures = 3
```

## 8. 失败状态

session 维护：

- `compaction_fail_streak`
- `context_irreducible`
- `last_compaction_failure_reason`
- `last_compaction_stage`

失败原因包括：

- `max_failures_reached`
- `nothing_to_compress`
- `post_compaction_still_over_limit`

以下场景会重置失败状态：

- 当前估算低于软线
- microcompact 后低于软线
- checkpoint compact 后低于硬线

进入 `context_irreducible` 后，RunLoop 会停止本次主模型请求，生成最终 assistant 消息，并追加错误事件：

```text
NEWMAN-CONTEXT-001
```

默认建议用户开启新会话、拆分任务，或切换更大上下文窗口模型。

## 9. Transcript 与模型可见范围

Newman 区分两套历史：

- `session.messages`：完整 transcript，供 UI、审计和恢复使用
- prompt 可见消息：只给模型看的未归档部分

checkpoint compact 不删除 transcript。它只会：

1. 生成 `checkpoint.summary`
2. 记录已归档前缀边界
3. 让后续 prompt 从边界之后开始取消息

归档边界来自：

- `checkpoint.turn_range[1]`
- 或 `checkpoint.metadata["compressed_message_count"]`

只有同时满足以下条件时才生效：

- checkpoint 存在
- `session.metadata["checkpoint_active"] is True`
- `checkpoint.metadata["transcript_retained"] is True`

## 10. 保留单位

压缩保留最近 `segment`，不是最近完整 turn。

默认：

```text
runtime.context_compaction_preserve_recent = 4
```

segment 由 `_build_message_segments()` 生成：

- 连续同 `group_id` 的消息归为一段
- assistant tool_calls 与后续匹配的 tool 消息归为一段
- 未匹配 tool 消息单独成段
- 其他 user / assistant / system 消息各自成段

这样可以避免切断 tool 调用链，同时允许压缩同一长 turn 中较早、已闭合的工作片段。

## 11. Microcompact

`microcompact_session()` 是第一层压缩，只改写当前可归档前缀中的 `role="tool"` 消息。

单条 tool 消息满足以下任一条件才会处理：

- 归一化后正文长度至少 `600` 字符
- 有 `frontend_message`
- 有 `recommended_next_step`

已标记 `microcompact_applied` 的消息不会重复处理。

改写后的正文大致为：

```text
[Microcompact tool output] {tool_name} {status}.
Original output archived at: {artifact_ref}.
{frontend_message 或 Preview}
Next: {recommended_next_step}
```

如果存在 `sessions_dir`，原始输出会落盘到：

```text
backend_data/sessions/tool_outputs/{session_id}/
```

相关 metadata：

- `microcompact_applied = true`
- `microcompact_strategy = "tool_output_digest"`
- `microcompact_original_length`
- `microcompact_artifact_ref`

session 级别会记录：

- `last_compaction_stage = "microcompact"`
- `last_microcompact_at = utc_now()`

## 12. Checkpoint Compact

`summarize_messages()` 是第二层压缩，会真正改变模型可见历史范围。

压缩模型收到的 JSON 负载包含：

- `session`
- `existing_checkpoint_summary`
- `messages_to_compact`
- `preserved_recent_messages`

目标是生成 handoff summary，保留：

- 当前进展
- 关键决策
- 重要约束和用户偏好
- 下一步待做事项
- 继续工作所需引用

摘要会排除工具流水、文件读写流水、memory 维护记录、内部 ID 和无关分支过程。

消息 payload 会先脱噪：

- user 消息保留必要附件描述
- assistant 消息保留 tool 名称、finish_reason、turn_outcome 等关键字段
- tool 消息保留 `tool/success/summary/frontend_message/recommended_next_step/path/error_code` 等后续可能需要的信息

成功时：

- `summary_strategy = "llm_handoff_summary"`
- checkpoint metadata 记录保留段数、压缩级别、消息计数、归档边界、是否保留 transcript、模型和 usage 等信息

回退场景：

- provider 是 `MockProvider`
- provider 抛出 `ProviderError`
- provider 返回空摘要

回退时：

- `summary_strategy = "fallback_archived_snapshot"`
- metadata 写入 `fallback_reason`
- 新摘要保留旧 checkpoint summary，并追加 `## Archived Message Snapshot`

保存后：

```text
turn_range = [0, archived_message_count]
```

session 设置：

- `checkpoint_active = true`
- `checkpoint_restore_hint = checkpoint_id`
- `last_compaction_stage = "checkpoint_compact"`

## 13. 手动压缩

接口：

```text
POST /api/sessions/{session_id}/compress
```

行为：

1. 读取 session 和现有 checkpoint
2. 执行 `microcompact_session()`
3. 执行 `summarize_messages()`
4. 若没有可归档内容，返回 `compressed: false` 和 `reason: "nothing_to_compress"`
5. 若成功，保存 checkpoint 并返回 session、checkpoint 和 `microcompact_count`

手动压缩与自动压缩共用 segment 保留规则、summary 生成逻辑，并且都不删除完整 transcript。

区别：

- 手动压缩不依赖软线/硬线判断
- 手动接口不会循环复压到低于预算

## 14. Restore Checkpoint

接口：

```text
POST /api/sessions/{session_id}/restore-checkpoint
```

它不是还原旧消息，而是把 checkpoint 摘要显式写回会话。

行为：

1. 读取 checkpoint
2. 构造 system 消息：

```text
## Restored From Checkpoint
{checkpoint.summary}
```

3. 删除已有旧 `checkpoint_restore` system 消息
4. 把新 restore 消息插入 `session.messages` 开头
5. 设置 `checkpoint_active = false`
6. 设置 `checkpoint_restore_hint = checkpoint_id`

后续 prompt 中若已有 `metadata.type = "checkpoint_restore"` 的 system 消息，就不会再额外注入 `## Checkpoint Summary`。

Restore 不会：

- 重建被归档前缀的原始 prompt 视图
- 恢复 microcompact 前的完整 tool 输出

## 15. 前端展示建议

聊天页展示上下文占用时，主状态应表达：

```text
如果现在再发一次请求，会占掉多少预算
```

建议字段：

- `budget_pressure`
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

tooltip 或次级说明可解释最近一次真实请求的 `confirmed_prompt_tokens`。

## 16. 总结

当前实现可以概括为：

- 用 `projected_next_prompt_tokens` 评估下一次请求风险
- 用 `budget_pressure` 给前端展示主预算占用
- 先 microcompact 老 tool 输出，再把更早历史压成 checkpoint handoff summary
- 完整 transcript 始终保留，只改变模型可见历史范围
- 按 segment 保留最近上下文，避免切断 tool 调用链
- 通过失败计数、`context_irreducible` 和 restore 管理不可继续压缩的长会话
