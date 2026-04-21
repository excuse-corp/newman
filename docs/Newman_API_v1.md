# Newman API 文档 v1.4

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
- [config.py](/root/newman/backend/api/routes/config.py)
- [workspace.py](/root/newman/backend/api/routes/workspace.py)
- [plugins.py](/root/newman/backend/api/routes/plugins.py)
- [tools.py](/root/newman/backend/api/routes/tools.py)
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
    "read_file_range",
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

- 读取与定位：`read_file`、`read_file_range`、`list_dir`、`list_files`、`search_files`、`grep`
- 编辑与执行：`write_file`、`edit_file`、`terminal`
- 协作与知识：`update_plan`、`fetch_url`、`search_knowledge_base`

说明：

- `list_files` 是 `list_dir` 的别名。
- `grep` 是 `search_files` 的别名。
- `read_file` 只用于“小文件完整读取”：只接收 `path`，返回完整文件内容的 base64 JSON 载荷 `{ "dataBase64": "..." }`；当前限制为不超过 `65536` 字节。
- `read_file_range` 只用于“文本分段读取”：接收 `path`、`offset`、`limit`，其中 `offset` 为 1-based 起始行号，`limit` 为单次最多返回的行数；当前仅支持 UTF-8 文本文件。
- 选择建议：
  - 需要完整原始文件字节，且文件较小：用 `read_file`
  - 文件较大，或只想看某段文本：用 `read_file_range`
- `read_file` / `read_file_range` 的完整输出只会在当前 turn 的后续推理里临时可见；session 持久化历史只保留摘要和元数据，不会把 base64 或大段文本原样长期写进 `session.messages`。
- `write_file`、`edit_file` 默认需要审批。
- `terminal` 采用两级前置审批：Level 1 黑名单直接拒绝，Level 2 风险模式进入人工审批；Linux 沙箱内的明显只读命令会自动放行。
- 若配置了插件 MCP server，运行时还会额外挂载 `mcp__...` 工具。
- `terminal` 在 Linux 下默认走原生沙箱；当前阶段仅实现 Linux，macOS / Windows 为待做。
- 当前内置工具会从 `backend/tools/impl/` 动态发现；新增模块只要导出 `build_tools(context)`，并在生态重载后即可注册。

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
    "messages": [
      {
        "id": "turn_user_001",
        "role": "user",
        "content": "帮我检查一下前端 timeline 实现",
        "created_at": "2026-04-12T08:30:00+00:00",
        "metadata": {
          "approval_mode": "manual",
          "turn_id": "turn_user_001",
          "request_id": "req_abc123"
        }
      },
      {
        "id": "msg_asst_001",
        "role": "assistant",
        "content": "我先对照 PRD 和现有代码看一下。",
        "created_at": "2026-04-12T08:30:06+00:00",
        "metadata": {
          "turn_id": "turn_user_001",
          "request_id": "req_abc123",
          "finish_reason": "stop"
        }
      }
    ],
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
  "checkpoint": null,
  "context_usage": {
    "effective_context_window": 95000,
    "auto_compact_limit": 86808,
    "confirmed_prompt_tokens": 1248,
    "confirmed_pressure": 0.013136842105263158,
    "confirmed_request_kind": "session_turn",
    "confirmed_recorded_at": "2026-04-11T15:20:00+00:00",
    "projected_next_prompt_tokens": 1376,
    "projected_pressure": 0.01448421052631579,
    "projection_source": "confirmed_plus_delta",
    "projected_over_limit": false,
    "compaction_stage": null,
    "compaction_fail_streak": 0,
    "context_irreducible": false,
    "last_compaction_failure_reason": null
  }
}
```

说明：

- `session.metadata.plan` 与顶层 `plan` 字段内容相同，后者只是为了前端读取更直接。
- 只有在模型调用 `update_plan` 工具后，`plan` 才会出现。
- Web chat 回合里的 `session.messages[*].metadata` 现在会尽量补齐 `turn_id`，便于前端把同一轮的用户消息、过程事件和最终回答聚合成一个 turn 容器。
- 通过 `/api/sessions/{session_id}/messages` 发起的 HTTP 回合，消息元数据通常还会包含 `request_id`；最终 assistant 消息会额外写入 `finish_reason`。
- `context_usage.effective_context_window` 使用的是“有效上下文窗口”，当前定义为配置的模型 `context_window * 95%`。
- `context_usage.auto_compact_limit` 是运行时真正用来判断自动压缩的阈值，已经扣除了回答预留、压缩预留和安全缓冲。
- `context_usage.confirmed_*` 表示最近一次真实模型请求里已确认的 prompt 占用；只有最近一条 `counts_toward_context_window=true` 且 `usage_available=true` 的记录才会填充这些字段。
- `context_usage.projected_*` 表示“如果现在再发起下一次模型请求”，运行时估算出的上下文占用与压力。
- 若存在最近一次真实 usage 记录，且新消息增量可估算，则 `projection_source = "confirmed_plus_delta"`；否则会退回 `projection_source = "assembled_prompt_estimate"`。
- 投影估算基于当前完整 prompt 组装结果，而不只是 `session.messages`：会一并考虑 Stable Memory、工具总览、checkpoint summary 和当前会话消息。
- `projected_over_limit = true` 表示下一次请求的估算 prompt 已超过自动压缩阈值，不等同于一定超过模型硬 context window。
- 若存在 `checkpoint.summary`，其内容现在是基于 LLM 生成的 handoff summary，而不是简单的消息逐条拼接文本。
- `compaction_stage`、`compaction_fail_streak`、`context_irreducible` 和 `last_compaction_failure_reason` 用于前端展示压缩状态与失败原因。

## 3.2A 获取会话 usage 记录

`GET /api/sessions/{session_id}/usage`

查询参数：

- `limit`: 可选，默认 `100`，最大 `500`

响应示例：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "available": true,
  "records": [
    {
      "request_id": "a4d8b7...",
      "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
      "turn_id": "7b78...",
      "request_kind": "session_turn",
      "counts_toward_context_window": true,
      "streaming": true,
      "provider_type": "openai_compatible",
      "model": "minimax-m2.5",
      "context_window": 100000,
      "effective_context_window": 95000,
      "usage_available": true,
      "input_tokens": 1420,
      "output_tokens": 221,
      "total_tokens": 1641,
      "finish_reason": "stop",
      "created_at": "2026-04-11T15:20:00+00:00",
      "metadata": {
        "assembled_message_count": 9,
        "tool_schema_count": 12,
        "estimated_input_tokens": 1398,
        "response_content_length": 328,
        "tool_call_count": 0
      }
    }
  ]
}
```

