# F-160: 反事实推理 — 强制"如果我错了，最可能错在哪"显式化

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-160-counterfactual-reasoning.md`
> 最后更新: 2026-07-22
> 设计来源: DC-A 元架构脑暴 [§3.C 推理扩展 — DC-012](dynamic-context-architecture.md)

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 1 推理扩展轻量级特性（P0，~1-2 周，**门槛最低**：纯 prompt + 1 个 Hook） |
| 覆盖 DC | DC-012 反事实推理 |
| 前置依赖 | F-119 Section Registry（用于注入 prompt 段）、F-102 Hook 扩展点（用于自检） |
| 协同 | F-130 Profile 体系（debug Profile 可加重反事实权重）、F-158-A VERIFIED source、F-161 涌现发现、F-163 对抗质疑器（共享 Critic persona） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/counterfactual/`，零 `src/` 侵入 |
| 落地形态 | CLAUDE.md / 输出风格约束 + 反事实 prompt 模板 + 预注入 section + 自检 Hook |

---

## §1 设计规划

### 1.1 背景

LLM 的过度自信是幻觉的隐性根源之一——模型倾向于"自信地说出一个结论"而不主动考虑"如果我错了会怎样"。**反事实推理 (Counterfactual Reasoning)** 是显式训练 agent 思考"如果我错了，最可能错在哪？什么证据会反驳我？"的最简单动作。

相比 F-163 对抗质疑器（需要独立 sub-agent 翻倍成本）和 F-164 多视角扇出（需要多 agent 编排），F-160 是**纯 prompt 工程 + 1 个自检 Hook**，几乎不引入 token 开销，但能显著降低过度自信导致的错误结论。

### 1.2 目标

- 让"如果错了，最可能错在哪"成为 Agent 在每次最终结论前的**强制行为**
- 提供反事实 prompt 模板（决策 / 断言 / 推荐 3 类）
- 通过 F-119 把反事实模板注入到 system prompt 末段
- 自检 Hook 检测 reply 中是否含 "Counterfactual Check" 块；缺失则警告（不强制中断）
- 与 F-158-A VERIFIED 标记协同——反事实发现的反驳证据可触发 INFERRED 降级
- 与 F-163 对抗质疑器共享 persona — 可作为 F-163 Critic prompt 的轻量级 baseline

### 1.3 非目标 (Out of Scope)

- 不替代 F-163 对抗质疑器（独立 sub-agent）—— F-160 是 prompt 层 baseline，F-163 是结构化纵深
- 不替代 F-164 多视角扇出 —— F-160 是单 agent 自我反思，F-164 是多 agent 横向综合
- 不引入新的 LLM 调用 —— 纯 prompt 注入 + Hook 拦截
- 不做跨会话反事实记忆 —— 依赖 F-166 记忆分层

### 1.4 子特性分解

| 编号 | 子特性 | 状态 | 工时 |
|:----:|--------|:----:|:----:|
| P160-A | 反事实 prompt 模板（决策 / 断言 / 推荐 三类） | 📋 | 1d |
| P160-B | 预注入 section（通过 F-119 register_section） | 📋 | 1d |
| P160-C | 反事实自检 Hook（缺失警告，不强制中断） | 📋 | 1d |
| P160-D | 与 F-158 / F-163 / F-130 协同（共享 persona / INFERRED 降级） | 📋 | 1-2d |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-119 Section Registry | **强协同** | P160-B 通过 `register_section` 把反事实模板注入到 `counterfactual_guide` section |
| F-102 Hook 扩展点 | **强协同** | P160-C `post_reply_hook` 检测反事实块是否存在 |
| F-130 Profile 体系 | **协同** | debug Profile 可加重反事实权重（多列 1-2 个原因） |
| F-158 抗幻觉基线 | **协同** | 反事实发现的反驳证据可触发 F-158-A INFERRED 降级 |
| F-163 对抗质疑器（Wave 2） | **下游** | F-163 Critic prompt 可引用 F-160 模板作为轻量级 baseline |
| F-161 涌现发现（Wave 1 后续） | **协同** | F-161 反思 prompt 可包含 "反事实检查" 步骤 |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/counterfactual/__init__.py` | — | 子系统入口，注册 templates / injector / hooks |
| `extensions/counterfactual/templates.py` | P160-A | 3 类反事实 prompt 模板（decision / assertion / recommendation） |
| `extensions/counterfactual/injector.py` | P160-B | `register_counterfactual_section()` 通过 F-119 注入 |
| `extensions/counterfactual/hooks.py` | P160-C | `post_reply_hook` 检测反事实块 |
| `extensions/counterfactual/capabilities.py` | — | Protocol 接口契约（`TemplateRenderer` / `SelfChecker`） |
| `tests/counterfactual/test_templates.py` | P160-A | 3 类模板格式化 + 关键占位符替换 |
| `tests/counterfactual/test_hooks.py` | P160-C | 反事实块检测 + 警告生成 |
| `tests/counterfactual/test_e2e.py` | 全部 | 端到端：模板注入 → Agent 输出 → Hook 检测 → INFERRED 降级 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_counterfactual_extensions()` 在 import 时注册模板 + 注入 section |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | `post_reply_hook` 中追加 `counterfactual.self_check` |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.counterfactual` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-160 |
| `docs/feature_plan/dynamic-context-architecture.md` | §8 变更记录加 F-160 启动行 |

### 1.7 核心 Prompt 模板（P160-A）

#### 1.7.1 决策类反事实模板

```python
# extensions/counterfactual/templates.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TemplateKind = Literal["decision", "assertion", "recommendation"]

