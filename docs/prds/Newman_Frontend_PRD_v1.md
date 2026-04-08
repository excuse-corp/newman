# Newman Frontend PRD v1.0

2026 · 内部文档

> 基于现有 `frontend/src/App.tsx`、`frontend/src/styles.css` 的 UI 原型，以及 [Newman_PRD_v9.md](/root/newman/docs/prds/Newman_PRD_v9.md) 整体产品定义整理。

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

结合当前原型样式，前端设计语言应固定为：

- 纸感工作台
- 米白底色
- 低噪音边框
- 三栏结构
- 结果与过程并列
- 右侧证据抽屉
- 轻量、克制、可信

当前原型已体现这一方向，见：

- [App.tsx](/root/newman/frontend/src/App.tsx)
- [styles.css](/root/newman/frontend/src/styles.css)

---

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

### 3.2 默认克制

界面不追求“炫”，要追求：

- 信息清晰
- 风险提示准确
- 主次分明
- 可持续长时间使用

### 3.3 证据始终可达

所有重要结论都必须尽量能展开查看依据，特别是：

- RAG 引用
- 工具输入输出
- Skill 来源
- 错误摘要

### 3.4 任务连续性优先

用户中途离开、刷新页面、恢复会话后，前端要尽量恢复：

- 会话列表状态
- 当前会话
- 抽屉打开状态
- 正在审批的请求
- 正在流式返回的最后状态

### 3.5 本地优先体验

前端不应过度依赖云端概念，不使用需要平台账号才能成立的交互模型。

---

## 四、目标用户

### 4.1 核心用户

- 在本地环境中使用 AI 辅助完成复杂任务的知识工作者
- 需要查看中间过程和证据来源的重度用户
- 需要 AI 帮助运行命令、读写文件、分析资料的研发或数据用户

### 4.2 用户诉求

- 不仅要答案，还要过程
- 不仅要过程，还要可控
- 不仅要可控，还要不打断工作流

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

后续 P1 可增补：

- `Plugins`
- `Knowledge`
- `Settings`

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

### 当前原型特征

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
- Trace Blocks
- Final Answer Block
- Composer Bar
- Context Usage Indicator
- Evidence Drawer

### 关键要求

- 空态要强调“开始一个任务”，不是“开始聊天”
- 中间态要优先展示执行轨迹
- 最终答案要保留继续追问的上下文

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

### 交互要求

- 切换会话后，中心区与右侧 Drawer 数据同步刷新
- 会话标题优先使用 AI 自动摘要标题，允许用户手动重命名

---

## 7.4 Trace Timeline

### 目标

展示 Agent 中间执行过程。

### 展示对象

- thinking
- plan
- tool call
- skill call
- agent handoff / 协同
- tool result
- tool error feedback

### 当前原型已经体现的类型

- `trace`
- `tool`
- `skill`
- `agent`
- `result`

### 前端要求

- 每个 Trace 节点都应可点击
- 点击后右侧 Drawer 展示该节点详情
- 不同类型节点要有一致但可区分的视觉样式

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

- 右侧抽屉滑入
- 支持拖拽宽度
- 与主会话并列存在，不打断阅读

### 产品要求

- Trace tab：解释当前节点做了什么
- Tool IO tab：展示参数、输出、耗时、状态
- 引用 tab：展示来源文档、网页、技能或 agent 来源

---

## 7.6 Approval Modal

### 目标

承载 Level 2 工具审批交互。

### 触发条件

收到 SSE 事件 `tool_approval_request`

### 展示内容

- 工具名
- 操作对象
- 风险说明
- 影响范围
- 倒计时
- `允许` / `拒绝`

### 交互要求

- 倒计时以 SSE `tool_approval_request.data.timeout_seconds` 为准
- 当前后端默认审批超时为 120 秒，超时后由后端自动拒绝
- 用户做出选择后，前端立刻更新工具状态
- 被拒绝后，Conversation 中应出现明确可见的系统反馈

---

## 7.7 Memory Workspace

### 目标

让用户查看并编辑 Newman 的稳定记忆与长期记忆。

### MVP 范围

- 查看 `Newman.md`
- 查看 `USER.md`
- 查看 `MEMORY.md`
- 查看 `SKILLS_SNAPSHOT.md`
- 展示最近一次记忆更新时间

### P1 范围

- 记忆 diff
- 记忆来源追溯
- 记忆片段检索

---

## 7.8 Skills Workspace

### 目标

展示当前系统可用 Skills，并解释每个 Skill 的作用。

### MVP 范围

- Skill 列表
- Skill 简介
- 对应 `SKILL.md` 内容预览
- 当前会话可用 / 不可用状态

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

### Trace 卡片

- 像“执行记录条目”，不是像聊天气泡
- 应支持 hover 和 active 状态
- 选中后与右侧 Drawer 形成联动

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

- Trace 节点列表
- 当前选中节点
- 节点详情缓存

### 9.4 Tool State

- 工具执行状态
- 工具耗时
- 工具输入输出摘要
- 错误恢复状态

### 9.5 Approval State

- 当前审批请求
- 倒计时
- 审批结果

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
2. 中间 Trace 增加新节点
3. 用户点击节点
4. 右侧 Drawer 打开，显示该工具详情
5. 收到 `tool_call_finished` 后状态更新

## 11.3 审批流程

1. 收到 `tool_approval_request`
2. 弹出 Approval Modal
3. 用户允许或拒绝
4. 前端调用审批 API
5. 收到 `tool_approval_resolved`
6. Trace 与 Tool 状态同步更新

## 11.4 错误恢复流程

1. Tool 执行失败
2. 收到 `tool_error_feedback`
3. Trace 中显示“错误恢复中”
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

---

## 十三、验收标准

### P0 验收

- 三栏工作台布局可用
- 会话列表与新建会话可用
- 对话流式展示可用
- Trace 节点可点击并联动 Drawer
- Tool Approval 闭环可用
- Context Usage 显示可用
- 移动端不崩布局

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
