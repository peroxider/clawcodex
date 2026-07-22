# F-96: PROMPT_CACHE_BREAK_DETECTION 缓存命中率监测

> 状态: 📋 规划中(已有 `clawcodex_ext/providers/anthropic_provider._extract_usage_dict` 与 `src/cost_tracker.ModelUsage` 基础;目标模块 `clawcodex_ext/providers/cache_breaker.py` 待建)
> 章节: `docs/feature_plan/06-ccb-benchmark/f-96-cache-break-detection.md`
> 最后更新: 2026-07-01
> 缺口来源: gap-analysis-2026q2.md §3.3(`#### F-96: PROMPT_CACHE_BREAK_DETECTION`,已分解到本文档 §0)

## §0 缺口摘要

> 本节为 gap-analysis-2026q2.md §3.3 F-96 派工条目的分解版本;详细设计与基线请阅读 §1。

### 0.1 缺口描述

usage 字段采集已具备,但**缺产品级可观测层**:

- 已有 `clawcodex_ext/providers/anthropic_provider.py:_extract_usage_dict()`(抽取 `cache_creation_input_tokens` / `cache_read_input_tokens` / `ephemeral_5m` / `ephemeral_1h` 四类字段);
- 已有 `ClawcodexAnthropicProvider.chat_stream_response` 把 `usage` 回写 `ChatResponse.usage`;
- 已有 `src/cost_tracker.py:ModelUsage` 按模型累计 cache_creation / cache_read;
- 已有 `src/context_system/system_prompt_cache.py` / `src/utils/cache_warning.py`(配置错误检查)。

完全缺失:

- 滑动窗口命中率(hit ratio)/ TTL 占比(`5m` vs `1h`)/ break 计数;
- cache 命中率突变、prefix 不再命中、TTL 类型切换的**运行时**探测(现有 `cache_warning` 只在配置错误时报);
- 查看"最近 N 轮 cache 健康度"的工具 / CLI;
- 上层 Agent(auto-compact / system prompt 拼接)订阅"prefix 已 break"事件的能力。

### 0.2 对标

- CCB `PROMPT_CACHE_BREAK_DETECTION` 滑窗命中率监测 + break 归因;
- CCB 命中率突变 / 全 miss / TTL 切换三类事件显式 emit;
- CCB provider 无侵入(hook 复制 usage 流,不阻断 provider 调用);
- CCB Anthropic 优先 + openai_compatible 可扩展 usage 桥接。

### 0.3 解耦落地路径(全部 `clawcodex_ext/providers/`,不改 `_extract_usage_dict`)

- `cache_breaker.py` — `CacheSample` / `CacheWindowSummary` / `CacheBreakEvent` 模型 + `CacheSampler`(per-session/per-model deque 滑窗)+ `CacheBreakDetector`;
- `cache_breaker_hook.py` — 从 `ChatResponse.usage` 复制样本,不阻断 provider;
- `clawcodex_ext/command_system/cache_commands.py` — `/cache` / `/cost cache` 命令族;
- `clawcodex_ext/tool_system/tools/cache_status.py` — `CacheStatusTool` 给 Agent;
- 可选 statusline / audit log emit。

### 0.4 依赖

- 现有 `anthropic_provider._extract_usage_dict` / `ChatResponse.usage` / `cost_tracker.ModelUsage`;
- F-69 Budget Mode(命中率退化可触发 budget 调整);
- F-89 Proactive(idle tick 检查 cache 健康度);
- F-68 Feature Gate(`CACHE_BREAK_DETECTION` 默认 off)。

### 0.5 估算工时

1 周(单人)。

---

## §1 设计规划

### 1.1 目标

对标 CCB `PROMPT_CACHE_BREAK_DETECTION` 能力,把 ClawCodex 当前零散的 Anthropic prompt cache usage 字段采集升级为**持续观测 + 命中率告警 + 缓存破坏归因**系统。用户和上层 Agent 能在不修改 provider 实现的前提下,实时观察 system prompt / conversation prefix 的 cache 命中率,并在命中率突变、prefix 不再命中、或 TTL 类型切换时被明确告知。