DECISION_TEMPLATE = """
## Counterfactual Check（决策类）

你刚刚给出的决策：**{decision}**

请显式回答以下问题（不要省略，不要泛泛而谈）：

1. **最可能让此决策错的 2 个原因** — 具体到可验证的事实层面，不是"考虑不周"这种套话
2. **什么证据会反驳此决策** — 如果存在以下证据：[列出 1-2 个具体可观察的信号]，应立即弱化结论
3. **如果发现反驳证据，应如何修正** — 给出至少 1 个具体的替代方向

格式要求：
- 用 `### Counterfactual` 块包裹上述回答
- 若反驳证据不存在 → 在块末尾标注 `[REINFORCED]` 表示结论被强化
- 若反驳证据可能存在 → 在块末尾标注 `[WEAKENED]` 并降级结论措辞
"""

ASSERTION_TEMPLATE = """
## Counterfactual Check（断言类）

你刚刚给出的事实断言：**{assertion}**

请显式回答：

1. **断言的可证伪条件** — 什么观察结果会证明此断言错误？
2. **断言的隐含假设** — 此断言成立需要哪些前提？哪些前提可能不成立？
3. **反例检索建议** — 如果有时间，应去哪里 / 用什么工具检索反例？（如 `Grep("X", scope="project")` / `WebFetch("X 官方文档")`）

格式要求：
- 用 `### Counterfactual` 块包裹
- 若断言已被 F-158 VERIFIED → 块末尾标注 `[VERIFIED_PROTECTED]`，无需弱化
- 若断言为 INFERRED → 块末尾标注 `[INFERRED_VULNERABLE]`，可考虑弱化措辞
"""

RECOMMENDATION_TEMPLATE = """
## Counterfactual Check（推荐类）

你刚刚给出的推荐：**{recommendation}**

请显式回答：

1. **推荐的隐含成本** — 此推荐需要付出什么代价？（时间 / 性能 / 复杂度 / 维护）
2. **推荐的失败模式** — 在什么场景下此推荐会失败？
3. **替代方案** — 至少给出 1 个同等目标的替代方向

格式要求：
- 用 `### Counterfactual` 块包裹
- 块末尾标注 `[COST_AWARE]` / `[FAILURE_AWARE]` / `[ALTERNATIVES_PROVIDED]` 至少一项
"""

@dataclass(frozen=True)
class TemplateRegistry:
    """3 类模板注册表。"""
    decision: str = DECISION_TEMPLATE
    assertion: str = ASSERTION_TEMPLATE
    recommendation: str = RECOMMENDATION_TEMPLATE


TEMPLATES = TemplateRegistry()


def render_template(kind: TemplateKind, **kwargs: str) -> str:
    """渲染指定类型的反事实模板。

    Args:
        kind: 模板类别（decision / assertion / recommendation）
        **kwargs: 模板占位符填充（如 decision="采用 X 方案"）

    Returns:
        完整 prompt 片段，可拼接到 system prompt 末段
    """
    template = getattr(TEMPLATES, kind)
    try:
        return template.format(**kwargs)
    except KeyError as e:
        raise ValueError(f"Missing template placeholder: {e}") from e


