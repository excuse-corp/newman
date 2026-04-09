# Newman API 文档 v1.2

2026 · Phase 4 基线接口 + Stable Memory 抽取 + 轻量多阶段规划 + Linux 原生沙箱

本文档对应当前已落地的 FastAPI 接口与 SSE 事件协议实现，覆盖：

- Phase 2：知识检索与错误恢复基线
- Phase 3：插件/Skill、MCP bridge、Scheduler
- Phase 4：前端工作台所需工作区接口、会话压缩入口、Channels webhook 基线
- Phase 4.5：轻量多阶段任务规划、文件导航与安全编辑工具
- Phase 4.6：Linux 原生终端沙箱（bubblewrap）

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
http://localhost:8005
```

### 推荐启动方式

```bash
conda activate newman
./scripts/dev/start_postgres.sh
uvicorn backend.main:app --reload
```

本地默认依赖：

- PostgreSQL: `127.0.0.1:65437`
- Database: `newman`
- Chroma 持久化目录: `backend_data/chroma/`
- 知识文档与解析产物目录: `backend_data/knowledge/`

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
  "version": "0.6.0",
  "provider": "mock",
  "sandbox_enabled": true,
  "sandbox": {
    "enabled": true,
    "backend": "linux_bwrap",
    "mode": "workspace-write",
    "platform": "linux",
    "platform_supported": true,
    "available": true,
    "network_access": false
  },
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
    "risk_level": "low",
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
- `write_file`、`edit_file` 默认需要审批。
- `terminal` 采用两级前置审批：Level 1 黑名单直接拒绝，Level 2 风险模式进入人工审批；Linux 沙箱内的明显只读命令会自动放行。
- 若配置了插件 MCP server，运行时还会额外挂载 `mcp__...` 工具。
- `terminal` 在 Linux 下默认走原生沙箱；当前阶段仅实现 Linux，macOS / Windows 为待做。

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

- `/api/sessions` 返回普通 JSON，适合常规创建流程。
- 若前端需要把“会话创建成功”也纳入统一事件流，可使用 `/api/sessions/stream`。

说明：

- 创建新会话不会等待稳定记忆抽取完成。
- 后端会在响应返回后，后台异步对“上一个非空会话”执行 `USER.md` 稳定偏好抽取。
- 抽取时优先使用对应会话的 checkpoint JSON；若存在保留中的近期消息，则一并作为补充上下文。
- 抽取结果会合并到 `backend_data/memory/USER.md`。
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

## 3.2A 流式创建会话

`POST /api/sessions/stream`

响应类型：

```text
text/event-stream
```

事件示例：

```json
{
  "event": "session_created",
  "data": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "title": "供应商合同抽取",
    "created": true,
    "memory_extraction": {
      "scheduled": true,
      "trigger": "new_session_created",
      "source_session_id": "9a62e9e8a71e4de8bf4f7f721f0a5b22",
      "reason": "background_task_started"
    }
  },
  "ts": 1741234567890,
  "request_id": "req_xxx"
}
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

## 3.3A 获取会话结构化事件历史

`GET /api/sessions/{session_id}/events`

查询参数：

- `limit`: 可选，默认 `200`，返回最近 N 条结构化事件

响应示例：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "events": [
    {
      "event": "tool_call_started",
      "data": {
        "tool": "read_file",
        "arguments": {
          "path": "/root/newman/README.md"
        }
      },
      "request_id": "req_xxx",
      "ts": 1741234567890
    },
    {
      "event": "tool_call_finished",
      "data": {
        "tool": "read_file",
        "success": true,
        "summary": "文件已读取完成"
      },
      "request_id": "req_xxx",
      "ts": 1741234567999
    }
  ]
}
```

说明：

- 该接口面向前端恢复 timeline / trace / 审批状态，返回结构化事件数组。
- 数据源复用会话审计日志，但会过滤为 `event/data/request_id/ts` 结构。
- 返回顺序与原始事件写入顺序一致。
- 若当前会话没有审计日志，则返回空数组。

## 3.4 删除会话

`DELETE /api/sessions/{session_id}`

## 3.4A 重命名会话

`PATCH /api/sessions/{session_id}`

请求体：

```json
{
  "title": "新的会话标题"
}
```

响应示例：

```json
{
  "updated": true,
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "title": "新的会话标题",
  "updated_at": "2026-04-08T08:10:00+00:00"
}
```

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
    "metadata": {
      "preserve_recent": 4,
      "compression_level": "manual",
      "original_message_count": 12
    }
  }
}
```

