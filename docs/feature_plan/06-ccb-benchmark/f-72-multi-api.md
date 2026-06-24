# F-72: Multi-API 原生适配器扩展

> 状态: 📋 规划中
> 章节: docs/feature_plan/06-ccb-benchmark/f-72-multi-api.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

对标 CCB Multi-API，为各 LLM 供应商提供原生适配器（绕过 LiteLLM），充分利用平台专有能力（streaming、structured output、function calling、safety/grounding 等）。

### 1.2 子特性分解

| 编号 | 子特性 | Python 依赖 | 状态 | 预计工时 |
|:----:|--------|:-----------:|:----:|:--------:|
| P72-A | OpenAI 原生适配器（stream/structured output/function call） | `openai` | 📋 | 3-5d |
| P72-B | Gemini 原生适配器（Safety/grounding 全能力） | `google-genai` | 📋 | 3-5d |
| P72-C | Grok/xAI 原生适配器 | `requests` | 📋 | 2-3d |
| P72-D | 原生适配器自动选择（provider → adapter → LiteLLM 回退） | 无 | 📋 | 2-3d |
| P72-E | 平台专有特性映射表与能力标记 | 无 | 📋 | 3-5d |

### 1.3 架构

```
NativeProvider(ABC)
  ├── OpenAIProvider  — OpenAI 原生 SDK
  ├── GeminiProvider  — Google Generative AI
  └── GrokProvider    — xAI REST API

AdapterFactory
  ├── adapter_for(provider) → NativeProvider | None
  └── fallback → LiteLLM
```

### 1.4 NativeProvider 基类

```python
class NativeProvider(ABC):
    """原生适配器基类，继承自现有 Provider 抽象。"""

    @abstractmethod
    def stream_chat(self, messages, system=None, **kwargs) -> AsyncIterator[dict]:
        """原生流式聊天。"""

    @abstractmethod
    def structured_output(self, messages, schema, **kwargs) -> dict:
        """原生结构化输出（JSON mode / constrained decoding）。"""

    @abstractmethod
    def function_call(self, messages, tools, **kwargs) -> dict:
        """原生函数/工具调用。"""
```

### 1.5 OpenAI 适配器示例

```python
class OpenAIProvider(NativeProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def stream_chat(self, messages, system=None, **kwargs) -> AsyncIterator[dict]:
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True, **kwargs
        )
        async for chunk in response:
            yield chunk.model_dump()
```

### 1.6 自动选择与工厂

```python
def adapter_for(provider_name: str) -> type[NativeProvider] | None:
    """根据 provider 名称返回最适合的原生适配器类。"""
    mapping = {
        "openai": OpenAIProvider,
        "azure": AzureOpenAIProvider,
        "gemini": GeminiProvider,
        "grok": GrokProvider,
        "xai": GrokProvider,
    }
    match = mapping.get(provider_name)
    if match:
        return match
    # 未匹配 -> 返回 None，调用方回退到 LiteLLM
    return None
```

### 1.7 依赖

| 子特性 | Python 依赖 | 可选 |
|--------|:-----------:|:----:|
| P72-A | `openai` | ✅ |
| P72-B | `google-genai` | ✅ |
| P72-C | `requests` | ❌（标准库） |

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+基类+适配器+工厂） | 对齐 FEATURE_PLAN.legacy.md |
