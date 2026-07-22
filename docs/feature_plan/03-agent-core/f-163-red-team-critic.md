# F-163: 对抗质疑器 — Red-Team Critic 1v1 纵深对抗

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-163-red-team-critic.md`
> 最后更新: 2026-07-22
> 设计来源: DC-A 元架构脑暴 [§3.B 抗幻觉机制](dynamic-context-architecture.md) — DC-008

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 2 P1 工具化组（中等门槛，~2-3 月可落地） |
| 覆盖 DC | DC-008 对抗质疑器 (Red-Team Critic) |
| 前置依赖 | F-118 子 agent 编排 + F-119 Section Registry + F-102 Hook 扩展点 + F-162 审计日志 |
| 协同 | F-130 Profile（触发策略可作 Profile 配置项）、F-162 审计日志（反证证据来源）、F-164 多视角（同期 Wave 2 横向） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/red_team_critic/`，零 `src/` 侵入 |
| 落地形态 | Critic / Proposer / Synthesizer 三角色 + 多轮迭代循环 + 触发策略 |

---

## §1 设计规划

### 1.1 背景

F-158 / F-162 已提供"事实主张的可信度标注 + 关键事实硬拦截"两层防御，但**只解决"事实对不对"**，未解决"方案行不行"。

**问题**：当 Agent 给出方案（API 设计 / 架构选型 / 重构路径 / 风险评估）时，单纯的事实正确 ≠ 方案最优。一个不靠谱的方案可能：
- 选了正确的库版本但调用方式反模式
- 改了正确的文件但引入更大的回归风险
- 给出"理论上可行"的方案但完全没考虑成本 / 团队习惯 / 维护成本

**期望单个 LLM 自我对抗不可靠**：实验证明 LLM 在自我批评时倾向于"自圆其说"——既肯定优点又找缺点，但找出的缺点往往不痛不痒（确认偏差 confirmation bias）。

**F-163 的定位**：引入一个**专门对抗人格的 sub-agent**（Red-Team Critic），让 Proposer 和 Critic **1v1 纵深对抗**多轮迭代，直到 Critic 无新质疑或达最大轮数。

### 1.2 目标

- 让"方案评估"从"LLM 单链推理"升级为"Proposer ↔ Critic 多轮对抗"
- 让 Critic 输出**结构化质疑清单**（claim / counter_evidence / severity），可被下游消费
- 让 Proposer 收到质疑后能针对性修订（而不是泛泛"我再想想"）
- 与 F-118 子 agent 编排基础设施复用，不重新发明轮子
- 与 F-162 审计日志协同：F-162 的"未验证 claim" 可作为 Critic 反证证据

### 1.3 非目标 (Out of Scope)