说明：

- 运行时自动压缩分两档：
  - 普通压缩：命中 `context_compress_threshold`，保留最近 4 条消息
  - 强制压缩：命中 `context_critical_threshold`，保留最近 2 条消息

## 3.6 恢复 Checkpoint

`POST /api/sessions/{session_id}/restore-checkpoint`

响应示例：

```json
{
  "restored": true,
  "checkpoint": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "checkpoint_id": "cp_xxx",
    "summary": "Checkpoint Summary\n- user: ...",
    "turn_range": [0, 8],
    "created_at": "2026-04-02T10:00:00+00:00",
    "metadata": {
      "preserve_recent": 2,
      "compression_level": "critical",
      "original_message_count": 18
    }
  },
  "session": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "title": "供应商合同抽取",
    "messages": []
  }
}
```

说明：

- 恢复不会重建原始 Working History。
- 当前实现会把 checkpoint 摘要恢复为一条显式的 `system` message，并重新纳入后续上下文。

---

## 四、消息接口

## 4.1 发送消息并接收 SSE

`POST /api/sessions/{session_id}/messages`

请求体：

```json
{
  "content": "请帮我总结当前工作区的结构",
  "approval_mode": "manual"
}
```

也支持 `multipart/form-data`：

- `content`: 文本内容，可为空
- `images`: 可重复上传的图片字段，仅支持 `jpg/jpeg/png`
- `approval_mode`: 可选，支持：
  - `manual`：本轮每个命中 Level 2 的工具都需要点击确认
  - `auto_approve_level2`：本轮命中的 Level 2 工具默认放行

当上传图片时，后端会：

1. 保存原始图片到 `backend_data/uploads/chat/{session_id}/`
2. 调用 `models.multimodal` 做图片解析
3. 将图片解析摘要拼接进本轮用户输入
4. 把附件信息写入该条 user message 的 `metadata.attachments`

审批模式说明：

- `approval_mode` 会随本轮用户消息一起写入该条 user message 的 `metadata.approval_mode`
- 后端按该次请求提交的值锁定本轮审批策略
- 用户发送后即使在前端切换 UI 选项，也不会影响已经开始执行的这一轮
- 未传 `approval_mode` 时，默认值为 `manual`

响应类型：

```text
text/event-stream
```

当前实现说明：

- 通过 Runtime 进入主循环
- 默认 Provider 为 `mock`
- 支持普通消息和 `/tool ...` 调试指令
- 支持图片附件与多模态预解析
- 单轮最大工具调用深度默认 30
- 插件 hook 会通过 `hook_triggered` 事件回传
- 结束时统一发送 `stream_completed`

工具深度上限说明：

- 当单轮工具调用达到 `max_tool_depth` 上限时，后端不会直接中断成空错误
- 当前实现会禁止继续调用新工具，并基于已有上下文输出一个阶段性答复
- 最终答复会明确提示用户：已到当前使用工具上限，可以输入“继续”
- 此时 `final_response.finish_reason = "tool_limit_reached"`

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

`GET /api/sessions/{session_id}/pending-approval`

响应示例：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "pending": {
    "approval_request_id": "apr_xxx",
    "tool": "terminal",
    "arguments": {
      "command": "echo hi > /tmp/x"
    },
    "reason": "terminal_mutation_or_unknown",
    "timeout_seconds": 120,
    "remaining_seconds": 78
  }
}
```

若当前没有待审批请求：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "pending": null
}
```

`POST /api/sessions/{session_id}/approve`

请求体：

```json
{
  "approval_request_id": "apr_xxx"
}
```

响应示例：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "approval_request_id": "apr_xxx",
  "approved": true
}
```

## 5.2 审批拒绝

`POST /api/sessions/{session_id}/reject`

请求体：

```json
{
  "approval_request_id": "apr_xxx"
}
```

响应示例：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "approval_request_id": "apr_xxx",
  "approved": false
}
```

---

## 六、审计接口

## 6.1 获取审计日志

`GET /api/audit/{session_id}`

