# Newman API 文档 v1.7

本文档描述 Newman 当前 FastAPI 服务已落地的 HTTP 接口与 SSE 事件协议。接口实现以 `backend/api/app.py` 和 `backend/api/routes/` 为准。

部署、模型配置、飞书接入等用户向步骤见：

- [getting_started.md](getting_started.md)
- [feishu_cc_connect_codex_reusable_solution.md](feishu_cc_connect_codex_reusable_solution.md)

## 1. 总览

### Base URL

```text
http://localhost:8005
```

Docker 默认端口映射：

```text
Frontend: http://127.0.0.1:17775
Backend:  http://127.0.0.1:18005
```

本地源码运行默认：

```bash
conda activate newman
./scripts/dev/start_postgres.sh
uvicorn backend.main:app --reload
```

### 内容类型

- REST：`application/json`
- 文件上传：`multipart/form-data`
- SSE：`text/event-stream`

### 请求追踪

每个 HTTP 响应都会带：

```text
x-request-id: <uuid>
```

SSE payload 里也会带 `request_id`。

### 认证

若启用实例鉴权，前端通常先走首次配置或登录接口，再通过 cookie 访问后续 API。

也可用 `Authorization: Bearer <admin_token>` 访问受保护接口，具体由 `backend/api/middleware/auth.py` 处理。

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

## 2. 健康检查

### `GET /healthz`

返回运行时健康状态、工具列表、插件、调度器和 Channel 状态。

示例：

```json
{
  "ok": true,
  "version": "0.6.0",
  "provider": "openai_compatible",
  "deployment_profile": "none",
  "sandbox_enabled": true,
  "sandbox": {
    "configured": true,
    "enabled": true,
    "deployment_profile": "none",
    "backend": "linux_bwrap",
    "selected_backend": "linux_bwrap",
    "mode": "workspace-write",
    "platform": "linux",
    "platform_supported": true,
    "available": true,
    "network_access": false,
    "file_enforcement": "full",
    "network_enforcement": "full",
    "process_enforcement": "full",
    "process_visibility_enforcement": "full",
    "process_lifecycle_enforcement": "full",
    "resource_enforcement": "partial",
    "probe_ok": true,
    "probe_error": "",
    "provider_detail": "",
    "allow_partial_enforcement": false
  },
  "tools": ["read_file", "search_files", "terminal", "update_plan"],
  "plugins_enabled": 1,
  "scheduler_running": true,
  "channels_enabled": 1
}
```

`deployment_profile` 是当前加载的部署 profile；`macos_source_online` 会启用 macOS Seatbelt partial sandbox 并允许沙箱内命令联网。`sandbox.backend` 是配置值，`sandbox.selected_backend` 是 runtime provider registry 实际选择并 probe 的后端。`file_enforcement`、`network_enforcement`、`process_enforcement`、`process_visibility_enforcement`、`process_lifecycle_enforcement`、`resource_enforcement` 分别报告 `full|partial|unsupported`。当 `sandbox.enabled=false`、functional probe 失败或 policy 禁止 partial enforcement 时，`sandbox.available=false`，并通过 `probe_error` / `provider_detail` 说明原因；受限模式不会因为 runner 不可用而自动裸跑本地命令。

### `GET /readyz`

返回关键数据目录。

```json
{
  "ok": true,
  "sessions_dir": "/root/newman/backend_data/sessions",
  "plugins_dir": "/root/newman/plugins",
  "skills_dir": "/root/newman/skills",
  "mcp_dir": "/root/newman/backend_data/mcp",
  "scheduler_dir": "/root/newman/backend_data/scheduler",
  "channels_dir": "/root/newman/backend_data/channels"
}
```

## 3. 首次配置与认证

### `GET /api/bootstrap/status`

返回是否需要首次配置。

```json
{
  "enabled": true,
  "needs_setup": true
}
```

### `POST /api/bootstrap/setup`

首次写入模型配置、可选飞书配置，并生成实例访问密钥。

请求：

```json
{
  "primary_endpoint": "https://api.example.com/v1",
  "primary_api_key": "sk_xxx",
  "primary_model": "gpt-4.1-mini",
  "share_primary_for_multimodal": true,
  "multimodal_model": "gpt-4.1",
  "anysearch_api_key": "",
  "feishu_app_id": "",
  "feishu_app_secret": "",
  "login_after_setup": true
}
```

响应：

```json
{
  "configured": true,
  "authenticated": true,
  "admin_token_configured": true,
  "warnings": []
}
```