F-96 不是为了降低 prompt cache 的实现门槛(那已经在 `_extract_usage_dict` / `cache_control` block / `system_prompt_cache.py` 完成),而是补齐产品层的**可观测性、可告警性、可归因性**,把“沉默的命中率退化”变成可见事件。

### 1.2 背景

现有基线(已经具备的能力):

1. `clawcodex_ext/providers/anthropic_provider.py:_extract_usage_dict()` 从 Anthropic SDK `Usage` 抽取四类 cache 字段:
   - `cache_creation_input_tokens`
   - `cache_read_input_tokens`
   - `cache_creation.ephemeral_5m_input_tokens`
   - `cache_creation.ephemeral_1h_input_tokens`
2. `clawcodex_ext/providers/anthropic_provider.py:ClawcodexAnthropicProvider.chat_stream_response` 在每次响应结束后把 `usage` dict 回写到 `ChatResponse.usage`;
3. `src/cost_tracker.py:ModelUsage` 已经按模型聚合 cache_creation / cache_read 数值,`record_api_usage()` 可累加;
4. `src/context_system/system_prompt_cache.py` 与 `src/utils/cache_warning.py` 已有 cache status 检查工具,后者提示"是否正确注入 cache_control block"。

缺口:

- `_extract_usage_dict` 仅**抽取**字段,不做**趋势判断**;用户看到原始数字仍难判断“上一轮还在命中,这轮突然不命中”;
- `cache_warning.py` 只在**配置错误**(block 缺失/类型错误)时报错,不报**运行时命中率退化**;
- `ModelUsage` 只做**累计**,没有**滑动窗口命中率**(hit ratio)、**TTL 占比**(`5m` vs `1h` 比例)、**break 计数**;
- 没有任何工具或 CLI 命令让用户“查看最近 N 轮的 cache 健康度”;
- 上层 Agent(例如 auto-compact、system prompt 拼接)无法订阅"prefix 已 break"事件。

F-96 在这些基线上叠加观测层,**不修改 `_extract_usage_dict` 也不阻断 provider 调用**,用 hook 模式把 usage 数据流复制给 cache breaker。

### 1.3 子特性分解

| 编号 | 子特性 | 预计工作量 |
|:----:|--------|:----------:|
| P96-A | 数据模型(`CacheSample`, `CacheWindowSummary`, `CacheBreakEvent`) | 1 天 |
| P96-B | 采样器(`CacheSampler`):per-session/per-model 滑窗 | 1.5 天 |
| P96-C | Break 探测器(`CacheBreakDetector`):命中率突变/TTL 切换/全部 miss | 1.5 天 |
| P96-D | Provider usage 桥接(Anthropic 优先 + 可扩展 openai_compatible) | 1 天 |
| P96-E | 告警 emit(`/cost cache` CLI + statusline + 可选 audit log) | 1 天 |
| P96-F | Tool/CLI 接入:`CacheStatusTool` + `/cache` 命令族 | 1 天 |
| P96-G | Agent 集成 hook:ultra-compress / system prompt mutation 时下发 stale notice | 1 天 |
| P96-H | 单元 + 集成测试 | 1.5 天 |

**估算总工时**:1 周。

### 1.4 架构设计

```
Anthropic ChatResponse.usage
        │
        ▼
CacheSamplerHook(extension hook)
        │
        ▼
CacheSampler
  ├─ per-session deque(maxlen=window_size) of CacheSample
  ├─ background age cleanup
  └─ emit summary on demand
        │
        ▼
CacheBreakDetector
  ├─ hit_ratio(cur, prev) < threshold → BREAK
  ├─ TTL flip 5m ↔ 1h → TTL_FLIP
  ├─ consecutive_miss ≥ k → STALE
  └─ cache_creation > break_creation_threshold → REWRITE
        │
        ▼
CacheBreakNotifier
  ├─ CLI: /cache status / history / --tail 50
  ├─ Tool: CacheStatusTool for Agent / TeamMem recall
  ├─ Statusline (optional opt-in)
  └─ Audit (history JSONL)
```

#### 包结构