- 不替代 F-164 多视角扇出（DC-010）—— 对抗是 1v1 纵深，多视角是 N 选 1 横向
- 不替代 F-130 矛盾检测器（P130-A）—— 矛盾检测关注"输出内部一致性"，Critic 关注"方案是否最优"
- 不替代 F-162 关键事实硬拦截 —— 事实正确是基础，方案对抗是上层
- 不替代人类 review —— Critic 是辅助，最终决策权仍在用户
- 不立即支持多 Critic 并行（先单 Critic 多轮；多 Critic 是 Wave 3 / F-168 假设并行情景的延伸）

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖 DC | 状态 | 工时 |
|:----:|--------|:-------:|:----:|:----:|
| P163-A | Critic 角色定义（persona + 质疑 prompt 模板） | DC-008 核心 | 📋 | 2-3d |
| P163-B | Proposer ↔ Critic 多轮迭代循环 | DC-008 核心 | 📋 | 3-4d |
| P163-C | 结构化质疑输出（claim / counter_evidence / severity） | DC-008 输出契约 | 📋 | 1-2d |
| P163-D | Proposer 修订机制（接收质疑 → 针对性修改） | DC-008 修订 | 📋 | 2-3d |
| P163-E | 终止条件 + Synthesizer 角色 | DC-008 收敛 | 📋 | 1-2d |
| P163-F | 触发策略（哪些场景启用 Critic） | DC-008 部署 | 📋 | 1d |
| P163-G | Critic 审计日志（与 F-162 协同） | DC-008 运营 | 📋 | 1d（远期） |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-118 子 agent 编排 | **强协同（前置）** | Critic / Proposer / Synthesizer 均通过 F-118 sub-agent 框架实例化；复用 F-118 `SubAgent.run(prompt, persona=...)` |
| F-119 Section Registry | **强协同** | P163-A 通过 `register_section` 注入 `red_team_critic_guide` section，让 Critic / Proposer 在 system prompt 看到自己的角色定义 |
| F-102 Hook Extensions | **强协同** | P163-B 多轮循环可通过 F-102 `LoopHook.post_query` 触发；终止条件通过 `pre_reply` 拦截"未对抗完成即输出" |
| F-162 工具强制验证（Wave 2 同波） | **协同（输入）** | F-162 审计日志中的"未验证 claim" 可作为 Critic 反证证据；F-163 §1.7.7 可消费 |
| F-130 Profile | **协同** | P163-F 触发策略可作 Profile 配置项（`review` Profile 默认启用 Critic；`default` Profile 默认不启用） |
| F-164 多视角扇出（Wave 2 同波） | **同期区分** | F-163 是 1v1 纵深，F-164 是 N 选 1 横向；两者共用 F-118 sub-agent 基础设施，但**不共享触发路径** |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/red_team_critic/__init__.py` | — | 子系统入口；注册 critic / proposer / synthesizer / loop |
| `extensions/red_team_critic/critic.py` | P163-A | `CriticPersona` dataclass + `CRITIC_PROMPT_TEMPLATE` + `Critic.find_objections(proposal)` |
| `extensions/red_team_critic/proposer.py` | P163-D | `ProposerPersona` + `Proposer.revise(proposal, critique)` |
| `extensions/red_team_critic/synthesizer.py` | P163-E | `SynthesizerPersona` + `Synthesizer.finalize(proposal, critique_history)` |
| `extensions/red_team_critic/loop.py` | P163-B | `adversarial_review(proposal, *, rounds, early_stop) -> FinalDecision` 多轮迭代主循环 |
| `extensions/red_team_critic/structured.py` | P163-C | `Objection` dataclass（claim / counter_evidence / severity / category）+ JSON schema 校验 |
| `extensions/red_team_critic/trigger.py` | P163-F | `should_run_critic(context) -> bool` 触发策略；基于 Profile + 任务风险等级 + 历史审计 |
| `extensions/red_team_critic/audit.py` | P163-G | NDJSON 质疑历史记录；与 F-162 audit log schema 兼容 |
| `extensions/red_team_critic/capabilities.py` | — | Protocol 接口契约（`Critic` / `Proposer` / `Synthesizer` / `LoopController` / `TriggerPolicy`） |
| `extensions/red_team_critic/hooks.py` | 全部 | 在 F-102 LoopHook 注册 `red_team_critic.orchestrate`（拦截 + 编排） |
| `tests/red_team_critic/test_critic.py` | P163-A | Critic 输出格式校验 + 角色 prompt 注入测试 |
| `tests/red_team_critic/test_proposer.py` | P163-D | Proposer 修订响应测试（mock critique 输入） |
| `tests/red_team_critic/test_structured.py` | P163-C | Objection dataclass + JSON schema 解析 |
| `tests/red_team_critic/test_loop.py` | P163-B | 1 / 2 / 3 轮迭代 + early_stop 触发 |
| `tests/red_team_critic/test_synthesizer.py` | P163-E | 收敛判定 + 最终输出格式 |
| `tests/red_team_critic/test_trigger.py` | P163-F | 4 Profile 触发策略 + 风险等级 |
| `tests/red_team_critic/test_e2e.py` | 全部 | 端到端：proposal → Critic 3 轮 → Proposer 修订 → Synthesizer 收敛 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_red_team_critic_extensions()` 在 import 时注册 critic / loop / trigger |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | 在 `pre_reply_hook` 链追加 `red_team_critic.trigger_check`（仅当 trigger 命中才进入 loop） |
| `extensions/sub_agent/` （F-118） | 不修改；F-163 通过 F-118 public API 调用 |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.red_team_critic` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-163 |
| `docs/feature_plan/dynamic-context-architecture.md` | §8 变更记录 + §4.4 映射表标记 F-163 状态 |

### 1.7 核心 API 设计

#### 1.7.1 Critic 角色定义（P163-A）

```python
# extensions/red_team_critic/critic.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from extensions.red_team_critic.structured import Objection


# Critic 必须包含"承认优点"部分，避免单边悲观
CRITIC_PROMPT_TEMPLATE = """你是 Red-Team Critic（对抗质疑员）。

任务：对以下方案提出**3 条最尖锐的质疑**，同时指出 1 条该方案的合理之处（避免单边悲观）。

方案：
{proposal}

历史质疑（用于去重，不要重复已提出的质疑）：
{prior_objections}

输出要求（严格 JSON，不要任何 markdown 包装）：
{{
  "strengths": ["<string>", ...],              // 1-2 条合理之处
  "objections": [
    {{
      "claim": "<被质疑的具体子断言>",          // 必须从方案中可定位
      "counter_evidence": "<反驳证据或反例>",   // 引用文档 / 经验 / 案例
      "severity": "low" | "medium" | "high" | "critical",
      "category": "performance" | "security" | "maintainability" | "ux" | "correctness" | "cost"
    }},
    ...
  ]
}}
"""


@dataclass
class CriticPersona:
    """Critic 角色配置。"""
    name: str = "red-team"
    temperature: float = 0.7                  # 适度随机避免模板化质疑
    max_objections_per_round: int = 3
    require_strengths: bool = True              # 必须输出 strengths（防单边悲观）
    categories: tuple[str, ...] = (
        "performance", "security", "maintainability",
        "ux", "correctness", "cost",
    )


