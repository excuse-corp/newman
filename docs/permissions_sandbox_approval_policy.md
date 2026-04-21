# 权限、沙箱、审批 Policy 的关系

## 1. 一句话说明

- 权限决定“能不能访问这个路径”
- 沙箱决定 `terminal` “在系统层面实际能碰到什么”
- 审批 policy 决定“本来允许的动作，要不要人工确认”

这三层不是一回事。


## 2. 谁管什么

### 2.1 权限

权限只关心路径边界。

系统把路径分成四类：

- A 类：`runtime_workspace`，全面开放读写
- B 类：平台可维护目录，例如 `backend_data/memory/`、`skills/`、`plugins/`、`backend/tools/`
- C 类：平台只读目录
- D 类：受保护目录

路径权限规则：

- A/B：可读可写
- C：只读
- D：受保护，不属于普通维护范围

权限层回答的问题是：

- 这个文件能不能读
- 这个文件能不能写
- 这个目录能不能删


### 2.2 沙箱

沙箱主要作用在 `terminal`。

原因是：

- `read_file`、`write_file`、`edit_file` 这类工具本身就直接处理文件路径
- `terminal` 会执行 shell 命令，需要系统层面的硬隔离

沙箱层回答的问题是：

- `terminal` 实际运行时，哪些目录被挂进去
- 哪些目录只读
- 哪些目录可写
- 网络是否开放

因此：

- 权限允许写，不代表 `terminal` 就一定能写
- 只有沙箱也把这个目录挂成可写，`terminal` 才能真正写入


### 2.3 审批 policy

审批 policy 只负责风险控制。

它不负责定义路径边界，也不能扩大权限。

审批层回答的问题是：

- 这个动作虽然允许，但要不要人工确认
- 这个命令是不是高风险
- 这个改动要不要拦下来

例如：

- 写 `skills/` 可能是允许的，但仍然需要审批
- 批量覆盖文件可能是允许的，但仍然需要审批
- `rm -rf /` 这种命令即使用户想批，也应该直接拒绝


## 3. 正确的执行顺序

系统应按下面的顺序处理：

1. 先做权限判断
2. 再做审批判断
3. 最后执行工具
4. 如果是 `terminal`，执行时再受沙箱硬约束

也就是说：

```text
权限 -> 审批 -> 工具执行
               \
                terminal 再经过沙箱
```


## 4. 为什么要先做权限判断

因为“没有权限”的动作，不应该进入审批。

例如：

- 修改 `.env`
- 修改 `newman.yaml`
- 修改未授权代码目录
- 修改受保护运行数据

这类动作应该直接拒绝，而不是弹出“是否批准”。

否则用户会误以为：

- 只要点同意，就能突破系统边界

这不是审批该做的事。


## 5. Level 1 / Level 2 在这里是什么位置

当前系统里的 `level1` 和 `level2` 属于审批 policy。

它们的职责应理解为：

- `Level 1`：绝对拒绝
- `Level 2`：允许但需要人工审批

它们不负责判断路径是不是可写。


## 6. 一些直白例子

### 例子 1：写 `runtime_workspace`

- 权限：允许
- 审批：可能需要，也可能不需要，取决于动作风险
- `terminal`：如果沙箱把 `runtime_workspace` 挂成可写，就能真正写入


### 例子 2：写 `skills/`

- 权限：允许，因为它是平台可维护目录
- 审批：通常建议走审批
- `terminal`：只有沙箱把 `skills/` 挂成可写，`terminal` 才能写
- 文件工具：也需要被授权写 `skills/`


### 例子 3：写普通 `frontend/` 代码

- 权限：不允许，因为它属于只读代码区
- 审批：不进入审批
- 结果：直接拒绝


### 例子 4：写 `.env`

- 权限：不允许，因为它属于受保护目录
- 审批：不进入审批
- 结果：直接拒绝


### 例子 5：执行 `rm -rf /`

- 权限：这不是单一路径问题
- 审批：命中 `Level 1`
- 结果：直接拒绝


## 7. 最终原则

最终应遵守以下原则：

1. 权限定义边界
2. 沙箱提供 `terminal` 的硬隔离
3. 审批只处理风险，不处理边界
4. 审批不能扩大权限
5. 无权限动作直接拒绝
6. 有权限但高风险的动作才进入审批


## 8. 常见审批 reason code

下面这些 reason code 可以直白理解：

- `maintain_memory`：正在修改记忆目录
- `maintain_skill`：正在修改 `skills/`
- `maintain_plugin`：正在修改 `plugins/`
- `maintain_tool`：正在修改 `backend/tools/`
- `terminal_mutation_or_unknown`：`terminal` 执行的是写入类命令，或者命令风险不明确
- `process_spawn`：`terminal` 看起来要启动常驻进程或后台进程
- `danger_full_access_terminal`：当前 `terminal` 运行在 `danger-full-access` 模式

下面这些 reason code 不进入审批，而是直接拒绝：

- `read_outside_readable_paths`
- `write_outside_writable_paths`
- `read_protected_path`
- `write_protected_path`
- `mcp_path_outside_workspace`
- `mcp_path_protected`
- `terminal_read_outside_readable_paths`
- `terminal_write_outside_writable_paths`
- `terminal_read_protected_path`
- `terminal_write_protected_path`
- `terminal_write_readonly_path`
