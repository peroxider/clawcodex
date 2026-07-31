# F-165: 矛盾检测独立版 — 三维语义矛盾检测 + 自动修订

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-165-self-contradiction-detector.md`
> 最后更新: 2026-07-22
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-007

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 2 P1 工具化组（中等门槛，~2-3 月可落地） |
| 覆盖 DC | DC-007 自相矛盾检测循环（**完整版**，F-130 P130-A 仅覆盖工具重复维度） |
| 前置依赖 | F-130 P130-A 循环检测器（避免重复检测工具重复维度）+ F-119 Section Registry + F-102 Hook 扩展点 + F-158 VERIFIED facts |
| 协同 | F-130 P130-A（工具重复检测，F-165 不重复）、F-158 VERIFIED Working Memory、F-163 对抗质疑器（同期 Wave 2，逻辑冲突信号可作 Critic 输入） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/contradiction_detector/`，零 `src/` 侵入 |
| 落地形态 | 三维矛盾检测器（vs VERIFIED / intra-reply / vs history）+ 修订循环 + 置信度门控 |

---

## §1 设计规划

### 1.1 背景

F-130 P130-A 已提供**循环检测器框架**，但**只覆盖"工具重复"维度**（如：连续 3 次调用 Read 同一文件、重复同一 Grep 查询、同一错误模式重复出现）。这只能捕获"行为模式重复"，**无法捕获语义矛盾**。

**问题**：Agent 输出中常出现语义层矛盾，**单链推理**无法避免：

| 类型 | 示例 |
|------|------|
| **与已知事实冲突** | 上一轮已 VERIFIED "Python 3.11 已 stable"，本轮断言"Python 3.12 才是 stable" |
| **内部不一致** | 同一回复前半段说"用 FastAPI"，后半段说"用 Django" |
| **与前文对话矛盾** | 前几轮说过"该项目使用 Poetry"，本轮断言"该项目使用 uv" |

这些矛盾**不是工具重复**，F-130 检测器无法捕获；**不是事实错误**（事实本身可能正确），F-158 置信度标注无法捕获；**不是关键事实**，F-162 硬拦截无法覆盖。

**F-165 的定位**：在 F-130 工具重复检测器之上，叠加**三维语义矛盾检测**：
- 维度 1：**vs VERIFIED facts** — 比对 F-158 Working Memory 中的已验证事实
- 维度 2：**intra-reply inconsistency** — 同一回复内前后断言的逻辑一致性
- 维度 3：**vs conversation history** — 与前几轮对话断言的一致性

检测到矛盾后 → 自动重写 / 标记冲突 / 抛给用户确认。

### 1.2 目标

- 让"语义矛盾"成为**可被检测、可被修订**的工件，而非"用户事后才发现"
- 让 F-130 工具重复检测与 F-165 语义矛盾检测**正交协作**（不重复检测同一信号）
- 让检测器输出**带置信度的结构化冲突**（而非二元 yes/no），可被下游消费
- 让"修订循环"轻量级（避免每轮都触发完整 LLM 调用）

### 1.3 非目标 (Out of Scope)

