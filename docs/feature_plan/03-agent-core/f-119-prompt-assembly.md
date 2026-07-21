# F-119: System Prompt 段落拼装与自迭代基础设施

> 状态: ✅ 已完成
> 章节: docs/feature_plan/03-agent-core/f-119-prompt-assembly.md
> 最后更新: 2026-07-21
> 设计来源: 2026-06-25 架构审计 + 2026-07-14 动态上下文拼接方案扩展

## §1 设计规划

### 1.1 背景

ClawCodex 当前的 system prompt 由 `clawcodex_ext/context_system/prompt_assembly.py` 拼接，结构上分为：
- **7 个静态段**（order 0-6：intro / system / doing_tasks / actions / using_tools / tone_style / output_efficiency），硬编码在模块顶层常量中，**无任何注册/扩展接口**
- **7 个动态段**（order 10-90：tool_docs / environment / memory / mcp / agents / skills / output_style / plan_mode / non_interactive / tool_restrictions），由参数驱动
- **1 个 memory 段 builder 注册表**（`register_memory_section_builder`），是当前唯一可扩展点，且仅覆盖 memory 一个段
- **2 个字符串级入口**：`append_system_prompt`（追加末尾）、`custom_system_prompt`（整体替换 7 段）

2026-07-14 动态上下文拼接（Dynamic Context Splicing）需求分析新增驱动场景：

**驱动场景 A — 编排器工作流感知**：Orchestrator 在不同阶段（issue 创建 → 代码编写 → 验证 → PR 提交）需要向系统提示注入不同的上下文（当前 Issue 标题/描述、CI 状态、SOP 指令等），这些上下文当前只能通过 `append_system_prompt` 追加到末尾，无法插入到相关段落附近。

**驱动场景 B — 三方扩展按需注上下文**：外部系统（Issue Tracker、CI Pipeline、知识库）的数据需要以声明式方式注入到系统提示的指定位置，且每个扩展应互相独立、可插拔。

**驱动场景 C — 运行时条件包含**：某些上下文片段只在特定条件下生效（如 PR 验证阶段才注入 verification 指令），需要基于运行时状态（`runtime_ctx`）的条件包含而非存在/不存在二元选择。

审计结论：
- 下游扩展（`clawcodex_ext/*`、`extensions/*`）除了 memory 段以外，**没有任何方式对单个静态段做覆盖/调整/插入新段**
- 自迭代优化（prompt A/B、版本回滚、效果观测）只能通过 `custom_system_prompt` 整体替换或 `append_system_prompt` 末尾追加，**粒度粗、cache 行为不可控、无法做小步迭代**
- 段落 cache 基础设施（`SystemPromptCache` + `CacheScope`）已就位，但 builder API 不暴露给下游
- 动态上下文注入（上述场景 A/B/C）完全不存在——无通用注册表、无条件包含机制、无运行时上下文传递、无声明式配置入口

### 1.2 目标

在不修改 `src/context_system/`（保持上游兼容 facade）的前提下，提供：

1. **通用 section builder registry**：把 `register_memory_section_builder` 模式泛化到全部 7 个静态段 + 允许插入新段
2. **段落级自迭代观测**：把当前未暴露的 `build_full_system_prompt_blocks` 内部数据 dump 出来，让自迭代框架能"看到真实 prompt"
3. **A/B 与变体框架骨架**：在 Query Engine 上方提供变体注入入口，配合 `custom_system_prompt` 短路分支做效果对比
4. **与解耦架构对齐**：所有新代码落在 `clawcodex_ext/context_system/` 或 `extensions/prompt_lab/`，不碰 `src/`
5. **动态上下文拼接能力**：提供基于 `runtime_ctx` 的条件包含、tags 筛选、`order` 数值定位的通用注入机制，让扩展可独立注册上下文提供者，在任意 position 插入/覆盖/禁用段

