# Newman Frontend PRD v2.0

2026 · 内部文档

### 版本变更记录

| 版本 | 日期 | 变更摘要 |
| --- | --- | --- |
| v1.0 | 2026-04 | 初始版本 |
| v2.0 | 2026-04-12 | 1) Timeline 从单层改为双层结构（主层 + 次层）；2) 明确 Turn 的三段渲染结构（用户消息 → Timeline → Answer Slot）；3) 补充系统工具清单（read_file / list_dir / list_files / search_files / grep / fetch_url / terminal / write_file / edit_file / update_plan / search_knowledge_base）；4) 新增终端工具（terminal）的深色终端样式展示规范；5) 次层按工具类型区分展示样式（终端 / 文件 / 检索 / 网络 / 计划 / 通用）；6) Thinking 阶段增加动态 icon → 意图文案的过渡交互；7) 工具语义映射字典增加次层展示类型列；8) 8.2 Trace 卡片视觉规范拆分为主层 / 次层通用 / 次层终端三部分 |

---

## 一、文档目标

本文档定义 Newman Web 前端的产品目标、信息架构、交互模型、视觉语言、状态模型与交付范围，用于指导前端设计与实现。

本 PRD 的定位不是“聊天页面说明”，而是“Agent 工作台前端规范”。

前端必须承载 Newman 的三个核心产品特性：

- 本地优先
- 过程透明
- 可治理、可恢复、可追踪

---

## 二、产品定位

### 2.1 前端定位

Newman 前端是一个面向单用户、本地优先的 Agent 工作台，而不是通用聊天网页。

它的核心价值不是“把回答展示出来”，而是让用户在一次任务中同时看见：

- 当前会话和上下文
- Agent 的中间过程
- 工具调用与状态变化
- 审批动作与风险提示
- 证据、引用与来源
- 会话记忆和后续可追问入口

### 2.2 设计关键词

前端设计语言应固定为：

- 纸感工作台
- 米白底色
- 低噪音边框
- 三栏结构
- 结果与过程并列
- 右侧抽屉
- 轻量、克制、可信


## 三、设计原则

### 3.1 透明优先

用户必须能看见系统在做什么，而不是只看见最终答案。

前端需要可视化以下过程：

- thinking / planning
- tool call
- skill usage
- agent collaboration
- citation / source lookup
- error recovery
- approval pending / approved / rejected

### 3.2 主区人话优先

主对话区默认展示“用户能理解的执行进展”，而不是直接铺出内部事件名。

- 主句优先表达“我正在做什么 / 下一步要做什么 / 当前卡在哪”
- 不直接把 `tool_call_started`、`skill call`、`agent handoff` 这类原始类型作为主文案
- 工具名、Skill 名、Agent 名、耗时、状态等技术信息降级为次级信息
- 原始输入输出、参数、错误细节、引用证据进入右侧 Drawer
- 前端不得为了生成主区文案再调用 LLM，总结必须来自确定性映射逻辑

### 3.3 默认克制

界面不追求“炫”，要追求：

- 信息清晰
- 风险提示准确
- 主次分明
- 可持续长时间使用

### 3.4 证据始终可达

所有重要结论都必须尽量能展开查看依据，特别是：

- RAG 引用
- 工具输入输出
- Skill 来源
- 错误摘要

### 3.5 任务连续性优先

用户中途离开、刷新页面、恢复会话后，前端要尽量恢复：

- 会话列表状态
- 当前会话
- 抽屉打开状态
- 正在审批的请求
- 正在流式返回的最后状态

### 3.6 本地优先体验

前端不应过度依赖云端概念，不使用需要平台账号才能成立的交互模型。

---

## 四、目标用户

### 4.1 核心用户

- 在本地环境中使用 AI 辅助完成复杂任务的工作者，aka，牛马
- 需要查看中间过程和证据来源的重度用户
- 需要 AI 帮助运行命令、读写文件、分析资料的研发或数据用户

### 4.2 用户诉求

- 不仅要答案，还要过程
- 不仅要过程，还要可控
- 不仅要可控，还要不打断工作流
- UI要有一致性，好看
---

## 五、前端能力边界

### 5.1 前端负责

- 会话浏览与切换
- 对话输入与展示
- SSE 消费与状态同步
- 工具过程可视化
- Tool Approval 交互
- RAG 引用与证据展示
- 会话恢复和压缩操作入口
- 插件管理入口
- Memory / Skills / Files 工作区页面

### 5.2 前端不负责

- Agent 推理
- Prompt 拼接
- Tool 执行
- 权限策略判定
- 记忆抽取与压缩逻辑本身

这些能力由后端提供，前端只做：

- 可视化
- 控制入口
- 状态反馈

---

## 六、信息架构

### 6.1 一级导航

基于当前原型，一级导航固定为左侧工作区导航：

- `Chat`
- `Memory`
- `Skills`
- `Files`


### 6.2 页面层级

```text
App Shell
├── Chat Workspace
│   ├── Session List
│   ├── Conversation Stage
│   ├── Composer
│   └── Evidence Drawer
├── Memory Workspace
├── Skills Workspace
├── Files Workspace
└── Settings / Plugins
```

### 6.3 Chat Workspace 信息架构

```text
左栏：会话与导航
中栏：主对话和执行轨迹
右栏：详情抽屉 / 引用 / Tool IO / Trace
底部：输入与上下文状态
```

---

## 七、核心页面与模块

## 7.1 App Shell

### 目标

承载整个产品的基础布局与导航框架。

