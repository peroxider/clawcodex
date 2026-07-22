# F-161: 涌现式上下文发现 — Agent 主动反思"我可能需要 X"显式化

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-161-emergent-context-discovery.md`
> 最后更新: 2026-07-22
> 设计来源: DC-A 元架构脑暴 [§3.D 元架构层 — DC-018](dynamic-context-architecture.md)

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 1 元架构层轻量级特性（P0，~1-2 周） |
| 覆盖 DC | DC-018 涌现式上下文发现 |
| 前置依赖 | **F-159 JIT 上下文合成**（执行层已就绪，本特性是反思调度层） |
| 协同 | F-130 Profile（emergent 触发可作 Profile 切换依据）、F-158-A VERIFIED（emergent 抓取即 VERIFIED 来源）、F-160 反事实（emergent 反思含反事实检查步骤） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/emergent/`，零 `src/` 侵入；调用 F-159 通过 import + Protocol 注入 |
| 落地形态 | 涌现反思 prompt 模板 + 触发器 + JIT 桥接 + 反思缓存 + 信心评分门控 |

---

## §1 设计规划

### 1.1 背景

F-159 提供 **JIT 上下文合成**——Agent / 用户 / Hook 显式触发"我需要 X"或 `/context X`，按需抓取。但**很多关键缺口 Agent 不会显式声明**——它不知道"自己不知道什么"，自然不会主动触发 JIT。

**涌现式上下文发现 (Emergent Context Discovery)** 让 Agent **主动反思**"要完成此任务我需要哪些信息？当前上下文覆盖了哪些？缺哪些？"，把"不知道自己不知道"显式化。这是 meta-cognition 在 Agent 上下文管理上的体现。

F-161 与 F-159 是同一思路的两个层级：
- **F-159 显式触发层** — "我需要 X" / `/context X`（用户或 Agent 显式声明）
- **F-161 隐式反思层** — "我可能需要 X，但我还不知道"（Agent 通过反思发现缺口）

F-161 不实现抓取本身——它调用 F-159 `synthesize(intent)` 执行实际抓取。是 F-159 的**调度前置**。

### 1.2 目标

- 让"不知道自己不知道"通过反思 prompt 显式化
- 提供 EMERGENT_DISCOVERY_PROMPT，含 4 个反思问题（需要什么 / 覆盖什么 / 缺什么 / 信心几分）
- 触发器：任务开始 + 关键决策点自动触发反思
- 反思输出 → 缺口清单 → 调用 F-159 `synthesize(intent)` 逐个执行抓取
- 反思结果缓存避免重复反思
- 信心评分门控：confidence < 阈值 → 强制触发抓取
- 与 F-130 Profile / F-158-A / F-160 协同

### 1.3 非目标 (Out of Scope)

- 不替代 F-159 显式触发层——F-161 是 F-159 的反思调度前置
- 不替代 F-160 反事实推理——F-161 反思 prompt 可包含"反事实检查"步骤（与 F-160 协同）
- 不实现抓取本身——完全依赖 F-159 `synthesize(intent)`
- 不引入新的 LLM 调用——反思本身是 1 次 LLM 调用（meta-cognition 的固有成本）
- 不做跨会话反思记忆——依赖 F-166 记忆分层（Wave 2）

### 1.4 子特性分解

