# M06 API & SSE — 接口与事件层

> Newman 模块 PRD · Phase 1 · 预估 6 工作日

---

## 一、模块目标

提供 FastAPI 接口层和 SSE 流式事件协议，连接前端与 Runtime。

---

## 二、功能范围

### ✅ 包含

- 会话管理 API（创建 / 列表 / 恢复 / 删除）
- 消息发送 API
- SSE 统一事件结构（event + data + ts）
- 10 个必须支持的事件类型
- 审批交互 API（approve / reject）
- 工具调用审计日志 API
- request_id 全链路追踪

### ❌ 不包含

- WebSocket
- GraphQL
- 多租户认证

---

## 三、前置依赖

- M04 Runtime（API 调用 Runtime 处理请求）

---

## 四、文件结构

```text
api/
  routes/
    sessions.py           # 会话管理路由
    messages.py           # 消息发送路由
    approvals.py          # 审批交互路由
    audit.py              # 审计日志路由
  sse/
    event_emitter.py      # SSE 事件发射器
    event_types.py        # 事件类型定义
  middleware/
    request_id.py         # request_id 中间件
    error_handler.py      # 全局错误处理
  app.py                  # FastAPI 应用入口
```

---

## 五、核心设计

### SSE 统一事件结构

```json
{
  "event": "<event_type>",
  "data": { "...": "..." },
  "ts": 1741234567890
}
```

### 必须支持的事件类型

| 事件 | 描述 |
|------|------|
| `session_created` | 会话创建成功 |
| `assistant_delta` | 流式文本增量 |
| `tool_call_started` | 工具调用开始 |
| `tool_call_finished` | 工具调用完成 |
| `tool_approval_request` | 需要用户审批 |
| `tool_approval_resolved` | 审批已处理 |
| `tool_error_feedback` | 工具错误反馈 |
| `checkpoint_created` | Checkpoint 已创建 |
| `final_response` | 回合完成 |
| `error` | 系统级错误 |

### API 路由设计

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions` | 列表会话 |
| GET | `/api/sessions/{id}` | 获取会话详情 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/sessions/{id}/messages` | 发送消息（返回 SSE 流） |
| POST | `/api/sessions/{id}/approve` | 审批通过 |
| POST | `/api/sessions/{id}/reject` | 审批拒绝 |

---

## 六、验收标准

1. 所有 SSE 事件可重放
2. 审批事件有超时处理（默认 120 秒）
3. request_id 贯穿日志与事件
4. 流式响应延迟 < 200ms
5. 错误响应使用统一结构（code + message + request_id）

---

## 七、技术备注

- SSE 使用 FastAPI 的 StreamingResponse + async generator
- request_id 通过 middleware 注入，格式为 UUIDv4
- CORS 配置需支持本地前端开发（localhost:3000）
