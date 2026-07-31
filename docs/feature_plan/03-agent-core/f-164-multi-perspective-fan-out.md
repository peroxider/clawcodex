# F-164: 多视角扇出 — N 个独立视角并行推理 + 综合

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-164-multi-perspective-fan-out.md`
> 最后更新: 2026-07-22
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-010

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 2 P1 工具化组（中等门槛，~2-3 月可落地） |
| 覆盖 DC | DC-010 多视角扇出 (Multi-Perspective Fan-Out) |
| 前置依赖 | F-118 子 agent 编排 + F-119 Section Registry + F-102 Hook 扩展点 + F-130 Profile |
| 协同 | F-163 对抗质疑器（同期 Wave 2，纵深互补）、F-118 sub-agent、F-130 风险分级触发 |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/multi_perspective/`，零 `src/` 侵入 |
| 落地形态 | 5 个默认 Perspective Persona + 并行扇出 + Synthesizer 综合 + 风险分级触发 |

---

## §1 设计规划

### 1.1 背景

F-158 / F-162 已提供"事实层"防御（标注 + 拦截），F-163 引入"单方案纵深对抗"。但**只解决"一个方案好不好"，未解决"是否有更好的替代方案"**。

**问题**：单链 CoT（Chain-of-Thought）存在**窄化偏差**——一旦 LLM 锁定初始思路，后续推理会围绕该思路自圆其说，缺乏对**替代方案**的探索：

- 选了 FastAPI 后，所有论据都倾向"FastAPI 更快"
- 决定重构后，所有论据都倾向"重构更清洁"
- 选了 SQLite 后，所有论据都倾向"轻量级够用"

这种偏差在工程决策中尤其危险——**关键决策若缺乏多视角对照，容易陷入"局部最优 + 自信过度"的陷阱**。

**F-164 的定位**：让 N 个不同"视角 / persona"的 sub-agent **独立并行推理**，每个视角给结论 + 论据；Synthesizer 综合：共识 → 高置信，分歧 → 标需人类决策。让用户看到"该决策在不同视角下分别如何"。

### 1.2 目标

- 让"多视角对照"成为关键决策的**默认流程**而非"用户主动要求"
- 让 Synthesizer 输出 **consensus（共识）+ conflicts（分歧）+ human-judgment tags**，可被下游消费
- 让 Perspective Persona 可**动态注册扩展**（用户 / 项目可注入领域专家视角）
- 与 F-163 形成**纵深+横向**互补：F-163 打磨单方案，F-164 探索替代方案
- 风险分级触发：低风险任务默认不启用（成本太高），关键决策启用

### 1.3 非目标 (Out of Scope)

- 不替代 F-163 对抗质疑器（DC-008）—— F-164 是 N 选 1 横向，F-163 是 1v1 纵深
- 不替代 F-130 Profile 的模式切换（Profile 切的是"上下文视角"，F-164 切的是"决策视角"）
- 不立即支持视角间"互相看到对方结论"——保持独立性是核心特性（避免确认偏差）
- 不替代用户最终决策权 —— F-164 提供素材，决策在人
- 不立即做"视角权重学习"（基于历史决策反哺权重）—— 留 Wave 3 / F-168 假设并行情景的延伸

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖 DC | 状态 | 工时 |
|:----:|--------|:-------:|:----:|:----:|
| P164-A | Perspective Persona 库（5 个默认视角） | DC-010 核心 | 📋 | 2-3d |
| P164-B | 并行扇出（asyncio.gather） | DC-010 核心 | 📋 | 2-3d |
| P164-C | Synthesizer 综合（consensus + conflicts + human tags） | DC-010 输出 | 📋 | 3-4d |
| P164-D | 风险分级触发（与 F-130 Profile 协同） | DC-010 部署 | 📋 | 1-2d |
| P164-E | 视角动态注册 Protocol | DC-010 扩展 | 📋 | 1-2d |
| P164-F | 视角审计 + 决策追溯 NDJSON | DC-010 运营 | 📋 | 1d（远期） |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-118 子 agent 编排 | **强协同（前置）** | 每个 Perspective 通过 F-118 SubAgent 实例化；并行调用走 `asyncio.gather(sub_agent.run(...))` |
| F-119 Section Registry | **强协同** | P164-A 通过 `register_section` 注入 `multi_perspective_guide` section，让 Synthesizer 在 system prompt 看到综合策略 |
| F-102 Hook Extensions | **强协同** | P164-B 在 `pre_reply_hook` 链注册 `multi_perspective.fan_out`（位于 F-163 之后） |
| F-130 Profile | **协同** | P164-D 触发策略可作 Profile 配置项（`high-risk` / `decision-making` Profile 默认启用，`default` Profile 默认关闭） |
| F-163 对抗质疑器（同期 Wave 2） | **互补** | F-164 是 N 选 1 横向；F-163 是 1v1 纵深；两者**不共享触发路径**，可同时启用 |
| F-162 工具强制验证（Wave 2） | **下游消费者** | F-164 各 Perspective 的"事实声明"可走 F-162 拦截；F-162 audit log 可作为"哪个视角忽视了关键事实"的反证 |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/multi_perspective/__init__.py` | — | 子系统入口；注册 perspectives / synthesizer / trigger |
| `extensions/multi_perspective/perspectives.py` | P164-A | 5 个默认 Perspective Persona：`SeniorEngineer` / `SecurityReviewer` / `Newcomer` / `PerfOptimizer` / `Maintainer` + `PERSPECTIVE_PROMPT_TEMPLATE` |
| `extensions/multi_perspective/fan_out.py` | P164-B | `parallel_perspective_run(question, perspectives, sub_agents)` 异步并行扇出（asyncio.gather） |
| `extensions/multi_perspective/synthesizer.py` | P164-C | `SynthesizerPersona` + `synthesize(perspective_results) -> MultiPerspectiveDecision` 综合策略（consensus + conflicts + human tags） |
| `extensions/multi_perspective/structured.py` | P164-C | `PerspectiveResult` dataclass（conclusion / reasoning / confidence / dissenting_points）+ `MultiPerspectiveDecision`（consensus / conflicts / requires_human / confidence） |
| `extensions/multi_perspective/trigger.py` | P164-D | `should_run_perspectives(context) -> bool` 风险分级触发；5 Profile 映射 + 关键词匹配 |
| `extensions/multi_perspective/registry.py` | P164-E | `PerspectiveRegistry` Protocol + `register_perspective` / `unregister_perspective` / `list_perspectives` |
| `extensions/multi_perspective/audit.py` | P164-F | NDJSON 视角推理记录；与 F-162 / F-163 audit log schema 兼容 |
| `extensions/multi_perspective/capabilities.py` | — | Protocol 接口契约（`Perspective` / `FanOutController` / `Synthesizer` / `Registry`） |
| `extensions/multi_perspective/hooks.py` | 全部 | 在 F-102 LoopHook 注册 `multi_perspective.fan_out`（拦截 + 编排） |
| `tests/multi_perspective/test_perspectives.py` | P164-A | 5 个默认 Perspective prompt 注入测试 |
| `tests/multi_perspective/test_fan_out.py` | P164-B | asyncio.gather 并行执行 + 部分失败处理 |
| `tests/multi_perspective/test_synthesizer.py` | P164-C | consensus 提取 + conflicts 识别 + human tags |
| `tests/multi_perspective/test_trigger.py` | P164-D | 5 Profile 触发策略 + 风险等级 |
| `tests/multi_perspective/test_registry.py` | P164-E | 动态注册 / 反注册 / 列表查询 |
| `tests/multi_perspective/test_e2e.py` | 全部 | 端到端：question → 5 Perspective 并行 → Synthesizer 综合 → Decision |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_multi_perspective_extensions()` 在 import 时注册 perspectives / fan_out / synthesizer |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | 在 `pre_reply_hook` 链追加 `multi_perspective.fan_out`（位于 F-163 之后） |
| `extensions/sub_agent/` （F-118） | 不修改；F-164 通过 F-118 public API 调用 |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.multi_perspective` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-164 |
| `docs/feature_plan/dynamic-context-index.md` | DC→F 映射、依赖与全局验收总则 |

### 1.7 核心 API 设计

#### 1.7.1 Perspective Persona 库（P164-A）

```python
# extensions/multi_perspective/perspectives.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