响应体：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "events": [
    "{\"event\":\"tool_call_started\",\"data\":{\"tool\":\"read_file\"},\"request_id\":\"req_xxx\"}"
  ]
}
```

说明：

- 这是调试接口，返回原始审计日志行，不保证适合前端直接恢复 timeline。
- 前端恢复会话过程状态时，优先使用 `GET /api/sessions/{session_id}/events`。

---

## 七、工作区接口

这些接口主要服务 Phase 4 前端工作台。

## 7.1 获取 Stable Memory 文件

`GET /api/workspace/memory`

响应示例：

```json
{
  "latest_updated_at": "2026-04-09T09:00:00+00:00",
  "files": {
    "newman": {
      "path": "/root/newman/backend_data/memory/Newman.md",
      "content": "# Newman System Prompt ...",
      "updated_at": "2026-04-09T08:55:00+00:00"
    },
    "user": {
      "path": "/root/newman/backend_data/memory/USER.md",
      "content": "# USER.md\n\n<!-- BEGIN AUTO USER MEMORY -->\n## User Memory\n仅记录跨 session 稳定成立的用户偏好、沟通方式和长期协作约定，不记录一次性任务或项目事实。\n\n- 暂无条目\n<!-- END AUTO USER MEMORY -->",
      "updated_at": "2026-04-09T09:00:00+00:00"
    },
    "memory": {
      "path": "/root/newman/backend_data/memory/MEMORY.md",
      "content": "# MEMORY.md\n\n长期记忆内容 ...",
      "updated_at": "2026-04-09T08:30:00+00:00"
    },
    "skills": {
      "path": "/root/newman/backend_data/memory/SKILLS_SNAPSHOT.md",
      "content": "# SKILLS_SNAPSHOT.md\n\n当前可用 skill 快照 ...",
      "updated_at": "2026-04-09T08:40:00+00:00"
    }
  }
}
```

说明：

- `latest_updated_at` 用于前端展示“最近一次记忆更新时间”。
- 若某个 memory 文件尚不存在，则其 `content` 为空字符串，`updated_at` 为 `null`。

## 7.2 更新 Stable Memory 文件

`PUT /api/workspace/memory/{memory_key}`

支持的 `memory_key`：

- `newman`
- `user`
- `memory`
- `skills`

请求体：

```json
{
  "content": "# Updated memory"
}
```

响应示例：

```json
{
  "saved": true,
  "memory_key": "memory",
  "path": "/root/newman/backend_data/memory/MEMORY.md",
  "updated_at": "2026-04-09T09:10:00+00:00"
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
- 文档类解析支持：`.pdf`、`.docx`、`.pptx`、`.xlsx`
- 若是图片文件，请改用 `/api/knowledge/documents/upload`

## 8.2 列出知识文档

`GET /api/knowledge/documents`

响应示例：

```json
{
  "documents": [
    {
      "document_id": "doc_xxx",
      "title": "M07_RAG.md",
      "source_path": "docs/prds/M07_RAG.md",
      "stored_path": "/root/newman/backend_data/knowledge/doc_xxx_M07_RAG.md",
      "size_bytes": 12456,
      "content_type": "text/markdown",
      "parser": "text",
      "chunk_count": 12,
      "page_count": null,
      "imported_at": "2026-04-08T09:00:00+00:00"
    }
  ]
}
```

说明：

- Files Workspace 中的“最近上传或引用文件”“文档解析状态”可直接基于该接口返回的结构化字段渲染。
- 若前端需要打开某个知识文件正文，可结合 `stored_path` 调用 `GET /api/workspace/files?path=...`。

## 8.3 上传知识文档

`POST /api/knowledge/documents/upload`

请求类型：

```text
multipart/form-data
```

字段：

- `file`: 单个文件

支持类型：

- 文本类：`.md`、`.txt`、`.json`、`.csv`、`.py`、`.yaml`、`.yml`、`.log`
- 文档类：`.pdf`、`.docx`、`.pptx`、`.xlsx`
- 图片类：`.jpg`、`.jpeg`、`.png`

说明：

- 文档类会执行“解析 -> 切块 -> embedding -> PostgreSQL + Chroma 入库”
- 图片类会先调用 `models.multimodal` 解析，再以文本摘要形式入库
- 文档元数据、chunk 映射、搜索统计和引用记录存 PostgreSQL
- 向量索引存 Chroma 持久化目录
- 检索命中后会为 Top-N 结果记录 citation usage，便于后续统计与溯源

## 8.4 搜索知识库

`POST /api/knowledge/search`

请求体：

```json
{
  "query": "混合检索",
  "limit": 3
}
```

返回结果字段包含：

- `lexical_score`
- `vector_score`
- `rerank_score`
- `chunk_id`
- `chunk_index`
- `page_number`
- `location_label`
- `citation`

`citation` 结构示例：

```json
{
  "document_id": "doc_xxx",
  "title": "M07_RAG.md",
  "stored_path": "/root/newman/backend_data/knowledge/doc_xxx_M07_RAG.md",
  "chunk_id": "doc_xxx_3",
  "chunk_index": 3,
  "page_number": 5,
  "location_label": "page 5",
  "snippet": "关键片段预览文本..."
}
```

---

## 九、插件与 Skill 接口

## 9.1 获取插件列表

`GET /api/plugins`

响应示例：

```json
{
  "plugins": [
    {
      "name": "example-plugin",
      "version": "1.0.0",
      "description": "Example Phase 3 plugin with a sample skill, hooks, and inline MCP server.",
      "enabled": true,
      "plugin_path": "/root/newman/plugins/example-plugin",
      "skill_count": 1,
      "hook_count": 5,
      "mcp_server_count": 1
    }
  ],
  "errors": [
    {
      "plugin_path": "/root/newman/plugins/broken-plugin",
      "plugin_name": "broken-plugin",
      "message": "Hook handler not found: hooks/missing.py"
    }
  ]
}
```

说明：

- `plugins` 是已成功加载的插件
- `errors` 是扫描时发现但未能加载的插件校验错误
- 后端会在每轮新消息开始前自动感知 `plugins/` 和 `skills/` 目录变化，并在下一轮重建插件生态
- 也可以手动调用 `/api/plugins/rescan` 立即刷新

## 9.2 重新扫描插件

`POST /api/plugins/rescan`

返回结构与 `GET /api/plugins` 一致，额外包含：

```json
{
  "reloaded": true
}
```

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
      "description": "Review what happened in a session and identify the best next step.",
      "when_to_use": "Use when the user asks for a recap, retrospective, unblock plan, or next-step review of a session.",
      "summary": "Review what happened in a session and identify the best next step."
    }
  ]
}
```

说明：

- 运行时会动态生成 `backend_data/memory/SKILLS_SNAPSHOT.md`
- `SKILLS_SNAPSHOT.md` 只负责告诉模型“有哪些 skill 可用、什么时候该用”
- 具体 Skill 正文建议通过工作区文件或 `read_file` 按需读取
- `backend_data/memory/USER.md` 会被后台稳定记忆抽取逻辑自动合并更新
- 已启用插件中的 skill 会和工作区 `skills/` 下的 skill 合并进入同一个 snapshot
- 插件启停或 skill 文件变更后，下一轮 prompt 会使用最新 snapshot
- 当前列表只返回“当前可用”的 skill：workspace skill + 已启用 plugin skill

## 9.6 获取 Skill 详情

`GET /api/skills/{skill_name}`

响应示例：

```json
{
  "skill": {
    "name": "writer",
    "source": "workspace",
    "plugin_name": null,
    "path": "/root/newman/skills/writer/SKILL.md",
    "description": "Write and refine deliverables.",
    "when_to_use": null,
    "summary": "Write and refine deliverables.",
    "content": "---\nname: writer\ndescription: Write and refine deliverables.\n---\n\n## Workflow\n...",
    "readonly": false,
    "available": true,
    "tool_dependencies": ["read_file", "write_file"],
    "usage_limits_summary": "- Do not modify unrelated files. - Only change what is required.",
    "directory_path": "/root/newman/skills/writer"
  }
}
```

字段说明：

- `readonly = true` 表示该 skill 来自 plugin 或其他只读来源，不能通过管理接口修改
- `tool_dependencies` 为根据 `SKILL.md` 内容提取出的工具依赖摘要
- `usage_limits_summary` 为根据 `SKILL.md` 中的约束/限制段落提取出的简要说明

## 9.7 导入 Workspace Skill

`POST /api/skills/import`

请求体：

```json
{
  "source_path": "imports/reviewer"
}
```

说明：

- `source_path` 只允许为 workspace 内部的 skill 文件夹路径
- 目标文件夹内必须包含 `SKILL.md`
- 导入行为会把整个 skill 文件夹复制到工作区 `skills/` 目录下，并立即刷新 snapshot

响应示例：

```json
{
  "skill": {
    "name": "reviewer",
    "source": "workspace",
    "plugin_name": null,
    "path": "/root/newman/skills/reviewer/SKILL.md",
    "description": "Review a change.",
    "when_to_use": null,
    "summary": "Review a change.",
    "content": "---\nname: reviewer\ndescription: Review a change.\n---\n\nReview things carefully.\n",
    "readonly": false,
    "available": true,
    "tool_dependencies": [],
    "usage_limits_summary": "",
    "directory_path": "/root/newman/skills/reviewer"
  }
}
```

## 9.8 更新 Workspace Skill

`PUT /api/skills/{skill_name}`

请求体：

```json
{
  "content": "# Updated Skill\n\nUse `search_files` first."
}
```

说明：

- 只允许更新 workspace skill 的 `SKILL.md`
- 若目标 skill 为 plugin skill 或其他只读来源，接口会返回冲突错误

## 9.9 删除 Workspace Skill

`DELETE /api/skills/{skill_name}`

响应示例：

```json
{
  "deleted": true,
  "skill_name": "reviewer"
}
```

说明：

- 只允许删除 workspace skill
- plugin skill 或其他只读来源不能通过该接口删除

---

## 十、MCP 接口

当前实现已经支持 `inline`、`http_json`、`http_sse`、`stdio` 四种 bridge 传输，并把 MCP 工具注册进统一 `ToolRegistry`。MCP 资源也会被整理进运行时工具概览，供模型侧感知。

当前仍未完成的部分：
- 还没有接入官方 MCP Python SDK
- `stdio` 采用的是 Newman 当前自定义的 newline-delimited JSON bridge，不是完整官方 MCP stdio 协议
- `http_sse` 当前实现为兼容型 SSE 响应解析，不是长连接会话复用模型
- 还没有单独的前端 MCP 管理页

### 10.0 MCP Server 配置字段

```json
{
  "name": "my-stdio-server",
  "transport": "stdio",
  "command": ["python"],
  "args": ["-m", "demo_mcp_server"],
  "env": {
    "DEMO_MODE": "1"
  },
  "url": null,
  "enabled": true,
  "requires_approval": true,
  "timeout_seconds": 20,
  "headers": {},
  "tools": [],
  "resources": []
}
```

字段说明：

- `transport`
  - `inline`：工具与资源直接写在配置里
  - `http_json`：通过 HTTP JSON 拉取 `/tools`、`/resources`，并调用 `/invoke/{tool}`
  - `http_sse`：通过 HTTP/SSE 响应解析同样的 `/tools`、`/resources`、`/invoke/{tool}`
  - `stdio`：启动本地子进程，使用 newline-delimited JSON bridge 交互
- `command + args`
  - 仅 `stdio` 需要
- `url`
  - `http_json` / `http_sse` 需要
- `requires_approval`
  - 该 MCP Server 下所有工具默认是否进入统一审批流程
- `tools`
  - `inline` 模式可直接内嵌工具清单
- `resources`
  - `inline` 模式可直接内嵌资源清单

最小可用样例：

`inline`

```json
{
  "name": "inline-demo",
  "transport": "inline",
  "enabled": true,
  "requires_approval": false,
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
        }
      },
      "risk_level": "low"
    }
  ],
  "resources": [
    {
      "uri": "memory://inline/context",
      "name": "inline-context",
      "description": "Inline MCP resource",
      "mime_type": "text/markdown",
      "content": "# hello"
    }
  ]
}
```

`http_json`

```json
{
  "name": "remote-http-json",
  "transport": "http_json",
  "url": "http://127.0.0.1:9000/mcp",
  "enabled": true,
  "requires_approval": true,
  "timeout_seconds": 20,
  "headers": {
    "Authorization": "Bearer demo-token"
  }
}
```

`stdio`

```json
{
  "name": "local-stdio",
  "transport": "stdio",
  "command": ["python"],
  "args": ["-m", "demo_mcp_server"],
  "env": {
    "DEMO_MODE": "1"
  },
  "enabled": true,
  "requires_approval": false
}
```

`http_sse`

```json
{
  "name": "remote-http-sse",
  "transport": "http_sse",
  "url": "http://127.0.0.1:9100/mcp",
  "enabled": true,
  "requires_approval": true,
  "timeout_seconds": 20
}
```

## 10.1 获取 MCP Server 列表与状态

`GET /api/mcp/servers`

响应示例：

```json
{
  "servers": [
    {
      "name": "my-inline",
      "transport": "inline",
      "url": null,
      "command": [],
      "args": [],
      "env": {},
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
            }
          },
          "risk_level": "low"
        }
      ],
      "resources": [
        {
          "uri": "memory://inline/context",
          "name": "inline-context",
          "description": "Inline MCP resource",
          "mime_type": "text/markdown",
          "content": "# hello"
        }
      ]
    }
  ],
  "statuses": [
    {
      "name": "my-inline",
      "transport": "inline",
      "enabled": true,
      "tool_count": 1,
      "resource_count": 1,
      "status": "connected",
      "detail": "",
      "last_checked_at": "2026-04-08T09:00:00+00:00"
    }
  ]
}
```

## 10.2 创建或更新 MCP Server

`POST /api/mcp/servers`

请求体示例：

```json
{
  "name": "my-inline",
  "transport": "inline",
  "command": [],
  "args": [],
  "env": {},
  "url": null,
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
  ],
  "resources": [
    {
      "uri": "memory://inline/context",
      "name": "inline-context",
      "description": "Inline MCP resource",
      "mime_type": "text/markdown",
      "content": "# hello"
    }
  ]
}
```

响应示例：

```json
{
  "server": {
    "name": "my-inline",
    "transport": "inline",
    "url": null,
    "command": [],
    "args": [],
    "env": {},
    "enabled": true,
    "requires_approval": false,
    "timeout_seconds": 20,
    "headers": {},
    "tools": [],
    "resources": []
  },
  "status": {
    "name": "my-inline",
    "transport": "inline",
    "enabled": true,
    "tool_count": 0,
    "resource_count": 0,
    "status": "connected",
    "detail": "",
    "last_checked_at": "2026-04-08T09:00:00+00:00"
  }
}
```

## 10.3 删除 MCP Server

`DELETE /api/mcp/servers/{server_name}`

响应示例：

```json
{
  "deleted": true,
  "server_name": "my-inline"
}
```

## 10.4 重连 MCP Server

`POST /api/mcp/servers/{server_name}/reconnect`

响应示例：

```json
{
  "server_name": "my-inline",
  "status": {
    "name": "my-inline",
    "transport": "inline",
    "enabled": true,
    "tool_count": 1,
    "resource_count": 1,
    "status": "connected",
    "detail": "",
    "last_checked_at": "2026-04-08T09:00:00+00:00"
  }
}
```

## 10.5 获取 MCP 资源列表

`GET /api/mcp/resources`

响应示例：

```json
{
  "resources": [
    {
      "server_name": "my-inline",
      "transport": "inline",
      "uri": "memory://inline/context",
      "name": "inline-context",
      "description": "Inline MCP resource",
      "mime_type": "text/markdown",
      "content": "# hello"
    }
  ],
  "statuses": [
    {
      "name": "my-inline",
      "transport": "inline",
      "enabled": true,
      "tool_count": 1,
      "resource_count": 1,
      "status": "connected",
      "detail": "",
      "last_checked_at": "2026-04-08T09:00:00+00:00"
    }
  ]
}
```

说明：

- MCP 工具会统一注册为 `mcp__{server_name}__{tool_name}`
- `risk_level` 和 `requires_approval` 会进入统一 ToolRouter / Approval 流程
- MCP 资源当前通过运行时工具概览暴露给模型，不单独作为前端 UI 区块展示
- `http_json` / `http_sse` 默认约定以下端点：
  - `GET /tools`
  - `GET /resources`
  - `POST /invoke/{tool_name}`
- `stdio` 当前约定 newline-delimited JSON bridge：
  - `tools.list`
  - `resources.list`
  - `tools.invoke`

---

## 十一、Scheduler 接口

## 11.1 获取任务列表

`GET /api/scheduler/tasks`

响应示例：

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
      "max_retries": 2,
      "status": "pending",
      "created_at": "2026-04-08T09:00:00+00:00",
      "updated_at": "2026-04-08T09:00:00+00:00",
      "last_run_at": null,
      "next_run_at": "2026-04-08T18:00:00+00:00",
      "last_error": "",
      "run_count": 0
    }
  ]
}
```