### `GET /api/auth/status`

```json
{
  "enabled": true,
  "needs_setup": false,
  "authenticated": true,
  "auth_method": "cookie",
  "admin_token_configured": true
}
```

### `POST /api/auth/login`

```json
{
  "admin_token": "instance_token"
}
```

登录成功后写入认证 cookie。

### `POST /api/auth/logout`

清除认证 cookie。

### `POST /api/auth/regenerate-token`

重新生成实例访问密钥，并写入当前项目 `.env`。

响应：

```json
{
  "rotated": true,
  "admin_token": "new_token",
  "instance_token": "new_token",
  "auth_method": "cookie"
}
```

## 4. 会话接口

### `POST /api/sessions`

创建或恢复会话。

```json
{
  "title": "供应商合同抽取"
}
```

响应：

```json
{
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "title": "供应商合同抽取",
  "created": true,
  "evolution": {
    "scheduled": true,
    "trigger": "new_session_created",
    "source_session_id": "previous_session_id",
    "reason": "background_task_started"
  }
}
```

### `POST /api/sessions/stream`

流式创建会话，返回 `session_created` SSE 事件。

### `GET /api/sessions`

返回会话列表。

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

### `GET /api/sessions/{session_id}`

返回会话详情、计划草稿、协作模式、checkpoint 与上下文占用。

顶层字段：

- `session`
- `plan`
- `collaboration_mode`
- `plan_draft`
- `approved_plan`
- `workflow_state`
- `awaiting_user_input`
- `checkpoint`
- `context_usage`

`context_usage` 口径见 [context_compression.md](context_compression.md)。

### `PATCH /api/sessions/{session_id}`

重命名会话。

```json
{
  "title": "新的会话标题"
}
```

### `DELETE /api/sessions/{session_id}`

删除会话。

### `PATCH /api/sessions/{session_id}/collaboration-mode`

切换协作模式。

```json
{
  "mode": "plan"
}
```

`mode` 支持：

- `default`
- `plan`
- `subagent`

### `GET /api/sessions/{session_id}/plan-draft`

读取计划草稿。

### `PUT /api/sessions/{session_id}/plan-draft`

保存计划草稿。传空字符串会清除草稿。

```json
{
  "markdown": "1. 检查接口\n2. 修改实现\n3. 运行测试"
}
```

### `GET /api/sessions/{session_id}/usage`

返回该会话及其子代理会话的模型 usage 记录。

查询参数：

- `limit`：默认 `100`，最大 `500`

### `GET /api/sessions/{session_id}/events`

返回结构化事件历史，供前端恢复 timeline。

查询参数：

- `limit`：默认 `200`

### `GET /api/sessions/{session_id}/multiagent-runs`

返回该会话下的 multi-agent run 列表。

查询参数：

- `turn_id`：可选，按父 turn 过滤

### `POST /api/sessions/{session_id}/compress`

手动压缩会话上下文。

响应：

```json
{
  "compressed": true,
  "checkpoint": {},
  "session": {},
  "microcompact_count": 1
}
```

若无可压缩内容：

```json
{
  "compressed": false,
  "reason": "nothing_to_compress",
  "microcompact_count": 0
}
```

### `POST /api/sessions/{session_id}/restore-checkpoint`

把 checkpoint 摘要恢复为显式 system message。

响应：

```json
{
  "restored": true,
  "checkpoint": {},
  "session": {}
}
```

## 5. 消息与 SSE

### `POST /api/sessions/{session_id}/messages`

发送一轮用户消息，响应类型为 `text/event-stream`。

JSON 请求：

```json
{
  "content": "请总结当前工作区结构",
  "approval_mode": "manual",
  "environment_context": {
    "city": "Shanghai"
  }
}
```

表单请求支持：

- `content`
- `attachments`
- `images`
- `approval_mode`
- `environment_context`：JSON 字符串

`approval_mode` 常用值：

- `manual`
- `auto_approve_level2`
- `auto_allow`

行为说明：

- 同一 `session_id` 同时只允许一个活跃回合。
- 若当前会话已有运行任务，返回 `409`。
- 若 Scheduler 正在同一会话执行任务，也返回 `409`。
- 上传附件会先保存到运行目录，再写入 user message metadata。
- SSE 断开后，worker 可能进入 detached 状态继续运行。

### `POST /api/sessions/{session_id}/interrupt`

停止当前会话活跃任务。

响应：