# 通用 Perspective prompt 模板
PERSPECTIVE_PROMPT_TEMPLATE = """你是 {persona_name}。

背景设定：
{persona_background}

任务：对以下问题/决策给出**独立**结论与论据。
重要约束：
1. 你看不到其他视角的结论（避免确认偏差）
2. 你的结论必须可独立证伪
3. 你的论据必须可追溯到具体经验/文档/案例

问题/决策：
{question}

输出要求（严格 JSON，不要任何 markdown 包装）：
{{
  "conclusion": "<你的独立结论，1-3 句话>",
  "reasoning": "<论据，引用具体经验/文档/案例>",
  "confidence": <float 0.0~1.0>,
  "dissenting_points": ["<你认为其他视角可能反对的点>", ...],
  "evidence_refs": ["<引用：文档路径/案例/经验>", ...]
}}
"""


@dataclass
class Perspective:
    """单个视角的完整定义。"""
    id: str                              # 唯一标识（如 "senior-engineer"）
    name: str                            # 显示名（如 "资深工程师"）
    persona_name: str                    # 注入 prompt 的 persona（如 "20 年经验的后端架构师"）
    persona_background: str              # persona 背景描述（关注维度 / 偏好 / 经验）
    system_prompt: str = ""              # 可选：额外的 system prompt 片段
    temperature: float = 0.7
    tags: tuple[str, ...] = ()           # 分类标签（"engineering" / "security" / "perf" / "maintainability"）


# ==== 5 个默认 Perspective ====

DEFAULT_PERSPECTIVES: list[Perspective] = [
    Perspective(
        id="senior-engineer",
        name="资深工程师",
        persona_name="20 年经验的后端架构师，深度参与过 50+ 项目的技术选型与重构",
        persona_background=(
            "你关注：长期可维护性 > 短期开发速度；架构清晰度 > 黑科技；显式依赖 > 隐式约定；"
            "对'技术债务'有极强的敏感度；对'时髦框架'持谨慎态度。"
        ),
        tags=("engineering", "maintainability"),
    ),
    Perspective(
        id="security-reviewer",
        name="安全审查员",
        persona_name="应用安全专家，熟悉 OWASP Top 10、CWE、依赖漏洞、注入攻击",
        persona_background=(
            "你关注：输入校验 > 业务逻辑；最小权限 > 便利；加密默认值 > 性能；"
            "对'信任内部网络'假设持怀疑态度；对日志中的敏感信息敏感。"
        ),
        tags=("security",),
    ),
    Perspective(
        id="newcomer",
        name="新人开发者",
        persona_name="刚加入团队 1 个月的全栈开发者，对项目历史一无所知",
        persona_background=(
            "你关注：上手成本 > 功能完整；文档完整 > 代码注释；约定一致 > 巧妙简化；"
            "对'项目特定黑话'感到困惑；对'需要问同事才能理解的代码'持负面态度。"
        ),
        tags=("ux", "maintainability"),
    ),
    Perspective(
        id="perf-optimizer",
        name="性能优化师",
        persona_name="性能工程师，痴迷于延迟、吞吐、内存占用、CPU profile",
        persona_background=(
            "你关注：P99 延迟 > 平均延迟；吞吐 > 单请求成本；冷启动 > 热路径优化；"
            "对'sync 阻塞调用'敏感；对'N+1 查询'零容忍。"
        ),
        tags=("performance",),
    ),
    Perspective(
        id="maintainer",
        name="长期维护者",
        persona_name="负责该系统 3 年以上的 on-call 工程师，处理过各种生产事故",
        persona_background=(
            "你关注：可观测性 > 业务正确性；故障转移 > 高可用；可回滚 > 一次到位；"
            "对'未测试的迁移路径'持负面态度；对'凌晨 3 点的告警'极度敏感。"
        ),
        tags=("reliability", "observability"),
    ),
]