### 1.3 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工时 |
|:----:|--------|------|:----:|:--------:|
| P119-A | 通用 section builder registry | 把 `register_memory_section_builder` 泛化为 `register_section(id, *, builder, order, cache_scope, tags)`，用 `RegisteredSection` dataclass 承载元数据；builder 签名改为 `(runtime_ctx: dict) → str | None` | ✅ | 2-3d |
| P119-B | 段落级 override API | 暴露 `override_section(id, content, ...)` / `insert_section(after_id, ...)` / `disable_section(id)` 三类高阶操作，封装 builder 调用顺序 | ✅ | 2-3d |
| P119-C | Prompt dump 观测接口 | `dump_effective_system_prompt(query_source, format='blocks' | 'str')` 返回结构化数据（每段 id/order/scope/content/byte_len/sha256），供自迭代框架消费 | ✅ | 1-2d |
| P119-D | 自迭代元 prompt 注入器 | 通过 `register_iteration_meta_section` 注入 prompt 自迭代元指令（缓存策略、上一轮得分、本轮目标），落 `append_system_prompt` 之前的"REQUEST 段"位置 | ✅ | 1-2d |
| P119-E | 变体框架骨架（`extensions/prompt_lab/`） | Layer 2 新子系统，封装 `VariantManager` + `ExperimentAssignment` + `MetricsSink` 三个 Protocol；先提供本地 NDJSON sink，后续接扩展 | ✅ | 3-5d |
| P119-F | 段落 cache 失效联动 | 当 `override_section` 触发时，自动调用 `SystemPromptCache.invalidate(id)` 或 `invalidate_scope(scope)`，避免脏读 | ✅ | 0.5-1d |
| P119-G | 稳定性门禁 + 拼装快照测试 | 扩 `tests/misc/test_prompt_assembly.py`，覆盖 5 路径（默认 / custom / append / 7 段 override / 新段插入），保证 byte-stable | ✅ | 1d |
| P119-H | Tags 筛选 + runtime_ctx 传递 | builder registry 支持 tags 元数据 + 带 `runtime_ctx: dict` 调用 builder；`consult_sections(tags=[...])` 按标签筛选生效段；runtime_ctx 含 cwd、task_id、workflow_phase、issue_info 等 | ✅ | 1-2d |
| P119-I | Layer 2 上下文提供者扩展示例 | `extensions/context_providers/` 下实现 2-3 个参考示例（from_issue、from_ci、from_config），展示注册式上下文注入的端到端流程 | ✅ | 1-2d |

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
| `clawcodex_ext/context_system/section_registry.py`（P119-B 合并） | P119-B | `override_section(id, content, *, cache_scope=None, order=None, reason=None)` + `insert_section(...)` + `disable_section(id)`；背后通过 `DANGEROUS_uncachedSystemPromptSection` 工厂做 reason 强制 |
| `clawcodex_ext/context_system/prompt_dump.py` | P119-C | `dump_effective_system_prompt(query_source, format='blocks' \| 'str' \| 'structured')`；`structured` 模式返回 `list[SectionSnapshot]` 含 `id/order/scope/byte_len/sha256` |
| `clawcodex_ext/context_system/prompt_assembly.py`（P119-D 合并） | P119-D | `_build_iteration_meta_section(ctx)` 调用 `consult_section_builders("iteration_meta", runtime_ctx)`；实际调用时机在 `_build_full_system_prompt` 末尾、`append_system_prompt` 之前 |
| `extensions/prompt_lab/__init__.py` | P119-E | 子系统入口；导出 `VariantManager` / `ExperimentAssignment` / `MetricsSink` |
| `extensions/prompt_lab/variants.py` | P119-E | `VariantManager` — key→variant 字典 + 默认 fallback |
| `extensions/prompt_lab/experiments.py` | P119-E | `ExperimentAssignment` — 用户/session 维度的稳定 hash 分配（sticky assignment） |
| `extensions/prompt_lab/sinks/ndjson.py` | P119-E | `NDJSONMetricsSink` — 写 `.reports/prompt_lab/<date>.ndjson` |
| `extensions/prompt_lab/capabilities.py` | P119-E | 复用 `extensions/capabilities/` 风格定义 Protocol 接口契约 |
| `tests/misc/test_section_registry.py` | P119-G | 5 路径 + 7 段 override + cache 失效测试 |
| `tests/misc/test_prompt_dump.py` | P119-G | dump 格式 / sha256 稳定性 / 缺段不 panic |
| `extensions/context_providers/from_issue.py` | P119-I | 从 Issue Tracker 读取标题/描述/标签，注册为 `order=55` 的动态段 |
| `extensions/context_providers/from_ci.py` | P119-I | 注入最近 CI 运行状态（用于 PR 验证上下文） |
| `extensions/context_providers/from_config.py` | P119-I | 从 `.clawcodex/context_sections.yaml` 读取用户声明的上下文片段并注册 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/context_system/prompt_assembly.py` | 在 `_build_*_section` 7 个内部函数尾部插入 `consult_section_builders(id, order, scope)` 回调；7 段常量保持不变（与上游 TS 兼容） |
| `clawcodex_ext/context_system/prompt_assembly.py` | `__all__` 透传新模块 API（通过 facade 暴露） |
| `clawcodex_ext/context_system/prompt_assembly.py` | `build_full_system_prompt_blocks()` 中 `sections.sort()` 之前插入 `collect_registered_sections(runtime_ctx)`，遍历注册表注入动态段 |
| `src/context_system/prompt_assembly.py` | **不改**（lazy proxy 已自动透传 `_mod.__dict__`） |
| `clawcodex_ext/__init__.py` | 未新增独立 `install_section_registry_extensions()`；现有 `install_memory_extension()` 直接调用 `register_section("memory", ...)`，保持默认 memory builder 行为 |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 prompt_lab + context_providers 模块导入断言 |
| `tests/stability_gate/test_stage2_cli.py` | 增加 context_providers CLI smoke test（可选） |
| `docs/feature_plan/01-overview.md` | 三层架构图补充 `extensions/prompt_lab/` 和 `extensions/context_providers/` |
| `docs/feature_plan/README.md` | F-Number 总表 + 状态表加入 F-119 |

### 1.6 核心 API 设计

#### 1.6.1 Section Builder Registry（P119-A + P119-H）

```python
# clawcodex_ext/context_system/section_registry.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# ==== 核心数据结构 ====

