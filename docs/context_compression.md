# Newman 上下文压缩逻辑说明

本文档描述当前 Newman 项目中已经落地的会话上下文压缩机制，包括：

- 何时触发压缩
- 压缩时实际送给模型的材料
- 第一次压缩与后续压缩的差异
- 压缩后历史上下文如何重新参与后续对话
- `restore-checkpoint` 的作用
- 前端上下文窗口占用圆环的计算口径
- 当前实现的边界与限制

本文档对应当前代码实现，而不是理想设计。

---

## 1. 核心目标

当一个 session 的历史越来越长时，继续把完整历史都送给模型，会逐步逼近模型上下文窗口上限。

因此，系统会在必要时把较早的历史消息压缩成一份 `checkpoint.summary`，然后只保留最近的一小段原始消息，后续对话继续在：

- Stable Context
- `checkpoint.summary`
- 最近保留的消息
- 后续新增消息

这个组合上继续运行。

---

## 2. 涉及到的核心对象

### 2.1 `session.messages`

会话当前仍然保留的原始消息列表。

类型定义见：

- `backend/sessions/models.py`

压缩前，它包含当前整个会话的所有消息。  
压缩后，它只保留最近 `4` 条消息。

### 2.2 `checkpoint.summary`

压缩后生成并持久化到 `{session_id}_checkpoint.json` 的摘要文本。  
它不是简单日志，而是一次单独的 handoff summary。

实现见：

- `backend/memory/compressor.py`
- `backend/memory/checkpoint_store.py`

### 2.3 `preserve_recent`

当前固定为 `4`。

含义是：

- 每次压缩时，当前 `session.messages` 的最后 `4` 条消息不会被裁掉
- 其余更早的消息会进入“待归档历史”

实现见：

- `backend/runtime/run_loop.py`
- `backend/api/routes/sessions.py`

### 2.4 `restore-checkpoint`

这是一个手动接口，不会自动执行。  
它的作用是把 `checkpoint.summary` 显式恢复成一条 `system` message 放回 session。

实现见：

- `backend/api/routes/sessions.py`

---

## 3. 何时触发压缩

当前有两种触发方式。

### 3.1 自动触发

每轮对话结束后，运行时会计算当前 assembled prompt 的上下文占用比例：

```text
effective_context_window = configured_context_window * 95%
pressure = estimated_tokens / effective_context_window
```

如果 `pressure` 超过 `context_compress_threshold`，就会自动触发压缩。

实现见：

- `backend/runtime/run_loop.py`
- `backend/memory/compressor.py`

注意：

- 自动触发用的是“完整 assembled prompt”的估算口径
- 这里的 assembled prompt 包含 Stable Context、checkpoint summary 和 session.messages
- 阈值比较使用的是“有效上下文窗口”，不是裸 `context_window`

### 3.2 手动触发

接口：

```text
POST /api/sessions/{session_id}/compress
```

手动触发不会先判断阈值，而是直接尝试压缩。  
如果当前消息数小于等于 `4`，没有可裁剪历史，就会返回：

```json
{"compressed": false, "reason": "nothing_to_compress"}
```

---

## 4. 压缩前如何切分消息

每次压缩都会先把当前 `session.messages` 切成两段：

```text
messages_to_compact = session.messages[:-4]
preserved_recent_messages = session.messages[-4:]
```

实现见：

- `backend/memory/compressor.py`

这意味着：

- 被压缩进 summary 的，是“除最后 4 条之外的所有当前消息”
- 最后 4 条消息不会立即进入 summary，而是继续保留在 session 中

注意，这里的“4 条”是“4 条消息”，不是“4 轮对话”。

也就是说这 4 条里可能包含：

- `user`
- `assistant`
- `tool`
- `system`

只要它们存在于 `session.messages` 中，就按消息条数计算。

---

## 5. 实际送给模型压缩的内容

当前压缩方案参考了 Codex 的本地 compact 思路，但做成了 Newman 自己的 payload。

### 5.1 压缩提示词

系统提示词位于：

- `backend/memory/prompts/checkpoint_compact.md`

它要求模型输出一份 handoff summary，重点覆盖：

- 当前进展和关键决策
- 重要上下文、约束、用户偏好
- 剩余待做事项
- 后续继续任务所需的关键引用

