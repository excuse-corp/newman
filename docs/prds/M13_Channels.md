# M13 Channels — 企业 IM 接入

> Newman 模块 PRD · Phase 4 · 预估 8 工作日

---

## 一、模块目标

实现企业 IM（飞书、企业微信）的 Channel Adapter，将 IM 消息转换为 Newman 会话。

---

## 二、功能范围

### ✅ 包含

- Channel Adapter 抽象层
- 飞书 Adapter（P0）
- 企业微信 Adapter（P0）
- 钉钉 Adapter（P1）
- 消息格式转换
- Webhook 回调处理

### ❌ 不包含

- 多租户
- 消息广播

---

## 三、前置依赖

- M06 API & SSE（通过 API 创建会话和发送消息）

---

## 四、文件结构

```text
channels/
  base.py                 # Channel Adapter 基类
  feishu.py               # 飞书 Adapter
  wecom.py                # 企业微信 Adapter
  dingtalk.py             # 钉钉 Adapter
  message_converter.py    # 消息格式转换
  webhook_handler.py      # Webhook 处理
```

---

## 五、核心设计

### Channel Adapter 抽象

```python
class BaseChannel(ABC):
    @abstractmethod
    async def receive_message(self, raw_event: dict) -> ChannelMessage: ...

    @abstractmethod
    async def send_response(self, channel_id: str, response: str, format: str = "text") -> bool: ...

    @abstractmethod
    def verify_webhook(self, request) -> bool: ...
```

### 消息流转

```text
IM 平台 Webhook
  ↓
WebhookHandler 签名验证
  ↓
Channel Adapter 解析消息
  ↓
MessageConverter 转换为 Newman 格式
  ↓
调用 Newman API 创建/继续会话
  ↓
获取响应
  ↓
MessageConverter 转换为 IM 平台格式
  ↓
Channel Adapter 发送响应
```

### 消息格式映射

| 类型 | Newman 格式 | 飞书 | 企微 |
|------|-------------|------|------|
| 纯文本 | text | text | text |
| 富文本 | markdown | post | markdown |
| 文件 | file attachment | file | media |
| 图片 | image attachment | image | image |

---

## 六、验收标准

1. 飞书/企微消息能触发 Newman 会话并返回响应
2. 支持富文本消息格式转换
3. Webhook 回调签名验证通过
4. IM 平台超时时优雅降级（返回"处理中"提示）

---

## 七、技术备注

- 飞书使用开放平台事件订阅 + 消息卡片
- 企微使用回调模式 + 主动推送
- 钉钉使用 Stream 模式
- 每个 IM 用户映射一个 Newman session_id（通过 user_id 关联）
