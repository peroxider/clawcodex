# F-119: System Prompt 段落拼装与自迭代基础设施

> 状态: 📋 规划中
> 章节: docs/feature_plan/03-agent-core/f-119-prompt-assembly.md
> 最后更新: 2026-06-25
> 设计来源: 2026-06-25 对 `clawcodex_ext/context_system/prompt_assembly.py` 的架构审计

## §1 设计规划

### 1.1 背景

ClawCodex 当前的 system prompt 由 `clawcodex_ext/context_system/prompt_assembly.py` 拼接，结构上分为：
- **7 个静态段**（order 0-6：intro / system / doing_tasks / actions / using_tools / tone_style / output_efficiency），硬编码在模块顶层常量中，**无任何注册/扩展接口**
- **7 个动态段**（order 10-90：tool_docs / environment / memory / mcp / agents / skills / output_style / plan_mode / non_interactive / tool_restrictions），由参数驱动
- **1 个 memory 段 builder 注册表**（`register_memory_section_builder`），是当前唯一可扩展点，且仅覆盖 memory 一个段
- **2 个字符串级入口**：`append_system_prompt`（追加末尾）、`custom_system_prompt`（整体替换 7 段）

审计结论：
- 下游扩展（`clawcodex_ext/*`、`extensions/*`）除了 memory 段以外，**没有任何方式对单个静态段做覆盖/调整/插入新段**
- 自迭代优化（prompt A/B、版本回滚、效果观测）只能通过 `custom_system_prompt` 整体替换或 `append_system_prompt` 末尾追加，**粒度粗、cache 行为不可控、无法做小步迭代**
- 段落 cache 基础设施（`SystemPromptCache` + `CacheScope`）已就位，但 builder API 不暴露给下游

### 1.2 目标

在不修改 `src/context_system/`（保持上游兼容 facade）的前提下，提供：

1. **通用 section builder registry**：把 `register_memory_section_builder` 模式泛化到全部 7 个静态段 + 允许插入新段
2. **段落级自迭代观测**：把当前未暴露的 `build_full_system_prompt_blocks` 内部数据 dump 出来，让自迭代框架能"看到真实 prompt"
3. **A/B 与变体框架骨架**：在 Query Engine 上方提供变体注入入口，配合 `custom_system_prompt` 短路分支做效果对比
4. **与解耦架构对齐**：所有新代码落在 `clawcodex_ext/context_system/` 或 `extensions/prompt_lab/`，不碰 `src/`

### 1.3 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工时 |
|:----:|--------|------|:----:|:--------:|
| P119-A | 通用 section builder registry | 仿 `register_memory_section_builder`，把 7 段 + 动态段均纳入 `(section_id, order, cache_scope)` 三键索引的可注册回调 | 📋 | 2-3d |
| P119-B | 段落级 override API | 暴露 `override_section(id, content, ...)` / `insert_section(after_id, ...)` / `disable_section(id)` 三类高阶操作，封装 builder 调用顺序 | 📋 | 2-3d |
| P119-C | Prompt dump 观测接口 | `dump_effective_system_prompt(query_source, format='blocks' \| 'str')` 返回结构化数据（每段 id/order/scope/content/byte_len/sha256），供自迭代框架消费 | 📋 | 1-2d |
| P119-D | 自迭代元 prompt 注入器 | 通过 `register_iteration_meta_section` 注入 prompt 自迭代元指令（缓存策略、上一轮得分、本轮目标），落 `append_system_prompt` 之前的"REQUEST 段"位置 | 📋 | 1-2d |
| P119-E | 变体框架骨架（`extensions/prompt_lab/`） | Layer 2 新子系统，封装 `VariantManager` + `ExperimentAssignment` + `MetricsSink` 三个 Protocol；先提供本地 NDJSON sink，后续接扩展 | 📋 | 3-5d |
| P119-F | 段落 cache 失效联动 | 当 `override_section` 触发时，自动调用 `SystemPromptCache.invalidate(id)` 或 `invalidate_scope(scope)`，避免脏读 | 📋 | 0.5-1d |
| P119-G | 稳定性门禁 + 拼装快照测试 | 扩 `tests/misc/test_prompt_assembly.py`，覆盖 5 路径（默认 / custom / append / 7 段 override / 新段插入），保证 byte-stable | 📋 | 1d |