### 组成

- 左侧 Rail Navigation
- 中间主工作区
- 可伸缩右侧 Drawer
- 全局弹层层级

- 左栏和主区都采用米白纸感背景
- 左右栏可拖拽调宽
- 移动端时自动退化为单栏

---

## 7.2 Chat Workspace

### 目标

作为 Newman 的主入口，支持用户输入、观察中间过程、查看最终结果和证据。

### 组成

- Empty State
- Conversation Pane
- Turn Containers（每个 turn 严格由三部分组成，详见下方）
- Per-turn Trace Timeline（双层结构：主层 + 次层）
- Single Answer Slot
- Composer Bar
- Context Usage Indicator
- Evidence Drawer

### Turn 的三段渲染结构

聊天页面中，每一个 turn 在主区的展示严格分为以下三部分，自上而下排列：

1. **用户消息**：右侧气泡，展示用户本次输入
2. **本轮 Timeline**：左侧区域，展示本轮 Agent 的中间执行过程（双层结构，见 7.4 节详述）
3. **本轮唯一 Answer Slot**：左侧区域，展示 Agent 最终回答

其中 Timeline 是整个 turn 可视化的核心，它采用**双层结构**：

- **主层（Primary Layer）**：展示 Agent“准备干什么”的人话摘要，简明扼要，一句话说清意图
- **次层（Secondary Layer）**：展示工具 / Skill 的具体调用过程，包含工具名、参数摘要、执行状态、耗时等技术细节

主层和次层的关系是：主层是面向用户的叙事，次层是面向过程的证据。用户默认看到主层，次层作为可展开的详情附属于主层节点之下。

### 关键要求

- 空态要强调“开始一个任务”，不是“开始聊天”，也要考虑到会话列表为空的时候的样式
- 中间态要优先展示执行轨迹
- 主区默认展示“我正在做什么”的进展文案，而不是底层事件类型
- 最终答案要保留继续追问的上下文，如果有的话
- Composer Bar 内需要提供“本轮审批策略”选择，允许用户在发送前切换：
- `全部默认通过`
- `逐个确认 Level 2`
- 该选择不是全局设置，只作用于用户接下来发送的这一条消息
- 用户点击发送后，前端必须把当时的选择快照随本轮消息一起提交；本轮执行过程中即使用户再切换 UI，也不得影响已发出的这一轮

---

## 7.3 Session List

### 目标

帮助用户管理和恢复不同任务会话。

### 功能

- 新建会话
- 查看历史会话
- 切换会话
- 删除会话
- 展示当前活跃会话
- 重命名

### 交互要求

- 切换会话后，中心区与右侧 Drawer 数据同步刷新
- 会话标题优先使用 AI 自动摘要标题，允许用户手动重命名

---

## 7.4 Trace Timeline（双层结构）

### 目标

展示 Agent 中间执行过程，采用主层 + 次层的双层结构，让用户既能快速理解 Agent 在做什么，又能按需深入查看工具调用细节。

### Turn 容器规则

- 主区的一级渲染单位必须是 `turn`，而不是“平铺的消息列表 + 平铺的事件列表”
- 一个 `turn` 至少包含以下三层承载：
- 用户消息
- 本轮 Trace Timeline（双层结构）
- 本轮唯一的回答槽位
- `assistant_delta` 只能更新当前 turn 的回答槽位，不得额外生成第二个 assistant 气泡
- `final_response` 只能把同一个回答槽位切到“已完成 / 待归档”状态，不得再创建第二个最终回答卡片
- 会话详情接口返回的持久化 `assistant` 消息，只能接管同一个回答槽位，不得与流式回答并列显示
- 任意时刻，同一 turn 在主区只允许看到一个 assistant 回答窗口

### 双层结构定义

Timeline 内部采用**主层 + 次层**的嵌套结构：

#### 主层（Primary Layer）

- **定位**：面向用户的叙事层，展示 Agent“准备干什么 / 正在干什么”
- **内容要求**：一句简明的人话，不宜过长，捡重点说。例如“我先看一下相关文件”、“正在运行构建检查”
- **交互**：
  - 主层节点按时间顺序自上而下排列
  - Thinking 阶段：显示一个动态 thinking icon（如脉动圆点或旋转指示器），thinking 结束后该动态 icon 消失，替换为 Agent 的意图摘要文案
  - 每个主层节点下方可展开次层
  - 主层节点可点击，点击后右侧 Drawer 展示该节点详情

#### 次层（Secondary Layer）

- **定位**：面向过程的证据层，展示工具 / Skill 的具体调用过程
- **内容要求**：展示工具名、调用参数摘要、执行状态（运行中 / 成功 / 失败）、耗时等技术细节
- **展开方式**：默认折叠，用户点击主层节点可展开查看次层；当工具正在执行时次层自动展开
- **视觉层级**：次层在主层下方缩进展示，与主层形成父子关系，视觉上明确从属

### 次层的工具调用展示规范

不同类型的工具在次层中有不同的展示方式：

#### 终端工具（`terminal`）展示规范

终端工具的次层展示需要参考 Claude Code 的终端调用样式，具体要求：

1. **Shell 标识区**：次层顶部显示 `Shell` 标签，表明这是一个终端命令调用
2. **命令行展示**：以 `$` 前缀展示实际执行的命令，例如 `$ npm run build`，使用等宽字体
3. **输出区域**：命令下方展示终端输出内容，保留原始格式（等宽字体、保留换行和缩进）
4. **状态指示**：
   - 运行中：显示动态加载指示器
   - 成功：右下角显示 `✓ 成功` 标记（绿色）
   - 失败：右下角显示 `✗ 失败` 标记（红色），并展示错误输出