## 11.2 获取调度告警

`GET /api/scheduler/alerts`

响应示例：

```json
{
  "alerts": [
    {
      "alert_id": "alt-001",
      "task_id": "daily-report",
      "task_name": "日报生成",
      "severity": "error",
      "message": "任务执行失败，已重试 2 次: session_message 任务必须提供 session_id",
      "created_at": "2026-04-08T09:10:00+00:00",
      "acknowledged": false
    }
  ]
}
```

## 11.3 创建任务

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
  "max_retries": 5
}
```

## 11.4 启用任务

`POST /api/scheduler/tasks/{task_id}/enable`

## 11.5 禁用任务

`POST /api/scheduler/tasks/{task_id}/disable`

## 11.6 立即执行任务

`POST /api/scheduler/tasks/{task_id}/run`

## 11.7 删除任务

`DELETE /api/scheduler/tasks/{task_id}`

说明：

- 当前实现使用内置轮询引擎，不依赖 APScheduler
- 支持 `session_message` 和 `background_task`
- 任务配置保存在 `backend_data/scheduler/tasks.json`
- 调度失败会写入 `backend_data/scheduler/alerts.json`

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
  "ts": 1741234567890,
  "request_id": "req_xxx"
}
```

### 当前已实现事件

- `assistant_delta`
- `attachment_received`
- `attachment_processed`
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