def get_default_perspectives() -> list[Perspective]:
    """获取 5 个默认 Perspective（深拷贝防共享修改）。"""
    import copy
    return copy.deepcopy(DEFAULT_PERSPECTIVES)
```

#### 1.7.2 并行扇出（P164-B）

```python
# extensions/multi_perspective/fan_out.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from extensions.multi_perspective.perspectives import Perspective, PERSPECTIVE_PROMPT_TEMPLATE
from extensions.multi_perspective.structured import PerspectiveResult


@dataclass
class FanOutConfig:
    """扇出配置。"""
    timeout_ms: int = 30000                  # 单 Perspective 超时
    max_concurrency: int = 5                 # 最大并发（5 个默认 Perspective 不超限）
    fail_on_any_error: bool = False          # 任一 Perspective 失败 → 整体失败？默认 False（容忍部分失败）
    min_successful: int = 3                  # 至少 N 个成功才输出 Decision（少于则标 requires_human）


async def parallel_perspective_run(
    question: str,
    perspectives: list[Perspective],
    *,
    sub_agents: dict[str, Any],              # F-118 SubAgent 实例池（key=persona_name）
) -> list[PerspectiveResult]:
    """异步并行调用 N 个 Perspective sub-agent。

    Args:
        question: 待决策的问题
        perspectives: 视角列表（默认 5 个）
        sub_agents: F-118 SubAgent 实例池（每个 persona 对应一个 sub-agent）

    Returns:
        list[PerspectiveResult] — 与 perspectives 同序
    """
    semaphore = asyncio.Semaphore(FanOutConfig.max_concurrency)

    async def run_one(p: Perspective) -> PerspectiveResult:
        async with semaphore:
            prompt = PERSPECTIVE_PROMPT_TEMPLATE.format(
                persona_name=p.persona_name,
                persona_background=p.persona_background,
                question=question,
            )
            try:
                raw = await asyncio.wait_for(
                    sub_agent_run(sub_agents, p, prompt),
                    timeout=FanOutConfig.timeout_ms / 1000,
                )
                return _parse_perspective_result(raw, p)
            except asyncio.TimeoutError:
                return PerspectiveResult(
                    perspective_id=p.id,
                    conclusion="",
                    reasoning="",
                    confidence=0.0,
                    dissenting_points=[],
                    evidence_refs=[],
                    error=f"timeout after {FanOutConfig.timeout_ms}ms",
                )
            except Exception as e:
                return PerspectiveResult(
                    perspective_id=p.id,
                    conclusion="",
                    reasoning="",
                    confidence=0.0,
                    dissenting_points=[],
                    evidence_refs=[],
                    error=f"sub-agent error: {e}",
                )

    tasks = [run_one(p) for p in perspectives]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return results


async def sub_agent_run(
    sub_agents: dict[str, Any],
    perspective: Perspective,
    prompt: str,
) -> str:
    """调用 F-118 SubAgent（F-118 forward reference：API 待对齐）。

    注：F-118 当前为规划阶段，此处 API 契约由 F-164 自行约定：
    - 接受 sub_agents 字典，key 为 persona_name
    - 返回 str（sub-agent 的原始输出）

    F-164 vs F-163 签名差异（待 F-118 落地时统一）：
    - F-164：agent pool 按 persona_name 索引，调用 `agent.run(prompt, temperature=...)`，persona 嵌入 pool key
    - F-163：单 agent 实例，调用 `sub_agent.run(prompt, persona=..., temperature=...)`，persona 作为 kwarg
    - 两种模式 F-118 需同时支持，或在 F-118 落地时选定其一作为 canonical
    """
    agent = sub_agents.get(perspective.persona_name)
    if agent is None:
        raise ValueError(f"sub-agent not found for persona: {perspective.persona_name}")
    # F-118 实际 API 待落地时对齐（参见 F-163 §1.5 forward reference 说明）
    return await agent.run(prompt, temperature=perspective.temperature)


def _parse_perspective_result(raw: str, p: Perspective) -> PerspectiveResult:
    """解析 Perspective JSON 输出。"""
    import json
    import re
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    data = json.loads(text)
    return PerspectiveResult(
        perspective_id=p.id,
        conclusion=data["conclusion"],
        reasoning=data["reasoning"],
        confidence=float(data["confidence"]),
        dissenting_points=data.get("dissenting_points", []),
        evidence_refs=data.get("evidence_refs", []),
        error="",
    )
