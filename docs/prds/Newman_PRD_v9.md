# Newman 产品需求文档（PRD）v9.0

2026 · 内部文档

## 一、文档目标

本文档定义 Newman 的产品目标、系统边界、核心运行时、模块契约和交付范围，用于指导后续架构设计、研发拆分与验收。

本版在 v8 的基础上做了以下优化：

- 统一版本标识，避免文件名与正文版本不一致
- 强化本地优先、透明可控、可插拔扩展三条产品主线
- 明确 `Tool / Skill / Plugin / Hook / MCP` 五层能力模型
- 参考成熟 Agent CLI 架构，补强运行时、权限、记忆压缩与插件设计
- 收敛 MVP 范围，避免首版过度设计
- 减少重复描述，统一事件、错误、状态、模块边界

---

## 二、产品定义

### 2.1 产品定位

Newman 是一个运行在本地的轻量级 AI Agent 系统，目标是成为用户在知识处理、执行协助、工作流自动化中的可信数字副手。

Newman 与典型云端 AI SaaS 的核心区别：

- 数据本地优先：对话、记忆、技能、知识库、插件配置默认保存在用户本机
- 能力透明：System Prompt 组成、工具调用、审批、错误恢复过程可见
- 可插拔扩展：支持通过 Skills、Plugins、MCP 逐步增加能力
- 多模型兼容：通过统一 Provider 层接入 OpenAI-compatible、Anthropic-compatible 或本地模型服务

### 2.2 核心设计原则

#### 1. 文件即记忆（File-first Memory）

- 稳定记忆和用户偏好以 Markdown/JSON 持久化
- 运行时可建立索引与缓存，但不改变“文件为事实源”的原则
- 用户可直接查看、编辑、备份、迁移

#### 2. 技能即说明，插件即交付（Skills as Instructions, Plugins as Delivery）

- Skill 是 Agent 完成某类任务的方法说明书
- Plugin 是能力分发单元，可包含 Skills、Hooks、MCP 配置、工具扩展和前端扩展
- Skill 不直接执行副作用，真正执行由 Tool Runtime 完成

#### 3. 透明可控（Transparent by Default）

- Prompt 拼接顺序可解释
- 工具调用过程可追踪
- 高风险动作必须审批
- 错误要结构化，能让模型继续恢复，而不是直接中断

#### 4. 本地优先，远程可选（Local-first, Remote-optional）

- 默认在本机工作区执行
- 默认不依赖平台账号体系
- 企业 IM、远程访问、外部知识源作为可选扩展

---

## 三、目标用户与典型场景

### 3.1 目标用户

- 需要处理文档、报告、表格和网页资料的知识工作者
- 需要执行脚本、调试代码、自动化任务的研发或数据用户
- 重视数据私有性、可审计性和可控性的个人与小团队

### 3.2 典型使用场景

#### 场景 A：文档理解与知识提炼

用户上传 PDF、Word、PPT、Excel、图片等资料，询问重点结论、差异分析、行动建议。

系统行为：

- 解析文档
- 建立检索索引
- 混合召回与重排
- 生成结构化回答并附引用溯源

#### 场景 B：本地执行与错误修复

用户给出脚本、命令或代码片段，请求执行、检查报错、尝试修复。

系统行为：

- 判断是否需要工具执行
- 进入工具审批流程
- 在受限运行时执行
- 将错误摘要回灌给模型继续恢复

#### 场景 C：长期助理与工作流提醒

用户希望 Newman 记住偏好、持续跟踪任务、定时提醒或按计划执行巡检。

系统行为：

- 保存跨会话记忆
- 管理待办和会话摘要
- 通过 Scheduler 触发计划任务
- 将触发事件注入对话或后台任务队列

---

## 四、MVP 范围与非目标

### 4.1 MVP 必做范围（P0）