- 不替代 F-130 P130-A 工具重复检测器 —— F-165 是 F-130 之上的语义层扩展
- 不替代 F-158 置信度标注 —— F-158 是事实正确性，F-165 是断言间一致性
- 不替代 F-162 工具强制验证 —— F-162 是"是否调用工具"，F-165 是"断言间是否一致"
- 不立即支持跨会话持久化的"个人矛盾档案" —— 仅本会话内 Working Memory
- 不替代 F-163 对抗质疑器 —— F-163 是 Proposer↔Critic 1v1 纵深，F-165 是单 Proposer 内省；F-163 可消费 F-165 的冲突信号

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖 DC | 状态 | 工时 |
|:----:|--------|:-------:|:----:|:----:|
| P165-A | 三维矛盾检测器（vs VERIFIED / intra-reply / vs history） | DC-007 核心 | 📋 | 3-4d |
| P165-B | 输出 → 反馈 → 修订循环 | DC-007 核心 | 📋 | 2-3d |
| P165-C | 自动修订机制（rewrite / flag / ask user 三策略） | DC-007 修订 | 📋 | 2-3d |
| P165-D | 与 F-130 P130-A 检测器协同（去重 + 互补） | DC-007 与 F-130 边界 | 📋 | 1-2d |
| P165-E | 触发策略（5 Profile 映射 + 关键词匹配 + 长度门控） | DC-007 部署 | 📋 | 1d |
| P165-F | 冲突审计 NDJSON 日志 | DC-007 运营 | 📋 | 1d（远期） |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-130 P130-A 循环检测器 | **前置（去重）** | P165-D 协调：F-130 检测"工具重复"，F-165 检测"语义矛盾"，两者**正交不重叠** |
| F-119 Section Registry | **强协同** | P165-A 通过 `register_section` 注入 `contradiction_detector_guide` section，让模型看到三维检测规则 |
| F-102 Hook Extensions | **强协同** | P165-B 修订循环通过 F-102 `LoopHook.pre_reply` 拦截；与 F-130 检测器串联 |
| F-158 VERIFIED facts | **强协同（输入）** | P165-A 维度 1（vs VERIFIED）消费 F-158 Working Memory 中的 `ConfidenceMarker(VERIFIED)` |
| F-163 对抗质疑器（同期 Wave 2） | **协同** | F-165 检测到的"语义矛盾"可作为 Critic 反证证据（注入到 F-163 counter_evidence 字段） |
| F-130 Profile | **协同** | P165-E 触发策略可作 Profile 配置项（`strict` Profile 默认启用，`default` Profile 默认关闭） |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/contradiction_detector/__init__.py` | — | 子系统入口；注册 detector / reviser / trigger |
| `extensions/contradiction_detector/detector.py` | P165-A | `ContradictionDetector` + 3 个维度检测器 `VsVerifiedDetector` / `IntraReplyDetector` / `VsHistoryDetector` |
| `extensions/contradiction_detector/structured.py` | P165-A | `Conflict` dataclass（dimension / claim_a / claim_b / confidence / severity / suggested_fix）+ JSON schema 校验 |
| `extensions/contradiction_detector/reviser.py` | P165-C | `Reviser` + `rewrite_reply` / `flag_conflicts` / `ask_user` 三策略实现 |
| `extensions/contradiction_detector/loop.py` | P165-B | `detect_and_revise(reply, *, history, working_memory) -> ReviseResult` 主循环 |
| `extensions/contradiction_detector/coordinator.py` | P165-D | `F130Coordinator` — 与 F-130 P130-A 检测器协同（信号路由，避免重复检测） |
| `extensions/contradiction_detector/trigger.py` | P165-E | `should_run_detector(context) -> bool` 触发策略 + 5 Profile 映射 |
| `extensions/contradiction_detector/audit.py` | P165-F | NDJSON 冲突记录；与 F-158 / F-162 / F-163 audit schema 兼容 |
| `extensions/contradiction_detector/capabilities.py` | — | Protocol 接口契约（`Detector` / `Reviser` / `Coordinator` / `TriggerPolicy`） |
| `extensions/contradiction_detector/hooks.py` | 全部 | 在 F-102 LoopHook 注册 `contradiction_detector.detect_and_revise` |
| `tests/contradiction_detector/test_vs_verified.py` | P165-A 维度1 | mock F-158 Working Memory + 断言冲突测试 |
| `tests/contradiction_detector/test_intra_reply.py` | P165-A 维度2 | 同一回复内前后矛盾测试 |
| `tests/contradiction_detector/test_vs_history.py` | P165-A 维度3 | 与前几轮对话矛盾测试 |
| `tests/contradiction_detector/test_reviser.py` | P165-C | 三策略（rewrite / flag / ask user）行为测试 |
| `tests/contradiction_detector/test_coordinator.py` | P165-D | 与 F-130 P130-A 信号路由测试 |
| `tests/contradiction_detector/test_trigger.py` | P165-E | 5 Profile 触发策略 + 长度门控 |
| `tests/contradiction_detector/test_e2e.py` | 全部 | 端到端：reply → 检测 → 修订 → 输出 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_contradiction_detector_extensions()` 在 import 时注册 detector / reviser / coordinator |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | 在 `pre_reply_hook` 链追加 `contradiction_detector.detect_and_revise`（位于 F-130 P130-A 之后） |
| `extensions/self_correct/` （F-130） | 不修改；F-165 通过 F-130 public API 调用 P130-A 检测器 |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.contradiction_detector` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-165 |
| `docs/feature_plan/dynamic-context-index.md` | DC→F 映射、依赖与全局验收总则 |

### 1.7 核心 API 设计

#### 1.7.1 三维矛盾检测器（P165-A）

```python
# extensions/contradiction_detector/detector.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from extensions.contradiction_detector.structured import Conflict

if TYPE_CHECKING:
    from extensions.anti_hallucination.confidence_marker import ConfidenceMarker


class Detector(ABC):
    """矛盾检测器抽象接口（可被替换实现）。"""

    @abstractmethod
    def detect(
        self,
        reply: str,
        *,
        history: list[dict] | None = None,
        working_memory: list["ConfidenceMarker"] | None = None,
    ) -> list[Conflict]:
        """检测 reply 中的矛盾，返回 Conflict 列表。"""
        ...


class VsVerifiedDetector(Detector):
    """维度 1：vs F-158 Working Memory 中的已验证事实。"""

    def __init__(self, *, llm_client: object | None = None):
        self.llm = llm_client                    # 注入 LLM 客户端（可选，None 时仅做简单关键词比对）

    def detect(
        self,
        reply: str,
        *,
        history: list[dict] | None = None,
        working_memory: list["ConfidenceMarker"] | None = None,
    ) -> list[Conflict]:
        working_memory = working_memory or []
        if not working_memory:
            return []

        conflicts = []
        for marker in working_memory:
            if marker.level != "VERIFIED" or not marker.source:
                continue  # 仅与已 VERIFIED 事实比
            # 抽取 marker.claim 的关键实体（实体名 / 版本号 / 库名）
            entities = _extract_entities(marker.claim)
            # 在 reply 中查找反向断言（如 "X 不是 Y" / "X 是 Z"）
            for entity in entities:
                contradiction = _find_negation(reply, entity, expected=marker.claim)
                if contradiction:
                    conflicts.append(Conflict(
                        dimension="vs_verified",
                        claim_a=marker.claim,
                        claim_b=contradiction,
                        confidence=_estimate_confidence(marker, contradiction),
                        severity="high",
                        suggested_fix=f"保持 '{marker.claim}'（已 VERIFIED）；删去反向断言或改为'未确定'",
                        source_marker_fingerprint=marker.fingerprint or "",
                    ))
        return conflicts


