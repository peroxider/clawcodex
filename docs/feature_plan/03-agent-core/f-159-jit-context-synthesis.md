# F-159: JIT 上下文合成 — 按需生成切断"假装知道"幻觉源头

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-159-jit-context-synthesis.md`
> 最后更新: 2026-07-22
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-003

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 1 上下文生命周期特性（P0，~1-2 周可落地） |
| 覆盖 DC | DC-003 JIT 上下文合成（与 DC-009 / DC-006 / DC-018 强协同） |
| 前置依赖 | F-119 Section Registry（register_section）、F-102 Hook 扩展点 |
| 协同 | F-130 Profile 模板占位符填充、F-158-A VERIFIED source、F-161 涌现发现（下游） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/jit_context/`，零 `src/` 侵入 |
| 落地形态 | Intent Router + Loader 集合 + 结果缓存 + 动态 Section 注册 + 触发限流 |

---

## §1 设计规划

### 1.1 背景

当前 Agent 的"上下文"在会话启动时基本一次性预加载——system prompt 拼装完成后，无论 Agent 是否真正需要该上下文，token 已消耗；同时 Agent 对"未预加载"的内容只能凭训练知识"假装知道"，直接成为幻觉源头。

**F-119 已提供 Section Registry**（零件可插拔），但缺乏"零件按需生成"的机制：
- **何时触发** — 模型不知道何时该"主动要"
- **如何抓取** — 没有统一的 loader 接口
- **如何缓存** — 同一意图反复抓取浪费 token
- **如何注入** — 抓取结果未与 system prompt 联动
- **如何限流** — 模型过度触发导致延迟膨胀

F-159 在 F-119 基础上提供 **JIT (Just-In-Time) 上下文合成**机制：当 Agent 显式声明需求 / 用户主动指定 / 检测到知识缺口时，按需抓取、缓存、注入到下次 query 的上下文。

### 1.2 目标

- 切断"假装知道"幻觉源头——未加载即不可断言
- 提供 `RequestContext(intent, hint)` API — Agent / Hook / 用户主动触发
- 基于意图路由到对应 loader（Grep / WebFetch / Bash）
- 按 `(intent, scope)` 缓存合成结果，避免重复抓取
- 抓取结果通过 F-119 `register_section` 注入到 system prompt
- 单次会话上限 + 优先级队列，避免延迟膨胀

### 1.3 非目标 (Out of Scope)

- 不替代任何已有 F-N 核心实现
- 不引入新的 prompt 拼接机制（复用 F-119）
- 不立即做"模型自主反思需求"（这是 F-161 涌现式上下文发现的职责，F-159 仅承载显式触发层）
- 不做跨会话缓存（依赖 F-166 记忆分层，先落地会话内缓存）

### 1.4 子特性分解