```

#### 1.7.3 结构化输出（P164-C 数据契约）

```python
# extensions/multi_perspective/structured.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal


@dataclass
class PerspectiveResult:
    """单个视角的输出。"""
    perspective_id: str
    conclusion: str
    reasoning: str
    confidence: float
    dissenting_points: list[str]
    evidence_refs: list[str]
    error: str = ""                         # 非空表示该 Perspective 失败


@dataclass
class ConsensusPoint:
    """共识点（多个视角结论相近）。"""
    topic: str                              # 共识主题
    supporting_perspective_ids: list[str]   # 支持该共识的视角
    synthesis: str                          # 综合表述
    confidence: float                       # 平均置信度


@dataclass
class ConflictPoint:
    """分歧点（多个视角结论不一致）。"""
    topic: str
    positions: dict[str, str]               # perspective_id → 该视角的结论
    severity: Literal["low", "medium", "high"]
    requires_human: bool = True


@dataclass
class MultiPerspectiveDecision:
    """多视角综合决策。"""
    question: str
    perspective_results: list[PerspectiveResult]
    consensus: list[ConsensusPoint]
    conflicts: list[ConflictPoint]
    requires_human: bool
    overall_confidence: float               # 共识强度（共识数 / 总视角数）

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "perspective_results": [asdict(r) for r in self.perspective_results],
            "consensus": [asdict(c) for c in self.consensus],
            "conflicts": [asdict(c) for c in self.conflicts],
            "requires_human": self.requires_human,
            "overall_confidence": self.overall_confidence,
        }
```

#### 1.7.4 Synthesizer 综合（P164-C 算法）

```python
# extensions/multi_perspective/synthesizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from extensions.multi_perspective.structured import (
        PerspectiveResult, MultiPerspectiveDecision,
    )


SYNTHESIZER_PROMPT_TEMPLATE = """你是 Synthesizer（多视角综合员）。

各视角对问题"{question}"的独立结论如下：
{results_text}

任务：
1. 提取**共识**（多数视角结论相近的主题） → 标高置信
2. 提取**分歧**（结论不一致的主题） → 标需人类决策
3. 综合整体置信度（共识强度）

输出要求（严格 JSON）：
{{
  "consensus": [
    {{
      "topic": "<共识主题>",
      "supporting_perspective_ids": ["<视角id>", ...],
      "synthesis": "<综合表述>",
      "confidence": <float 0.0~1.0>
    }},
    ...
  ],
  "conflicts": [
    {{
      "topic": "<分歧主题>",
      "positions": {{"<perspective_id>": "<该视角的结论>", ...}},
      "severity": "low" | "medium" | "high"
    }},
    ...
  ],
  "requires_human": <bool>,
  "overall_confidence": <float 0.0~1.0>
}}
"""


@dataclass
class SynthesizerPersona:
    name: str = "synthesizer"
    temperature: float = 0.3                # 低温度保证综合稳定


class Synthesizer:
    def __init__(self, persona: SynthesizerPersona, *, sub_agent: object):
        self.persona = persona
        self.sub_agent = sub_agent

    async def synthesize(
        self,
        question: str,
        perspective_results: list["PerspectiveResult"],
    ) -> "MultiPerspectiveDecision":
        # 1. 启发式：先本地提取共识 / 分歧（轻量级，避免每次都调 LLM）
        heuristic_decision = _heuristic_synthesize(question, perspective_results)

        # 2. LLM 综合（仅在 heuristic 标 requires_human=True 或高分歧时调用）
        if heuristic_decision.requires_human or any(
            c.severity == "high" for c in heuristic_decision.conflicts
        ):
            results_text = _format_results_for_llm(perspective_results)
            prompt = SYNTHESIZER_PROMPT_TEMPLATE.format(
                question=question,
                results_text=results_text,
            )
            raw = await self.sub_agent.run(
                prompt,
                persona=self.persona.name,
                temperature=self.persona.temperature,
            )
            llm_decision = _parse_synthesizer_output(raw, perspective_results, question)
            return llm_decision

        return heuristic_decision


def _heuristic_synthesize(
    question: str,
    results: list["PerspectiveResult"],
) -> "MultiPerspectiveDecision":
    """启发式综合：基于结论相似度提取共识/分歧（无需 LLM 调用）。"""
    from extensions.multi_perspective.structured import (
        MultiPerspectiveDecision, ConsensusPoint, ConflictPoint,
    )

    successful = [r for r in results if not r.error]
    if not successful:
        return MultiPerspectiveDecision(
            question=question,
            perspective_results=results,
            consensus=[],
            conflicts=[],
            requires_human=True,
            overall_confidence=0.0,
        )

    # 简化启发式：所有 successful 视角结论相似 → 标共识
    # 实际实现可用 sentence embedding 余弦相似度聚类
    consensus_topics = _cluster_consensus(successful)
    conflict_topics = _find_conflicts(successful)

    return MultiPerspectiveDecision(
        question=question,
        perspective_results=results,
        consensus=consensus_topics,
        conflicts=conflict_topics,
        requires_human=len(conflict_topics) > 0,
        overall_confidence=len(successful) / len(results),
    )


def _cluster_consensus(results: list["PerspectiveResult"]) -> list["ConsensusPoint"]:
    """聚类提取共识（简化实现：相同 perspective_id 标签 → 共识候选）。"""
    # 完整实现需 sentence embedding；此处占位
    return [
        ConsensusPoint(
            topic="placeholder",
            supporting_perspective_ids=[r.perspective_id for r in results],
            synthesis=" / ".join(r.conclusion for r in results if r.conclusion),
            confidence=sum(r.confidence for r in results) / len(results),
        )
    ]


