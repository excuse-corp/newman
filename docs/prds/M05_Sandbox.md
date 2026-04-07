# M05 Sandbox — 执行沙箱

> Newman 模块 PRD · Phase 1 · 预估 5 工作日

---

## 一、模块目标

提供 **Linux 原生执行沙箱**，优先保护 `terminal` 工具，使 Shell 命令在明确的文件与网络边界内运行。

本阶段参考 Codex 的设计思路：

- 不采用 Docker 作为主沙箱方案
- 采用 Linux 原生沙箱能力（`bubblewrap`）
- 提供可切换的沙箱模式
- 先完成 Linux 适配
- macOS / Windows 明确标记为待做

---

## 二、功能范围

### ✅ 包含

- Linux 平台的 `bubblewrap` 沙箱执行
- `terminal` 工具接入原生沙箱
- 三种沙箱模式：
  - `read-only`
  - `workspace-write`
  - `danger-full-access`
- 工作区路径作为默认可写根
- 额外 `writable_roots` 配置
- 网络默认关闭（`network_access: false`）
- 执行超时与输出截断
- 健康检查中暴露沙箱状态

### ❌ 不包含

- Docker 容器池沙箱
- 远程沙箱
- macOS 原生沙箱接入
- Windows 原生沙箱接入
- seccomp / syscall 级网络过滤的完整实现

---

## 三、交付边界

### 本阶段交付

- Linux 下 `terminal` 实际通过 `bwrap` 启动
- `workspace-write` 模式允许写入 `workspace` 与配置声明的 `writable_roots`
- `read-only` 模式只允许只读访问
- `danger-full-access` 模式保留为显式关闭沙箱的兼容模式

### 待做

- macOS：Seatbelt / `sandbox-exec`
- Windows：Restricted Token / Job Object / 等效原生方案
- Linux 下更接近 Codex 的 seccomp / network proxy 能力

---

## 四、前置依赖

- Linux 主机
- 系统已安装 `bubblewrap`（`bwrap`）

---

## 五、文件结构

```text
sandbox/
  native_sandbox.py      # 跨平台入口（当前只落 Linux）
  linux_bwrap.py         # Linux bubblewrap 参数构造与执行
  resource_limits.py     # 资源限制配置
  workspace_mount.py     # Workspace 路径解析
  Dockerfile             # 历史原型文件，后续可删除或保留作实验用途
```

---

## 六、核心设计

### 6.1 沙箱模式

| 模式 | 含义 |
|------|------|
| `read-only` | 允许读取工作区，禁止写入 |
| `workspace-write` | 允许写入 `workspace` 与额外 `writable_roots` |
| `danger-full-access` | 不启用原生沙箱，直接在宿主机执行 |

说明：

- Newman Phase 1 默认推荐 `workspace-write`
- 网络默认关闭；当 `network_access=false` 时，Linux 下通过 `bwrap --unshare-net` 关闭网络命名空间访问

### 6.2 执行流程

```text
ToolOrchestrator 请求执行 terminal
  ↓
NativeSandbox 判断：
  - 是否启用沙箱
  - 当前平台是否为 Linux
  - bwrap 是否可用
  - 当前 mode 是什么
  ↓
LinuxBwrapSandbox 构造 bwrap 参数
  ↓
在受限命名空间内执行 shell 命令
  ↓
捕获 stdout / stderr
  ↓
执行超时 / 输出截断
  ↓
返回 ToolExecutionResult
```

### 6.3 与 `workspace` 的关系

- `workspace` 是默认工作目录，不等于安全边界
- 真正的安全边界由原生沙箱决定
- `workspace-write` 模式下，`workspace` 只是默认可写根之一

### 6.4 非 Linux 平台策略

- 若 `sandbox.enabled=true` 且当前不是 Linux
- 当前阶段直接返回结构化错误，明确提示“平台适配待做”
- 不静默降级为“假沙箱”

---

## 七、配置约定

```yaml
sandbox:
  enabled: true
  backend: "linux_bwrap"
  mode: "workspace-write"
  network_access: false
  writable_roots: []
  timeout: 30
  output_limit_bytes: 10240
```

说明：

- `backend` 当前只支持 `linux_bwrap`
- `writable_roots` 为附加可写目录，默认只写 `workspace`
- `timeout` 与 `output_limit_bytes` 为所有执行模式共用限制

---

## 八、验收标准

1. Linux 下 `terminal` 在 `read-only` 模式不能写工作区文件
2. Linux 下 `terminal` 在 `workspace-write` 模式可写 `workspace`
3. Linux 下 `terminal` 在 `danger-full-access` 模式不经过 `bwrap`
4. 当 `network_access=false` 时，沙箱命令无法直接访问外网
5. 未安装 `bwrap` 时返回结构化错误，而不是静默回退
6. 非 Linux 平台开启沙箱时返回“待适配”错误

---

## 九、技术备注

- 当前阶段以工程可落地为目标，优先完成 `bubblewrap` 文件系统 / namespace 级隔离
- 不在本阶段追求 Codex Linux 全量能力（如 seccomp 细粒度策略、代理模式网络）
- 历史 Docker 沙箱原型不作为主执行路径