```
clawcodex_ext/providers/
├── cache_breaker.py               # P96-A/B/C: 数据模型 + 采样器 + 探测器
├── cache_breaker_hook.py          # P96-D: 把 ChatResponse.usage 接到采样器
└── cache_breaker_notifier.py      # P96-E/F: CLI 通知 + Tool 适配

clawcodex_ext/command_system/
└── cache_commands.py              # P96-F: /cache 命令族

clawcodex_ext/tool_system/tools/
└── cache_status.py                # P96-F: CacheStatusTool

extensions/capabilities/
└── cache_event_protocol.py        # P96-G: CacheEvent Protocol

tests/clawcodex_ext/providers/
├── test_cache_sampler.py
├── test_cache_break_detector.py
├── test_cache_breaker_hook.py
└── test_cache_commands.py
```

### 1.5 核心数据模型

```python
@dataclass(frozen=True)
class CacheSample:
    ts: str                           # ISO 8601 UTC
    session_id: str
    workspace_root: str | None
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cache_creation_5m: int
    cache_creation_1h: int
    duration_ms: int | None = None
    turn_index: int | None = None
    system_prompt_hash: str | None = None


@dataclass(frozen=True)
class CacheWindowSummary:
    session_id: str
    model: str
    window_size: int
    samples: int
    total_input: int
    total_cache_read: int
    total_cache_creation: int
    hit_ratio: float                 # 0..1 (cache_read / (cache_read + cache_creation + non_cached))
    ttl_breakdown_5m: float          # 0..1 (5m / total_creation)
    ttl_breakdown_1h: float
    consecutive_miss: int
    last_break_at: str | None


@dataclass(frozen=True)
class CacheBreakEvent:
    id: str
    session_id: str
    model: str
    kind: Literal[
        "hit_ratio_drop",
        "ttl_flip_5m_to_1h",
        "ttl_flip_1h_to_5m",
        "consecutive_miss",
        "rewrite_threshold",
        "first_sample",
    ]
    severity: Literal["info", "warning", "error"]
    hit_ratio_before: float | None
    hit_ratio_after: float | None
    detected_at: str
    suggestion: str | None = None
    related_turn_index: int | None = None


@dataclass(frozen=True)
class CacheBreakConfig:
    enabled: bool = False
    window_size: int = 20
    hit_ratio_drop_threshold: float = 0.30      # 当 hit_ratio 下降 ≥ 30% 时告警
    consecutive_miss_threshold: int = 3
    rewrite_creation_threshold: int = 60_000     # cache_creation 超过此值视为 rewrite
    history_path: Path = Path("~/.clawcodex/cache/breaker.jsonl")
    max_history: int = 1000
```

### 1.6 核心接口

```python
class CacheSampler:
    """Per-session / per-model sliding window samples."""

    def __init__(self, *, config: CacheBreakConfig) -> None: ...

    def record(self, sample: CacheSample) -> CacheWindowSummary | None: ...

    def window(self, session_id: str, *, model: str | None = None) -> CacheWindowSummary: ...

    def reset(self, session_id: str) -> None: ...

    def list_sessions(self) -> list[str]: ...


class CacheBreakDetector:
    """Sliding-window + sample heuristics."""

    def __init__(self, *, config: CacheBreakConfig, notifier: CacheBreakNotifier | None = None) -> None: ...

    def observe(self, sample: CacheSample) -> tuple[CacheBreakEvent | None, CacheWindowSummary]: ...

    def latest_event(self, session_id: str) -> CacheBreakEvent | None: ...


class CacheBreakNotifier:
    """Emit break events to CLI/Tool/audit log."""

    def emit(self, event: CacheBreakEvent) -> None: ...
    def list_recent(self, *, limit: int = 50) -> list[CacheBreakEvent]: ...
    def pretty(self, summary: CacheWindowSummary) -> str: ...


def install_cache_breaker_hook(provider_name: str = "anthropic") -> None:
    """Wire ChatResponse.usage → CacheSampler inside the given provider."""
```

### 1.7 探测规则与算法

