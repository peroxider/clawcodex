# F-72: Multi-API 原生适配器扩展

> 状态: 🟡 部分实现（P72-A~C/E 原生适配器已落地；P72-D 自动选择工厂已落地；P72-D LiteLLM 回退软接通待验证）
> 章节: docs/feature_plan/06-ccb-benchmark/f-72-multi-api.md
> 最后更新: 2026-07-21

## §1 设计规划

### 1.1 目标

对标 CCB Multi-API，为各 LLM 供应商提供原生适配器（绕过 LiteLLM），充分利用平台专有能力（streaming、structured output、function calling、safety/grounding 等）。

### 1.2 子特性分解

| 编号 | 子特性 | Python 依赖 | 状态 | 预计工时 |
|:----:|--------|:-----------:|:----:|:--------:|
| P72-A | OpenAI 原生适配器（stream/structured output/function call） | `openai` | ✅ `clawcodex_ext/providers/native/openai_adapter.py` | 3-5d |
| P72-B | Gemini 原生适配器（Safety/grounding 全能力） | `google-genai` | ✅ `clawcodex_ext/providers/native/gemini_adapter.py` | 3-5d |
| P72-C | Grok/xAI 原生适配器 | `openai` | ✅ `clawcodex_ext/providers/native/grok_adapter.py` | 2-3d |
| P72-D | 原生适配器自动选择（provider → adapter → LiteLLM 回退） | 无 | ✅ `clawcodex_ext/providers/native/__init__.py` (工厂 + 软回退) | 2-3d |
| P72-E | 平台专有特性映射表与能力标记 | 无 | ✅ `clawcodex_ext/providers/native/capabilities.py` | 3-5d |

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

### 2.1 已落地

| 日期 | 里程碑 | 文件 | 状态 |
|------|--------|------|:----:|
| 2026-07 | OpenAI 原生适配器 | `clawcodex_ext/providers/native/openai_adapter.py` | ✅ |
| 2026-07 | Gemini 原生适配器（composition 封装） | `clawcodex_ext/providers/native/gemini_adapter.py` | ✅ |
| 2026-07 | Grok/xAI 原生适配器 | `clawcodex_ext/providers/native/grok_adapter.py` | ✅ |
| 2026-07 | 能力标记系统（11 项能力常量） | `clawcodex_ext/providers/native/capabilities.py` | ✅ |
| 2026-07 | 适配器工厂 + 软回退 | `clawcodex_ext/providers/native/__init__.py` | ✅ |
| 2026-07 | NativeProvider 基类 | `clawcodex_ext/providers/native/base.py` | ✅ |

### 2.2 待验证/待完善

| 项 | 说明 |
|----|------|
| LiteLLM 回退软接通 | 工厂返回 `None` 时调用方是否确实回退到 LiteLLM？需端到端验证 |
| 原生适配器 CLI 选择 | 用户能否通过 `clawcodex-dev` CLI 显式选择原生适配器路径？ |
| 测试覆盖 | 各适配器缺少单元测试覆盖 |

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（架构+基类+适配器+工厂） | 对齐 FEATURE_PLAN.legacy.md |
| 2026-07-21 | 更新状态为 🟡 部分实现，落地清单确认 5 子特性全部完成 | 代码核查确认 `clawcodex_ext/providers/native/` 已实现 |