| 编号 | 子特性 | 状态 | 工时 |
|:----:|--------|:----:|:----:|
| P159-A | Intent 解析与路由 | 📋 | 1-2d |
| P159-B | Loader 集合（Grep / WebFetch / Bash） | 📋 | 2-3d |
| P159-C | 合成结果缓存（`(intent, scope)` 维度） | 📋 | 1d |
| P159-D | 动态 Section 注册（F-119 联动） | 📋 | 1d |
| P159-E | 触发限流（单会话上限 + 优先级队列） | 📋 | 1d |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-119 Section Registry | **强协同** | P159-D 通过 `register_section` 把合成结果注入到下次 query 的 system prompt |
| F-102 Hook 扩展点 | **强协同** | `post_query_hook` 检测"我需要 X"类表达并自动触发 JIT |
| F-158 抗幻觉基线协议 | **协同** | JIT 抓取结果可作为 F-158-A `ConfidenceMarker.source`（VERIFIED 的证据） |
| F-130 Profile 模板 | **协同** | P159-A 抓取的摘要可填充 F-130 Profile 模板的 `{{placeholder}}` |
| F-161 涌现式上下文发现（Wave 1 后续） | **下游** | F-161 的"反思 prompt"调用 F-159 API 执行抓取 |
| F-166 记忆分层（Wave 2 远期） | **远期** | P159-C 跨会话缓存的存储后端 |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/jit_context/__init__.py` | — | 子系统入口，注册 router / loaders / cache / limiter |
| `extensions/jit_context/intent_router.py` | P159-A | `Intent` dataclass + `parse_intent(text)` + `RequestContext(intent, hint)` API |
| `extensions/jit_context/loaders.py` | P159-B | `Loader` Protocol + `GrepLoader` / `WebFetchLoader` / `BashLoader` + `register_loader` |
| `extensions/jit_context/cache.py` | P159-C | `SynthesisCache` 类（`(intent, scope)` key + LRU + TTL） |
| `extensions/jit_context/synthesizer.py` | P159-D | `synthesize(intent)` → 调 loader → 摘要 → `register_section` |
| `extensions/jit_context/rate_limiter.py` | P159-E | `RateLimiter`（token bucket / session 配额 + 优先级队列） |
| `extensions/jit_context/hooks.py` | 全部 | `post_query_hook` 检测 JIT 触发 + 调度 |
| `extensions/jit_context/capabilities.py` | — | Protocol 接口契约（`Loader` / `Cache` / `RateLimiter`） |
| `tests/jit_context/test_intent_router.py` | P159-A | intent 解析 + 路由表 |
| `tests/jit_context/test_loaders.py` | P159-B | Grep / WebFetch / Bash loader mock |
| `tests/jit_context/test_cache.py` | P159-C | LRU + TTL + key 命中 |
| `tests/jit_context/test_rate_limiter.py` | P159-E | token bucket + 优先级 |
| `tests/jit_context/test_e2e.py` | 全部 | 端到端：trigger → loader → cache → register_section → 下次 query |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_jit_context_extensions()` 在 import 时注册 router / loaders / cache / limiter |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | `post_query_hook` 中追加 `jit_context.maybe_trigger` |
| `clawcodex_ext/context_system/section_registry.py` | 暴露 `register_section` 给 F-159 调用（已存在） |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.jit_context` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-159 |
| `docs/feature_plan/dynamic-context-index.md` | DC→F 映射、依赖与全局验收总则 |

### 1.7 核心 API 设计

#### 1.7.1 Intent 解析与路由（P159-A）

```python
# extensions/jit_context/intent_router.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Any
import re

IntentKind = Literal["code_lookup", "doc_check", "fact_verify", "env_inspect", "user_specified"]

@dataclass
class Intent:
    """JIT 抓取意图。"""
    kind: IntentKind            # 意图类别
    target: str                 # 抓取目标（如 "项目错误处理约定" / "FastAPI 0.110 签名"）
    hint: str = ""              # 补充提示（用户/Agent 给出的关键词）
    priority: int = 5           # 1 (low) ~ 9 (high)
    scope: Literal["project", "global", "ephemeral"] = "project"
    requested_by: Literal["agent", "user", "hook"] = "agent"
    source_text: str = ""       # 触发该 intent 的原始文本

# 触发模式：模型"我需要 X" / 用户"/context X" / 检测到知识缺口
TRIGGER_PATTERNS = [
    (re.compile(r"我需要(?:了解|看|确认)?\s*(.+?)(?:[,。！？]|$)"), "agent"),
    (re.compile(r"need\s+(?:to\s+)?(?:check|know|see)\s+(?:about\s+)?(.+?)(?:[.!?]|$)", re.IGNORECASE), "agent"),
    (re.compile(r"^/context\s+(.+)$", re.MULTILINE), "user"),
    (re.compile(r"^!ctx\s+(.+)$", re.MULTILINE), "user"),
]

# Intent → Loader 路由表（按 kind 匹配）
ROUTING_TABLE: dict[IntentKind, str] = {
    "code_lookup": "GrepLoader",
    "doc_check": "WebFetchLoader",
    "fact_verify": "GrepLoader",      # 先 Grep 项目内，未命中走 WebFetch
    "env_inspect": "BashLoader",
    "user_specified": "GrepLoader",   # 默认 Grep；可被 hint 覆盖
}


