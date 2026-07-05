# 飞书接入指南：通过 cc-connect 连接 Codex

本文说明如何把飞书机器人接到本机 Codex，让用户在飞书里发任务，由 Codex 在指定项目目录执行，并把结果回复到飞书。

推荐用法：

- Windows / 服务器上运行 `cc-connect`
- 每个项目准备一个飞书机器人应用
- 每个项目绑定一个固定代码目录 `work_dir`
- 群聊中一条新的顶层 `@机器人` 消息代表一个新任务
- 回复这条消息代表继续同一个任务

## 1. 工作链路

```text
飞书用户
  -> 飞书自建应用 / 机器人
  -> cc-connect
  -> Codex CLI
  -> 项目目录
  -> 飞书回复
```

职责：

- 飞书：消息入口、用户身份、群聊上下文
- cc-connect：接收飞书消息、路由项目、管理 session
- Codex：读取项目、运行命令、修改代码、生成最终回复
- 项目目录：Codex 实际工作的本地仓库

## 2. 接入前准备

服务器需要：

- 已安装 Codex CLI
- Codex 已完成登录或模型配置
- 已安装 cc-connect
- 服务器能访问飞书开放平台
- 服务器能访问 Codex 使用的模型服务

飞书侧需要：

- 创建飞书自建应用
- 开启机器人能力
- 获取 `app_id` 和 `app_secret`
- 开通并发布接收消息、机器人发送消息等权限
- 把机器人加入目标单聊或群聊

先验证 Codex CLI 可用：

```bash
codex exec --skip-git-repo-check --sandbox read-only --cd /path/to/repo "只回复：smoke test ok"
```

如果这一步失败，先修 Codex 登录、模型配置或项目路径。

## 3. 推荐配置方式

建议：

```text
一个飞书机器人应用 = 一个项目
一个项目群 = 一个项目入口
一个 work_dir = 一个本地代码仓库
```

示例：

```text
newman-bot -> /root/newman
dataman-bot -> /root/dataman
fileman-bot -> /root/fileman
```

这样项目边界清楚，权限容易收口，问题也更容易排查。

## 4. 配置文件

推荐把配置放在：

```text
~/.cc-connect/config.toml
```

单项目模板：

```toml
language = "zh"

[log]
level = "info"

[display]
mode = "quiet"
thinking_messages = false
tool_messages = false
reply_footer = false
show_context_indicator = false

[stream_preview]
enabled = false

[instant_reply]
enabled = false

[queue]
max_depth = 5

[[projects]]
name = "newman"
filter_external_sessions = true

[projects.agent]
type = "codex"

[projects.agent.options]
work_dir = "/root/newman"
mode = "full-auto"
# mode = "suggest"    # 只读建议模式，更稳
# mode = "full-auto" # 可自动改代码，适合已授权项目

[[projects.platforms]]
type = "feishu"

[projects.platforms.options]
app_id = "cli_xxx"
app_secret = "sec_xxx"
allow_from = "ou_xxx"
allow_chat = "oc_xxx"
enable_feishu_card = false
thread_isolation = true
reply_to_trigger = true
done_emoji = "none"
```

关键字段：

- `work_dir`：Codex 实际工作的项目目录，必须写死，不要让飞书消息传入任意路径
- `mode`：`suggest` 为只读建议，`full-auto` 允许改代码
- `allow_from`：允许使用机器人的飞书用户
- `allow_chat`：允许使用机器人的群；群固定后建议配置
- `thread_isolation = true`：群聊中按消息话题隔离任务上下文
- `reply_to_trigger = true`：机器人回复挂在触发消息下，方便看任务线程

多项目时，在同一个 `config.toml` 里增加多个 `[[projects]]`，每个项目配置独立的飞书应用和 `work_dir`。

## 5. 启动服务

前台启动：

```bash
cc-connect -config ~/.cc-connect/config.toml
```

安装为后台服务：

```bash
cc-connect daemon install --config ~/.cc-connect/config.toml
cc-connect daemon start
cc-connect daemon status --config ~/.cc-connect/config.toml
```

查看日志：

```bash
cc-connect daemon logs --config ~/.cc-connect/config.toml -n 100
```