- 单用户、本地优先
- Web 前端 + FastAPI 后端
- 单 Agent 主循环
- 文件型稳定记忆与会话历史
- 上下文压缩与会话恢复
- 当前核心工具：`read_file`、`fetch_url`、`terminal`、`search_knowledge_base`
- Tool 审批机制
- 文档解析与基础 RAG
- 插件目录与 Skill 目录热加载
- OpenAI-compatible Provider 抽象
- SSE 流式事件协议

### 4.2 P1 增强范围

- MCP 集成
- 定时任务 Scheduler
- 长期记忆向量召回
- 企业 IM Channel Adapter
- 前端工具审批中心、插件管理中心

### 4.3 明确不在当前版本实现

- 多 Agent 协作主流程
- 复杂团队权限体系
- 云端账号与多租户
- 远程桥接、桌面常驻代理、移动端同步
- 插件市场和在线分发

---

## 五、核心能力模型

为避免概念混淆，Newman 统一采用以下五层能力模型。

### 5.1 Tool

Tool 是最底层原子执行能力，例如：

- 读文件
- 发网络请求
- 执行 Shell 命令
- 查询知识库

特点：

- 有明确输入输出 Schema
- 有权限等级和审批规则
- 可被统一路由与统一错误处理

### 5.2 Skill

Skill 是方法说明书，告诉 Agent 应该如何使用 Tool 完成某类任务。

特点：

- 以 `SKILL.md` 形式存在
- 可以被注入 Stable Context，也可以按需读取
- 自身无副作用
- 产生命令建议，但最终执行仍由 Tool Runtime 决定

### 5.3 Plugin

Plugin 是能力交付单元，可包含：

- Skills
- Hooks
- MCP Server 配置
- 前端扩展配置
- 插件级默认设置

特点：

- 可启用、禁用、安装、卸载
- 可热加载
- 是 Newman 扩展生态的基本单位

### 5.4 Hook

Hook 是系统生命周期扩展点，例如：

- SessionStart
- PreToolUse
- PostToolUse
- SessionEnd
- FileChanged

特点：

- 供插件和系统扩展接入
- 必须受沙箱与权限约束
- 不应破坏主循环确定性

### 5.5 MCP

MCP 用于接入外部能力提供者或本地服务。

特点：

- 与本地 Tool 一样进入统一注册表
- 按配置决定是否审批
- 可以暴露工具与资源

---

## 六、系统架构总览

### 6.1 技术选型

| 方向 | 选型 |
|---|---|
| 后端 | Python 3.11 + FastAPI |
| 流式输出 | SSE |
| Agent 编排 | LangChain 1.x + LangGraph 1.x |
| 运行时模型接口 | Provider Adapter |
| 本地知识检索 | BM25 + Chroma + Reranker |
| 关系与统计存储 | PostgreSQL |
| 本地事实源 | File System |
| 执行沙箱 | Linux 原生沙箱（bubblewrap，Phase 1），macOS / Windows 待做 |
| 前端 | Next.js 14+ |

### 6.2 系统分层

```text
UI / CLI / IM Channel
    ↓
API Layer (FastAPI + SSE)
    ↓
Runtime Layer
  - ThreadManager
  - SessionTask
  - RunLoop
  - ToolRouter
  - ToolOrchestrator
    ↓
Capability Layer
  - Tools
  - Skills
  - Plugins
  - Hooks
  - MCP
    ↓
Foundation Layer
  - Memory Files
  - Sessions Store
  - RAG Index
  - Provider Adapters
  - Sandbox
```

### 6.3 关键设计决定

#### 决定 A：运行时与能力分离

- 运行时只负责编排和状态推进
- Tool / Skill / Plugin 不直接耦合到主循环内部细节

#### 决定 B：Stable Context 文件化

Stable Context 由固定文件和工具概览拼接而成，避免隐藏 prompt 逻辑。

#### 决定 C：权限前置

工具不仅执行前审批，还要在“暴露给模型前”经过权限过滤。

#### 决定 D：错误结构化

错误不是字符串日志，而是统一结果结构，便于分类、回灌和前端展示。

---

## 七、执行运行时

### 7.1 生命周期总览