def parse_intent(text: str) -> Intent | None:
    """从文本中解析一个 Intent；返回 None 表示未识别。

    解析策略：
    1. 优先匹配 user_specified 模式（/context / !ctx 前缀）
    2. 其次匹配 agent 自发声明（"我需要 X" / "need X"）
    3. kind 由目标关键词启发式分类（如含 "API / 文档" → doc_check）
    """
    for pattern, requested_by in TRIGGER_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        target = m.group(1).strip()
        if not target:
            continue
        kind = _classify_target(target)
        return Intent(
            kind=kind,
            target=target,
            requested_by=requested_by,  # type: ignore[arg-type]
            source_text=text[max(0, m.start() - 20):m.end() + 20],
        )
    return None


def _classify_target(target: str) -> IntentKind:
    """基于目标关键词启发式分类 intent kind。"""
    t = target.lower()
    if any(kw in t for kw in ["api", "文档", "docs", "documentation", "signature", "签名"]):
        return "doc_check"
    if any(kw in t for kw in ["环境", "env", "python version", "node version", "系统"]):
        return "env_inspect"
    if any(kw in t for kw in ["用没用", "有没有", "support", "use", "支持", "依赖"]):
        return "fact_verify"
    return "code_lookup"


# ==== 主动请求 API ====

def request_context(intent: Intent | str, *, hint: str = "") -> Intent:
    """Agent / 用户 / Hook 主动请求 JIT 合成。

    Args:
        intent: Intent 实例，或字符串（自动 parse_intent）
        hint: 补充关键词

    Returns:
        标准化后的 Intent（含优先级 + scope）
    """
    if isinstance(intent, str):
        parsed = parse_intent(intent)
        if parsed is None:
            # 兜底：作为 code_lookup 处理
            parsed = Intent(
                kind="user_specified",
                target=intent,
                hint=hint,
                requested_by="user",
            )
        else:
            parsed.hint = parsed.hint or hint
        intent = parsed
    return intent
```

#### 1.7.2 Loader 集合（P159-B）

```python
# extensions/jit_context/loaders.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Any, Callable
from .intent_router import Intent

@dataclass
class LoadResult:
    """Loader 抓取结果。"""
    content: str                # 抓取内容（已摘要或原文）
    excerpt: str = ""           # 关键片段（注入 system prompt 用）
    source: str = ""            # 文件路径 / URL / 命令输出
    raw_size: int = 0           # 原始字节数
    truncated: bool = False     # 是否截断

# ==== Loader Protocol ====

class Loader(Protocol):
    """Loader 接口契约 — 每种抓取源实现此协议即可被注册。"""
    name: str

    def can_handle(self, intent: Intent) -> bool: ...

    def load(self, intent: Intent, *, max_bytes: int = 4096) -> LoadResult: ...

# ==== 内置 Loader ====

class GrepLoader:
    """项目内代码 / 文件检索 loader。"""
    name = "GrepLoader"

    def __init__(self, grep_fn: Callable | None = None) -> None:
        # 依赖注入而非直接 import 上游工具，保持解耦
        self._grep = grep_fn or _default_project_grep

    def can_handle(self, intent: Intent) -> bool:
        return intent.scope in ("project", "ephemeral")

    def load(self, intent: Intent, *, max_bytes: int = 4096) -> LoadResult:
        result = self._grep(intent.target, scope=intent.scope)
        excerpt = (result.first_match or "")[:512]
        content = self._summarize(result, max_bytes=max_bytes)
        return LoadResult(
            content=content,
            excerpt=excerpt,
            source=result.first_match_path or "(no match)",
            raw_size=result.total_bytes,
            truncated=len(content) >= max_bytes,
        )

    def _summarize(self, result: Any, *, max_bytes: int) -> str:
        # 简化策略：取前 N 行 + 提示命中数
        lines = result.lines[:50]
        return "\n".join(lines)[:max_bytes]


class WebFetchLoader:
    """官方文档 / 外部网页抓取 loader。"""
    name = "WebFetchLoader"

    def __init__(self, webfetch_fn: Callable | None = None) -> None:
        self._fetch = webfetch_fn or _default_webfetch

    def can_handle(self, intent: Intent) -> bool:
        return intent.kind in ("doc_check", "fact_verify")

    def load(self, intent: Intent, *, max_bytes: int = 4096) -> LoadResult:
        query = f"{intent.target} {intent.hint}".strip()
        doc = self._fetch(query)
        excerpt = doc.text[:512]
        content = doc.text[:max_bytes]
        return LoadResult(
            content=content,
            excerpt=excerpt,
            source=doc.url,
            raw_size=len(doc.text),
            truncated=len(doc.text) > max_bytes,
        )


