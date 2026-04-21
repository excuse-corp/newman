# Newman 每轮开始时的 Prompt / Context 组装说明

本文档说明当前 Newman 实现里，在“每一次真正向主模型发请求之前”，上下文到底会被塞哪些内容、分成几块、每块包含什么，以及在不同场景下会有什么差异。

这里说的“每轮开始”，不是只指用户发来一条新消息后的第一次模型请求，也包括：

- 同一回合里，模型发起工具调用后、拿到工具结果之后的下一次模型请求
- 工具失败后的收口请求
- 达到工具调用上限后的收口请求

也就是说，只要代码走到：

```python
response = await self._stream_provider_response(
    assembled,
    self.registry.tools_for_provider(task.permission_context),
    ...
)
```

这一刻，发给模型的上下文就是本文描述的这套结构。

## 1. 先说结论：不是一坨 JSON，而是两条并行输入通道

每次主模型请求，实际有两条输入通道：

1. `messages`
2. `tools`

其中：

- `messages` 是真正的聊天上下文
- `tools` 是函数工具 schema，不在聊天消息正文里，而是作为 provider 的独立参数传过去

所以“上下文被塞了什么”，要分开看：

- 一部分被塞进 `messages`
- 一部分被塞进 `tools`

## 2. 总体结构

主模型请求在运行时的大致形状如下：

```python
assembled = [
  system_block_0,                # guardrail + stable context
  optional_checkpoint_block,     # 有 checkpoint 且未 restore 时才有
  *session_history_blocks,       # 当前 session.messages 逐条映射后的消息
]

tools = registry.tools_for_provider(permission_context)
```

这里的 `tools` 不是固定全量集合，而是“当前 `permission_context` 允许暴露给模型的工具集合”。

如果当前 provider 是：

- `openai_compatible`：`assembled` 直接作为 `messages` 传入，`tools` 单独传入
- `anthropic_compatible`：所有 `role=system` 的消息会先合并成一个大的 `system` 字符串；非 `system` 消息进入 `messages`；`tools` 仍然单独传入

### 2.1 OpenAI-compatible 真实载荷形状

在 `openai_compatible` 下，大致会变成：

```json
{
  "model": "...",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "content": "...", "tool_call_id": "call_1"}
  ],
  "tools": [
    {"type": "function", "function": {...}}
  ],
  "max_tokens": 4096,
  "temperature": 0.2,
  "stream": true
}
```

也就是说：

- 多条 `system` message 会原样保留
- `messages` 和 `tools` 是两个独立字段

### 2.2 Anthropic-compatible 真实载荷形状

在 `anthropic_compatible` 下，大致会变成：

```json
{
  "model": "...",
  "system": "system_message_1\\n\\nsystem_message_2",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."},
    {"role": "tool", "content": "...", "tool_call_id": "call_1"}
  ],
  "tools": [
    {"type": "function", "function": {...}}
  ],
  "max_tokens": 4096,
  "temperature": 0.2,
  "stream": true
}
```

也就是说：

- 所有 `system` 块会先被拼成一个大的 `system` 字符串
- 非 `system` 的历史消息顺序不变
- `tools` 依然是单独字段

## 3. 第一大块：System Block 0

这是每次请求一定会出现的第一条 `system` message。它的内容不是单一文件，而是两层内容拼在一起：

1. Commentary guardrail
2. Stable Context

代码上是：

```python
messages = [{
  "role": "system",
  "content": f"{COMMENTARY_SYSTEM_GUARDRAIL}\\n\\n{stable_context}"
}]
```

### 3.1 Commentary guardrail

这是一段固定的英文规则，作用是强制模型在“本轮如果要调用工具或技能”时，先输出一条简短的 `<commentary>...</commentary>`。

当前内容是：

```text
CRITICAL TOOL/SKILL RULE:
If you will call any tool or use any skill in this turn, you must output exactly one short <commentary>...</commentary> message immediately before the first tool or skill action.
Do not skip it. Use the user's language. Do not put final-answer content inside <commentary>.
```

这段 guardrail 会被直接放在 system prompt 最前面。

### 3.2 Stable Context

`stable_context` 由下面 4 段内容按顺序拼起来，中间用两个换行分隔：

1. `backend_data/memory/Newman.md`
2. `backend_data/memory/USER.md`
3. `backend_data/memory/SKILLS_SNAPSHOT.md`
4. `## Tooling Overview\n{tools_overview}`

拼接逻辑等价于：

```text
{Newman.md}

{USER.md}

{SKILLS_SNAPSHOT.md}

## Tooling Overview
{tools_overview}
```