```text
用户输入
  ↓
ThreadManager 创建或恢复线程
  ↓
SessionTask 初始化
  ↓
PromptAssembler 拼接三层上下文
  ↓
TokenEstimator 判断是否压缩
  ↓
RunLoop 调用模型
  ↓
如果无 tool_call → TurnComplete
如果有 tool_call → ToolRouter → ToolOrchestrator → Tool Runtime
  ↓
ResultNormalizer → ErrorClassifier → FeedbackWriter
  ↓
继续循环或完成回合
  ↓
写回 session / memory / metrics / SSE
```

### 7.2 ThreadManager

职责：

- 新建会话并生成 `session_id`
- 恢复会话与最近 checkpoint
- 提供会话列表和删除能力
- 保证线程状态隔离

数据来源：

- `sessions/*.json`
- `sessions/*_checkpoint.json`

### 7.3 SessionTask

SessionTask 是单轮执行容器，持有：

- 当前 Thread history
- 当前 Agent 配置
- 当前可用工具集合
- 当前可用 Skills 子集
- 审批上下文
- SSE 推送队列
- 工具调用计数器

### 7.4 PromptAssembler

Prompt 拼接使用三层模型：

#### 1. Stable Context

- `Newman.md`
- `USER.md`
- `SKILLS_SNAPSHOT.md`
- 工具列表

规则：

- 永不压缩
- 永不截断
- 每轮重新装载

#### 2. Working History

- user / assistant / tool_call / tool_result 消息
- 是主要压缩对象

#### 3. Checkpoint Summary

- 当上下文超限时，用结构化摘要替换旧的 Working History

### 7.5 Skill 注入策略

借鉴成熟 Agent CLI 设计，Skill 分两种注入方式：

- `Skill Snapshot Injection`：将当前会话允许的 Skills 摘要注入 Stable Context
- `On-demand Skill Read`：模型可通过只读方式读取具体 `SKILL.md`

这样可以同时满足：

- 让模型知道“有哪些技能可用”
- 避免首轮 prompt 塞入过多细节

### 7.6 RunLoop

约束：

- 单轮最大工具调用深度默认 20
- 工具结果必须归一化后再写回 history
- 所有可恢复错误必须写回 history
- 只有致命错误才中断当前回合

---

## 八、工具治理与权限模型

### 8.1 Tool 元数据要求

每个 Tool 至少定义：

- `name`
- `description`
- `input_schema`
- `risk_level`
- `requires_approval`
- `timeout_seconds`
- `allowed_paths` 或 `allowed_domains`

### 8.2 ToolRouter

ToolRouter 负责：

- 按工具名匹配 Runtime
- 判断是否需要 Orchestrator
- 对路径、域名、Workspace 约束做静态检查

### 8.3 ToolOrchestrator

ToolOrchestrator 是统一治理层，负责：

- 两级审批
- 超时
- 透明重试
- 审计记录
- 终止控制

### 8.4 两级审批

#### Level 1：静默拦截

触发条件：

- 命中黑名单
- 明显越权路径
- 明显危险命令

处理：

- 不弹窗
- 直接返回结构化拒绝结果

#### Level 2：人在回路

触发条件：

- 高风险命令
- 写入非工作区文件
- 白名单外网络访问
- 被标记为 `require_approval=true` 的 MCP 工具

处理：

- 暂停执行
- 推送 `tool_approval_request` 事件
- 等待用户确认

### 8.5 权限上下文（Permission Context）

参考成熟 CLI 代理经验，Newman 不只做“执行前审批”，还要维护会话级权限上下文：

- allow rules
- deny rules
- ask rules
- additional working directories
- 当前会话是否可提升权限

这样做的价值：

- 减少模型看见不该用的工具
- 减少重复审批
- 提高系统一致性

---

## 九、统一错误恢复机制

### 9.1 设计原则

- 错误是状态，不是异常字符串
- 错误首先进入结构化结果模型
- 可恢复错误优先回灌给模型继续处理
- 致命错误才终止主循环

### 9.2 ToolExecutionResult