class Critic:
    """Critic 角色实例（封装 F-118 sub-agent 调用）。"""

    def __init__(self, persona: CriticPersona, *, sub_agent: object):
        self.persona = persona
        self.sub_agent = sub_agent                  # F-118 SubAgent 实例

    def find_objections(
        self,
        proposal: str,
        *,
        prior_objections: list[Objection] | None = None,
    ) -> dict:
        """调用 sub-agent 执行 Critic 任务，返回结构化输出。"""
        prior = prior_objections or []
        prior_text = "\n".join(
            f"- [{o.severity}] {o.claim}" for o in prior
        ) or "（无历史质疑）"

        prompt = CRITIC_PROMPT_TEMPLATE.format(
            proposal=proposal,
            prior_objections=prior_text,
        )
        raw = self.sub_agent.run(
            prompt,
            persona=self.persona.name,
            temperature=self.persona.temperature,
        )
        # 解析为结构化对象
        return parse_critic_output(raw, self.persona)
```

#### 1.7.2 Proposer 修订机制（P163-D）

```python
# extensions/red_team_critic/proposer.py
from __future__ import annotations

from dataclasses import dataclass

from extensions.red_team_critic.structured import Objection


PROPOSER_REVISE_PROMPT = """你是 Proposer（方案提出者）。

你之前的方案：
{proposal}

Critic 提出的质疑：
{objections_text}

任务：**针对每条质疑**给出回应，并修订方案。回应可以是：
- "接受"：修订方案，对应章节标注 [REVISED: ...]
- "拒绝"：给出反驳理由（与 Critic 进一步对抗，由 Synthesizer 终裁）
- "部分接受"：修订部分内容，说明保留理由

输出要求（严格 JSON）：
{{
  "responses": [
    {{
      "objection_claim": "<对应质疑的 claim>",
      "decision": "accept" | "reject" | "partial",
      "rationale": "<回应理由>",
      "revised_section": "<被修订的方案片段，> 或 <原文不变>"
    }},
    ...
  ],
  "revised_proposal": "<完整的修订后方案>"
}}
"""


@dataclass
class ProposerPersona:
    name: str = "proposer"
    temperature: float = 0.5
    require_per_objection_response: bool = True   # 必须逐条回应


class Proposer:
    def __init__(self, persona: ProposerPersona, *, sub_agent: object):
        self.persona = persona
        self.sub_agent = sub_agent

    def revise(self, proposal: str, objections: list[Objection]) -> str:
        objections_text = "\n".join(
            f"[{o.severity}|{o.category}] {o.claim}\n  反证: {o.counter_evidence}"
            for o in objections
        )
        prompt = PROPOSER_REVISE_PROMPT.format(
            proposal=proposal,
            objections_text=objections_text,
        )
        raw = self.sub_agent.run(
            prompt,
            persona=self.persona.name,
            temperature=self.persona.temperature,
        )
        # 解析：取 revised_proposal 字段
        parsed = parse_proposer_output(raw, self.persona)
        return parsed["revised_proposal"]


def parse_critic_output(raw: str, persona: CriticPersona) -> dict:
    """解析 Critic JSON 输出（剥离 markdown 包装，校验 schema）。"""
    import json
    import re
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    data = json.loads(text)
    if persona.require_strengths and not data.get("strengths"):
        raise ValueError("Critic output missing 'strengths' field (anti-single-sided-pessimism)")
    if len(data.get("objections", [])) > persona.max_objections_per_round:
        raise ValueError(f"Too many objections: {len(data['objections'])}")
    return data


def parse_proposer_output(raw: str, persona: ProposerPersona) -> dict:
    """解析 Proposer JSON 输出。"""
    import json
    import re
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    return json.loads(text)
```

#### 1.7.3 结构化质疑输出（P163-C）

```python
# extensions/red_team_critic/structured.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal
import hashlib

Severity = Literal["low", "medium", "high", "critical"]
Category = Literal["performance", "security", "maintainability", "ux", "correctness", "cost"]


@dataclass
class Objection:
    """单条结构化质疑。"""
    claim: str                                  # 被质疑的具体子断言
    counter_evidence: str                       # 反驳证据或反例
    severity: Severity
    category: Category
    source_round: int = 0                       # 第几轮提出的（去重追踪）
    fingerprint: str = ""                       # claim 哈希（去重）

    def __post_init__(self):
        if not self.fingerprint:
            # 用 claim 文本生成 fingerprint（忽略大小写和标点差异）
            normalized = self.claim.lower().strip()
            self.fingerprint = hashlib.sha1(normalized.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Objection":
        return cls(
            claim=data["claim"],
            counter_evidence=data["counter_evidence"],
            severity=data["severity"],
            category=data["category"],
            source_round=data.get("source_round", 0),
            fingerprint=data.get("fingerprint", ""),
        )


# Critic 输出的 JSON schema（用于 fail-fast 校验）
CRITIC_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["objections"],
    "properties": {
        "strengths": {"type": "array", "items": {"type": "string"}},
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim", "counter_evidence", "severity", "category"],
                "properties": {
                    "claim": {"type": "string", "minLength": 5},
                    "counter_evidence": {"type": "string", "minLength": 5},
                    "severity": {"enum": ["low", "medium", "high", "critical"]},
                    "category": {"enum": ["performance", "security", "maintainability", "ux", "correctness", "cost"]},
                },
            },
        },
    },
}
```

#### 1.7.4 多轮迭代循环（P163-B）

```python
# extensions/red_team_critic/loop.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from extensions.red_team_critic.critic import Critic
from extensions.red_team_critic.proposer import Proposer
from extensions.red_team_critic.synthesizer import Synthesizer
from extensions.red_team_critic.structured import Objection