| 编号 | 子特性 | 状态 | 工时 |
|:----:|--------|:----:|:----:|
| P161-A | 涌现反思 prompt 模板（含 4 反思问题） | 📋 | 1d |
| P161-B | 反思触发器（任务开始 + 关键决策点） | 📋 | 1-2d |
| P161-C | 反思 → F-159 JIT 桥接（调用 synthesize） | 📋 | 1-2d |
| P161-D | 反思结果缓存（`(task_kind, context_hash)` key） | 📋 | 1d |
| P161-E | 信心评分门控（confidence < 阈值 → 强制抓取） | 📋 | 1d |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| **F-159 JIT 上下文合成** | **强协同（前置）** | P161-C 调用 `synthesize(intent)` 执行实际抓取 |
| F-119 Section Registry | **强协同** | P161-A 通过 `register_section` 把反思 prompt 注入到 `emergent_discovery_guide` section |
| F-102 Hook 扩展点 | **强协同** | `pre_turn_hook` / `pre_decision_hook` 注册反思触发器 |
| F-130 Profile 体系 | **协同** | emergent 反思触发可作 Profile 切换依据（多次反思未解决 → 切换 debug Profile） |
| F-158 抗幻觉基线 | **协同** | emergent 抓取结果可作为 F-158-A VERIFIED source |
| F-160 反事实推理 | **协同** | F-161 反思 prompt 可包含 "反事实检查" 步骤（"如果我错了，最可能错在哪"） |
| F-166 记忆分层（Wave 2 远期） | **远期** | 跨会话反思记忆的存储后端 |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/emergent/__init__.py` | — | 子系统入口，注册 prompts / triggers / bridge / cache |
| `extensions/emergent/prompts.py` | P161-A | `EMERGENT_DISCOVERY_PROMPT` + `EMERGENT_GAP_PROMPT` + 反思输出 dataclass |
| `extensions/emergent/triggers.py` | P161-B | `EmergentTrigger` Protocol + `OnTaskStartTrigger` / `OnDecisionPointTrigger` |
| `extensions/emergent/bridge.py` | P161-C | `bridge_to_jit(reflection)` 调用 F-159 `synthesize(intent)` |
| `extensions/emergent/cache.py` | P161-D | `ReflectionCache`（`(task_kind, context_hash)` key + TTL） |
| `extensions/emergent/confidence.py` | P161-E | `extract_confidence(reflection_output)` + 门控阈值 |
| `extensions/emergent/hooks.py` | 全部 | `pre_turn_hook` / `pre_decision_hook` 集成 |
| `extensions/emergent/capabilities.py` | — | Protocol 接口契约（`Trigger` / `ConfidenceExtractor`） |
| `tests/emergent/test_prompts.py` | P161-A | 模板格式化 + 输出解析 |
| `tests/emergent/test_triggers.py` | P161-B | 任务开始 / 关键决策点触发 |
| `tests/emergent/test_bridge.py` | P161-C | 反思输出 → F-159 synthesize 调用 |
| `tests/emergent/test_cache.py` | P161-D | 缓存命中 + 过期 |
| `tests/emergent/test_e2e.py` | 全部 | 端到端：触发 → 反思 → 缺口 → JIT 抓取 → 重新回答 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_emergent_extensions()` 在 import 时注册 prompts / triggers / bridge / cache |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | `pre_turn_hook` / `pre_decision_hook` 追加 `emergent.maybe_trigger` |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.emergent` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-161 |
| `docs/feature_plan/dynamic-context-architecture.md` | §8 变更记录加 F-161 启动行 |

### 1.7 核心 API 设计

#### 1.7.1 涌现反思 prompt 模板（P161-A）

```python
# extensions/emergent/prompts.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
import re


# ==== 主反思 prompt：触发 Agent 主动思考缺口 ====

EMERGENT_DISCOVERY_PROMPT = """
## Emergent Context Discovery（涌现式上下文发现）

### 当前任务
{task}

### 当前上下文摘要
{current_context_summary}

### 反思要求
请显式回答以下 4 个问题（不要泛泛而谈，必须具体到可验证的事实层面）：

1. **要完成此任务，我需要哪些信息？** — 列出 3-5 个关键信息点（如"项目错误处理约定"、"目标 API 最新签名"、"部署环境配置"）

2. **当前上下文覆盖了哪些？缺哪些？** — 对每个信息点标注 COVERED / PARTIAL / MISSING

3. **对每个缺口，我应该调用哪个工具 / 检索哪个来源？** — 具体到 `Grep("X", scope="project")` / `WebFetch("X 官方文档")` / `Bash("command")` 的程度

4. **我是否有信心基于现有上下文回答？(0-1)** — 如果 < 0.7，必须列出至少 1 个具体缺口

### 输出格式
```
### Reflection
- NEEDED:
  - [COVERED] 信息点 1 (source: ...)
  - [PARTIAL]  信息点 2 (gap: ...)
  - [MISSING]  信息点 3 (tool: Grep/WebFetch/Bash, query: ...)
- CONFIDENCE: 0.X
- REASON: 如果 < 0.7，列出至少 1 个具体证据缺口
```

### 反事实协同（F-160）
- 在列出缺口时，同步思考"如果我错了，最可能错在哪"
- 缺口 1 应包含反事实推理：当前结论的最可能反驳证据是什么？
"""

# ==== 缺口补充 prompt：反思后二次追问 ====

EMERGENT_GAP_PROMPT = """
上一轮反思识别出以下缺口：
{gaps}

请针对每个缺口给出更具体的检索策略：
- 缺口 1：用什么查询字符串？什么 scope？
- 缺口 2：是否有备选工具？（如 Grep 失败时走 WebFetch）
- 缺口 3：是否需要先 JIT 抓取再继续反思？
"""

# ==== 反思输出解析 ====

@dataclass
class Gap:
    """反思识别出的缺口。"""
    info_point: str                 # 信息点描述
    status: Literal["COVERED", "PARTIAL", "MISSING"]
    gap_detail: str = ""            # 部分缺失时的具体缺失内容
    tool_hint: str = ""             # 建议工具 (Grep / WebFetch / Bash)
    query_hint: str = ""            # 建议查询字符串