def select_kind_from_context(text: str) -> TemplateKind:
    """根据 Agent 输出的最近内容启发式选择模板类型。

    简化策略：
    - 含 "决策 / decide / 采用" → decision
    - 含 "断言 / is / 一定是 / 存在" → assertion
    - 含 "推荐 / 建议 / 考虑" → recommendation
    - 默认 decision
    """
    t = text.lower()
    if any(kw in t for kw in ["决定", "决策", "采用", "decide", "decision", "choose"]):
        return "decision"
    if any(kw in t for kw in ["断言", "一定是", "肯定是", "确实", "is", "exists"]):
        return "assertion"
    if any(kw in t for kw in ["推荐", "建议", "考虑", "recommend", "suggest"]):
        return "recommendation"
    return "decision"
```

#### 1.7.2 预注入 section（P160-B）

```python
# extensions/counterfactual/injector.py
from __future__ import annotations

from typing import Any
from .templates import render_template, select_kind_from_context, TemplateKind


def register_counterfactual_section() -> str:
    """通过 F-119 register_section 把反事实模板注入 system prompt 末段。

    Returns:
        注册的 section_id
    """
    from clawcodex_ext.context_system.section_registry import register_section

    section_id = "counterfactual_guide"

    def _builder(_ctx: Any) -> str:
        # builder 每次构建时返回固定的反事实指南（不带具体决策内容）
        # 具体决策内容由 Agent 在生成 reply 时按需调用 render_template
        return COUNTERFACTUAL_GUIDE_SECTION

    register_section(
        section_id,
        builder=_builder,
        order=80,                       # 靠后：让 Agent 先看到其他指南
        cache_scope="session",
        tags=["counterfactual", "reasoning"],
    )
    return section_id


COUNTERFACTUAL_GUIDE_SECTION = """
## Counterfactual Reasoning（反事实推理）

### 核心原则
每个最终结论前必须附加 **Counterfactual Check** 块 — 显式回答"如果错了，最可能错在哪"。

### 何时使用
- 决策类输出（"采用 X 方案"） → 列出 2 个最可能的反驳原因
- 事实断言（"X 一定是 Y"） → 列出可证伪条件 + 隐含假设
- 推荐建议（"建议用 X"） → 列出隐含成本 + 失败模式 + 替代方案

### 强制行为
- 每个最终结论前必须有 `### Counterfactual` 块
- 反驳证据不存在 → 标注 `[REINFORCED]` 强化结论
- 反驳证据可能存在 → 标注 `[WEAKENED]` 弱化结论措辞
- 与 F-158 抗幻觉协同：反事实发现的反驳证据触发 INFERRED 降级

### 模板
```python
from extensions.counterfactual.templates import render_template

# 在生成最终结论前调用
prompt = render_template("decision", decision="你的决策内容")
```
"""


def maybe_inject_for_reply(reply: str) -> str | None:
    """根据 reply 内容启发式选择模板，返回额外注入片段。

    返回 None 表示无需额外注入（仅靠 system prompt 中的指南已足够）。
    """
    kind = select_kind_from_context(reply)
    # 仅返回模板提示，让 Agent 主动渲染
    return f"\n<!-- Counterfactual hint: reply 含 {kind} 类内容，记得附加 `### Counterfactual` 块 -->\n"
```

#### 1.7.3 自检 Hook（P160-C）

```python
# extensions/counterfactual/hooks.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


COUNTERFACTUAL_BLOCK_PATTERN = re.compile(
    r"###\s*Counterfactual[\s\S]*?(?=\n### |\Z)",
    re.MULTILINE,
)

VERDICT_PATTERN = re.compile(
    r"\[(REINFORCED|WEAKENED|VERIFIED_PROTECTED|INFERRED_VULNERABLE|COST_AWARE|FAILURE_AWARE|ALTERNATIVES_PROVIDED)\]"
)


@dataclass
class CounterfactualCheckResult:
    """反事实块自检结果。"""
    has_block: bool                # 是否含 ### Counterfactual 块
    verdict: str | None            # 提取的 verdict 标注
    missing_reasons: list[str]     # 缺失项原因列表
    warnings: list[str]            # 用户可见警告

    @property
    def is_complete(self) -> bool:
        return self.has_block and self.verdict is not None


