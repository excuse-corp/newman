# Newman API 文档 v1.1

2026 · Phase 4 基线接口 + Stable Memory 抽取 + 轻量多阶段规划

本文档对应当前已落地的 FastAPI 接口与 SSE 事件协议实现，覆盖：

- Phase 2：知识检索与错误恢复基线
- Phase 3：插件/Skill、MCP bridge、Scheduler
- Phase 4：前端工作台所需工作区接口、会话压缩入口、Channels webhook 基线
- Phase 4.5：轻量多阶段任务规划、文件导航与安全编辑工具

代码入口：

- [app.py](/root/newman/backend/api/app.py)
- [sessions.py](/root/newman/backend/api/routes/sessions.py)
- [messages.py](/root/newman/backend/api/routes/messages.py)
- [workspace.py](/root/newman/backend/api/routes/workspace.py)
- [plugins.py](/root/newman/backend/api/routes/plugins.py)
- [mcp.py](/root/newman/backend/api/routes/mcp.py)
- [scheduler.py](/root/newman/backend/api/routes/scheduler.py)
- [channels.py](/root/newman/backend/api/routes/channels.py)

---

## 一、总览

### Base URL

```text
http://localhost:8000
```

### 内容类型

- REST：`application/json`
- SSE：`text/event-stream`

### 请求追踪

每个 HTTP 响应头返回：

```text
x-request-id: <uuid>
```

### 健康检查

`GET /healthz`

响应示例：

```json
{
  "ok": true,
  "version": "0.5.0",
  "provider": "mock",
  "sandbox_enabled": false,
  "tools": [
    "read_file",
    "list_dir",
    "list_files",
    "search_files",
    "grep",
    "fetch_url",
    "terminal",
    "write_file",
    "edit_file",
    "update_plan",
    "search_knowledge_base",
    "mcp__example-inline__echo_context"
  ],
  "knowledge_documents": 1,
  "plugins_enabled": 1,
  "scheduler_running": true,
  "channels_enabled": 2
}
```

`GET /readyz`

响应示例：

```json
{
  "ok": true,
  "knowledge_dir": "/root/newman/backend_data/knowledge",
  "sessions_dir": "/root/newman/backend_data/sessions",
  "plugins_dir": "/root/newman/plugins",
  "skills_dir": "/root/newman/skills",
  "mcp_dir": "/root/newman/backend_data/mcp",
  "scheduler_dir": "/root/newman/backend_data/scheduler",
  "channels_dir": "/root/newman/backend_data/channels"
}
```

### 统一错误格式

```json
{
  "error": {
    "code": "NEWMAN-API-001",
    "message": "请求参数校验失败",
    "severity": "warning",
    "kind": "validation",
    "details": []
  },
  "request_id": "req_xxx"
}
```

---

## 二、当前内置工具

当前内置工具分为 3 类：

- 读取与定位：`read_file`、`list_dir`、`list_files`、`search_files`、`grep`
- 编辑与执行：`write_file`、`edit_file`、`terminal`
- 协作与知识：`update_plan`、`fetch_url`、`search_knowledge_base`

说明：

- `list_files` 是 `list_dir` 的别名。
- `grep` 是 `search_files` 的别名。
- `write_file`、`edit_file`、`terminal` 默认需要审批。
- 若配置了插件 MCP server，运行时还会额外挂载 `mcp__...` 工具。

---

## 三、会话接口

## 3.1 创建会话

`POST /api/sessions`

请求体：

```json
{
  "title": "供应商合同抽取"
}
```