### 3.3 这 4 段现在分别是什么

#### 3.3.1 `Newman.md`

这里注入的是整个 [backend_data/memory/Newman.md](/root/newman/backend_data/memory/Newman.md) 文件全文，不是摘要。

它当前包含的主要章节是：

- 角色定位
- 核心工作原则
- 工具使用规则
- 技能使用规则
- 记忆使用规则
- 输出风格
- 绝对禁止
- 最终目标

也就是说，模型每次开局都会重新看到这些平台级规则。

#### 3.3.2 `USER.md`

这里注入的是整个 [backend_data/memory/USER.md](/root/newman/backend_data/memory/USER.md) 文件全文。

当前实际内容很短：

```md
# USER.md

<!-- BEGIN AUTO USER MEMORY -->
## User Memory
仅记录跨 session 稳定成立的用户偏好、沟通方式和长期协作约定，不记录一次性任务或项目事实。

- 暂无条目
<!-- END AUTO USER MEMORY -->
```

#### 3.3.3 `SKILLS_SNAPSHOT.md`

这里注入的是整个 [backend_data/memory/SKILLS_SNAPSHOT.md](/root/newman/backend_data/memory/SKILLS_SNAPSHOT.md) 文件全文。

当前实际快照里有 1 个技能：

```md
## Skills
A skill is a set of local instructions stored in a `SKILL.md` file. Below is the list of skills available in this session.
### Available skills
- skill-creator: Create or update Newman skills in the workspace using the current skill conventions. (file: /root/newman/skills/skill-creator/SKILL.md) | when_to_use: Use when the user wants to create, revise, package, or standardize a skill.
### How to use skills
- Trigger rules: if the user names a skill, or the task clearly matches a skill description, you must use that skill for this turn.
- Progressive disclosure: do not preload skill bodies. First decide which single skill is most relevant, then read its `SKILL.md` with `read_file`.
- If the skill references sibling files such as `references/`, `templates/`, or `scripts/`, inspect only the files needed for the current task.
- Prefer using existing tools (`read_file`, `read_file_range`, `list_dir`, `search_files`, `write_file`, `edit_file`, `update_plan`, `terminal`) exactly as the skill instructs.
- Do not read multiple skills up front unless the user explicitly asks for a comparison.
```

#### 3.3.4 `Tooling Overview`

这是一个纯文本工具总览，不是工具 schema 本体。作用是让模型在 system prompt 里知道“有哪些工具、它们大致做什么”。

当前运行时生成的内容是：

```text
- edit_file: Edit a text file by applying exact string replacements.
- fetch_url: Fetch a URL over HTTP(S).
- list_dir: List files and directories inside the workspace.
- read_file: Read a small workspace file and return the entire contents as base64 in dataBase64. Use this only when you need the exact complete file bytes.
- read_file_range: Read up to limit lines from a UTF-8 text file starting at offset (1-based line number). Use this for large text files or partial reads.
- search_files: Search file contents in the workspace and return matching lines.
- search_knowledge_base: Search imported knowledge documents and return the most relevant snippets.
- terminal: Execute a shell command inside the native sandbox.
- update_plan: Create or update the current multi-step plan for this session. Use it for complex tasks, and keep at most one step in_progress.
- write_file: Create or overwrite a text file inside the workspace.
```

这里的 alias 工具（如 `list_files`、`grep`）不会再进入 overview；overview 只展示主工具名，避免重复占用 token。

如果未来 MCP resource 有描述，还会额外拼一段：

```text
## MCP Resources
...
```

当前实例里没有这段。

## 4. 第二大块：可选 Checkpoint Summary Block

如果当前 session 存在 checkpoint，并且 `session.messages` 里还没有 `checkpoint_restore` 类型的 system message，那么会额外插入第二条 `system` message：

```text
## Checkpoint Summary
{checkpoint.summary}
```

注意两点：

1. 这是主对话请求里的摘要注入方式
2. 它不是整段历史 JSON，而是一份已经生成好的摘要文本

### 4.1 什么时候不会插这块

如果你手动调用过 `restore-checkpoint`，session 里会出现一条：

```text
## Restored From Checkpoint
{checkpoint.summary}
```

这时 `PromptAssembler` 会发现 `checkpoint_restore` 已存在，就不再重复补上 `## Checkpoint Summary`，避免同一份摘要被注入两次。

## 5. 第三大块：Session History Blocks

这是最容易误解的一块。

