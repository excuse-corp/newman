# M05 Sandbox — 执行沙箱

> Newman 模块 PRD · Phase 1 · 预估 5 工作日

---

## 一、模块目标

提供基于 Docker 的受限运行时，确保 Shell 和 Python 代码在安全边界内执行。

---

## 二、功能范围

### ✅ 包含

- Docker 容器生命周期管理（创建、启动、停止、销毁）
- 资源限制（CPU / 内存 / 磁盘 / 网络）
- Workspace 目录挂载（可读写）
- 执行超时与强制终止
- 标准输出/错误捕获与截断

### ❌ 不包含

- 远程沙箱
- 多租户隔离

---

## 三、前置依赖

无（Docker 基础设施）

---

## 四、文件结构

```text
sandbox/
  docker_sandbox.py       # Docker 容器管理
  resource_limits.py      # 资源限制配置
  workspace_mount.py      # Workspace 目录挂载
  Dockerfile              # 沙箱基础镜像
```

---

## 五、核心设计

### 资源限制默认值

| 资源 | 默认限制 |
|------|----------|
| CPU | 1 核 |
| 内存 | 512 MB |
| 磁盘 | 1 GB |
| 网络 | 仅 workspace 内访问，外网受限 |
| 执行超时 | 30 秒（可配置） |

### 执行流程

```text
ToolOrchestrator 请求执行
  ↓
DockerSandbox 创建/复用容器
  ↓
挂载 Workspace 目录
  ↓
执行命令（带超时监控）
  ↓
捕获 stdout / stderr
  ↓
截断过长输出（默认 10KB）
  ↓
返回 ToolExecutionResult
  ↓
容器闲置超时后自动销毁
```

### 安全约束

- 容器以非 root 用户运行
- 禁止特权模式
- 禁止挂载宿主机敏感目录
- 网络默认关闭，需白名单开启

---

## 六、验收标准

1. Shell 命令在 Docker 容器内执行，不影响宿主机
2. 资源超限时容器被正确终止
3. 执行超时能被检测并返回结构化错误
4. Workspace 目录可读写，其他目录只读
5. 过长输出被截断且不丢失关键信息（保留头尾）

---

## 七、技术备注

- 使用 docker-py（docker SDK for Python）管理容器
- 沙箱镜像预装 Python 3.11、常用系统工具
- 容器池策略：预热 1 个空闲容器，按需扩展，闲置 5 分钟后销毁