### 1.4 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-100 Dreaming | 协同 | 记忆 consolidation 后可能需清空 memory 段 cache，P119-F 联动 |
| F-102 Hook Extensions | 协同 | P119-D 可作为 P102-D LoopHook 的 `pre_llm` 阶段调用源（注入元 prompt） |
| F-68 Feature Gate | 消费者 | 自迭代能力应受 feature flag 控制，关闭时不写元 prompt、不 dump |
| F-69 Budget Mode | 消费者 | dump/prompt 观测应受 budget 控制，超 budget 时跳过非必要段 |
| F-70 Plugin 系统 | 前置 | P119-E 变体框架可作为 plugin 注册的一种特殊形态（register_variant_provider） |
| 上游 `src/context_system/prompt_assembly.py` | 仅 facade | 不修改，仅确保 `__getattr__` 透传新 API |

### 1.5 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `clawcodex_ext/context_system/section_registry.py` | P119-A | `SectionBuilder` 协议 + `_section_builders: dict[(id, order, scope), list[Callable]]` + `register_section_builder(id, order, scope, builder)` + `consult_section_builders(...)` |
| `clawcodex_ext/context_system/section_override.py` | P119-B | `override_section(id, content, *, cache_scope=None, order=None, reason=None)` + `insert_section(...)` + `disable_section(id)`；背后通过 `DANGEROUS_uncachedSystemPromptSection` 工厂做 reason 强制 |
| `clawcodex_ext/context_system/prompt_dump.py` | P119-C | `dump_effective_system_prompt(query_source, format='blocks' \| 'str' \| 'structured')`；`structured` 模式返回 `list[SectionSnapshot]` 含 `id/order/scope/byte_len/sha256` |
| `clawcodex_ext/context_system/iter_meta.py` | P119-D | `register_iteration_meta_section(builder)`；调用时机在 `_build_full_system_prompt` 末尾、`append_system_prompt` 之前 |
| `extensions/prompt_lab/__init__.py` | P119-E | 子系统入口；导出 `VariantManager` / `ExperimentAssignment` / `MetricsSink` |
| `extensions/prompt_lab/variants.py` | P119-E | `VariantManager` — key→variant 字典 + 默认 fallback |
| `extensions/prompt_lab/experiments.py` | P119-E | `ExperimentAssignment` — 用户/session 维度的稳定 hash 分配（sticky assignment） |
| `extensions/prompt_lab/sinks/ndjson.py` | P119-E | `NDJSONMetricsSink` — 写 `.reports/prompt_lab/<date>.ndjson` |
| `extensions/prompt_lab/capabilities.py` | P119-E | 复用 `extensions/capabilities/` 风格定义 Protocol 接口契约 |
| `tests/misc/test_section_registry.py` | P119-G | 5 路径 + 7 段 override + cache 失效测试 |
| `tests/misc/test_prompt_dump.py` | P119-G | dump 格式 / sha256 稳定性 / 缺段不 panic |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/context_system/prompt_assembly.py` | 在 `_build_*_section` 7 个内部函数尾部插入 `consult_section_builders(id, order, scope)` 回调；7 段常量保持不变（与上游 TS 兼容） |
| `clawcodex_ext/context_system/prompt_assembly.py` | `__all__` 透传新模块 API（通过 facade 暴露） |
| `src/context_system/prompt_assembly.py` | **不改**（lazy proxy 已自动透传 `_mod.__dict__`） |
| `clawcodex_ext/__init__.py` | `install_section_registry_extensions()` 在 import 时自动注册默认 builder（保持现有行为） |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 prompt_lab 模块导入断言 |
| `docs/feature_plan/01-overview.md` | 三层架构图补充 `extensions/prompt_lab/` |
| `docs/feature_plan/README.md` | F-Number 总表 + 状态表加入 F-119 |

### 1.6 核心 API 设计

#### 1.6.1 Section Builder Registry（P119-A）

```python
# clawcodex_ext/context_system/section_registry.py
from typing import Callable, Protocol
from enum import Enum

class SectionScope(str, Enum):
    GLOBAL = "global"
    SESSION = "session"
    REQUEST = "request"

