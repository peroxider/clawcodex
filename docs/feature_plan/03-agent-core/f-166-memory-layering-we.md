# F-166: 记忆分层 — Working + Episodic 两层先落地（DC-004）

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-166-memory-layering-we.md`
> 最后更新: 2026-07-22
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-004

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 2 P1 工具化组（中等门槛，~2-3 月可落地；Working 层低门槛可独立落地） |
| 覆盖 DC | DC-004 记忆分层 (Working + Episodic 两层先落地；Semantic + Procedural 留 Wave 3 / F-175+) |
| 前置依赖 | F-119 Section Registry + F-102 Hook 扩展点 + F-158 Working Memory (VERIFIED markers) |
| 协同 | F-158 Working Memory (VERIFIED 标记)、F-130 Profile (不同 Profile 访问不同层)、F-159 JIT (跨会话查询) |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/memory_layers/`，零 `src/` 侵入 |
| 落地形态 | Working Memory (进程内) + Episodic Memory (NDJSON) + 写入策略 + 读取权限分层 + Provenance 追溯 |

---

## §1 设计规划

### 1.1 背景

当前 Agent 的"记忆"是**单层、扁平、无生命周期管理**的——所有事实、决策、未解疑问都堆在对话历史里，无结构、无层次、无来源追溯：

- Agent 不知道哪些是**已验证事实**（VERIFIED）vs **临时草稿**（scratchpad）
- Agent 不知道哪些是**本会话相关**（working）vs **跨会话有用**（episodic）
- Agent 不知道每个记忆的**来源**（哪个工具调用 / 哪轮对话 / 哪个用户输入）
- 跨会话时，所有上下文都被丢弃，**无法复用历史经验**

这导致：
- **冗余抓取**：上次查过的事实，下次又查一遍（F-159 JIT 命中缓存但仅限本会话）
- **上下文爆炸**：所有历史堆在 prompt 里，token 浪费
- **不可信**：无法区分"我刚才随口说的"vs"我读文件确认的"

**F-166 的定位**：把记忆按**生命周期 + 可信度**分层，每层有独立写入策略和读取权限。Wave 2 P1 范围内先落地 **Working + Episodic 两层**（Semantic + Procedural 留 Wave 3）。

### 1.2 目标

- 让 Working Memory 成为 Agent 的**结构化 scratchpad**（决策栈、未解疑问、关键事实、VERIFIED 标记）
- 让 Episodic Memory 成为**跨会话经验库**（"上次类似场景处理结果"）
- 让每条记忆可**Provenance 追溯**（来源工具 / 轮次 / 用户输入）
- 让写入策略**按层分级**（Working 写最勤 / Episodic 写需标注）
- 与 F-158 Working Memory 兼容：F-158 的 VERIFIED markers 是 F-166 Working Memory 的**子集**

### 1.3 非目标 (Out of Scope)