主模型看到的“历史聊天记录”不是一个整块 JSON，而是把 `session.messages` 当前保留下来的每一条消息，按顺序逐条映射成 chat message。

### 5.1 它保留什么

保留的是“当前 session 里仍然存在的消息”，包括但不限于：

- `user`
- `assistant`
- `tool`
- `system`

如果 session 曾经被压缩过，那么较老历史已经不在 `session.messages` 里了，只剩：

- checkpoint summary
- 最近保留的原始消息
- 压缩后新增的消息

### 5.2 它不保留什么

主对话 prompt 并不会把每条消息的全部字段都注入进去。像这些字段通常不会进入主模型上下文：

- `id`
- `created_at`
- 大多数 `metadata`
- `request_id`
- `turn_id`
- 附件列表结构

真正进入主模型的只有以下几类：

#### 普通 `user` / `assistant` / `system`

直接变成：

```json
{"role": "...", "content": "..."}
```

#### `assistant` 且带 `metadata.tool_calls`

会额外保留工具调用协议字段：

```json
{
  "role": "assistant",
  "content": "...",
  "tool_calls": [
    {
      "id": "call_xxx",
      "type": "function",
      "function": {
        "name": "read_file",
        "arguments": "{\"path\":\"/root/newman/README.md\"}"
      }
    }
  ]
}
```

注意：

- 这里会保留 `content`
- 同时也会保留 `tool_calls`
- `arguments` 会被重新序列化成 JSON 字符串

#### `tool`

会变成：

```json
{
  "role": "tool",
  "content": "...",
  "tool_call_id": "call_xxx"
}
```

这能让模型在下一次请求里把“哪个工具调用”与“哪个工具结果”对上号。

## 6. 第四大块：Tools Schema（独立于 messages）

除了 `assembled messages` 之外，运行时还会把工具 schema 单独作为 `tools` 参数传给 provider。

这块不是 system prompt 文本，而是结构化 JSON schema。

每个工具形状类似：

```json
{
  "type": "function",
  "function": {
    "name": "read_file",
    "description": "Read a small workspace file and return the entire contents as base64 in dataBase64. Use this only when you need the exact complete file bytes.",
    "parameters": {
      "type": "object",
      "properties": {
        "...": "..."
      }
    }
  }
}
```

这里有两个关键点：

1. `Tooling Overview` 是给模型看的纯文本说明，展示的是主工具摘要
2. `tools` 才是 provider 真正用来发起 function call 的结构化接口定义，而且当前实现会按本轮任务做分组筛选，不一定把所有工具 schema 都发进去

两者都会同时存在。

## 7. 一次正常用户回合里，组装发生在什么时候

### 7.1 用户消息先入 session

用户请求一进来，先被写成一条 `SessionMessage(role="user")` 放进 session。

如果有图片上传，还会先做图片分析，然后把分析摘要拼进用户消息正文。

例如原始用户输入：

```text
帮我看下这张图
```

如果上传了 `error.png`，分析结果是“终端截图显示 PostgreSQL 连接失败”，那么真正进 session 的用户消息正文会变成：

```md
帮我看下这张图

## Uploaded Images
- error.png: 终端截图显示 PostgreSQL 连接失败
```

注意：

- 图片摘要会进入 `content`
- 附件文件路径、content_type 等更多细节只在 metadata 里，不会直接进入主模型 prompt

### 7.2 然后先做一次 `_maybe_checkpoint()`

在本轮第一次主模型请求发出之前，运行时会先检查是否需要上下文压缩。

如果需要压缩，会发生两件事：

1. 旧消息被裁剪，`session.messages` 只保留最近 4 条
2. 生成或刷新 `checkpoint.summary`

所以本轮第一次真正送给模型的 prompt，看到的已经是“压缩后的 session 视图”。

### 7.3 然后才组装第一次 `assembled`

也就是：

- System Block 0
- 可选 Checkpoint Summary
- 当前 `session.messages`
- 独立的 `tools`

## 8. 同一回合里，工具调用后会再怎么组装

如果模型这次没有直接给最终回答，而是先发起工具调用，那么 session 会继续追加两类消息：

1. 一条 `assistant` 消息
2. 一条或多条 `tool` 消息

之后下一次主模型请求会重新从头组装整套上下文，而不是只发增量。

### 8.1 assistant 工具调用消息长什么样

这条消息的 `content` 来自：

- `commentary`
- 以及可能存在的 `response.content`

两者拼接规则是：

```text
{commentary}

{content}
```

如果只有 `commentary`，那就只保存 `commentary`。

