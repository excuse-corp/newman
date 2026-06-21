Feishu + cc-connect + Codex 可复用实施方案

## 1. 目标

目标是把飞书机器人接到本机 Codex，让用户在飞书里发文字任务，由 Codex 在指定项目目录执行，并把最终结果回到飞书。

这套方案适合：

- 一个或多个本地代码仓库
- 只需要飞书文字下任务
- 不要求把中间推理过程持续展示给用户
- 希望按项目、按群聊话题隔离上下文

推荐形态：

- 一个飞书机器人应用对应一个项目
- 一个项目主群对应一个项目
- 群里一条新的 `@机器人` 顶层消息对应一个新任务 session
- 回复这条消息则继续同一个 session


## 2. 总体架构

```text
飞书用户
  -> 飞书自建应用 / 机器人
  -> cc-connect
  -> Codex CLI
  -> 本地项目目录
  -> Codex 输出最终结果
  -> cc-connect 回复飞书
```

职责划分：

- 飞书：消息入口、用户身份、群聊上下文
- cc-connect：平台接入、项目路由、session 管理、消息转发
- Codex：读取项目、运行命令、改代码、生成最终回复
- Git 仓库目录：Codex 实际工作的工作区


## 3. 核心连接关系

### 3.1 飞书如何连到 cc-connect

`cc-connect` 负责接飞书平台。配置好飞书应用的 `app_id` / `app_secret` 后，`cc-connect` 会建立与飞书的长连接并接收入站消息，不需要公网 webhook。

飞书里的消息不是直接发给 Codex，而是先到 `cc-connect`，由它决定：

- 这条消息属于哪个 project
- 这条消息属于哪个 session
- 是否允许这个用户 / 这个群使用机器人

### 3.2 cc-connect 如何连到 Codex

`cc-connect` 的 `codex` agent 使用的是本机 Codex CLI。

当前默认实现是：

- 首条消息：`codex exec --json`
- 同一 session 后续消息：`codex exec resume <thread_id>`

也就是说，`cc-connect` 不会为同一 session 的每条消息都新建一个 Codex 会话，而是复用同一个底层 Codex thread。

### 3.3 Codex 如何连到项目目录

每个 `project` 配一个 `work_dir`：

```toml
[projects.agent.options]
work_dir = "/root/newman"
```

Codex 收到这个 project 的任务后，就会在该目录下读代码、跑命令、改文件。


## 4. session 模型

这是整套方案最容易混淆的部分。

### 4.1 单聊机器人

默认规则：

```text
同一个飞书单聊窗口 = 一个 cc-connect session = 一个底层 Codex session
```

也就是说，你在同一个机器人单聊窗口里连续发消息，默认是在续同一个 session。

### 4.2 群聊机器人

推荐打开：

```toml
thread_isolation = true
```

打开后，群聊规则变成：

```text
一条新的顶层 @机器人 消息 = 一个新 session
回复该消息 = 同一个 session
```

所以群里的正确使用姿势是：

```text
@机器人 修复登录接口
  -> 新 session

回复这条消息：继续跑测试
  -> 同一个 session

再新发一条顶层消息：@机器人 优化报表查询
  -> 另一个新 session
```

### 4.3 reply_to_trigger 的作用

```toml
reply_to_trigger = true
```

这个开关只决定机器人回消息时，飞书界面上是不是显示为“回复消息 / 话题回复”。

它 **不决定 session 是否新建**。

- `true`：机器人回复会挂在触发消息下面，看起来像话题回复
- `false`：机器人发普通群消息，不挂回复

session 是否新建，仍然由 `thread_isolation` 和“是不是新顶层消息”决定。


## 5. 项目模型

推荐使用：

```text
一个飞书机器人应用 = 一个项目
一个项目群 = 一个项目入口
一个顶层任务消息 = 一个 session
```

例如：

```text
dataman-bot -> /root/dataman
envoys-bot  -> /root/Envoys
newman-bot  -> /root/newman
fileman-bot -> /root/fileman
```

这种方式的优点：

- 项目边界清楚
- 权限容易收口
- 群和代码目录不会串
- 出问题时排查简单

如果项目数量不多，这是最稳的方案。


## 6. 推荐部署模式

推荐模式是：

- 多个飞书应用
- 一个 `cc-connect` 进程
- `config.toml` 中配置多个 `[[projects]]`

