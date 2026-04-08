# M14 Config — 配置管理

> Newman 模块 PRD · Phase 1 · 预估 3 工作日

---

## 一、模块目标

实现统一配置管理，确保配置与代码分离、Prompt 模板独立管理。

---

## 二、功能范围

### ✅ 包含

- 配置加载与验证（YAML 为主）
- 环境变量覆盖
- Prompt 模板管理
- 模型配置、工具配置、审批策略配置

### ❌ 不包含

- 远程配置中心
- 配置热更新

---

## 三、前置依赖

无

---

## 四、文件结构

```text
config/
  loader.py               # 配置加载器
  schema.py               # 配置 Schema 验证
  defaults.yaml           # 默认配置
  prompts/
    newman_template.md    # System Prompt 初始化模板
    user_template.md      # User Memory 模板
    memory_template.md    # Long-term Memory 模板
    skills_snapshot_template.md # Skills 快照初始化模板
    error_feedback.md     # 运行时错误反馈模板
```

---

## 五、核心设计

### 配置层级（优先级从高到低）

1. 环境变量（`NEWMAN_` 前缀）
2. 用户配置文件（`~/.newman/config.yaml`）
3. 项目配置文件（`./newman.yaml`）
4. 默认配置（`config/defaults.yaml`）

### 默认配置示例

```yaml
# defaults.yaml
server:
  host: "0.0.0.0"
  port: 8005

provider:
  type: "openai_compatible"
  model: "gpt-4o"
  endpoint: "https://api.openai.com/v1"
  timeout: 60
  max_tokens: 4096

runtime:
  max_tool_depth: 20
  context_compress_threshold: 0.8
  context_critical_threshold: 0.92

sandbox:
  enabled: true
  backend: "linux_bwrap"
  mode: "workspace-write"
  network_access: false
  writable_roots: []
  timeout: 30
  output_limit_bytes: 10240

approval:
  level1_blacklist:
    - "rm -rf /"
    - "sudo"
  level2_patterns:
    - "write_file_outside_workspace"
    - "process_spawn"
    - "terminal_mutation_or_unknown"
    - "danger_full_access_terminal"
```

### 环境变量覆盖规则

```text
NEWMAN_PROVIDER_MODEL=deepseek-chat
→ provider.model = "deepseek-chat"

NEWMAN_RUNTIME_MAX_TOOL_DEPTH=30
→ runtime.max_tool_depth = 30
```

---

## 六、验收标准

1. 所有配置项有默认值且可被环境变量覆盖
2. 配置验证失败时给出清晰错误信息（指出哪个字段、期望类型、实际值）
3. Prompt 模板可独立编辑不影响代码
4. 配置加载日志显示最终生效值和来源

---

## 七、技术备注

- 使用 Pydantic v2 进行 Schema 验证
- 配置文件监控可后续扩展（watchdog），但 MVP 不实现热更新
- Prompt 模板使用 Jinja2 或简单变量替换
- Phase 1 沙箱配置只要求 Linux 生效；macOS / Windows 保留配置项但执行层暂不实现