### 5.2 用户侧 payload

真正送给模型的 JSON 材料包括：

- `session`
- `existing_checkpoint_summary`
- `messages_to_compact`
- `preserved_recent_messages`

也就是说，模型不仅会看到“准备被裁掉的历史消息”，还会看到“本轮压缩后仍然会保留的最近 4 条消息”，从而生成更连贯的 summary。

### 5.3 参数

当前请求参数为：

- `temperature = 0`
- `max_tokens = 1200`

如果当前 provider 不是 `mock`，系统会真的发起一次独立的 `provider.chat(...)` 压缩请求。  
如果当前 provider 是 `mock`，或压缩请求失败、返回空内容，就会走 fallback。

---

## 6. 第一次压缩时的真实逻辑

假设当前 session 中一共有 10 条消息：

```text
M1 M2 M3 M4 M5 M6 M7 M8 M9 M10
```

压缩时固定保留最后 4 条：

```text
messages_to_compact = M1 M2 M3 M4 M5 M6
preserved_recent_messages = M7 M8 M9 M10
```

系统会把：

- `existing_checkpoint_summary = ""`
- `messages_to_compact = M1..M6`
- `preserved_recent_messages = M7..M10`

一起送给模型，请模型生成一份新的 summary。

压缩成功后，会做两件事：

1. checkpoint 写入这份新 summary
2. `session.messages` 被裁成只剩：

```text
M7 M8 M9 M10
```

所以第一次压缩完成后，后续继续参与对话的历史表示是：

- `checkpoint.summary`
- `M7 M8 M9 M10`
- 后续新增消息

注意：

- 第一次压缩并不是把“所有消息都压进 summary”
- 最近 4 条消息不会被压掉，而是继续原样保留

---

## 7. 第二次及以后压缩时的真实逻辑

这是最容易被误解的部分。

假设第一次压缩之后，session 里剩下：

```text
M7 M8 M9 M10
```

后来又新增：

```text
M11 M12 M13 M14 M15
```

那么第二次压缩前，当前 `session.messages` 实际上是：

```text
M7 M8 M9 M10 M11 M12 M13 M14 M15
```

第二次压缩时再次按“保留最后 4 条”切分：

```text
messages_to_compact = M7 M8 M9 M10 M11
preserved_recent_messages = M12 M13 M14 M15
```

此时送给模型的是：

- `existing_checkpoint_summary = 上一次的 summary`
- `messages_to_compact = M7..M11`
- `preserved_recent_messages = M12..M15`

模型会基于这些材料，重新生成一份“新的 consolidated summary”。

然后系统会：

1. 用新的 summary 覆盖 checkpoint
2. 把 `session.messages` 再次裁成只剩：

```text
M12 M13 M14 M15
```

所以第二次压缩后的后续历史表示是：

- 新的 `checkpoint.summary`
- `M12 M13 M14 M15`
- 后续新增消息

### 7.1 一个非常重要的澄清

第二次压缩并不是严格意义上的：

```text
旧 summary + “上一次压缩后新增的所有消息”
```

而是：

```text
旧 summary + 当前这轮准备被再次归档的所有消息
```

这两者很多时候接近，但并不完全等价。

原因是：

- 上一次压缩时保留下来的最后 4 条消息
- 到下一次压缩时，往往也会有一部分被重新吸收到新的 summary 里

所以更准确的表述应当是：

- 新 summary = 旧 summary + 当前这轮将被归档的消息，由模型重新整合后生成

而不是简单做字符串追加。

---

## 8. 压缩后的历史上下文如何参与后续对话

真正发送给主模型的 assembled prompt 由 `PromptAssembler` 组装。

当前组装顺序是：

1. Stable Context
2. `## Checkpoint Summary\n{checkpoint.summary}`，如果存在 checkpoint 且当前 session 中还没有 `checkpoint_restore`
3. 当前 `session.messages`

实现见：

- `backend/runtime/prompt_assembler.py`

因此，在没有执行 `restore-checkpoint` 的情况下，压缩后的对话上下文口径是：

- Stable Context
- `checkpoint.summary`
- 当前保留在 session 中的最近 4 条消息
- 压缩之后新增的所有消息

---

## 9. `restore-checkpoint` 的作用

接口：

```text
POST /api/sessions/{session_id}/restore-checkpoint
```