常见文件位置：

```text
~/.cc-connect/config.toml
~/.cc-connect/logs/
~/.codex/sessions/
```

## 6. 飞书里如何使用

### 单聊

直接给机器人发消息：

```text
修复登录接口报错
继续跑测试
总结改动
```

同一个单聊窗口默认续同一个 session。

### 群聊

推荐规则：

1. 新任务：发新的顶层 `@机器人` 消息
2. 继续任务：回复这条消息
3. 新独立任务：再发新的顶层 `@机器人` 消息

示例：

```text
@newman-bot 修复登录接口报错

回复这条消息：
继续跑测试

再新发一条：
@newman-bot 优化报表查询
```

如果群聊里多个任务串上下文，先检查是否配置了：

```toml
thread_isolation = true
```

## 7. 常用管理命令

可在飞书里发送：

```text
/whoami
/new 新会话名
/list
/switch 1
/current
/stop
```

建议：

- 单聊通常不需要频繁 `/new`
- 群聊优先用“新的顶层 @机器人 消息”开启新任务

## 8. 安全建议

至少做这些限制：

- 配置 `allow_from`，只允许指定用户下任务
- 群稳定后配置 `allow_chat`，限制固定群
- 每个项目使用独立机器人应用
- `work_dir` 写死为项目目录，不允许从飞书消息传路径
- 未明确授权自动改代码前，使用 `mode = "suggest"`

注意：`thread_isolation` 只隔离上下文，不隔离文件系统。多个 session 仍可能同时修改同一个 `work_dir`。如果需要强隔离，后续应升级为每个 session 一个 git worktree。

## 9. Codex Session 说明

cc-connect 默认通过非交互模式调用 Codex：

```text
codex exec --json
codex exec resume <thread_id>
```

因此飞书里完成的任务会有 Codex transcript，但不一定出现在你平时的交互式会话列表里。

查看所有 session：

```bash
codex resume --all --include-non-interactive
```

继续指定 session：

```bash
codex exec resume <SESSION_ID> "继续"
```

transcript 通常位于：

```text
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
```

## 10. 故障排查

### 机器人能收到消息但不能回复

检查飞书应用是否已开通并发布机器人发送消息权限，例如 `im:message:send_as_bot`。

### 单聊正常，群里没反应

检查：

- 机器人是否已加入该群
- 群消息是否 `@机器人`
- `allow_chat` 是否配置成了其他群

### 飞书消息到了，但 Codex 没执行

检查：

- `cc-connect` 是否运行
- `work_dir` 是否存在
- `codex exec` 是否可用
- Codex 登录、模型配置或 provider 是否失效

### 多个群任务串上下文

检查：

```toml
thread_isolation = true
```

群聊里继续同一任务时，要“回复原任务消息”，不要重新发顶层消息。

## 11. 推荐落地步骤

单项目先跑通：

1. 安装并验证 Codex CLI
2. 安装 cc-connect
3. 创建飞书自建应用并开启机器人
4. 配置 `~/.cc-connect/config.toml`
5. 前台启动 cc-connect
6. 单聊测试 `/whoami`
7. 群聊测试 `@机器人`
8. 确认可用后安装为后台服务

多项目扩展：

1. 每个项目创建独立飞书应用
2. 每个项目配置独立 `[[projects]]`
3. 每个项目绑定独立 `work_dir`
4. 每个项目配置独立群和 `allow_chat`
5. 收紧 `allow_from`

## 12. 参考链接

- Codex CLI：<https://developers.openai.com/codex/cli>
- Codex non-interactive mode：<https://developers.openai.com/codex/noninteractive>
- Codex CLI reference：<https://developers.openai.com/codex/cli/reference>
- cc-connect：<https://github.com/chenhg5/cc-connect>

## 13. 总结

这套接入方式的核心是：

```text
飞书负责入口
cc-connect 负责路由和 session
Codex 负责执行
项目目录承载真实改动
```

长期使用时，最推荐：

```text
一个飞书机器人应用 = 一个项目
一个项目群 = 一个项目入口
一条新的顶层 @机器人 消息 = 一个新 session
回复该消息 = 继续同一个 session
```