- 不立即落地 Semantic Memory（DC-004 完整版留 Wave 3 / F-175+；Wave 2 P1 范围仅 Working + Episodic）
- 不落地 Procedural Memory（DC-004 可选第四层，留 Wave 3）
- 不替代 F-130 Profile 切换机制（F-166 提供记忆层基础设施，F-130 提供 Profile 切换策略）
- 不替代 F-159 JIT 缓存（F-159 是"按需抓取"机制，F-166 是"分层持久化"机制）
- 不立即做记忆晋升（Working → Episodic 自动晋升留 Wave 3；Wave 2 范围仅显式 write）
- 不替代 F-158 Working Memory 的 VERIFIED 标注 —— F-158 是 F-166 Working Memory 的**子类型**

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖 DC | 状态 | 工时 |
|:----:|--------|:-------:|:----:|:----:|
| P166-A | Working Memory 层（进程内 dict + GC + 类型化条目） | DC-004 核心 | 📋 | 2-3d |
| P166-B | Episodic Memory 层（NDJSON 持久化 + 时间戳 + 标签） | DC-004 核心 | 📋 | 2-3d |
| P166-C | 写入策略 + 读取权限分层（按层 access control） | DC-004 策略 | 📋 | 1-2d |
| P166-D | Provenance 追溯（每条记忆可追溯来源） | DC-004 可信度 | 📋 | 1-2d |
| P166-E | 与 F-130 Profile 协同（不同 Profile 访问不同层） | DC-004 协同 | 📋 | 1d |
| P166-F | 生命周期管理（GC + 持久化 + 容量限制） | DC-004 运营 | 📋 | 1-2d |
| P166-G | 记忆审计 NDJSON 日志 | DC-004 运营 | 📋 | 1d（远期） |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-119 Section Registry | **强协同** | P166-A 通过 `register_section` 注入 `memory_layers_guide` section，让模型看到当前激活层与访问规则 |
| F-102 Hook Extensions | **强协同** | P166-C 在 `post_query_hook` / `pre_reply_hook` 注册 `memory_layers.write_through`（按规则写入对应层） |
| F-158 Working Memory | **兼容（子集关系）** | F-166 Working Memory **包含** F-158 VERIFIED markers 作为 `MemoryEntry(type=VERIFIED_FACT)` 子类型；不重复存储 |
| F-130 Profile | **协同** | P166-E 不同 Profile 可配置不同层访问权限（如 `strict` Profile 默认禁写 Episodic，避免污染；`default` Profile 全开） |
| F-159 JIT 合成 | **协同** | F-159 JIT 抓取结果可选择性写入 Episodic Memory（按用户配置），跨会话复用 |
| F-159 §1.7 synthesize | **协同** | 抓取结果通过 F-166 写入对应层（默认 Working；用户配置可升 Episodic） |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/memory_layers/__init__.py` | — | 子系统入口；注册 working / episodic / write_policy / read_policy |
| `extensions/memory_layers/working.py` | P166-A | `WorkingMemory` 类（进程内 dict + 类型化 `MemoryEntry` + 自动 GC） |
| `extensions/memory_layers/episodic.py` | P166-B | `EpisodicMemory` 类（NDJSON 持久化 + 标签 + 时间戳 + session_id） |
| `extensions/memory_layers/structured.py` | P166-A | `MemoryEntry` dataclass（key / value / type / provenance / ttl / tags / layer）+ `MemoryType` 枚举（DECISION / QUESTION / FACT / TODO / VERIFIED_FACT / SCRATCH） |
| `extensions/memory_layers/write_policy.py` | P166-C | `WritePolicy` + 按层规则（默认/Profile 限定）+ auto-promote 规则（Wave 3） |
| `extensions/memory_layers/read_policy.py` | P166-C | `ReadPolicy` + 按层访问控制（默认/Profile 限定） |
| `extensions/memory_layers/provenance.py` | P166-D | `Provenance` dataclass（source_tool / source_turn / source_user_input / source_file）+ Citation 兼容 |
| `extensions/memory_layers/profile_integration.py` | P166-E | 与 F-130 Profile 协同（PROFILE_LAYER_ACCESS 5 Profile 映射） |
| `extensions/memory_layers/lifecycle.py` | P166-F | GC + 容量限制 + 持久化触发 + Wave 3 晋升预留接口 |
| `extensions/memory_layers/audit.py` | P166-G | NDJSON 写入 / 读取审计；与 F-158 / F-162 / F-163 / F-165 audit schema 兼容 |
| `extensions/memory_layers/capabilities.py` | — | Protocol 接口契约（`MemoryLayer` / `WritePolicy` / `ReadPolicy` / `LifecycleManager`） |
| `extensions/memory_layers/hooks.py` | 全部 | 在 F-102 LoopHook 注册 `memory_layers.write_through` / `memory_layers.read_for_context` |
| `tests/memory_layers/test_working.py` | P166-A | 进程内读写 + 自动 GC 测试 |
| `tests/memory_layers/test_episodic.py` | P166-B | NDJSON 追加 / 跨会话加载测试 |
| `tests/memory_layers/test_write_policy.py` | P166-C | 按层写入策略（Working 全开 / Episodic 需显式） |
| `tests/memory_layers/test_read_policy.py` | P166-C | 按层读取权限（strict Profile 禁读 Episodic） |
| `tests/memory_layers/test_provenance.py` | P166-D | Provenance 字段填充 + 追溯 |
| `tests/memory_layers/test_profile_integration.py` | P166-E | 5 Profile 层访问映射 |
| `tests/memory_layers/test_lifecycle.py` | P166-F | GC 触发 + 容量上限 |
| `tests/memory_layers/test_e2e.py` | 全部 | 端到端：write → read → provenance → GC |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_memory_layers_extensions()` 在 import 时注册 working / episodic / write_policy |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | 在 `post_query_hook` 链追加 `memory_layers.write_through`（按规则写入对应层） |
| `extensions/anti_hallucination/confidence_marker.py` | F-158 `ConfidenceMarker` 改为 F-166 `MemoryEntry(type=VERIFIED_FACT)` 的**视图**（不重复存储） |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.memory_layers` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-166 |
| `docs/feature_plan/dynamic-context-index.md` | DC→F 映射、依赖与全局验收总则 |

### 1.7 核心 API 设计

#### 1.7.1 Working Memory 层（P166-A）

```python
# extensions/memory_layers/working.py
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from extensions.memory_layers.structured import MemoryEntry, MemoryType, MemoryLayer
from extensions.memory_layers.provenance import Provenance


@dataclass
class WorkingMemoryConfig:
    """Working Memory 配置。"""
    max_entries: int = 1000               # 容量上限
    default_ttl_ms: int | None = None     # None = 不过期；否则 entry 在 ttl 毫秒后被 GC
    auto_gc_interval_sec: int = 60        # 自动 GC 周期