@dataclass
class LoopConfig:
    """循环配置。"""
    max_rounds: int = 3
    early_stop_on_no_new_objections: bool = True
    early_stop_on_low_severity_only: bool = True   # 仅剩 low 级质疑 → 提前收敛
    require_per_round_min_objections: int = 1       # 每轮至少 1 条质疑（防 Critic 偷懒）


@dataclass
class RoundTrace:
    """单轮迭代的完整轨迹（用于审计 + Synthesizer 终裁）。"""
    round_index: int
    proposal: str
    objections: list[Objection]
    revised_proposal: str
    strengths: list[str] = field(default_factory=list)


@dataclass
class FinalDecision:
    """对抗审查的最终输出。"""
    final_proposal: str
    rounds: int
    trace: list[RoundTrace]
    outstanding_objections: list[Objection]      # 未被 Proposer 接受的质疑
    confidence: float                             # 0.0 ~ 1.0


def adversarial_review(
    proposal: str,
    *,
    critic: Critic,
    proposer: Proposer,
    synthesizer: Synthesizer,
    config: LoopConfig | None = None,
    on_round_complete: Any | None = None,         # 回调：每轮完成时触发（用于审计）
) -> FinalDecision:
    """Proposer ↔ Critic 多轮迭代主循环。

    Args:
        proposal: 初始方案
        critic: Critic 角色
        proposer: Proposer 角色
        synthesizer: Synthesizer 角色（用于终裁）
        config: 循环配置
        on_round_complete: 回调（用于审计 / UI 实时展示）

    Returns:
        FinalDecision — 含 final_proposal / rounds / trace / outstanding_objections / confidence
    """
    config = config or LoopConfig()
    trace: list[RoundTrace] = []
    current_proposal = proposal
    prior_objections: list[Objection] = []

    for round_idx in range(1, config.max_rounds + 1):
        # 1. Critic 找茬
        critic_out = critic.find_objections(current_proposal, prior_objections=prior_objections)
        new_objections = [
            Objection(
                claim=o["claim"],
                counter_evidence=o["counter_evidence"],
                severity=o["severity"],
                category=o["category"],
                source_round=round_idx,
            )
            for o in critic_out.get("objections", [])
        ]

        # 2. 早停检查
        if config.early_stop_on_no_new_objections and not _has_new(prior_objections, new_objections):
            break
        if config.require_per_round_min_objections and len(new_objections) < 1:
            break
        if config.early_stop_on_low_severity_only and all(
            o.severity == "low" for o in new_objections
        ):
            # 仅剩 low 级质疑 → 收敛，让 Proposer 修订后定稿
            pass  # 不 break，让本轮正常完成

        # 3. Proposer 修订
        revised = proposer.revise(current_proposal, new_objections)

        # 4. 记录
        round_trace = RoundTrace(
            round_index=round_idx,
            proposal=current_proposal,
            objections=new_objections,
            revised_proposal=revised,
            strengths=critic_out.get("strengths", []),
        )
        trace.append(round_trace)
        if on_round_complete:
            on_round_complete(round_trace)

        # 5. 更新状态
        prior_objections.extend(new_objections)
        current_proposal = revised

    # 6. Synthesizer 终裁
    final = synthesizer.finalize(current_proposal, trace)
    return final


def _has_new(prior: list[Objection], new: list[Objection]) -> bool:
    """判定 new 中是否有 fingerprint 不在 prior 的质疑。"""
    prior_fps = {o.fingerprint for o in prior}
    return any(o.fingerprint not in prior_fps for o in new)
```

#### 1.7.5 终止条件 + Synthesizer（P163-E）

```python
# extensions/red_team_critic/synthesizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from extensions.red_team_critic.loop import RoundTrace, FinalDecision


SYNTHESIZER_FINALIZE_PROMPT = """你是 Synthesizer（终裁者）。

Proposer 与 Critic 已完成多轮对抗。最终方案：
{final_proposal}

所有质疑历史：
{objections_history}

未解决的质疑（如有）：
{outstanding_objections}

任务：给出**最终决策**与置信度。

输出要求（严格 JSON）：
{{
  "final_proposal": "<采纳的最终方案，可与 Proposer 最后输出相同，或综合调整>",
  "confidence": <float 0.0~1.0>,
  "rationale": "<决策理由：哪些质疑被采纳、哪些被拒绝>",
  "outstanding_risks": ["<未解决但被接受的质疑>", ...]
}}
"""