响应体：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "title": "供应商合同抽取",
  "created": true,
  "memory_extraction": {
    "scheduled": true,
    "trigger": "new_session_created",
    "source_session_id": "9a62e9e8a71e4de8bf4f7f721f0a5b22",
    "reason": "background_task_started"
  }
}
```

说明：

- 创建新会话不会等待稳定记忆抽取完成。
- 后端会在响应返回后，后台异步对“上一个非空会话”执行稳定记忆抽取。
- 抽取时优先使用对应会话的 checkpoint JSON；若存在保留中的近期消息，则一并作为补充上下文。
- 抽取结果会按分类分别合并到 `backend_data/memory/USER.md` 与 `backend_data/memory/MEMORY.md`。
- `mock` provider 下不会调度抽取任务，此时 `memory_extraction.scheduled = false`，`reason = "mock_provider"`。

## 3.2 获取会话列表

`GET /api/sessions`

响应体：

```json
[
  {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "title": "供应商合同抽取",
    "created_at": "2026-04-02T08:00:00+00:00",
    "updated_at": "2026-04-02T08:10:00+00:00",
    "message_count": 6
  }
]
```

## 3.3 获取会话详情

`GET /api/sessions/{session_id}`

响应体：

```json
{
  "session": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "title": "供应商合同抽取",
    "messages": [],
    "metadata": {
      "plan": {
        "explanation": "先确认代码结构，再改后端，最后更新前端和文档。",
        "steps": [
          {
            "step": "检查运行时与工具注册点",
            "status": "completed"
          },
          {
            "step": "补齐后端工具与计划状态",
            "status": "in_progress"
          },
          {
            "step": "更新前端展示和 API 文档",
            "status": "pending"
          }
        ],
        "updated_at": "2026-04-03T09:30:00+00:00",
        "current_step": "补齐后端工具与计划状态",
        "progress": {
          "total": 3,
          "completed": 1,
          "in_progress": 1,
          "pending": 1
        }
      }
    },
    "updated_at": "2026-04-02T08:10:00+00:00"
  },
  "plan": {
    "explanation": "先确认代码结构，再改后端，最后更新前端和文档。",
    "steps": [
      {
        "step": "检查运行时与工具注册点",
        "status": "completed"
      },
      {
        "step": "补齐后端工具与计划状态",
        "status": "in_progress"
      },
      {
        "step": "更新前端展示和 API 文档",
        "status": "pending"
      }
    ],
    "updated_at": "2026-04-03T09:30:00+00:00",
    "current_step": "补齐后端工具与计划状态",
    "progress": {
      "total": 3,
      "completed": 1,
      "in_progress": 1,
      "pending": 1
    }
  },
  "checkpoint": null
}
```

说明：

- `session.metadata.plan` 与顶层 `plan` 字段内容相同，后者只是为了前端读取更直接。
- 只有在模型调用 `update_plan` 工具后，`plan` 才会出现。

## 3.4 删除会话

`DELETE /api/sessions/{session_id}`

## 3.5 手动压缩会话

`POST /api/sessions/{session_id}/compress`

响应示例：

```json
{
  "compressed": true,
  "checkpoint": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "checkpoint_id": "cp_xxx",
    "summary": "Checkpoint Summary\n- user: ...",
    "turn_range": [0, 8],
    "created_at": "2026-04-02T10:00:00+00:00",
    "metadata": {}
  }
}
```

---

## 四、消息接口

## 4.1 发送消息并接收 SSE

`POST /api/sessions/{session_id}/messages`

请求体：

```json
{
  "content": "请帮我总结当前工作区的结构"
}
```

响应类型：

```text
text/event-stream
```

当前实现说明：

- 通过 Runtime 进入主循环
- 默认 Provider 为 `mock`
- 支持普通消息和 `/tool ...` 调试指令
- 插件 hook 会通过 `hook_triggered` 事件回传
- 结束时统一发送 `stream_completed`

示例：

```text
/tool read_file {"path":"/root/newman/docs/prds/Newman_PRD_v9.md"}
/tool list_dir {"path":"backend","recursive":false}
/tool search_files {"query":"handle_message","path":"backend","glob":"*.py"}
/tool edit_file {"path":"README.md","edits":[{"old_text":"old","new_text":"new"}]}
/tool update_plan {"steps":[{"step":"检查现状","status":"completed"},{"step":"实现后端","status":"in_progress"},{"step":"更新前端","status":"pending"}]}
/tool search_knowledge_base {"query":"混合检索","limit":3}
/tool mcp__example-inline__echo_context {"text":"hello"}
```

---

## 五、审批接口

## 5.1 审批通过

`POST /api/sessions/{session_id}/approve`

## 5.2 审批拒绝

`POST /api/sessions/{session_id}/reject`

---

## 六、审计接口

## 6.1 获取审计日志

`GET /api/audit/{session_id}`

响应体：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "events": [
    "{\"event\":\"tool_call_started\",\"data\":{\"tool\":\"read_file\"}}"
  ]
}
```

---

## 七、工作区接口

这些接口主要服务 Phase 4 前端工作台。

## 7.1 获取 Stable Memory 文件

`GET /api/workspace/memory`

响应示例：