统一结构保留，字段如下：

- `success`
- `tool`
- `action`
- `category`
- `exit_code`
- `summary`
- `stdout`
- `stderr`
- `duration_ms`
- `retryable`
- `metadata`

### 9.3 错误分类

保留 v8 分类，但新增两条实现要求：

- 分类结果必须既能驱动模型恢复，也能驱动前端展示
- 分类结果必须能映射为统一错误码

### 9.4 错误摘要要求

错误摘要必须同时面向两类消费者：

- 模型：需要最小必要上下文和建议下一步
- 前端：需要可读的错误状态与风险级别

建议统一输出：

```text
The previous action failed.

Tool: {tool}
Action: {action}
Category: {category}
Exit code: {exit_code}
Retryable: {retryable}

Summary:
{summary}

Key output:
{key_output}

Recommended next step:
{recommended_next_step}
```

---

## 十、记忆与上下文压缩

### 10.1 记忆分层

Newman 统一采用四类记忆对象：

#### A. System Memory

- `Newman.md`
- 平台级全局规则

#### B. User Memory

- `USER.md`
- 用户偏好和交互约定

#### C. Session Memory

- `sessions/*.json`
- 单会话历史事实

#### D. Long-term Memory

- `MEMORY.md`
- 跨会话重要信息

### 10.2 上下文压缩策略

保留 v8 中 `80% / 92%` 双阈值思路，但新增两个实现约束：

- 压缩永远只作用于 Working History
- Stable Context 与 Long-term Memory 不参与裁剪，只参与注入策略优化

### 10.3 Checkpoint 设计

Checkpoint 必须满足：

- 可读
- 可替换
- 可恢复
- 可持续递归压缩

### 10.4 长期记忆策略

MVP：

- `MEMORY.md` 全量注入

优化阶段：

- 将长期记忆片段化、向量化
- 每轮召回 Top-K 片段注入
- 文件仍作为事实源，索引只是加速层

---

## 十一、Plugin 与 Skill 体系

### 11.1 目录约定

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

### 11.2 Plugin 元数据

每个插件至少声明：

- `name`
- `version`
- `description`
- `enabled_by_default`
- `skills`
- `hooks`
- `mcp_servers`
- `required_permissions`

### 11.3 Skill 设计原则

- Skill 是说明，不是脚本
- Skill 内容应描述目标、输入前提、推荐工具、约束和失败处理
- Skill 应支持按需读取，不应强制整包注入

### 11.4 热加载

插件与技能支持热加载，但要求：

- 插件状态变更后重新计算可用工具与技能集合
- 当前运行中的 SessionTask 不强制中断
- 下一轮生效

---

## 十二、RAG 与知识库

### 12.1 核心流程

```text
文档导入 → 文档解析 → Chunk 切分 → Embedding → Chroma 持久化
               ↓
            元数据入 PostgreSQL
               ↓
用户查询 → BM25 + Vector Search → Reranker → 引用生成
```

### 12.2 存储职责

- File System：原始文档和解析产物
- Chroma：向量检索
- PostgreSQL：文档元数据、chunk 映射、引用记录、统计数据

### 12.3 引用要求

RAG 输出必须支持：

- 文档名
- 片段位置
- 页码或来源路径
- 引用片段预览

---

## 十三、SSE 事件协议

### 13.1 统一事件结构

```json
{ "event": "<event_type>", "data": { "...": "..." }, "ts": 1741234567890 }
```

### 13.2 必须支持的事件

- `session_created`
- `assistant_delta`
- `tool_call_started`
- `tool_call_finished`
- `tool_approval_request`
- `tool_approval_resolved`
- `tool_error_feedback`
- `checkpoint_created`
- `final_response`
- `error`

### 13.3 前端消费原则

- 所有事件必须可重放
- 所有关键事件必须可视化
- 审批事件必须有超时处理

---

## 十四、前端产品要求

### 14.1 MVP 前端能力

- 会话列表
- 聊天主界面
- 工具调用时间线
- Level 2 审批弹窗
- RAG 引用展示
- Session 恢复与手动压缩

