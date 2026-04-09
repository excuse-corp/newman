# M10 MCP — 外部能力接入

> Newman 模块 PRD · Phase 3 · 预估 6 工作日

---

## 一、模块目标

实现 MCP 协议接入，将外部能力提供者纳入统一工具注册表。

---

## 二、功能范围

### ✅ 包含

- MCP Client 实现
- MCP Server 配置管理
- MCP 工具注册到 ToolRegistry
- MCP 工具审批策略配置
- MCP 资源暴露

### ❌ 不包含

- MCP Server 开发框架
- MCP 市场

---

## 三、前置依赖

- M03 Tools（ToolRegistry）
- M09 Plugin（MCP 可作为插件子模块）

---

## 四、文件结构

```text
mcp/
  client.py               # MCP Client 实现
  config.py               # MCP Server 配置管理
  tool_adapter.py         # MCP 工具 → Tool 适配器
  resource_adapter.py     # MCP 资源适配器
```

---

## 五、核心设计

### MCP Server 配置

```yaml
mcp_servers:
  - name: local-inline
    transport: inline
    requires_approval: false
    tools:
      - name: echo_text
        description: Return inline MCP output
        input_schema:
          type: object
          properties:
            text:
              type: string
        risk_level: low
    resources:
      - uri: memory://inline/context
        name: inline-context
        description: Inline MCP resource
        mime_type: text/markdown
        content: "# hello"

  - name: local-stdio
    transport: stdio
    command: ["python"]
    args: ["-m", "demo_mcp_server"]
    env:
      DEMO_MODE: "1"
    requires_approval: false

  - name: web-search
    transport: http_json
    url: "http://localhost:8080/mcp"
    requires_approval: true

  - name: web-search-sse
    transport: http_sse
    url: "http://localhost:8081/mcp"
    requires_approval: true
```

### 工具注册流程

```text
MCP Server 启动
  ↓
MCP Client 连接并获取工具列表
  ↓
tool_adapter 转换为 Newman Tool 格式
  ↓
注册到 ToolRegistry（与本地 Tool 统一管理）
  ↓
按配置设置审批策略
```

### 与本地 Tool 的统一

- MCP 工具与本地 Tool 共享同一套 ToolRouter → ToolOrchestrator 流程
- MCP 工具的 risk_level 和 requires_approval 由配置决定
- MCP 工具的错误也走统一的 ErrorClassifier

### 当前实现口径

- 当前目标以“能注册、能调用、能审批、能报错”为准
- `inline`、`http_json`、`stdio` 已是优先保证路径
- `http_sse` 当前按“单次请求可调用”实现，不追求长连接会话复用
- 当前不以“必须使用官方 MCP Python SDK”为交付前提
- 当前 `stdio` 为 Newman 自定义 newline-delimited JSON bridge

### 当前约定端点

对于 `http_json` / `http_sse`，当前 bridge 约定：

- `GET /tools`
- `GET /resources`
- `POST /invoke/{tool_name}`

对于 `stdio`，当前 bridge 约定消息：

- `tools.list`
- `resources.list`
- `tools.invoke`

---

## 六、验收标准

1. MCP Server 配置后其工具自动出现在注册表
2. MCP 工具与本地 Tool 共享审批流程
3. MCP Server 断连时返回结构化错误
4. MCP 资源能被正确暴露给模型

---

## 七、技术备注

- 当前不强制使用官方 Python SDK，以稳定可调用为先
- 支持 `inline`、`stdio`、`http_json`、`http_sse`
- MCP Server 进程生命周期由 Newman 管理

---

## 八、当前完成度说明

截至当前版本，M10 已完成：

- MCP Server 配置管理
- MCP 工具注册到 `ToolRegistry`
- MCP 工具接入统一审批流程
- `inline`、`http_json`、`stdio`、`http_sse` 四种 bridge 传输的最小可用实现
- MCP 资源列表整理与运行时暴露
- MCP 状态查询、删除、重连 API

当前仍未完成：

- 官方 MCP Python SDK 接入
- 完整官方 stdio 协议对齐
- 完整 SSE 长连接会话复用模型
- MCP 前端管理界面
