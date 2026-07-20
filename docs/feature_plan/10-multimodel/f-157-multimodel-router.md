# F-157: 多模型并行调度 — 核心路由器设计

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                   clawcodex_ext/multimodel/                  │
│                                                              │
│  ┌──────────────────────┐     ┌──────────────────────────┐   │
│  │   MultiModelRouter   │     │  Strategy Implementations│   │
│  │   (implements         │     │                          │   │
│  │    BaseProvider)      │────▶│  • ParallelStrategy      │   │
│  │                      │     │  • VotingStrategy        │   │
│  │   wraps N providers  │     │  • RoutingStrategy       │   │
│  │   delegates to       │     │  • FallbackStrategy      │   │
│  │   strategy           │     └──────────────────────────┘   │
│  └──────────────────────┘                                    │
│                                                              │
│  ┌──────────────────────┐     ┌──────────────────────────┐   │
│  │  Aggregator          │     │  SessionBridge           │   │
│  │  (vote/merge/rank)   │     │  (provider logging +     │   │
│  │                      │     │   cost tracking)         │   │
│  └──────────────────────┘     └──────────────────────────┘   │
│                                                              │
│  ┌──────────────────────┐     ┌──────────────────────────┐   │
│  │  CLI Commands        │     │  /multimodel slash cmd   │   │
│  │  (model-group mgmt)  │     │  (runtime switch)        │   │
│  └──────────────────────┘     └──────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
         │
         │  implements BaseProvider → 对 query() 透明
         ▼
┌──────────────────────────────────────────────────────────────┐
│  query() / QueryEngine         (Layer 0 — 不变)              │
│    provider.chat_stream_response(...)                         │
└──────────────────────────────────────────────────────────────┘
```

## 2. 核心类型

### 2.1 ProviderSlot — 子 provider 描述

```python
# clawcodex_ext/multimodel/slots.py

@dataclass
class ProviderSlot:
    """一个子 provider 及其配置。"""
    name: str                   # 标识名，如 "sonnet", "gpt4o"
    provider: BaseProvider      # 子 provider 实例
    model: str | None = None    # 模型名（覆盖 provider 默认）
    weight: float = 1.0         # 投票权重
    timeout_ms: int = 120_000   # 单次调用超时
    enabled: bool = True        # 是否参与本轮调用
```

### 2.2 MultiModelResult — 单模型调用结果

```python
# clawcodex_ext/capabilities/multimodel_protocol.py

@dataclass
class MultiModelResult:
    """单个模型调用的完整结果。"""
    slot_name: str
    response: ChatResponse
    duration_ms: int
    tokens: dict[str, int]      # {"input": N, "output": N}
    error: str | None = None
    cancelled: bool = False
```

### 2.3 AggregatedOutput — 聚合后的最终输出

```python
@dataclass
class AggregatedOutput:
    """聚合后的最终输出。"""
    chosen: ChatResponse                    # 选中的最终响应
    runners_up: list[MultiModelResult]      # 备选结果
    vote_summary: dict | None = None        # 投票摘要
    provenance: list[MultiModelResult]      # 所有原始结果（审计用）
    summary_text: str | None = None         # 自动生成的差异摘要
```

## 3. MultiModelRouter

```python
# clawcodex_ext/multimodel/router.py

class MultiModelRouter(BaseProvider):
    """多模型路由器 — 实现 BaseProvider 接口，对 query() 透明。

    用法:
        router = MultiModelRouter(
            slots=[
                ProviderSlot("sonnet", anthropic_provider, "claude-sonnet-4-6"),
                ProviderSlot("gpt4o", openai_provider, "gpt-4o"),
            ],
            strategy=ParallelStrategy(),
        )
        # 直接传给 QueryEngineConfig(provider=router)
    """

    def __init__(
        self,
        slots: list[ProviderSlot],
        strategy: MultiModelStrategy,
        aggregator: AggregatorProtocol | None = None,
    ):
        self.slots = slots
        self.strategy = strategy
        self._aggregator = aggregator
        # 记录最后一次调用的完整结果（供展示层查询）
        self._last_result: list[MultiModelResult] | None = None
        self._last_aggregated: AggregatedOutput | None = None

    def chat_stream_response(self, messages, **kwargs) -> ChatResponse:
        """委托给当前策略执行。

        策略内部决定：
        - 并行调用所有 slots（ParallelStrategy / VotingStrategy）
        - 串行选择 slot（RoutingStrategy）
        - 逐个尝试（FallbackStrategy）

        返回聚合后的 ChatResponse（对 query() 透明）。
        """
        result = asyncio.run(self.strategy.execute(
            router=self,
            messages=messages,
            **kwargs,
        ))
        self._last_result = result
        if self._aggregator:
            aggregated = asyncio.run(self._aggregator.aggregate(result, {}))
            self._last_aggregated = aggregated
            return aggregated.chosen
        # 无聚合器：取第一个成功结果
        for r in result:
            if r.error is None:
                return r.response
        raise RuntimeError(f"All {len(self.slots)} providers failed")