5. **折叠行为**：
   - 命令行始终可见
   - 输出内容超过一定行数（建议 10 行）时默认折叠，显示“已运行命令 ⌄”的可展开提示
   - 用户可点击展开查看完整输出
6. **视觉样式**：
   - 背景色采用深色（如 `#1e1e1e` 或 `#2d2d2d`），与主区暖白形成对比，模拟终端感
   - 文字使用等宽字体，颜色为浅色（如 `#d4d4d4`）
   - 圆角卡片包裹，与主区纸感风格协调

#### 文件操作工具（`read_file` / `write_file` / `edit_file`）展示规范

1. **文件路径展示**：显示被操作的文件路径（缩短为文件名 + 父目录）
2. **操作类型标签**：`查看` / `写入` / `编辑`
3. **状态**：运行中 / 已完成 / 失败
4. **edit_file 特殊处理**：可展示“已编辑 1 个文件”的摘要，点击可在 Drawer 中查看 diff

#### 检索类工具（`search_files` / `grep` / `list_dir` / `list_files` / `search_knowledge_base`）展示规范

1. **查询/路径展示**：显示检索关键词或目标路径
2. **结果数量**：完成后展示匹配数量
3. **状态**：运行中 / 已完成 / 失败

#### 网络工具（`fetch_url`）展示规范

1. **URL 展示**：显示目标 URL（可截断为域名）
2. **状态**：运行中 / 已完成 / 失败

#### 计划工具（`update_plan`）展示规范

1. **计划摘要**：展示更新后的计划步骤概要
2. **状态**：已更新

#### 通用 fallback 展示

对于未单独定义展示规范的工具：

1. **工具名**：显示工具名称
2. **参数摘要**：展示关键参数的简短摘要
3. **状态**：运行中 / 已完成 / 失败 / 重试中

### 双层交互流程示例

以用户问“今天天气如何”为例：

```
[用户气泡] 今天天气如何

[Timeline 主层] 🔄 thinking...        ← 动态 thinking icon
                ↓ thinking 结束
[Timeline 主层] 我先查一下天气信息      ← thinking icon 消失，显示意图文案
  [Timeline 次层]                     ← 自动展开
    ┌─────────────────────────────┐
    │ 🔧 fetch_url               │
    │ 目标：weather.example.com   │
    │ 状态：✓ 已完成  耗时 1.2s    │
    └─────────────────────────────┘

[Answer Slot] 今天洛杉矶天气晴朗...    ← Agent 最终回答
```

以用户要求“帮我跑一下构建”为例：

```
[用户气泡] 帮我跑一下构建

[Timeline 主层] 🔄 thinking...
                ↓
[Timeline 主层] 我先查看一下项目结构
  [Timeline 次层]
    ┌─────────────────────────────┐
    │ 📂 list_dir                 │
    │ 路径：/root/newman/frontend │
    │ 状态：✓ 已完成               │
    └─────────────────────────────┘

[Timeline 主层] 正在运行构建命令
  [Timeline 次层]                   ← 终端工具使用深色终端样式
    ┌─ Shell ─────────────────────┐
    │ $ npm run build             │
    │                             │
    │ > fileman-frontend@0.0.1    │
    │ > node ./node_modules/...   │
    │                             │
    │ vite v5.4.21 building...    │
    │ ✓ 34 modules transformed.   │
    │                    ✓ 成功    │
    └─────────────────────────────┘

[Timeline 主层] 构建通过，我再确认一下结果
  [Timeline 次层]
    ┌─────────────────────────────┐
    │ 📄 read_file                │
    │ 文件：dist/index.html       │
    │ 状态：✓ 已完成               │
    └─────────────────────────────┘

[Answer Slot] 构建已成功完成...
```

### 展示对象

- thinking
- plan
- tool call（`read_file` / `list_dir` / `list_files` / `search_files` / `grep` / `fetch_url` / `terminal` / `write_file` / `edit_file` / `update_plan` / `search_knowledge_base`）
- skill call
- agent handoff / 协同
- tool result
- tool error feedback

以上是过程数据模型中的 canonical 类型，不等于主对话区必须原样显示这些技术名词。

### 前端要求

- 每个主层节点都应可点击
- 点击后右侧 Drawer 展示该节点详情（包含完整的次层信息）
- 不同类型节点要有一致但可区分的视觉样式
- 主层节点主文案必须是用户可理解的进展描述
- `tool / skill / agent / raw event` 只能作为次层标签、状态或 Drawer 内容
- 次层中终端工具必须使用深色终端样式，其他工具使用与主区协调的浅色卡片样式

### 呈现分层

- 主层：一句用户可理解的执行进展，例如“正在查看相关文件”
- 次层：展示工具调用的具体过程和技术元信息，例如工具名、参数、Shell 命令及输出、耗时、状态、结果数量
- 详情层：在右侧 Drawer 中展示原始输入输出、引用、错误细节和结构化字段

### 节点更新规则

- 同一个 `tool_call_id` 的 `started / finished / retry / error` 优先更新同一节点（包括主层和次层），不在主区连续堆叠多条日志
- 同一个审批请求的 `request / resolved` 优先更新同一节点
- 只有用户视角上“发生了新的阶段变化”时，才新增主层节点
- 没有足够结构化字段时允许退化为通用文案，但不允许伪造推理内容
- 次层节点跟随其所属的主层节点一起更新状态

