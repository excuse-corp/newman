# Newman 沙箱重构技术规格

Status: Phase 0-3 landed; Phase 4 provider/runtime integration landed; macOS/Windows host e2e pending
Target version: Sandbox v2
Last updated: 2026-08-25
Applies to: terminal, plugin CLI, stdio MCP, plugin hooks, subagents, in-process file tools

本文定义 Newman 沙箱重构的目标架构、接口契约、策略解析、后端能力、错误分类、审批升级、配置迁移、测试矩阵和分阶段上线门槛。本文中的 `MUST`、`SHOULD`、`MAY` 分别表示强制要求、默认应满足的要求、可选增强。

## 1. 背景

当前 Newman 原生沙箱主要是 Linux `bwrap` 实现，配置层的 backend 也只允许 `linux_bwrap`。该实现对 terminal 和 plugin CLI 有实际隔离能力，但尚未形成全局一致的沙箱边界：stdio MCP、plugin hook、Office 转换、skill runtime 的 venv/pip 等入口仍可能直接在宿主进程启动；进程内文件工具也未完全共享 `read-only` / `workspace-write` 的沙箱语义。

现有实现还存在两个高优先级风险：

- 失败分类过宽：把任意 stderr 中的 `permission denied` / `operation not permitted` / `read-only file system` 识别为 sandbox denial，可能把命令自身失败误判为沙箱拦截。
- 升级路径可能 fail-open：在 `auto_allow` / unattended 场景下，误判后的 escalation 可能以 `force_unsandboxed=True` 裸跑原命令。

DeepSeek Harness 的可借鉴点是 policy/provider 分离、`ConfinedArgv` 携带 enforcement metadata、runner failure 优先于 denial 分类、`SANDBOX_UNAVAILABLE` fail-closed、session policy 单独解析、跨平台后端明确 `full|partial|unsupported`。不建议直接照搬其 `--ro-bind / /` 默认根只读挂载，因为这会扩大 Newman 当前较窄的宿主可读面。

## 2. 设计目标

Sandbox v2 MUST 满足以下目标：

- 受限模式不可因 sandbox runner 不可用、启动失败或探测失败而裸跑。
- 所有模型可触达的本机外部代码入口共享同一个 per-call sandbox policy。
- 进程内文件工具与 shell/CLI 使用一致的 `read-only`、`workspace-write`、`danger-full-access` 语义。
- runner failure、sandbox denial、普通 command failure 必须结构化区分。
- 权限升级必须一次性、绑定具体调用、绑定命令/argv hash、绑定 policy，并可审计。
- 每个后端必须声明 file/network/process/resource 的 enforcement level：`full`、`partial` 或 `unsupported`。
- 健康检查必须做 functional probe，不得只检查二进制是否存在。
- Docker、scheduler、Feishu auto_allow 等无人值守场景不得静默放宽到裸跑。

## 3. 非目标

Sandbox v2 不承诺以下能力：

- 不替代 Docker、microVM、Firecracker 或远程执行环境。
- 不防护内核漏洞、root escape 或宿主内核级提权。
- 不对远程 HTTP/SSE MCP server 提供本机内核沙箱，只能标记其为 remote/unsupported 并做参数级约束。
- 不默认提供完整资源隔离；CPU、内存、进程数、文件大小限制属于 best-effort resource limits。
- 不保证凭据安全，除非执行入口使用明确的环境变量 allowlist 和 secret 过滤。

## 4. 安全不变量

以下不变量是 merge gate，任何实现不得违反：

1. `read-only` 或 `workspace-write` 下，provider 必须返回 enforcing argv，或返回 `SANDBOX_UNAVAILABLE` / `SANDBOX_PROBE_FAILED`；不得 silent passthrough。
2. `danger-full-access` 只能来自显式部署配置、显式 session mode event，或单次批准的 escalation token。
3. runner failure 不得触发无沙箱重试。
4. generic stderr 关键词不得单独作为 sandbox denial 依据。
5. escalation token 必须绑定 `session_id`、`tool_call_id`、`tool_name`、`argv_sha256`、`policy_hash`、`workspace_root`、`expires_at`。
6. unattended scheduler 默认禁止升级到 `danger-full-access`。
7. `auto_allow` 不得自动批准 sandbox escalation，除非部署配置显式设置 `allow_automatic_full_access: true`，且该设置必须产生启动告警和审计事件。
8. 所有不可信本机外部代码入口必须经过 `SandboxProcessRunner`；无法迁移的入口必须在 metadata 中标记 `sandboxed=false` 和原因。
9. 环境变量默认 allowlist；名称匹配 `TOKEN`、`SECRET`、`API_KEY`、`PASSWORD`、`PRIVATE_KEY`、`CREDENTIAL` 的变量默认过滤。
10. 每次执行结果必须带 sandbox metadata，包含 backend、mode、file/network/process enforcement、runner state、denial state、escalation state、invocation id 和 policy hash。

## 5. 目标架构

建议目录结构：

```text
backend/sandbox/
  models.py
  policy.py
  provider.py
  registry.py
  process.py
  classifier.py
  path_policy.py
  providers/
    linux_bwrap.py
    linux_landlock.py
    macos_seatbelt.py
    windows_acl.py
```

迁移期保留 `backend/sandbox/native_sandbox.py` 的 `NativeSandbox` facade，对外接口尽量兼容，内部委托 `SandboxProcessRunner`。旧调用方先接入 facade，待入口全部迁移后再收敛为 v2 API。

核心分层：

- `policy.py`：解析部署配置、session event、per-call approval，生成 `SandboxPolicy`。
- `provider.py`：定义 provider 抽象，只负责 probe 和 argv confinement，不负责 subprocess 生命周期。
- `registry.py`：按平台和配置选择 provider，维护 functional probe cache。
- `process.py`：统一启动、流式输出、timeout、cancel、descendant cleanup、环境变量过滤和结果 metadata。
- `classifier.py`：按 runner failure rules、backend denial signatures 和退出状态分类。
- `path_policy.py`：为进程内文件工具提供 canonical path fence。

## 6. 统一数据模型

