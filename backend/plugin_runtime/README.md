# Plugin Runtime

当前已落地的是 Phase 3 基线能力：

- 扫描工作区 `plugins/` 目录中的 `plugin.yaml`
- 目录内容变化后自动重扫，下一轮会话生效
- 支持插件启用、禁用、重新扫描
- 自动发现 `skills/*/SKILL.md`
- 支持声明式 hook 消息与可执行 hook handler
- 支持插件内嵌的 MCP server 配置
- 支持插件声明 CLI wrapper commands，并把它们注册成结构化 provider tools
- 暴露插件加载错误，便于定位失效的 `plugin.yaml`

`commands[]` 建议最少声明：
- `tool_name`
- `executable`
- `readonly_prefixes`

如需高风险二次确认，可额外声明：
- `confirmation_flag`
- `confirmation_protocol.exit_code`
- `confirmation_protocol.error_type`

约定结构：

```text
plugins/
  <plugin_name>/
    plugin.yaml
    skills/
      <skill_name>/SKILL.md
    hooks/
      <handler>.py
    plugin.yaml  # 可选 commands: 暴露结构化 CLI wrapper tools
```