---

## 7.5 Evidence Drawer

### 目标

作为“过程详情 + 工具输入输出 + 引用证据”的统一承载容器。

### Tabs

- `Trace`
- `Tool IO`
- `引用`

P1 可增加：

- `Raw Event`
- `Prompt Context`

### 当前原型特征

- 右侧抽屉滑入，要有动效
- 点击抽屉中的关闭按钮或者点击非抽屉的页面中的其他地方，抽屉收回去
- 支持拖拽宽度，拖拉线的样式和左侧导航栏的拖拉线样式一样
- 与主会话并列存在，不打断阅读

### 产品要求

- Trace tab：解释当前节点做了什么
- Tool IO tab：展示参数、输出、耗时、状态
- 引用 tab：展示来源文档、网页、技能或 agent 来源

---

## 7.6 Approval Modal

### 目标

承载 Level 2 工具审批交互，并与底部输入区的“本轮审批策略”联动。

### 触发条件

收到 SSE 事件 `tool_approval_request`

补充说明：

- 若用户在本轮发送前选择了 `全部默认通过`，则本轮命中的 Level 2 工具默认放行，不弹出 Approval Modal
- 若用户在本轮发送前选择了 `逐个确认 Level 2`，则本轮每一个命中的 Level 2 工具都要进入 Approval Modal
- Level 1 黑名单拒绝不受该选择影响，仍由后端直接拒绝

### 展示内容

- 工具名
- 操作对象
- 风险说明
- 影响范围
- 倒计时
- `允许` / `拒绝`
- 若本轮审批策略为 `逐个确认 Level 2`，Modal 内应显示当前轮次策略提示，避免用户误以为是全局设置

### 交互要求

- 倒计时以 SSE `tool_approval_request.data.timeout_seconds` 为准
- 当前后端默认审批超时为 120 秒，超时后由后端自动拒绝
- 用户做出选择后，前端立刻更新工具状态
- 被拒绝后，Conversation 中应出现明确可见的系统反馈
- 输入栏中的策略选择器默认使用当前 UI 已选值，但“是否弹审批”必须以后端收到的本轮消息快照为准
- 前端在用户发送后应保留一条轻量可见的“本轮已锁定策略”反馈，便于用户核对刚发出的消息到底使用了哪种审批方式

---

## 7.7 Memory Workspace

### 目标

让用户查看并编辑 Newman 的稳定记忆与长期记忆。

### MVP 范围


- 查看 `USER.md`
- 查看 `MEMORY.md`

- 展示最近一次记忆更新时间


---

## 7.8 Skills Workspace

### 目标

展示当前系统可用 Skills，并解释每个 Skill 的作用。

### MVP 范围

- Skill 列表
- Skill 简介
- 对应 `SKILL.md` 内容预览
- 当前会话可用 / 不可用状态
- 可以删除某个skill
- 可以手动传入某个skill文件夹
- 提供保存按钮，保存后即代表skill列表更新了，系统可以使用新的skill

### 产品要求

- 明确告诉用户 Skill 是“说明书”，不是“直接执行器”
- 支持查看 Skill 依赖的 Tool 和使用限制

---

## 7.9 Files Workspace

### 目标

帮助用户理解当前工作区与知识文件，而不是做完整文件管理器。

### MVP 范围

- 当前工作区路径展示
- 最近上传或引用文件
- 文档解析状态
- 快速跳转到引用文件

---

## 八、视觉与交互规范

## 8.1 整体风格

前端应延续当前原型视觉方向：

- 主背景为暖白和浅米色
- 深色按钮与浅色卡片形成稳定对比
- 卡片边框轻，阴影弱
- 字体优先中文系统无衬线

### 当前色彩关键词

- 背景：`#ffffff`, `#fbfaf7`, `#f8f4ee`
- 线框：`#e5ddd3`, `#d8cec1`
- 文本：`#111111`, `#7f776f`
- 强调色：灰蓝、鼠尾草绿、暖橙

### 视觉结论

这是一套“纸张、档案、工作台”语义，不应改造成：

- 紫色科技风
- 深色黑客风
- SaaS Dashboard 风

---

## 8.2 组件视觉原则

### 会话列表

- 极简
- 文本优先
- 当前项只做轻度强调，不做强视觉喧宾夺主

### Trace 卡片（双层视觉规范）

#### 主层卡片

- 像“执行记录条目”，不是像聊天气泡
- 应支持 hover 和 active 状态
- 选中后与右侧 Drawer 形成联动
- Thinking 状态：显示动态 icon（如脉动圆点），thinking 完成后 icon 消失并替换为意图文案
- 主层文案使用正常正文字体，保持与整体纸感风格一致

#### 次层卡片（通用类型）

- 在主层卡片下方缩进展示，明确父子从属关系
- 使用浅色背景卡片，圆角，轻边框
- 展示工具名 icon + 工具名标签 + 参数摘要 + 状态标记
- 默认折叠，可展开

#### 次层卡片（终端类型）

终端工具（`terminal`）的次层展示必须使用独立的深色终端样式：