@dataclass
class RegisteredSection:
    """已注册的动态上下文段元数据。"""
    id: str
    builder: Callable[[dict[str, Any]], str | None]  # (runtime_ctx) -> content | None
    order: int = 50           # 插入位置（与 SystemPromptSection.order 一致）
    cache_scope: str = "session"  # global / session / request
    tags: list[str] = field(default_factory=list)  # 如 ["workflow", "ci", "issue"]

_sections: dict[str, RegisteredSection] = {}

# ==== 注册 API ====

def register_section(
    id: str,
    *,
    builder: Callable[[dict[str, Any]], str | None],
    order: int = 50,
    cache_scope: str = "session",
    tags: list[str] | None = None,
) -> RegisteredSection:
    """注册一个动态上下文 section。

    Args:
        id: 唯一标识符，用于后续 override / disable / 引用。
        builder: ``(runtime_ctx: dict) -> str | None``。接收运行时上下文
            （含 cwd、task_id、workflow_phase、issue_info 等），
            返回段内容或 ``None``（跳过该段）。
        order: 插入位置。与 ``SystemPromptSection.order`` 语义一致，
            0-6 为静态段、10+ 为动态段。
        cache_scope: "global" / "session" / "request"。
        tags: 用于筛选分组的标签列表。
    """
    sec = RegisteredSection(
        id=id,
        builder=builder,
        order=order,
        cache_scope=cache_scope,
        tags=tags or [],
    )
    _sections[id] = sec
    return sec

def unregister_section(id: str) -> None:
    """移除已注册的 section（用于热卸载）。"""
    _sections.pop(id, None)

def get_registered_sections(
    tags: list[str] | None = None,
) -> list[RegisteredSection]:
    """返回所有已注册 section，可选按 tags 筛选（OR 逻辑）。"""
    if not tags:
        return list(_sections.values())
    return [s for s in _sections.values() if any(t in s.tags for t in tags)]

def consult_registered_sections(
    section_id: str,
    runtime_ctx: dict[str, Any],
) -> str | None:
    """按 id 查找已注册 section 并调用其 builder（用于覆盖静态段）。"""
    sec = _sections.get(section_id)
    if sec is not None:
        try:
            return sec.builder(runtime_ctx)
        except Exception:
            pass
    return None

