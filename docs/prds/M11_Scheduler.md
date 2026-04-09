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
  alert_store.py          # 失败告警持久化
```

---

## 五、核心设计

### 任务定义

```json
{
  "tasks": [
    {
      "task_id": "daily-report",
      "name": "日报生成",
      "cron": "0 18 * * 1-5",
      "action": {
        "type": "session_message",
        "prompt": "请根据今天的工作记录生成日报",
        "session_id": "session-123"
      },
      "enabled": true,
      "max_retries": 2
    }
  ]
}
```

### 调度流程

```text
SchedulerEngine 定期检查到期任务
  ↓
方式 A：注入到指定会话（session_message）
方式 B：创建新后台会话执行（background_task）
  ↓
任务状态更新（pending → running → completed / failed）
  ↓
失败时写入告警记录（alerts.json）
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

- 当前实现使用内置轮询调度引擎，不依赖 APScheduler
- 任务定义存储在 `backend_data/scheduler/tasks.json`
- 失败告警存储在 `backend_data/scheduler/alerts.json`
- 后台任务创建的会话标记为 `background: true`

---

## 八、当前完成度说明

截至当前版本，M11 已完成：

- 任务定义与持久化
- 5 段 Cron 表达式解析
- `session_message` 与 `background_task` 两种执行方式
- 任务状态追踪
- 失败自动重试
- 失败告警持久化与查询
- 任务删除接口

当前仍未完成：

- APScheduler 接入
- 独立 `event_injector.py` 模块
- 分布式调度 / 工作流编排