class IntraReplyDetector(Detector):
    """维度 2：同一回复内前后断言的逻辑一致性。"""

    def __init__(self, *, llm_client: object | None = None):
        self.llm = llm_client

    def detect(
        self,
        reply: str,
        *,
        history: list[dict] | None = None,
        working_memory: list["ConfidenceMarker"] | None = None,
    ) -> list[Conflict]:
        # 简化启发式：按段落 / 句子拆分，提取每段的"主张"，做反向断言检测
        # 完整实现可用 LLM 或 sentence embedding
        segments = _split_into_segments(reply)
        claims = [_extract_main_claim(s) for s in segments if _extract_main_claim(s)]
        conflicts = []
        for i, claim_a in enumerate(claims):
            for j, claim_b in enumerate(claims[i + 1:], start=i + 1):
                if _is_logical_negation(claim_a, claim_b):
                    conflicts.append(Conflict(
                        dimension="intra_reply",
                        claim_a=claim_a,
                        claim_b=claim_b,
                        confidence=_estimate_intra_confidence(claim_a, claim_b),
                        severity="medium",
                        suggested_fix="二选一保留，删去另一个；或合并表述",
                        source_marker_fingerprint="",
                    ))
        return conflicts


class VsHistoryDetector(Detector):
    """维度 3：与前几轮对话断言的一致性。"""

    def __init__(self, *, llm_client: object | None = None):
        self.llm = llm_client

    def detect(
        self,
        reply: str,
        *,
        history: list[dict] | None = None,
        working_memory: list["ConfidenceMarker"] | None = None,
    ) -> list[Conflict]:
        history = history or []
        if not history:
            return []

        # 提取 history 中 Agent 的关键断言（简化：取最近 5 轮）
        prior_claims = []
        for turn in history[-5:]:
            if turn.get("role") == "assistant":
                claim = _extract_main_claim(turn.get("content", ""))
                if claim:
                    prior_claims.append(claim)

        conflicts = []
        for claim_a in prior_claims:
            contradiction = _find_negation(reply, _extract_entities(claim_a)[0] if _extract_entities(claim_a) else "", expected=claim_a)
            if contradiction:
                conflicts.append(Conflict(
                    dimension="vs_history",
                    claim_a=claim_a,
                    claim_b=contradiction,
                    confidence=_estimate_history_confidence(claim_a, contradiction),
                    severity="medium",
                    suggested_fix="回顾前几轮对话，采纳最新且正确的断言；或在答复中显式说明变更理由",
                    source_marker_fingerprint="",
                ))
        return conflicts


class ContradictionDetector:
    """三维矛盾检测器组合（F-165 核心入口）。"""

    def __init__(
        self,
        *,
        vs_verified: VsVerifiedDetector | None = None,
        intra_reply: IntraReplyDetector | None = None,
        vs_history: VsHistoryDetector | None = None,
    ):
        self.detectors: list[Detector] = [
            d for d in (vs_verified or VsVerifiedDetector(),
                        intra_reply or IntraReplyDetector(),
                        vs_history or VsHistoryDetector())
            if d is not None
        ]

    def detect(
        self,
        reply: str,
        *,
        history: list[dict] | None = None,
        working_memory: list["ConfidenceMarker"] | None = None,
    ) -> list[Conflict]:
        all_conflicts: list[Conflict] = []
        for detector in self.detectors:
            try:
                conflicts = detector.detect(
                    reply,
                    history=history,
                    working_memory=working_memory,
                )
                all_conflicts.extend(conflicts)
            except Exception as e:
                # 单维度检测器失败不应阻塞其他维度
                # 失败本身写审计日志（详见 P165-F）
                continue
        return all_conflicts


# ==== 辅助函数（简化实现） ====