class BashLoader:
    """系统环境 / 命令执行 loader。"""
    name = "BashLoader"

    def __init__(self, bash_fn: Callable | None = None) -> None:
        self._bash = bash_fn or _default_bash

    def can_handle(self, intent: Intent) -> bool:
        return intent.kind == "env_inspect"

    def load(self, intent: Intent, *, max_bytes: int = 4096) -> LoadResult:
        # 安全约束：仅允许只读命令（whitelist）
        cmd = self._safe_command(intent.target)
        result = self._bash(cmd, timeout=10)
        return LoadResult(
            content=result.stdout[:max_bytes],
            excerpt=result.stdout[:512],
            source=cmd,
            raw_size=len(result.stdout),
            truncated=len(result.stdout) > max_bytes,
        )

    def _safe_command(self, target: str) -> str:
        """仅允许 whitelist 内的只读命令。"""
        whitelist = ["python --version", "node --version", "go version",
                     "which ", "echo $PATH", "ls ", "cat "]
        for w in whitelist:
            if target.startswith(w):
                return target
        raise ValueError(f"BashLoader 拒绝执行非白名单命令: {target!r}")


# ==== Loader 注册表 ====

_loaders: list[Loader] = []

def register_loader(loader: Loader) -> None:
    """注册一个 loader；后注册的优先匹配。"""
    _loaders.append(loader)

def get_loader(intent: Intent) -> Loader | None:
    """按 intent 找最匹配的 loader。"""
    for loader in reversed(_loaders):
        if loader.can_handle(intent):
            return loader
    return None

# ==== 默认实现占位（实际由 Orchestrator 注入） ====

def _default_project_grep(target: str, *, scope: str) -> Any:
    from clawcodex_ext.tool_system.grep_bridge import project_grep
    return project_grep(target, scope=scope)

def _default_webfetch(query: str) -> Any:
    from clawcodex_ext.tool_system.webfetch_bridge import webfetch
    return webfetch(query)

def _default_bash(cmd: str, *, timeout: int) -> Any:
    from clawcodex_ext.tool_system.bash_bridge import bash
    return bash(cmd, timeout=timeout)
```

#### 1.7.3 合成结果缓存（P159-C）

```python
# extensions/jit_context/cache.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time
import hashlib
from collections import OrderedDict

from .loaders import LoadResult

@dataclass
class CacheEntry:
    """单条缓存项。"""
    key: str
    result: LoadResult
    created_at: float
    ttl_seconds: float
    hit_count: int = 0

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class SynthesisCache:
    """按 (intent, scope) key 的合成结果缓存。

    特性：
    - LRU 淘汰（容量满时丢弃最久未使用）
    - TTL 过期（默认 600 秒 / 10 分钟）
    - 命中计数（高频 intent 优先保留）
    """

    def __init__(self, *, capacity: int = 64, default_ttl: float = 600.0) -> None:
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._capacity = capacity
        self._default_ttl = default_ttl

    @staticmethod
    def make_key(intent_target: str, scope: str, hint: str = "") -> str:
        """稳定 key — target + scope + hint 哈希。"""
        raw = f"{scope}\x00{intent_target.lower()}\x00{hint.lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def get(self, key: str) -> LoadResult | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del self._store[key]
            return None
        entry.hit_count += 1
        self._store.move_to_end(key)
        return entry.result

    def put(self, key: str, result: LoadResult, *, ttl: float | None = None) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = CacheEntry(
            key=key,
            result=result,
            created_at=time.time(),
            ttl_seconds=ttl if ttl is not None else self._default_ttl,
        )
        # LRU 淘汰
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


_session_cache: SynthesisCache | None = None

def get_cache() -> SynthesisCache:
    global _session_cache
    if _session_cache is None:
        _session_cache = SynthesisCache()
    return _session_cache

def reset_cache() -> None:
    global _session_cache
    _session_cache = None
```

#### 1.7.4 动态 Section 注册（P159-D）

```python
# extensions/jit_context/synthesizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import time
import uuid