class WorkingMemory:
    """进程内 Working Memory 层。

    特性：
    - 类型化条目（MemoryType 枚举）
    - LRU 淘汰（max_entries 超限时）
    - 自动 GC（ttl 过期 + 周期清理）
    - 线程安全（RLock）
    """

    def __init__(self, config: WorkingMemoryConfig | None = None):
        self.config = config or WorkingMemoryConfig()
        self._store: OrderedDict[str, MemoryEntry] = OrderedDict()
        self._lock = RLock()

    def write(
        self,
        key: str,
        value: Any,
        *,
        entry_type: MemoryType = MemoryType.SCRATCH,
        provenance: Provenance | None = None,
        ttl_ms: int | None = None,
        tags: tuple[str, ...] = (),
    ) -> MemoryEntry:
        """写入一条 Working Memory。"""
        with self._lock:
            entry = MemoryEntry(
                key=key,
                value=value,
                entry_type=entry_type,
                layer=MemoryLayer.WORKING,
                provenance=provenance or Provenance.unknown(),
                created_at=time.time(),
                ttl_ms=ttl_ms or self.config.default_ttl_ms,
                tags=tags,
            )
            self._store[key] = entry
            # LRU：移动到末尾
            self._store.move_to_end(key)
            # 容量检查
            if len(self._store) > self.config.max_entries:
                self._store.popitem(last=False)     # 淘汰最早的
            return entry

    def read(self, key: str) -> MemoryEntry | None:
        """读取一条 Working Memory（不存在返回 None）。"""
        with self._lock:
            entry = self._store.get(key)
            if entry and self._is_expired(entry):
                self._store.pop(key, None)
                return None
            if entry:
                self._store.move_to_end(key)        # LRU 更新
            return entry

    def list_all(self) -> list[MemoryEntry]:
        """列出所有 Working Memory 条目。"""
        with self._lock:
            return [e for e in self._store.values() if not self._is_expired(e)]

    def gc(self) -> int:
        """手动 GC：清理过期条目。返回清理数量。"""
        with self._lock:
            expired_keys = [
                k for k, e in self._store.items() if self._is_expired(e)
            ]
            for k in expired_keys:
                self._store.pop(k, None)
            return len(expired_keys)

    def _is_expired(self, entry: MemoryEntry) -> bool:
        if entry.ttl_ms is None:
            return False
        elapsed_ms = (time.time() - entry.created_at) * 1000
        return elapsed_ms > entry.ttl_ms
```

#### 1.7.2 Episodic Memory 层（P166-B）

```python
# extensions/memory_layers/episodic.py
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from extensions.memory_layers.structured import MemoryEntry, MemoryType, MemoryLayer
from extensions.memory_layers.provenance import Provenance


class EpisodicMemory:
    """跨会话 Episodic Memory 层（NDJSON 持久化）。

    特性：
    - NDJSON 追加写入（每行一条 MemoryEntry）
    - session_id 分段（不同会话条目可通过 session_id 过滤）
    - 标签检索（tags 字段）
    - 容量上限（按行数 / 文件大小）
    - 文件位置：~/.cache/clawcodex/memory/episodic.jsonl 或项目内 .memory/episodic.jsonl
    """

    def __init__(
        self,
        storage_path: Path,
        *,
        max_file_size_mb: int = 100,
        session_id: str | None = None,
    ):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_file_size_mb = max_file_size_mb
        self.session_id = session_id or str(uuid.uuid4())   # 默认当前会话 ID
        self._lock = RLock()

    def write(
        self,
        key: str,
        value: Any,
        *,
        entry_type: MemoryType = MemoryType.SCRATCH,
        provenance: Provenance | None = None,
        tags: tuple[str, ...] = (),
    ) -> MemoryEntry:
        """追加写入一条 Episodic Memory。"""
        with self._lock:
            entry = MemoryEntry(
                key=key,
                value=value,
                entry_type=entry_type,
                layer=MemoryLayer.EPISODIC,
                provenance=provenance or Provenance.unknown(),
                created_at=time.time(),
                ttl_ms=None,                                # Episodic 不过期（除非显式 GC）
                tags=tags,
                session_id=self.session_id,
            )
            self._append_ndjson(entry)
            self._rotate_if_needed()
            return entry

    def read(self, key: str, *, session_id: str | None = None) -> MemoryEntry | None:
        """读取最新一条匹配 key 的 Episodic Memory。

        Args:
            key: 条目 key
            session_id: None = 跨会话；否则仅当前会话
        """
        with self._lock:
            target_session = session_id  # None = 跨会话
            latest = None
            for entry in self._iter_entries():
                if entry.key == key:
                    if target_session is None or entry.session_id == target_session:
                        if latest is None or entry.created_at > latest.created_at:
                            latest = entry
            return latest

    def list_recent(self, n: int = 50, *, session_id: str | None = None, tags: tuple[str, ...] = ()) -> list[MemoryEntry]:
        """列出最近 N 条 Episodic Memory（可按 session_id + tags 过滤）。"""
        with self._lock:
            entries = list(self._iter_entries())
            if session_id:
                entries = [e for e in entries if e.session_id == session_id]
            if tags:
                entries = [e for e in entries if any(t in e.tags for t in tags)]
            return entries[-n:]

    def _append_ndjson(self, entry: MemoryEntry) -> None:
        """追加一条 NDJSON。"""
        line = json.dumps(asdict(entry), ensure_ascii=False, default=str) + "\n"
        with self.storage_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _iter_entries(self) -> Iterator[MemoryEntry]:
        """迭代所有 NDJSON 条目。"""
        if not self.storage_path.exists():
            return
        with self.storage_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield MemoryEntry.from_dict(data)
                except (json.JSONDecodeError, KeyError):
                    continue

    def _rotate_if_needed(self) -> None:
        """超过 max_file_size_mb 时轮转文件。"""
        if not self.storage_path.exists():
            return
        size_mb = self.storage_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_file_size_mb:
            timestamp = int(time.time())
            rotated = self.storage_path.with_suffix(f".{timestamp}.jsonl")
            self.storage_path.rename(rotated)
            # 新文件下次 write 时自动创建
```

#### 1.7.3 结构化数据契约（P166-A）

```python
# extensions/memory_layers/structured.py
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class MemoryLayer(str, Enum):
    """记忆层枚举。"""
    WORKING = "working"
    EPISODIC = "episodic"
    # Wave 3 预留：
    # SEMANTIC = "semantic"
    # PROCEDURAL = "procedural"