@dataclass
class SynthesizerPersona:
    name: str = "synthesizer"
    temperature: float = 0.3                   # 低温度保证终裁稳定


class Synthesizer:
    def __init__(self, persona: SynthesizerPersona, *, sub_agent: object):
        self.persona = persona
        self.sub_agent = sub_agent

    def finalize(self, final_proposal: str, trace: list) -> "FinalDecision":
        from extensions.red_team_critic.loop import FinalDecision

        objections_history = "\n\n".join(
            f"Round {rt.round_index}:\n" +
            "\n".join(f"  - [{o.severity}|{o.category}] {o.claim}" for o in rt.objections)
            for rt in trace
        ) or "（无质疑历史）"

        # 提取 outstanding_objections（severity high+ 且未在后续修订中被解决）
        outstanding = _extract_outstanding(trace)

        prompt = SYNTHESIZER_FINALIZE_PROMPT.format(
            final_proposal=final_proposal,
            objections_history=objections_history,
            outstanding_objections="\n".join(
                f"  - [{o.severity}] {o.claim}" for o in outstanding
            ) or "（无）",
        )
        raw = self.sub_agent.run(
            prompt,
            persona=self.persona.name,
            temperature=self.persona.temperature,
        )
        import json
        import re
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        data = json.loads(text)
        return FinalDecision(
            final_proposal=data["final_proposal"],
            rounds=len(trace),
            trace=trace,
            outstanding_objections=outstanding,
            confidence=float(data["confidence"]),
        )


def _extract_outstanding(trace: list) -> list:
    """提取未解决的质疑（heuristic：最后轮提出且 severity>=high）。"""
    if not trace:
        return []
    last_round = trace[-1]
    return [
        o for o in last_round.objections
        if o.severity in ("high", "critical")
    ]
```

#### 1.7.6 触发策略（P163-F）

```python
# extensions/red_team_critic/trigger.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    """任务风险等级（由 Agent 自评或外部注入）。"""
    LOW = "low"               # 普通对话 / 简单查询
    MEDIUM = "medium"         # 代码改动 / 配置变更
    HIGH = "high"             # 架构选型 / 关键 API 设计
    CRITICAL = "critical"     # 安全相关 / 数据迁移 / 不可逆操作


@dataclass
class TriggerPolicy:
    """Critic 触发策略。"""
    enabled: bool = False
    min_risk_level: RiskLevel = RiskLevel.HIGH
    max_proposal_length: int = 8000              # 超过此长度强制启用
    require_keywords: tuple[str, ...] = ()       # 触发关键词（如 "重构" / "迁移"）
    exclude_keywords: tuple[str, ...] = ()       # 排除关键词（如 "typo" / "格式"）


# ==== Profile → TriggerPolicy 映射（F-130 协同） ====

PROFILE_TRIGGERS: dict[str, TriggerPolicy] = {
    "default": TriggerPolicy(
        enabled=False,                            # 默认 Profile 不启用
        min_risk_level=RiskLevel.HIGH,
    ),
    "review": TriggerPolicy(
        enabled=True,                             # review Profile 默认启用
        min_risk_level=RiskLevel.MEDIUM,
        require_keywords=("重构", "迁移", "设计", "选型", "refactor", "migration"),
    ),
    "strict": TriggerPolicy(
        enabled=True,
        min_risk_level=RiskLevel.LOW,             # strict 连低风险也对抗
        require_keywords=(),
    ),
    "debug": TriggerPolicy(
        enabled=False,                            # debug Profile 不对抗（专注于快速修复）
        min_risk_level=RiskLevel.CRITICAL,
    ),
    "creative": TriggerPolicy(
        enabled=False,                            # creative 鼓励发散，不对抗
        min_risk_level=RiskLevel.CRITICAL,
    ),
}


def should_run_critic(
    context: dict,
    *,
    profile_id: str | None = None,
) -> bool:
    """判定当前上下文是否应触发 Critic。

    Args:
        context: {"risk_level": str, "proposal": str, "intent": str}
        profile_id: 当前 F-130 Profile ID

    Returns:
        True = 启用 Critic 多轮对抗
    """
    policy = PROFILE_TRIGGERS.get(profile_id or "default", PROFILE_TRIGGERS["default"])
    if not policy.enabled:
        return False

    risk = RiskLevel(context.get("risk_level", "low"))
    risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    if risk_order.index(risk) < risk_order.index(policy.min_risk_level):
        return False

    proposal = context.get("proposal", "")
    if len(proposal) > policy.max_proposal_length:
        return True

    intent = context.get("intent", "").lower()
    if any(kw.lower() in intent for kw in policy.exclude_keywords):
        return False
    if policy.require_keywords and not any(kw.lower() in intent for kw in policy.require_keywords):
        return False

    return True