```json
{
  "interrupted": true,
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "request_id": "req_xxx",
  "turn_id": "turn_xxx",
  "message": "上一次回合被用户中断，当前任务已停止。"
}
```

无活跃任务：

```json
{
  "interrupted": false,
  "session_id": "1c2030c74d144c40aef2b0e6f59718f5",
  "reason": "no_active_run"
}
```

### SSE 事件格式

```json
{
  "event": "assistant_delta",
  "data": {},
  "ts": 1741234567890,
  "request_id": "req_xxx"
}
```

常见事件：

- `session_created`
- `answer_started`
- `assistant_delta`
- `tool_call_started`
- `tool_call_finished`
- `tool_error_feedback`
- `tool_approval_request`
- `approval_resolved`
- `attachment_received`
- `attachment_processed`
- `checkpoint_created`
- `plan_updated`
- `user_input_requested`
- `turn_interrupted`
- `final_response`
- `error`
- `stream_completed`

## 6. 审批接口

### `GET /api/sessions/{session_id}/pending-approval`

返回当前会话待审批工具调用。

```json
{
  "session_id": "session_id",
  "pending": {
    "approval_request_id": "apr_xxx",
    "turn_id": "turn_xxx",
    "tool": "terminal",
    "arguments": {
      "command": "npm install"
    },
    "reason": "terminal_mutation_or_unknown",
    "timeout_seconds": 120,
    "remaining_seconds": 78
  }
}
```

### `POST /api/sessions/{session_id}/approve`

```json
{
  "approval_request_id": "apr_xxx"
}
```

### `POST /api/sessions/{session_id}/reject`

```json
{
  "approval_request_id": "apr_xxx"
}
```

approve / reject 响应：

```json
{
  "session_id": "session_id",
  "approval_request_id": "apr_xxx",
  "approved": true,
  "already_resolved": false
}
```

### `GET /api/sessions/{session_id}/multiagent-approvals`

返回父会话下所有子代理待审批项。

### `POST /api/sessions/{session_id}/multiagent-approvals/{approval_request_id}/approve`

通过子代理工具审批。

### `POST /api/sessions/{session_id}/multiagent-approvals/{approval_request_id}/reject`

拒绝子代理工具审批。

## 7. 配置接口

### `GET /api/config/project`

读取项目 `newman.yaml`。

### `PUT /api/config/project`

保存项目 `newman.yaml`。

```json
{
  "content": "server:\n  port: 8005\n"
}
```

保存前会校验 YAML 和配置结构。该接口不会自动 reload。

### `GET /api/config/env`

读取项目 `.env`。

### `PUT /api/config/env`

保存项目 `.env`，并同步更新当前进程环境变量。

```json
{
  "content": "NEWMAN_MODELS_PRIMARY_MODEL=gpt-4.1-mini\n"
}
```

### `POST /api/config/reload`

重新加载配置、runtime、scheduler 与 channels。

```json
{
  "reloaded": true,
  "path": "/root/newman/newman.yaml",
  "effective_workspace": "/root/newman",
  "warnings": []
}
```

## 8. 工作区接口

### `GET /api/workspace/memory`

读取 stable memory 文件。

返回 `newman`、`user`、`memory`、`skills` 四类文件内容和更新时间。

### `PUT /api/workspace/memory/{memory_key}`

更新 stable memory 文件。

`memory_key` 支持：

- `newman`
- `user`
- `memory`
- `skills`

### `GET /api/workspace/roots`

返回 workspace、browse root、output root、可读根、可写根和保护根。

### `GET /api/workspace/files?path=.`

浏览目录或读取文本文件预览。

目录最多返回前 `200` 项；文件内容最多返回前 `20000` 字符。

### `GET /api/workspace/file-content?path=...&download=false`

返回完整文件响应。适合图片、PDF、二进制文件或下载。

### `GET /api/workspace/upload-content?path=...&download=false`

读取允许目录内的上传文件。

### `GET /api/workspace/attachment-content?path=...&download=false`

读取允许目录内的附件文件。

允许根包括：

- `backend_data/uploads/chat`
- `<workspace>/user_uploads`
- `<workspace>/parser_outputs`

## 9. 审计与 Usage

### `GET /api/audit/{session_id}`

返回原始审计日志行。

前端恢复 timeline 时优先使用：

```text
GET /api/sessions/{session_id}/events
```

### `GET /api/usage/summary`

返回全局模型 usage 汇总。

查询参数：

