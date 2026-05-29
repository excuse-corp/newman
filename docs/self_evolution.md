# Newman 自进化机制

本文档描述当前已落地的 Newman 自进化 MVP。实现入口主要在：

- [backend/evolution/service.py](/root/newman/backend/evolution/service.py)
- [backend/evolution/store.py](/root/newman/backend/evolution/store.py)
- [backend/api/routes/evolution.py](/root/newman/backend/api/routes/evolution.py)
- [frontend/src/pages/EvolutionPage.tsx](/root/newman/frontend/src/pages/EvolutionPage.tsx)

## 一、目标与边界

自进化采用全自动策略，不做事前审批。系统会自动总结 session 经验，更新 `MEMORY.md`，并按需要修改 Skill 目录。

自动允许：

- 更新 `backend_data/memory/MEMORY.md`
- 修改 `skills/**` 下的 Skill 目录
- 修改 `plugins/**` 下已加载 Skill 对应目录内的文件
- 修改 `SKILL.md`、脚本、`requirements.txt`、参考文档等 skill 内部文件

不自动允许：

- 修改权限配置
- 修改系统 prompt
- 修改 Newman 后端/前端代码
- 安装插件
- 新增高权限工具
- 放宽沙箱或审批策略

## 二、触发机制

当前只有两类自动触发：

```text
新 session 创建 -> 后台总结上一个非空 session
当前 session 每累计 20 个 user turn -> 后台做一次增量总结
```

说明：

- 20 turn 按 `role == "user"` 的消息数量计算，不按工具调用次数计算。
- `mock` provider 下不会调度自进化。
- 同一个 session 同时只允许一个 evolution run 在后台执行。
- 手动调试可调用 `POST /api/evolution/run`。

## 三、上下文提取

自进化不会把整个原始运行时状态直接交给 LLM，而是构造结构化上下文。

输入包含：

- `trigger`
- session 基本信息
- `message_range`
- 当前 user turn 总数
- checkpoint summary，如果存在
- 当前 `MEMORY.md`
- 当前 `USER.md`
- 最近 5 条 evolution run 摘要
- 当前可用 skill 列表
- session 消息窗口

消息窗口规则：

- `new_session_created`：默认从上一个 session 的开头读取，超过上限时保留最后 `max_context_messages` 条。
- `turn_interval`：读取上次 evolution 后的消息，并向前重叠 `overlap_user_turns` 个 user turn。
- tool 消息不会全量塞入大输出，只保留工具名、动作、成功状态、摘要、推荐下一步和截断后的内容预览。

后端不单独做“用户纠正关键词”识别。诸如“没完成后用户继续补充信息，最后完成”的情况，由 LLM 从连续上下文中自行判断。

## 四、LLM 两阶段流程

### 4.1 自进化分析

第一阶段使用 `EVOLUTION_ANALYSIS_PROMPT`，让 LLM 输出结构化计划：

```json
{
  "memory_updates": [
    {
      "text": "可写入 MEMORY.md 的一条经验。",
      "reason": "为什么这条经验值得沉淀。",
      "evidence_message_ids": ["..."]
    }
  ],
  "skill_update_requests": [
    {
      "skill_name": "frontend-debug",
      "skill_path": "skills/frontend-debug/SKILL.md",
      "reason": "为什么要更新这个 skill。",
      "desired_change": "希望 skill 吸收什么经验。"
    }
  ],
  "skip_reason": null
}
```

`memory_updates` 由后端去重后追加到 `MEMORY.md` 的自动区块。

### 4.2 Skill 编辑

第二阶段只在需要更新 skill 时执行。后端会读取对应 skill 目录内的文本文件，再使用 `SKILL_EDIT_PROMPT` 让 LLM 输出文件操作：

```json
{
  "change_summary": "补充构建验证流程和脚本。",
  "file_operations": [
    {
      "action": "update",
      "path": "SKILL.md",
      "content": "完整的新文件内容"
    },
    {
      "action": "create",
      "path": "scripts/check_build.py",
      "content": "完整的新脚本内容"
    }
  ],
  "validation_plan": [
    "parse SKILL.md",
    "py_compile Python scripts"
  ],
  "risk_notes": []
}
```

后端只接受 skill 根目录内的相对路径。绝对路径、`..`、重复路径和删除 `SKILL.md` 会被拒绝。

## 五、验证与回滚

每次文件修改前都会保存快照，并记录 unified diff。

Memory 验证：

- 自动区块存在时只替换自动区块
- 新经验去重
- 单次新增数量受配置限制

Skill 验证：

- 所有操作路径必须位于对应 skill 根目录内
- `SKILL.md` 必须存在
- `parse_skill_file()` 能解析 `SKILL.md`
- Python 脚本通过 `py_compile`
- JSON/YAML 文件能解析
- `reload_ecosystem()` 后 skill 能重新加载

如果 skill 验证失败，本次 skill 文件变更会自动回滚。前端 Evolution Log 也可以对已应用的 run 执行事后回滚。

## 六、数据目录

```text
backend_data/evolution/
  events.jsonl
  runs/
    {run_id}.json
  snapshots/
    {run_id}/
      {file_digest}.before
```

`runs/{run_id}.json` 记录：

- 触发类型
- 来源 session
- 状态
- 消息范围
- user turn 数
- 变更列表
- diff
- 快照路径
- 验证状态
- 错误信息

## 七、前端展示

前端新增 `Evolution Log` 页面，功能是审计和回滚，不做审批。

页面展示：

- 自动进化记录列表
- 触发来源
- 状态
- 变更文件
- diff
- 验证结果
- 错误信息
- 回滚按钮

## 八、配置项

默认配置位于 [backend/config/defaults.yaml](/root/newman/backend/config/defaults.yaml)：

```yaml
evolution:
  enabled: true
  turn_interval: 20
  overlap_user_turns: 6
  max_context_messages: 120
  max_tool_output_chars: 2000
  max_memory_updates_per_run: 8
  max_skill_updates_per_run: 3
  max_skill_file_bytes: 200000
  max_skill_total_bytes: 700000

paths:
  evolution_dir: "backend_data/evolution"
```

这些配置可通过 `newman.yaml` 或 `NEWMAN_` 环境变量覆盖。
