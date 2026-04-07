> 这是运行时模板文件。
> 工具执行失败后，后端会直接读取并渲染本文件；它不是一次性初始化模板。

上一步执行失败了。

请把下面的信息视为“下一轮推理的重要输入”，而不是普通日志。

Tool: {{ tool }}
Action: {{ action }}
Category: {{ category }}
Error code: {{ error_code }}
Severity: {{ severity }}
Risk level: {{ risk_level }}
Recovery class: {{ recovery_class }}
Exit code: {{ exit_code }}
Retryable: {{ retryable }}
Attempt: {{ attempt_count }}
Frontend message: {{ frontend_message }}

## 失败摘要

{{ summary }}

## 关键输出

{{ key_output }}

## 下一步建议

{{ recommended_next_step }}

## 处理要求

- 先理解失败原因，再决定下一步
- 不要机械重复同一个失败动作
- 如果错误明显是暂时性的，才考虑重试
- 如果错误表明参数、路径、权限、依赖或上下文有问题，应优先修正这些问题
- 如果用户需要知道风险或阻塞点，应在后续回复中明确说明