Python 类型定义 SHOULD 采用 dataclass 或 pydantic model，但字段语义必须稳定。

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Mapping, Sequence

SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
Enforcement = Literal["full", "partial", "unsupported"]
SandboxBackend = Literal[
    "auto",
    "linux_bwrap",
    "linux_landlock",
    "macos_seatbelt",
    "windows_acl",
    "none",
]

@dataclass(frozen=True)
class SandboxPolicy:
    mode: SandboxMode
    workspace_root: Path
    cwd: Path
    readable_roots: tuple[Path, ...] = ()
    writable_roots: tuple[Path, ...] = ()
    protected_roots: tuple[Path, ...] = ()
    network_access: bool = False
    require_network_isolation: bool = True
    require_process_isolation: bool = True
    allow_partial_enforcement: bool = False
    env_allowlist: tuple[str, ...] = ("PATH", "LANG", "LC_*")
    timeout_seconds: int | None = None
    output_limit_bytes: int | None = None
    session_id: str | None = None
    tool_call_id: str | None = None
    invocation_id: str = ""
    source: Literal["deployment", "session", "approval"] = "deployment"

@dataclass(frozen=True)
class RunnerFailureRule:
    exit_codes: tuple[int, ...] = ()
    stderr_prefixes: tuple[str, ...] = ()
    stderr_substrings: tuple[str, ...] = ()
    reason: str = ""

@dataclass(frozen=True)
class ConfinedArgv:
    argv: tuple[str, ...]
    backend: str
    file_enforcement: Enforcement
    network_enforcement: Enforcement
    process_enforcement: Enforcement
    resource_enforcement: Enforcement = "partial"
    denial_signatures: tuple[str, ...] = ()
    runner_failure_rules: tuple[RunnerFailureRule, ...] = ()
    notes: tuple[str, ...] = ()