```

## 4. 调度策略

### 4.1 ParallelStrategy — 并行对比

```
用户输入 "Write a Python quicksort"
  ├── sonnet-4-6 → [完整响应 A]
  ├── gpt-4o     → [完整响应 B]
  └── deepseek   → [完整响应 C]
                      ↓
    全部返回，用户对比选择（无聚合，PassThroughAggregator）
```

```python
# clawcodex_ext/multimodel/strategies/parallel.py

class ParallelStrategy(MultiModelStrategy):
    """并行策略：所有模型同时接收相同输入，全部返回。"""

    name = "parallel"

    async def execute(self, router, messages, **kwargs) -> list[MultiModelResult]:
        results: list[MultiModelResult] = []
        semaphore = asyncio.Semaphore(router.config.max_concurrent or 5)

        async def _call_one(slot: ProviderSlot) -> MultiModelResult:
            async with semaphore:
                t0 = time.monotonic()
                try:
                    resp = await asyncio.wait_for(
                        slot.provider.chat_async(messages, **kwargs),
                        timeout=slot.timeout_ms / 1000,
                    )
                    dt = int((time.monotonic() - t0) * 1000)
                    return MultiModelResult(
                        slot_name=slot.name,
                        response=resp,
                        duration_ms=dt,
                        tokens=resp.usage or {},
                    )
                except asyncio.TimeoutError:
                    return MultiModelResult(
                        slot_name=slot.name,
                        response=ChatResponse("", "", {}, ""),
                        duration_ms=slot.timeout_ms,
                        error=f"Timeout after {slot.timeout_ms}ms",
                    )
                except Exception as e:
                    dt = int((time.monotonic() - t0) * 1000)
                    return MultiModelResult(
                        slot_name=slot.name,
                        response=ChatResponse("", "", {}, ""),
                        duration_ms=dt,
                        error=str(e),
                    )

        tasks = [_call_one(slot) for slot in router.slots if slot.enabled]
        results = await asyncio.gather(*tasks)
        router._last_result = results
        return results
```

### 4.2 VotingStrategy — 投票集成

```
用户输入 "Explain quantum computing"
  ├── sonnet-4-6        → 完整响应 A
  ├── gpt-4o            → 完整响应 B
  ├── deepseek-v4-flash → 完整响应 C
  └── gemini-2.5-pro    → 完整响应 D
                      ↓
          Aggregator 投票/评分/排序
                      ↓
          返回得分最高的响应（附带投票摘要）
```

```python
# clawcodex_ext/multimodel/strategies/voting.py

class VotingStrategy(MultiModelStrategy):
    """投票策略：并行调用，聚合器选择最佳结果。"""

    name = "voting"

    min_votes: int = 2
    aggregator: AggregatorProtocol

    async def execute(self, router, messages, **kwargs) -> list[MultiModelResult]:
        # 同 ParallelStrategy 并行调用所有 slots
        results = await _parallel_call_all(router, messages, **kwargs)
        router._last_result = results
        # 聚合器选择
        aggregated = await self.aggregator.aggregate(results, {})
        router._last_aggregated = aggregated
        # 返回所有结果 + 选中的结果以特殊标记放在第一条
        return [aggregated.chosen] + aggregated.provenance
```

### 4.3 RoutingStrategy — 任务路由分发

```
用户输入 "Write a blog post about Python"
  ├── Turn 1: 规划大纲 → claude-opus-4 (强推理)
  ├── Turn 2: 撰写正文 → gpt-4o (高创意)
  └── Turn 3: 代码示例 → deepseek-v4-flash (代码强项)
                      ↓
      按序执行，每个 turn 由路由规则决定用哪个模型
```

```python
# clawcodex_ext/multimodel/strategies/routing.py

@dataclass
class RoutingRule:
    """路由规则：匹配条件 → 目标 slot。"""
    matcher: Callable[[list[Message], ToolContext], str]  # 返回 slot name
    description: str = ""