### 与前端 PRD 对齐说明

- `session_created` 已实现，但只出现在 `POST /api/sessions/stream` 的 SSE 中，不会出现在 `POST /api/sessions/{session_id}/messages` 的消息流里。
- 前端当前应以 `final_response` 作为“本轮回答结束”的主信号；`assistant_done` 还未单独实现。
- `memory_updated` 还未实现为 SSE 事件。前端若要看到最新 Memory 内容，当前应通过 `GET /api/workspace/memory` 主动刷新。

说明：

- `tool_approval_request` 只会在通过前置审批后、需要用户人工确认时触发。
- 若命中 Level 1 黑名单，后端会直接拒绝，不会发送 `tool_approval_request`。
- `tool_error_feedback` 不仅用于工具执行失败，也用于 Provider 层的可恢复错误回灌。
- `tool_call_finished`、`tool_error_feedback` 和 fatal `error` 事件会携带结构化错误恢复字段：
  `error_code`、`severity`、`risk_level`、`recovery_class`、`frontend_message`、`recommended_next_step`
- 所有 SSE 事件当前都会附带 `request_id`，便于和 HTTP 请求、审计日志做关联。
- 消息流中的审计日志现在也按同一结构保存为完整事件包：`event`、`data`、`ts`、`request_id`
- `GET /api/sessions/{session_id}/events` 会基于这些结构化审计事件返回前端可恢复的 timeline 数据

