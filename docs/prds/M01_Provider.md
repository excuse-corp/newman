# M01 Provider — 模型接入层

> Newman 模块 PRD · Phase 1 · 预估 5 工作日

---

## 一、模块目标

提供统一的 LLM 接入抽象，支持 OpenAI-compatible 和 Anthropic-compatible 接口，实现模型无关的调用层。

---

## 二、功能范围

### ✅ 包含

- Provider 基类抽象（BaseProvider）
- OpenAI-compatible Adapter（支持 streaming / non-streaming）
- Anthropic-compatible Adapter
- 模型配置管理（model name, endpoint, API key, parameters）
- Token 计数估算器（TokenEstimator）
- 统一响应结构规范化

### ❌ 不包含

- 本地模型推理引擎
- 模型路由与负载均衡
- 计费与配额管理

---

## 三、前置依赖

无（基础模块，无前置依赖）

---

## 四、文件结构

```text
providers/
  base.py                   # Provider 基类
  openai_compatible.py      # OpenAI-compatible Adapter
  anthropic_compatible.py   # Anthropic-compatible Adapter
  token_estimator.py        # Token 计数估算
config/
  models.yaml               # 模型配置
```

---

## 五、核心接口设计

### BaseProvider 抽象

```python
class BaseProvider(ABC):
    @abstractmethod
    async def chat(self, messages, tools=None, **kwargs) -> ProviderResponse: ...

    @abstractmethod
    async def chat_stream(self, messages, tools=None, **kwargs) -> AsyncIterator[ProviderChunk]: ...

    @abstractmethod
    def estimate_tokens(self, messages) -> int: ...
```

### ProviderResponse 统一结构

```python
@dataclass
class ProviderResponse:
    content: str
    tool_calls: list[ToolCall] | None
    usage: TokenUsage
    model: str
    finish_reason: str
```

---

## 六、验收标准

1. 能通过配置切换 OpenAI / Anthropic 接口而无需改业务代码
2. streaming 和 non-streaming 模式均可用
3. TokenEstimator 估算误差 < 10%
4. 接口超时、认证失败等异常能被结构化捕获
5. 单元测试覆盖率 ≥ 80%

---

## 七、技术备注

- OpenAI-compatible 需兼容 DeepSeek、Qwen 等本地部署的 OpenAI 格式服务
- Anthropic-compatible 需支持 system prompt 和 tool_use 格式差异
- Token 估算采用 tiktoken 或 provider 返回的 usage 字段