```

#### 1.7.7 Hook 集成

```python
# extensions/red_team_critic/hooks.py
from __future__ import annotations

from typing import Any

from extensions.red_team_critic.loop import adversarial_review
from extensions.red_team_critic.critic import Critic
from extensions.red_team_critic.proposer import Proposer
from extensions.red_team_critic.synthesizer import Synthesizer
from extensions.red_team_critic.trigger import should_run_critic


def red_team_critic_pre_reply_hook(
    proposal: str,
    history: list[dict],
    *,
    sub_agents: dict[str, Any],                # F-118 sub-agent 实例池
    profile_id: str | None = None,
    risk_level: str = "medium",
    audit_sink: Any | None = None,
) -> dict:
    """F-102 LoopHook 集成的 Critic 编排入口。

    Returns:
        {
            "decision": "pass" | "intercept",
            "modified_proposal": str,           # 经对抗修订后的方案
            "rounds": int,
            "outstanding_objections": list[dict],
            "confidence": float,
        }
    """
    context = {"proposal": proposal, "risk_level": risk_level, "intent": history[-1].get("content", "") if history else ""}
    if not should_run_critic(context, profile_id=profile_id):
        return {"decision": "pass", "modified_proposal": proposal, "rounds": 0,
                "outstanding_objections": [], "confidence": 1.0}

    critic = Critic(sub_agent=sub_agents["red-team"])
    proposer = Proposer(sub_agent=sub_agents["proposer"])
    synthesizer = Synthesizer(sub_agent=sub_agents["synthesizer"])

    def _on_round(round_trace):
        if audit_sink:
            audit_sink.write(round_trace)

    final = adversarial_review(
        proposal,
        critic=critic,
        proposer=proposer,
        synthesizer=synthesizer,
        on_round_complete=_on_round,
    )

    return {
        "decision": "intercept" if final.confidence < 0.7 else "pass",
        "modified_proposal": final.final_proposal,
        "rounds": final.rounds,
        "outstanding_objections": [o.to_dict() for o in final.outstanding_objections],
        "confidence": final.confidence,
    }
```

### 1.8 核心流程

```
[Agent 提出 proposal]
    ↓
[F-102 LoopHook.pre_reply 链]
    ├─→ [F-158 scan_for_unmarked_claims]        # 软警告（已有）
    ├─→ [F-162 pre_reply_interceptor]            # 硬拦截（Wave 2 同波）
    ├─→ [F-163 red_team_critic_pre_reply_hook]   # 对抗编排（新增）
    │       ├─ should_run_critic(context, profile)?
    │       │   ├─ False → pass（保持原 proposal）
    │       │   └─ True → 进入对抗循环
    │       │
    │       ├─ Round 1..N:
    │       │   ├─ Critic.find_objections(proposal, prior) → JSON {strengths, objections}
    │       │   ├─ 校验 JSON schema（fail-fast）
    │       │   ├─ 检查早停（无新质疑 / 仅 low / 达到 max_rounds）
    │       │   ├─ Proposer.revise(proposal, objections) → revised_proposal
    │       │   ├─ on_round_complete(round_trace) → 写 audit log
    │       │   └─ 更新 current_proposal = revised
    │       │
    │       └─ Synthesizer.finalize(final_proposal, trace) → FinalDecision
    │           ├─ confidence < 0.7 → 标记 decision="intercept"，返回 modified_proposal
    │           └─ confidence >= 0.7 → decision="pass"，返回 modified_proposal
    ↓
[Orchestrator 决策]:
    ├─ decision=pass → 输出 modified_proposal（可能与原 proposal 相同）
    └─ decision=intercept → 输出 modified_proposal + outstanding_objections（UI 提示）