from .intent_router import Intent
from .loaders import get_loader, LoadResult
from .cache import get_cache, SynthesisCache
from .rate_limiter import get_limiter, RateLimitExceeded


@dataclass
class SynthesisResult:
    """一次 JIT 合成的完整结果。"""
    intent: Intent
    result: LoadResult
    section_id: str            # F-119 register_section 用的 ID
    cache_hit: bool
    duration_ms: float

    def render_excerpt(self) -> str:
        """渲染为适合注入 system prompt 的 markdown 片段。"""
        return (
            f"## JIT Context: {self.intent.kind} / {self.intent.target}\n\n"
            f"**Source**: {self.result.source}\n\n"
            f"{self.result.excerpt}"
        )


def synthesize(intent: Intent) -> SynthesisResult:
    """执行一次 JIT 合成：限流 → 缓存 → loader → register_section。

    Returns:
        SynthesisResult 含 section_id（已注册到 F-119）

    Raises:
        RateLimitExceeded: 触发限流时
        RuntimeError: 无可用 loader 或抓取失败
    """
    started = time.monotonic()

    # 1. 限流检查
    get_limiter().acquire(intent)

    # 2. 缓存命中
    cache = get_cache()
    key = SynthesisCache.make_key(intent.target, intent.scope, intent.hint)
    cached = cache.get(key)
    if cached is not None:
        section_id = _register_dynamic_section(intent, cached)
        return SynthesisResult(
            intent=intent,
            result=cached,
            section_id=section_id,
            cache_hit=True,
            duration_ms=(time.monotonic() - started) * 1000,
        )

    # 3. 选 loader 并抓取
    loader = get_loader(intent)
    if loader is None:
        raise RuntimeError(f"No loader for intent: {intent.kind}")

    try:
        result = loader.load(intent)
    except Exception as e:
        raise RuntimeError(f"Loader {loader.name} failed: {e}") from e

    # 4. 写缓存
    cache.put(key, result)

    # 5. 注册为动态 section
    section_id = _register_dynamic_section(intent, result)

    return SynthesisResult(
        intent=intent,
        result=result,
        section_id=section_id,
        cache_hit=False,
        duration_ms=(time.monotonic() - started) * 1000,
    )


def _register_dynamic_section(intent: Intent, result: LoadResult) -> str:
    """通过 F-119 register_section 把抓取结果注入 system prompt。"""
    from clawcodex_ext.context_system.section_registry import register_section

    section_id = f"jit_{intent.kind}_{uuid.uuid4().hex[:8]}"
    content = result.content

    def _builder(_ctx: Any) -> str:
        # 动态 section 每次构建时返回缓存内容（不再二次抓取）
        return (
            f"## JIT Context: {intent.target}\n"
            f"_Source: {result.source} | "
            f"Loaded at session turn {intent.source_text!r}_\n\n"
            f"{content}"
        )

    register_section(
        section_id,
        builder=_builder,
        order=50,                    # 插在 F-119 标准 section 之后
        cache_scope="session",       # 会话内缓存，避免反复构建
        tags=["jit", "dynamic", intent.kind],
    )
    return section_id
```

#### 1.7.5 触发限流（P159-E）

```python
# extensions/jit_context/rate_limiter.py
from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Literal
import time

from .intent_router import Intent