class SectionBuilder(Protocol):
    """Builder callback 返回 SystemPromptSection | None.
    第一个返回非 None 的 builder 胜出，与 memory 段行为一致。"""
    def __call__(self) -> "SystemPromptSection | None": ...

# 索引: (section_id, order, scope) -> list[SectionBuilder]
_section_builders: dict[tuple[str, int, SectionScope], list[SectionBuilder]] = {}

def register_section_builder(
    section_id: str,
    order: int,
    scope: SectionScope,
    builder: SectionBuilder,
) -> None:
    """注册一个 section builder。多次注册按调用顺序链式；第一个返回非 None 的胜出。"""
    key = (section_id, order, scope)
    _section_builders.setdefault(key, []).append(builder)

def consult_section_builders(
    section_id: str,
    order: int,
    scope: SectionScope,
) -> "SystemPromptSection | None":
    """按注册顺序调用 builder，返回第一个非 None；无注册返回 None。"""
    for builder in _section_builders.get((section_id, order, scope), []):
        result = builder()
        if result is not None:
            return result
    return None
```

#### 1.6.2 段落级 Override API（P119-B）

```python
# clawcodex_ext/context_system/section_override.py
from clawcodex_ext.context_system.system_prompt_cache import (
    SystemPromptSection, CacheScope, DANGEROUS_uncachedSystemPromptSection,
)
from clawcodex_ext.context_system.section_registry import consult_section_builders
from clawcodex_ext.context_system.prompt_assembly import get_system_prompt_cache

def override_section(
    section_id: str,
    content: str,
    *,
    cache_scope: CacheScope | None = None,
    order: int | None = None,
    reason: str = "downstream override",
) -> SystemPromptSection:
    """用 content 替换指定 section 的默认内容。
    cache_break=True（强制每轮重算），避免误用 cache 导致旧内容残留。
    reason 必填，触发 DANGEROUS 命名约定的 code review 关注。"""
    section = DANGEROUS_uncachedSystemPromptSection(
        name=section_id,
        content=content,
        reason=reason,
        cache_scope=cache_scope or CacheScope.SESSION,
        order=order or _infer_order(section_id),
    )
    # 注册为最高优先级的 builder，下次 build 时自动覆盖
    register_section_builder(section_id, section.order, section.cache_scope,
                             lambda: section)
    # 立即清空该段 cache（P119-F 联动）
    get_system_prompt_cache().invalidate(section_id)
    if section.cache_break:
        get_system_prompt_cache().invalidate_scope(section.cache_scope)
    return section

def disable_section(section_id: str) -> None:
    """注册一个永远返回 None 的 builder，等价于关闭该段。"""
    register_section_builder(section_id, _infer_order(section_id), CacheScope.SESSION,
                             lambda: None)

def insert_section(
    after_id: str,
    new_id: str,
    content: str,
    *,
    cache_scope: CacheScope = CacheScope.SESSION,
    reason: str = "downstream insertion",
) -> SystemPromptSection:
    """在 after_id 之后插入新段。order = after_id 的 order + 0.5（避开整数排序）。"""
    base_order = _infer_order(after_id)
    new_order = base_order + 0.5
    section = DANGEROUS_uncachedSystemPromptSection(
        name=new_id, content=content, reason=reason,
        cache_scope=cache_scope, order=int(new_order) if new_order == int(new_order) else new_order,
    )
    register_section_builder(new_id, section.order, section.cache_scope, lambda: section)
    return section
```

#### 1.6.3 Prompt Dump（P119-C）

```python
# clawcodex_ext/context_system/prompt_dump.py
import hashlib
import json
from typing import Literal

@dataclass
class SectionSnapshot:
    id: str
    order: float
    cache_scope: str
    byte_len: int
    sha256: str
    content: str  # 可选，含/不含由 include_content 参数控制
    source: Literal["default", "builder_override", "disabled", "appended"]