它不会自动执行，只会在显式调用接口时执行。

执行后，系统会创建一条新的 `system` 消息：

```text
## Restored From Checkpoint
{checkpoint.summary}
```

并插入当前 session。

同时，后续组装 prompt 和计算 `context_usage` 时，会检测当前 session 里是否已经存在 `checkpoint_restore` 消息。  
如果已经存在，就不再额外从 checkpoint 文件里重复补一份 `checkpoint.summary`。

这样做是为了避免同一份摘要被算两次。

---

## 10. 前端上下文窗口占用圆环的计算口径

前端圆环不是看“本轮真实消耗 tokens”，而是看：

```text
当前 session 历史上下文表示 / context_window
```

也就是：

1. 如果存在 checkpoint，且当前 session 里没有 `checkpoint_restore`，先计入：

```text
## Checkpoint Summary
{checkpoint.summary}
```

2. 再计入当前 `session.messages`
3. 用 `runtime.provider.estimate_tokens(...)` 估算 token
4. 再除以 `context_window`

实现见：

- `backend/api/routes/sessions.py`
- `frontend/src/App.tsx`

所以圆环展示的是：

- 当前历史上下文占窗口的估算比例

而不是：

- 当前这一轮真实花掉了多少 tokens

---

## 11. fallback 逻辑

如果压缩摘要请求失败，或者当前 provider 是 `mock`，系统不会中断压缩流程，而是退回到结构化归档摘要。

fallback 逻辑会：

1. 先保留旧的 `checkpoint.summary`，如果存在
2. 再追加一个：

```text
## Archived Message Snapshot
```

3. 把本轮 `messages_to_compact` 逐条转成：

```text
- role: content
```

也就是说，fallback 不是 handoff summary，而是“可读的历史快照”。

---

## 12. metadata 中会记录什么

当前 checkpoint metadata 会记录：

- `preserve_recent`
- `compression_level`
- `original_message_count`
- `compressed_message_count`
- `summary_strategy`
- `summary_model`
- `summary_usage`
- `summary_fallback_reason`

其中：

- `summary_strategy = llm_handoff_summary` 表示压缩成功使用了模型摘要
- `summary_strategy = fallback_archived_snapshot` 表示走了降级快照逻辑

---

## 13. 当前实现的限制

### 13.1 保留的是 4 条消息，不是 4 轮对话

如果一轮里包含工具调用、系统消息或其他中间消息，这 4 条里不一定是 2 轮完整的人机往返。

### 13.2 现在有按请求落库的 usage 账本，但还没有专门的可视化面板

当前项目会把模型请求 usage 写入 PostgreSQL `model_usage_records`。

包括：

- 主聊天轮次 `session_turn`
- 工具上限后的最终收口 `tool_limit_finalize`
- 压缩摘要 `context_compaction` / `manual_context_compaction`
- 记忆提取 `memory_extraction`
- 多模态分析 `multimodal_analysis`
- RAG rerank `rag_rerank`

当前前端圆环优先展示最近一次计入上下文窗口的真实 usage：

```text
pressure = latest_context_record.total_tokens / effective_context_window
```

只有在当前 session 还没有真实 usage 记录时，才会退回本地估算。

### 13.3 第二次压缩不是“纯新增 delta 摘要”

新的 summary 是模型基于：

- 旧 summary
- 当前待归档消息
- 当前保留的最近 4 条消息

重新生成的一份 consolidated summary。

它不是简单的：

```text
old_summary + new_delta
```

### 13.4 `restore-checkpoint` 不是自动流程的一部分

它只是一个手动恢复能力，目前不会在主循环中自动触发。

---

## 14. 一句话总结

当前 Newman 的上下文压缩逻辑可以概括为：

- 每次压缩都固定保留最近 `4` 条消息
- 更早的历史会结合旧 summary 一起送给模型，生成一份新的 handoff summary
- 自动压缩阈值按有效上下文窗口 `95%` 口径计算
- 聊天页圆环优先使用最近一次真实模型请求的 `total_tokens / effective_context_window`
- 压缩完成后，后续上下文以“checkpoint.summary + 当前保留的 4 条消息 + 后续新增消息”的形式继续工作
- 前端上下文圆环看的是这份“历史上下文表示”的估算占比，不是每轮真实 token 消耗