class MemoryType(str, Enum):
    """记忆类型枚举（按用途分类）。"""
    DECISION = "decision"               # 决策记录
    QUESTION = "question"               # 未解疑问
    FACT = "fact"                       # 一般事实
    TODO = "todo"                       # 待办
    VERIFIED_FACT = "verified_fact"     # 已验证事实（F-158 marker 视图）
    SCRATCH = "scratch"                 # 草稿 / 临时


@dataclass
class MemoryEntry:
    """单条记忆条目。"""
    key: str
    value: Any
    entry_type: MemoryType
    layer: MemoryLayer
    provenance: dict                       # Provenance 序列化（dict 形式避免循环引用）
    created_at: float                      # epoch 秒
    ttl_ms: int | None = None              # None = 不过期
    tags: tuple[str, ...] = ()
    session_id: str = ""                   # 仅 Episodic 使用

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(
            key=data["key"],
            value=data["value"],
            entry_type=MemoryType(data["entry_type"]),
            layer=MemoryLayer(data["layer"]),
            provenance=data["provenance"],
            created_at=data["created_at"],
            ttl_ms=data.get("ttl_ms"),
            tags=tuple(data.get("tags", [])),
            session_id=data.get("session_id", ""),
        )

    def is_expired(self) -> bool:
        if self.ttl_ms is None:
            return False
        elapsed_ms = (time.time() - self.created_at) * 1000
        return elapsed_ms > self.ttl_ms
```

#### 1.7.4 Provenance 追溯（P166-D）

```python
# extensions/memory_layers/provenance.py
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Provenance:
    """记忆来源追溯。"""
    source_tool: str = ""                 # "Read" / "Grep" / "WebFetch" / "Bash" / "User" / "Agent"
    source_turn: int = 0                  # 对话轮次（0 = 用户初始输入）
    source_user_input: str = ""           # 触发的用户输入（截断 200 字）
    source_file: str = ""                 # 源文件路径（若适用）
    source_url: str = ""                  # 源 URL（若适用）
    source_timestamp: float = 0.0         # 源事件时间戳

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def unknown(cls) -> "Provenance":
        return cls(source_tool="unknown")

    @classmethod
    def from_tool(cls, tool: str, target: str = "", turn: int = 0) -> "Provenance":
        """从工具调用构造 Provenance。"""
        import time
        return cls(
            source_tool=tool,
            source_turn=turn,
            source_file=target if tool in ("Read", "Grep", "Bash") else "",
            source_url=target if tool == "WebFetch" else "",
            source_timestamp=time.time(),
        )

    @classmethod
    def from_user(cls, user_input: str, turn: int = 0) -> "Provenance":
        """从用户输入构造 Provenance。"""
        import time
        return cls(
            source_tool="User",
            source_turn=turn,
            source_user_input=user_input[:200],
            source_timestamp=time.time(),
        )
```

#### 1.7.5 写入策略（P166-C）

```python
# extensions/memory_layers/write_policy.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from extensions.memory_layers.structured import MemoryEntry, MemoryLayer, MemoryType


class WriteOutcome(str, Enum):
    """写入决策结果。"""
    ALLOWED = "allowed"                   # 允许写入
    DENIED = "denied"                     # 拒绝写入
    PROMOTE = "promote"                   # 允许但需晋升标记（Wave 3 留）


@dataclass
class WritePolicy:
    """按层写入策略。"""
    working_allow_types: set[MemoryType] = None      # None = 全类型允许
    episodic_require_explicit: bool = True          # Episodic 必须显式 write() 调用
    episodic_max_per_session: int = 100             # 单会话 Episodic 上限
    require_provenance: bool = True                 # 必须有 Provenance（除非 SCRATCH）


# ==== Profile → WritePolicy 映射（F-130 协同） ====

PROFILE_WRITE_POLICIES: dict[str, WritePolicy] = {
    "default": WritePolicy(
        working_allow_types=None,                    # 全类型允许
        episodic_require_explicit=True,
        episodic_max_per_session=100,
        require_provenance=True,
    ),
    "strict": WritePolicy(
        working_allow_types={MemoryType.VERIFIED_FACT, MemoryType.DECISION},
        episodic_require_explicit=True,
        episodic_max_per_session=20,                 # strict 限制更严
        require_provenance=True,
    ),
    "review": WritePolicy(
        working_allow_types=None,
        episodic_require_explicit=False,             # review 可隐式写
        episodic_max_per_session=200,
        require_provenance=False,                    # review 不强制要求来源
    ),
    "debug": WritePolicy(
        working_allow_types=None,
        episodic_require_explicit=True,
        episodic_max_per_session=50,
        require_provenance=False,
    ),
    "creative": WritePolicy(
        working_allow_types=None,
        episodic_require_explicit=False,
        episodic_max_per_session=300,                # creative 鼓励记录
        require_provenance=False,
    ),
}


def evaluate_write(
    entry: MemoryEntry,
    *,
    policy: WritePolicy,
    session_episodic_count: int = 0,
) -> WriteOutcome:
    """评估写入决策。"""
    if entry.entry_type not in (policy.working_allow_types or set(MemoryType)):
        return WriteOutcome.DENIED
    if entry.layer == MemoryLayer.EPISODIC:
        if policy.episodic_require_explicit and entry.entry_type == MemoryType.SCRATCH:
            return WriteOutcome.DENIED
        if session_episodic_count >= policy.episodic_max_per_session:
            return WriteOutcome.DENIED
    if policy.require_provenance and not entry.provenance.get("source_tool"):
        if entry.entry_type != MemoryType.SCRATCH:
            return WriteOutcome.DENIED
    return WriteOutcome.ALLOWED