- **背景色**：`#1e1e1e` 或 `#2d2d2d`（深色），与主区暖白形成对比
- **文字颜色**：`#d4d4d4`（浅灰色）
- **字体**：等宽字体（如 `Menlo`、`Monaco`、`Consolas`、`monospace`）
- **顶部标签**：左上角显示 `Shell` 标签
- **命令行**：以 `$ ` 前缀展示命令，命令文字加粗或高亮
- **输出区域**：保留原始格式，支持滚动
- **状态标记**：右下角显示 `✓ 成功`（绿色）或 `✗ 失败`（红色）
- **圆角卡片**：与主区纸感风格协调，但内部是终端风格
- **折叠策略**：输出超过 10 行时默认折叠，显示可展开的摘要行（如“已运行命令 ⌄”或“Ran 1 command ⌄”）

### 结果卡片

- 比中间过程更完整
- 但不能完全淹没过程视图

### 抽屉

- 作为证据面板存在
- 应始终感觉像“附属证据层”，不是抢主舞台的第二个页面

---

## 8.3 移动端策略

当前原型已在 `820px` 以下退化为单栏，这个方向合理。

MVP 移动端策略：

- 左栏折叠
- 右侧 Drawer 不独立常驻，改为全屏滑层
- 输入栏置底吸附

不要求首版完整移动端优化，但必须保证：

- 可读
- 可操作
- 不崩布局

---

## 九、前端状态模型

前端至少维护以下状态域：

### 9.1 Session State

- 当前 session id
- session list
- 当前会话标题
- 恢复状态

### 9.2 Conversation State

- 消息列表
- 流式输出缓冲
- 当前是否在生成
- 当前是否强制终止

### 9.3 Trace State

- Trace 主层节点列表（每个主层节点包含其下属次层节点数组）
- 当前选中主层节点
- 当前展开的次层节点
- 节点详情缓存
- Thinking 状态（running / completed）

### 9.4 Tool State

- 工具执行状态
- 工具耗时
- 工具输入输出摘要
- 错误恢复状态

### 9.5 Approval State

- 当前审批请求
- 倒计时
- 审批结果
- `nextTurnApprovalMode`：输入区当前选中的下一轮策略
- `activeTurnApprovalMode`：已发送且正在执行的当前轮策略快照

### 9.6 Drawer State

- 是否打开
- 当前 tab
- 当前详情对象
- 当前宽度

### 9.7 UI Preference State

- 左栏宽度
- 右栏宽度
- 最近工作区页面

---

## 十、事件与接口契约

前端通过 SSE 订阅会话事件流，并以 REST 处理显式操作。

## 10.1 必须支持的 SSE 事件

- `assistant_delta`
- `tool_call_started`
- `tool_call_finished`
- `tool_retry_scheduled`
- `tool_approval_request`
- `tool_approval_resolved`
- `tool_error_feedback`
- `checkpoint_created`
- `final_response`
- `error`

当前前端还应兼容以下已实现事件：

- `attachment_received`
- `attachment_processed`
- `hook_triggered`
- `plan_updated`
- `stream_completed`

补充说明：

- `session_created` 已由 `POST /api/sessions/stream` 提供，但当前主消息流不依赖它
- `assistant_done` 暂未单独实现，现阶段以 `final_response` 作为“回答结束”信号
- `memory_updated` 暂未实现为 SSE，Memory 页当前通过 REST 刷新

## 10.2 前端事件处理原则

- 任何 SSE 事件都必须可落入统一事件总线
- UI 渲染不得直接依赖某个单一组件内部状态
- 工具状态和聊天状态要分离
- 前端必须先构建 `turn view model`，再渲染主区，不得把 `session.messages`、`assistant_delta`、`final_response` 作为三套并列 UI 输出
- 原始 SSE 事件必须先归一化为前端内部节点模型，再渲染到主区
- 主区文案必须由确定性映射逻辑生成，不得在前端再次调用 LLM 总结
- 如果事件缺少足够字段，使用保守 fallback 文案，不生成“看起来聪明但未经证实”的解释

## 10.3 必须支持的 REST 操作

- 新建会话
- 获取会话列表
- 重命名会话
- 删除会话
- 发送消息
- 提交审批结果
- 手动触发压缩
- 恢复 checkpoint
- 获取插件列表
- 更新插件启停

发送消息接口补充要求：

- `POST /api/sessions/{id}/messages` 需要支持携带 `approval_mode`
- 当前最小枚举值：
- `manual`：每个命中 Level 2 的工具都需要点击确认
- `auto_approve_level2`：本轮命中 Level 2 的工具默认通过
- 前端提交后不得假设后端会读取当前 UI 实时状态，而应始终依赖本次请求携带的快照

## 10.4 事件到主区文案的映射规则

### 10.4.1 总体要求

前端必须采用“原始事件 / 持久化消息 -> turn 容器 -> 归一化节点 -> 主区文案”的固定流程：

1. 接收 SSE 原始事件与 session detail 持久化消息
2. 先按 `turn_id / request_id / 时间区间` 归并为 turn 容器
3. 把过程事件归一化为内部 `timeline item`
4. 把 `assistant_delta / final_response / persisted assistant message` 归并到同一个回答槽位
5. 按事件类型和结构化字段选择文案模板
6. 把工具名、Skill 名、Agent 名、耗时、状态等作为次级元信息附着到节点
7. 把原始输入输出和引用证据保留到 Drawer

禁止做法：

- 根据上下文自由生成一段新的解释性文案
- 用 LLM 对工具结果再总结成主区文案
- 当前端没有收到对应事件时，凭空补出 `thinking`、`skill`、`agent` 过程
- 为同一个 turn 同时渲染“流式回答气泡”和“持久化 assistant 消息气泡”

允许做法：