### 14.2 可视化重点

- 工具执行中
- 工具审批中
- 错误恢复中
- 已压缩 checkpoint

### 14.3 前端状态管理

前端至少要区分：

- 对话流状态
- 工具状态
- 审批状态
- 插件状态
- 会话元信息状态

---

## 十五、模块划分

```text
backend/
  api/
  runtime/
  memory/
  tools/
  sandbox/
  rag/
  plugins/
  skills/
  providers/
  channels/
  sessions/
  config/

frontend/
  app/
  components/
  features/
  stores/
```

### 15.1 后端核心模块

- `runtime/`
  - `thread_manager.py`
  - `session_task.py`
  - `prompt_assembler.py`
  - `run_loop.py`
  - `tool_router.py`
  - `tool_orchestrator.py`
- `memory/`
  - `stable_context.py`
  - `checkpoint_store.py`
  - `memory_extract.py`
- `plugins/`
  - `plugin_loader.py`
  - `plugin_registry.py`
- `providers/`
  - `base.py`
  - `openai_compatible.py`
  - `anthropic_compatible.py`

---

## 十六、非功能需求

### 16.1 安全

- 高危执行必须经过审批
- Shell 执行必须进入沙箱
- Linux 优先采用原生沙箱（bubblewrap）实现 `read-only` / `workspace-write` / `danger-full-access`
- macOS / Windows 的原生沙箱适配列为待做，不在本阶段交付
- 配置文件权限最小化
- 日志脱敏

### 16.2 可观察性

- 每轮请求都有 `request_id`
- 工具调用有耗时和结果分类
- SSE 事件可追踪

### 16.3 可维护性

- 模块边界清晰
- 文件结构稳定
- 配置和代码分离
- Prompt 模板独立管理

---

## 十七、与 Claude 项目对照后的借鉴结论

Newman 明确借鉴以下架构思想，但不照搬其具体实现：

### 应借鉴

- Tool/Skill/Plugin 分层
- 会话级 Permission Context
- Stable Context 与 Working History 分层
- Context Compaction 与 Checkpoint 机制
- 插件启停与热加载
- MCP 统一纳入工具注册表
- 后台调度事件注入会话

### 不照搬

- 与特定厂商绑定的 OAuth、远程桥接、内部 feature flag
- 重型 CLI/终端 UI 架构
- 复杂企业遥测和内部策略系统

---

## 十八、阶段性交付建议

### Phase 1：可用内核

- ThreadManager
- SessionTask
- PromptAssembler
- RunLoop
- ToolRouter
- ToolOrchestrator
- 5 个核心工具

### Phase 2：知识与记忆

- 文档解析
- RAG 检索
- Checkpoint 压缩
- Long-term Memory

### Phase 3：扩展生态

- Plugin Loader
- Skill Registry
- MCP 集成
- Scheduler

### Phase 4：产品化

- 完整前端体验
- 插件管理界面
- 企业 IM 接入

---

## 十九、验收标准

### P0 验收

- 新建会话、恢复会话、删除会话可用
- 核心 5 工具能被统一路由、统一执行、统一回写
- Level 2 审批闭环完成
- 会话压缩与恢复闭环完成
- RAG 端到端可用
- SSE 事件完整，前端能正确展示关键状态

### P1 验收

- 插件热加载稳定
- MCP 接入稳定
- Scheduler 能触发后台任务
- 长期记忆召回有效

---

## 二十、总结

Newman 的核心不是“接一个模型接口做聊天”，而是建立一个本地优先、能力透明、可治理、可恢复、可扩展的 Agent 运行时。

本版 PRD 的核心改进在于：

- 把运行时骨架说清楚
- 把 Tool/Skill/Plugin/MCP 边界说清楚
- 把权限和错误恢复从“附属能力”提升为“第一层能力”
- 把记忆与压缩从“实现细节”提升为产品机制

这将使 Newman 更适合长期演进为个人 AI 助手平台，而不是一次性 Demo。