同时这条消息还会在 metadata 里记录 `tool_calls`。下一次组装 prompt 时，`tool_calls` 会重新被恢复成 provider 需要的协议字段。

### 8.2 tool 结果消息长什么样

每个工具执行完之后，session 会追加一条：

```json
{
  "role": "tool",
  "content": "persisted_output if provided, otherwise result.stdout or result.summary",
  "metadata": {
    "tool_call_id": "...",
    "tool": "...",
    "success": true/false,
    ...
  }
}
```

对于 `read_file` / `read_file_range` 这类容易膨胀上下文的工具，当前实现会把 session 中的 `content` 收缩成摘要 JSON，而不是把完整 base64 或全文长期持久化。

但下一次真正进入主模型上下文时，只有：

```json
{
  "role": "tool",
  "content": "...",
  "tool_call_id": "..."
}
```

会被保留下来。

如果当前 turn 还没有结束，运行时还可以用一份临时 override 把这条 `tool` message 替换回完整输出，让同一轮后续推理继续使用真实内容；等 turn 结束后，长期保留的仍然是 session 里的摘要版。

## 9. 特殊收口请求还会额外塞 system 消息

并不是所有主模型请求都只是“system + checkpoint + history”。

有两个特殊分支会在请求前额外往 `session.messages` 里插一条新的 `system` 消息，因此下一次 assembled 里会多出一块。

### 9.1 工具达到上限时

会先插入一条 `system`：

```text
你已达到当前回合的工具调用上限（N 次）。禁止继续调用任何工具。请仅基于现有上下文、已有工具结果和 checkpoint 摘要，给出一个阶段性结论，并明确告诉用户：如果要继续深入处理，请直接输入“继续”。
```

然后再发一次主模型请求，并且这一次 `tools=[]`，不再暴露工具。

### 9.2 工具 fatal error 时

会先插入一条 `system`：

```text
刚才的工具调用已经确认失败。禁止继续调用任何工具，也不要重复同一个失败动作。如果不依赖该工具，你仍然可以基于现有上下文直接回答用户原问题，请直接给出最终回答。如果无法可靠回答，就明确说明阻塞原因、失败工具、关键报错，以及建议用户下一步怎么做。不要假装工具成功。
```

然后再发一次主模型请求，并且同样 `tools=[]`。

## 10. 例子 1：普通文本对话，未压缩，无工具

假设当前 session 里已经有：

```text
user: 这个项目是做什么的？
assistant: 这是一个本地 AI Agent 运行时。
```

用户又发来：

```text
那它怎么做上下文压缩？
```

那么第一次主模型请求的大致结构就是：

```json
messages = [
  {
    "role": "system",
    "content": "COMMENTARY_SYSTEM_GUARDRAIL + Stable Context"
  },
  {
    "role": "user",
    "content": "这个项目是做什么的？"
  },
  {
    "role": "assistant",
    "content": "这是一个本地 AI Agent 运行时。"
  },
  {
    "role": "user",
    "content": "那它怎么做上下文压缩？"
  }
]

tools = [
  {"type": "function", "function": {...}},
  {"type": "function", "function": {...}}
]
```

此时没有：

- checkpoint block
- tool_call 协议消息
- tool 结果消息

## 11. 例子 2：有 checkpoint 的普通请求

假设 session 之前已经压缩过，当前存在：

- `checkpoint.summary = "## Current Progress ..."`
- 当前 session 中最新保留的 4 条消息

那么主模型看到的大致结构会是：

```json
messages = [
  {
    "role": "system",
    "content": "COMMENTARY_SYSTEM_GUARDRAIL + Stable Context"
  },
  {
    "role": "system",
    "content": "## Checkpoint Summary\n## Current Progress ..."
  },
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  {"role": "user", "content": "..."}
]
```

这里不会把旧历史原文重新塞回来，只会塞：

- checkpoint 摘要
- 当前仍保留在 `session.messages` 中的原始消息

## 12. 例子 3：工具调用后的下一次请求

假设模型先输出了一句 commentary，然后调用：

- `read_file(path=/root/newman/README.md)`

并且工具返回：

- `{"dataBase64":"IyBOZXdtYW4KLi4u"}`
- 同时 session 持久化层只保存一条摘要版 tool message，例如 `{"summary":"Read complete file README.md; raw content omitted from persisted history", ...}`

那么下一次主模型请求时，相关 history 会长这样：