@dataclass(frozen=True)
class PreparedSandboxInvocation:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path
    backend: str
    file_enforcement: Enforcement
    network_enforcement: Enforcement
    process_visibility_enforcement: Enforcement
    process_lifecycle_enforcement: Enforcement
    resource_enforcement: Enforcement = "partial"
    denial_signatures: tuple[str, ...] = ()
    runner_failure_rules: tuple[RunnerFailureRule, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    cleanup: Callable[[], Awaitable[None]] | None = None
    start_new_session: bool = False
```

Provider interface：

```python
@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    backend: str
    file_enforcement: Enforcement
    network_enforcement: Enforcement
    process_enforcement: Enforcement
    resource_enforcement: Enforcement = "partial"
    process_visibility_enforcement: Enforcement = "unsupported"
    process_lifecycle_enforcement: Enforcement = "unsupported"
    detail: str = ""

class SandboxProvider(Protocol):
    name: str

    def probe(self, policy: SandboxPolicy) -> ProviderHealth:
        ...

    def confine(self, argv: Sequence[str], policy: SandboxPolicy) -> ConfinedArgv:
        ...

    def prepare(
        self,
        argv: Sequence[str],
        policy: SandboxPolicy,
        env: Mapping[str, str] | None = None,
    ) -> PreparedSandboxInvocation:
        ...
```

`confine()` MUST accept exact argv only，不接受 shell string。`prepare()` 是 Phase 4 后的新主入口；`confine()` 保留给 Linux bwrap/Landlock 迁移兼容。terminal tool 如果需要 shell 语义，调用方负责构造：

```python
["/usr/bin/bash", "--noprofile", "--norc", "-lc", command]
```

## 7. SandboxProcessRunner

统一 runner 是所有本机外部进程入口的唯一执行器。

```python
@dataclass(frozen=True)
class SandboxRunRequest:
    argv: tuple[str, ...]
    policy: SandboxPolicy
    env: Mapping[str, str] = field(default_factory=dict)
    stdin: bytes | None = None
    stream: bool = False
    label: str = ""

@dataclass(frozen=True)
class SandboxRunResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    error_code: str | None
    error_message: str | None
    metadata: Mapping[str, object]

class SandboxProcessRunner:
    async def run_argv(self, request: SandboxRunRequest) -> SandboxRunResult:
        ...

    async def start_stdio(self, request: SandboxRunRequest) -> "SandboxStdioProcess":
        ...
```

Runner responsibilities：

- 解析 provider，并在 constrained mode 下执行 functional probe。
- 优先调用 provider `prepare()`；旧 provider 无 `prepare()` 时才降级调用 `confine()`。
- 清洗环境变量，合并 allowlist，不传完整 `os.environ`。
- 校验 cwd 必须在 policy 允许范围内。
- 启动子进程、流式输出、截断输出、处理 timeout/cancel。
- 普通退出、timeout、cancel、runner 启动失败、stdio MCP 断开、服务关闭时 MUST 调用 invocation cleanup。
- 使用 provider 提供的 lifecycle hint 清理 descendant processes：POSIX process group、Windows Job Object 或 provider-specific cleanup。
- 执行分类顺序并返回结构化 metadata。
- 当 provider 只能 partial enforcement 且 policy 不允许 partial 时，MUST 在启动前返回 `SANDBOX_PARTIAL_ENFORCEMENT`。

## 8. Policy Resolution

mode 优先级从高到低：

1. 有效的一次性 approval token。
2. session `sandbox/mode` event。
3. deployment config。

workspace 优先级从高到低：

1. immutable session cwd。
2. deployment `sandbox.workspace_root`。
3. project root。

Policy resolver MUST：

- 对所有 root 做 `resolve(strict=False)` 并 canonicalize。
- 拒绝 NUL、换行、非法 URI scheme、明显 traversal 输入。
- `read-only` 下 `writable_roots` 必须为空。
- `workspace-write` 下默认 writable root 为 workspace root；可由 manifest grants 收窄或扩展，但不得与 protected roots 冲突。
- protected root 优先级高于 writable root；冲突返回 `SANDBOX_INVALID_POLICY`。
- 每次 invocation 生成随机 `invocation_id`，并计算稳定 `policy_hash`。

Session mode event 格式：

```json
{
  "type": "sandbox/mode",
  "mode": "read-only|workspace-write|danger-full-access",
  "actor": "user|admin|system",
  "reason": "human readable reason",
  "created_at": "2026-08-23T00:00:00Z"
}
```

模型不得直接写入该 event。只能由用户、管理员或受信系统组件创建。

## 9. 权限升级规格

允许的 widening table：

```text
read-only       -> workspace-write
read-only       -> danger-full-access
workspace-write -> danger-full-access
danger-full-access -> no escalation needed
```

Tool schema MUST 要求 `sandbox_permissions` 与 `justification` 成对出现：

- `sandbox_permissions` 只能是 `workspace-write` 或 `danger-full-access`。
- `justification` 必须是 1 到 500 字符的人类可读说明。
- 请求 mode 不得比当前 effective mode 更窄；更窄请求按当前 mode 执行并记录 metadata。

Approval request MUST 绑定以下字段：

```json
{
  "approval_request_id": "uuid",
  "session_id": "session id",
  "tool_call_id": "tool call id",
  "tool_name": "terminal|plugin_cli|mcp_stdio|hook|file_write|...",
  "requested_mode": "danger-full-access",
  "effective_mode_before": "workspace-write",
  "argv_sha256": "hex sha256 or null for file tools",
  "command_preview": "truncated command preview",
  "policy_hash": "hex sha256",
  "workspace_root": "/canonical/workspace",
  "writable_roots": ["/canonical/workspace"],
  "justification": "why this is needed",
  "expires_at": "2026-08-23T00:05:00Z"
}
```

Approval token MUST be single-use。执行前 consume token；如果 argv、cwd、workspace、writable roots、tool name 或 policy hash 变化，必须重新审批。

Unattended behavior：

- scheduler、webhook、后台自动任务默认返回 `SANDBOX_ESCALATION_DENIED_UNATTENDED`。
- `auto_allow` 只能自动批准普通 tool execution，不得自动批准 sandbox widening。
- 如部署确实需要自动 full access，必须显式设置 `sandbox.escalation.allow_automatic_full_access: true`，并在启动日志、health 和 audit 中标红暴露。

## 10. Provider Selection

配置字段：

```yaml
sandbox:
  backend: auto  # auto|linux_bwrap|linux_landlock|macos_seatbelt|windows_acl|none
```

Selection rules：

- `none` 只能与 `mode: danger-full-access` 一起使用；否则返回 `SANDBOX_INVALID_POLICY`。
- `auto` 先按平台过滤候选 provider，再执行 functional probe。
- functional probe cache key 至少包含 backend、platform、kernel/os version、policy capability requirements。
- constrained mode 下无可用候选时 fail-closed，返回 `SANDBOX_UNAVAILABLE`。
- 如果 provider 只能 partial enforcement，且 policy 要求 `allow_partial_enforcement: false`，必须返回 `SANDBOX_PARTIAL_ENFORCEMENT`。

Recommended auto order：

```text
Linux:  linux_bwrap -> linux_landlock
macOS:  macos_seatbelt
Windows: windows_acl
Other:  unsupported
```

## 11. Linux bwrap Provider

Phase 1 MUST 优先完成 `linux_bwrap` v2，因为这是当前 Newman 已有的真实隔离基础。

Required argv properties：

- MUST 使用 `--new-session`。
- MUST 使用 `--die-with-parent`。
- MUST 使用 `--unshare-user`。
- MUST 使用 `--unshare-pid`。
- MUST 挂载 `--proc /proc`。
- SHOULD 提供最小 `/dev`，例如 `--dev /dev` 或更窄的设备集。
- 当 `network_access=false` 时 MUST 使用 `--unshare-net`。
- readable roots 使用 `--ro-bind SRC DST`。
- writable roots 使用 `--bind SRC DST`。
- protected directory 使用 `--tmpfs DST` 或同等 masking。
- protected file 使用 `/dev/null` mask 或同等只读空文件。
- cwd 使用 `--chdir`，且 cwd 必须在可见 mount 下。

Mount policy：

- MUST 在生成 bind 参数前 materialize 需要写入的目录 source，避免 `bwrap: Can't find source path`。
- MUST 不以 `--ro-bind / /` 作为默认读授权。
- SHOULD 只暴露运行命令必要的 runtime roots，例如 `/usr`、`/usr/local`、`/bin`、`/lib`、`/lib64`、解析后的 interpreter/PATH 目录。
- MUST 不让 PATH 目录扩展为任意宿主读权限；PATH mount 需要 canonicalize、deduplicate，并经过 protected roots 过滤。
- MUST 将 workspace root 作为 `workspace-write` 默认 writable root。

Probe MUST 用生产等价 profile 执行真实命令，至少验证：

- workspace 可见。
- `workspace-write` 下 workspace 可写。
- protected `.env` 不可读。
- 未授权 `/tmp` 不可写。
- `network_access=false` 下无法访问网络。
- runner failure 能被识别为 runner failure，而不是 sandbox denial。

## 12. Linux Landlock Provider

Phase 3 引入 Landlock 作为 Linux fallback 或轻量文件隔离后端。

Landlock provider MUST：

- 使用 native launcher 或稳定二进制，不在 Python 进程内半配置半执行。
- 明确标记 `file_enforcement=partial|full`，取决于 kernel ABI 和实际规则。
- 标记 `network_enforcement=unsupported`，除非另有独立网络隔离机制。
- 标记 `process_enforcement=unsupported`，除非另有 PID/session 隔离机制。
- 当 policy 要求 network/process isolation 且 Landlock 不支持时 fail-closed。
- 在 health 中暴露 ABI version、规则覆盖范围和 partial 原因。

## 13. macOS Seatbelt Provider

Phase 4 引入 `macos_seatbelt`，目标是最小可用的 native partial sandbox：限制文件写入范围，并在 `network_access=false` 时通过 Seatbelt profile 禁止网络访问。该 provider 不提供 Linux PID namespace 等价能力，只能通过进程组做生命周期清理。

实现形态：

```text
/usr/bin/sandbox-exec -p <generated SBPL profile> -- <exact argv>
```

SBPL profile MUST 采用写隔离模型：

```scheme
(version 1)
(allow default)
(deny file-write*)
(allow file-write* (literal "/dev/null"))
(allow file-write* (subpath "<workspace>"))
(allow file-write* (subpath "<private-temp>"))
```

当 `network_access=false` 时 MUST 增加：

```scheme
(deny network*)
```

macOS provider MUST：

- 执行 functional probe，而不只检查 `sandbox-exec` 是否存在；probe 至少验证 profile 可启动、workspace 写入成功、private temp 写入成功、workspace 外写入失败、workspace 内 protected root 写入失败、workspace 内 symlink escape 写入失败、read-only 写 workspace 失败、read-only 写 private temp 成功、`network_access=false` 下 localhost 连接失败。
- 对 workspace、cwd、writable roots、private temp 做 `realpath` 后再生成 profile。
- SBPL 字符串 MUST 拒绝 NUL，并转义反斜杠、双引号和换行。
- 每次 invocation 创建独立 `0700` private temp，并通过 env 设置 `TMPDIR`、`TMP`、`TEMP`。
- 每次 invocation MUST 将 `HOME`、`XDG_CACHE_HOME`、`XDG_CONFIG_HOME`、`XDG_DATA_HOME`、`PYTHONPYCACHEPREFIX` 重定向到 private temp 内，并设置 `PYTHONDONTWRITEBYTECODE=1`，避免工具默认写真实 HOME/cache 或在 read-only 根上生成 bytecode。
- 不授权系统全局临时目录。
- 使用 exact argv，不允许 `shell=True`。
- 使用 `start_new_session=True` 或等价机制建立进程组；timeout/cancel 后 MUST 清理整个进程组。
- profile 编译失败、`sandbox-exec` 缺失、probe 失败时返回 `SANDBOX_UNAVAILABLE`，不得执行原始 argv。
- `sandbox-exec` 默认使用 `/usr/bin/sandbox-exec`，允许通过 `sandbox.provider_path` 指定替代路径；目标必须存在且可执行。runner 自身失败 MUST 通过 runner failure rule 标记为 `SANDBOX_RUNNER_FAILED`，不得被误判为普通命令失败或 sandbox denial。
- 明确标记 `sandbox-exec`/Seatbelt 的 deprecated/compat 风险，不承诺长期稳定。
- workspace 内 protected roots SHOULD 通过 profile 中的后置 `deny file-write*` 覆盖，而不是直接让整个 workspace-write policy 不可用；如果目标系统规则顺序不支持该覆盖，functional probe MUST fail closed。

能力声明：

```text
file_enforcement=full
network_enforcement=full when network_access=false, otherwise unsupported
process_visibility_enforcement=unsupported
process_lifecycle_enforcement=partial
resource_enforcement=partial
```

macOS MVP acceptance：

- `workspace-write` 可写 workspace 和 private temp。
- `read-only` 写 workspace 失败。
- workspace 外写入失败。
- workspace 内 symlink 指向 workspace 外时写入失败，且目标文件不产生副作用。
- `HOME` / `TMPDIR` 均指向 per-invocation private temp，并在执行结束后被清理。
- `network_access=false` 下连接本地测试 listener 失败。
- profile/runner 失败不会裸跑。
- timeout/cancel 后子进程组被清理。

## 14. Windows ACL Provider

Phase 4 引入 `windows_acl`，目标是最小可用的 native partial sandbox：限制文件写入范围，并通过 Job Object 清理进程树。该 provider 不提供读取隔离、网络隔离或进程可见性隔离。

Windows provider 分两层实现：

- Python provider：负责 policy 校验、private temp 生命周期、workspace/temp SID 生成、helper argv 构造、metadata、runner failure rules 和 fail-closed。
- Native helper：负责 Win32 token、ACL、process spawn、Job Object 和退出码镜像。

Helper argv contract：

```text
newman-sandbox-win.exe run
  --workspace <canonical workspace>
  --temp <private temp dir>
  --mode <read-only|workspace-write>
  [--write-sid <workspace sid> --temp-write-sid <temp sid>]
  --
  <exact argv...>
```

Runner failure contract：

```text
stderr prefix: newman-windows-acl-run:
exit code: 127
```

Python provider MUST：

- 非 Windows 平台返回 `SANDBOX_UNSUPPORTED_PLATFORM` 或 `SANDBOX_UNAVAILABLE`。
- helper 缺失、不可执行、probe 失败时 fail-closed。
- workspace、cwd、temp、writable roots 必须 canonicalize。
- workspace、private temp、protected roots 不得相互包含或冲突。
- `read-only` 下不得传 `--write-sid` / `--temp-write-sid`。
- `workspace-write` 下必须传 deterministic workspace SID 和 per-temp random SID。
- 每次 invocation 创建 private temp，并在 cleanup 中删除；cleanup 失败只记录 metadata，不得掩盖 runner failure。
- network isolation 被要求时必须返回 `SANDBOX_PARTIAL_ENFORCEMENT`，除非 policy 显式允许 partial。

Native helper MUST：

- 使用 `CreateRestrictedToken`，启用 `WRITE_RESTRICTED`、`DISABLE_MAX_PRIVILEGE` 和 `LUA_TOKEN` 等限制。
- restricting SID list 至少区分 `read-only` 和 `workspace-write`：`read-only` 不携带 workspace/temp write SID；`workspace-write` 携带 workspace SID 和 temp SID。
- 对 workspace/temp materialize NTFS write ACE；workspace grant 可以 standing reuse，temp grant 必须 revocable。
- 使用 `CreateProcessAsUserW` 或等价 API 启动目标命令。
- 使用 Job Object 并设置 kill-on-job-close，runner 退出时清理子进程树。
- runner 失败时统一输出 `newman-windows-acl-run: <detail>` 并 exit 127；不得 unrestricted spawn。
- 所有 Win32 API 返回值必须检查；失败路径必须 revoke 已应用的 temp grant。

能力声明：

```text
file_enforcement=partial
network_enforcement=unsupported
process_visibility_enforcement=unsupported
process_lifecycle_enforcement=partial
resource_enforcement=partial
```

Windows known boundaries MUST 出现在 README、health detail 和 execution metadata：

- Everyone 可写目录仍可能可写。
- NTFS hard link 是文件对象别名，可能绕过路径边界。
- FAT/非 ACL 文件系统不受 NTFS ACL 约束。
- `WRITE_RESTRICTED` 只限制写访问，不限制读取和网络。
- console isolation 不可用。
- workspace ACE 是 standing grant，可能留下不可见残留；temp ACE 必须可撤销。

Windows MVP acceptance：

- `workspace-write` 可写 workspace/private temp，workspace 外普通 NTFS 写入失败。
- `read-only` 不携带 workspace/temp write SID，写 workspace 失败。
- helper 缺失、token/ACL/spawn/Job Object 失败均不裸跑。
- Job Object 能清理子进程树。
- helper 支持空格、Unicode、引号和长路径。
- Everyone、hard link、FAT 边界测试必须标为 partial/known limitation，而不是 full pass。

## 15. 错误契约与分类

标准错误码：

```text
SANDBOX_UNAVAILABLE
SANDBOX_INVALID_POLICY
SANDBOX_PROBE_FAILED
SANDBOX_RUNNER_FAILED
SANDBOX_DENIED
SANDBOX_DENIAL_CANDIDATE
SANDBOX_PARTIAL_ENFORCEMENT
SANDBOX_ESCALATION_REQUIRED
SANDBOX_ESCALATION_DENIED
SANDBOX_ESCALATION_DENIED_UNATTENDED
```

分类顺序 MUST 固定：

1. Python/subprocess spawn error，例如 executable not found、permission denied on runner binary。
2. Provider `runner_failure_rules`，例如 bwrap 自身启动失败、profile 编译失败、launcher 初始化失败。
3. Backend-specific denial signatures，且必须结合退出码、stderr prefix、runner started state 或 provider metadata。
4. 普通 command failure，保持原始 return code，不触发 sandbox escalation。

MUST NOT 使用全局 generic stderr substring 作为 denial 依据。例如命令输出 `permission denied` 只能是 `SANDBOX_DENIAL_CANDIDATE`，不得自动升级或裸跑。

Execution metadata schema：

```json
{
  "sandboxed": true,
  "backend": "linux_bwrap",
  "mode": "workspace-write",
  "file_enforcement": "full",
  "network_enforcement": "full",
  "process_enforcement": "full",
  "process_visibility_enforcement": "full",
  "process_lifecycle_enforcement": "full",
  "resource_enforcement": "partial",
  "runner_started": true,
  "runner_failed": false,
  "sandbox_denied": false,
  "sandbox_escalated": false,
  "invocation_id": "uuid",
  "policy_hash": "hex sha256",
  "approval_request_id": null,
  "provider_detail": "short non-secret detail"
}
```

## 16. 入口覆盖规格

Sandbox v2 的入口覆盖分为 mandatory 和 explicit unsupported 两类。任何入口不得处于“看似有沙箱但实际裸跑”的中间状态。

Mandatory in Phase 1：

- terminal：通过 `SandboxProcessRunner.run_argv()` 执行 exact argv。
- plugin CLI：通过 `run_argv()` 执行 exact argv；manifest grants 与全局 policy 合并校验；使用 env allowlist。

Mandatory in Phase 2：

- stdio MCP：通过 `SandboxProcessRunner.start_stdio()` 启动长期子进程；重连生成新 invocation；审计 command、args、cwd、env allowlist 和 policy hash。
- plugin hook：默认 `read-only` + `network_access=false`；写入必须来自 manifest grants 或 approval。
- skill runtime venv/pip：通过 runner 或独立可信 worker；不能继续继承完整宿主环境。
- Office conversion (`soffice`)：通过 runner 或独立 worker；转换输出目录必须是 explicit writable root。
- subagent：继承父会话 effective policy 和 workspace；子 agent 不得自行放宽；escalation 必须回到父会话审批。

Explicit unsupported：

- HTTP/SSE MCP：标记 `sandboxed=false`、`backend=remote`、`file_enforcement=unsupported`。本机沙箱不适用于远程 server，只能做参数 guard 和 allowlist。

## 17. 进程内文件工具规格

文件工具包括 write、edit、delete、mkdir、move、copy 等所有会改变本机文件系统的操作。

`path_policy.py` MUST 提供：

```python
class PathPolicy:
    def check_read(self, path: Path, policy: SandboxPolicy) -> PathDecision:
        ...

    def check_write(self, path: Path, policy: SandboxPolicy) -> PathDecision:
        ...

    def check_delete(self, path: Path, policy: SandboxPolicy) -> PathDecision:
        ...
```

Behavior：

- `read-only` 下 mutation tool 直接返回 `SANDBOX_DENIED`。
- `workspace-write` 下 target canonical path 必须在 writable roots 内。
- `danger-full-access` 下不做 workspace fence，但必须审计。
- protected roots 优先于 writable roots。
- 拒绝 NUL、换行、非法 URI、traversal、无法 canonicalize 的路径。
- canonical 检查后必须使用 canonical target 执行实际操作，避免检查 A 写入 B。
- Linux SHOULD 使用 `O_NOFOLLOW`、atomic write + rename。
- 后续增强 SHOULD 使用 `openat2(RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS)` 收敛 symlink TOCTOU。

## 18. 配置 v2

最小可用启用矩阵：

| Backend | 最小可用状态 | File | Network | Process/PID | 默认建议 |
| --- | --- | --- | --- | --- | --- |
| `linux_bwrap` | Linux 推荐默认后端 | `full` | `full` when `network_access=false` | `full` | 生产默认；probe 失败必须 fail-closed |
| `linux_landlock` | Linux partial fallback | `full` | `unsupported` | `unsupported` | 仅显式设置 `allow_partial_enforcement=true` 时使用 |
| `macos_seatbelt` | Phase 4 provider landed; macOS e2e pending | `full` write-effect only | `full` when `network_access=false` | visibility `unsupported`, lifecycle `partial` | 需 `allow_partial_enforcement=true` 才可在要求进程隔离的策略下运行 |
| `windows_acl` | Phase 4 provider/helper source landed; Windows e2e pending | `partial` | `unsupported` | visibility `unsupported`, lifecycle `partial` | 需 helper、`allow_partial_enforcement=true` 且不得要求网络隔离 |
| `none` | 仅允许显式 full access 场景 | `unsupported` | `unsupported` | `unsupported` | 不得在 constrained mode 静默 fallback |

当前发布口径：Linux bwrap 是唯一已在本机验证的 full sandbox；Landlock 是显式 partial 文件隔离；macOS Seatbelt 和 Windows ACL provider 已接入 runtime，但必须通过对应宿主 e2e 后才能宣称该平台可用。最终 Phase 4 发布口径为：三平台具备 native provider，但只有 Linux bwrap 是 full；macOS Seatbelt 和 Windows ACL 均为带边界声明的 partial provider。

目标配置：

```yaml
sandbox:
  enabled: true
  backend: auto
  mode: read-only
  workspace_root: null
  network_access: false
  require_network_isolation: true
  require_process_isolation: true
  allow_partial_enforcement: false
  readable_roots: []
  writable_roots: []
  protected_roots:
    - .env
  env_allowlist:
    - PATH
    - LANG
    - LC_*
  timeout: 30
  output_limit_bytes: 10240
  probe_timeout_ms: 5000
  escalation:
    policy: ask
    allow_automatic_full_access: false
  resource_limits:
    max_processes: null
    cpu_seconds: null
    memory_bytes: null
    file_size_bytes: null
```

Migration rules：

- 旧 `enabled`、`mode`、`network_access` 原样迁移。
- 旧 `backend: linux_bwrap` 保留兼容，但 SHOULD 输出 deprecation warning，推荐 `auto`。
- 旧 readable/writable/protected permissions 统一进入 `SandboxPolicy`。
- `force_unsandboxed` 不得作为外部 tool 参数暴露，只能由已 consume 的 approval token 在 orchestrator 内部生成。
- Docker 默认 `sandbox.enabled=false` 必须在启动 health 和 README 中明确暴露风险，不得显示为 sandbox healthy。

Phase 4 recommended deployment profiles：

Linux source deployment：

```dotenv
NEWMAN_DEPLOY_PROFILE=linux_source_default
```

expands to：

```yaml
sandbox:
  enabled: true
  backend: linux_bwrap
  mode: workspace-write
  network_access: true
  require_network_isolation: false
  require_process_isolation: true
  allow_partial_enforcement: false
```

macOS source deployment with sandboxed commands allowed to access network：

```dotenv
NEWMAN_DEPLOY_PROFILE=macos_source_online
```

expands to：

```yaml
sandbox:
  enabled: true
  backend: macos_seatbelt
  mode: workspace-write
  network_access: true
  require_network_isolation: false
  require_process_isolation: false
  allow_partial_enforcement: true
```

Windows：

```yaml
sandbox:
  enabled: true
  backend: windows_acl
  mode: workspace-write
  network_access: false
  require_network_isolation: false
  require_process_isolation: false
  allow_partial_enforcement: true
```

Default values MUST stay conservative: `allow_partial_enforcement=false`、`require_network_isolation=true`、`require_process_isolation=true`。切换平台不得静默降低安全等级。

## 19. Health 与审计

Health endpoint SHOULD 返回：

```json
{
  "deployment_profile": "linux_source_default",
  "sandbox": {
    "configured": true,
    "enabled": true,
    "deployment_profile": "linux_source_default",
    "platform": "linux",
    "requested_backend": "auto",
    "selected_backend": "linux_bwrap",
    "available": true,
    "probe": "passed",
    "file_enforcement": "full",
    "network_enforcement": "full",
    "process_enforcement": "full",
    "process_visibility_enforcement": "full",
    "process_lifecycle_enforcement": "full",
    "resource_enforcement": "partial",
    "last_error": null
  }
}
```

Audit events：

```text
sandbox_probe_completed
sandbox_provider_selected
sandbox_invocation_started
sandbox_invocation_finished
sandbox_runner_failed
sandbox_denied
sandbox_escalation_requested
sandbox_escalation_resolved
sandbox_policy_rejected
```

Audit MUST NOT 记录 secret、完整环境变量、完整 stdin、未截断 command。命令应记录 sha256 和短 preview。

## 20. 测试矩阵

Unit tests：

- mode widening table。
- policy root canonicalization。
- protected/writable conflict。
- env allowlist 与 secret-name filtering。
- bwrap argv generation。
- missing bind source materialization。
- runner failure rules 优先于 denial signatures。
- fake `permission denied` 不触发 `SANDBOX_DENIED` 或裸跑。
- `read-only` 下 write/edit/delete 返回 `SANDBOX_DENIED`。
- subagent policy inheritance。

Linux e2e tests：

- `workspace-write` 下 workspace 可写。
- `read-only` 下 workspace 和 `/tmp` 不可写。
- protected `.env` 不可读。
- 未授权 `/etc/passwd` 不可读，除非显式 readable root 授权。
- `network_access=false` 无法联网，`network_access=true` 可按配置联网。
- PID namespace 生效。
- symlink escape 被拒绝。
- 缺少 bwrap、user namespace disabled、profile fail 均 no side effect 且不裸跑。
- fake command stderr `permission denied` 不自动 escalation。
- 新 workspace 的 outputs/chat 等 writable roots 不因 source 不存在导致 runner 启动失败。
- timeout/cancel 后 descendant process 被清理。

Entry coverage tests：

- terminal 使用 `SandboxProcessRunner`。
- plugin CLI 使用 `SandboxProcessRunner` 并清洗 env。
- stdio MCP 使用 `start_stdio`，重连生成新 invocation。
- plugin hook 默认 read-only + network deny。
- Office conversion 输出只能写 explicit writable root。
- scheduler unattended 拒绝 full access escalation。
- Feishu `auto_allow` 不自动绕过沙箱。
- HTTP/SSE MCP metadata 明确 remote/unsupported。

Merge gate：

- `python -m pytest -q backend/tests` 通过。
- Linux sandbox e2e suite 通过。
- runner unavailable no-side-effect regression 通过。
- fake denial no-escalation regression 通过。
- health snapshot、audit snapshot、config migration snapshot 通过。

## 21. 分阶段实施

Phase 0: stop-the-bleeding fixes

- 移除 generic stderr -> sandbox denial -> unsandboxed retry 链路。
- `auto_allow` / unattended 禁止自动 `danger-full-access` escalation。
- 修复 `read-only` 下 write/edit/delete 仍可写的问题。
- 修复 bwrap bind source 不存在导致启动失败的问题。
- 添加 runner unavailable no-side-effect regression。
- Docker/README/health 明确 `sandbox.enabled=false` 风险。

Phase 1: unified policy/provider/bwrap

- 新增 `models.py`、`policy.py`、`provider.py`、`registry.py`、`process.py`、`classifier.py`。
- `NativeSandbox` facade 委托 v2 runner。
- terminal 和 plugin CLI 迁移到 `SandboxProcessRunner`。
- bwrap functional probe、env sanitize、metadata、compat config 完成。

Phase 2: all local process entrypoints

- stdio MCP 迁移到 `start_stdio`。
- plugin hook 迁移到 runner。
- skill runtime venv/pip 和 Office conversion 接入 runner 或可信 worker。
- subagent policy inheritance 和 escalation 回父会话审批完成。

Phase 3: Linux fallback

- 引入 Landlock provider。
- 完成 ABI probe、partial enforcement metadata、require isolation fail-closed。
- Linux fallback 测试加入 CI 可选 job。

Phase 4: cross-platform partial backends

- 公共 runner 契约补 `PreparedSandboxInvocation`、provider `prepare()`、async cleanup、进程组/Job lifecycle metadata。
- 引入 macOS Seatbelt provider、SBPL profile builder、private temp、functional probe 和 e2e smoke。
- 引入 Windows ACL Python provider、SID/private temp/helper argv contract、runner failure rules 和 native helper。
- 更新 registry：Linux `linux_bwrap -> linux_landlock`，macOS `macos_seatbelt`，Windows `windows_acl`，Other unsupported。
- health、README、API docs 和 execution metadata 明确 full/partial/unsupported 能力，不允许把 partial 表述为 full。
- CI 增加 macOS 13/14 smoke、Windows 10/11 x64 smoke；Windows ARM64 至少做 helper build smoke。

## 22. Definition of Done

Sandbox v2 完成标准：

- constrained mode 下 runner 不可用、probe 失败、provider 启动失败均不会裸跑。
- 所有模型可触达的本机外部进程要么经过统一 runner，要么显式标记 trusted/unsupported 且有安全说明。
- terminal、plugin CLI、stdio MCP、hook、skill runtime、Office conversion 的 env 都不再默认继承完整 `os.environ`。
- 进程内文件工具与 shell mode 语义一致。
- escalation token 单次、绑定、可审计，且 unattended 默认拒绝 full access。
- health 能真实反映 selected backend 和 enforcement level。
- Linux e2e 证明文件、网络、PID 隔离按 policy 生效。
- 迁移不会静默放宽、关闭或伪装沙箱能力。

## 23. 当前实现进度

截至 2026-08-26，本轮已完成 Phase 0-4 的主要安全骨架与跨平台 provider 接入：

- Phase 0 fail-closed：受限模式下 bwrap 缺失、runner 启动失败、functional probe 失败均不再自动裸跑；generic stderr `permission denied` / `operation not permitted` / `read-only file system` 不再触发自动升级。
- Phase 0 escalation：`auto_allow` 默认拒绝 sandbox escalation；只有显式配置 `allow_automatic_full_access=true` 才允许自动 full access，并返回结构化 `SANDBOX_ESCALATION_DENIED*` 错误码。
- Phase 0 文件工具：`read-only` 下 `write_file` / `edit_file` 返回 `SANDBOX_DENIED`，不会写入；protected 或不可写 root 的 mutation 同样结构化拒绝。
- Phase 1 bwrap facade：`NativeSandbox.health()` 执行 functional probe；`prepare_argv()` 统一生成 wrapped argv、清洗 env、校验 cwd 可见性；writable bind source 会在构造 argv 前 materialize。
- Phase 1 v2 API：新增 `backend/sandbox/models.py`、`policy.py`、`provider.py`、`registry.py`、`process.py`、`classifier.py`、`path_policy.py`，提供 `SandboxPolicy`、`SandboxRunRequest`、`SandboxProcessRunner`、provider health、policy hash 和 runner failure helper，迁移期由 `NativeSandbox` facade 承接既有执行逻辑。
- Phase 3 provider selection：新增 `NativeSandboxProvider`、`LinuxLandlockProvider` 和 `SandboxProviderRegistry`；runtime registry 已注册 bwrap adapter 与 Landlock provider，默认仍优先 bwrap；显式配置的未实现后端返回 `available=false` / `unsupported`，不会静默回退到裸进程。
- Phase 3 token boundary：新增 `EscalationTokenStore`，token 绑定完整调用上下文、过期时间和审批请求；升级重试前原子 consume，重复消费、绑定变更和过期均 fail-closed。
- Phase 3 Landlock：新增 `backend/sandbox/linux_landlock.py`，通过 Landlock ABI probe 和子进程 `preexec_fn` 应用文件访问规则；metadata 标记 `file_enforcement=full`、`network/process_enforcement=unsupported`；默认拒绝 partial enforcement，只有 `allow_partial_enforcement=true` 才允许运行，否则返回 `SANDBOX_PARTIAL_ENFORCEMENT`。
- Phase 3 runner hardening：provider runner 的启动失败、`preexec` 失败和 timeout 统一转为结构化 `SandboxRunResult`；terminal 和 plugin CLI 主路径已通过 `SandboxProcessRunner` 执行，默认 bwrap 仍委托 `NativeSandbox` facade 以保持流式输出和现有分类语义。
- Phase 3 health：`/healthz` 通过 runtime provider registry 报告 selected backend 与 enforcement level；显式 `linux_landlock` 不再被旧 bwrap facade 误报为 unavailable/none。
- Phase 3 token lifecycle：`EscalationTokenStore` 已加入 `max_tokens` 容量上限、已消费 token 保留窗口和容量压力下优先回收 consumed token；活跃 token 不会被静默驱逐，容量耗尽时 fail-closed。
- MVP 收口测试：新增 `/healthz` contract 测试、Landlock 配置级 terminal 主路径 smoke、Linux bwrap e2e 宿主副作用隔离验收、macOS/Windows backend unsupported registry 测试。
- Phase 1 metadata：执行结果统一补充 `sandboxed`、`backend`、`mode`、`file/network/process/resource_enforcement`、`runner_started`、`runner_failed`、`sandbox_denied`、`sandbox_escalated`、`invocation_id`、`policy_hash`、`provider_detail` 和过滤 env 列表。
- Phase 1 env：本机子进程默认使用 allowlist 环境，名称包含 `TOKEN`、`SECRET`、`API_KEY`、`PASSWORD`、`PRIVATE_KEY`、`CREDENTIAL`、`ACCESS_KEY` 的变量强制过滤。
- Phase 2 entrypoints：stdio MCP、plugin hook、旧版 Office conversion、上传 skill runtime wrapper、内置 `ppt-studio` / `html-excel-skill` Python runtime 已接入沙箱入口或自清洗 runtime env；HTTP/SSE MCP 标记为 remote unsupported。
- Phase 2 subagent：multiagent 继承父 sandbox mode/workspace snapshot，并拒绝 agent 自带 `sandbox_mode` / `sandbox_permissions` 放宽字段。
- 审批审计：sandbox escalation approval event/result 绑定 `approval_request_id`、`session_id`、`turn_id`、`tool_call_id`、`tool_name`、`requested_mode`、`effective_mode_before`、`argv_sha256`、`policy_hash`、`sandbox_invocation_id`、`workspace_root`、`writable_roots`、ISO `expires_at` 和 `expires_at_epoch`；unattended 与默认 `auto_allow` 均 fail-closed。
- 配置与文档：`probe_timeout_ms`、`env_allowlist`、`allow_partial_enforcement`、`allow_automatic_full_access` 已进入 defaults、项目模板、Docker 配置和 `.env.example`；README、Getting Started 和 API 文档已记录 fail-closed 与 escalation 默认拒绝语义。
- Phase 4 runner lifecycle：新增 `PreparedSandboxInvocation` 与 provider `prepare()` 契约；`SandboxProcessRunner` 已支持 provider env/cwd/metadata、async cleanup、POSIX process-group cleanup 和 split process visibility/lifecycle metadata。
- Phase 4 macOS provider：新增 `backend/sandbox/macos_seatbelt.py`，实现 SBPL profile builder、workspace 内 protected-write deny、private temp/home/cache 重定向、optional network deny、symlink escape functional probe、fail-closed prepare 和 unit tests；macOS host e2e 已加入但当前 Linux 环境会 skip。
- Phase 4 Windows provider：新增 `backend/sandbox/windows_acl.py`，实现 deterministic workspace SID、per-temp SID、private temp、helper argv contract、runner failure rules、partial enforcement metadata 和 fail-closed prepare。
- Phase 4 Windows helper：新增 `backend/sandbox/windows_runner/`，Windows 源码路径实现 restricted token、NTFS ACL grant/revoke、`CreateProcessAsUserW`、kill-on-close Job Object 和 exit-code mirroring；非 Windows 构建保持 runner-failure stub。
- Phase 4 registry/config：runtime registry 已注册 `macos_seatbelt` 和 `windows_acl`；`auto` 按当前平台选择 provider；显式跨平台 backend fail-closed；配置新增 `require_network_isolation`、`require_process_isolation` 和 `provider_path`。
- Deployment profiles：新增 `NEWMAN_DEPLOY_PROFILE` / `deployment_profile` 选择器，以及 `linux_source_default`、`macos_source_online` 两套源码部署 profile；profile overlay 位于项目/用户配置之后、显式环境变量之前。

本轮验证：

- `python -m compileall -q backend` 通过。
- `g++ -std=c++20 -Wall -Wextra -Werror -o /tmp/newman-sandbox-win-stub backend/sandbox/windows_runner/src/main.cpp` 通过，验证非 Windows fail-closed stub 可编译。
- macOS/provider runner targeted tests 通过：`python -m pytest -q backend/tests/test_cross_platform_sandbox_e2e.py backend/tests/test_macos_seatbelt_provider.py backend/tests/test_sandbox_process_runner.py` -> 17 passed, 4 skipped。
- 沙箱/审批/entrypoint 相关 targeted tests 通过，包括 `test_sandbox_process_runner.py`、`test_sandbox_provider_registry.py`、`test_sandbox_approval_tokens.py`、`test_sandbox_environment.py`、`test_linux_landlock_provider.py`、`test_terminal_permissions.py`、`test_mcp_registry.py`、`test_plugin_runtime.py`、`test_attachment_sandbox.py`、`test_path_permissions.py`、`test_turn_approval.py`。
- API approval contract tests 通过。
- `python -m pytest -q backend/tests` 通过：507 passed, 4 skipped。

仍属于 Phase 3/4 或深水区重构的后续项：

- `SandboxProcessRunner` / provider registry 已成为 terminal 与 plugin CLI 的主入口；默认 bwrap 路径仍委托 `NativeSandbox` facade，后续应把 shell streaming/classification 完全拆入 runner/provider，减少 facade 内部执行逻辑。
- `EscalationTokenStore` 已抽象并接入审批升级路径，且具备进程内容量/回收策略；如果后续引入跨进程 worker 或持久审批队列，应补持久化 token 表和跨进程原子 consume。
- Landlock 当前只提供文件访问隔离，不提供网络/PID 隔离；不能把它作为 bwrap 的等价替代，除非 policy 显式允许 partial enforcement。
- macOS Seatbelt provider 尚未在 macOS 宿主跑过 e2e；不能宣称 macOS 已验收可用。
- Windows ACL helper 源码尚未在 Windows 10/11 宿主构建和跑 e2e；不能宣称 Windows 已验收可用。
- Windows ACL 仍是 partial provider，无法提供读取隔离、网络隔离、进程可见性隔离，也无法覆盖 Everyone ACL、hard link 和非 NTFS/FAT 边界。