说明：

- 当前会把模型请求 usage 详细写入 PostgreSQL `model_usage_records` 表。
- 主对话轮次、压缩摘要、记忆提取、多模态分析、RAG rerank 等都会分别写入 usage 记录。
- `counts_toward_context_window=true` 的记录才会参与聊天页上下文窗口圆环。

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
    "summary": "## Current Progress\n- 已确认前端缺少真实事件聚合逻辑。\n\n## Important Context\n- 用户要求 Trace 节点使用用户可理解的进展文案。\n\n## What Remains To Be Done\n- 对齐事件聚合规则并更新展示。",
    "turn_range": [0, 8],
    "created_at": "2026-04-02T10:00:00+00:00",
    "metadata": {
      "preserve_recent": 4,
      "compression_level": "manual",
      "original_message_count": 12,
      "compressed_message_count": 8,
      "summary_strategy": "llm_handoff_summary",
      "summary_model": "qwen3-coder-plus",
      "summary_usage": {
        "input_tokens": 1620,
        "output_tokens": 214,
        "total_tokens": 1834
      }
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

- 手动压缩与自动压缩现在共用同一套逻辑：都会裁剪 session，并保留最近 `runtime.context_compaction_preserve_recent` 条消息；默认值为 `4`。
- 实际保留时会尽量对齐同一 turn / tool group，避免把一轮消息从中间截断。
- `checkpoint.summary` 通过一次独立的 LLM handoff summary 请求生成，提示词参考 Codex 本地 compact 方案，要求输出“当前进展、关键约束、剩余工作、关键引用”等可供后续模型继续任务的摘要。
- 若已存在旧 checkpoint，压缩请求会把旧 `summary` 与本轮将被裁剪的历史消息一起交给模型，要求产出一份“替换旧 summary 的刷新版摘要”，而不是简单字符串追加。
- 若当前 provider 为 `mock`，或压缩摘要请求失败/返回空内容，则会退回到结构化归档摘要：保留旧 summary，并附加 `## Archived Message Snapshot` 文本快照。
- 当当前会话消息数小于等于当前配置的保留数量时，没有可裁剪历史，接口会返回 `{"compressed": false, "reason": "nothing_to_compress"}`。
- 压缩触发阈值基于有效上下文窗口计算：
  - `effective_context_window = configured_context_window * 95%`
  - `pressure = assembled_prompt_estimated_tokens / effective_context_window`
  - 当 `pressure >= runtime.context_compress_threshold` 时自动触发压缩

## 3.6 恢复 Checkpoint

`POST /api/sessions/{session_id}/restore-checkpoint`

响应示例：

```json
{
  "restored": true,
  "checkpoint": {
    "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
    "checkpoint_id": "cp_xxx",
    "summary": "## Current Progress\n- 已完成首轮接口排查。\n\n## Important Context\n- 用户要求不要在主区暴露技术术语。\n\n## What Remains To Be Done\n- 继续对齐 Trace Timeline 的聚合规则。",
    "turn_range": [0, 8],
    "created_at": "2026-04-02T10:00:00+00:00",
    "metadata": {
      "preserve_recent": 4,
      "compression_level": "normal",
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
- `restore-checkpoint` 不会在主循环中自动触发，只有显式调用该接口时才会执行。
- 当 session 中已经存在 `checkpoint_restore` 消息时，后续上下文组装不会再额外从 checkpoint 文件重复补一份 `summary`。

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
- `auto_approve_level2` 只影响 Level 2 命中的审批；工具自身 `requires_approval=true` 的 mandatory 审批仍需人工确认
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
- 同一 `session_id` 同时只允许一个活跃回合；若上一轮仍在执行或等待审批，再次发送会返回 `409`
- 单轮最大工具调用深度默认 30
- 插件 hook 会通过 `hook_triggered` 事件回传
- 结束时统一发送 `stream_completed`
- 若需要主动停止当前回合，可调用 `POST /api/sessions/{session_id}/interrupt`

工具深度上限说明：

- 当单轮工具调用达到 `max_tool_depth` 上限时，后端不会直接中断成空错误
- 当前实现会禁止继续调用新工具，并基于已有上下文输出一个阶段性答复
- 最终答复会明确提示用户：已到当前使用工具上限，可以输入“继续”
- 此时 `final_response.finish_reason = "tool_limit_reached"`

示例：

```text
/tool read_file {"path":"/root/newman/docs/prds/Newman_PRD_v9.md"}
/tool read_file_range {"path":"README.md","offset":1,"limit":120}
/tool list_dir {"path":"backend","recursive":false}
/tool search_files {"query":"handle_message","path":"backend","glob":"*.py"}
/tool edit_file {"path":"README.md","edits":[{"old_text":"old","new_text":"new"}]}
/tool update_plan {"steps":[{"step":"检查现状","status":"completed"},{"step":"实现后端","status":"in_progress"},{"step":"更新前端","status":"pending"}]}
/tool search_knowledge_base {"query":"混合检索","limit":3}
/tool mcp__example-inline__echo_context {"text":"hello"}
```

## 4.2 停止当前会话中的运行任务

`POST /api/sessions/{session_id}/interrupt`

响应示例：

```json
{
  "interrupted": true,
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "request_id": "req_abc123",
  "turn_id": "turn_user_001",
  "message": "当前任务已停止"
}
```

若当前没有活跃任务：

```json
{
  "interrupted": false,
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "reason": "no_active_run"
}
```

说明：

- 成功停止后，后端会取消当前 worker，并在 session 中追加一条 `role=system`、`metadata.type="turn_interrupted"` 的消息。
- 同时会把结构化 `turn_interrupted` 事件写入审计日志，因此 `GET /api/sessions/{session_id}/events` 可恢复该状态。
- 若当前会话正有一条活跃的 `/messages` SSE 连接，后端会先把 `turn_interrupted` 推回这条流，再结束本轮并发送 `stream_completed`。

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
    "turn_id": "turn_user_001",
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

## 六、审计与配置接口

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

## 6.2 获取项目配置文件

`GET /api/config/project`

响应示例：

```json
{
  "path": "/root/newman/newman.yaml",
  "content": "server:\n  port: 8005\npaths:\n  workspace: \".\"\n",
  "effective_workspace": "/root/newman",
  "source_priority": [
    "environment",
    "~/.newman/config.yaml",
    "newman.yaml",
    "defaults.yaml"
  ],
  "reload_supported": true
}
```

说明：

- `content` 返回项目根目录下 `newman.yaml` 的完整文本。
- `effective_workspace` 返回当前已生效配置解析后的绝对路径。
- `source_priority` 表示配置合并优先级，越靠前优先级越高。

## 6.3 保存项目配置文件

`PUT /api/config/project`

请求体：

```json
{
  "content": "server:\n  port: 8010\npaths:\n  workspace: \"workspace\"\n"
}
```

响应示例：

```json
{
  "saved": true,
  "path": "/root/newman/newman.yaml",
  "content": "server:\n  port: 8010\npaths:\n  workspace: \"workspace\"\n",
  "effective_workspace": "/root/newman/workspace",
  "requires_reload": true,
  "warnings": []
}
```

说明：

- 保存前会先校验 YAML 语法以及配置结构；顶层必须是 YAML 对象。
- 该接口只负责写入 `newman.yaml`，不会自动热重载当前进程。
- `warnings` 会提示“即使 reload 也不能立刻生效”的配置项变化，例如监听地址或 CORS。

## 6.4 重载项目配置

`POST /api/config/reload`

响应示例：

```json
{
  "reloaded": true,
  "path": "/root/newman/newman.yaml",
  "effective_workspace": "/root/newman/workspace",
  "warnings": [
    "`server.host` / `server.port` 的变化需要重启进程后才能真正改变监听地址。"
  ]
}
```

说明：

- 该接口会重新加载配置，并热替换 `settings`、`runtime`、`scheduler` 与 `channels` 服务实例。
- 新运行时会先重建生态并刷新 scheduler；若启动新实例失败，会回滚到旧实例。
- `server.host`、`server.port` 和 `server.cors_origins` 的变化会写入配置，但仍需要重启进程才能完全生效。

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

## 7.2A 获取工作区根权限信息

`GET /api/workspace/roots`

响应示例：

```json
{
  "workspace": "/root/newman",
  "readable_roots": [
    "/root/newman",
    "/root/newman/backend",
    "/root/newman/docs"
  ],
  "writable_roots": [
    "/root/newman"
  ],
  "protected_roots": [
    "/root/newman/backend_data/secrets"
  ]
}
```

说明：

- 该接口返回当前路径访问策略展开后的绝对路径集合。
- 前端可用它判断哪些目录允许浏览、编辑或需要特别标识。

## 7.3 浏览工作区文件

`GET /api/workspace/files?path=.`

目录响应：

```json
{
  "path": "/root/newman",
  "type": "dir",
  "access": "writable",
  "entries": [
    {
      "name": "backend",
      "path": "/root/newman/backend",
      "type": "dir",
      "access": "writable"
    }
  ]
}
```

文件响应：

```json
{
  "path": "/root/newman/docs/Newman_API_v1.md",
  "type": "file",
  "access": "readable",
  "content": "# Newman API 文档 ..."
}
```

说明：

- 若 `path` 指向目录，当前最多返回前 `200` 个子项，并默认跳过隐藏/忽略路径。
- 若 `path` 指向文件，返回的是文本预览内容，当前最多截断到前 `20000` 个字符。
- `access` 来自当前路径权限模型，常见值包括 `writable`、`readable`、`protected`。

## 7.3A 获取文件原始内容

`GET /api/workspace/file-content?path=frontend/src/assets/newman-logo.png`

说明：

- 该接口直接返回文件响应，自动推断 `Content-Type`，并设置 `content-disposition: inline`。
- 适合前端预览图片、PDF 或需要完整内容的文件；相比 `GET /api/workspace/files` 不会进行文本截断。

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

## 九、插件、Tool 与 Skill 接口

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
- 后端会在每轮新消息开始前自动感知 `plugins/`、`skills/` 和 `backend/tools/` 目录变化，并在下一轮重建生态

## 9.2 获取插件详情

`GET /api/plugins/{plugin_name}`

响应示例：

```json
{
  "plugin": {
    "name": "example-plugin",
    "version": "1.0.0",
    "description": "Example plugin",
    "enabled": true,
    "plugin_path": "/root/newman/plugins/example-plugin",
    "skill_count": 1,
    "hook_count": 2,
    "mcp_server_count": 1,
    "directory_path": "/root/newman/plugins/example-plugin",
    "manifest_path": "/root/newman/plugins/example-plugin/plugin.yaml",
    "manifest": {
      "name": "example-plugin",
      "version": "1.0.0",
      "description": "Example plugin",
      "enabled_by_default": true,
      "skills": [],
      "hooks": [],
      "mcp_servers": [],
      "required_permissions": [],
      "ui": null
    },
    "manifest_content": "name: example-plugin\nversion: 1.0.0\n...",
    "skill_paths": [
      "/root/newman/plugins/example-plugin/skills/demo_skill"
    ],
    "hook_handlers": [
      {
        "event": "FileChanged",
        "handler": "hooks/on_change.py",
        "message": "",
        "timeout_seconds": 5,
        "path": "/root/newman/plugins/example-plugin/hooks/on_change.py"
      }
    ],
    "tool_names": [],
    "available": true
  }
}
```

## 9.3 导入插件

`POST /api/plugins/import`

请求体：

```json
{
  "source_path": "imports/my_plugin"
}
```

说明：

- `source_path` 必须位于当前可读目录范围内
- 目标文件夹内必须包含 `plugin.yaml`
- 导入行为会把整个插件目录复制到 `plugins/`，然后立即重载插件生态

## 9.4 更新插件 Manifest

`PUT /api/plugins/{plugin_name}`

请求体：

```json
{
  "content": "name: example-plugin\nversion: 2.0.0\ndescription: Updated plugin\n"
}
```

说明：

- 当前接口更新的是目标插件的 `plugin.yaml` 完整内容
- 其他插件文件仍建议通过文件工具或工作区文件接口维护
- 更新成功后会立即重载插件生态

## 9.5 删除插件

`DELETE /api/plugins/{plugin_name}`

响应示例：

```json
{
  "deleted": true,
  "plugin_name": "example-plugin"
}
```

## 9.6 重新扫描插件

`POST /api/plugins/rescan`

返回结构与 `GET /api/plugins` 一致，额外包含：

```json
{
  "reloaded": true
}
```

## 9.7 启用 / 禁用插件

`POST /api/plugins/{plugin_name}/enable`

`POST /api/plugins/{plugin_name}/disable`

说明：

- 这两个接口都会返回最新的插件详情结构
- 启停状态会写入插件状态存储，并触发运行时生态重载

## 9.8 获取 Tool 列表

`GET /api/tools`

响应示例：

```json
{
  "tools": [
    {
      "name": "read_file",
      "description": "Read a small workspace file and return the entire contents as base64 in dataBase64. Use this only when you need the exact complete file bytes. If the file may be large or you only need part of a text file, use read_file_range instead.",
      "risk_level": "low",
      "requires_approval": false,
      "timeout_seconds": 10,
      "allowed_paths": [
        "/data/newman/runtime_workspace",
        "/root/newman/backend",
        "/root/newman/docs"
      ],
      "source_type": "builtin",
      "module": "backend.tools.impl.read_file",
      "class_name": "ReadFileTool",
      "file_path": "/root/newman/backend/tools/impl/read_file.py",
      "file_access": "writable",
      "managed": true,
      "input_schema": {
        "type": "object"
      }
    }
  ]
}
```

字段说明：

- `source_type`
  - `builtin`：内置工具，来自 `backend/tools/impl/`
  - `mcp`：MCP 桥接工具
  - `runtime`：其他运行时注册工具
- `file_access` 表示该工具实现文件在当前权限模型中的访问级别
- `managed = true` 表示该工具实现文件位于当前可维护范围内

## 9.9 获取 Tool 详情

`GET /api/tools/{tool_name}`

返回结构与 `GET /api/tools` 中单个 `tool` 条目一致。

## 9.10 重新扫描 Tool 生态

`POST /api/tools/rescan`

响应示例：

```json
{
  "reloaded": true,
  "tools": []
}
```

说明：

- 会触发运行时重建工具注册表
- 当前内置 Tool 采用动态发现机制：`backend/tools/impl/` 下模块只要导出 `build_tools(context)`，重扫后即可注册

## 9.11 获取 Skill 列表

`GET /api/skills`

响应示例：

```json
{
  "skills": [
    {
      "name": "session_review",
      "source": "system",
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

- 运行时里的 skill 是“一个目录”，不是单独一段文本；目录内必须有 `SKILL.md`，也可以包含 `scripts/`、`references/`、`templates/`、`assets/`、`requirements.txt`、`pyproject.toml` 等辅助资源。
- 运行时会动态生成 `backend_data/memory/SKILLS_SNAPSHOT.md`
- `SKILLS_SNAPSHOT.md` 只负责告诉模型“有哪些 skill 可用、什么时候该用”
- 列表接口只返回 skill 元数据摘要，不会内联同目录下的脚本、模板、参考资料等辅助文件
- `path` 指向 skill 的 `SKILL.md`；若需要 skill 目录根路径，请使用详情接口中的 `directory_path`
- 具体 Skill 正文建议通过工作区文件或 `read_file` 按需读取
- `backend_data/memory/USER.md` 会被后台稳定记忆抽取逻辑自动合并更新
- 已启用插件中的 skill 会和平台 `skills/` 目录下的 skill 合并进入同一个 snapshot
- 插件启停或 skill 文件变更后，下一轮 prompt 会使用最新 snapshot
- 当前列表只返回“当前可用”的 skill：平台 skill + 已启用 plugin skill

## 9.12 获取 Skill 详情

`GET /api/skills/{skill_name}`

响应示例：

```json
{
  "skill": {
    "name": "writer",
    "source": "system",
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
- `content` 仅返回该 skill 的 `SKILL.md` 文本，不会展开同目录下的 `scripts/`、`references/`、`templates/` 等文件
- `tool_dependencies` 为根据 `SKILL.md` 内容提取出的工具依赖摘要
- `usage_limits_summary` 为根据 `SKILL.md` 中的约束/限制段落提取出的简要说明
- `directory_path` 为 skill 目录根路径；若要检查或编辑同目录下的脚本和参考文件，应基于这个目录进一步读取文件

## 9.13 导入 Skill

`POST /api/skills/import`

请求体：

```json
{
  "source_path": "imports/reviewer"
}
```

说明：

- `source_path` 必须位于当前可读目录范围内
- 目标文件夹内必须包含 `SKILL.md`
- 导入行为会把整个 skill 文件夹复制到平台 `skills/` 目录下，并立即刷新 snapshot
- 复制范围不仅包含 `SKILL.md`，也包含同目录下的 `scripts/`、`references/`、`templates/`、依赖清单等资源文件
- 当前没有单独的“创建空 skill”接口；新增 skill 的受支持方式是先准备一个合法 skill 目录，再通过本接口导入

## 9.14 更新 Skill

`PUT /api/skills/{skill_name}`

请求体：

```json
{
  "content": "# Updated Skill\n\nUse `search_files` first."
}
```

说明：

- 只允许更新平台 `skills/` 目录中的 system skill
- 当前该接口只会覆盖目标 skill 的 `SKILL.md` 内容，不会修改同目录下的脚本、模板、参考资料或依赖文件
- 若目标 skill 为 plugin skill 或其他只读来源，接口会返回冲突错误

## 9.15 删除 Skill

`DELETE /api/skills/{skill_name}`

响应示例：

```json
{
  "deleted": true,
  "skill_name": "reviewer"
}
```

说明：

- 只允许删除 system skill
- 删除行为针对整个 skill 目录，而不只是删除 `SKILL.md`
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
- MCP 工具参数里出现路径类字段时，运行前会做 preflight 校验：只允许落在当前 `runtime workspace` 内；命中受保护路径也会直接拒绝
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

补充约定：

- 会话主消息流里的事件，`data.turn_id` 会标识该事件归属的 turn。
- `assistant_delta` 只用于更新当前 turn 的流式回答槽位，不代表已持久化消息。
- `final_response` 表示当前 turn 的回答文本已经完成，且会携带已持久化 assistant message 的 `message_id` / `created_at` 方便前端对账。

### 当前已实现事件

- `session_created`
- `thinking_delta`
- `thinking_complete`
- `commentary_delta`
- `commentary_complete`
- `answer_started`
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
- `turn_interrupted`
- `final_response`
- `stream_completed`
- `error`

### 与前端 PRD 对齐说明

- `session_created` 已实现，但只出现在 `POST /api/sessions/stream` 的 SSE 中，不会出现在 `POST /api/sessions/{session_id}/messages` 的消息流里。
- `thinking_delta` / `thinking_complete` 与 `commentary_delta` / `commentary_complete` 已实现，用于前端展示“当前思路”和“正在执行的短说明”。
- `answer_started` 已实现，用于标记“当前子轮次开始进入正式回答阶段”；它适合作为 timeline 的“开始回答”节点来源，但不是回答完成信号。
- 前端当前应以 `final_response` 作为“本轮回答结束”的主信号；`assistant_done` 还未单独实现。
- `memory_updated` 还未实现为 SSE 事件。前端若要看到最新 Memory 内容，当前应通过 `GET /api/workspace/memory` 主动刷新。
- `turn_interrupted` 会由 `POST /api/sessions/{session_id}/interrupt` 持久化到审计日志和事件历史；若当前消息流仍处于活跃状态，也会实时推回同一条 `/messages` SSE 连接。
- 为了支持“单 turn 单回答槽位”渲染，当前推荐前端同时消费三类数据：`assistant_delta` 的流式文本、`final_response` 的完成信号，以及 `GET /api/sessions/{session_id}` 返回的持久化 `assistant` 消息。

说明：

- `tool_approval_request` 只会在通过前置审批后、需要用户人工确认时触发。
- 若命中 Level 1 黑名单，后端会直接拒绝，不会发送 `tool_approval_request`。
- `tool_error_feedback` 不仅用于工具执行失败，也用于 Provider 层的可恢复错误回灌。
- `answer_started` 当前只会出现在“本 turn 已经发生过工具调用，且本次 provider 流真正开始输出正式回答”时；纯直接回答回合不会发送这个事件。
- 若模型先吐出一段回答、随后又决定继续调工具，后端会发送 `assistant_delta` 且 `data.reset = true`，前端应清空之前的临时回答槽位并等待后续新的回答片段。
- `tool_call_finished`、`tool_error_feedback` 和 fatal `error` 事件会携带结构化错误恢复字段：
  `error_code`、`severity`、`risk_level`、`recovery_class`、`frontend_message`、`recommended_next_step`
- 所有 SSE 事件当前都会附带 `request_id`，便于和 HTTP 请求、审计日志做关联。
- 当前主消息流里的大多数 turn 级事件都会在 `data` 中携带 `turn_id`。
- 消息流中的审计日志现在也按同一结构保存为完整事件包：`event`、`data`、`ts`、`request_id`
- `GET /api/sessions/{session_id}/events` 会基于这些结构化审计事件返回前端可恢复的 timeline 数据

### 事件示例

#### `answer_started`

```json
{
  "event": "answer_started",
  "data": {
    "turn_id": "turn_user_001",
    "group_id": "turn_user_001:group:final",
    "model": "gpt-5"
  },
  "ts": 1741234567890,
  "request_id": "req_abc123"
}
```

#### `assistant_delta`

```json
{
  "event": "assistant_delta",
  "data": {
    "turn_id": "turn_user_001",
    "content": "我先对照 PRD 和现有代码看一下。",
    "delta": "我先对照 PRD 和现有代码看一下。",
    "model": "gpt-5"
  },
  "ts": 1741234567890,
  "request_id": "req_abc123"
}
```

补充说明：

- `delta` 是本次新增的流式片段；`content` 是当前 turn 临时回答槽位的完整累计文本
- 若 `data.reset = true`，表示之前泄露出来的临时回答应被视为失效，前端应先清空这段回答，再等待新的回答流

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
    "summary": "## Current Progress\n- 已完成首轮接口排查。\n\n## Important Context\n- 用户要求不要在主区暴露技术术语。\n\n## What Remains To Be Done\n- 继续对齐 Trace Timeline 的聚合规则。",
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
    "turn_id": "turn_user_001",
    "content": "已达到当前回合的工具调用上限，请输入“继续”继续处理。",
    "finish_reason": "tool_limit_reached",
    "message_id": "msg_asst_001",
    "created_at": "2026-04-12T08:31:02+00:00"
  },
  "ts": 1741234567890,
  "request_id": "req_abc123"
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