```json
messages = [
  {
    "role": "system",
    "content": "COMMENTARY_SYSTEM_GUARDRAIL + Stable Context"
  },
  {
    "role": "user",
    "content": "帮我看 README 里这个项目的定位"
  },
  {
    "role": "assistant",
    "content": "我先读取 README。",
    "tool_calls": [
      {
        "id": "call_1",
        "type": "function",
        "function": {
          "name": "read_file",
          "arguments": "{\"path\": \"/root/newman/README.md\"}"
        }
      }
    ]
  },
  {
    "role": "tool",
    "content": "{\"dataBase64\":\"IyBOZXdtYW4KLi4u\"}",
    "tool_call_id": "call_1"
  }
]
```

也就是说，在同一 turn 的下一次请求里，工具协议链条仍会使用完整工具输出；只是 turn 结束后，长期保留在 session 里的会是摘要版，而不是整段 base64。

## 13. 例子 4：restore-checkpoint 之后

如果用户手动执行了 `restore-checkpoint`，session 里会被插入一条：

```json
{
  "role": "system",
  "content": "## Restored From Checkpoint\n{checkpoint.summary}"
}
```

此时下一次主模型请求会是：

```json
messages = [
  {
    "role": "system",
    "content": "COMMENTARY_SYSTEM_GUARDRAIL + Stable Context"
  },
  {
    "role": "system",
    "content": "## Restored From Checkpoint\n..."
  },
  ...
]
```

而不会再额外多出一条：

```text
## Checkpoint Summary
...
```

## 14. 例子 5：工具 fatal error 后的收口请求

假设刚才 `search_knowledge_base` 已确定失败，那么收口请求前，session 里会先多一条 `system`：

```text
刚才的工具调用已经确认失败。禁止继续调用任何工具，也不要重复同一个失败动作。...
```

然后新的 assembled 大致会变成：

```json
messages = [
  {
    "role": "system",
    "content": "COMMENTARY_SYSTEM_GUARDRAIL + Stable Context"
  },
  {"role": "user", "content": "..."},
  {
    "role": "assistant",
    "content": "我先去知识库里查一下。",
    "tool_calls": [...]
  },
  {
    "role": "tool",
    "content": "知识库查询失败",
    "tool_call_id": "call_1"
  },
  {
    "role": "system",
    "content": "刚才的工具调用已经确认失败。禁止继续调用任何工具..."
  }
]

tools = []
```

这里最关键的是：

- 不是只改 system prompt
- 而是把这条收口约束作为一条新的 `system` 历史消息加入 session
- 同时这次请求不再暴露任何工具 schema

## 15. 一个很重要的边界：哪些东西不会进主模型上下文

下面这些信息虽然在系统里存在，但通常不会原样进主模型 prompt：

- `session.metadata`
- `checkpoint.metadata`
- 大部分 `message.metadata`
- `message.id`
- `message.created_at`
- 图片附件的本地路径
- SSE event 流
- usage 账本
- 历史消息压缩时使用的 JSON payload

这些内容有的只用于：

- 前端展示
- 审计
- 压缩摘要请求
- 调试
- 路由层

主对话 prompt 不会自动把它们全塞进去。

## 16. 最后用一句话概括

当前 Newman 的主模型上下文组装，不是“把整个会话 JSON 都喂给模型”，而是：

1. 先塞 1 条大的 system message：`commentary guardrail + stable context`
2. 再按需塞 1 条 checkpoint system message
3. 再把当前 `session.messages` 逐条转成 chat messages
4. 同时把可见工具以独立 `tools schema` 传给 provider

如果本轮已经发生工具调用、压缩、checkpoint restore、fatal error 或工具上限收口，这些变化会先写回 session，再参与下一次 prompt 组装。

## 17. 相关源码

- [backend/runtime/prompt_assembler.py](/root/newman/backend/runtime/prompt_assembler.py)
- [backend/memory/stable_context.py](/root/newman/backend/memory/stable_context.py)
- [backend/runtime/run_loop.py](/root/newman/backend/runtime/run_loop.py)
- [backend/api/routes/messages.py](/root/newman/backend/api/routes/messages.py)
- [backend/api/routes/sessions.py](/root/newman/backend/api/routes/sessions.py)
- [backend/providers/openai_compatible.py](/root/newman/backend/providers/openai_compatible.py)
- [backend/providers/anthropic_compatible.py](/root/newman/backend/providers/anthropic_compatible.py)
- [backend_data/memory/Newman.md](/root/newman/backend_data/memory/Newman.md)
- [backend_data/memory/USER.md](/root/newman/backend_data/memory/USER.md)
- [backend_data/memory/SKILLS_SNAPSHOT.md](/root/newman/backend_data/memory/SKILLS_SNAPSHOT.md)