@dataclass
class ReflectionResult:
    """反思输出结构化结果。"""
    needed: list[Gap] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    raw_output: str = ""

    @property
    def missing_gaps(self) -> list[Gap]:
        """仅返回 MISSING 状态的缺口（需触发抓取）。"""
        return [g for g in self.needed if g.status == "MISSING"]

    @property
    def partial_gaps(self) -> list[Gap]:
        return [g for g in self.needed if g.status == "PARTIAL"]


# ==== 正则解析 ====

NEEDED_LINE_PATTERN = re.compile(
    r"-\s*\[(COVERED|PARTIAL|MISSING)\]\s*(.+?)(?:\s*\(source:\s*(.+?)\))?(?:\s*\(gap:\s*(.+?)\))?(?:\s*\(tool:\s*(.+?),\s*query:\s*(.+?)\))?$"
)
CONFIDENCE_PATTERN = re.compile(r"CONFIDENCE:\s*([0-9.]+)")
REASON_PATTERN = re.compile(r"REASON:\s*(.+?)$", re.MULTILINE)


def parse_reflection(text: str) -> ReflectionResult:
    """解析 Agent 输出的反思文本为结构化 ReflectionResult。"""
    result = ReflectionResult(raw_output=text)

    # 1. 解析 NEEDED 块
    in_needed = False
    for line in text.splitlines():
        if line.strip().startswith("- NEEDED:"):
            in_needed = True
            continue
        if in_needed:
            if line.strip().startswith("- CONFIDENCE:"):
                in_needed = False
                break
            m = NEEDED_LINE_PATTERN.match(line)
            if m:
                status, info, source, gap, tool, query = m.groups()
                result.needed.append(Gap(
                    info_point=info.strip(),
                    status=status,  # type: ignore[arg-type]
                    gap_detail=(gap or "").strip(),
                    tool_hint=(tool or "").strip(),
                    query_hint=(query or "").strip(),
                ))

    # 2. 解析 CONFIDENCE
    cm = CONFIDENCE_PATTERN.search(text)
    if cm:
        try:
            result.confidence = float(cm.group(1))
        except ValueError:
            result.confidence = 0.0

    # 3. 解析 REASON
    rm = REASON_PATTERN.search(text)
    if rm:
        result.reason = rm.group(1).strip()

    return result
```

#### 1.7.2 反思触发器（P161-B）

```python
# extensions/emergent/triggers.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Literal, Any

TriggerKind = Literal["task_start", "decision_point", "user_requested", "periodic"]

@dataclass
class TriggerEvent:
    """触发反思的事件。"""
    kind: TriggerKind
    task: str
    current_context_summary: str
    turn_id: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class EmergentTrigger(Protocol):
    """反思触发器协议 — 实现此协议即可注册。"""
    name: str

    def should_trigger(self, event: TriggerEvent) -> bool: ...


# ==== 内置触发器 ====

class OnTaskStartTrigger:
    """任务开始时触发反思。"""
    name = "OnTaskStartTrigger"

    def should_trigger(self, event: TriggerEvent) -> bool:
        return event.kind == "task_start"


class OnDecisionPointTrigger:
    """关键决策点触发反思。"""
    name = "OnDecisionPointTrigger"

    # 决策点关键词
    DECISION_KEYWORDS = [
        "decide", "deciding", "decision", "采用", "选择", "决定", "建议",
        "implement", "deploy", "refactor", "重构", "实现", "部署",
    ]

    def should_trigger(self, event: TriggerEvent) -> bool:
        if event.kind != "decision_point":
            return False
        task_lower = event.task.lower()
        return any(kw in task_lower for kw in self.DECISION_KEYWORDS)


class PeriodicTrigger:
    """长任务周期触发反思（每 N turn 一次）。"""
    name = "PeriodicTrigger"

    def __init__(self, interval_turns: int = 5) -> None:
        self._interval = interval_turns
        self._last_triggered_turn = 0

    def should_trigger(self, event: TriggerEvent) -> bool:
        if event.kind != "decision_point":
            return False
        return (event.turn_id - self._last_triggered_turn) >= self._interval


# ==== 触发器注册表 ====

_triggers: list[EmergentTrigger] = []

def register_trigger(trigger: EmergentTrigger) -> None:
    _triggers.append(trigger)

def get_active_triggers(event: TriggerEvent) -> list[EmergentTrigger]:
    """获取所有应当触发的触发器。"""
    return [t for t in _triggers if t.should_trigger(event)]
```

#### 1.7.3 反思 → F-159 JIT 桥接（P161-C）

```python
# extensions/emergent/bridge.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .prompts import ReflectionResult, Gap, EMERGENT_GAP_PROMPT


@dataclass
class BridgeResult:
    """反思 → JIT 桥接结果。"""
    synthesized_sections: list[str] = field(default_factory=list)
    skipped_gaps: list[Gap] = field(default_factory=list)
    failed_gaps: list[Gap] = field(default_factory=list)
    total_duration_ms: float = 0.0

    @property
    def has_jit_synthesis(self) -> bool:
        return bool(self.synthesized_sections)