def collect_new_sections(
    runtime_ctx: dict[str, Any],
    tags: list[str] | None = None,
) -> list[tuple[RegisteredSection, str | None]]:
    """遍历注册表，返回 (section, content) 对列表。
    用于插入非静态段 ID 的新注册 section。"""
    result: list[tuple[RegisteredSection, str | None]] = []
    for sec in get_registered_sections(tags=tags):
        # 跳过保留 ID（静态段由 consult_registered_sections 处理）
        if sec.id in _RESERVED_STATIC_IDS:
            continue
        try:
            content = sec.builder(runtime_ctx)
            if content is not None:
                result.append((sec, content))
        except Exception:
            pass
    return result
```

**与现有 `register_memory_section_builder` 的兼容**：P119-A 落地后，旧 API 标记为 `register_section("memory", builder=fn, order=25, cache_scope="request")` 的薄封装。保留旧名 2 个版本后 deprecated。

#### 1.6.1a 运行时上下文（`runtime_ctx`）契约

Builder 接收的 `runtime_ctx: dict[str, Any]` 保证包含以下键（可扩展）：

| 键 | 类型 | 来源 | 示例 |
|----|------|------|------|
| `cwd` | `str` | `build_full_system_prompt_blocks(cwd=...)` | `"/home/user/project"` |
| `workflow_phase` | `str` | 编排器注入（Orchestrator 阶段） | `"verification"` / `"pr_open"` |
| `task_id` | `str \| None` | 编排器注入 | `"F-38-issue-3"` |
| `issue_info` | `dict \| None` | 编排器注入 | `{"title": "..." , "labels": [...]}` |
| `ci_status` | `str \| None` | CI 提供者注入 | `"passing"` / `"failing"` |
| `custom` | `dict[str, Any]` | 扩展自由填充 | `{"sop_phase": "review"}` |

#### 1.6.2 段落级 Override API（P119-B）

```python
# clawcodex_ext/context_system/section_override.py
from clawcodex_ext.context_system.section_registry import (
    register_section,
    unregister_section,
    consult_registered_sections,
)

# 已知静态段 order 映射（与 prompt_assembly.py 中 _build_* 函数对齐）
_STATIC_ORDER_MAP: dict[str, int] = {
    "intro": 0,
    "system": 1,
    "doing_tasks": 2,
    "actions": 3,
    "using_tools": 4,
    "tone_style": 5,
    "output_efficiency": 6,
    "tool_docs": 10,
    "environment": 20,
    "memory": 25,
    "mcp": 30,
    "agents": 40,
    "skills": 50,
    "output_style": 60,
    "proactive": 65,
    "plan_mode": 70,
    "non_interactive": 80,
    "tool_restrictions": 90,
}

def _infer_order(section_id: str) -> int:
    """根据已知段 ID 推断 order；未知段默认 55（skills 之后、output_style 之前）。"""
    return _STATIC_ORDER_MAP.get(section_id, 55)

def override_section(
    section_id: str,
    content: str,
    *,
    reason: str = "downstream override",
    **kwargs,
) -> RegisteredSection:
    """用固定 content 覆盖指定 section。

    注册一个直接返回 content 的 builder。P119-F 联动由
    ``register_section`` 调用者自行触发（原因：新注册段不覆盖 cache
    范围，调用方确定后统一 invalidate）。
    """
    return register_section(
        section_id,
        builder=lambda _ctx: content,
        order=_infer_order(section_id),
        **kwargs,
    )

def disable_section(section_id: str) -> None:
    """注册一个永远返回 None 的 builder，等价于关闭该段。"""
    register_section(
        section_id,
        builder=lambda _ctx: None,
        order=_infer_order(section_id),
    )

def insert_section(
    after_id: str,
    new_id: str,
    content: str,
    *,
    cache_scope: str = "session",
    tags: list[str] | None = None,
    reason: str = "downstream insertion",
) -> RegisteredSection:
    """在 after_id 之后插入新段。order = after_id 的 order + 0.5。"""
    base_order = _infer_order(after_id)
    new_order = base_order + 0.5
    return register_section(
        new_id,
        builder=lambda _ctx: content,
        order=new_order,
        cache_scope=cache_scope,
        tags=tags,
    )
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

#### 1.6.5 Layer 2 上下文提供者扩展示例（P119-I）