也就是：

```text
一个 cc-connect 服务
  -> 托管多个 project
  -> 每个 project 绑定自己的飞书 app 和 work_dir
```

这样既保留了“一机器人一项目”的清晰边界，又不需要维护多个后台进程。


## 7. 目录与运行文件

推荐目录：

```text
~/.cc-connect/config.toml      # cc-connect 主配置
~/.cc-connect/logs/...         # cc-connect 日志
~/.codex/...                   # Codex 认证、历史、session transcript
```

常见路径示例：

```text
/root/.cc-connect/config.toml
/root/.cc-connect/logs/cc-connect.log
/root/.codex/sessions/
```

说明：

- `cc-connect` 的配置和状态文件不需要放进项目仓库
- 项目仓库只作为 `work_dir`
- 只有当你在飞书里让 Codex 修改项目时，项目目录本身才会发生变更


## 8. 实施前提

### 8.1 服务器前提

需要：

- 已安装 Codex CLI
- Codex 已可正常运行
- 服务器可以访问飞书开放平台
- 服务器可以访问 Codex 所需的模型提供方

先用本机命令验证 Codex：

```bash
codex exec --skip-git-repo-check --sandbox read-only --cd /path/to/repo "只回复：smoke test ok"
```

### 8.2 飞书应用前提

每个项目准备一个飞书自建应用，并开启机器人能力。

至少需要准备：

- `app_id`
- `app_secret`

至少需要确认这些权限已经开通并发布：

- 接收消息相关权限
- 机器人发送消息权限，例如 `im:message:send_as_bot`

如果权限没开全，典型现象是：

- 机器人能收到消息
- 但无法回复消息


## 9. 配置模板

下面是一份可直接复用的模板。注意这里全部使用占位符，不要把真实密钥提交进仓库。

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
# backend = "exec"        # 推荐默认
# backend = "app_server"  # 需要更强交互能力时再切

[[projects.platforms]]
type = "feishu"

[projects.platforms.options]
app_id = "cli_xxx"
app_secret = "sec_xxx"
allow_from = "ou_xxx"
allow_chat = "oc_xxx"          # 可选；群定型后建议收口
enable_feishu_card = false
thread_isolation = true
reply_to_trigger = true
done_emoji = "none"

[[projects]]
name = "dataman"
filter_external_sessions = true

[projects.agent]
type = "codex"

[projects.agent.options]
work_dir = "/root/dataman"
mode = "full-auto"

[[projects.platforms]]
type = "feishu"

[projects.platforms.options]
app_id = "cli_xxx"
app_secret = "sec_xxx"
allow_from = "ou_xxx"
enable_feishu_card = false
thread_isolation = true
done_emoji = "none"
```


## 10. 启动方式

### 10.1 前台启动

```bash
cc-connect -config ~/.cc-connect/config.toml
```

### 10.2 后台服务

```bash
cc-connect daemon install --config ~/.cc-connect/config.toml
cc-connect daemon start
cc-connect daemon status --config ~/.cc-connect/config.toml
```

日志查看：

```bash
cc-connect daemon logs --config ~/.cc-connect/config.toml -n 100
```


## 11. 日常使用方式

### 11.1 单聊机器人

直接给机器人发消息：

```text
修复登录接口报错
继续跑测试
总结改动
```

这默认会走同一个 session。

### 11.2 群聊机器人

推荐操作规则：

1. 新任务：发一条新的顶层 `@机器人` 消息
2. 继续同一任务：回复这条消息
3. 新的独立任务：再发一条新的顶层 `@机器人` 消息

示例：

```text
@newman-bot 修复登录接口报错

回复这条消息：
继续跑测试

