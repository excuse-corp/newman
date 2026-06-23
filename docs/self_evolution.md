# 自进化机制

这份文档描述 Newman 当前代码中的自进化实现，用于补齐 README 里的原有链接。

更细的流程图见 [newman_flow.md](newman_flow.md) 的“十一、自进化”，接口定义见 [Newman_API_v1.md](Newman_API_v1.md) 的“7.4 自进化接口”。

## 触发点

当前实现有三种触发方式：

1. `new_session_created`
   新建 session 时，后台异步总结“上一个非空 session”。
2. `turn_interval`
   当前 session 在 `SessionEnd` 后，如果用户消息数相对上次自进化累计达到 `20`，则做一次增量总结。
3. `manual`
   通过 `POST /api/evolution/run` 手动补跑。

注意：

- 新建 session 触发的是“上一个非空 session”，不是刚创建出来的新 session。
- `turn_interval` 当前按 `user_turn_count` 计数，不按总消息数或工具调用数计数。

## 分析输入

自进化分析阶段不会直接把原始 session 文件整包交给模型，而是先组装结构化上下文：

- `trigger`
- `session`
  - `session_id`
  - `title`
  - `created_at`
  - `updated_at`
  - 过滤后的 `metadata`
- `message_range`
- `user_turn_count`
- `checkpoint`
- `current_memory`
- `current_user_memory`
- `recent_evolution_runs`
  - 最近 5 次 run 的 `status`、`summary` 和变更摘要
- `skills`
  - 当前可用 skill 的元数据摘要
- `messages`
  - 本次参与分析的消息切片

消息裁剪规则：

- `new_session_created` 和 `manual` 默认从第 0 条消息开始分析。
- `turn_interval` 只看上次 evolution 之后的消息，并向前补少量 user turn 重叠上下文。
- 单次分析最多保留 `120` 条消息。
- 普通消息 `content` 最多保留 `8000` 字符。
- `tool` 消息会被结构化为 `tool`、`action`、`success`、`summary`、`recommended_next_step` 和 `content_preview`，其中预览默认最多 `2000` 字符。

## 模型允许输出的内容

分析模型只允许输出两类结果：

- `memory_updates`
- `skill_update_requests`

当前明确禁止自动建议或自动修改：

- 权限配置
- 系统 prompt
- 后端代码
- 前端代码
- 插件安装
- 工具权限
- 沙箱策略

## 自动修改范围

### MEMORY

当前自动经验沉淀目标是 `backend_data/memory/MEMORY.md`。

限制：

- 每次 run 最多 1 条 memory
- 单条 memory 最多 80 个字符
- 去重后才会真正写入

### Skill

如果分析阶段产出了 `skill_update_requests`，系统会读取目标 skill 目录中的文本文件，再调用 skill 编辑模型生成 `file_operations`。

允许修改的文件类型主要包括：

- `SKILL.md`
- `README.md`
- `requirements.txt`
- 目录内文本脚本和参考文档

不允许越过 skill 根目录写文件。

## 落盘、验证与回滚

自进化不通过普通工具调用落盘，而是由后端确定性执行：

1. 保存目标文件快照
2. 写入 memory 或 skill 文件
3. 对 skill 变更做校验
   - `SKILL.md` 解析
   - Python `py_compile`
   - JSON / YAML 解析
   - `reload_ecosystem()`
4. 校验失败时自动回滚
5. 把 run、diff、快照和错误写入 `backend_data/evolution/`

## 关键实现文件

- `backend/runtime/run_loop.py`
  - 调度触发
- `backend/evolution/service.py`
  - 上下文构造、模型分析、应用、验证、回滚
- `backend/evolution/prompts.py`
  - 分析 prompt 和 skill 编辑 prompt
- `backend/evolution/store.py`
  - run、事件、快照存储
- `backend/api/routes/evolution.py`
  - Evolution Log 与手动触发接口
