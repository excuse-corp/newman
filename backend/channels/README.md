# Channels

当前已落地的是 Phase 4 基线能力：

- `feishu` 与 `wecom` 两个 Channel Adapter
- webhook 基础验签
- IM 用户到 Newman session 的映射
- webhook 消息转会话消息，再把最终答复转回 channel payload

当前边界：

- 还没有真正调用飞书/企微发消息 API
- 当前返回的是标准化响应 payload，便于本地联调和后续接真实发送端