- `days`：默认 `7`，范围 `1..366`
- `tz`：默认 `Asia/Shanghai`
- `model`：可选
- `recent_limit`：默认 `7`，范围 `1..100`
- `include_estimated`：默认 `false`

返回维度包括：

- `totals`
- `by_day`
- `by_model`
- `by_request_kind`
- `by_session`
- `recent_records`

## 10. 插件、工具与 Skill

### Plugins

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/plugins` | 获取插件列表 |
| `POST` | `/api/plugins/import` | 从本地路径导入插件 |
| `POST` | `/api/plugins/rescan` | 重新扫描插件 |
| `GET` | `/api/plugins/{plugin_name}` | 获取插件详情 |
| `POST` | `/api/plugins/{plugin_name}/enable` | 启用插件 |
| `POST` | `/api/plugins/{plugin_name}/disable` | 禁用插件 |
| `PUT` | `/api/plugins/{plugin_name}` | 更新插件 manifest |
| `DELETE` | `/api/plugins/{plugin_name}` | 删除插件 |

### Tools

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/tools` | 获取工具列表 |
| `GET` | `/api/tools/{tool_name}` | 获取工具详情 |
| `POST` | `/api/tools/rescan` | 重新扫描工具生态 |

当前内置工具从 `backend/tools/impl/` 动态发现；插件和 MCP 可额外挂载工具。

### Skills

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/skills` | 获取 Skill 列表 |
| `POST` | `/api/skills/import` | 从本地路径导入 Skill |
| `POST` | `/api/skills/upload` | 上传并安装 Skill |
| `GET` | `/api/skills/{skill_name}` | 获取 Skill 详情 |
| `PUT` | `/api/skills/{skill_name}` | 更新 Skill |
| `DELETE` | `/api/skills/{skill_name}` | 删除 Skill |

### Plugin Drafts

Plugin Drafts 用于通过自然语言 `request` 或结构化 `PluginSpec` 生成、校验并审批 Newman 插件。MVP 仅支持插件内 Skill 和 CLI wrapper commands；草稿安装后默认 disabled。自然语言入口默认生成 Skill 型插件；只有需求中显式给出 `工具名` / `命令` 等字段时才会生成 CLI wrapper。

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/plugin-drafts` | 获取插件草稿列表 |
| `POST` | `/api/plugin-drafts` | 创建插件草稿，可传 `request` 或 `spec`，可选自动生成并校验 |
| `GET` | `/api/plugin-drafts/{draft_id}` | 获取草稿详情 |
| `GET` | `/api/plugin-drafts/{draft_id}/review` | 刷新并获取安装前审计报告 |
| `POST` | `/api/plugin-drafts/{draft_id}/validate` | 校验草稿包和安全规则 |
| `POST` | `/api/plugin-drafts/{draft_id}/approve` | 明确审批草稿安装 |
| `POST` | `/api/plugin-drafts/{draft_id}/install` | 安装已审批草稿，默认禁用插件 |
| `POST` | `/api/plugin-drafts/{draft_id}/reject` | 拒绝草稿 |
| `POST` | `/api/plugin-drafts/{draft_id}/rollback` | 回滚已安装草稿 |

草稿详情中的 `review` 包含安装目标、已存在插件冲突、文件变更、环境变量、CLI wrapper、确认步骤和安全提示，用于 UI 在审批/安装前展示可审计信息。

## 11. MCP 接口

### `GET /api/mcp/servers`

返回 MCP server 配置与连接状态。

### `POST /api/mcp/servers`

创建或更新 MCP server。

请求体使用 `MCPServerConfig`。

### `DELETE /api/mcp/servers/{server_name}`

删除 MCP server。

### `POST /api/mcp/servers/{server_name}/reconnect`

重连 MCP server。

### `GET /api/mcp/resources`

返回 MCP resources 与 server 状态。

## 12. Multi-agent 接口

### `GET /api/multiagent/runs/{run_id}`

获取 multi-agent run 详情和任务列表。

### `GET /api/multiagent/tasks/{task_id}`

获取子任务详情。

### `POST /api/multiagent/runs/{run_id}/cancel`

取消整个 run。

```json
{
  "reason": "user_requested"
}
```

### `POST /api/multiagent/tasks/{task_id}/cancel`

取消单个子任务。

```json
{
  "reason": "user_requested"
}
```

## 13. Scheduler 接口

### `GET /api/scheduler/tasks`

返回定时任务列表。

### `GET /api/scheduler/tasks/{task_id}/runs`

返回任务运行记录。

查询参数：

- `limit`：默认 `20`，范围 `1..100`