def bridge_to_jit(
    reflection: ReflectionResult,
    *,
    priority: int = 5,
) -> BridgeResult:
    """把反思识别出的 MISSING 缺口桥接到 F-159 synthesize(intent)。

    Args:
        reflection: 反思结构化结果
        priority: 分配给所有 intent 的优先级

    Returns:
        BridgeResult 含已合成的 section_id 列表 + 跳过 / 失败的缺口

    Note:
        依赖注入 F-159 synthesize 函数；未注入时降级为 no-op（仅返回 skipped_gaps）。
        实际部署时由 clawcodex_ext/__init__.py 注入 F-159 的真实实现。
    """
    from extensions.jit_context.intent_router import Intent
    from extensions.jit_context.synthesizer import synthesize
    from extensions.jit_context.rate_limiter import RateLimitExceeded

    result = BridgeResult()
    started = time.monotonic() if (_time := _get_time()) else 0.0

    missing = reflection.missing_gaps
    if not missing:
        return result

    for gap in missing:
        # 构造 Intent
        intent = Intent(
            kind=_infer_kind_from_tool(gap.tool_hint),
            target=gap.info_point,
            hint=gap.query_hint,
            priority=priority,
            scope="project",
            requested_by="emergent",  # 标注触发来源
        )

        try:
            jr = synthesize(intent)
            result.synthesized_sections.append(jr.section_id)
        except RateLimitExceeded:
            # 限流：跳过该缺口，记入 skipped
            result.skipped_gaps.append(gap)
        except RuntimeError:
            # 抓取失败：记入 failed
            result.failed_gaps.append(gap)

    result.total_duration_ms = (_get_time()() - started) * 1000 if _get_time() else 0.0
    return result


def _infer_kind_from_tool(tool_hint: str) -> str:
    """从 gap.tool_hint 推断 IntentKind。"""
    t = (tool_hint or "").lower()
    if "webfetch" in t or "doc" in t or "官方" in t:
        return "doc_check"
    if "bash" in t or "env" in t or "version" in t:
        return "env_inspect"
    if "grep" in t or "support" in t or "use" in t or "用" in t:
        return "fact_verify"
    return "code_lookup"


# 时间函数（便于测试 mock）
import time as _time_module
def _get_time():
    return _time_module.monotonic
```

#### 1.7.4 反思结果缓存（P161-D）

```python
# extensions/emergent/cache.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import hashlib
import time
from collections import OrderedDict

from .prompts import ReflectionResult


@dataclass
class CacheEntry:
    """单条反思缓存。"""
    key: str
    reflection: ReflectionResult
    bridge_sections: list[str]        # 桥接时已合成的 sections
    created_at: float
    ttl_seconds: float
    hit_count: int = 0

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class ReflectionCache:
    """反思结果缓存 — 避免重复反思同一任务。

    key = hash(task_kind + current_context_summary)
    """

    def __init__(self, *, capacity: int = 32, default_ttl: float = 300.0) -> None:
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._capacity = capacity
        self._default_ttl = default_ttl

    @staticmethod
    def make_key(task: str, context_summary: str) -> str:
        """稳定 key — task 类别 + 上下文摘要哈希。"""
        # 简化：用 task 前 50 字符 + context_summary hash
        task_prefix = task[:50].lower().strip()
        ctx_hash = hashlib.sha256(context_summary.encode("utf-8")).hexdigest()[:16]
        raw = f"{task_prefix}\x00{ctx_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def get(self, key: str) -> CacheEntry | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self._store[key]
            return None
        entry.hit_count += 1
        self._store.move_to_end(key)
        return entry

    def put(
        self,
        key: str,
        reflection: ReflectionResult,
        bridge_sections: list[str],
        *,
        ttl: float | None = None,
    ) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = CacheEntry(
            key=key,
            reflection=reflection,
            bridge_sections=bridge_sections,
            created_at=time.time(),
            ttl_seconds=ttl if ttl is not None else self._default_ttl,
        )
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "size": len(self._store),
            "capacity": self._capacity,
            "hit_total": sum(e.hit_count for e in self._store.values()),
        }


_session_cache: ReflectionCache | None = None

def get_cache() -> ReflectionCache:
    global _session_cache
    if _session_cache is None:
        _session_cache = ReflectionCache()
    return _session_cache

def reset_cache() -> None:
    global _session_cache
    _session_cache = None
```

#### 1.7.5 信心评分门控（P161-E）

```python
# extensions/emergent/confidence.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .prompts import ReflectionResult


@dataclass
class ConfidenceGateResult:
    """信心门控决策。"""
    confidence: float
    should_force_jit: bool            # 是否强制触发 JIT
    should_ask_user: bool             # 是否应询问用户
    reason: str

    @property
    def decision(self) -> Literal["PROCEED", "FORCE_JIT", "ASK_USER", "BLOCK"]:
        if self.should_ask_user:
            return "ASK_USER"
        if self.should_force_jit:
            return "FORCE_JIT"
        if self.confidence < 0.3:
            return "BLOCK"
        return "PROCEED"