- 使用固定模板
- 使用结构化字段拼接文案
- 使用前端本地映射字典做工具语义归类
- 使用后端返回的结构化 `summary_text` / `display_label` / `target_label` 这类字段

### 10.4.2 主区与 Drawer 的信息分工

主区只展示：

- 当前在做什么
- 是否需要用户确认
- 当前是否成功、失败、重试、等待
- 少量结果摘要，例如数量、对象名、完成状态

主区不直接展开：

- 原始工具参数
- 长文本输出
- 错误堆栈
- 引用原文片段
- MCP / Skill / Agent 的底层协议字段

这些内容统一进入右侧 Drawer。

### 10.4.3 归一化节点类型

| 原始事件 / 来源 | 归一化节点类型 | 主区默认可见 | 说明 |
| --- | --- | --- | --- |
| `assistant_delta` | `assistant_stream` | 否 | 只更新当前 turn 的回答槽位，不作为过程节点 |
| `plan_updated` | `plan` | 是 | 展示“先做什么”的阶段性计划 |
| `tool_call_started` | `progress` | 是 | 表达正在执行的动作 |
| `tool_call_finished` | `progress` | 是 | 更新已有节点为完成，并补充结果摘要 |
| `tool_retry_scheduled` | `progress_retry` | 是 | 更新已有节点为“准备重试” |
| `tool_approval_request` | `approval` | 是 | 必须在主区清晰可见 |
| `tool_approval_resolved` | `approval` | 是 | 更新审批节点状态 |
| `tool_error_feedback` | `error_recovery` | 是 | 展示失败与恢复策略 |
| `final_response` | `assistant_finalized` | 否 | 把当前回答槽位置为完成态，并作为持久化 assistant message 的对账信号 |
| `error` | `fatal_error` | 是 | 不可恢复错误 |
| `checkpoint_created` | `system_meta` | 否 | 默认只在 Drawer 或调试视图中可见 |
| `attachment_received` / `attachment_processed` | `attachment_progress` | 视场景 | 默认低优先级展示 |
| `hook_triggered` | `system_meta` | 否 | 默认不抢占主区 |
| 结构化 `thinking` 事件 | `thinking` | 是 | 当前后端若未提供则不虚构 |
| 结构化 `skill` 事件 | `skill_progress` | 是 | 当前后端若未提供则不虚构 |
| 结构化 `agent handoff` 事件 | `agent_progress` | 是 | 当前后端若未提供则不虚构 |

### 10.4.4 主文案模板规则

| 归一化节点类型 | 状态 | 主区文案模板 | 次级信息 |
| --- | --- | --- | --- |
| `thinking` | running | `我先理一下思路` | `thinking` 标签可选显示 |
| `plan` | updated | `先列一下执行步骤` | 可展示步骤数 |
| `progress` | running | 按工具语义映射生成，例如 `正在查看相关文件` | 工具名、对象名、耗时 |
| `progress` | completed | 按结构化结果生成，例如 `已找到 4 个文件`，无结果时为 `这一步已完成` | 工具名、结果数、耗时 |
| `progress_retry` | waiting | `刚才那一步没成功，我换一种方式继续` | 重试次数、工具名 |
| `skill_progress` | running | `正在应用一个分析步骤` | Skill 名 |
| `skill_progress` | completed | `这个分析步骤已完成` | Skill 名 |
| `agent_progress` | running | `正在并行处理这个任务` | Agent 名、角色 |
| `agent_progress` | completed | `并行处理结果已返回` | Agent 名、角色 |
| `approval` | pending | `这一步需要你确认后我才能继续` | 工具名、风险级别、倒计时 |
| `approval` | approved | `已获得你的确认，继续处理中` | 工具名 |
| `approval` | rejected | `你已拒绝这一步，我将改用别的方法` | 工具名 |
| `error_recovery` | recovering | `刚才那一步失败了，我正在调整后继续` | 工具名、错误类别 |
| `error_recovery` | blocked | `这一步暂时没成功，需要你关注一下` | 工具名、错误类别 |
| `fatal_error` | failed | `这次执行中断了，请查看错误详情` | 错误类别 |

### 10.4.4A 单回答槽位生命周期

- `assistant_delta` 到来后，当前 turn 的回答槽位进入 `streaming`
- `final_response` 到来后，同一个回答槽位进入 `finalizing`
- 前端拿到持久化 `assistant message` 后，同一个回答槽位进入 `persisted`
- 三个阶段只能共用一个回答槽位，禁止同时显示两份内容相同的 assistant 回答窗口
- Drawer 中允许区分“当前回答 / 最终回答 / 持久化来源”，但主区只能看到一个回答窗口

### 10.4.5 工具语义映射字典

前端不得直接把工具名拼成主句，而应先将工具归类到语义动作，再选文案模板。

#### 系统工具清单

当前系统注册的工具如下，所有工具均需在映射字典中有对应条目：

- `read_file`——读取文件内容
- `list_dir`——列出目录结构
- `list_files`——列出文件列表
- `search_files`——按名称检索文件
- `grep`——按内容搜索文件
- `fetch_url`——抓取网页内容
- `terminal`——执行终端命令
- `write_file`——写入新文件
- `edit_file`——编辑已有文件
- `update_plan`——更新执行计划
- `search_knowledge_base`——检索本地知识库

#### 推荐最小映射字典