```python
# extensions/context_providers/from_issue.py
"""示例：从 Issue Tracker 注入上下文。"""
from clawcodex_ext.context_system.section_registry import register_section

def _issue_context_builder(runtime_ctx: dict) -> str | None:
    issue = runtime_ctx.get("issue_info")
    if not issue:
        return None
    return (
        "## Current Issue Context\n"
        f"- Title: {issue.get('title', '')}\n"
        f"- Description: {issue.get('description', '')}\n"
        f"- Labels: {', '.join(issue.get('labels', []))}\n"
        f"- Phase: {runtime_ctx.get('workflow_phase', 'unknown')}"
    )

# 注册到 order=55（skills 之后、output_style 之前），tags 标记为 workflow 相关
register_section(
    "issue-context",
    builder=_issue_context_builder,
    order=55,
    tags=["workflow", "issue-tracker"],
)


# extensions/context_providers/from_ci.py
"""示例：注入 CI 状态。"""
from clawcodex_ext.context_system.section_registry import register_section

def _ci_status_builder(runtime_ctx: dict) -> str | None:
    ci = runtime_ctx.get("ci_status")
    if ci is None:
        return None
    return f"## CI Status\n- Current: {ci}\n"

register_section("ci-status", builder=_ci_status_builder, order=56, tags=["ci"])


# extensions/context_providers/from_config.py
"""示例：从 YAML 配置文件声明式注入上下文片段。"""
from clawcodex_ext.context_system.section_registry import register_section

def _config_sections_builder(runtime_ctx: dict) -> str | None:
    custom = runtime_ctx.get("custom", {})
    sections = custom.get("declared_sections", [])
    if not sections:
        return None
    return "\n\n".join(
        f"## {s['title']}\n{s['content']}" for s in sections
    )

register_section(
    "declared-config",
    builder=_config_sections_builder,
    order=57,
    tags=["config"],
)
```

### 1.7 核心注入点（`prompt_assembly.py` 修改示意）

```python
# 7 个 _build_*_section 内部函数尾部统一插入：
from clawcodex_ext.context_system.section_registry import consult_registered_sections

def _build_intro_section(use_cache: bool, runtime_ctx: dict | None = None) -> SystemPromptSection | None:
    # ... 原有逻辑 ...
    built = SystemPromptSection(id="intro", content=content,
                                cache_scope=CacheScope.GLOBAL, order=0)
    # P119-A 注入：先查注册表，再返回
    override = consult_registered_sections("intro", runtime_ctx or {})
    return override if override is not None else built

# 在 build_full_system_prompt_blocks() 中，sections.sort() 之前插入：
from clawcodex_ext.context_system.section_registry import collect_new_sections

# 收集 runtime_ctx（P119-H）
runtime_ctx: dict[str, Any] = {"cwd": cwd}
if cwd:
    runtime_ctx["workflow_phase"] = cwd  # 实际由编排器/调用方注入

# 遍历注册表，注入新段
for sec, content in collect_new_sections(runtime_ctx):
    from clawcodex_ext.context_system.system_prompt_cache import CacheScope
    sections.append(SystemPromptSection(
        id=sec.id,
        content=content,
        cache_scope=CacheScope[sec.cache_scope.upper()],
        order=sec.order,
    ))

# 继续执行 sections.sort(key=lambda s: s.order) ← 原逻辑不变
```

由于 7 个函数结构同构，可抽取 `_build_cached_section(...)` 帮助函数减少重复（提示：原代码重复 7 次的 `_prompt_cache.get / set` 模板可一并合并到 helper）。

**对上游的侵入评估**：实际 diff 共约 15 行新代码 + 7 个函数签名增加 `runtime_ctx` 可选参数。遵循黄金法则例外 #3（解耦成本 > 直接修改成本），选择直接 patch `prompt_assembly.py`，标记 `# TODO: 上游合并后移除`。

### 1.8 与现有架构的对齐