### `GET /api/scheduler/alerts`

返回调度告警。

### `POST /api/scheduler/tasks`

创建任务。

```json
{
  "name": "每日总结",
  "cron": "0 9 * * *",
  "timezone": "Asia/Shanghai",
  "approval_mode": "auto_allow",
  "enabled": true,
  "max_retries": 5,
  "source": "api",
  "action": {
    "type": "session_message",
    "session_id": "session_id",
    "content": "生成今天的项目摘要"
  }
}
```

`action.type` 支持：

- `session_message`
- `background_task`

### `PATCH /api/scheduler/tasks/{task_id}`

更新任务。请求体字段均可选。

### `POST /api/scheduler/tasks/{task_id}/enable`

启用任务。

### `POST /api/scheduler/tasks/{task_id}/disable`

禁用任务。

### `POST /api/scheduler/tasks/{task_id}/run`

立即执行任务。

### `DELETE /api/scheduler/tasks/{task_id}`

删除任务。

## 14. Channels 接口

### `GET /api/channels/status`

返回所有 Channel 状态。

### `GET /api/channels/events/stream`

返回 Channel 事件 SSE 流。

### `GET /api/channels/feishu/setup/status`

返回飞书 Channel 配置状态。

### `POST /api/channels/feishu/setup/validate`

校验飞书配置。

```json
{
  "timeout_seconds": 10
}
```

### `POST /api/channels/feishu/setup/test`

执行飞书接入测试。

```json
{
  "timeout_seconds": 45,
  "validate_first": true
}
```

### `POST /api/channels/{platform}/webhook`

legacy webhook 入口。`platform` 例如：

- `feishu`
- `wecom`

当前推荐飞书优先使用 Channel SDK 长连接。

## 15. Runtime Location

### `POST /api/runtime/location/resolve`

把浏览器经纬度解析为城市级位置。

```json
{
  "latitude": 31.2304,
  "longitude": 121.4737
}
```

响应：

```json
{
  "resolved": true,
  "city": "Shanghai",
  "source": "browser_geolocation",
  "precision": "city",
  "captured_at_utc": "2026-07-05T10:00:00+00:00"
}
```

## 16. Evolution 接口

### `GET /api/evolution/runs`

返回自进化运行列表。

查询参数：

- `limit`：可选

### `GET /api/evolution/runs/{run_id}`

返回自进化运行详情。

### `POST /api/evolution/run`

手动触发自进化。

```json
{
  "session_id": "session_id",
  "trigger": "manual"
}
```

### `POST /api/evolution/runs/{run_id}/rollback`

回滚一次自进化运行。

## 17. 当前路由总表

### System

| Method | Path |
| --- | --- |
| `GET` | `/healthz` |
| `GET` | `/readyz` |

### Auth / Bootstrap

| Method | Path |
| --- | --- |
| `GET` | `/api/bootstrap/status` |
| `POST` | `/api/bootstrap/setup` |
| `GET` | `/api/auth/status` |
| `POST` | `/api/auth/login` |
| `POST` | `/api/auth/logout` |
| `POST` | `/api/auth/regenerate-token` |

### Sessions / Messages

| Method | Path |
| --- | --- |
| `POST` | `/api/sessions` |
| `POST` | `/api/sessions/stream` |
| `GET` | `/api/sessions` |
| `GET` | `/api/sessions/{session_id}` |
| `PATCH` | `/api/sessions/{session_id}` |
| `DELETE` | `/api/sessions/{session_id}` |
| `POST` | `/api/sessions/{session_id}/messages` |
| `POST` | `/api/sessions/{session_id}/interrupt` |
| `GET` | `/api/sessions/{session_id}/usage` |
| `GET` | `/api/sessions/{session_id}/events` |
| `POST` | `/api/sessions/{session_id}/compress` |
| `POST` | `/api/sessions/{session_id}/restore-checkpoint` |
| `PATCH` | `/api/sessions/{session_id}/collaboration-mode` |
| `GET` | `/api/sessions/{session_id}/plan-draft` |
| `PUT` | `/api/sessions/{session_id}/plan-draft` |
| `GET` | `/api/sessions/{session_id}/multiagent-runs` |

### Approvals

| Method | Path |
| --- | --- |
| `GET` | `/api/sessions/{session_id}/pending-approval` |
| `POST` | `/api/sessions/{session_id}/approve` |
| `POST` | `/api/sessions/{session_id}/reject` |
| `GET` | `/api/sessions/{session_id}/multiagent-approvals` |
| `POST` | `/api/sessions/{session_id}/multiagent-approvals/{approval_request_id}/approve` |
| `POST` | `/api/sessions/{session_id}/multiagent-approvals/{approval_request_id}/reject` |

