# M09 Plugin & Skill — 插件与技能体系

> Newman 模块 PRD · Phase 3 · 预估 8 工作日

---

## 一、模块目标

实现插件目录约定、插件加载器、Skill 注册与注入、Hook 生命周期扩展点。

---

## 二、功能范围

### ✅ 包含

- Plugin 目录约定（plugin.yaml / skills/ / hooks/ / mcp/ / ui/）
- PluginLoader（扫描、验证、加载）
- PluginRegistry（启用 / 禁用 / 卸载）
- Skill 注入策略（Snapshot Injection + On-demand Read）
- Hook 注册与触发（SessionStart / PreToolUse / PostToolUse / SessionEnd / FileChanged）
- 热加载机制

### ❌ 不包含

- 插件市场
- 插件签名验证

---

## 三、前置依赖

- M03 Tools（插件可注册工具）
- M04 Runtime（Hook 嵌入主循环）

---

## 四、文件结构

```text
plugins/
  plugin_loader.py        # 插件扫描与加载
  plugin_registry.py      # 插件状态管理
  plugin_schema.py        # plugin.yaml 校验
skills/
  skill_registry.py       # Skill 注册表
  skill_injector.py       # Skill 注入（Snapshot + On-demand）
hooks/
  hook_manager.py         # Hook 生命周期管理
  hook_types.py           # Hook 类型定义
```

---

## 五、核心设计

### 插件目录结构

```text
plugins/
  <plugin_name>/
    plugin.yaml
    skills/
      <skill_name>/SKILL.md
    hooks/
    mcp/
    ui/
```

### Plugin 元数据（plugin.yaml）

```yaml
name: example-plugin
version: 1.0.0
description: 示例插件
enabled_by_default: true
skills:
  - name: code_review
    path: skills/code_review/SKILL.md
hooks:
  - event: PreToolUse
    handler: hooks/pre_tool_check.py
mcp_servers: []
required_permissions:
  - read_file
  - terminal
```

### Skill 注入策略

| 方式 | 时机 | 内容 |
|------|------|------|
| Snapshot Injection | 每轮 PromptAssembler | Skills 摘要列表注入 Stable Context |
| On-demand Read | 模型请求时 | 通过 read_file 读取具体 SKILL.md |

### Hook 生命周期

| Hook 事件 | 触发时机 |
|-----------|----------|
| SessionStart | 会话创建时 |
| PreToolUse | 工具执行前 |
| PostToolUse | 工具执行后 |
| SessionEnd | 会话结束时 |
| FileChanged | 工作区文件变更时 |

### 热加载规则

- 插件状态变更后重新计算可用工具与技能集合
- 当前运行中的 SessionTask 不强制中断
- 下一轮生效

---

## 六、验收标准

1. 插件目录放入后自动扫描加载
2. 插件启停后下一轮生效，不中断当前会话
3. Skill Snapshot 正确注入 Stable Context
4. Hook 触发顺序可预测且受沙箱约束
5. plugin.yaml 校验失败时给出清晰错误信息

---

## 七、技术备注

- PluginLoader 使用 watchdog 监控 plugins/ 目录变化
- Hook handler 在独立线程/进程中执行，有超时限制
- Skill 文件变更触发 Snapshot 重新生成