| 维度 | 现状 | F-119 落地后 |
|------|------|-------------|
| 静态 7 段可扩展 | ❌ 硬编码 | ✅ builder registry |
| 动态段可扩展 | ⚠️ 仅 memory | ✅ 全部走 registry |
| 段落级 cache 控制 | ⚠️ 内部硬编码 TTL | ✅ 暴露给下游 |
| 自迭代观测 | ❌ 无 | ✅ dump API |
| A/B 框架 | ❌ 无 | ✅ extensions/prompt_lab/ 骨架 |
| 编排器上下文注入 | ❌ 仅 `append_system_prompt` 末尾 | ✅ 按 order 插入任意位置 |
| 运行时条件包含 | ❌ 无 | ✅ `runtime_ctx` 驱动 builder 条件返回 |
| 声明式上下文配置 | ❌ 无 | ✅ `extensions/context_providers/from_config.py` |
| Tags 分组筛选 | ❌ 无 | ✅ `get_registered_sections(tags=[...])` |
| 解耦合规 | ✅ | ✅ 新增代码全在 `clawcodex_ext/` + `extensions/` |

### 1.9 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 段落 override 破坏 cache 稳定性 | 自迭代实验被 cache 命中污染 | P119-F 强制 `DANGEROUS_uncachedSystemPromptSection`，reason 必填触发 code review |
| 7 段 builder hook 引入性能损耗 | 每次 build 多走 N 次 callback | 段落数量有限（≤20），callback 链路 LRU 缓存；hot path benchmark 验证 <1ms |
| `extensions/prompt_lab/` 引入新依赖 | 影响 P0 门禁 | 0 第三方依赖，仅 stdlib + 现有模块；P119-G 门禁覆盖 |
| dump 接口泄露 prompt 内容 | 日志泄露敏感 prompt | dump 默认 `include_content=False`；开启需显式传 `include_content=True` 并打 warning 日志 |
| 上游 merge 时改 prompt_assembly 行为 | builder hook 失效 | hook 注入点用 sentinel 默认值；`consult_section_builders` 失败时 fall back 到默认段，**不抛异常** |
| 与 `register_memory_section_builder` 重复 | 两套 API 并存造成认知负担 | P119-A 落地时把 `register_memory_section_builder` 标记为 `register_section("memory", builder=fn, order=25, cache_scope="request")` 的薄封装；保留旧名 2 个版本后 deprecated |
| runtime_ctx 中敏感信息泄露 | Issue/CI 数据可能含敏感信息，被注入到 prompt 中发送给 LLM | builder 实现应过滤敏感字段；`runtime_ctx` 默认不传递 `api_key` 等敏感键；`from_ci.py` 等示例提供者附过滤说明 |
| 注册 section 热卸载导致竞态 | 在多线程场景下 unregister 与 build 并发 | P119-B 的 `register_section` 使用 `_sections` 全局 dict（非线程安全）；首期仅支持单线程/编排器串行，未来加 `threading.Lock` |

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|---------|
| 2026-06-25 | 架构审计 + 子特性分解 | 本文档 | 与 f-100/f-102 格式对齐 |
| 2026-07-21 | P119-A~I 代码落地 + 测试 + 门禁 | `clawcodex_ext/context_system/section_registry.py`, `prompt_dump.py`, `prompt_assembly.py`; `extensions/prompt_lab/`, `extensions/context_providers/`; `tests/misc/test_section_registry.py`, `test_prompt_dump.py`, `test_prompt_assembly.py`; `tests/stability_gate/test_stage5_extensions.py` | 相关 pytest 通过；Stage 5 扩展导入测试覆盖 prompt_lab / context_providers |

### 2.2 已验证项