def evaluate_confidence(
    reflection: ReflectionResult,
    *,
    force_jit_threshold: float = 0.7,
    ask_user_threshold: float = 0.4,
) -> ConfidenceGateResult:
    """基于反思输出的 confidence + 缺口数量做门控决策。

    阈值策略：
    - confidence < 0.4 → ASK_USER（让用户确认是否继续）
    - 0.4 ≤ confidence < 0.7 → FORCE_JIT（强制触发 JIT 抓取后再回答）
    - confidence ≥ 0.7 且无 MISSING → PROCEED（直接回答）

    Args:
        reflection: 反思结构化结果
        force_jit_threshold: 低于此值触发 FORCE_JIT
        ask_user_threshold: 低于此值触发 ASK_USER
    """
    confidence = reflection.confidence
    missing_count = len(reflection.missing_gaps)
    partial_count = len(reflection.partial_gaps)

    # 启发式 1：MISSING 缺口 ≥ 3 → 必触发 FORCE_JIT
    if missing_count >= 3:
        return ConfidenceGateResult(
            confidence=confidence,
            should_force_jit=True,
            should_ask_user=False,
            reason=f"识别到 {missing_count} 个 MISSING 缺口，超过 3 个强制抓取阈值",
        )

    # 启发式 2：confidence 极低 → BLOCK
    if confidence < ask_user_threshold:
        return ConfidenceGateResult(
            confidence=confidence,
            should_force_jit=False,
            should_ask_user=True,
            reason=f"confidence {confidence:.2f} < {ask_user_threshold}，请用户确认是否继续",
        )

    # 启发式 3：confidence 低于 force 阈值但有缺口 → FORCE_JIT
    if confidence < force_jit_threshold and (missing_count > 0 or partial_count > 0):
        return ConfidenceGateResult(
            confidence=confidence,
            should_force_jit=True,
            should_ask_user=False,
            reason=f"confidence {confidence:.2f} < {force_jit_threshold} 且存在缺口，强制触发 JIT",
        )

    # 默认：PROCEED
    return ConfidenceGateResult(
        confidence=confidence,
        should_force_jit=False,
        should_ask_user=False,
        reason="confidence 充分且无严重缺口，直接回答",
    )
```

#### 1.7.6 Hook 集成（自动触发）

```python
# extensions/emergent/hooks.py
from __future__ import annotations

from typing import Any
import time

from .prompts import EMERGENT_DISCOVERY_PROMPT, parse_reflection
from .triggers import TriggerEvent, get_active_triggers
from .bridge import bridge_to_jit
from .cache import get_cache, ReflectionCache
from .confidence import evaluate_confidence


def install_emergent_hooks(hook_registry: Any) -> None:
    """向 F-102 LoopHook 注册 pre_turn_hook + pre_decision_hook。"""
    from extensions.jit_context.synthesizer import synthesize as jit_synthesize
    from extensions.jit_context.intent_router import Intent

    @hook_registry.register("pre_turn_hook")
    def _maybe_reflect_on_task_start(
        task: str, current_context_summary: str, turn_id: int = 0, **_kw: Any
    ) -> dict:
        """任务开始 turn 触发反思。"""
        event = TriggerEvent(
            kind="task_start",
            task=task,
            current_context_summary=current_context_summary,
            turn_id=turn_id,
        )
        active = get_active_triggers(event)
        if not active:
            return {"emergent_triggered": False}

        # 1. 缓存命中检查
        cache = get_cache()
        key = ReflectionCache.make_key(task, current_context_summary)
        cached = cache.get(key)
        if cached is not None:
            # 缓存命中：复用之前的反思 + 桥接
            bridge = bridge_to_jit(cached.reflection)
            return {
                "emergent_triggered": True,
                "cache_hit": True,
                "synthesized_sections": bridge.synthesized_sections,
            }

        # 2. 缓存未命中：返回反思 prompt，让 Agent 在本 turn 输出反思
        return {
            "emergent_triggered": True,
            "cache_hit": False,
            "reflection_prompt": EMERGENT_DISCOVERY_PROMPT.format(
                task=task,
                current_context_summary=current_context_summary,
            ),
        }

    @hook_registry.register("post_reflection_hook")
    def _on_reflection_complete(
        reflection_text: str, task: str, current_context_summary: str, **_kw: Any
    ) -> dict:
        """Agent 输出反思后被调用 — 解析 + 桥接 + 缓存。"""
        reflection = parse_reflection(reflection_text)
        bridge = bridge_to_jit(reflection)
        gate = evaluate_confidence(reflection)

        # 写缓存
        cache = get_cache()
        key = ReflectionCache.make_key(task, current_context_summary)
        cache.put(key, reflection, bridge.synthesized_sections)

        return {
            "reflection_parsed": True,
            "missing_count": len(reflection.missing_gaps),
            "partial_count": len(reflection.partial_gaps),
            "confidence": reflection.confidence,
            "gate_decision": gate.decision,
            "synthesized_sections": bridge.synthesized_sections,
            "skipped_gaps": len(bridge.skipped_gaps),
            "failed_gaps": len(bridge.failed_gaps),
        }

    @hook_registry.register("pre_decision_hook")
    def _maybe_reflect_on_decision(
        task: str, current_context_summary: str, turn_id: int = 0, **_kw: Any
    ) -> dict:
        """关键决策点 turn 触发反思（复用 OnDecisionPointTrigger 逻辑）。"""
        event = TriggerEvent(
            kind="decision_point",
            task=task,
            current_context_summary=current_context_summary,
            turn_id=turn_id,
        )
        active = get_active_triggers(event)
        if not active:
            return {"emergent_triggered": False}
        # 行为同 _maybe_reflect_on_task_start（DRY：可重构为公共函数）
        return _maybe_reflect_on_task_start(
            task=task,
            current_context_summary=current_context_summary,
            turn_id=turn_id,
        )