def _find_conflicts(results: list["PerspectiveResult"]) -> list["ConflictPoint"]:
    """检测冲突（基于 dissenting_points 字段）。"""
    all_dissents = [d for r in results for d in r.dissenting_points]
    if not all_dissents:
        return []
    # 简化：每个 dissenting_point 视为一个 conflict
    return [
        ConflictPoint(
            topic=d[:50],
            positions={"auto-detected": d},
            severity="medium",
            requires_human=True,
        )
        for d in all_dissents[:5]   # 最多 5 条
    ]


def _format_results_for_llm(results: list["PerspectiveResult"]) -> str:
    """格式化 Perspective 结果供 LLM 综合。"""
    lines = []
    for r in results:
        lines.append(
            f"[{r.perspective_id}] confidence={r.confidence:.2f}\n"
            f"  结论: {r.conclusion}\n"
            f"  论据: {r.reasoning}\n"
            f"  反对点: {'; '.join(r.dissenting_points) or '（无）'}\n"
            + (f"  ⚠️ 错误: {r.error}\n" if r.error else "")
        )
    return "\n".join(lines)


def _parse_synthesizer_output(
    raw: str,
    results: list["PerspectiveResult"],
    question: str,
) -> "MultiPerspectiveDecision":
    """解析 Synthesizer JSON 输出。"""
    import json
    import re
    from extensions.multi_perspective.structured import (
        MultiPerspectiveDecision, ConsensusPoint, ConflictPoint,
    )
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    data = json.loads(text)
    return MultiPerspectiveDecision(
        question=question,
        perspective_results=results,
        consensus=[
            ConsensusPoint(
                topic=c["topic"],
                supporting_perspective_ids=c["supporting_perspective_ids"],
                synthesis=c["synthesis"],
                confidence=float(c["confidence"]),
            )
            for c in data.get("consensus", [])
        ],
        conflicts=[
            ConflictPoint(
                topic=c["topic"],
                positions=c["positions"],
                severity=c["severity"],
                requires_human=True,
            )
            for c in data.get("conflicts", [])
        ],
        requires_human=bool(data.get("requires_human", False)),
        overall_confidence=float(data.get("overall_confidence", 0.5)),
    )
```

#### 1.7.5 触发策略（P164-D）

```python
# extensions/multi_perspective/trigger.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    """任务风险等级（与 F-163 复用同一枚举）。"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PerspectiveTriggerPolicy:
    """F-164 触发策略。"""
    enabled: bool = False
    min_risk_level: RiskLevel = RiskLevel.HIGH
    default_perspectives: tuple[str, ...] = (
        "senior-engineer", "security-reviewer", "newcomer",
        "perf-optimizer", "maintainer",
    )
    require_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


# ==== 5 Profile 映射（F-130 协同） ====

PROFILE_TRIGGERS: dict[str, PerspectiveTriggerPolicy] = {
    "default": PerspectiveTriggerPolicy(
        enabled=False,                            # 默认 Profile 不启用
        min_risk_level=RiskLevel.HIGH,
    ),
    "review": PerspectiveTriggerPolicy(
        enabled=True,
        min_risk_level=RiskLevel.MEDIUM,
        require_keywords=("选型", "决策", "重构", "迁移", "design", "decision", "migration"),
    ),
    "strict": PerspectiveTriggerPolicy(
        enabled=True,
        min_risk_level=RiskLevel.LOW,             # strict 连低风险也启用
        require_keywords=(),
    ),
    "debug": PerspectiveTriggerPolicy(
        enabled=False,                            # debug 专注于快速修复
        min_risk_level=RiskLevel.CRITICAL,
    ),
    "creative": PerspectiveTriggerPolicy(
        enabled=False,                            # creative 鼓励发散，不强制多视角
        min_risk_level=RiskLevel.CRITICAL,
    ),
}


def should_run_perspectives(
    context: dict,
    *,
    profile_id: str | None = None,
) -> bool:
    """判定当前上下文是否应触发多视角扇出。

    Args:
        context: {"risk_level": str, "question": str, "intent": str}
        profile_id: 当前 F-130 Profile ID

    Returns:
        True = 启用多视角扇出
    """
    policy = PROFILE_TRIGGERS.get(profile_id or "default", PROFILE_TRIGGERS["default"])
    if not policy.enabled:
        return False

    risk = RiskLevel(context.get("risk_level", "low"))
    risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    if risk_order.index(risk) < risk_order.index(policy.min_risk_level):
        return False

    intent = context.get("intent", "").lower()
    if any(kw.lower() in intent for kw in policy.exclude_keywords):
        return False
    if policy.require_keywords and not any(kw.lower() in intent for kw in policy.require_keywords):
        return False

    return True
```

#### 1.7.6 视角动态注册 Protocol（P164-E）

```python
# extensions/multi_perspective/registry.py
from __future__ import annotations

from typing import Protocol
from extensions.multi_perspective.perspectives import Perspective


class PerspectiveRegistry(Protocol):
    """视角注册表 Protocol（可被替换实现）。"""

    def register(self, perspective: Perspective) -> None:
        """注册一个 Perspective（id 重复 → 抛 ValueError）。"""
        ...

    def unregister(self, perspective_id: str) -> None:
        """反注册一个 Perspective。"""
        ...

    def get(self, perspective_id: str) -> Perspective | None:
        """按 id 查询 Perspective。"""
        ...

    def list_all(self) -> list[Perspective]:
        """列出所有注册的 Perspective。"""
        ...

    def list_by_tag(self, tag: str) -> list[Perspective]:
        """按 tag 过滤 Perspective。"""
        ...