```json
{
  "files": {
    "newman": {
      "path": "/root/newman/backend_data/memory/Newman.md",
      "content": "# Newman System Prompt ..."
    },
    "user": {
      "path": "/root/newman/backend_data/memory/USER.md",
      "content": "# USER.md\n\n<!-- BEGIN AUTO USER MEMORY -->\n## User Memory\n仅记录跨 session 稳定成立的用户偏好、沟通方式和长期协作约定，不记录一次性任务或项目事实。\n\n- 暂无条目\n<!-- END AUTO USER MEMORY -->"
    },
    "memory": {
      "path": "/root/newman/backend_data/memory/MEMORY.md",
      "content": "# MEMORY.md\n\n<!-- BEGIN AUTO MEMORY -->\n## Long-term Memory\n仅记录跨 session 仍有价值的客观事实，不记录偏好、系统规则或临时任务。\n\n- 暂无条目\n<!-- END AUTO MEMORY -->"
    }
  }
}
```

## 7.2 更新 Stable Memory 文件

`PUT /api/workspace/memory/{memory_key}`

支持的 `memory_key`：

- `newman`
- `user`
- `skills`
- `memory`

请求体：

```json
{
  "content": "# Updated memory"
}
```

## 7.3 浏览工作区文件

`GET /api/workspace/files?path=.`

目录响应：

```json
{
  "path": "/root/newman",
  "type": "dir",
  "entries": [
    {
      "name": "backend",
      "path": "/root/newman/backend",
      "type": "dir"
    }
  ]
}
```

文件响应：

```json
{
  "path": "/root/newman/docs/Newman_API_v1.md",
  "type": "file",
  "content": "# Newman API 文档 ..."
}
```

---

## 八、知识库接口

## 8.1 导入知识文档

`POST /api/knowledge/documents/import`

请求体：

```json
{
  "source_path": "docs/prds/M07_RAG.md"
}
```

说明：

- 仅支持 workspace 内文件
- 当前支持文本类文件：`.md`、`.txt`、`.json`、`.csv`、`.py`、`.yaml`、`.yml`、`.log`

## 8.2 列出知识文档

`GET /api/knowledge/documents`

## 8.3 搜索知识库

`POST /api/knowledge/search`

请求体：

```json
{
  "query": "混合检索",
  "limit": 3
}
```

---

## 九、插件与 Skill 接口

## 9.1 获取插件列表

`GET /api/plugins`

## 9.2 重新扫描插件

`POST /api/plugins/rescan`

## 9.3 启用插件

`POST /api/plugins/{plugin_name}/enable`

## 9.4 禁用插件

`POST /api/plugins/{plugin_name}/disable`

## 9.5 获取 Skill 列表

`GET /api/skills`

响应示例：

```json
{
  "skills": [
    {
      "name": "session_review",
      "source": "workspace",
      "plugin_name": null,
      "path": "/root/newman/skills/session_review/SKILL.md",
      "summary": "Use this skill when you want to review what happened in a session and identify the next best action."
    }
  ]
}
```

说明：

- 运行时会动态生成 `backend_data/memory/SKILLS_SNAPSHOT.md`
- 具体 Skill 正文仍建议通过工作区文件或 `read_file` 按需读取
- `backend_data/memory/USER.md` 与 `backend_data/memory/MEMORY.md` 会被后台稳定记忆抽取逻辑自动合并更新

---

## 十、MCP 接口

当前实现是 Phase 3/4 的 bridge 基线，不是完整官方 MCP 协议栈。

## 10.1 获取 MCP Server 列表与状态

`GET /api/mcp/servers`

## 10.2 创建或更新 MCP Server

`POST /api/mcp/servers`

请求体示例：

```json
{
  "name": "my-inline",
  "transport": "inline",
  "enabled": true,
  "requires_approval": false,
  "timeout_seconds": 20,
  "headers": {},
  "tools": [
    {
      "name": "echo_text",
      "description": "Return inline MCP output",
      "input_schema": {
        "type": "object",
        "properties": {
          "text": {
            "type": "string"
          }
        },
        "required": ["text"]
      },
      "risk_level": "low"
    }
  ]
}
```

---

## 十一、Scheduler 接口

## 11.1 获取任务列表

`GET /api/scheduler/tasks`

## 11.2 创建任务

`POST /api/scheduler/tasks`

请求体：

```json
{
  "name": "phase4-check",
  "cron": "*/30 * * * *",
  "action": {
    "type": "background_task",
    "prompt": "请总结今天的变更"
  },
  "enabled": true,
  "max_retries": 0
}
```

## 11.3 启用任务

`POST /api/scheduler/tasks/{task_id}/enable`

## 11.4 禁用任务

`POST /api/scheduler/tasks/{task_id}/disable`

## 11.5 立即执行任务