```

#### 1.7.7 预注入 section

```python
# extensions/emergent/section_injector.py
"""通过 F-119 register_section 把涌现反思指南注入 system prompt。"""
from __future__ import annotations

from typing import Any


EMERGENT_GUIDE_SECTION = """
## Emergent Context Discovery（涌现式上下文发现）

### 核心原则
不要预设你"什么都知道"。在任务开始或关键决策点，主动反思：
"要完成此任务我需要哪些信息？当前上下文覆盖了哪些？缺哪些？"

### 何时触发
- 任务开始（首 turn）— 必须反思一次
- 关键决策点（采用 X / 重构 / 部署 / 实现）— 自动触发反思
- 长任务每 5 turn 周期反思一次

### 反思要求（4 个问题）
1. 需要哪些信息（3-5 个关键点）？
2. 当前上下文覆盖了哪些 / 缺哪些（COVERED / PARTIAL / MISSING）？
3. 对每个缺口用什么工具检索？
4. 信心评分（0-1）；< 0.7 必须列出缺口

### 输出格式
```
### Reflection
- NEEDED:
  - [COVERED] ... (source: ...)
  - [PARTIAL]  ... (gap: ...)
  - [MISSING]  ... (tool: Grep/WebFetch/Bash, query: ...)
- CONFIDENCE: 0.X
- REASON: ...
```

### 与 F-159 JIT 协同
- 反思识别出的 MISSING 缺口会自动调用 F-159 `synthesize(intent)` 执行抓取
- 抓取结果作为动态 section 注入到下次 query

### 与 F-160 反事实协同
- 反思时同步做反事实检查（"如果我错了，最可能错在哪"）
- 缺口列表应包含反事实推理
"""


def register_emergent_section() -> str:
    """通过 F-119 register_section 注入涌现反思指南。"""
    from clawcodex_ext.context_system.section_registry import register_section

    section_id = "emergent_discovery_guide"

    def _builder(_ctx: Any) -> str:
        return EMERGENT_GUIDE_SECTION

    register_section(
        section_id,
        builder=_builder,
        order=75,                       # 介于 F-158 (60) 与 F-160 (80) 之间
        cache_scope="session",
        tags=["emergent", "discovery", "meta-cognition"],
    )
    return section_id
```

### 1.8 核心流程

```
[新任务 "实现 X 模块的错误处理"]
  ↓
[F-102 pre_turn_hook 触发]
  ↓
P161-B OnTaskStartTrigger.should_trigger(event) → True
  ↓
P161-D cache.get(key) → 未命中（首次）
  ↓
[F-119 emergent_discovery_guide section 已在 system prompt 中]
  ↓
[Agent 看到反思指南 → 输出反思]
  ↓
reflection_text = """
### Reflection
- NEEDED:
  - [COVERED] X 模块结构 (source: Read src/x.py)
  - [PARTIAL]  错误处理约定 (gap: 仅看到 try/except，无 retry 策略)
  - [MISSING]  项目错误处理统一风格 (tool: Grep, query: "raise|except|retry")
  - [MISSING]  X 模块上游调用约定 (tool: Grep, query: "from .x import")
- CONFIDENCE: 0.5
- REASON: 2 个 MISSING 缺口未覆盖
"""
  ↓
P161-A parse_reflection(text) → ReflectionResult(confidence=0.5, missing_gaps=[...])
  ↓
P161-C bridge_to_jit(reflection)
  → 遍历 2 个 MISSING → Intent → F-159 synthesize(intent)
  → synthesized_sections=["jit_code_lookup_xxxxxxxx", "jit_code_lookup_yyyyyyyy"]
  ↓
