# M08 Error Recovery — 统一错误恢复

> Newman 模块 PRD · Phase 2 · 预估 5 工作日

---

## 一、模块目标

实现结构化错误分类、错误码映射、可恢复/致命分流和双消费者（模型+前端）错误摘要。

---

## 二、功能范围

### ✅ 包含

- 错误分类体系（可恢复 vs 致命）
- 统一错误码映射
- 错误摘要模板（同时服务模型和前端）
- 透明重试策略
- 错误回灌机制

### ❌ 不包含

- 自动故障转移
- 外部告警

---

## 三、前置依赖

- M03 Tools（工具错误来源）
- M04 Runtime（错误在 RunLoop 中处理）

---

## 四、文件结构

```text
runtime/
  error_classifier.py     # 错误分类器
  feedback_writer.py      # 错误摘要生成器
  error_codes.py          # 统一错误码定义
  retry_policy.py         # 重试策略
```

---

## 五、核心设计

### 错误分类

| 类型 | 处理方式 | 示例 |
|------|----------|------|
| 可恢复 | 回灌给模型继续处理 | 命令执行失败、文件不存在、网络超时 |
| 致命 | 终止当前回合 | 认证失败、沙箱崩溃、模型拒绝响应 |

### 错误摘要模板

```text
The previous action failed.

Tool: {tool}
Action: {action}
Category: {category}
Exit code: {exit_code}
Retryable: {retryable}

Summary:
{summary}

Key output:
{key_output}

Recommended next step:
{recommended_next_step}
```

### 双消费者设计

| 消费者 | 需要 |
|--------|------|
| 模型 | 最小必要上下文 + 建议下一步 |
| 前端 | 可读错误状态 + 风险级别 + 错误码 |

### 重试策略

- 最大重试次数：3（可配置）
- 退避策略：指数退避（1s, 2s, 4s）
- 仅对标记为 retryable 的错误自动重试
- 重试透明于模型（重试成功则不感知失败）

---

## 六、验收标准

1. 所有工具错误均被分类为可恢复或致命
2. 可恢复错误自动回灌给模型并继续处理
3. 错误摘要同时包含模型可理解的下一步建议和前端可展示的风险级别
4. 重试策略正确执行且对模型透明
5. 统一错误码可被前端直接用于 i18n 映射

---

## 七、技术备注

- 错误码格式建议：`NEWMAN-{MODULE}-{NUMBER}`，如 `NEWMAN-TOOL-001`
- ErrorClassifier 基于规则匹配，不依赖 LLM
- FeedbackWriter 生成的摘要需控制在 500 tokens 以内
