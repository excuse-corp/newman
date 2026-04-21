# M04 Runtime — Agent 运行时内核

> Newman 模块 PRD · Phase 1 · 预估 8 工作日

---

## 一、模块目标

实现 Agent 主循环，包括 ThreadManager、SessionTask、PromptAssembler、RunLoop，完成从用户输入到响应输出的完整链路。

---

## 二、功能范围

### ✅ 包含

- ThreadManager（会话创建 / 恢复 / 列表 / 删除）
- SessionTask（单轮执行容器）
- PromptAssembler（三层 Prompt 拼接）
- RunLoop（模型调用 → tool_call 判断 → 结果归一化 → 循环）
- ErrorClassifier（错误分类）
- FeedbackWriter（错误摘要生成）
- ResultNormalizer（工具结果归一化写回 history）
- 单轮最大工具调用深度控制（默认 30）

### ❌ 不包含

- 多 Agent 协作
- 后台任务队列

---

## 三、前置依赖

- M01 Provider（LLM 调用）
- M02 Memory（上下文管理）
- M03 Tools（工具路由与执行）

---

## 四、文件结构

```text
runtime/
  thread_manager.py       # 会话生命周期管理
  session_task.py         # 单轮执行容器
  prompt_assembler.py     # 三层 Prompt 拼接
  run_loop.py             # Agent 主循环
  error_classifier.py     # 错误分类器
  feedback_writer.py      # 错误摘要生成
  result_normalizer.py    # 结果归一化
```

---

## 五、核心设计

### 生命周期

```text
用户输入
  ↓
ThreadManager 创建或恢复线程
  ↓
SessionTask 初始化
  ↓
PromptAssembler 拼接三层上下文
  ↓
TokenEstimator 判断是否压缩
  ↓
RunLoop 调用模型
  ↓
如果无 tool_call → TurnComplete
如果有 tool_call → ToolRouter → ToolOrchestrator → Tool Runtime
  ↓
ResultNormalizer → ErrorClassifier → FeedbackWriter
  ↓
继续循环或完成回合
  ↓
写回 session / memory / metrics / SSE
```

### SessionTask 持有

- 当前 Thread / Session 数据
- 审批上下文
- 工具调用计数器

### Prompt 三层模型

| 层 | 内容 | 规则 |
|----|------|------|
| Stable Context | Newman.md, USER.md, SKILLS_SNAPSHOT.md, 工具列表 | 永不压缩、永不截断、每轮重新装载 |
| Working History | user / assistant / tool_call / tool_result 消息 | 主要压缩对象 |
| Checkpoint Summary | 结构化摘要 | 上下文超限时替换旧 Working History |

### RunLoop 约束

- 单轮最大工具调用深度默认 30
- 工具结果必须归一化后再写回 history
- 所有工具错误与 Provider 可恢复错误都必须以反馈形式写回 history
- 只有致命错误才中断当前回合
- 工具调用深度超限时，不直接空中断，而是基于已有上下文优雅降级收口

---

## 六、验收标准

1. 完整链路：用户输入 → Prompt 拼接 → LLM 调用 → 工具执行 → 结果归一化 → 响应输出
2. 工具错误与 Provider 可恢复错误自动回灌给模型继续处理
3. 致命错误终止当前回合并返回结构化错误
4. 工具调用深度超限时优雅降级（返回当前已有结果 + 提示用户可输入“继续”）
5. 会话恢复后能从 Checkpoint 继续

---

## 七、技术备注

- 当前 RunLoop 使用手写循环而非 LangGraph StateGraph
- SessionTask 生命周期与单次 API 请求绑定
- 所有状态变更通过 SSE 事件推送给前端