def self_check(reply: str) -> CounterfactualCheckResult:
    """扫描 reply 是否含反事实块 + verdict 标注。

    行为策略：
    - 缺失块 → warning，但不强制中断（避免破坏用户体验）
    - 含块但无 verdict → warning，提示需明确 verdict
    - 含块 + verdict → 通过
    """
    block_match = COUNTERFACTUAL_BLOCK_PATTERN.search(reply)
    has_block = block_match is not None

    if not has_block:
        return CounterfactualCheckResult(
            has_block=False,
            verdict=None,
            missing_reasons=["reply 中缺少 `### Counterfactual` 块"],
            warnings=[
                "⚠️ 反事实检查缺失：最终结论前未附加 `### Counterfactual` 块。"
                "建议列出 2 个最可能的反驳原因 + verdict 标注。"
            ],
        )

    block_text = block_match.group()
    verdict_match = VERDICT_PATTERN.search(block_text)
    verdict = verdict_match.group(1) if verdict_match else None

    warnings: list[str] = []
    if verdict is None:
        warnings.append(
            "⚠️ 反事实块缺 verdict 标注：需在块末尾标注 "
            "[REINFORCED] / [WEAKENED] / [VERIFIED_PROTECTED] / [INFERRED_VULNERABLE]"
        )

    return CounterfactualCheckResult(
        has_block=True,
        verdict=verdict,
        missing_reasons=[] if verdict else ["缺 verdict 标注"],
        warnings=warnings,
    )


def install_counterfactual_hooks(hook_registry: Any) -> None:
    """向 F-102 LoopHook 注册 post_reply_hook 自检。"""
    from extensions.anti_hallucination.frontier_tracker import get_frontier

    @hook_registry.register("post_reply_hook")
    def _counterfactual_check(reply: str, **_kw: Any) -> dict:
        result = self_check(reply)
        if result.is_complete:
            # 通过：把 verdict 写入 Working Memory（与 F-158 协同）
            frontier = get_frontier()
            if result.verdict == "WEAKENED":
                frontier.boundary_rules.append(
                    f"反事实自检发现弱化信号（最近 reply）：{reply[:50]}..."
                )
            return {
                "counterfactual_passed": True,
                "verdict": result.verdict,
                "warnings": [],
            }

        # 不通过：返回警告，不强制中断
        return {
            "counterfactual_passed": False,
            "verdict": result.verdict,
            "warnings": result.warnings,
        }
```

#### 1.7.4 与 F-158 协同（P160-D）

```python
# extensions/counterfactual/bridge.py
"""F-160 与 F-158 抗幻觉基线 / F-130 Profile / F-163 对抗质疑器的协同桥。"""
from __future__ import annotations

from typing import Literal


VerdictLiteral = Literal[
    "REINFORCED", "WEAKENED",
    "VERIFIED_PROTECTED", "INFERRED_VULNERABLE",
    "COST_AWARE", "FAILURE_AWARE", "ALTERNATIVES_PROVIDED",
]


def should_downgrade_to_inferred(verdict: str | None) -> bool:
    """反事实 verdict → 是否触发 F-158-A INFERRED 降级。

    规则：
    - WEAKENED → True（结论被弱化，对应 fact 应标记 INFERRED）
    - INFERRED_VULNERABLE → True（推断本身易被反驳）
    - 其他 → False（保持原 VERIFIED / INFERRED 标记）
    """
    return verdict in ("WEAKENED", "INFERRED_VULNERABLE")


def profile_hint(verdict: str | None) -> str | None:
    """反事实 verdict → F-130 Profile 切换建议。

    规则：
    - WEAKENED + 多次出现 → 建议切换到 debug Profile
    - 持续 REINFORCED → 当前 Profile OK，无需切换
    """
    if verdict == "WEAKENED":
        return "debug"  # 建议但不强切
    return None
```

#### 1.7.5 输出风格约束（CLAUDE.md 片段）

```python
# extensions/counterfactual/output_style.py
"""F-160 在 CLAUDE.md / 输出风格约束中追加的反事实行为指南。"""

OUTPUT_STYLE_FRAGMENT = """
## Counterfactual Reasoning（反事实推理）

每个最终结论前必须附加 `### Counterfactual` 块，包含：

1. **最可能让此结论错的 2 个原因**（具体到可验证事实层面）
2. **什么证据会反驳此结论**
3. **如果反驳证据存在，应如何修正**

块末尾必须标注一个 verdict：
- `[REINFORCED]` — 反驳证据不存在，结论被强化
- `[WEAKENED]` — 反驳证据可能存在，弱化结论措辞
- `[VERIFIED_PROTECTED]` — 已被 F-158 VERIFIED，无需弱化
- `[INFERRED_VULNERABLE]` — 推断本身易被反驳

仅对关键决策 / 断言 / 推荐强制要求；对中间推理步骤不强求。
"""