| 规则 | 触发条件 | 严重度 | 默认动作 |
|------|----------|:------:|----------|
| `hit_ratio_drop` | `cur.hit_ratio < prev.hit_ratio - 0.30` 且样本 ≥ 2 | warning | CLI banner + audit |
| `consecutive_miss` | 连续 `k` 轮 `cache_read = 0` | warning | suggest 检查 system prompt 改动 |
| `ttl_flip_5m_to_1h` | 从 `5m-only` 突变为 `1h` 占比 > 80% | info | 审计 TTL 变化 |
| `ttl_flip_1h_to_5m` | 从 `1h` 切换到 `5m` 主导 | info | 审计 TTL 变化 |
| `rewrite_threshold` | 单轮 `cache_creation` > 60k | error | audit + 上层 agent 提示 |
| `first_sample` | session 第一条记录 | info | 仅记录初始状态 |

`hit_ratio` 计算采用 CCB 语义:

```
non_cached_input = input_tokens - cache_creation_input_tokens - cache_read_input_tokens
hit_ratio = cache_read_input_tokens / max(1, (cache_read_input_tokens + cache_creation_input_tokens + max(0, non_cached_input)))
```

> 注:Anthropic prompt-cache 的 `input_tokens` 是 total,`cache_creation + cache_read` 不超过 total,所以非缓存部分即为 `input - cache_creation - cache_read`。

### 1.8 Provider usage 桥接

实现要点:

1. **不修改** `clawcodex_ext/providers/anthropic_provider.py` 主干;利用现有 `ChatResponse.usage` dict 出口;
2. 通过 `clawcodex_ext/providers/hooks.py` 暴露的 provider-agnostic `usage_hook(slot, payload)` 注册;
3. 在 `chat_stream_response` 末尾(现有 `record_api_usage()` 调用旁边)插入 `_emit_cache_sample()`;
4. `_extract_usage_dict` 已经返回 `cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`,采样器直接读 nested dict;
5. 多 provider 支持先以 Anthropic 唯一实现为主,`openai_compatible` / kimi / moonshot 等通过同样的 `usage_hook` 协议接入(本 F-96 文档范围只承诺 Anthropic,可扩展协议见 P96-D)。

### 1.9 CLI / Tool 行为

#### `/cache` 命令族

```
/cache status [--session <id>] [--model <name>]
/cache history [--tail 50] [--severity warning]
/cache reset [--session <id>]
/cache off
/cache on
/cache explain <event-id>      # 显示触发该 event 的 sample 上下文
```

输出示例:

```
/cache status
Session: agent-2026-06-30-aaaa
Model:   claude-sonnet-4-6
Window:  last 20 turns
─────────────────────────────────────────
  total input            : 184,213
  cache_read             : 142,891
  cache_creation         :  18,402
  hit_ratio              :  77.6%   ▲ +2.1%
  ttl breakdown 5m/1h    :  41% / 59%
  consecutive_miss       :  0
  last break event       :  none
─────────────────────────────────────────
Recent events (last 24h):
  03:14:05  INFO   first_sample            session initialized
  04:02:33  WARN   hit_ratio_drop          0.812 → 0.471  (-34.1%)
  04:02:33  WARN   consecutive_miss        k=3
```

#### `CacheStatusTool` actions

| action | 输入 | 输出 |
|--------|------|------|
| `status` | `session_id?`, `model?` | 窗口摘要 |
| `history` | `severity?`, `limit?` | 事件列表 |
| `explain` | `event_id` | 触发 sample 上下文 + 修复建议 |
| `on` / `off` | - | 切换并持久化 enable 标志 |

### 1.10 失败模式

| 错误 | 场景 | 处理 |
|------|------|------|
| `CacheSamplerHookNotInstalled` | provider hook 未注册 | `/cache status` 提示并给 `install_cache_breaker_hook` 命令 |
| `CacheHistoryCorrupt` | JSONL 单行损坏 | 跳过 + WARN,不删除原文件 |
| `CacheBreakConfigInvalid` | threshold 非法 | fail closed: 不启动采样 |
| `CacheNotEnabled` | feature flag 关闭 | 返回空 status,CLI 提示 `CACHE_BREAK_DETECTION=off` |
| 误报 (`hit_ratio_drop` 但实际是 round 1 冷启动) | window 不足 | 窗口 < 4 时不报 warning;info 级记录 first_sample |