`POST /api/scheduler/tasks/{task_id}/run`

说明：

- 当前实现使用内置轮询引擎，不依赖 APScheduler
- 支持 `session_message` 和 `background_task`
- 任务配置保存在 `backend_data/scheduler/tasks.json`

---

## 十二、Channels 接口

当前实现是本地联调友好的 Phase 4 基线：

- 支持 `feishu`、`wecom`
- 支持 webhook 基础验签
- 支持将 IM 用户映射到 Newman session
- 当前 webhook 响应返回标准化 payload，尚未真正推送回 IM 平台

## 12.1 获取 Channel 状态

`GET /api/channels/status`

响应示例：

```json
{
  "channels": [
    {
      "platform": "feishu",
      "enabled": true,
      "webhook_token_configured": false
    },
    {
      "platform": "wecom",
      "enabled": true,
      "webhook_token_configured": false
    }
  ]
}
```

## 12.2 飞书 Webhook

`POST /api/channels/feishu/webhook`

请求体示例：

```json
{
  "event": {
    "open_id": "u-1",
    "chat_id": "c-1",
    "text": "你好"
  }
}
```

响应示例：

```json
{
  "ok": true,
  "response": {
    "platform": "feishu",
    "user_id": "u-1",
    "session_id": "session_xxx",
    "format": "text",
    "content": "[mock] Newman 已收到你的消息：你好"
  }
}
```

## 12.3 企业微信 Webhook

`POST /api/channels/wecom/webhook`

请求体示例：

```json
{
  "event": {
    "from_user": "wx-user-1",
    "chat_id": "room-a",
    "content": "请给我今天的摘要"
  }
}
```

验签说明：

- 若配置了 `channels.feishu.webhook_token` 或 `channels.wecom.webhook_token`
- 可通过请求头 `x-newman-channel-token` 或 body 中的 `token` 字段传入

---

## 十三、SSE 事件协议

### 统一格式

```json
{
  "event": "<event_type>",
  "data": { "...": "..." },
  "ts": 1741234567890
}
```

### 当前已实现事件

- `assistant_delta`
- `tool_call_started`
- `tool_call_finished`
- `tool_retry_scheduled`
- `hook_triggered`
- `plan_updated`
- `tool_approval_request`
- `tool_approval_resolved`
- `tool_error_feedback`
- `checkpoint_created`
- `final_response`
- `stream_completed`
- `error`

### 事件示例

#### `hook_triggered`

```json
{
  "event": "hook_triggered",
  "data": {
    "event": "SessionStart",
    "message": "example-plugin: Example plugin observed a new session round.",
    "context": {
      "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
      "content": "请帮我总结当前工作区"
    }
  },
  "ts": 1741234567890
}
```

#### `tool_error_feedback`

```json
{
  "event": "tool_error_feedback",
  "data": {
    "tool": "fetch_url",
    "category": "network_error",
    "error_code": "NEWMAN-TOOL-999",
    "severity": "error",
    "summary": "域名未在白名单内: example.com",
    "retryable": false,
    "attempt_count": 1
  },
  "ts": 1741234567890
}
```

#### `plan_updated`

```json
{
  "event": "plan_updated",
  "data": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "summary": "计划已更新，完成 1/3 步",
    "plan": {
      "explanation": "先确认代码结构，再改后端，最后更新前端和文档。",
      "steps": [
        {
          "step": "检查运行时与工具注册点",
          "status": "completed"
        },
        {
          "step": "补齐后端工具与计划状态",
          "status": "in_progress"
        },
        {
          "step": "更新前端展示和 API 文档",
          "status": "pending"
        }
      ],
      "updated_at": "2026-04-03T09:30:00+00:00",
      "current_step": "补齐后端工具与计划状态",
      "progress": {
        "total": 3,
        "completed": 1,
        "in_progress": 1,
        "pending": 1
      }
    }
  },
  "ts": 1741234567890
}
```

#### `stream_completed`

```json
{
  "event": "stream_completed",
  "data": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "ok": true
  },
  "ts": 1741234567890
}
```

---

## 十四、当前边界

当前 Phase 4 已可用，但仍有边界：

- 前端基于现有 Vite/React 工作台，不是 Next.js 架构
- hook 目前是声明式消息回调，不执行任意脚本
- MCP 目前是 bridge 基线，不是完整官方 MCP 协议栈
- Scheduler 当前使用内置 cron 解析与轮询执行
- Channels 当前返回标准化 webhook 响应，尚未接入真实飞书/企微发送端