CLAUDE_MD_FRAGMENT = """
## 抗过度自信（F-160 启用时追加）

1. 每个最终结论前必须附加反事实检查块
2. 反事实检查不是套话，必须列出具体的反驳证据
3. 与 F-158 抗幻觉协同：反事实发现的反驳证据触发 INFERRED 降级
4. 用户可临时关闭：query 中含 `/no_counterfactual` 前缀绕过
"""
```

### 1.8 核心流程

```
[Agent 即将生成 "采用 X 方案" 的最终结论]
  ↓
[F-160 P160-B 已通过 F-119 注入 counterfactual_guide section 到 system prompt 末段]
  ↓
[Agent 看到指南 → 在生成决策时主动附加反事实检查]
  ↓
reply = """
## 决策
采用 X 方案。

### Counterfactual
1. 最可能错：X 与现有架构 Y 冲突（依据：Y 的接口签名与 X 不兼容）
2. 最可能错：X 在高并发下性能不足（依据：X 是单线程实现）
3. 反例检索建议：Grep("Y", scope="project") 检查现有架构

[REINFORCED] — 当前未见反驳证据
"""
  ↓
P160-C self_check(reply)
  → has_block=True, verdict="REINFORCED"
  → 通过（无 warning）
  ↓
[可选] P160-D bridge.should_downgrade_to_inferred("REINFORCED") → False
  → 不触发 F-158 INFERRED 降级
  ↓
[reply 正常输出给用户]
```

### 1.9 与现有架构的对齐

| 维度 | 现状 | F-160 落地后 |
|------|------|-------------|
| 过度自信 | ❌ 模型直接给结论 | ✅ 反事实块强制列出反驳证据 |
| 反驳证据可追溯 | ❌ 无 | ✅ 反事实块作为可审计工件 |
| verdict 标注 | ❌ 无 | ✅ 6 档 verdict（REINFORCED / WEAKENED / ...） |
| 与 F-119 协同 | — | ✅ register_section 注入指南 |
| 与 F-102 协同 | — | ✅ post_reply_hook 自检 |
| 与 F-158 协同 | — | ✅ INFERRED 降级触发 |
| 与 F-130 协同 | — | ✅ verdict 可作 Profile 切换建议 |
| 与 F-163 协同 | — | ✅ F-163 Critic prompt 可引用 F-160 模板 |
| 解耦合规 | — | ✅ 零 `src/` 改动 |
| Token 开销 | — | 🟢 极低（仅 prompt 注入 + 1 个 Hook） |

### 1.10 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 模型机械写反事实但不真信 | 沦为套话 | verdict 标注强制（REINFORCED / WEAKENED 区分真伪）；F-158 抽查 |
| 反事实块过度膨胀 | 输出变长 | 仅对最终结论要求；中间推理不强求 |
| 用户明确要"凭印象答" | 强制反事实破坏体验 | CLI 开关 `counterfactual.strict=false`；query 中 `/no_counterfactual` 前缀绕过 |
| verdict 标注不一致 | 解析失败 | 严格正则匹配 6 档标注；扩展时同步更新 VERDICT_PATTERN |
| 与 F-163 重复 | 双倍成本 | F-160 是 prompt baseline；F-163 是独立 sub-agent 纵深；F-163 Critic 可直接引用 F-160 模板避免重写 |
| 中间推理步骤被误判 | 频繁触发 warning | self_check 仅针对最终结论（含 "决策 / 断言 / 推荐" 关键词的 reply） |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|----------|
| 2026-07-22 | 初始创建 | 本文档 | 与 F-130 / F-158 / F-159 格式对齐；映射到 DC-A §4.4 F-160 |

### 2.2 待验证项

- P160-A 3 类模板（decision / assertion / recommendation）格式化正确，关键占位符无遗漏
- P160-A `select_kind_from_context` 对中英文决策 / 断言 / 推荐关键词正确分类
- P160-B `register_counterfactual_section` 通过 F-119 注册的 section 可在 `dump_effective_system_prompt` 中看到
- P160-C `self_check` 正确识别反事实块（has_block=True）
- P160-C `self_check` 正确提取 verdict（6 档标注）
- P160-C 缺失 verdict 时返回 warning，不强制中断
- P160-D `should_downgrade_to_inferred("WEAKENED")` 返回 True
- P160-D `should_downgrade_to_inferred("REINFORCED")` 返回 False
- P160-D `profile_hint("WEAKENED")` 返回 "debug"
- 端到端：模板注入 → Agent 输出 → Hook 检测 → INFERRED 降级
- 稳定性门禁全量（Stage 1-5 + 7-9）通过
- Orchestrator 单元测试（排除 `manual_e2e_f38.py`）通过

---

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `DECISION_TEMPLATE` / `ASSERTION_TEMPLATE` / `RECOMMENDATION_TEMPLATE` 3 类模板完整，含占位符 | 📋 |
| 2 | `render_template("decision", decision="...")` 正确替换占位符 | 📋 |
| 3 | `render_template("assertion", assertion="...")` 正确替换 | 📋 |
| 4 | `render_template("recommendation", recommendation="...")` 正确替换 | 📋 |
| 5 | `select_kind_from_context` 对中英文决策 / 断言 / 推荐关键词正确分类 3 种 TemplateKind | 📋 |
| 6 | `register_counterfactual_section` 通过 F-119 `register_section` 注册，section_id="counterfactual_guide" | 📋 |
| 7 | `COUNTERFACTUAL_GUIDE_SECTION` 含核心原则 + 何时使用 + 强制行为 + 模板示例 | 📋 |
| 8 | `self_check` 正确识别反事实块（正则匹配 `### Counterfactual`） | 📋 |
| 9 | `self_check` 正确提取 verdict（6 档标注） | 📋 |
| 10 | `self_check` 缺失块时返回 warning，不强制中断 | 📋 |
| 11 | `should_downgrade_to_inferred("WEAKENED")` 返回 True | 📋 |
| 12 | `should_downgrade_to_inferred("INFERRED_VULNERABLE")` 返回 True | 📋 |
| 13 | `should_downgrade_to_inferred("REINFORCED")` 返回 False | 📋 |
| 14 | `profile_hint("WEAKENED")` 返回 "debug" | 📋 |
| 15 | `OUTPUT_STYLE_FRAGMENT` / `CLAUDE_MD_FRAGMENT` 文档化输出风格约束 | 📋 |
| 16 | 4 子特性在 `import extensions.counterfactual` 时自动注册 | 📋 |
| 17 | `install_counterfactual_hooks` 向 F-102 hook_registry 注册 `post_reply_hook` | 📋 |
| 18 | 稳定性门禁 + 反事实 E2E 测试通过 | 📋 |

