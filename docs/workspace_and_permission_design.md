# Newman Workspace 与权限设计

## 1. 文档目的

本文档定义 Newman 的目录划分、路径权限和对话维护边界。

本文档只描述目标逻辑要求，不展开优缺点分析。


## 2. 基本约束

- 系统采用单租户模式
- `runtime_workspace` 由配置文件指定，可以位于 Newman 项目目录之外
- `runtime_workspace` 面向 Newman 全面开放，可读、可写、可编辑、可执行
- 不做任何自动清理策略
- 用户可通过与 Newman 对话维护以下内容：
  - 记忆
  - 技能
  - 插件
  - 工具
- 代码区中除上述可维护目录外，其他内容默认只读


## 3. 目录模型

系统划分为三类目录：

1. 平台代码区
2. 平台数据区
3. 运行工作区

示例如下：

```text
/root/newman
├── backend/                         # 平台后端代码
├── frontend/                        # 平台前端代码
├── plugins/                         # 平台插件目录
├── skills/                          # 平台技能目录
├── docs/                            # 平台文档
├── newman.yaml                      # 平台配置
└── .env                             # 敏感环境配置

/root/newman/backend_data
├── memory/                          # Memory 文件
├── uploads/                         # 上传原件
├── knowledge/                       # 知识库解析产物
├── sessions/                        # 会话数据
├── audit/                           # 审计数据
├── chroma/                          # 向量索引
├── scheduler/                       # 调度数据
├── channels/                        # 渠道数据
└── mcp/                             # MCP 数据

/data/newman/runtime_workspace       # 实际工作区，由 paths.workspace 指定
└── ...                              # 目录结构由业务自行定义
```


## 4. 路径分类

### 4.1 A 类：全面开放读写目录

这类目录允许 Newman 通过对话执行读取、写入、编辑、创建、删除和运行任务。

- `paths.workspace` 指向的 `runtime_workspace`


### 4.2 B 类：平台可维护目录

这类目录允许 Newman 通过对话维护，但不属于 `runtime_workspace`。

- `backend_data/memory/`
- `skills/`
- `plugins/`
- `backend/tools/` 或其他明确指定的工具实现目录

这类目录用于满足以下能力：

- 维护记忆文件
- 创建、更新、删除 Skill
- 创建、更新、删除 Plugin
- 维护指定工具实现


### 4.3 C 类：平台只读目录

这类目录允许 Newman 读取、搜索和理解，但默认不允许写入。

- `backend/` 中除 B 类目录外的其他代码
- `frontend/`
- `docs/`
- `tests/`
- `scripts/`
- 其他仓库代码和文档目录


### 4.4 D 类：受保护目录

这类目录不属于普通对话维护范围。

- `.env`
- `newman.yaml`
- `backend_data/uploads/`
- `backend_data/chroma/`
- `backend_data/sessions/`
- `backend_data/audit/`
- `backend_data/postgres/`
- 其他运行时核心数据目录

对这类目录：

- 不允许普通对话直接写入
- 是否允许读取，由系统单独控制


## 5. 权限要求

### 5.1 读权限

Newman 应具备以下读权限：

- A 类目录：允许
- B 类目录：允许
- C 类目录：允许
- D 类目录：按系统控制，默认不纳入普通维护范围


### 5.2 写权限

Newman 应具备以下写权限：

- A 类目录：允许
- B 类目录：允许
- C 类目录：禁止
- D 类目录：禁止


### 5.3 创建与删除权限

Newman 应具备以下创建与删除权限：

- A 类目录：允许
- B 类目录：允许
- C 类目录：禁止
- D 类目录：禁止


## 6. 工具级权限要求

### 6.1 文件工具

`read_file`、`list_dir`、`search_files` 应支持：

- A 类目录读取
- B 类目录读取
- C 类目录读取

`write_file`、`edit_file` 应支持：

- A 类目录写入
- B 类目录写入
- C 类目录禁止写入
- D 类目录禁止写入


### 6.2 Terminal 工具

`terminal` 应满足以下要求：

- 默认工作目录为 `runtime_workspace`
- 在 A 类目录中允许读写执行
- 在 B 类目录中允许读写执行
- 在 C 类目录中只允许只读访问
- 在 D 类目录中禁止普通写入


### 6.3 审批要求

以下动作即使发生在 A 类或 B 类目录中，也应保留审批：

- 删除目录
- 批量覆盖文件
- 运行未知 shell 命令
- 创建或修改插件执行入口
- 创建或修改工具实现
- 修改记忆、技能、插件、工具之外的代码路径


## 7. 目录职责

### 7.1 runtime_workspace

`runtime_workspace` 是 Newman 的主工作区。

职责：

- 用户任务文件处理
- 代码生成与修改
- 临时文件处理
- 导出结果生成
- 会话中需要持续操作的业务文件处理

要求：

- 对 Newman 全面开放
- 不承担平台核心配置与平台核心数据的持久化职责