```

#### 1.7.6 读取策略（P166-C）

```python
# extensions/memory_layers/read_policy.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from extensions.memory_layers.structured import MemoryLayer


class ReadOutcome(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    REDACTED = "redacted"                 # 允许读但脱敏（远期）


@dataclass
class ReadPolicy:
    working_allow: bool = True
    episodic_allow: bool = True
    episodic_session_filter: str | None = None      # None = 跨会话；否则仅当前会话
    episodic_max_age_sec: int | None = None         # 仅读最近 N 秒


# ==== Profile → ReadPolicy 映射 ====

PROFILE_READ_POLICIES: dict[str, ReadPolicy] = {
    "default": ReadPolicy(
        working_allow=True,
        episodic_allow=True,
        episodic_session_filter=None,                # 默认跨会话读
        episodic_max_age_sec=None,
    ),
    "strict": ReadPolicy(
        working_allow=True,
        episodic_allow=False,                        # strict 不读跨会话
        episodic_session_filter=None,
        episodic_max_age_sec=None,
    ),
    "review": ReadPolicy(
        working_allow=True,
        episodic_allow=True,
        episodic_session_filter=None,
        episodic_max_age_sec=86400 * 7,              # review 仅读最近 7 天
    ),
    "debug": ReadPolicy(
        working_allow=True,
        episodic_allow=True,
        episodic_session_filter=None,
        episodic_max_age_sec=86400,                  # debug 仅读最近 1 天
    ),
    "creative": ReadPolicy(
        working_allow=True,
        episodic_allow=True,
        episodic_session_filter=None,
        episodic_max_age_sec=None,
    ),
}


def evaluate_read(
    layer: MemoryLayer,
    *,
    policy: ReadPolicy,
    session_id: str = "",
    entry_session_id: str = "",
    entry_age_sec: float = 0.0,
) -> ReadOutcome:
    """评估读取决策。"""
    if layer == MemoryLayer.WORKING and not policy.working_allow:
        return ReadOutcome.DENIED
    if layer == MemoryLayer.EPISODIC:
        if not policy.episodic_allow:
            return ReadOutcome.DENIED
        if policy.episodic_session_filter and entry_session_id != session_id:
            return ReadOutcome.DENIED
        if policy.episodic_max_age_sec and entry_age_sec > policy.episodic_max_age_sec:
            return ReadOutcome.DENIED
    return ReadOutcome.ALLOWED
```

#### 1.7.7 生命周期管理（P166-F）

```python
# extensions/memory_layers/lifecycle.py
from __future__ import annotations

import time
from dataclasses import dataclass

from extensions.memory_layers.working import WorkingMemory
from extensions.memory_layers.episodic import EpisodicMemory


@dataclass
class LifecyclePolicy:
    """生命周期管理策略。"""
    working_max_entries: int = 1000
    working_default_ttl_ms: int | None = None      # None = 永不过期
    episodic_max_file_size_mb: int = 100
    episodic_gc_age_days: int | None = None        # None = 永不 GC Episodic
    auto_gc_interval_sec: int = 60


class LifecycleManager:
    """统一管理 Working + Episodic 两层的生命周期。"""

    def __init__(
        self,
        working: WorkingMemory,
        episodic: EpisodicMemory,
        policy: LifecyclePolicy | None = None,
    ):
        self.working = working
        self.episodic = episodic
        self.policy = policy or LifecyclePolicy()
        self._last_gc_time = 0.0

    def maybe_gc(self) -> dict[str, int]:
        """按需触发 GC。"""
        now = time.time()
        if now - self._last_gc_time < self.policy.auto_gc_interval_sec:
            return {"working": 0, "episodic": 0}

        result = {"working": self.working.gc(), "episodic": 0}

        # Episodic GC（按 age）
        if self.policy.episodic_gc_age_days:
            cutoff = now - (self.policy.episodic_gc_age_days * 86400)
            # 实际实现：扫描 NDJSON 文件，删除早于 cutoff 的条目
            result["episodic"] = self._gc_episodic(cutoff)

        self._last_gc_time = now
        return result

    def _gc_episodic(self, cutoff_ts: float) -> int:
        """GC 早于 cutoff_ts 的 Episodic 条目。"""
        from pathlib import Path
        import json
        path = self.episodic.storage_path
        if not path.exists():
            return 0

        kept_lines: list[str] = []
        removed = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get("created_at", 0) < cutoff_ts:
                        removed += 1
                        continue
                    kept_lines.append(line)
                except json.JSONDecodeError:
                    continue

        # 原子重写
        tmp = path.with_suffix(".gc.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write("\n".join(kept_lines) + "\n")
        tmp.replace(path)
        return removed
```

#### 1.7.8 Hook 集成

```python
# extensions/memory_layers/hooks.py
from __future__ import annotations

from typing import Any

from extensions.memory_layers.working import WorkingMemory
from extensions.memory_layers.episodic import EpisodicMemory
from extensions.memory_layers.write_policy import evaluate_write, PROFILE_WRITE_POLICIES
from extensions.memory_layers.read_policy import evaluate_read, PROFILE_READ_POLICIES


def memory_layers_write_through_hook(
    key: str,
    value: Any,
    *,
    layer: str,                              # "working" / "episodic"
    entry_type: str,
    profile_id: str | None,
    working: WorkingMemory,
    episodic: EpisodicMemory,
    audit_sink: Any | None = None,
) -> dict:
    """F-102 LoopHook 集成的写入入口（post_query_hook 调用）。

    Returns:
        {"written": bool, "outcome": str, "layer": str, "key": str}
    """
    from extensions.memory_layers.structured import MemoryLayer, MemoryType
    from extensions.memory_layers.provenance import Provenance

    policy = PROFILE_WRITE_POLICIES.get(profile_id or "default", PROFILE_WRITE_POLICIES["default"])
    mem_layer = MemoryLayer(layer)
    mem_type = MemoryType(entry_type)

    if mem_layer == MemoryLayer.WORKING:
        entry = working.write(key, value, entry_type=mem_type)
    elif mem_layer == MemoryLayer.EPISODIC:
        entry = episodic.write(key, value, entry_type=mem_type)
    else:
        return {"written": False, "outcome": "unknown_layer", "layer": layer, "key": key}

    outcome = evaluate_write(entry, policy=policy)
    if audit_sink:
        audit_sink.write(entry, outcome)
    return {
        "written": outcome.value == "allowed",
        "outcome": outcome.value,
        "layer": layer,
        "key": key,
    }


def memory_layers_read_for_context_hook(
    query: str,
    *,
    profile_id: str | None,
    session_id: str,
    working: WorkingMemory,
    episodic: EpisodicMemory,
) -> list[dict]:
    """读取相关记忆（供 system prompt 注入）。"""
    from extensions.memory_layers.structured import MemoryLayer

    policy = PROFILE_READ_POLICIES.get(profile_id or "default", PROFILE_READ_POLICIES["default"])
    results = []

    # Working Memory：直接 list_all
    if policy.working_allow:
        for entry in working.list_all():
            if query.lower() in str(entry.value).lower():
                results.append({"layer": "working", "entry": entry.to_dict()})

    # Episodic Memory：按策略过滤
    if policy.episodic_allow:
        recent = episodic.list_recent(n=20)
        for entry in recent:
            if query.lower() in str(entry.value).lower():
                # 检查策略
                read_outcome = evaluate_read(
                    MemoryLayer.EPISODIC,
                    policy=policy,
                    session_id=session_id,
                    entry_session_id=entry.session_id,
                    entry_age_sec=__import__("time").time() - entry.created_at,
                )
                if read_outcome.value == "allowed":
                    results.append({"layer": "episodic", "entry": entry.to_dict()})

    return results
```

### 1.8 核心流程

```
[Agent 产生新事实 / 决策 / 疑问]
    ↓
[F-102 LoopHook.post_query 链]
    └─→ [F-166 memory_layers_write_through_hook]
            ├─ 调用 working.write() 或 episodic.write()
            ├─ 构造 MemoryEntry（含 Provenance）
            ├─ evaluate_write(policy) → ALLOWED / DENIED
            │   ├─ ALLOWED → 实际写入
            │   └─ DENIED → 拒绝 + 写审计
            ↓
[F-102 LoopHook.pre_reply 链]
    └─→ [F-166 memory_layers_read_for_context_hook]
            ├─ 按 query 关键词检索 working + episodic
            ├─ evaluate_read(policy) 过滤
            └─ 输出相关 MemoryEntry 列表 → 注入 system prompt

[周期 GC]
    ↓
[LifecycleManager.maybe_gc()]
    ├─ Working.gc()：清理过期条目 + LRU 淘汰
    └─ Episodic.gc()：按 age_days 删除
```

### 1.9 与现有架构的对齐

| 对齐点 | 说明 |
|-------|------|
| F-119 Section Registry | 通过 `register_section("memory_layers_guide", ...)` 让模型看到当前激活层与访问规则 |
| F-102 LoopHook | 在 `post_query_hook` 链注册 `memory_layers.write_through`；在 `pre_reply_hook` 链注册 `memory_layers.read_for_context` |
| F-158 Working Memory | F-166 Working Memory **包含** F-158 VERIFIED markers 作为 `MemoryEntry(type=VERIFIED_FACT)` 子类型；不重复存储 |
| F-130 Profile | PROFILE_WRITE_POLICIES + PROFILE_READ_POLICIES 5 Profile 映射：default/strict/review/debug/creative；切换 Profile 时策略自动生效 |
| F-159 JIT 合成 | F-159 抓取结果可选择性写入 F-166 Episodic Memory（按用户配置），跨会话复用 |
| 解耦 | 全部落在 `extensions/memory_layers/`；F-102 hook 注册在 `clawcodex_ext/hooks/_pluggy_adapter.py`；F-158 ConfidenceMarker 改为 F-166 视图（不改源码）；零 `src/` 侵入 |

### 1.10 风险与缓解

| 风险 | 描述 | 缓解 |
|------|------|------|
| **Episodic 污染** | 跨会话写入的低质量条目污染未来决策 | P166-C `episodic_require_explicit=True`（默认需显式 write）+ `episodic_max_per_session=100`（默认上限） |
| **Working 爆炸** | 单会话 Working Memory 条目过多 | P166-A `max_entries=1000` + LRU 淘汰 + TTL 自动 GC |
| **Provenance 缺失** | 条目无来源，无法追溯可信度 | P166-C `require_provenance=True`（除 SCRATCH 外必填）；P166-D Provenance dataclass 必填字段 |
| **Profile 切换导致层访问变化** | 用户切 Profile 后 Episodic 突然不可读 | P166-E PROFILE_READ_POLICIES 显式声明每 Profile 访问规则；UI 层提示 |
| **NDJSON 损坏** | 单行损坏 → 整文件不可读 | P166-B `_iter_entries` 容忍 `JSONDecodeError`（跳过损坏行）+ 写审计 |
| **文件膨胀** | Episodic 文件超过 max_file_size_mb | P166-B `_rotate_if_needed` 自动轮转（带时间戳归档） |
| **与 F-158 冲突** | F-158 单独存储 VERIFIED markers 与 F-166 Working Memory 重复 | F-166 Working Memory 把 F-158 VERIFIED markers 作为 `MemoryEntry(type=VERIFIED_FACT)` **视图**（不复制数据） |
| **Wave 3 范围溢出** | 用户期望 F-166 包含 Semantic / Procedural 层 | §1.3 非目标明确：Wave 2 P1 仅 Working + Episodic；Semantic + Procedural 留 Wave 3 / F-175+ |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 说明 |
|:----:|--------|------|
| 2026-07-22 | 初始文档创建 | DC-A §4.4 映射表基础上落地 F-166 记忆分层；覆盖 DC-004；Wave 2 P1 第五个落地 F-N（Wave 2 P1 收官）；Working + Episodic 两层先落地，Semantic + Procedural 留 Wave 3；与 F-119 / F-102 / F-158 / F-130 / F-159 协同；解耦落地于 `extensions/memory_layers/`，零 `src/` 侵入 |

### 2.2 待验证项

| 编号 | 验证项 | 关联子特性 |
|:----:|--------|:----------:|
| 1 | `WorkingMemory.write` + `read` 基本路径 | P166-A |
| 2 | `WorkingMemory` LRU 淘汰（max_entries 超限） | P166-A |
| 3 | `WorkingMemory.gc` TTL 过期清理 | P166-A |
| 4 | `WorkingMemory` 线程安全（RLock） | P166-A |
| 5 | `EpisodicMemory.write` NDJSON 追加 | P166-B |
| 6 | `EpisodicMemory.read` 最新条目检索 | P166-B |
| 7 | `EpisodicMemory._rotate_if_needed` 文件轮转 | P166-B |
| 8 | `EpisodicMemory._iter_entries` 容忍 JSON 损坏行 | P166-B |
| 9 | `evaluate_write` 5 Profile 策略生效 | P166-C |
| 10 | `evaluate_read` 5 Profile 策略生效 | P166-C |
| 11 | `Provenance.from_tool` / `from_user` 构造正确 | P166-D |
| 12 | `PROFILE_WRITE_POLICIES` + `PROFILE_READ_POLICIES` 5 Profile 完整 | P166-E |
| 13 | `LifecycleManager.maybe_gc` Working + Episodic GC | P166-F |
| 14 | `LifecycleManager._gc_episodic` 按 age_days 删除 | P166-F |
| 15 | F-158 VERIFIED markers 作为 F-166 Working Memory 子类型视图（不复制数据） | 集成 |
| 16 | Hook 链顺序：F-102 post_query → F-166 write_through | 集成 |
| 17 | E2E：write → read → provenance → GC 完整流程 | 集成 |

---

## §3 实施细节

### 3.1 验收标准

**功能完整性**：
- [ ] Working Memory：进程内读写 + LRU + GC + 线程安全
- [ ] Episodic Memory：NDJSON 持久化 + session_id + 标签检索 + 轮转
- [ ] 5 Profile 写入 / 读取策略差异化生效
- [ ] Provenance 字段完整（source_tool / source_turn / source_file / source_url）
- [ ] LifecycleManager 周期 GC + 容量上限

**质量门禁**：
- [ ] Stage 5 扩展测试 `extensions.memory_layers` 模块导入通过
- [ ] `tests/memory_layers/` 8 个测试用例全 PASS
- [ ] ruff check `extensions/memory_layers/` 无 error
- [ ] 与 F-158 Working Memory 集成（视图而非复制）

**运营可见性**：
- [ ] NDJSON 审计日志可被 `jq` 查询
- [ ] UI 层可展示当前 Working Memory 条目数 + Episodic 文件大小
- [ ] Profile 切换时层访问规则立即生效（无需重启）
- [ ] GC 触发可观测（写审计日志）

### 3.2 落地路径（推荐顺序）

1. **P166-A 数据契约先行** — `MemoryEntry` / `MemoryType` / `MemoryLayer` / `Provenance` dataclass
2. **P166-A Working Memory** — 进程内读写 + LRU + GC + 线程安全
3. **P166-D Provenance** — `from_tool` / `from_user` 工厂方法
4. **P166-B Episodic Memory** — NDJSON 追加 + 检索 + 轮转
5. **P166-C 写入策略** — `WritePolicy` + 5 Profile 映射 + `evaluate_write`
6. **P166-C 读取策略** — `ReadPolicy` + 5 Profile 映射 + `evaluate_read`
7. **P166-F 生命周期** — `LifecycleManager` + Working GC + Episodic GC
8. **集成 F-158** — `ConfidenceMarker` 改为 `MemoryEntry(type=VERIFIED_FACT)` 视图
9. **P166-G 审计** — NDJSON 写入 + 与 F-158 / F-162 / F-163 / F-165 audit schema 兼容
10. **集成到 F-102 LoopHook** — `memory_layers_write_through_hook` + `memory_layers_read_for_context_hook` 注册
11. **集成测试** — F-158 / F-130 / F-159 mock 集成；E2E 完整流程

### 3.3 与 F-119 / F-102 / F-158 / F-130 / F-159 的协同点

- **F-119 `register_section`** → 注册 `memory_layers_guide` section（`order=30`，F-119 标准 section 之后），让模型看到当前激活层与访问规则
- **F-119 `dump_effective_system_prompt`** → 验证 `memory_layers_guide` section 已注入
- **F-102 LoopHook** → P166-C 在 `post_query_hook` 链注册 `memory_layers.write_through`；在 `pre_reply_hook` 链注册 `memory_layers.read_for_context`
- **F-158 `ConfidenceMarker`** → F-166 Working Memory 把 F-158 VERIFIED markers 作为 `MemoryEntry(type=VERIFIED_FACT)` **视图**；不复制数据，节省内存
- **F-130 Profile** → `PROFILE_WRITE_POLICIES` + `PROFILE_READ_POLICIES` 5 Profile 映射：default/strict/review/debug/creative；切换 Profile 时策略自动生效
- **F-159 `synthesize`** → 抓取结果可选择性写入 F-166 Episodic Memory（按用户配置 scope）；跨会话复用抓取结果

### 3.4 与 F-158 Working Memory 的边界

F-166 与 F-158 Working Memory **不重复**，定位互补：

| 维度 | F-158 Working Memory (VERIFIED) | F-166 Working Memory (完整) |
|------|------------------------------|----------------------------|
| 范围 | 仅 VERIFIED 事实 + 边界追踪 | 所有类型（决策 / 疑问 / 事实 / TODO / VERIFIED / SCRATCH） |
| 数据结构 | `ConfidenceMarker` dataclass | `MemoryEntry` dataclass（含 type 枚举） |
| 持久化 | 仅进程内 | 仅进程内（Wave 2 P1）；Wave 3 可升 Episodic |
| Provenance | 仅 `Citation`（tool / target / excerpt） | 完整 `Provenance`（tool / turn / user_input / file / url / timestamp） |
| 读取策略 | 无（任何代码可读） | Profile 限定（strict 可限制） |
| 写入策略 | 仅 scan + mark | 完整 WritePolicy + Profile 限定 |

**关键差异**：F-158 是"已验证事实"的窄视图；F-166 是"所有记忆"的宽基础。F-158 VERIFIED markers 在 F-166 Working Memory 中以 `type=VERIFIED_FACT` 形式呈现，**共享同一存储**。

---

## §4 DC-A 补充分解：Semantic 与 Procedural Memory

P166-A~G 仍只交付 Working / Episodic。本节定义 DC-004 剩余两层的后续实施边界，防止“留 Wave 3”成为未定义范围。

| 编号 | 子特性 | 实施范围 | 验收 |
|------|--------|----------|------|
| P166-H | Semantic Memory | 项目级、经审核的术语/结构/约定；只读默认 | 未审批内容不可晋升；每项可追溯到证据与审批 |
| P166-I | Procedural Memory | 可复用成功流程的版本化步骤与适用条件 | 执行前校验前置条件；失败不会自动覆盖既有流程 |
| P166-J | 晋升与回退工作流 | Working/Episodic → review queue → Semantic；支持撤销 | 审批、拒绝、撤销都有审计记录与来源链 |

**文件落点**：`extensions/memory_layers/{semantic,procedural,promotion,review_queue}.py`、`.memory/semantic/`、`.memory/procedural/` 与 `tests/memory_layers/test_{semantic,procedural,promotion}.py`。

```python
def propose_promotion(entry_id: str, *, target: Literal["semantic", "procedural"]) -> ReviewItem: ...
def approve_promotion(review_id: str, approver: str) -> MemoryEntry: ...
def retrieve_procedure(intent: str, context: Mapping[str, str]) -> Procedure | None: ...
```

Semantic 写入必须由人类或验证 Hook 批准，包含 source、confidence、expiry 和 owner；Procedural 条目必须包含 preconditions、steps、rollback 与 last_verified_at。任何自动检索结果都作为候选上下文，不得绕过 F-158/F-162 的证据与验证规则。

## §5 变更记录

| 日期 | 作者 | 变更 |
|:----:|------|------|
| 2026-07-22 | 起草 | 初始创建 | DC-A §4.4 映射表基础上落地 F-166 记忆分层；覆盖 DC-004；Wave 2 P1 第五个落地 F-N（**Wave 2 P1 收官**）；Working + Episodic 两层先落地（Semantic + Procedural 留 Wave 3 / F-168+）；Working Memory（进程内 + LRU + GC + 线程安全）+ Episodic Memory（NDJSON + session_id + 标签 + 轮转）+ Provenance 追溯（tool / turn / file / url）+ 写入/读取策略（5 Profile 映射）+ LifecycleManager（周期 GC + 容量上限）；F-158 Working Memory VERIFIED markers 作为 F-166 `MemoryEntry(type=VERIFIED_FACT)` 视图（不重复存储）；与 F-119 / F-102 / F-158 / F-130 / F-159 协同；解耦落地于 `extensions/memory_layers/`，零 `src/` 侵入 |
