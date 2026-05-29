# M02 Memory — 记忆与上下文管理

> Newman 模块 PRD · Phase 1 · 预估 7 工作日

---

## 一、模块目标

实现四层记忆模型（System / User / Long-term Experience / Session）和上下文压缩机制，确保"文件即记忆"原则。

---

## 二、功能范围

### ✅ 包含

- Stable Context 加载（Newman.md / USER.md / MEMORY.md / SKILLS_SNAPSHOT.md / TOOLS_SNAPSHOT.md / Tooling Overview）
- Session 存储（sessions/*.json）读写
- USER.md 稳定偏好提取与合并
- MEMORY.md 自进化经验沉淀
- Checkpoint 生成、存储、恢复
- 上下文压缩策略（80% / 92% 双阈值）

### ❌ 不包含

- 向量数据库管理（属于 RAG 模块）
- 多用户记忆隔离

---

## 三、前置依赖

- M01 Provider（压缩需调用 LLM 生成摘要）

---

## 四、文件结构

```text
memory/
  stable_context.py       # Stable Context 加载与拼接
  checkpoint_store.py     # Checkpoint 存储与恢复
  memory_extract.py       # User Memory 提取
  compressor.py           # 上下文压缩器
evolution/
  service.py              # 自进化分析、写入、验证、回滚
  store.py                # 自进化 run、快照和事件日志
sessions/
  session_store.py        # Session JSON 读写
```

---

## 五、核心设计

### 四层记忆模型

| 层级 | 来源 | 特点 |
|------|------|------|
| System Memory | Newman.md | 平台级全局规则，永不压缩 |
| User Memory | USER.md | 用户偏好和交互约定，永不压缩 |
| Long-term Experience Memory | MEMORY.md | Newman 自动沉淀的跨 session 经验，永不压缩 |
| Session Memory | sessions/*.json | 单会话历史事实，主要压缩对象 |

`MEMORY.md` 当前由自进化机制维护，记录可复用的工作流经验、错误恢复经验、工具使用经验和完成标准，不记录单次 session 流水账。

### 上下文压缩策略

- **80% 阈值**：触发时压缩 Working History 中最早的 N 轮对话为摘要
- **92% 阈值**：强制压缩，保留最近 2 轮 + Checkpoint Summary
- 压缩永远只作用于 Working History
- Stable Context、User Memory 与 MEMORY.md 不参与裁剪

### Checkpoint 设计要求

- 可读：用户可直接查看 checkpoint JSON
- 可替换：支持手动编辑
- 可恢复：可显式将 checkpoint 摘要恢复回会话上下文
- 可递归：支持持续递归压缩

---

## 六、验收标准

1. Stable Context 永不被压缩或截断
2. 触发 80% 阈值时自动压缩 Working History
3. 触发 92% 阈值时强制压缩，保留最近 2 条消息 + Checkpoint Summary
4. Checkpoint 可恢复且可读
5. 会话历史 JSON 可用户直接查看/编辑
6. 压缩后的摘要保留关键信息（人工抽样验证）
7. `MEMORY.md` 自动沉淀经验后会进入后续 Stable Context

---

## 七、技术备注

- Session JSON 格式需包含：session_id, created_at, messages[], metadata
- Checkpoint JSON 格式需包含：session_id, checkpoint_id, summary, turn_range, created_at
- 文件路径遵循 workspace 约定，不硬编码绝对路径