### 7.2 memory

`backend_data/memory/` 用于存放 Memory 文件。

要求：

- 允许通过对话维护
- 允许创建、更新和覆盖 Memory 内容
- 不纳入普通业务工作区


### 7.3 skills

`skills/` 用于存放平台 Skill。

要求：

- 允许通过对话创建、更新、删除 Skill
- Skill 生成结果直接落到 `skills/`
- 新 Skill 写入后应可被系统重新发现并加载


### 7.4 plugins

`plugins/` 用于存放平台 Plugin。

要求：

- 允许通过对话创建、更新、删除 Plugin
- Plugin 写入后应可被系统重新发现并加载
- Plugin 是否启用仍按插件启用机制控制


### 7.5 tools

`backend/tools/` 或指定工具目录用于存放工具实现。

要求：

- 允许通过对话维护指定工具代码
- 工具变更后应可被系统重新发现或重新注册
- 工具目录之外的其他后端代码仍保持只读


### 7.6 代码区其他路径

代码区中除 `skills/`、`plugins/`、`backend/tools/` 外的其他路径默认只读。

要求：

- 允许搜索和阅读
- 不允许直接写入
- 不允许通过普通对话进行覆盖式修改


## 8. 上传与知识文件要求

### 8.1 上传原件

上传原件继续保留在：

- `backend_data/uploads/chat/`
- `backend_data/uploads/knowledge/`

要求：

- 上传原件不作为普通工作区
- 原件目录不纳入普通写权限


### 8.2 工作副本

当文件需要被 Newman 持续编辑或运行时，应复制到 `runtime_workspace`。

要求：

- 原件和工作副本分离
- Newman 在 `runtime_workspace` 中操作工作副本


## 9. 配置要求

### 9.1 workspace 配置

示例配置：

```yaml
paths:
  workspace: "/data/newman/runtime_workspace"
```

要求：

- `workspace` 不要求位于 `/root/newman` 下
- `workspace` 必须是独立目录
- `workspace` 不应直接等于项目根目录


### 9.2 额外路径授权

系统应支持在 `workspace` 之外为 Newman 显式授予额外路径权限。

最少应支持两类额外授权：

- 额外可写路径
- 额外只读路径

示例逻辑如下：

```yaml
permissions:
  writable_paths:
    - "/data/newman/runtime_workspace"
    - "/root/newman/backend_data/memory"
    - "/root/newman/skills"
    - "/root/newman/plugins"
    - "/root/newman/backend/tools"
  readable_paths:
    - "/root/newman/backend"
    - "/root/newman/frontend"
    - "/root/newman/docs"
    - "/root/newman/tests"
    - "/root/newman/scripts"
  protected_paths:
    - "/root/newman/.env"
    - "/root/newman/newman.yaml"
    - "/root/newman/backend_data/uploads"
    - "/root/newman/backend_data/chroma"
    - "/root/newman/backend_data/sessions"
    - "/root/newman/backend_data/audit"
```

上面是逻辑模型，用于定义权限边界。


## 10. 对话维护能力要求

### 10.1 维护记忆

用户通过对话应能够：

- 更新 Memory 内容
- 覆盖 Memory 文件
- 查询当前 Memory 内容


### 10.2 维护 Skill

用户通过对话应能够：

- 创建 Skill
- 更新 Skill
- 删除 Skill
- 使新 Skill 进入系统可发现范围


### 10.3 维护 Plugin

用户通过对话应能够：

- 创建 Plugin
- 更新 Plugin
- 删除 Plugin
- 控制 Plugin 的启用与停用


### 10.4 维护 Tool

用户通过对话应能够：

- 创建 Tool
- 更新 Tool
- 删除 Tool
- 使新 Tool 进入系统可发现或可注册范围


### 10.5 阅读其他代码区

用户通过对话应能够：

- 阅读平台其他代码
- 搜索平台其他代码
- 基于只读代码理解系统结构

用户通过对话不应能够：

- 直接修改未授权代码路径


## 11. 实施要求

为满足本方案，系统应具备以下能力：

- `workspace` 与额外授权路径分离
- 文件工具支持“可写路径”和“只读路径”双 allowlist
- `terminal` 支持对 A 类和 B 类目录写入，对 C 类目录只读
- 高风险动作统一审批
- Skill、Plugin、Tool 变更后可重新加载
- 不对 `runtime_workspace` 和上传原件做自动清理


## 12. 最终规则

最终按以下规则执行：

1. `runtime_workspace` 是 Newman 的主工作区，全面开放
2. `backend_data/memory/`、`skills/`、`plugins/`、`backend/tools/` 是平台可维护目录
3. 代码区其他路径默认只读
4. `.env`、`newman.yaml`、上传原件目录和核心运行数据目录默认受保护
5. 用户可通过对话维护记忆、技能、插件和工具
6. 用户可通过对话阅读其他代码区，但不能直接修改未授权路径