| 工具类别 | 命中规则示例 | 主层运行中文案模板 | 主层完成文案模板 | 次层展示类型 |
| --- | --- | --- | --- | --- |
| 文件查看 | `read_file` | `正在查看文件` | `文件已查看完毕` | 文件卡片 |
| 目录浏览 | `list_dir` | `正在查看目录结构` | `目录结构已确认` | 文件卡片 |
| 文件列表 | `list_files` | `正在查看文件列表` | `文件列表已获取` | 文件卡片 |
| 文件检索 | `search_files` | `正在检索相关文件` | `已找到 {count} 个相关文件` | 检索卡片 |
| 内容搜索 | `grep` | `正在搜索文件内容` | `已找到 {count} 处匹配` | 检索卡片 |
| 网页抓取 | `fetch_url` | `正在查看网页资料` | `网页资料已获取` | 网络卡片 |
| 终端执行 | `terminal` | `正在运行命令` | `命令已执行完成` | **终端样式**（深色背景） |
| 文件写入 | `write_file` | `正在创建文件` | `文件已创建` | 文件卡片 |
| 文件编辑 | `edit_file` | `正在修改文件` | `文件已更新` | 文件卡片（含 diff 摘要） |
| 计划更新 | `update_plan` | `先列一下执行步骤` | `执行步骤已更新` | 计划卡片 |
| 知识库检索 | `search_knowledge_base` | `正在检索知识资料` | `已找到 {count} 条知识结果` | 检索卡片 |
| 外部能力调用 | `mcp__*` | `正在调用外部能力` | `外部能力调用已完成` | 通用卡片 |
| 提取 / 摘要 / 比对 | `extract`、`summarize`、`diff`、`compare` | `正在整理关键信息` | `关键信息已整理完成` | 通用卡片 |
| 未知工具 | fallback | `正在获取完成任务所需信息` | `这一步已完成` | 通用卡片 |

注：“次层展示类型”列指示次层应使用何种视觉样式，其中**终端样式**必须使用深色背景 + 等宽字体模拟终端效果，其他类型使用浅色卡片样式。

### 10.4.6 对象名拼接规则

当事件包含对象字段时，主文案可做有限拼接，但必须是确定性规则：

- 若存在 `target_label`，优先使用它
- 否则若存在单个 `path`，使用文件名或目录名
- 否则若存在 `query`，使用 `「{query}」相关资料`
- 否则若存在 `url`，使用域名或“网页资料”
- 否则若存在 `resource_name` / `title`，使用该名称
- 否则不拼对象名，退化为通用模板

示例：

- `search_files + query="styles.css"` -> `正在检索「styles.css」相关文件`
- `read_file + path="/root/newman/frontend/src/App.tsx"` -> `正在查看 App.tsx`
- `fetch_url + url="https://example.com/a"` -> `正在查看网页资料`

### 10.4.7 结果摘要拼接规则

主区只允许展示结构化、短句式结果摘要，优先级如下：

1. 后端提供 `summary_text`
2. 前端根据结构化计数字段生成，例如 `count`、`file_count`、`hit_count`、`updated_count`
3. 前端根据对象字段生成，例如 `已更新 App.tsx`
4. 没有结构化字段时，回退为 `这一步已完成`

禁止把长文本输出截断后直接塞进主区。

### 10.4.8 错误与审批文案规则

错误和审批必须比普通进展更直接，但仍然说人话：

- 权限或审批相关：`这一步需要你确认后我才能继续`
- 可恢复错误：`刚才那一步失败了，我换一种方式继续`
- 不可恢复错误：`这次执行中断了，请查看错误详情`
- 用户拒绝审批：`你已拒绝这一步，我将改用别的方法`

主区可以显示错误类别标签，例如 `权限`、`网络`、`超时`，但不要直接展示长错误栈。

### 10.4.9 P0 实现约束

- P0 必须使用前端本地映射表完成主区文案
- P0 不依赖 LLM 重写过程文案
- 若后端未来补充 `display_label`、`summary_text`、`target_label` 等结构化字段，前端可直接消费
- 即使后端补充这些字段，也应视为“结构化提示”，而不是自由文本生成链路
- 没有对应结构化事件时，前端不主动脑补 `thinking`、`skill`、`agent` 节点

---

## 十一、关键交互流程

## 11.1 新建会话

1. 用户点击左栏 `+`
2. 中间区进入空态
3. 用户输入任务
4. 前端创建会话并开始 SSE 订阅
5. 对话区切换到运行态

## 11.2 工具执行与查看详情

1. 收到 `tool_call_started`
2. 前端归一化为主区进展节点，并生成人话文案
3. 用户点击节点
4. 右侧 Drawer 打开，显示该工具详情
5. 收到 `tool_call_finished` 后更新同一节点状态与结果摘要

## 11.3 审批流程

1. 用户在底部输入栏选择本轮审批策略
2. 用户发送消息，前端把 `approval_mode` 与本轮消息一起提交
3. 后端开始执行本轮任务，并锁定本轮审批策略
4. 若策略为 `manual` 且命中 `tool_approval_request`，前端弹出 Approval Modal
5. 用户允许或拒绝
6. 前端调用审批 API
7. 收到 `tool_approval_resolved`
8. Trace 与 Tool 状态同步更新

若策略为 `auto_approve_level2`：

1. 用户在底部输入栏选择 `全部默认通过`
2. 用户发送消息，前端把 `approval_mode=auto_approve_level2` 随消息提交
3. 本轮命中的 Level 2 工具默认放行，不弹 Approval Modal
4. Tool 状态直接进入后续执行与完成链路

## 11.4 错误恢复流程