- P119-A 落地后 `consult_section_builders` 不引入可测性能损耗
- `dump_effective_system_prompt` sha256 在相同输入下稳定（byte-stable regression test）
- `extensions/prompt_lab/` 在 `__init__` 时零 import 副作用
- `extensions/context_providers/` 示例在 CI 环境不报错（无 Issue/CI 时返回 None）
- `runtime_ctx` 中 `custom` 键不被 builder 误用为注入点（安全审计）
- 稳定性门禁 Stage 5 扩展导入测试覆盖 prompt_lab / context_providers
- 相关单元测试（`test_section_registry.py`, `test_prompt_dump.py`, `test_prompt_assembly.py`）通过

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `register_section_builder("intro", 0, GLOBAL, fn)` 后，`build_full_system_prompt()` 返回的 intro 段内容由 fn 决定 | ✅ |
| 2 | `override_section("doing_tasks", new_content, reason="X")` 后立即生效，且 `_prompt_cache` 中 doing_tasks 段被失效 | ✅ |
| 3 | `insert_section("intro", "self_iter_meta", content)` 后，新段按 order 插入 intro 与 system 之间 | ✅ |
| 4 | `disable_section("tone_style")` 后，build 输出不含 tone_style 段；其他段 order 不变 | ✅ |
| 5 | `dump_effective_system_prompt(format="structured")` 返回 `list[SectionSnapshot]`，每段 sha256 在同输入下稳定 | ✅ |
| 6 | `extensions/prompt_lab.VariantManager.register("exp1", provider).resolve("exp1", session_id="abc")` 返回稳定 variant | ✅ |
| 7 | 7 段默认内容（无 builder 注册时）与现状 byte-equal | ✅ |
| 8 | 拼装快照测试 5 路径全通过 | ✅ |
| 9 | 稳定性门禁 + orchestrator 测试通过 | ✅ |
| 10 | 不修改 `src/context_system/prompt_assembly.py` 函数体（仅依赖 facade 透传） | ✅ |
| 11 | `register_section("issue-context", builder=fn, order=55, tags=["workflow"])` 后，build 输出在 order=55 位置出现新段 | ✅ |
| 12 | `get_registered_sections(tags=["ci"])` 只返回带有 `ci` tag 的 section | ✅ |
| 13 | `consult_registered_sections("intro", {"cwd": "/tmp"})` 返回 builder 输出的内容，未注册时返回 None | ✅ |
| 14 | `from_issue.py` 在 `runtime_ctx` 无 `issue_info` 时返回 None（不阻塞 build） | ✅ |

### 3.2 落地路径（推荐顺序）

1. **P119-C（dump）先行** — 验证当前 prompt_assembly 行为可观测，建立回归基线
2. **P119-A（registry）+ P119-H（tags + runtime_ctx）一并落地** — 通用化现有 memory 注册模式，builder 签名接受 runtime_ctx
3. **P119-B（override）+ P119-F（cache 联动）一并** — 段落级操作 API
4. **P119-D（iter meta）落 clawcodex_ext** — 自迭代元 prompt 注入
5. **P119-E（prompt_lab）落 extensions/** — A/B 框架骨架
6. **P119-I（context_providers 示例）落 extensions/** — 2-3 个参考实现，验证端到端流程
7. **P119-G（测试 + 门禁）全程伴随** — 每个 P119-X 落地后立即补测试

### 3.3 与 F-100 / F-102 的协同点

- **F-100 dreaming consolidate** 后调用 `get_system_prompt_cache().invalidate_scope(REQUEST)`，自然把 P119-B 注入的 REQUEST 段也失效
- **F-102 P102-D LoopHook pre_llm** 阶段可调用 `dump_effective_system_prompt(include_content=False)` 把快照 sha256 写入 hook event payload，供自迭代评估器使用
- **F-68 feature gate** 关闭 prompt_lab 时，`extensions/prompt_lab/__init__` 的 `install()` 应为 no-op

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-25 | 初始创建 | 架构审计后规划系统 prompt 段落拼装与自迭代基础设施 |
| 2026-07-14 | 引入动态上下文拼接方案 | 新增 P119-H（tags + runtime_ctx）、P119-I（context_providers 示例）；简化 P119-A 注册表设计（`RegisteredSection` dataclass + `id`-keyed dict）；builder 签名改为 `(runtime_ctx: dict) → str | None`；新增 `collect_new_sections()` 遍历新段注入；补充编排器工作流感知、条件包含、声明式配置三大驱动场景 |
| 2026-07-21 | 代码落地并标记完成 | P119-A~I 全部实现：`section_registry.py` 统一注册/override/insert/disable 与 tags/runtime_ctx；`prompt_dump.py` 提供 structured/blocks/str 三种 dump；`prompt_assembly.py` 全段接入 registry；`extensions/prompt_lab/` 变体框架骨架；`extensions/context_providers/` 三个示例提供者；测试与 Stage 5 门禁覆盖。`section_override.py` / `iter_meta.py` 功能合并入 `section_registry.py` / `prompt_assembly.py`。状态升级为 ✅ 已完成 |