### 事件示例

#### `attachment_received`

```json
{
  "event": "attachment_received",
  "data": {
    "count": 1,
    "files": [
      {
        "filename": "screen.png",
        "content_type": "image/png"
      }
    ]
  },
  "ts": 1741234567890
}
```

#### `attachment_processed`

```json
{
  "event": "attachment_processed",
  "data": {
    "count": 1,
    "files": [
      {
        "filename": "screen.png",
        "summary": "图片中包含一个终端窗口，显示 PostgreSQL 已启动..."
      }
    ]
  },
  "ts": 1741234567890
}
```

#### `checkpoint_created`

```json
{
  "event": "checkpoint_created",
  "data": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "checkpoint_id": "cp_xxx",
    "summary": "Checkpoint Summary\n- user: ...",
    "compression_level": "critical"
  },
  "ts": 1741234567890
}
```

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

说明：

- `hook_triggered` 既可能来自声明式 hook message，也可能来自可执行 hook handler 的标准输出
- 当前已接入的 hook 生命周期包括：`SessionStart`、`PreToolUse`、`PostToolUse`、`SessionEnd`、`FileChanged`
- 当 `write_file` 或 `edit_file` 成功写入文件后，会额外触发一次 `FileChanged`

`FileChanged` 场景示例：

```json
{
  "event": "hook_triggered",
  "data": {
    "event": "FileChanged",
    "message": "example-plugin: Example hook noticed file change: /root/newman/README.md",
    "context": {
      "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
      "tool": "edit_file",
      "path": "/root/newman/README.md"
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
    "tool": "provider:openai_compatible",
    "category": "timeout_error",
    "error_code": "NEWMAN-TOOL-001",
    "severity": "warning",
    "risk_level": "medium",
    "recovery_class": "recoverable",
    "frontend_message": "工具执行超时",
    "summary": "OpenAI-compatible request timed out",
    "retryable": true,
    "attempt_count": 1,
    "recommended_next_step": "Check whether the action is temporarily slow, then retry the smallest necessary step."
  },
  "ts": 1741234567890
}
```