def dump_effective_system_prompt(
    query_source: str = "main",
    format: Literal["blocks", "str", "structured"] = "structured",
    *,
    cwd: str | None = None,
    tools: list | None = None,
    mcp_servers: list | None = None,
    custom_system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    include_content: bool = False,
) -> list[SectionSnapshot] | list[dict] | str:
    """调用 build_full_system_prompt_blocks() 并把每段结构化序列化。
    自迭代框架据此：(1) 计算 prompt 漂移 diff、(2) 写回归基线、(3) 喂 evaluator。
    """
    blocks = build_full_system_prompt_blocks(
        cwd=cwd, tools=tools, mcp_servers=mcp_servers,
        custom_system_prompt=custom_system_prompt,
        append_system_prompt=append_system_prompt,
        query_source=query_source,
    )
    snapshots: list[SectionSnapshot] = []
    for i, block in enumerate(blocks):
        text = block.get("text", "")
        snapshots.append(SectionSnapshot(
            id=f"block_{i}",  # 见改进项：id 需从 section 元数据传递
            order=float(i),
            cache_scope=("global" if "cache_control" in block and
                         block["cache_control"].get("scope") == "global" else "session"),
            byte_len=len(text.encode("utf-8")),
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            content=text if include_content else "",
            source="appended" if i == len(blocks) - 1 and append_system_prompt else "default",
        ))
    if format == "structured":
        return snapshots
    if format == "blocks":
        return blocks
    return "\n\n".join(b.get("text", "") for b in blocks)
```

**改进项（待 P119-A 落地后补全）**：block 现在不带 `section_id` 元数据（已被 prompt_assembly 序列化时丢），需要让 `build_full_system_prompt_blocks` 在 `text` 字段外加 `_section_id` 内部字段（API caller 不可见，但 dump 时可读）。

#### 1.6.4 变体框架（P119-E）

```python
# extensions/prompt_lab/variants.py
from typing import Callable, Any
from extensions.prompt_lab.capabilities import VariantProvider

class VariantManager:
    """管理 prompt 变体集合的最小骨架。
    Layer 2 子系统，不依赖具体实现——通过 extensions/capabilities/ 暴露 Protocol。"""
    def __init__(self) -> None:
        self._providers: dict[str, VariantProvider] = {}

    def register(self, experiment_id: str, provider: VariantProvider) -> None:
        self._providers[experiment_id] = provider

    def resolve(
        self, experiment_id: str, *, session_id: str, query_source: str = "main",
    ) -> str:
        provider = self._providers.get(experiment_id)
        if provider is None:
            return "control"
        return provider.assign(session_id=session_id, query_source=query_source)

# extensions/prompt_lab/capabilities.py
from typing import Protocol

class VariantProvider(Protocol):
    """变体分配器接口——实现可基于 hash、配置、远端 feature flag 服务等。"""
    def assign(self, *, session_id: str, query_source: str) -> str: ...
    def content_for(self, variant: str) -> str: ...

class MetricsSink(Protocol):
    """自迭代指标落盘接口——首期实现 NDJSON，后续可接 OTLP/Prom。"""
    def record(self, event: "PromptEvent") -> None: ...
```

### 1.7 核心注入点（`prompt_assembly.py` 修改示意）

```python
# 7 个 _build_*_section 内部函数尾部统一插入：
def _build_intro_section(use_cache: bool) -> SystemPromptSection | None:
    # ... 原有逻辑 ...
    built = SystemPromptSection(id="intro", content=content,
                                cache_scope=CacheScope.GLOBAL, order=0)
    # P119-A 注入：先查 builder，再返回
    override = consult_section_builders("intro", 0, CacheScope.GLOBAL)
    return override if override is not None else built