P161-E evaluate_confidence(reflection) → FORCE_JIT (confidence=0.5 < 0.7)
  ↓
P161-D cache.put(key, reflection, bridge_synthesized)
  ↓
[F-119 下次 query 时把 jit_* sections 注入到 system prompt]
  ↓
[Agent 基于更完整的 context 重新回答]
```

### 1.9 与现有架构的对齐

| 维度 | 现状 | F-161 落地后 |
|------|------|-------------|
| "不知道自己不知道" | ❌ 模型假装全知 | ✅ 反思 prompt 强制列出缺口 |
| 抓取触发 | F-159 显式 | ✅ F-161 隐式反思 + 调用 F-159 |
| 反思结果复用 | ❌ 每次重新反思 | ✅ ReflectionCache 缓存 |
| 信心评分 | ❌ 无 | ✅ 4 档门控决策（PROCEED / FORCE_JIT / ASK_USER / BLOCK） |
| 与 F-119 协同 | — | ✅ register_section 注入反思指南 |
| 与 F-102 协同 | — | ✅ pre_turn_hook / post_reflection_hook 集成 |
| 与 F-159 协同 | — | ✅ P161-C 调用 synthesize(intent) |
| 与 F-130 协同 | — | ✅ 多次 FORCE_JIT 未解决 → 触发 debug Profile 切换 |
| 与 F-158 协同 | — | ✅ 抓取结果可作 VERIFIED source |
| 与 F-160 协同 | — | ✅ 反思 prompt 含反事实检查步骤 |
| 解耦合规 | — | ✅ 零 `src/` 改动 |

### 1.10 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 模型"假反思" | 泛泛而谈，列不出具体缺口 | 强制 4 个问题具体格式；ReflectionCache 监控命中率，<50% 触发告警 |
| 反思消耗 token | 长任务成本上升 | 缓存 + 周期触发（每 5 turn 一次）；任务开始 + 决策点 |
| 信心评分主观 | 模型可能高估 confidence | 缺口数量阈值覆盖（MISSING ≥ 3 强制 FORCE_JIT）；F-158 VERIFIED 校验 |
| 反复反思陷入循环 | Agent 无法跳出 | F-130 Profile 切换：多次反思未解决 → debug Profile；max_reflection_turns 上限 |
| Bridge 调用 F-159 失败 | 抓取失败导致反思无效 | skipped_gaps + failed_gaps 记录；下次 turn 自动重试 |
| 与 F-160 反事实冲突 | 反思 prompt 同时要求反事实检查 | F-161 反思 prompt 明确"缺口列表应包含反事实推理"——是协同而非冲突 |
| 反思触发频率失控 | 每个 turn 都反思 | OnTaskStartTrigger 仅 task_start；OnDecisionPointTrigger 仅决策点；PeriodicTrigger 默认 5 turn 间隔 |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|----------|
| 2026-07-22 | 初始创建 | 本文档 | 与 F-130 / F-158 / F-159 / F-160 格式对齐；映射到 DC-A §4.4 F-161 |

### 2.2 待验证项

- P161-A `EMERGENT_DISCOVERY_PROMPT` 含 4 个反思问题 + 输出格式 + 反事实协同说明
- P161-A `parse_reflection` 正则匹配 NEEDED / CONFIDENCE / REASON 三类输出
- P161-B `OnTaskStartTrigger.should_trigger(task_start)` 返回 True
- P161-B `OnDecisionPointTrigger.should_trigger(decision_point + 含决策关键词)` 返回 True
- P161-B `PeriodicTrigger.should_trigger(间隔 5 turn)` 正确触发
- P161-C `bridge_to_jit` 对每个 MISSING gap 构造 Intent + 调用 synthesize
- P161-C 限流时 gap 进入 skipped_gaps；抓取失败时进入 failed_gaps
- P161-D `ReflectionCache.make_key(task, context_summary)` 稳定哈希
- P161-D 缓存命中时跳过反思，直接复用之前的 bridge_sections
- P161-E `evaluate_confidence` 4 档决策正确（PROCEED / FORCE_JIT / ASK_USER / BLOCK）
- P161-E MISSING ≥ 3 强制 FORCE_JIT
- 端到端：触发 → 反思 → 缺口 → JIT 抓取 → 重新回答
- 稳定性门禁全量（Stage 1-5 + 7-9）通过
- Orchestrator 单元测试（排除 `manual_e2e_f38.py`）通过

---

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `EMERGENT_DISCOVERY_PROMPT` 含 4 反思问题 + 输出格式 + 反事实协同说明 | 📋 |
| 2 | `EMERGENT_GAP_PROMPT` 缺口补充 prompt 完整 | 📋 |
| 3 | `Gap` / `ReflectionResult` dataclass 字段齐全 | 📋 |
| 4 | `parse_reflection` 正确解析 NEEDED / CONFIDENCE / REASON 三类输出 | 📋 |
| 5 | `ReflectionResult.missing_gaps` / `partial_gaps` 属性过滤正确 | 📋 |
| 6 | `EmergentTrigger` Protocol 含 name + should_trigger 两个方法 | 📋 |
| 7 | 3 个内置触发器（OnTaskStart / OnDecisionPoint / Periodic）实现 Protocol | 📋 |
| 8 | `register_trigger` + `get_active_triggers` 注册表工作正常 | 📋 |
| 9 | `bridge_to_jit` 对每个 MISSING gap 构造 Intent + 调用 F-159 synthesize | 📋 |
| 10 | `bridge_to_jit` 限流时 gap 进入 skipped_gaps；抓取失败时进入 failed_gaps | 📋 |
| 11 | `BridgeResult.has_jit_synthesis` 属性正确 | 📋 |
| 12 | `ReflectionCache.make_key(task, context_summary)` 稳定哈希 | 📋 |
| 13 | `ReflectionCache` 支持 LRU 淘汰 + TTL 过期 | 📋 |
| 14 | `evaluate_confidence` 4 档决策（PROCEED / FORCE_JIT / ASK_USER / BLOCK）正确 | 📋 |
| 15 | `evaluate_confidence` MISSING ≥ 3 强制 FORCE_JIT | 📋 |
| 16 | `evaluate_confidence` confidence < ask_user_threshold 触发 ASK_USER | 📋 |
| 17 | `register_emergent_section` 通过 F-119 register_section 注册，section_id="emergent_discovery_guide" | 📋 |
| 18 | `install_emergent_hooks` 向 F-102 hook_registry 注册 pre_turn_hook + post_reflection_hook + pre_decision_hook | 📋 |
| 19 | 5 子特性在 `import extensions.emergent` 时自动注册 | 📋 |
| 20 | 稳定性门禁 + 涌现 E2E 测试通过 | 📋 |

### 3.2 落地路径（推荐顺序）

1. **P161-A 先行** — 反思 prompt 模板 + 解析函数（纯函数 + dataclass，立即可测）
2. **P161-B 紧随** — 3 个内置触发器 + 注册表
3. **P161-D 并行** — ReflectionCache（与 P161-A 独立）
4. **P161-C 收尾** — bridge_to_jit 调用 F-159 synthesize（依赖 P161-A + P161-B）
5. **P161-E 收尾** — evaluate_confidence 门控决策（依赖 P161-A 的 ReflectionResult）
6. **P161-F (预留，依赖 F-130 Profile)** — 多次反思未解决 → 自动切换 debug Profile

### 3.3 与 F-119 / F-159 / F-160 / F-158 / F-130 的协同点

- **F-119 `register_section`** → P161-A 把 `emergent_discovery_guide` 注入到 system prompt（order=75，介于 F-158 与 F-160 之间）
- **F-102 Hook `pre_turn_hook`** → P161-B `OnTaskStartTrigger` 自动触发反思
- **F-102 Hook `post_reflection_hook`** → P161-A parse + P161-C bridge + P161-E gate
- **F-159 `synthesize(intent)`** → P161-C 调用 F-159 执行实际抓取
- **F-159 `SynthesisCache`** → 抓取结果自然复用 F-159 缓存
- **F-158-A `ConfidenceMarker.source`** → emergent 抓取结果可作为 VERIFIED source
- **F-160 反事实** → emergent 反思 prompt 明确"缺口列表应包含反事实推理"
- **F-130 Profile 切换** → P161-F 多次反思未解决 → 切换 debug Profile（远期）

### 3.4 与 F-159 显式触发层的关系

| 维度 | F-159 (显式) | F-161 (隐式) |
|------|--------------|--------------|
| 触发方式 | Agent "我需要 X" / 用户 /context X | Agent 主动反思"我可能需要 X" |
| 调用方 | Agent / 用户 / Hook | Agent（meta-cognition） |
| 抓取执行 | synthesize(intent) | bridge_to_jit → synthesize(intent) |
| 缓存维度 | (intent.target, scope, hint) | (task, context_summary) |
| Token 成本 | 0（直接 API） | 1 次 LLM 反思调用 |
| 适用场景 | 用户明确需求 | 用户未明确但 Agent 应主动发现 |

两者是互补关系：F-159 处理"已知需求"，F-161 处理"潜在需求"。

---

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-22 | 初始创建 | DC-A §4.4 映射表基础上落地 F-161 涌现式上下文发现；覆盖 DC-018；Wave 1 P0 最后一个落地 F-N；是 F-159 JIT 的隐式反思调度层（meta-cognition 显式化）；与 F-119 / F-102 / F-159 / F-158 / F-160 / F-130 协同；解耦落地于 `extensions/emergent/`，零 `src/` 侵入 |