1. Tool 执行失败
2. 收到 `tool_error_feedback`
3. 主区显示人话错误恢复提示
4. 如果后续恢复成功，节点状态从错误中恢复到完成

## 11.5 查看引用

1. 用户点击结果卡片或 Trace 节点
2. 右侧 Drawer 打开到 `引用`
3. 查看来源、页码、片段预览
4. 支持跳转到 Files 或知识文件

---

## 十二、技术实现建议

## 12.1 当前实现现状

当前 `frontend` 工程是：

- Vite
- React 18
- TypeScript
- 手写 CSS

见 [package.json](/root/newman/frontend/package.json)。

## 12.2 建议路线

为了与总 PRD 对齐，建议分阶段处理：

### 路线 A：先保留现有 Vite 原型，快速迭代

适合：

- 继续打磨信息架构
- 快速做交互验证
- 保持轻量实现

### 路线 B：产品化阶段迁移到 Next.js

适合：

- 路由与页面结构清晰化
- 更稳定的数据获取与部署形态
- 和总 PRD 技术选型统一

建议：

- P0 原型可继续使用 Vite
- P1 或产品化阶段再迁移到 Next.js

## 12.3 状态管理建议

推荐使用 Zustand 或等价轻量状态库，按域拆分：

- `sessionStore`
- `conversationStore`
- `traceStore`
- `toolStore`
- `approvalStore`
- `uiStore`

## 12.4 Markdown 与引用渲染

建议：

- 聊天回答支持 Markdown
- Trace / Tool IO 采用结构化渲染，不直接 raw markdown 化

## 12.5 主区文案与双层渲染实现建议

建议前端实现一个固定的映射模块，例如：

- `normalizeSseEvent(rawEvent) -> TimelineItem`
- `buildChatTurns(messages, rawEvents) -> ChatTurn[]`
- `resolveToolSemantic(toolName) -> ToolSemantic`
- `resolveDisplayTarget(eventData) -> string | null`
- `buildTimelineCopy(item) -> { primaryText, secondaryMeta }`
- `resolveSecondaryCardType(toolName) -> 'terminal' | 'file' | 'search' | 'network' | 'plan' | 'generic'`

其中 `resolveSecondaryCardType` 用于决定次层使用何种视觉样式渲染，特别是 `terminal` 类型需要切换到深色终端样式。

实现要求：

- 所有主层过程文案都从同一套映射模块产出
- 次层展示类型由映射模块统一决定，不在组件内硬编码
- UI 组件只消费映射结果，不在组件内手写分散判断
- 同一事件在不同页面或不同组件中的主文案应保持一致
- 允许在映射模块内维护一份可配置字典，但不允许把文案生成散落在各个组件里
- 终端工具的次层渲染组件应独立封装（如 `TerminalCard`），接受命令、输出、状态作为 props
---

## 十三、验收标准

### P0 验收

- 三栏工作台布局可用
- 会话列表与新建会话可用
- 对话流式展示可用
- Turn 三段结构完整：用户消息 → Timeline → Answer Slot
- Timeline 双层结构可用：主层展示意图文案，次层展示工具调用详情
- Thinking 动态 icon 在 thinking 阶段显示、结束后替换为意图文案
- 次层默认折叠，支持展开查看工具调用过程
- 终端工具（`terminal`）次层使用深色终端样式展示命令和输出
- Trace 主层节点可点击并联动 Drawer
- Tool Approval 闭环可用
- Context Usage 显示可用
- 移动端不崩布局
- 主层过程文案不直接暴露原始事件名，默认以用户可理解进展呈现
- 主层过程文案由确定性映射逻辑生成，不依赖 LLM 重写
- 次层展示类型由映射模块统一决定，终端 / 文件 / 检索等类型视觉可区分

### P1 验收

- Memory / Skills / Files 页面可用
- 插件管理页可用
- 错误恢复状态可视化完整
- 引用展示支持跳转原始文件

---

## 十四、与现有原型的一致性要求

前端正式实现必须保留以下原型特征：

- 左栏导航 + 会话列表
- 中央对话与执行轨迹混合展示
- 右侧详情抽屉
- 底部输入栏 + 上下文占用指示器
- 暖白纸感风格
- 可点击 Trace 卡片

不应改成：

- 纯聊天双气泡界面
- 只有答案没有过程的单列结构
- 通用 SaaS 后台风格

---

## 十五、总结

Newman 前端的核心不是“把 AI 结果展示出来”，而是把一次 Agent 执行任务的全过程变成一个用户可理解、可检查、可批准、可追溯的工作界面。

因此前端的第一优先级不是炫技动画，也不是通用聊天体验，而是：

- 过程透明
- 状态准确
- 风险可感知
- 证据可到达
- 长时间使用不疲劳

---

## 十六、当前待办

以下需求已明确保留为待办，暂不在本轮强行固化：

- Evidence Drawer 的右侧信息架构还需继续细化，`Trace / Tool IO / 引用` 的具体字段和交互暂未定稿
- Memory / Skills / Files 三个工作区的深度产品化仍是待办，当前先保持基础可用
- 移动端工作台的抽屉滑层、输入栏吸附与更完整适配仍是待办
- 刷新页面后的连续性已补齐基础恢复：当前会话、工作区页、栏宽、最近选中的 trace、待审批请求，以及最近一次可见的流式回答内容
- 更完整的 SSE 断点续传仍是后续专项待办；当前只能恢复“最后一次可见状态”，不能把原流继续接上

这也是 Newman 与普通 AI 对话产品在前端层面的根本区别。