```

### 1.9 与现有架构的对齐

| 对齐点 | 说明 |
|-------|------|
| F-118 子 agent 编排 | Critic / Proposer / Synthesizer 均通过 F-118 SubAgent 实例化；复用 `SubAgent.run(prompt, persona=...)` 接口 |
| F-119 Section Registry | 通过 `register_section("red_team_critic_guide", ...)` 让 Critic / Proposer / Synthesizer 在 system prompt 看到各自角色定义 |
| F-102 LoopHook | 在 `pre_reply_hook` 链追加 `red_team_critic.trigger_check`；位于 F-158 / F-162 之后 |
| F-162 审计日志 | F-162 审计日志中的"未验证 claim" 可作为 Critic 反证证据（`counter_evidence` 字段引用 F-162 NDJSON）；audit schema 兼容 |
| F-130 Profile | PROFILE_TRIGGERS 5 Profile 映射：default(off)/review(on, medium)/strict(on, low)/debug(off)/creative(off)；切换 Profile 时 trigger 自动重读 |
| F-164 多视角（同期 Wave 2） | F-163 是 1v1 纵深；F-164 是 N 选 1 横向；两者共用 F-118 sub-agent 基础设施，但**不共享触发路径**（F-163 串行迭代，F-164 并行扇出） |
| 解耦 | 全部落在 `extensions/red_team_critic/`；F-102 hook 注册在 `clawcodex_ext/hooks/_pluggy_adapter.py`；零 `src/` 侵入 |

### 1.10 风险与缓解

| 风险 | 描述 | 缓解 |
|------|------|------|
| **Critic 过度悲观** | Critic 永远找茬，无视方案优点 | P163-A `CriticPersona.require_strengths=True` 强制输出 `strengths` 字段；fail-fast 校验 |
| **Proposer 接受所有质疑** | Proposer 失去主见，被 Critic 牵着走 | P163-D `PROPOSER_REVISE_PROMPT` 显式列出"接受 / 拒绝 / 部分接受"三选项；JSON 解析 `decision` 字段 |
| **Token 翻倍成本** | 3 轮迭代 = 6 次 LLM 调用 | P163-F 触发策略默认 `enabled=False`（仅 review/strict Profile 启用）；`max_rounds=3` 上限；`early_stop` 多条件收敛 |
| **Critic 输出格式不稳定** | LLM 不严格按 JSON 输出 | P163-C `CRITIC_OUTPUT_SCHEMA` 校验；`parse_critic_output` fail-fast 抛错；UI 层降级（展示原文） |
| **多轮循环死锁** | Critic / Proposer 互相反驳不收敛 | P163-B `max_rounds=3` 硬上限 + `early_stop_on_no_new_objections` 基于 fingerprint 去重 |
| **审计日志膨胀** | 3 轮 × 3 objection = 9 条/任务 | P163-G NDJSON 追加；可配置 `audit_enabled=False`（debug Profile 默认关闭） |
| **与 F-162 冲突** | F-162 拦截 + F-163 对抗可能双倍拦截 | Hook 链顺序：F-158 → F-162 → F-163；F-162 拦截会先于 F-163 触发；F-162 BLOCK 时 F-163 不再触发 |
| **与 F-164 重复** | F-164 多视角 vs F-163 对抗边界模糊 | F-163 是 1v1 纵深（串行多轮），F-164 是 N 选 1 横向（并行扇出）；两者**不共享触发路径**；用户可同时启用（不冲突） |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 说明 |
|:----:|--------|------|
| 2026-07-22 | 初始文档创建 | DC-A §4.4 映射表基础上落地 F-163 对抗质疑器；覆盖 DC-008；Wave 2 P1 第二个落地 F-N；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-164 协同；解耦落地于 `extensions/red_team_critic/`，零 `src/` 侵入 |

### 2.2 待验证项

| 编号 | 验证项 | 关联子特性 |
|:----:|--------|:----------:|
| 1 | `CRITIC_PROMPT_TEMPLATE` 注入 Critic 后输出 JSON 严格符合 `CRITIC_OUTPUT_SCHEMA` | P163-A / P163-C |
| 2 | `parse_critic_output` fail-fast：缺少 `strengths` 字段抛错 | P163-A / P163-C |
| 3 | `parse_critic_output` fail-fast：objections 数量超 `max_objections_per_round` 抛错 | P163-A / P163-C |
| 4 | `Proposer.revise` 严格按 JSON 输出，含 `decision` 字段（accept/reject/partial） | P163-D |
| 5 | `adversarial_review` 1 / 2 / 3 轮迭代各路径 | P163-B |
| 6 | 早停：`early_stop_on_no_new_objections`（fingerprint 去重生效） | P163-B |
| 7 | 早停：`max_rounds=3` 硬上限生效 | P163-B |
| 8 | `Synthesizer.finalize` 提取 outstanding_objections（severity high+） | P163-E |
| 9 | `PROFILE_TRIGGERS` 5 Profile 触发策略（default/review/strict/debug/creative） | P163-F |
| 10 | `should_run_critic` 关键词匹配（require / exclude） | P163-F |
| 11 | Hook 链顺序：F-158 → F-162 → F-163 | 集成 |
| 12 | F-118 SubAgent 实例池注入（critic / proposer / synthesizer 三个 sub-agent） | 集成 |
| 13 | F-119 `register_section("red_team_critic_guide", ...)` 集成 | 集成 |
| 14 | F-162 audit log 兼容（counter_evidence 字段可引用） | P163-G |
| 15 | E2E：完整对抗流程 + audit log 写入 | 集成 |

---

## §3 实施细节

### 3.1 验收标准

**功能完整性**：
- [ ] Critic / Proposer / Synthesizer 三角色 prompt 模板可注入并产出 JSON
- [ ] `parse_critic_output` 严格校验 schema（fail-fast on 字段缺失 / 类型错误）
- [ ] `adversarial_review` 支持 1-3 轮迭代，早停条件均生效
- [ ] 5 Profile 触发策略差异化生效（review/strict 启用，default/debug/creative 关闭）
- [ ] NDJSON 审计日志写入且与 F-162 schema 兼容

**质量门禁**：
- [ ] Stage 5 扩展测试 `extensions.red_team_critic` 模块导入通过
- [ ] `tests/red_team_critic/` 7 个测试用例全 PASS
- [ ] ruff check `extensions/red_team_critic/` 无 error
- [ ] 与 F-118 sub-agent 集成测试无回归

**运营可见性**：
- [ ] UI 层可展示对抗轮次轨迹（Round 1..N 的 proposal + objections + revised）
- [ ] `outstanding_objections` 在 UI 层醒目提示（severity high+）
- [ ] `confidence < 0.7` 时强制 UI 二次确认
- [ ] NDJSON 审计日志可被 `jq` 查询

### 3.2 落地路径（推荐顺序）

1. **P163-C 先行** — `Objection` dataclass + `CRITIC_OUTPUT_SCHEMA` 落地，先跑 JSON schema 校验测试
2. **P163-A Critic** — `CRITIC_PROMPT_TEMPLATE` + `CriticPersona` + `parse_critic_output` 实现
3. **P163-D Proposer** — `PROPOSER_REVISE_PROMPT` + `ProposerPersona` + `parse_proposer_output` 实现
4. **P163-E Synthesizer** — `SYNTHESIZER_FINALIZE_PROMPT` + `SynthesizerPersona` + `finalize` 实现
5. **P163-B 多轮循环** — `adversarial_review` 主循环 + 早停条件 + fingerprint 去重
6. **P163-F 触发策略** — `PROFILE_TRIGGERS` + `should_run_critic` + CLAUDE.md YAML 解析（远期）
7. **P163-G 审计** — NDJSON 写入 + `extensions.tool_verification.audit` 兼容层
8. **集成到 F-102 LoopHook** — `red_team_critic_pre_reply_hook` 注册；F-118 sub-agent 池注入
9. **集成测试** — F-118 mock sub-agent + 端到端对抗流程

### 3.3 与 F-118 / F-119 / F-102 / F-162 / F-130 / F-164 的协同点

- **F-118 SubAgent** → Critic / Proposer / Synthesizer 通过 `sub_agents["red-team"]` / `sub_agents["proposer"]` / `sub_agents["synthesizer"]` 三实例；F-163 不重新发明 sub-agent 框架
- **F-119 `register_section`** → 注册 `red_team_critic_guide` section（`order=70`，F-162 之后，F-160 之前），让三个 sub-agent 看到自己的角色定义
- **F-119 `dump_effective_system_prompt`** → 验证 `red_team_critic_guide` section 已注入到三个 sub-agent 的 system prompt
- **F-102 LoopHook** → P163-B 在 `pre_reply_hook` 链注册 `red_team_critic.orchestrate`；位于 F-158 / F-162 之后
- **F-162 audit log** → Critic 的 `counter_evidence` 字段可引用 F-162 NDJSON 中的"未验证 claim"作为反证证据；audit schema 兼容（同 `claim` / `severity` 字段语义）
- **F-130 Profile** → `PROFILE_TRIGGERS` 5 Profile 映射：default(off)/review(on, medium)/strict(on, low)/debug(off)/creative(off)；切换 Profile 时 trigger 自动重读
- **F-164 多视角（同期 Wave 2）** → F-163 是 1v1 纵深，F-164 是 N 选 1 横向；两者共用 F-118 sub-agent 基础设施，但**不共享触发路径**（F-163 串行多轮，F-164 并行扇出）；用户可同时启用

### 3.4 与 F-164 (多视角) 的边界

F-163 与 F-164 **不重复**，定位互补：

| 维度 | F-163 对抗 | F-164 多视角 |
|------|----------|-------------|
| 形态 | 1v1 纵深 | N 选 1 横向 |
| 角色 | Proposer ↔ Critic | N 个独立视角 Persona |
| 调用方式 | 串行多轮迭代 | 并行单轮扇出 |
| 输出 | 修订后的 final_proposal + outstanding_objections | N 个视角的方案 + consensus + conflicts |
| Token 成本 | 2-6 次 LLM 调用/任务 | N 次 LLM 调用/任务 |
| 适用场景 | 单方案深度打磨 | 多方案对比决策 |
| 触发 Profile | review / strict | high-risk 任务 |

**关键差异**：F-163 让"一个方案反复被打磨到最好"；F-164 让"多个方案同时被评估"。两者可同时启用（不冲突），适用于"既要打磨当前方案，又要探索替代方案"的复合场景。

---

## §4 变更记录

| 日期 | 作者 | 变更 |
|:----:|------|------|
| 2026-07-22 | 起草 | 初始创建 | DC-A §4.4 映射表基础上落地 F-163 对抗质疑器；覆盖 DC-008；Wave 2 P1 第二个落地 F-N；是 Wave 2 P1 工具化组的"方案层"对抗（区别于 F-162 "事实层"硬拦截）；Proposer / Critic / Synthesizer 三角色 + 多轮迭代循环 + 结构化质疑输出 + Proposer 修订机制 + 5 Profile 触发策略；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-164 协同；解耦落地于 `extensions/red_team_critic/`，零 `src/` 侵入 |