def _extract_entities(claim: str) -> list[str]:
    """从 claim 抽取关键实体（专有名词 / 版本号 / 库名）。"""
    import re
    entities = []
    # 版本号（如 3.11.0）
    entities.extend(re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", claim))
    # 库名（如 FastAPI / Django / Poetry）
    entities.extend(re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", claim))
    return entities


def _find_negation(reply: str, entity: str, *, expected: str) -> str | None:
    """在 reply 中查找与 expected 反向的断言。"""
    # 简化：仅匹配明显否定句式
    import re
    negation_patterns = [
        rf"{re.escape(entity)}\s*(?:不是|并非|不会|不能)",
        rf"不\s*使用\s*{re.escape(entity)}",
        rf"{re.escape(entity)}\s*不存在",
    ]
    for pat in negation_patterns:
        m = re.search(pat, reply)
        if m:
            return m.group()
    return None


def _split_into_segments(text: str) -> list[str]:
    """按段落 / 双换行符拆分。"""
    return [s.strip() for s in re.split(r"\n\n+", text) if s.strip()]


def _extract_main_claim(segment: str) -> str | None:
    """提取段落的主张（简化：取首句）。"""
    import re
    sentences = re.split(r"[。！？\n]", segment)
    for s in sentences:
        s = s.strip()
        if 10 <= len(s) <= 200:
            return s
    return None


def _is_logical_negation(claim_a: str, claim_b: str) -> bool:
    """简化判定：包含相反关键词。"""
    neg_pairs = [
        ("使用", "不使用"), ("推荐", "不推荐"), ("可行", "不可行"),
        ("应该", "不应该"), ("可以", "不可以"), ("支持", "不支持"),
    ]
    for pos, neg in neg_pairs:
        if (pos in claim_a and neg in claim_b) or (neg in claim_a and pos in claim_b):
            # 检查是否针对同一实体
            ea = set(_extract_entities(claim_a))
            eb = set(_extract_entities(claim_b))
            if ea & eb:
                return True
    return False


def _estimate_confidence(marker, contradiction) -> float:
    return 0.85  # 简化实现：VERIFIED vs 反向 → 高置信


def _estimate_intra_confidence(claim_a: str, claim_b: str) -> float:
    return 0.7


def _estimate_history_confidence(claim_a: str, claim_b: str) -> float:
    return 0.65
```

#### 1.7.2 结构化冲突输出（P165-A 数据契约）

```python
# extensions/contradiction_detector/structured.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal


Dimension = Literal["vs_verified", "intra_reply", "vs_history"]
Severity = Literal["low", "medium", "high", "critical"]


@dataclass
class Conflict:
    """单条检测到的矛盾。"""
    dimension: Dimension                         # 哪一维度的检测器发现
    claim_a: str                                 # 第一条断言
    claim_b: str                                 # 第二条断言（与 claim_a 矛盾）
    confidence: float                            # 0.0~1.0，检测器对"这是真矛盾"的置信度
    severity: Severity                            # 矛盾严重性（用户感知）
    suggested_fix: str                           # 修订建议（给 Reviser 参考）
    source_marker_fingerprint: str = ""           # 若 dimension=vs_verified，关联 F-158 marker fingerprint

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviseResult:
    """修订循环的最终输出。"""
    decision: Literal["pass", "rewrite", "flag", "ask_user"]
    modified_reply: str                          # 处理后的 reply
    conflicts: list[Conflict]                    # 检测到的所有冲突
    action_taken: str                            # "none" / "auto_rewrite" / "flag_in_reply" / "user_prompt"

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "modified_reply": self.modified_reply,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "action_taken": self.action_taken,
        }
```

#### 1.7.3 修订器（P165-C）

```python
# extensions/contradiction_detector/reviser.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from extensions.contradiction_detector.structured import Conflict, ReviseResult

if TYPE_CHECKING:
    pass


@dataclass
class RevisePolicy:
    """修订策略：阈值 + 动作。"""
    auto_rewrite_threshold: float = 0.85           # confidence >= 此值 → 自动重写
    flag_threshold: float = 0.6                    # confidence >= 此值 → 标记冲突（不重写）
    ask_user_threshold: float = 0.4                # confidence >= 此值 → 询问用户；< 此值 → pass
    max_auto_rewrite_attempts: int = 1             # 最多重写次数（防无限循环）


class Reviser:
    """根据冲突列表 + 修订策略，决定动作。"""

    def __init__(self, policy: RevisePolicy | None = None):
        self.policy = policy or RevisePolicy()
        self._rewrite_attempts = 0

    def revise(
        self,
        reply: str,
        conflicts: list[Conflict],
        *,
        rewrite_fn=None,                              # 注入重写函数（None 时仅 flag/ask）
    ) -> ReviseResult:
        if not conflicts:
            return ReviseResult("pass", reply, [], "none")

        max_conflict = max(conflicts, key=lambda c: c.confidence)

        if max_conflict.confidence >= self.policy.auto_rewrite_threshold and self._rewrite_attempts < self.policy.max_auto_rewrite_attempts:
            # 自动重写路径
            if rewrite_fn:
                modified = rewrite_fn(reply, max_conflict)
                self._rewrite_attempts += 1
                return ReviseResult("rewrite", modified, conflicts, "auto_rewrite")
            # 无 rewrite_fn → 退化为 flag
            return self._flag(reply, conflicts)

        if max_conflict.confidence >= self.policy.flag_threshold:
            return self._flag(reply, conflicts)

        if max_conflict.confidence >= self.policy.ask_user_threshold:
            return ReviseResult(
                "ask_user", reply, conflicts,
                action_taken="user_prompt",
            )

        # 低于 ask_user_threshold → 视为误报，pass
        return ReviseResult("pass", reply, conflicts, "none")

    def _flag(self, reply: str, conflicts: list[Conflict]) -> ReviseResult:
        """在 reply 末尾追加冲突标记（不重写内容）。"""
        flag_lines = ["", "--- ⚠️ 检测到以下矛盾 ---"]
        for c in conflicts:
            flag_lines.append(
                f"- [{c.dimension}|{c.severity}|conf={c.confidence:.2f}] "
                f"\"{c.claim_a}\" ⚡ \"{c.claim_b}\""
            )
            flag_lines.append(f"  建议: {c.suggested_fix}")
        modified = reply + "\n".join(flag_lines)
        return ReviseResult("flag", modified, conflicts, "flag_in_reply")
```

#### 1.7.4 修订循环（P165-B）

```python
# extensions/contradiction_detector/loop.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from extensions.contradiction_detector.detector import ContradictionDetector
from extensions.contradiction_detector.reviser import Reviser, RevisePolicy
from extensions.contradiction_detector.structured import Conflict, ReviseResult

if TYPE_CHECKING:
    from extensions.anti_hallucination.confidence_marker import ConfidenceMarker


@dataclass
class LoopConfig:
    max_rewrite_attempts: int = 1
    detect_after_rewrite: bool = True               # 重写后再检测一次（防"重写引入新矛盾"）
    fail_open_on_detector_error: bool = True        # 检测器异常 → pass（不阻塞用户）


def detect_and_revise(
    reply: str,
    *,
    history: list[dict] | None = None,
    working_memory: list["ConfidenceMarker"] | None = None,
    detector: ContradictionDetector | None = None,
    reviser: Reviser | None = None,
    rewrite_fn=None,
    on_conflict: callable = None,
    config: LoopConfig | None = None,
) -> ReviseResult:
    """F-165 修订循环主入口。

    Args:
        reply: Agent 输出文本
        history: 对话历史
        working_memory: F-158 VERIFIED markers 列表
        detector: 矛盾检测器（None 时构造默认 3 维度实例）
        reviser: 修订器（None 时使用默认 RevisePolicy）
        rewrite_fn: 重写函数（注入 LLM 调用；None 时跳过自动重写）
        on_conflict: 冲突回调（每检测到一条调用一次，用于审计）
        config: 循环配置

    Returns:
        ReviseResult — decision + modified_reply + conflicts + action_taken
    """
    config = config or LoopConfig()
    detector = detector or ContradictionDetector()
    reviser = reviser or Reviser()

    current_reply = reply
    history = history or []
    working_memory = working_memory or []

    for attempt in range(config.max_rewrite_attempts + 1):
        # 1. 检测
        try:
            conflicts = detector.detect(
                current_reply,
                history=history,
                working_memory=working_memory,
            )
        except Exception as e:
            if config.fail_open_on_detector_error:
                return ReviseResult("pass", current_reply, [], "none")
            raise

        # 2. 回调（每条冲突一次）
        if on_conflict:
            for c in conflicts:
                try:
                    on_conflict(c)
                except Exception:
                    pass  # 回调失败不阻塞主流程

        # 3. 修订
        result = reviser.revise(
            current_reply, conflicts,
            rewrite_fn=rewrite_fn,
        )

        # 4. 决策
        if result.decision != "rewrite":
            return result

        # 5. 重写后是否再次检测？
        if not config.detect_after_rewrite:
            return result

        current_reply = result.modified_reply
        history = history + [{"role": "assistant", "content": current_reply}]  # 更新 history 让维度 3 看到新内容

    return result
```

#### 1.7.5 与 F-130 P130-A 检测器协同（P165-D）

```python
# extensions/contradiction_detector/coordinator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from extensions.self_correct.loop_detector import LoopDetector
    from extensions.contradiction_detector.detector import ContradictionDetector


@dataclass
class F130Coordinator:
    """F-165 ↔ F-130 P130-A 信号路由。

    关键设计：两者检测维度**正交不重叠**：
    - F-130 P130-A：检测"工具重复"（行为模式信号）
    - F-165：检测"语义矛盾"（内容信号）

    因此 Coordinator 主要是**信号去重**而非"任一触发"：
    - 如果 F-130 已检测到 tool repetition → F-165 不重复检测同一信号
    - 如果 F-130 未检测到但 F-165 检测到语义矛盾 → 仍正常处理
    """
    def __init__(self, *, f130_detector: "LoopDetector" | None = None):
        self.f130 = f130_detector  # F-130 P130-A LoopDetector 实例

    def should_skip_for_f130(
        self,
        history: list[dict],
        contradictions: list,
    ) -> bool:
        """判定 F-165 是否应跳过本次检测（F-130 已覆盖）。

        Returns:
            True = F-130 已覆盖相同信号，F-165 跳过（不重复）
            False = F-130 未覆盖，F-165 正常处理
        """
        if not self.f130:
            return False
        f130_signals = self.f130.detect(history)
        if not f130_signals:
            return False
        # F-130 检测到的 tool repetition 与 F-165 的语义矛盾**正交**
        # 仅当 F-130 已处理且 F-165 的冲突也属于工具重复时，才跳过
        f130_categories = {s.category for s in f130_signals}
        if "tool_repetition" in f130_categories:
            # 检查 F-165 的冲突是否完全来自工具调用
            if all(c.dimension == "intra_reply" and "调用工具" in c.claim_b for c in contradictions):
                return True
        return False
```

#### 1.7.6 触发策略（P165-E）

```python
# extensions/contradiction_detector/trigger.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DetectorTriggerPolicy:
    enabled: bool = False
    min_risk_level: RiskLevel = RiskLevel.HIGH
    min_reply_length: int = 500                   # 短回复不触发（避免噪声）
    max_reply_length: int = 20000                 # 超长回复不触发（成本控制）
    require_keywords: tuple[str, ...] = ()


# ==== 5 Profile 映射（F-130 协同） ====

PROFILE_TRIGGERS: dict[str, DetectorTriggerPolicy] = {
    "default": DetectorTriggerPolicy(
        enabled=False,                            # 默认 Profile 不启用（成本高）
        min_risk_level=RiskLevel.HIGH,
        min_reply_length=1000,
    ),
    "review": DetectorTriggerPolicy(
        enabled=True,
        min_risk_level=RiskLevel.MEDIUM,
        min_reply_length=500,
    ),
    "strict": DetectorTriggerPolicy(
        enabled=True,
        min_risk_level=RiskLevel.LOW,             # strict 连短回复也检测
        min_reply_length=100,
    ),
    "debug": DetectorTriggerPolicy(
        enabled=False,                            # debug 专注于快速修复
        min_risk_level=RiskLevel.CRITICAL,
        min_reply_length=2000,
    ),
    "creative": DetectorTriggerPolicy(
        enabled=False,                            # creative 鼓励发散
        min_risk_level=RiskLevel.CRITICAL,
        min_reply_length=2000,
    ),
}


def should_run_detector(
    context: dict,
    *,
    profile_id: str | None = None,
) -> bool:
    """判定当前上下文是否应触发矛盾检测。

    Args:
        context: {"risk_level": str, "reply": str, "intent": str}
        profile_id: 当前 F-130 Profile ID

    Returns:
        True = 启用矛盾检测
    """
    policy = PROFILE_TRIGGERS.get(profile_id or "default", PROFILE_TRIGGERS["default"])
    if not policy.enabled:
        return False

    risk = RiskLevel(context.get("risk_level", "low"))
    risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    if risk_order.index(risk) < risk_order.index(policy.min_risk_level):
        return False

    reply = context.get("reply", "")
    if not (policy.min_reply_length <= len(reply) <= policy.max_reply_length):
        return False

    intent = context.get("intent", "").lower()
    if policy.require_keywords and not any(kw.lower() in intent for kw in policy.require_keywords):
        return False

    return True
```

#### 1.7.7 Hook 集成

```python
# extensions/contradiction_detector/hooks.py
from __future__ import annotations

from typing import Any

from extensions.contradiction_detector.loop import detect_and_revise
from extensions.contradiction_detector.coordinator import F130Coordinator
from extensions.contradiction_detector.trigger import should_run_detector


def contradiction_detector_pre_reply_hook(
    reply: str,
    history: list[dict],
    *,
    working_memory: list | None = None,
    f130_detector: Any | None = None,
    rewrite_fn: Any | None = None,
    profile_id: str | None = None,
    risk_level: str = "medium",
    audit_sink: Any | None = None,
) -> dict:
    """F-102 LoopHook 集成的矛盾检测入口。

    Returns:
        {
            "decision": "pass" | "rewrite" | "flag" | "ask_user",
            "modified_reply": str,
            "conflicts": list[dict],
            "action_taken": str,
        }
    """
    context = {"risk_level": risk_level, "reply": reply, "intent": history[-1].get("content", "") if history else ""}
    if not should_run_detector(context, profile_id=profile_id):
        return {"decision": "pass", "modified_reply": reply, "conflicts": [], "action_taken": "none"}

    # 与 F-130 P130-A 协同（信号去重）
    coordinator = F130Coordinator(f130_detector=f130_detector)
    result = detect_and_revise(
        reply,
        history=history,
        working_memory=working_memory,
        rewrite_fn=rewrite_fn,
        on_conflict=lambda c: audit_sink.write(c) if audit_sink else None,
    )

    # F-130 已覆盖同信号 → 跳过
    if coordinator.should_skip_for_f130(history, result.conflicts):
        return {"decision": "pass", "modified_reply": reply, "conflicts": [], "action_taken": "f130_covered"}

    return {
        "decision": result.decision,
        "modified_reply": result.modified_reply,
        "conflicts": [c.to_dict() for c in result.conflicts],
        "action_taken": result.action_taken,
    }
```

### 1.8 核心流程

```
[Agent 输出 reply]
    ↓
[F-102 LoopHook.pre_reply 链]
    ├─→ [F-130 P130-A LoopDetector]              # 工具重复检测（已有）
    ├─→ [F-158 scan_for_unmarked_claims]         # 软警告（已有）
    ├─→ [F-162 pre_reply_interceptor]             # 硬拦截（Wave 2）
    ├─→ [F-163 red_team_critic_pre_reply_hook]    # 1v1 纵深（Wave 2）
    ├─→ [F-164 multi_perspective_pre_reply_hook]  # N 选 1 横向（Wave 2）
    └─→ [F-165 contradiction_detector_pre_reply_hook]  # 语义矛盾检测（新增）
            ├─ should_run_detector(context, profile)?
            │   ├─ False → pass（保持原 reply）
            │   └─ True → 进入检测
            │
            ├─ ContradictionDetector.detect(reply, history, working_memory):
            │   ├─ VsVerifiedDetector  → vs F-158 VERIFIED markers
            │   ├─ IntraReplyDetector  → 同一回复内前后断言
            │   └─ VsHistoryDetector   → vs 前几轮对话
            │       ↓
            │   list[Conflict]
            │
            ├─ F130Coordinator.should_skip_for_f130?
            │   ├─ True → pass（F-130 已覆盖同信号）
            │   └─ False → 继续
            │
            ├─ Reviser.revise(reply, conflicts, rewrite_fn):
            │   ├─ max(confidence) >= auto_rewrite_threshold → rewrite（注入 LLM 重写）
            │   ├─ max(confidence) >= flag_threshold → flag（追加 ⚠️ 标记到 reply 末尾）
            │   ├─ max(confidence) >= ask_user_threshold → ask_user（UI 二次确认）
            │   └─ max(confidence) < ask_user_threshold → pass（视为误报）
            ↓
    [Orchestrator 决策]:
        ├─ decision=pass → 输出原 reply
        ├─ decision=rewrite → 输出 modified_reply（自动重写）
        ├─ decision=flag → 输出 modified_reply（带 ⚠️ 标记）
        └─ decision=ask_user → 阻塞，UI 弹窗询问用户
```

### 1.9 与现有架构的对齐

| 对齐点 | 说明 |
|-------|------|
| F-130 P130-A 循环检测器 | 通过 `F130Coordinator` 信号路由避免重复检测；两者**正交**（F-130 行为模式 / F-165 内容语义） |
| F-119 Section Registry | 通过 `register_section("contradiction_detector_guide", ...)` 让模型看到三维检测规则 |
| F-102 LoopHook | 在 `pre_reply_hook` 链追加 `contradiction_detector.detect_and_revise`；位于 F-130 P130-A 之后 |
| F-158 VERIFIED facts | `VsVerifiedDetector` 消费 F-158 Working Memory 中的 `ConfidenceMarker(VERIFIED, source=...)` |
| F-163 对抗质疑器（同期 Wave 2） | F-165 检测到的语义矛盾可注入到 F-163 `counter_evidence` 字段作为反证证据 |
| F-130 Profile | `PROFILE_TRIGGERS` 5 Profile 映射：default(off)/review(on, medium)/strict(on, low)/debug(off)/creative(off) |
| 解耦 | 全部落在 `extensions/contradiction_detector/`；F-102 hook 注册在 `clawcodex_ext/hooks/_pluggy_adapter.py`；零 `src/` 侵入 |

### 1.10 风险与缓解

| 风险 | 描述 | 缓解 |
|------|------|------|
| **检测器误报** | 简单启发式（_is_logical_negation）可能误判反义/类比 | P165-A 输出 `confidence` 字段；P165-C RevisePolicy 三档阈值（auto_rewrite / flag / ask_user）；误报自然落到 ask_user 阈值以下 → pass |
| **LLM 重写引入新矛盾** | 重写后内容可能产生新的语义矛盾 | P165-B `detect_after_rewrite=True` 重写后再检测一次；`max_rewrite_attempts=1` 上限 |
| **检测成本高** | 3 维度检测 = 多次 LLM 调用 | P165-E 默认 `enabled=False`；仅 review/strict Profile 启用；`min_reply_length=500` 过滤短回复 |
| **与 F-130 重复检测** | F-130 工具重复 vs F-165 语义矛盾可能部分重叠 | P165-D `F130Coordinator` 信号路由；两者**正交**不冲突，仅在"工具调用也涉及语义矛盾"的边界 case 去重 |
| **检测器失败阻塞用户** | LLM 客户端异常 → 检测器失败 → 用户卡住 | P165-B `fail_open_on_detector_error=True`；异常时直接 pass |
| **审计日志膨胀** | 高频检测 + 长 conflict 列表 → NDJSON 膨胀 | P165-F NDJSON 追加；可配置 `audit_enabled=False`（debug / creative Profile 默认关闭） |
| **与 F-163 双倍成本** | F-163（3 轮迭代）+ F-165（3 维度检测）= 多次 LLM 调用 | Hook 链顺序：F-163 触发后才 F-165；F-163 收敛的方案 → F-165 检测"修订后是否引入新矛盾" |
| **修改回复破坏用户预期** | 自动重写可能改变 Agent 原本想表达的内容 | P165-C `auto_rewrite_threshold=0.85`（高阈值，仅"非常确信是矛盾"才自动重写）；其他情况 flag / ask_user 让用户决定 |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 说明 |
|:----:|--------|------|
| 2026-07-22 | 初始文档创建 | DC-A §4.4 映射表基础上落地 F-165 矛盾检测独立版；覆盖 DC-007 完整版（F-130 P130-A 仅覆盖工具重复维度，F-165 扩展到三维语义矛盾）；Wave 2 P1 第四个落地 F-N；与 F-130 / F-158 / F-119 / F-102 / F-163 协同；解耦落地于 `extensions/contradiction_detector/`，零 `src/` 侵入 |

### 2.2 待验证项

| 编号 | 验证项 | 关联子特性 |
|:----:|--------|:----------:|
| 1 | `VsVerifiedDetector.detect` 与 F-158 mock VERIFIED marker 测试冲突提取 | P165-A 维度1 |
| 2 | `IntraReplyDetector.detect` 同一回复内前后矛盾测试 | P165-A 维度2 |
| 3 | `VsHistoryDetector.detect` 与前几轮对话矛盾测试 | P165-A 维度3 |
| 4 | `ContradictionDetector.detect` 三维度组合：任一维度失败不阻塞其他 | P165-A |
| 5 | `Reviser.revise` auto_rewrite 路径（conf >= 0.85） | P165-C |
| 6 | `Reviser.revise` flag 路径（0.6 <= conf < 0.85） | P165-C |
| 7 | `Reviser.revise` ask_user 路径（0.4 <= conf < 0.6） | P165-C |
| 8 | `Reviser.revise` pass 路径（conf < 0.4 视为误报） | P165-C |
| 9 | `detect_and_revise` max_rewrite_attempts=1 上限 | P165-B |
| 10 | `detect_and_revise` detect_after_rewrite 重写后再检测 | P165-B |
| 11 | `detect_and_revise` fail_open_on_detector_error 异常时 pass | P165-B |
| 12 | `F130Coordinator.should_skip_for_f130` 正交去重逻辑 | P165-D |
| 13 | `PROFILE_TRIGGERS` 5 Profile 触发策略 | P165-E |
| 14 | `should_run_detector` 长度门控（min/max_reply_length） | P165-E |
| 15 | Hook 链顺序：F-130 → F-158 → F-162 → F-163 → F-164 → F-165 | 集成 |
| 16 | F-158 Working Memory 集成（mock ConfidenceMarker） | 集成 |
| 17 | F-163 counter_evidence 字段消费（冲突信号作为反证） | 集成 |
| 18 | E2E：完整检测 → 修订 → 输出 | 集成 |

---

## §3 实施细节

### 3.1 验收标准

**功能完整性**：
- [ ] 3 维度检测器（vs VERIFIED / intra-reply / vs history）各自生效
- [ ] `ContradictionDetector` 组合调用，任一维度失败不阻塞
- [ ] `Reviser` 三档阈值（auto_rewrite / flag / ask_user / pass）正确路由
- [ ] `detect_and_revise` 修订循环 + 上限 + 异常 fail-open
- [ ] `F130Coordinator` 与 F-130 P130-A 信号路由（正交不重复）
- [ ] 5 Profile 触发策略差异化生效
- [ ] NDJSON 审计日志写入

**质量门禁**：
- [ ] Stage 5 扩展测试 `extensions.contradiction_detector` 模块导入通过
- [ ] `tests/contradiction_detector/` 7 个测试用例全 PASS
- [ ] ruff check `extensions/contradiction_detector/` 无 error
- [ ] 与 F-130 集成测试无回归（两者正交不冲突）

**运营可见性**：
- [ ] UI 层可展示冲突列表（claim_a / claim_b / dimension / confidence / severity）
- [ ] flag 模式下 ⚠️ 标记在 reply 末尾可见
- [ ] ask_user 模式阻塞性 UI 弹窗
- [ ] NDJSON 审计日志可被 `jq` 查询

### 3.2 落地路径（推荐顺序）

1. **P165-A 数据契约先行** — `Conflict` / `ReviseResult` dataclass + 维度枚举
2. **P165-A 维度 1** — `VsVerifiedDetector` + mock F-158 Working Memory
3. **P165-A 维度 2** — `IntraReplyDetector` + 段落拆分 + 启发式
4. **P165-A 维度 3** — `VsHistoryDetector` + 前几轮对话扫描
5. **P165-C Reviser** — `RevisePolicy` + 三档阈值 + `_flag` 路径
6. **P165-B 修订循环** — `detect_and_revise` + `max_rewrite_attempts` + `detect_after_rewrite`
7. **P165-D 协同** — `F130Coordinator.should_skip_for_f130` 正交去重
8. **P165-E 触发策略** — `PROFILE_TRIGGERS` + `should_run_detector` + 长度门控
9. **P165-F 审计** — NDJSON 写入 + 与 F-158 / F-162 / F-163 audit schema 兼容
10. **集成到 F-102 LoopHook** — `contradiction_detector_pre_reply_hook` 注册；F-130 P130-A 信号接入
11. **集成测试** — 与 F-130 / F-158 / F-163 mock 集成；E2E 检测 → 修订 → 输出

### 3.3 与 F-130 / F-158 / F-119 / F-102 / F-163 的协同点

- **F-130 P130-A 循环检测器** → 通过 `F130Coordinator` 信号路由；两者**正交不重叠**（F-130 工具重复 / F-165 语义矛盾）
- **F-130 Profile** → `PROFILE_TRIGGERS` 5 Profile 映射：default(off)/review(on, medium)/strict(on, low)/debug(off)/creative(off)；切换 Profile 时 trigger 自动重读
- **F-158 Working Memory** → `VsVerifiedDetector` 直接消费 `ConfidenceMarker(level="VERIFIED", source=...)` 列表
- **F-158 `register_section`** → 注册 `contradiction_detector_guide` section（`order=50`，F-158 之后），让模型看到三维检测规则
- **F-119 `dump_effective_system_prompt`** → 验证 `contradiction_detector_guide` section 已注入
- **F-102 LoopHook** → P165-B 在 `pre_reply_hook` 链注册 `contradiction_detector.detect_and_revise`；位于 F-130 / F-158 / F-162 / F-163 / F-164 之后
- **F-163 对抗质疑器** → F-165 检测到的语义矛盾可注入到 F-163 `counter_evidence` 字段作为 Critic 反证证据

### 3.4 与 F-130 P130-A (工具重复) 的边界

F-165 与 F-130 P130-A **不重复**，定位互补：

| 维度 | F-130 P130-A 工具重复 | F-165 语义矛盾 |
|------|---------------------|---------------|
| 检测对象 | Agent **行为模式**（tool call 序列 / 错误模式 / 输出重复度） | Agent **内容语义**（断言间一致性） |
| 信号类型 | 工具调用 ID / 错误消息文本相似度 / 输出 hash | 关键实体（库名 / 版本号 / 状态词）的反向断言 |
| 数据源 | 运行轨迹（tool_call list / error history） | Working Memory + 对话历史 + 同一回复 |
| 检测时机 | 每个 tool call 后 / 每个错误后 | 每个 reply 输出前 |
| 修复手段 | Profile 切换（F-130 P130-D） | 自动重写 / flag / ask_user（F-165 P165-C） |
| 触发 Profile | default(review/strict) | default(off) / review(on) / strict(on) |
| Token 成本 | 轻量（无 LLM 调用） | 较重（启发式 + 可选 LLM） |

**关键差异**：F-130 让"行为卡壳"时切换 Profile；F-165 让"内容自相矛盾"时被检测/修订。两者**正交**，可同时启用且不冲突。

---

## §4 变更记录

| 日期 | 作者 | 变更 |
|:----:|------|------|
| 2026-07-22 | 起草 | 初始创建 | DC-A §4.4 映射表基础上落地 F-165 矛盾检测独立版；覆盖 DC-007 完整版（F-130 P130-A 仅覆盖工具重复维度，F-165 扩展到三维语义矛盾检测：vs VERIFIED / intra-reply / vs history）；Wave 2 P1 第四个落地 F-N；与 F-130 P130-A 信号路由协同（正交不重叠）；三档修订阈值（auto_rewrite / flag / ask_user）+ 5 Profile 触发策略 + NDJSON 审计；与 F-130 / F-158 / F-119 / F-102 / F-163 / F-164 协同；解耦落地于 `extensions/contradiction_detector/`，零 `src/` 侵入 |