class InMemoryPerspectiveRegistry:
    """默认实现：内存字典存储。"""

    def __init__(self):
        self._store: dict[str, Perspective] = {}

    def register(self, perspective: Perspective) -> None:
        if perspective.id in self._store:
            raise ValueError(f"perspective id already registered: {perspective.id}")
        self._store[perspective.id] = perspective

    def unregister(self, perspective_id: str) -> None:
        self._store.pop(perspective_id, None)

    def get(self, perspective_id: str) -> Perspective | None:
        return self._store.get(perspective_id)

    def list_all(self) -> list[Perspective]:
        return list(self._store.values())

    def list_by_tag(self, tag: str) -> list[Perspective]:
        return [p for p in self._store.values() if tag in p.tags]


# 全局注册表实例
_default_registry = InMemoryPerspectiveRegistry()
for p in DEFAULT_PERSPECTIVES:                # 注册 5 个默认 Perspective
    _default_registry.register(p)


def get_default_registry() -> PerspectiveRegistry:
    """获取默认注册表（含 5 个默认 Perspective）。"""
    return _default_registry


def register_perspective(perspective: Perspective) -> None:
    """便捷 API：注册到默认注册表。"""
    _default_registry.register(perspective)
```

#### 1.7.7 Hook 集成

```python
# extensions/multi_perspective/hooks.py
from __future__ import annotations

import asyncio
from typing import Any

from extensions.multi_perspective.perspectives import get_default_perspectives
from extensions.multi_perspective.registry import get_default_registry
from extensions.multi_perspective.fan_out import parallel_perspective_run
from extensions.multi_perspective.synthesizer import Synthesizer
from extensions.multi_perspective.trigger import should_run_perspectives


async def multi_perspective_pre_reply_hook(
    question: str,
    history: list[dict],
    *,
    sub_agents: dict[str, Any],
    synthesizer_sub_agent: Any,
    profile_id: str | None = None,
    risk_level: str = "medium",
    audit_sink: Any | None = None,
) -> dict:
    """F-102 LoopHook 集成的多视角扇出入口。

    Returns:
        {
            "decision": "pass" | "intercept",
            "decision_payload": MultiPerspectiveDecision.to_dict(),
            "requires_human": bool,
        }
    """
    context = {"question": question, "risk_level": risk_level, "intent": history[-1].get("content", "") if history else ""}
    if not should_run_perspectives(context, profile_id=profile_id):
        return {"decision": "pass", "decision_payload": None, "requires_human": False}

    # 1. 取默认 5 个 Perspective（或用户注册的扩展）
    registry = get_default_registry()
    perspectives = registry.list_all()

    # 2. 并行扇出
    results = await parallel_perspective_run(question, perspectives, sub_agents=sub_agents)
    if audit_sink:
        for r in results:
            audit_sink.write(r)

    # 3. Synthesizer 综合
    synth = Synthesizer(sub_agent=synthesizer_sub_agent)
    decision = await synth.synthesize(question, results)

    return {
        "decision": "intercept" if decision.requires_human else "pass",
        "decision_payload": decision.to_dict(),
        "requires_human": decision.requires_human,
    }
```

### 1.8 核心流程

```
[用户提问 / 决策问题]
    ↓
[F-102 LoopHook.pre_reply 链]
    ├─→ [F-158 scan_for_unmarked_claims]              # 软警告（已有）
    ├─→ [F-162 pre_reply_interceptor]                  # 硬拦截（Wave 2 同波）
    ├─→ [F-163 red_team_critic_pre_reply_hook]         # 1v1 纵深（Wave 2 同波）
    ├─→ [F-164 multi_perspective_pre_reply_hook]       # N 选 1 横向（新增）
    │       ├─ should_run_perspectives(context, profile)?
    │       │   ├─ False → pass（保持原 reply）
    │       │   └─ True → 进入扇出
    │       │
    │       ├─ PerspectiveRegistry.list_all() → 5 个 Perspective
    │       ├─ parallel_perspective_run()  ← asyncio.gather
    │       │   ├─ SeniorEngineer.run(question) ─┐
    │       │   ├─ SecurityReviewer.run(question) │ 并行
    │       │   ├─ Newcomer.run(question) ────────┤
    │       │   ├─ PerfOptimizer.run(question) ───┤
    │       │   └─ Maintainer.run(question) ──────┘
    │       │       ↓ 5 × PerspectiveResult
    │       ├─ Synthesizer.synthesize(question, results)
    │       │   ├─ 启发式聚类（无需 LLM）
    │       │   ├─ 检测到高分歧或 requires_human → 调 LLM 综合
    │       │   └─ 输出 MultiPerspectiveDecision
    │       ↓
    │   decision:
    │       ├─ requires_human=False → pass（输出 consensus 摘要）
    │       └─ requires_human=True → intercept（UI 展示 consensus + conflicts）
    ↓
[Orchestrator 决策]:
    ├─ decision=pass → 输出 consensus 摘要（融合到 reply）
    └─ decision=intercept → 输出完整 Decision（consensus + conflicts）