### 3.2 落地路径（推荐顺序）

1. **P160-A 先行** — 3 类 prompt 模板 + 渲染函数 + 启发式选择 kind（纯函数 + 字符串模板，立即可测）
2. **P160-B 紧随** — 通过 F-119 `register_section` 注入指南（依赖 P160-A 的模板）
3. **P160-C 收尾** — 自检 Hook + verdict 正则匹配
4. **P160-D 远期** — 与 F-158 / F-130 / F-163 的协同桥（依赖 Wave 1 其他 F-N 落地）

### 3.3 与 F-119 / F-158 / F-130 / F-163 的协同点

- **F-119 `register_section`** → P160-B 把 `counterfactual_guide` 注入到 system prompt 末段（order=80）
- **F-119 `dump_effective_system_prompt`** → 验证 `counterfactual_guide` 已注入
- **F-102 Hook `post_reply_hook`** → P160-C `self_check` 检测反事实块
- **F-158-A INFERRED 降级** → P160-D `should_downgrade_to_inferred("WEAKENED")` 触发
- **F-130 Profile 切换** → P160-D `profile_hint("WEAKENED")` 建议切到 debug
- **F-163 Critic prompt** → Wave 2 落地时，F-163 Critic 可直接引用 F-160 模板，避免重写

### 3.4 轻量级特性说明

F-160 是 Wave 1 中**门槛最低（🟢）**的 F-N：
- 主体是 prompt 模板（不涉及新算法）
- 1 个 Hook（self_check 正则匹配）
- 1 个 Section 注入（10 行代码）
- Token 开销极低（仅 system prompt 末段 ~200 tokens + 每次 reply 检测 <1ms）

适合作为 Wave 1 的"暖场"特性 — 实施成本极低但能立即看到效果。

---

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-22 | 初始创建 | DC-A §4.4 映射表基础上落地 F-160 反事实推理；覆盖 DC-012；Wave 1 门槛最低（仅 prompt + 1 Hook）；与 F-119 / F-102 / F-158-A / F-130 / F-163 协同；解耦落地于 `extensions/counterfactual/`，零 `src/` 侵入 |