class RateLimitExceeded(Exception):
    """触发限流时抛出，调用方决定降级策略。"""
    def __init__(self, message: str, *, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class _QueueItem:
    intent: Intent
    enqueued_at: float


class RateLimiter:
    """单会话 JIT 触发限流器。

    约束：
    - 单 turn 上限：默认 3 次 / turn
    - 单 session 上限：默认 20 次 / session
    - 优先级队列：高 priority 先出
    - 冷却期：同一 target 在 N 秒内不重复抓取（即使缓存过期也不重抓）
    """

    def __init__(
        self,
        *,
        per_turn_limit: int = 3,
        per_session_limit: int = 20,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._per_turn_limit = per_turn_limit
        self._per_session_limit = per_session_limit
        self._cooldown = cooldown_seconds
        self._turn_count = 0
        self._session_count = 0
        self._last_target_at: dict[str, float] = {}
        self._queue: deque[_QueueItem] = deque()
        self._current_turn_id: int | None = None

    def begin_turn(self, turn_id: int) -> None:
        """新 turn 开始时调用 — 重置 per-turn 计数。"""
        self._current_turn_id = turn_id
        self._turn_count = 0

    def acquire(self, intent: Intent) -> None:
        """尝试获取执行权；超限时抛 RateLimitExceeded。"""
        # 1. session 上限
        if self._session_count >= self._per_session_limit:
            raise RateLimitExceeded(
                f"Session 配额已满 ({self._per_session_limit})",
                retry_after=0.0,
            )

        # 2. turn 上限
        if self._turn_count >= self._per_turn_limit:
            raise RateLimitExceeded(
                f"Turn 配额已满 ({self._per_turn_limit})",
                retry_after=0.0,
            )

        # 3. 冷却期
        last_at = self._last_target_at.get(intent.target)
        if last_at is not None:
            elapsed = time.time() - last_at
            if elapsed < self._cooldown:
                raise RateLimitExceeded(
                    f"Target {intent.target!r} 处于冷却期",
                    retry_after=self._cooldown - elapsed,
                )

        # 通过：记账
        self._turn_count += 1
        self._session_count += 1
        self._last_target_at[intent.target] = time.time()

    def enqueue(self, intent: Intent) -> None:
        """低优先级 intent 排队等候（不在 acquire 中抛错）。"""
        self._queue.append(_QueueItem(intent=intent, enqueued_at=time.time()))

    def drain_queue(self) -> list[Intent]:
        """按 priority 降序返回等候中的 intent。"""
        items = sorted(self._queue, key=lambda x: -x.intent.priority)
        self._queue.clear()
        return [it.intent for it in items]

    def stats(self) -> dict:
        return {
            "turn_used": self._turn_count,
            "turn_limit": self._per_turn_limit,
            "session_used": self._session_count,
            "session_limit": self._per_session_limit,
            "queue_size": len(self._queue),
        }


_session_limiter: RateLimiter | None = None

def get_limiter() -> RateLimiter:
    global _session_limiter
    if _session_limiter is None:
        _session_limiter = RateLimiter()
    return _session_limiter

def reset_limiter() -> None:
    global _session_limiter
    _session_limiter = None
```

#### 1.7.6 Hook 集成（自动触发）

```python
# extensions/jit_context/hooks.py
from __future__ import annotations

from typing import Any

def install_jit_context_hooks(hook_registry: Any) -> None:
    """向 F-102 LoopHook 注册 post_query_hook 自动检测 JIT 触发。"""
    from .intent_router import parse_intent, request_context
    from .synthesizer import synthesize
    from .rate_limiter import RateLimitExceeded

    @hook_registry.register("post_query_hook")
    def _auto_trigger(query: str, history: list[dict], turn_id: int, **_kw: Any) -> dict:
        """检测 query 中是否含 '我需要 X' 类表达；命中则自动 synthesize。"""
        intent = parse_intent(query)
        if intent is None:
            return {}

        try:
            result = synthesize(intent)
            return {
                "jit_triggered": True,
                "section_id": result.section_id,
                "cache_hit": result.cache_hit,
                "duration_ms": result.duration_ms,
                "intent_kind": intent.kind,
            }
        except RateLimitExceeded as e:
            return {
                "jit_triggered": False,
                "skipped_reason": "rate_limited",
                "retry_after": e.retry_after,
            }
        except RuntimeError as e:
            return {
                "jit_triggered": False,
                "skipped_reason": f"synthesis_error: {e}",
            }

    @hook_registry.register("pre_turn_hook")
    def _begin_turn(turn_id: int, **_kw: Any) -> None:
        """新 turn 开始时重置 per-turn 计数。"""
        from .rate_limiter import get_limiter
        get_limiter().begin_turn(turn_id)
```

### 1.8 核心流程

```
[Agent 输出 "我需要了解 FastAPI 0.110 签名"]
  ↓
P159-A parse_intent(text)
  → Intent(kind="doc_check", target="FastAPI 0.110 签名", priority=5)
  ↓
P159-E RateLimiter.acquire(intent)
  → 通过（turn_count 0/3，session_count 0/20）
  ↓
P159-C cache.get(key)
  → 未命中（首次请求）
  ↓
P159-B get_loader(intent)
  → WebFetchLoader（doc_check 匹配）
  ↓
WebFetchLoader.load(intent)
  → WebFetch("FastAPI 0.110 签名")
  → LoadResult(content=..., excerpt=..., source=fastapi.tiangolo.com/...)
  ↓
P159-C cache.put(key, result)
  ↓
P159-D _register_dynamic_section(intent, result)
  → register_section("jit_doc_check_xxxxxxxx", builder=..., order=50, tags=["jit", "dynamic", "doc_check"])
  ↓
SynthesisResult(section_id="jit_doc_check_xxxxxxxx", cache_hit=False, duration_ms=350)
  ↓
[下次 query 开始，F-119 build_full_system_prompt_blocks()
  → 调用 jit_doc_check_xxxxxxxx builder → 注入到 system prompt 末尾]
  ↓
[Agent 使用新 context 回答]
```

### 1.9 与现有架构的对齐

| 维度 | 现状 | F-159 落地后 |
|------|------|-------------|
| 上下文生成时机 | 会话启动一次性 | ✅ 按需 JIT（每 turn 可触发） |
| 假装知道幻觉源头 | 无防御 | ✅ 未加载即不可断言（与 F-158-A VERIFIED 联动） |
| 抓取接口统一 | ❌ 散落在各工具 | ✅ Loader Protocol 统一抽象 |
| 抓取结果缓存 | ❌ 无 | ✅ LRU + TTL 合成缓存 |
| 抓取结果注入 | ❌ 需手工拼接 | ✅ register_section 自动注入 |
| 触发频率失控 | ❌ 可能频繁触发 | ✅ 单 turn/session 配额 + 冷却期 |
| 跨 Loader 复用 | ❌ 各 loader 独立 | ✅ Intent → Loader 路由表 + 注册扩展 |
| 与 F-119 协同 | — | ✅ 复用 register_section，无侵入 |
| 与 F-158 协同 | — | ✅ 抓取结果作为 F-158-A VERIFIED source |
| 解耦合规 | — | ✅ 零 `src/` 改动 |

### 1.10 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 模型过度触发 JIT | token / 时延膨胀 | 单 turn ≤ 3 / session ≤ 20；冷却期 30s |
| Loader 抓取失败 | 用户体验受损 | 异常降级为 INFERRED（不阻塞回复）；返回 skipped_reason |
| 缓存内容过期 | 给模型看陈旧信息 | TTL 默认 600s；过期后再抓；高频 key 自动续期 |
| Bash loader 安全 | 任意命令执行风险 | whitelist 仅允许只读命令；timeout=10s |
| WebFetch 跨域成本 | 网络延迟不可控 | GrepLoader 优先；WebFetch 仅在 doc_check 触发 |
| 动态 section 膨胀 | system prompt 越来越长 | tags 筛选 + session 级 cache_scope；下个 turn 自动 GC 旧 section |
| Loader 抓取阻塞 query | 用户感延迟 | 后台异步抓取 + 占位 section（仅 PoC 阶段，MVP 先同步） |
| 与 F-130 Profile 切换抢资源 | 切换 + JIT 同时争 token | RateLimiter 在 Profile 切换 turn 内临时降级配额 |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|----------|
| 2026-07-22 | 初始创建 | 本文档 | 与 F-130 / F-158 格式对齐；映射到 DC-A §4.4 F-159 |

### 2.2 待验证项

- P159-A `parse_intent` 识别中英文 "我需要 / need / /context / !ctx" 4 种触发模式
- P159-A `_classify_target` 对 "API / 文档 / 环境 / 依赖" 关键词正确分类 5 种 IntentKind
- P159-B 3 个内置 loader (Grep / WebFetch / Bash) 各自 `can_handle` / `load` 行为正确
- P159-B BashLoader `_safe_command` 拒绝非白名单命令（如 `rm -rf`）
- P159-C 缓存 LRU 淘汰 + TTL 过期正确触发；key 哈希对 target 大小写不敏感
- P159-D `_register_dynamic_section` 在 F-119 中注册的 section 可在 `dump_effective_system_prompt` 中看到
- P159-E RateLimiter 单 turn / 单 session 上限正确抛 RateLimitExceeded
- P159-E 冷却期：同一 target 在 30s 内第二次 acquire 抛错
- `synthesize` 端到端：parse → limiter → cache → loader → register_section 全链路通过
- 稳定性门禁全量（Stage 1-5 + 7-9）通过
- Orchestrator 单元测试（排除 `manual_e2e_f38.py`）通过

---

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `Intent` dataclass 含 kind/target/hint/priority/scope/requested_by/source_text 字段 | 📋 |
| 2 | `parse_intent` 4 种触发模式正确匹配（"我需要" / "need" / "/context" / "!ctx"） | 📋 |
| 3 | `_classify_target` 5 种 IntentKind 正确分类（code_lookup / doc_check / fact_verify / env_inspect / user_specified） | 📋 |
| 4 | `request_context` API 支持 str 与 Intent 双入参，标准化 priority + scope | 📋 |
| 5 | `Loader` Protocol 含 name / can_handle / load 三个方法 | 📋 |
| 6 | 3 个内置 loader（GrepLoader / WebFetchLoader / BashLoader）实现 Loader Protocol | 📋 |
| 7 | `register_loader` + `get_loader` 注册表工作正常 | 📋 |
| 8 | BashLoader `_safe_command` 仅允许 whitelist 内只读命令 | 📋 |
| 9 | `SynthesisCache` 支持 LRU 淘汰 + TTL 过期 + key 哈希稳定 | 📋 |
| 10 | `SynthesisCache.make_key` 对 target 大小写不敏感 | 📋 |
| 11 | `RateLimiter` 单 turn / 单 session 配额 + 冷却期正确抛错 | 📋 |
| 12 | `synthesize` 完整流程：limiter → cache → loader → register_section 返回 SynthesisResult | 📋 |
| 13 | `_register_dynamic_section` 通过 F-119 `register_section` 注册，section_id 含 `jit_` 前缀 | 📋 |
| 14 | 5 子特性在 `import extensions.jit_context` 时自动注册 | 📋 |
| 15 | `install_jit_context_hooks` 向 F-102 hook_registry 注册 `post_query_hook` + `pre_turn_hook` | 📋 |
| 16 | 稳定性门禁 + JIT E2E 测试通过 | 📋 |

### 3.2 落地路径（推荐顺序）

1. **P159-A 先行** — Intent 解析与路由是最独立、可立即验证的子特性（纯函数 + dataclass）
2. **P159-B 紧随** — Loader 集合依赖 P159-A 的 Intent；优先实现 GrepLoader（最常用）
3. **P159-C 并行** — SynthesisCache 与 Loader 独立，可同步实现
4. **P159-E 并行** — RateLimiter 与 Cache 独立
5. **P159-D 收尾** — Synthesizer 串联 limiter + cache + loader + F-119 register_section
6. **P159-F (预留，依赖 F-166)** — 跨会话缓存持久化（远期 Wave 2）

### 3.3 与 F-119 / F-130 / F-158 的协同点

- **F-119 `register_section`** → P159-D 把抓取结果注册为 `jit_*` section，`order=50`，`cache_scope="session"`，`tags=["jit", "dynamic"]`
- **F-119 `dump_effective_system_prompt`** → 验证 `jit_*` section 已注入
- **F-130 Profile 占位符** → P159-A 抓取的摘要可作为 `{{placeholder}}` 的 fillers（如 `{{last_error_summary}}`）
- **F-158-A `ConfidenceMarker.source`** → JIT 抓取结果可被引用为 VERIFIED source（如 `[VERIFIED] (source: jit_doc_check_xxx) FastAPI 0.110 ...`）

### 3.4 与 F-161 (涌现发现) 的协同

- F-161 的"反思 prompt"决定抓取需求 → 调用 F-159 `request_context` 执行实际抓取
- F-159 是 F-161 的执行层 — F-161 决定"要什么"，F-159 决定"如何拿"

---

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-22 | 初始创建 | DC-A §4.4 映射表基础上落地 F-159 JIT 上下文合成；覆盖 DC-003；按 Wave 1 优先级推进；与 F-130（占位符填充）+ F-158-A（VERIFIED source）+ F-161（执行层）强协同；解耦落地于 `extensions/jit_context/`，零 `src/` 侵入 |