```

### 1.9 与现有架构的对齐

| 对齐点 | 说明 |
|-------|------|
| F-118 子 agent 编排 | 5 个 Perspective 均通过 F-118 SubAgent 实例化；并行调用走 `asyncio.gather`；F-118 forward reference 同 F-163 |
| F-119 Section Registry | 通过 `register_section("multi_perspective_guide", ...)` 让 Synthesizer 在 system prompt 看到综合策略 |
| F-102 LoopHook | 在 `pre_reply_hook` 链追加 `multi_perspective.fan_out`；位于 F-158 / F-162 / F-163 之后 |
| F-130 Profile | PROFILE_TRIGGERS 5 Profile 映射：default(off)/review(on, medium)/strict(on, low)/debug(off)/creative(off) |
| F-163 对抗质疑器（同期 Wave 2） | F-164 是 N 选 1 横向；F-163 是 1v1 纵深；两者共用 F-118 sub-agent 但**不共享触发路径** |
| F-162 工具强制验证 | F-164 各 Perspective 的"事实声明"可走 F-162 拦截；F-162 audit log 作为"哪个视角忽视关键事实"的反证 |
| 解耦 | 全部落在 `extensions/multi_perspective/`；F-102 hook 注册在 `clawcodex_ext/hooks/_pluggy_adapter.py`；零 `src/` 侵入 |

### 1.10 风险与缓解

| 风险 | 描述 | 缓解 |
|------|------|------|
| **Token 与时延翻倍** | 5 个 Perspective 并行 = 5 次 LLM 调用 | P164-D 默认 `enabled=False`；仅 review/strict Profile 启用；`max_concurrency=5` 上限 |
| **视角同质化** | 5 个默认 Perspective 实际可能给出相似结论（LLM 共享底层偏见） | P164-A `temperature=0.7` 防模板化；P164-E 动态注册允许注入领域专家；长期：基于历史决策反哺权重（Wave 3 / F-168） |
| **确认偏差回归** | 视角间若能看到对方结论 → 失去独立性 | §1.7.1 prompt 模板显式约束"看不到其他视角结论"；F-118 fan_out 不共享中间结果 |
| **Synthesizer 误导** | LLM 综合可能引入新的偏差（"看起来公允"的综合未必正确） | P164-C 启发式 + LLM 二阶段（仅高分歧调 LLM）；`requires_human=True` 强制 UI 二次确认 |
| **部分失败容错** | 某个 Perspective sub-agent 失败 → 整体失败？ | P164-B `fail_on_any_error=False` + `min_successful=3` 容忍 ≤2 个失败 |
| **审计日志膨胀** | 5 视角 × 长 reasoning = 高频 NDJSON 写入 | P164-F NDJSON 追加 + 可配置 `audit_enabled=False`（debug Profile 默认关闭） |
| **与 F-163 双倍成本** | F-163（3 轮迭代）+ F-164（5 视角并行）= 18 次 LLM 调用 | Hook 链顺序：F-163 触发后才 F-164；F-163 已收敛的方案 → F-164 复用而非重新生成 |
| **动态注册风险** | 用户注册的低质量 Perspective 污染综合 | P164-E Protocol `register()` 校验（id 唯一 / 必填字段）；可加入 `quality_score` 字段（远期） |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 说明 |
|:----:|--------|------|
| 2026-07-22 | 初始文档创建 | DC-A §4.4 映射表基础上落地 F-164 多视角扇出；覆盖 DC-010；Wave 2 P1 第三个落地 F-N；与 F-163 形成"纵深 + 横向"互补；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-163 协同；解耦落地于 `extensions/multi_perspective/`，零 `src/` 侵入 |

### 2.2 待验证项

| 编号 | 验证项 | 关联子特性 |
|:----:|--------|:----------:|
| 1 | 5 个默认 Perspective（senior-engineer / security-reviewer / newcomer / perf-optimizer / maintainer）prompt 注入 + JSON 解析 | P164-A |
| 2 | `asyncio.gather` 真正并行（5 个 Perspective 同时启动） | P164-B |
| 3 | 部分失败容错：`fail_on_any_error=False` + `min_successful=3` | P164-B |
| 4 | 单 Perspective 超时：`timeout_ms=30000` | P164-B |
| 5 | 启发式综合：无需 LLM 即可提取共识 / 分歧 | P164-C |
| 6 | LLM 综合：仅在启发式标 requires_human=True 时调用 | P164-C |
| 7 | `MultiPerspectiveDecision.to_dict()` schema 稳定 | P164-C |
| 8 | `PROFILE_TRIGGERS` 5 Profile 触发策略 | P164-D |
| 9 | `should_run_perspectives` 关键词匹配（require / exclude） | P164-D |
| 10 | `PerspectiveRegistry.register` 拒绝重复 id | P164-E |
| 11 | `PerspectiveRegistry.list_by_tag` 过滤生效 | P164-E |
| 12 | 动态注册：用户注入新 Perspective 后 `list_all()` 立即可见 | P164-E |
| 13 | Hook 链顺序：F-158 → F-162 → F-163 → F-164 | 集成 |
| 14 | F-118 SubAgent 实例池注入（5 个 persona sub-agent） | 集成 |
| 15 | F-119 `register_section("multi_perspective_guide", ...)` 集成 | 集成 |
| 16 | F-163 收敛的方案 → F-164 复用而非重新生成 | 集成 |
| 17 | E2E：完整扇出 + 综合 + 审计日志 | 集成 |

---

## §3 实施细节

### 3.1 验收标准

**功能完整性**：
- [ ] 5 个默认 Perspective prompt 模板可注入并产出 JSON
- [ ] `parallel_perspective_run` 真正并行（asyncio.gather）
- [ ] 部分失败容忍：≤2 个 Perspective 失败仍能输出 Decision
- [ ] 启发式综合 + LLM 综合 二阶段策略生效
- [ ] `requires_human=True` 时强制 UI 二次确认
- [ ] `PerspectiveRegistry` 动态注册 / 反注册 / 列表查询生效
- [ ] NDJSON 审计日志写入

**质量门禁**：
- [ ] Stage 5 扩展测试 `extensions.multi_perspective` 模块导入通过
- [ ] `tests/multi_perspective/` 6 个测试用例全 PASS
- [ ] ruff check `extensions/multi_perspective/` 无 error
- [ ] 与 F-163 集成测试无回归（两特性可同时启用）

**运营可见性**：
- [ ] UI 层可展示 5 视角独立结论（卡片式布局）
- [ ] consensus / conflicts 区分展示（绿色 / 红色）
- [ ] `requires_human=True` 时阻塞性 UI 二次确认弹窗
- [ ] NDJSON 审计日志可被 `jq` 查询

### 3.2 落地路径（推荐顺序）

1. **P164-A 先行** — 5 个默认 Perspective 落地，先跑 prompt 注入测试
2. **P164-E 视角注册表** — `InMemoryPerspectiveRegistry` + Protocol（与 P164-A 解耦）
3. **P164-B 并行扇出** — `parallel_perspective_run` + asyncio.gather + 部分失败容错
4. **P164-C 数据契约** — `PerspectiveResult` / `MultiPerspectiveDecision` / `ConsensusPoint` / `ConflictPoint` dataclass
5. **P164-C 启发式综合** — `_heuristic_synthesize` 无需 LLM 的聚类
6. **P164-C LLM 综合** — `Synthesizer.synthesize` 二阶段（启发式 + LLM 兜底）
7. **P164-D 触发策略** — `PROFILE_TRIGGERS` + `should_run_perspectives`
8. **P164-F 审计** — NDJSON 写入 + 与 F-162 / F-163 audit schema 兼容
9. **集成到 F-102 LoopHook** — `multi_perspective_pre_reply_hook` 注册；F-118 sub-agent 池注入
10. **集成测试** — F-163 收敛 → F-164 复用；E2E 完整扇出

### 3.3 与 F-118 / F-119 / F-102 / F-162 / F-130 / F-163 的协同点

- **F-118 SubAgent** → 5 个 Perspective + 1 个 Synthesizer 通过 `sub_agents` 字典注入；F-118 forward reference 同 F-163（API 契约 F-164 自定）
- **F-119 `register_section`** → 注册 `multi_perspective_guide` section（`order=90`，F-163 之后），让 Synthesizer 在 system prompt 看到综合策略
- **F-119 `dump_effective_system_prompt`** → 验证 `multi_perspective_guide` section 已注入到 Synthesizer 的 system prompt
- **F-102 LoopHook** → P164-B 在 `pre_reply_hook` 链注册 `multi_perspective.fan_out`；位于 F-158 / F-162 / F-163 之后
- **F-162 audit log** → F-164 各 Perspective 的 `evidence_refs` 字段可引用 F-162 NDJSON；audit schema 兼容
- **F-130 Profile** → `PROFILE_TRIGGERS` 5 Profile 映射：default(off)/review(on, medium)/strict(on, low)/debug(off)/creative(off)；切换 Profile 时 trigger 自动重读
- **F-163 对抗质疑器（同期 Wave 2）** → F-163 收敛的 final_proposal 可作为 F-164 各 Perspective 的输入"原始方案"（避免重复生成）

### 3.4 与 F-163 (对抗) 的边界

F-164 与 F-163 **不重复**，定位互补：

| 维度 | F-163 对抗 | F-164 多视角 |
|------|----------|-------------|
| 形态 | 1v1 纵深 | N 选 1 横向 |
| 角色 | Proposer ↔ Critic | N 个独立视角 Persona |
| 调用方式 | 串行多轮迭代 | 并行单轮扇出 |
| 输出 | 修订后的 final_proposal + outstanding_objections | consensus + conflicts + requires_human |
| Token 成本 | 2-6 次 LLM 调用/任务 | N 次 LLM 调用/任务（默认 N=5） |
| 适用场景 | 单方案深度打磨 | 多方案对比决策 |
| 触发 Profile | review / strict | review / strict |
| 视角同质化防御 | fingerprint 去重防重复质疑 | 显式约束"看不到其他视角结论" |

**关键差异**：F-163 让"一个方案反复被打磨到最好"；F-164 让"多个方案同时被评估"。两者**可同时启用**（不冲突），适用于"既要打磨当前方案，又要探索替代方案"的复合场景。

---

## §4 变更记录

| 日期 | 作者 | 变更 |
|:----:|------|------|
| 2026-07-22 | 起草 | 初始创建 | DC-A §4.4 映射表基础上落地 F-164 多视角扇出；覆盖 DC-010；Wave 2 P1 第三个落地 F-N；是 Wave 2 P1 工具化组的"决策层"多视角对照（区别于 F-162 "事实层"硬拦截 / F-163 "方案层"纵深对抗）；5 个默认 Perspective Persona（senior-engineer / security-reviewer / newcomer / perf-optimizer / maintainer）+ 并行扇出（asyncio.gather）+ Synthesizer 二阶段综合（启发式 + LLM 兜底）+ 5 Profile 触发策略 + 动态注册 Protocol；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-163 协同；解耦落地于 `extensions/multi_perspective/`，零 `src/` 侵入 |
