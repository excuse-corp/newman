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
  - name: local-file-server
    command: ["python", "-m", "mcp_file_server"]
    args: ["--workspace", "./workspace"]
    requires_approval: false
  - name: web-search
    url: "http://localhost:8080/mcp"
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

---

## 六、验收标准

1. MCP Server 配置后其工具自动出现在注册表
2. MCP 工具与本地 Tool 共享审批流程
3. MCP Server 断连时返回结构化错误
4. MCP 资源能被正确暴露给模型

---

## 七、技术备注

- MCP Client 使用官方 Python SDK
- 支持 stdio 和 HTTP/SSE 两种传输方式
- MCP Server 进程生命周期由 Newman 管理