class RoutingStrategy(MultiModelStrategy):
    """路由策略：每个 turn 根据规则选择不同模型。"""

    name = "routing"
    rules: list[RoutingRule]
    fallback_slot: str = "default"

    # 通过 pre_llm hook 注册到 query 循环
    def install_hook(self):
        from clawcodex_ext.query.hook_registry import register_loop_hook
        register_loop_hook(
            "multimodel_routing",
            self._routing_hook,
            phase="pre_llm",
            priority=50,
        )
```

### 4.4 FallbackStrategy — 故障转移

```
主模型 → 超时/429/5xx → 备选模型 1 → 备选模型 2 → 全部失败则报错
```

```python
# clawcodex_ext/multimodel/strategies/fallback.py

class FallbackStrategy(MultiModelStrategy):
    """故障转移策略：按优先级顺序尝试，成功后返回。"""

    name = "fallback"

    async def execute(self, router, messages, **kwargs) -> list[MultiModelResult]:
        results: list[MultiModelResult] = []
        for slot in router.slots:
            if not slot.enabled:
                continue
            try:
                resp = await asyncio.wait_for(
                    slot.provider.chat_async(messages, **kwargs),
                    timeout=slot.timeout_ms / 1000,
                )
                results.append(MultiModelResult(slot.name, resp, ...))
                router._last_result = results
                return results  # 成功即返回
            except Exception as e:
                results.append(MultiModelResult(slot.name, ..., error=str(e)))
                continue  # 尝试下一个
        raise RuntimeError("All fallback providers failed")
```

## 5. 协议接口

```python
# clawcodex_ext/capabilities/multimodel_protocol.py

class MultiModelStrategy(Protocol):
    """多模型调度策略协议。"""
    name: str

    async def execute(
        self,
        router: "MultiModelRouter",
        messages: list[MessageInput],
        **kwargs,
    ) -> list[MultiModelResult]: ...

class AggregatorProtocol(Protocol):
    """聚合器协议。"""
    async def aggregate(
        self, results: list[MultiModelResult], context: dict
    ) -> AggregatedOutput: ...
```

## 6. 集成方式

### 6.1 零侵入：通过 QueryEngineConfig 注入

```python
# 原代码
engine = QueryEngine(QueryEngineConfig(
    provider=anthropic_provider,   # 单 provider
    ...
))

# 多模型版本 — 只需替换 provider
router = MultiModelRouter(
    slots=[...],
    strategy=ParallelStrategy(),
)
engine = QueryEngine(QueryEngineConfig(
    provider=router,               # ← 替换为 router
    ...
))
```

### 6.2 可选增强：通过 pre_llm hook

RoutingStrategy 通过 `hook_registry` 的 `pre_llm` hook 在每个 turn 前动态选择模型。

### 6.3 备选方案：MultiModelQueryEngine

如果策略需要修改 query 循环的 yield 行为（如 ParallelStrategy 流式返回多个模型的 token），创建 `MultiModelQueryEngine` 继承或组合 `QueryEngine`，在 `clawcodex_ext/query/` 中实现。

## 7. 目录结构

```
clawcodex_ext/
  multimodel/
    __init__.py              # 导出 + 自动注册
    router.py                # MultiModelRouter
    slots.py                 # ProviderSlot
    config.py                # MultiModelConfig
    strategies/
      __init__.py
      base.py                # MultiModelStrategy 抽象基类
      parallel.py            # ParallelStrategy
      voting.py              # VotingStrategy
      routing.py             # RoutingStrategy
      fallback.py            # FallbackStrategy
    aggregators/
      __init__.py
      base.py                # AggregatorProtocol
      majority_vote.py       # MajorityVoteAggregator
      scoring.py             # ScoringAggregator
      rank.py                # RankAggregator
      passthrough.py         # PassThroughAggregator
    session_bridge.py        # 多模型成本追踪 + 审计日志
    cli.py                   # clawcodex-dev multimodel 子命令
    runtime_command.py       # /multimodel slash 命令

  capabilities/
    multimodel_protocol.py   # MultiModelStrategy / AggregatorProtocol
```

## 8. 实施路径

| 阶段 | 内容 | 改动范围 |
|------|------|---------|
| **P0** | `clawcodex_ext/capabilities/multimodel_protocol.py` + `MultiModelRouter` + `ParallelStrategy` | 纯新增文件，零侵入 |
| **P1** | `VotingStrategy` + `MajorityVoteAggregator` + `ScoringAggregator` | 纯新增 |
| **P2** | `FallbackStrategy` + session_bridge 成本追踪 | 纯新增 |
| **P3** | `RoutingStrategy` + `pre_llm` hook 注册 | 新增 + 可选 hook 注册 |
| **P4** | CLI 命令 + REPL `/multimodel` + TUI 展示 | 纯新增 |
