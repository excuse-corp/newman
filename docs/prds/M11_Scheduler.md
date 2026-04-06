# M11 Scheduler — 定时任务

> Newman 模块 PRD · Phase 3 · 预估 5 工作日

---

## 一、模块目标

实现定时任务调度，支持触发事件注入对话或后台任务队列。

---

## 二、功能范围

### ✅ 包含

- 任务定义与存储
- Cron 表达式解析
- 任务触发与事件注入
- 任务状态追踪

### ❌ 不包含

- 分布式任务队列
- 复杂工作流编排

---

## 三、前置依赖

- M04 Runtime（任务触发需创建 SessionTask）
- M06 API & SSE（事件注入通过 SSE 推送）

---

## 四、文件结构

```text
scheduler/
  task_store.py           # 任务定义与持久化
  cron_parser.py          # Cron 表达式解析
  scheduler_engine.py     # 调度引擎
  event_injector.py       # 事件注入器
```

---

## 五、核心设计

### 任务定义

```yaml
tasks:
  - id: daily-report
    name: 日报生成
    cron: "0 18 * * 1-5"
    action:
      type: session_message
      prompt: "请根据今天的工作记录生成日报"
    enabled: true
    max_retries: 2
```

### 调度流程

```text
SchedulerEngine 定期检查到期任务
  ↓
EventInjector 生成事件
  ↓
方式 A：注入到指定会话（session_message）
方式 B：创建新后台会话执行（background_task）
  ↓
任务状态更新（pending → running → completed / failed）
```

### 任务状态

| 状态 | 描述 |
|------|------|
| pending | 等待触发 |
| running | 执行中 |
| completed | 执行完成 |
| failed | 执行失败 |
| disabled | 已禁用 |

---

## 六、验收标准

1. 定时任务按 Cron 表达式准时触发（误差 < 5 秒）
2. 触发事件能注入对话或后台执行
3. 任务失败时有重试和告警机制
4. 任务状态可查询

---

## 七、技术备注

- 使用 APScheduler 作为调度引擎
- 任务定义存储在 `tasks.yaml` 文件中（文件即数据源）
- 后台任务创建的会话标记为 `background: true`