### 1.11 验收标准

1. `PROMPT_CACHE_BREAK_DETECTION=off` 时 `/cache status` 显示 disabled,不写 `~/.clawcodex/cache/breaker.jsonl`;
2. `install_cache_breaker_hook("anthropic")` 后,真实 `chat_stream_response` 在每个 turn 产生一条 `CacheSample`(可在测试用 `httpx_mock` 模拟);
3. 连续 3 轮 `cache_read_input_tokens == 0` 触发 `consecutive_miss warning`;
4. hit_ratio 单轮下降 30% 触发 `hit_ratio_drop warning`,但窗口 < 4 时不报;
5. `cache_creation` 单轮 > 60k 触发 `rewrite_threshold error`;
6. `/cache history --tail 5` 输出最近 5 条事件(含 severity);
7. `/cache reset --session X` 清空该 session 滑窗;
8. 关闭后再次打开能继续累计,而非从头;
9. 单元测试覆盖采样、探测、hook 注入、CLI、Notifier;
10. 退出码语义:`/cache status` 命中 warning 时返回 0(信息),`severity=error` 时返回 5。

## §2 落地步骤

| 步骤 | 内容 | 涉及子特性 | 工时 |
|:----:|------|:----------:|:----:|
| 1 | 定义 `CacheSample` / `CacheWindowSummary` / `CacheBreakEvent` | P96-A | 1 天 |
| 2 | 实现 `CacheSampler` 滑窗与 reset/list | P96-B | 1.5 天 |
| 3 | 实现 `CacheBreakDetector` 与探测算法 | P96-C | 1.5 天 |
| 4 | 注入 `install_cache_breaker_hook("anthropic")` | P96-D | 1 天 |
| 5 | 增加 `CacheBreakNotifier` 与 statusline/audit log | P96-E | 1 天 |
| 6 | 增加 `/cache` 命令族 + `CacheStatusTool` | P96-F | 1 天 |
| 7 | 增加 Agent 集成 hook(upstream mutation 时下发 stale notice) | P96-G | 1 天 |
| 8 | 补齐单元/集成/CLI 测试 | P96-H | 1.5 天 |

## §3 风险与缓解

| 风险 | 等级 | 缓解 |
|------|:----:|------|
| 误报打扰用户 | 🟠 | 窗口 < 4 不报 warning;首条记录只发 info;阈值可调 |
| hook 注入污染 provider 行为 | 🟡 | hook 只**订阅**使用量,不改 `_extract_usage_dict` 返回值;失败 fail-soft |
| 多 provider 数据混算 | 🟡 | `CacheSample` 强制携带 `provider`;窗口按 `(session_id, model, provider)` 分组 |
| JSONL 损坏 | 🟡 | 跳过坏行 + WARN,不重写原文件 |
| 上层 Agent 滥用通知导致打扰 | 🟠 | notifier 支持 `min_severity` 过滤;Agent 默认订阅 `error` 级 |
| 与 `cache_warning.py` 重复 | 🟡 | `cache_warning` 报配置错误;F-96 报运行时退化;两者并存互补 |

## §4 与其他特性的关系

| 协同 | 说明 |
|------|------|
| **F-94 BG_SESSIONS** | 后台 session 恢复后,采样器自然继续累计,可观察到恢复 prefix 的 break |
| **F-92 Skill Search** | 大量 skill 注入 system prompt 时容易触发 break,F-96 可归因 |
| **F-87 Ultraplan** | Plan 阶段重排 system prompt 时应触发 `cache_warning`,F-96 联动 stale notice |
| **Cost Tracker** | `ModelUsage` 是源数据;F-96 复用其累计语义,并扩展 hit_ratio |
| **Statusline / HUD** | 可在 footer 显示 cache hit_ratio + consecutive_miss |

---

**关联文档**: [README.md 缺口矩阵](./README.md#a-全特性对照矩阵), [F-94 BG_SESSIONS](./f-94-bg-sessions.md), F-92 Skill Search（特性已落地，设计文档已归档）