#### `tool_call_finished`

失败场景下，`tool_call_finished.data` 也会包含相同的结构化错误恢复字段，示例：

```json
{
  "event": "tool_call_finished",
  "data": {
    "tool_call_id": "call_xxx",
    "tool": "fetch_url",
    "success": false,
    "category": "network_error",
    "error_code": "NEWMAN-TOOL-008",
    "severity": "warning",
    "risk_level": "medium",
    "recovery_class": "recoverable",
    "frontend_message": "网络请求失败",
    "recommended_next_step": "Wait briefly and retry once; if it still fails, reduce scope or switch strategy.",
    "summary": "Request failed",
    "duration_ms": 842,
    "attempt_count": 3
  },
  "ts": 1741234567890
}
```

#### `error`

fatal 错误事件示例：

```json
{
  "event": "error",
  "data": {
    "code": "NEWMAN-TOOL-009",
    "message": "认证失败",
    "summary": "openai_compatible authentication failed",
    "tool": "provider:openai_compatible",
    "category": "auth_error",
    "severity": "error",
    "risk_level": "critical",
    "recovery_class": "fatal",
    "retryable": false,
    "recommended_next_step": "Stop this round, summarize the blocker clearly, and wait for user intervention or a configuration fix."
  },
  "ts": 1741234567890
}
```

