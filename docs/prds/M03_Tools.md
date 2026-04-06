# M03 Tools — 工具注册与执行

> Newman 模块 PRD · Phase 1 · 预估 10 工作日

---

## 一、模块目标

实现 5 个核心工具、统一工具注册表、工具路由与治理层，包括两级审批机制和 Permission Context。

---

## 二、功能范围

### ✅ 包含

- Tool 基类与元数据规范（name, description, input_schema, risk_level, requires_approval, timeout_seconds, allowed_paths/domains）
- ToolRegistry（统一注册表）
- ToolRouter（匹配、静态检查、分发）
- ToolOrchestrator（审批、超时、重试、审计、终止控制）
- 两级审批机制（Level 1 静默拦截 + Level 2 人在回路）
- Permission Context（allow / deny / ask 规则）
- 当前核心 Tool：read_file, fetch_url, terminal, search_knowledge_base
- ToolExecutionResult 统一结构

### ❌ 不包含

- MCP 工具集成（Phase 3）
- 自定义工具开发框架

---

## 三、前置依赖

- M05 Sandbox（terminal 需要沙箱）

---

## 四、文件结构

```text
tools/
  base.py                 # Tool 基类与元数据
  registry.py             # ToolRegistry 统一注册表
  router.py               # ToolRouter 路由与静态检查
  orchestrator.py         # ToolOrchestrator 治理层
  approval.py             # 两级审批逻辑
  permission_context.py   # 会话级权限上下文
  result.py               # ToolExecutionResult 定义
  impl/
    read_file.py          # 读文件工具
    fetch_url.py          # 网络请求工具
    terminal.py           # Shell 命令工具
    search_kb.py          # 知识库检索工具
```

---

## 五、核心设计

### Tool 元数据

```python
@dataclass
class ToolMeta:
    name: str
    description: str
    input_schema: dict
    risk_level: Literal["low", "medium", "high", "critical"]
    requires_approval: bool
    timeout_seconds: int
    allowed_paths: list[str] | None = None
    allowed_domains: list[str] | None = None
```

### 两级审批

| 级别 | 触发条件 | 处理方式 |
|------|----------|----------|
| Level 1 静默拦截 | 命中黑名单、明显越权路径、危险命令 | 不弹窗，直接返回结构化拒绝 |
| Level 2 人在回路 | 高风险命令、写入非工作区、白名单外网络、require_approval=true | 暂停执行，推送审批事件，等待用户确认 |

### ToolExecutionResult

```python
@dataclass
class ToolExecutionResult:
    success: bool
    tool: str
    action: str
    category: str
    exit_code: int | None
    summary: str
    stdout: str
    stderr: str
    duration_ms: int
    retryable: bool
    metadata: dict
```

---

## 六、验收标准

1. 5 个工具均可通过 ToolRouter 统一调度
2. Level 1 黑名单命中时直接返回结构化拒绝
3. Level 2 可通过 SSE 推送审批请求并等待用户确认
4. 所有工具返回 ToolExecutionResult 统一结构
5. 工具超时能被正确终止并归类为可恢复错误
6. Permission Context 的 deny 规则能阻止工具暴露给模型

---

## 七、技术备注

- read_file 需支持文本和二进制文件，有大小限制
- fetch_url 需支持 allowed_domains 白名单过滤
- terminal 必须通过 Sandbox 执行
- search_knowledge_base 为 RAG 模块提供的工具接口壳，实际检索逻辑在 M07