再新发一条：
@newman-bot 优化报表查询
```

### 11.3 管理命令

常见命令：

```text
/whoami
/new 新会话名
/list
/switch 1
/current
/stop
```

说明：

- 单聊里通常不需要频繁 `/new`
- 群聊里更推荐直接用“新的顶层 @机器人 消息”来开新 session


## 12. 底层 Codex session 的可见性

这点需要单独说明。

`cc-connect` 使用的是 Codex 的 **non-interactive** 模式，也就是 `codex exec`。

因此：

- 飞书里已经成功执行的任务，底层确实有 Codex session transcript
- 但它不一定自动出现在你平时看到的交互式会话列表里

底层 transcript 通常会落在：

```text
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
```

如果要查看这类 session，可以用：

```bash
codex resume --all --include-non-interactive
```

或者按具体 session ID 继续：

```bash
codex exec resume <SESSION_ID> "继续"
```


## 13. 安全与权限建议

至少要做这些收口：

1. `allow_from`

只允许指定飞书用户给机器人下任务。

2. `allow_chat`

群稳定后，把项目机器人限制到固定群。

3. 不允许消息直接传本地任意路径

项目目录必须写死在 `work_dir`，不要让用户从飞书里传目录路径。

4. 按项目隔离机器人

不要让一个机器人同时控制多个不相干项目，除非你愿意承担更高的误操作风险。

5. 控制执行模式

- `mode = "suggest"`：只读，更稳
- `mode = "full-auto"`：可以改代码，适合明确授权后的项目机器人


## 14. 已知行为与边界

### 14.1 群里不 `@机器人` 为什么没反应

默认行为。群消息通常必须 `@机器人` 才会进入处理。

如果开启 `group_reply_all = true`，机器人会响应群里所有消息，一般不建议。

### 14.2 为什么群里会显示话题回复

因为默认：

```toml
reply_to_trigger = true
```

这是显示层行为，不影响 session 规则。

### 14.3 为什么飞书有回复，但在 Codex 里没看到“新会话”

因为这类任务通常是：

- 进入非交互 `codex exec` session
- 同一飞书 session 会继续 `codex exec resume`

所以它是复用底层 thread，而不是每条飞书消息都新开一个交互式会话。

### 14.4 同一项目多个 session 是否会同时改同一目录

会。

`thread_isolation` 隔离的是上下文，不是文件系统。多个 session 仍可能同时操作同一个 `work_dir`。

如果后续要支持同项目多 session 并发改代码，建议升级为：

```text
一个 session 对应一个 git worktree
```

这是第二阶段能力，不是第一版必需项。


## 15. 推荐落地步骤

### 第一阶段：跑通单项目

1. 安装 Codex CLI
2. 验证 `codex exec` 可用
3. 安装 `cc-connect`
4. 创建一个飞书应用
5. 配置一个 project
6. 单聊测试 `/whoami`
7. 群聊测试 `@机器人`

### 第二阶段：扩展到多项目

1. 每个项目新建一个飞书应用
2. 在 `config.toml` 增加多个 `[[projects]]`
3. 每个项目配置独立 `work_dir`
4. 每个项目配置独立群
5. 收紧 `allow_from` / `allow_chat`

### 第三阶段：强化隔离

按需要增加：

- 每项目独立日志
- 独立运行账号
- 独立 systemd 服务
- session 级 worktree


## 16. 故障排查清单

### 16.1 机器人能收消息但不能回复

优先检查飞书应用是否开通并发布了机器人发送消息权限。

### 16.2 单聊正常，群里没反应

检查：

- 机器人是否已加入该群
- 是否 `@机器人`
- `allow_chat` 是否限制了别的群

### 16.3 飞书消息到了，但 Codex 没执行

检查：

- `cc-connect` 服务是否运行
- `work_dir` 是否存在
- 本机 `codex exec` 是否可用
- Codex 认证或 provider 配置是否失效

### 16.4 飞书群里多个任务串上下文

检查是否启用了：

```toml
thread_isolation = true
```

如果没开，群里的多任务容易混进同一个 session。


## 17. 参考链接

- Codex CLI：<https://developers.openai.com/codex/cli>
- Codex non-interactive mode：<https://developers.openai.com/codex/noninteractive>
- Codex CLI reference：<https://developers.openai.com/codex/cli/reference>
- Codex app-server：<https://developers.openai.com/codex/app-server>
- cc-connect 仓库：<https://github.com/chenhg5/cc-connect>


## 18. 结论

这套链路的本质是：

```text
飞书负责入口
cc-connect 负责路由和 session
Codex 负责执行
项目目录负责承载真实改动
```

如果要长期稳定使用，最推荐的组织方式是：

```text
一个飞书机器人应用 = 一个项目
一个项目群 = 一个项目入口
一条新的顶层 @机器人 消息 = 一个新 session
回复该消息 = 继续同一个 session
```

这已经足够支撑多项目、可控权限和清晰的上下文边界。