### Config / Workspace

| Method | Path |
| --- | --- |
| `GET` | `/api/config/project` |
| `PUT` | `/api/config/project` |
| `GET` | `/api/config/env` |
| `PUT` | `/api/config/env` |
| `POST` | `/api/config/reload` |
| `GET` | `/api/workspace/memory` |
| `PUT` | `/api/workspace/memory/{memory_key}` |
| `GET` | `/api/workspace/roots` |
| `GET` | `/api/workspace/files` |
| `GET` | `/api/workspace/file-content` |
| `GET` | `/api/workspace/upload-content` |
| `GET` | `/api/workspace/attachment-content` |

### Ecosystem

| Method | Path |
| --- | --- |
| `GET` | `/api/plugins` |
| `POST` | `/api/plugins/import` |
| `POST` | `/api/plugins/rescan` |
| `GET` | `/api/plugins/{plugin_name}` |
| `POST` | `/api/plugins/{plugin_name}/enable` |
| `POST` | `/api/plugins/{plugin_name}/disable` |
| `PUT` | `/api/plugins/{plugin_name}` |
| `DELETE` | `/api/plugins/{plugin_name}` |
| `GET` | `/api/tools` |
| `GET` | `/api/tools/{tool_name}` |
| `POST` | `/api/tools/rescan` |
| `GET` | `/api/skills` |
| `POST` | `/api/skills/import` |
| `POST` | `/api/skills/upload` |
| `GET` | `/api/skills/{skill_name}` |
| `PUT` | `/api/skills/{skill_name}` |
| `DELETE` | `/api/skills/{skill_name}` |

### MCP / Multi-agent / Scheduler / Channels

| Method | Path |
| --- | --- |
| `GET` | `/api/mcp/servers` |
| `POST` | `/api/mcp/servers` |
| `DELETE` | `/api/mcp/servers/{server_name}` |
| `POST` | `/api/mcp/servers/{server_name}/reconnect` |
| `GET` | `/api/mcp/resources` |
| `GET` | `/api/multiagent/runs/{run_id}` |
| `GET` | `/api/multiagent/tasks/{task_id}` |
| `POST` | `/api/multiagent/runs/{run_id}/cancel` |
| `POST` | `/api/multiagent/tasks/{task_id}/cancel` |
| `GET` | `/api/scheduler/tasks` |
| `GET` | `/api/scheduler/tasks/{task_id}/runs` |
| `GET` | `/api/scheduler/alerts` |
| `POST` | `/api/scheduler/tasks` |
| `PATCH` | `/api/scheduler/tasks/{task_id}` |
| `POST` | `/api/scheduler/tasks/{task_id}/enable` |
| `POST` | `/api/scheduler/tasks/{task_id}/disable` |
| `POST` | `/api/scheduler/tasks/{task_id}/run` |
| `DELETE` | `/api/scheduler/tasks/{task_id}` |
| `GET` | `/api/channels/status` |
| `GET` | `/api/channels/events/stream` |
| `GET` | `/api/channels/feishu/setup/status` |
| `POST` | `/api/channels/feishu/setup/validate` |
| `POST` | `/api/channels/feishu/setup/test` |
| `POST` | `/api/channels/{platform}/webhook` |

### Audit / Usage / Runtime / Evolution

| Method | Path |
| --- | --- |
| `GET` | `/api/audit/{session_id}` |
| `GET` | `/api/usage/summary` |
| `POST` | `/api/runtime/location/resolve` |
| `GET` | `/api/evolution/runs` |
| `GET` | `/api/evolution/runs/{run_id}` |
| `POST` | `/api/evolution/run` |
| `POST` | `/api/evolution/runs/{run_id}/rollback` |

## 18. 当前边界

- `server.host`、`server.port`、CORS 等监听层配置修改后需要重启进程才完全生效。
- `thread_isolation` 只隔离上下文，不隔离文件系统；多个任务仍可能同时改同一工作区。
- Channel webhook 是 legacy 入口；飞书推荐走 Channel SDK 长连接。
- `context_usage` 是下一次请求预算估算，不是 provider 物理 context limit。
- Linux 原生沙箱当前以 bubblewrap 为主；Windows/macOS 源码运行时的原生沙箱能力不是同一套实现。