```

由于 7 个函数结构同构，可抽取 `_build_cached_section(...)` 帮助函数减少重复（提示：原代码重复 7 次的 `_prompt_cache.get / set` 模板可一并合并到 helper）。

### 1.8 与现有架构的对齐

| 维度 | 现状 | F-119 落地后 |
|------|------|-------------|
| 静态 7 段可扩展 | ❌ 硬编码 | ✅ builder registry |
| 动态段可扩展 | ⚠️ 仅 memory | ✅ 全部走 registry |
| 段落级 cache 控制 | ⚠️ 内部硬编码 TTL | ✅ 暴露给下游 |
| 自迭代观测 | ❌ 无 | ✅ dump API |
| A/B 框架 | ❌ 无 | ✅ extensions/prompt_lab/ 骨架 |
| 解耦合规 | ✅ | ✅ 新增代码全在 `clawcodex_ext/` + `extensions/` |

### 1.9 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 段落 override 破坏 cache 稳定性 | 自迭代实验被 cache 命中污染 | P119-F 强制 `DANGEROUS_uncachedSystemPromptSection`，reason 必填触发 code review |
| 7 段 builder hook 引入性能损耗 | 每次 build 多走 N 次 callback | 段落数量有限（≤20），callback 链路 LRU 缓存；hot path benchmark 验证 <1ms |
| `extensions/prompt_lab/` 引入新依赖 | 影响 P0 门禁 | 0 第三方依赖，仅 stdlib + 现有模块；P119-G 门禁覆盖 |
| dump 接口泄露 prompt 内容 | 日志泄露敏感 prompt | dump 默认 `include_content=False`；开启需显式传 `include_content=True` 并打 warning 日志 |
| 上游 merge 时改 prompt_assembly 行为 | builder hook 失效 | hook 注入点用 sentinel 默认值；`consult_section_builders` 失败时 fall back 到默认段，**不抛异常** |
| 与 `register_memory_section_builder` 重复 | 两套 API 并存造成认知负担 | P119-A 落地时把 `register_memory_section_builder` 标记为 `register_section_builder("memory", 25, REQUEST)` 的薄封装；保留旧名 2 个版本后 deprecated |

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|---------|
| 2026-06-25 | 架构审计 + 子特性分解 | 本文档 | 与 f-100/f-102 格式对齐 |

### 2.2 待验证项

- P119-A 落地后 `consult_section_builders` 不引入可测性能损耗
- `dump_effective_system_prompt` sha256 在相同输入下稳定（byte-stable regression test）
- `extensions/prompt_lab/` 在 `__init__` 时零 import 副作用
- 稳定性门禁全量（Stage 1-5 + 7-9）通过
- Orchestrator 单元测试（排除 manual_e2e_f38.py）通过

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `register_section_builder("intro", 0, GLOBAL, fn)` 后，`build_full_system_prompt()` 返回的 intro 段内容由 fn 决定 | 📋 |
| 2 | `override_section("doing_tasks", new_content, reason="X")` 后立即生效，且 `_prompt_cache` 中 doing_tasks 段被失效 | 📋 |
| 3 | `insert_section("intro", "self_iter_meta", content)` 后，新段按 order 插入 intro 与 system 之间 | 📋 |
| 4 | `disable_section("tone_style")` 后，build 输出不含 tone_style 段；其他段 order 不变 | 📋 |
| 5 | `dump_effective_system_prompt(format="structured")` 返回 `list[SectionSnapshot]`，每段 sha256 在同输入下稳定 | 📋 |
| 6 | `extensions/prompt_lab.VariantManager.register("exp1", provider).resolve("exp1", session_id="abc")` 返回稳定 variant | 📋 |
| 7 | 7 段默认内容（无 builder 注册时）与现状 byte-equal | 📋 |
| 8 | 拼装快照测试 5 路径全通过 | 📋 |
| 9 | 稳定性门禁 + orchestrator 测试通过 | 📋 |
| 10 | 不修改 `src/context_system/prompt_assembly.py` 函数体（仅依赖 facade 透传） | 📋 |

### 3.2 落地路径（推荐顺序）

1. **P119-C（dump）先行** — 验证当前 prompt_assembly 行为可观测，建立回归基线
2. **P119-A（registry）落地** — 通用化现有 memory 注册模式
3. **P119-B（override）+ P119-F（cache 联动）一并** — 段落级操作 API
4. **P119-D（iter meta）落 clawcodex_ext** — 自迭代元 prompt 注入
5. **P119-E（prompt_lab）落 extensions/** — A/B 框架骨架
6. **P119-G（测试 + 门禁）全程伴随** — 每个 P119-X 落地后立即补测试

### 3.3 与 F-100 / F-102 的协同点

- **F-100 dreaming consolidate** 后调用 `get_system_prompt_cache().invalidate_scope(REQUEST)`，自然把 P119-B 注入的 REQUEST 段也失效
- **F-102 P102-D LoopHook pre_llm** 阶段可调用 `dump_effective_system_prompt(include_content=False)` 把快照 sha256 写入 hook event payload，供自迭代评估器使用
- **F-68 feature gate** 关闭 prompt_lab 时，`extensions/prompt_lab/__init__` 的 `install()` 应为 no-op

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-25 | 初始创建 | 架构审计后规划系统 prompt 段落拼装与自迭代基础设施 |