#### `tool_approval_request`

```json
{
  "event": "tool_approval_request",
  "data": {
    "approval_request_id": "apr_xxx",
    "tool": "terminal",
    "arguments": {
      "command": "echo hi > /tmp/x"
    },
    "reason": "terminal_mutation_or_unknown",
    "summary": "命中 Level 2 风险规则，需人工审批",
    "timeout_seconds": 120
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

#### `final_response`（工具上限优雅降级）

```json
{
  "event": "final_response",
  "data": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "content": "已达到当前回合的工具调用上限，请输入“继续”继续处理。",
    "finish_reason": "tool_limit_reached"
  },
  "ts": 1741234567890
}
```

---

## 十四、当前边界

当前 Phase 4 已可用，但仍有边界：

- 前端基于现有 Vite/React 工作台，不是 Next.js 架构
- RAG 当前已按 `PostgreSQL + Chroma` 落地，但检索质量仍依赖 `models.embedding` 与 `models.reranker` 的真实可用性
- 原生沙箱当前只适配 Linux（bubblewrap）；macOS / Windows 仍为待做
- hook 当前支持声明式消息和 Python handler 子进程执行，但尚未完全接入与终端同等级别的严格沙箱
- MCP 目前是 bridge 基线，不是完整官方 MCP 协议栈
- Scheduler 当前使用内置 cron 解析与轮询执行
- Channels 当前返回标准化 webhook 响应，尚未接入真实飞书/企微发送端

## 十五、前端联调待办

以下是已知但尚未在当前 API / 前端联调中完全闭环的项：

- `assistant_done` SSE 事件未实现，当前以前端消费 `final_response` 代替
- `memory_updated` SSE 事件未实现，当前 Memory 仍以 REST 刷新为主
- Evidence Drawer 的 `Trace / Tool IO / 引用` 三标签结构尚未定稿，当前前端右侧仍以摘要 + Raw JSON 为主
- 刷新页面后，前端现已能恢复当前会话、工作区页、栏宽、最近选中的 trace，并尽量恢复待审批请求和最近一次可见的流式回答内容
- 当前仍不支持真正的 SSE 断点续传；如果浏览器刷新时网络流被中断，页面只能恢复“最后一次可见状态”，不能继续复用原连接
- 移动端工作台只保证可读和不崩布局，右侧抽屉滑层与输入栏吸附仍为待办
