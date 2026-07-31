# F-158: 抗幻觉基线协议 — 置信度 / 否定检索 / 边界追踪

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-158-anti-hallucination-baseline.md`
> 最后更新: 2026-07-22
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-005 / DC-009 / DC-020

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 1 抗幻觉特性基线（P0，~1-2 周可落地） |
| 覆盖 DC | DC-005 置信度声明协议 + DC-009 否定式检索 + DC-020 边界追踪 |
| 前置依赖 | F-119 Section Registry + Hook 扩展点（已具备） |
| 协同 | F-130 Profile（frontier 可作 Profile 切换依据）、F-159 JIT（confidence source 引用） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/anti_hallucination/`，零 `src/` 侵入 |
| 落地形态 | CLAUDE.md / 输出风格约束 + Hook 拦截 + Working Memory 持久化 |

---

## §1 设计规划

### 1.1 背景

当前 Agent 在对话中对"事实主张"不做可靠性区分——同一个 LLM 输出里，"Python 3.11 是 stable 版本"（应为 VERIFIED）、"可能用了 Poetry 因为有 pyproject.toml"（INFERRED）、"生产部署在 K8s 上"（UNKNOWN）以同等语气呈现。用户只能靠直觉判断可信度。

**幻觉是 LLM 的结构性问题**：单靠提示词警告 + RLHF 无法消除，必须叠加运行时结构化对抗机制。F-158 把"事实主张的可靠性"提升为**一等公民行为**，通过三层防御抑制幻觉：

1. **置信度声明协议（P158-A / DC-005）** — 让模型显式标注每个事实主张的可靠程度
2. **否定式检索（P158-B / DC-009）** — 让"未使用 / 不存在"成为可证据化的断言
3. **边界追踪（P158-C / DC-020）** — 让"不知道"成为可审计的工件

### 1.2 目标

- 让"诚实地说不知道"成为 Agent 默认行为而非异常
- 让"事实主张"在用户侧可一眼分辨 VERIFIED / INFERRED / UNCERTAIN / UNKNOWN
- 让"主动查证 / 主动暴露知识缺口"可被审计、可被回归测试
- 与现有 F-119 段落拼装 + F-130 Profile 体系无缝协同，不引入新的架构概念

### 1.3 非目标 (Out of Scope)

- 不涉及模型权重 / 训练 / 微调
- 不替代任何已有 F-N 的核心实现
- 不追求 100% 标注覆盖（标注噪音会降低可读性，仅对"关键事实"标注）
- 不立即做跨会话 frontier 持久化（依赖 F-166 记忆分层，先落地会话内 Working Memory）

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖 DC | 状态 | 工时 |
|:----:|--------|:-------:|:----:|:----:|
| P158-A | 置信度声明协议 | DC-005 | 📋 | 2-3d |
| P158-B | 否定式检索 | DC-009 | 📋 | 2-3d |
| P158-C | 边界追踪 | DC-020 | 📋 | 1-2d |
| P158-D | 跨会话 frontier 持久化（依赖 F-166） | DC-020 扩展 | 📋 | 1-2d（远期） |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-119 Section Registry | **强协同** | P158-A 通过 `register_section` 注入置信度标注说明到 `anti_hallucination_guide` section |
| F-102 Hook Extensions | **强协同** | P158-A/B 的 `pre_reply_hook` 复用 F-102 的 LoopHook 拦截点 |
| F-130 Profile 体系 | **协同** | P158-C 的 frontier 可作为 Profile 切换依据（UNKNOWN 区比例 > 30% 触发 clarification Profile） |
| F-159 JIT 合成 | **下游消费者** | P158-A 的 `source` 字段引用 F-159 JIT 抓取结果 |
| F-166 记忆分层（Wave 2） | **远期** | P158-D 跨会话 frontier 持久化的存储后端 |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/anti_hallucination/__init__.py` | — | 子系统入口，注册 marker / retrieval / frontier |
| `extensions/anti_hallucination/confidence_marker.py` | P158-A | `ConfidenceMarker` dataclass + `VERIFY_RULES` + `scan_for_unmarked_claims` |
| `extensions/anti_hallucination/negative_retrieval.py` | P158-B | `extract_negation_targets` + `negative_retrieval(question)` + Grep/WebFetch 编排 |
| `extensions/anti_hallucination/frontier_tracker.py` | P158-C | `KnowledgeFrontier` dataclass + `render_frontier` + `frontier_self_check` |
| `extensions/anti_hallucination/hooks.py` | P158-A/B | `pre_reply_hook` 集成 scan + verify 拦截 |
| `extensions/anti_hallucination/output_style.py` | P158-A | CLAUDE.md / 输出风格约束片段（marker 格式定义） |
| `extensions/anti_hallucination/capabilities.py` | — | Protocol 接口契约（`ConfidenceScorer` / `NegationRetriever` / `FrontierStore`） |
| `tests/anti_hallucination/test_confidence_marker.py` | P158-A | 4 档 marker 识别 + scan 规则触发 |
| `tests/anti_hallucination/test_negative_retrieval.py` | P158-B | 问句解析 + Grep/WebFetch 调用 mock |
| `tests/anti_hallucination/test_frontier_tracker.py` | P158-C | 4 区块渲染 + self_check 拒绝 UNKNOWN 断言 |
| `tests/anti_hallucination/test_e2e.py` | 全部 | 端到端：scan → verify → marker → frontier 注入 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_anti_hallucination_extensions()` 在 import 时注册 marker / retrieval / frontier |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | 在 `pre_reply_hook` 注册 `anti_hallucination.scan_and_verify` |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.anti_hallucination` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-158 |
| `docs/feature_plan/dynamic-context-index.md` | DC→F 映射、依赖与全局验收总则 |

### 1.7 核心 API 设计

#### 1.7.1 置信度声明协议（P158-A）

```python
# extensions/anti_hallucination/confidence_marker.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Any
import re

ConfidenceLevel = Literal["VERIFIED", "INFERRED", "UNCERTAIN", "UNKNOWN"]

@dataclass
class Citation:
    """事实主张的证据来源。"""
    tool: str            # "Read" / "Grep" / "WebFetch" / "Bash"
    target: str          # 文件路径 / URL / 命令
    excerpt: str = ""    # 关键片段（前 200 字）
    timestamp: str = ""

@dataclass
class ConfidenceMarker:
    """单个事实主张的置信度声明。"""
    claim: str
    level: ConfidenceLevel
    source: Citation | None = None  # VERIFIED 必须有 source；其他 level 可选

    def render(self) -> str:
        """渲染为 markdown 标注片段。"""
        tag = f"[{self.level}]"
        if self.source:
            tag += f" (source: {self.source.tool} {self.source.target})"
        return f"{tag} {self.claim}"


# ==== 验证规则集 ====

@dataclass
class VerifyRule:
    """一类事实主张对应的强制验证规则。"""
    pattern: re.Pattern
    tool: str
    reason: str

VERIFY_RULES: list[VerifyRule] = [
    VerifyRule(
        pattern=re.compile(r"def\s+\w+\s*\("),
        tool="Read",
        reason="函数签名需从源文件确认",
    ),
    VerifyRule(
        pattern=re.compile(r"\b\d+\.\d+\.\d+\b"),
        tool="WebFetch",
        reason="semver 版本号需查证",
    ),
    VerifyRule(
        pattern=re.compile(r"^\s*import\s+[\w.]+", re.MULTILINE),
        tool="Grep",
        reason="import 路径需确认存在",
    ),
    VerifyRule(
        pattern=re.compile(r"\bclass\s+\w+\s*[:\(]"),
        tool="Read",
        reason="类定义需从源文件确认",
    ),
]

# 例外清单：这些上下文不应触发强制验证
VERIFY_EXCEPTIONS = [
    re.compile(r"^```"),                  # 代码块
    re.compile(r"# example"),             # 注释
    re.compile(r"^(localhost|127\.0\.0\.1)"),  # 本地地址
]


@dataclass
class UnmarkedClaim:
    """扫描出的无置信度标注的事实主张。"""
    claim: str
    rule: VerifyRule
    start: int
    end: int


def scan_for_unmarked_claims(
    text: str,
    *,
    history: list[dict[str, Any]] | None = None,
) -> list[UnmarkedClaim]:
    """扫描文本中的事实主张，对命中规则且无 VERIFIED 标注的 claim 返回。

    Args:
        text: Agent 输出文本
        history: 对话历史（含 tool_call 序列），用于判断该类规则是否已通过工具调用

    Returns:
        未标记的事实主张列表。调用方可选择：拦截追问 / 强制工具调用 / 接受 INFERRED 标注。
    """
    history = history or []
    invoked_tools = {t.get("tool_call", {}).get("name") for t in history}

    claims = []
    # 跳过例外清单区域
    skip_spans: list[tuple[int, int]] = []
    for line_start_match in re.finditer(r"^```.*?^```", text, re.MULTILINE | re.DOTALL):
        skip_spans.append((line_start_match.start(), line_start_match.end()))

    def in_skip(pos: int) -> bool:
        return any(s <= pos < e for s, e in skip_spans)

    for rule in VERIFY_RULES:
        for match in rule.pattern.finditer(text):
            if in_skip(match.start()):
                continue
            # 例外清单二次过滤
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_prefix = text[line_start:match.start()]
            if any(ex.match(line_prefix + match.group()) for ex in VERIFY_EXCEPTIONS):
                continue
            # 检查该 rule 对应 tool 是否在 history 中已被调用
            if rule.tool in invoked_tools:
                continue
            claims.append(UnmarkedClaim(
                claim=match.group(),
                rule=rule,
                start=match.start(),
                end=match.end(),
            ))
    return claims


def pre_reply_hook(reply: str, history: list[dict]) -> tuple[str, list[str]]:
    """Hook 实现：扫描无标注 claim，返回 (修正后 reply, 警告列表)。

    行为策略：
    - 命中规则的 claim 自动补 [VERIFIED, source=...]
    - 若工具未调用则警告但不强制中断（避免破坏用户体验）
    - 用户可在 CLAUDE.md 中将 strict_verify: true 改为强制中断
    """
    claims = scan_for_unmarked_claims(reply, history=history)
    warnings = []
    for c in claims:
        warnings.append(
            f"⚠️ 未经验证: '{c.claim}' 命中规则 {c.rule.tool} ({c.rule.reason})"
        )
    return reply, warnings
```

#### 1.7.2 否定式检索（P158-B）

```python
# extensions/anti_hallucination/negative_retrieval.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

# 识别"是否用过 / 是否支持 / 是否存在"类问句
NEGATION_PATTERNS = [
    re.compile(r"是否[用过支持存在包含依赖使用]"),
    re.compile(r"有没有\s+(?:用过|支持|用)"),
    re.compile(r"项目(?:中)?(?:是否)?(?:有|使用|采用|支持)?\s*([A-Za-z0-9_-]+)"),
    re.compile(r"does\s+(?:the\s+)?(?:project|repo|codebase)\s+(?:use|support|include)\s+([A-Za-z0-9_-]+)"),
]

@dataclass
class NegEvidence:
    """否定检索证据。"""
    target: str                # 待验证目标（如 "Poetry"）
    tool: str                  # "Grep" / "WebFetch"
    count: int                 # 命中数（0 = 不存在）
    sample: str = ""           # 第一处匹配路径或 URL
    checked_at: str = ""       # ISO 时间戳

@dataclass
class NegationAnswer:
    """否定检索结果。"""
    conclusion: str            # "未找到 X 的使用证据" 或 "找到 N 处使用"
    evidence: list[NegEvidence]
    confidence: float          # 0.0 ~ 1.0（0 命中 → 0.9；命中 → 0.5 需进一步查官方文档）

    def render(self) -> str:
        lines = [f"**结论**: {self.conclusion}", f"**置信度**: {self.confidence:.0%}", "", "**证据**:"]
        for e in self.evidence:
            lines.append(f"- `{e.target}` 工具={e.tool} 命中={e.count} 样本=`{e.sample}`")
        return "\n".join(lines)


def extract_negation_targets(question: str) -> list[str]:
    """从问句中抽取待验证目标。"""
    targets: list[str] = []
    for pat in NEGATION_PATTERNS:
        for m in pat.finditer(question):
            if m.groups():
                targets.append(m.group(1))
            else:
                # 从问句整体抽取名词短语（简化：取关键词前后 1-2 个 token）
                ctx = question[max(0, m.start() - 20):m.end() + 20]
                tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", ctx)
                targets.extend(tokens[:2])
    # 去重保持顺序
    seen: set[str] = set()
    out: list[str] = []
    for t in targets:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def negative_retrieval(
    question: str,
    *,
    grep_fn: Any = None,
    webfetch_fn: Any = None,
    scope: str = "project",
) -> NegationAnswer:
    """对每个 target 调用 Grep + 收集证据。

    Args:
        question: 用户问句
        grep_fn: 注入的 grep 函数（默认走项目内 Grep 工具）
        webfetch_fn: 注入的 webfetch 函数（用于查官方文档）
        scope: "project" / "global"

    Note:
        依赖注入而非直接 import 上游工具，保持解耦；
        Orchestrator 调用时传入真实的 grep_fn / webfetch_fn。
    """
    targets = extract_negation_targets(question)
    if not targets:
        return NegationAnswer(
            conclusion="未识别到否定类问句目标",
            evidence=[],
            confidence=0.0,
        )

    evidence: list[NegEvidence] = []
    for target in targets:
        # Grep 检索项目内
        try:
            grep_result = (grep_fn or _default_grep)(target, scope=scope)
            evidence.append(NegEvidence(
                target=target,
                tool="Grep",
                count=grep_result.match_count,
                sample=grep_result.first_match_path or "无匹配",
            ))
        except Exception:
            evidence.append(NegEvidence(target=target, tool="Grep", count=-1, sample="调用失败"))

        # 官方文档查询（可选，命中数 > 0 时跳过）
        if evidence[-1].count == 0 and webfetch_fn is not None:
            try:
                doc_result = webfetch_fn(f"{target} 官方文档")
                evidence.append(NegEvidence(
                    target=target,
                    tool="WebFetch",
                    count=1 if doc_result else 0,
                    sample=doc_result.url if doc_result else "无匹配",
                ))
            except Exception:
                pass

    all_zero = all(e.count == 0 for e in evidence if e.tool == "Grep")
    return NegationAnswer(
        conclusion="未找到目标使用证据" if all_zero else "找到目标使用证据，需人工确认",
        evidence=evidence,
        confidence=0.9 if all_zero else 0.5,
    )


def _default_grep(target: str, *, scope: str) -> Any:
    """占位实现：实际由 Orchestrator 注入真实 grep。"""
    from clawcodex_ext.tool_system.grep_bridge import project_grep
    return project_grep(target, scope=scope)
```

#### 1.7.3 边界追踪（P158-C）

```python
# extensions/anti_hallucination/frontier_tracker.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

@dataclass
class Fact:
    """已 VERIFIED 的事实。"""
    fact: str
    source: str          # 工具调用结果或文件路径
    confidence: float    # 0.0 ~ 1.0
    verified_at: str = ""

@dataclass
class Inference:
    """从可见证据推断的结论。"""
    claim: str
    basis: str           # 推断依据（如"因为有 pyproject.toml"）
    confidence: float

@dataclass
class Gap:
    """未知区域。"""
    area: str
    importance: Literal["high", "medium", "low"]
    why_needed: str = ""

@dataclass
class KnowledgeFrontier:
    """当前会话的知识边界。"""
    known: list[Fact] = field(default_factory=list)
    inferred: list[Inference] = field(default_factory=list)
    unknown: list[Gap] = field(default_factory=list)
    boundary_rules: list[str] = field(
        default_factory=lambda: [
            "不在 UNKNOWN 区断言",
            "对 INFERRED 结论标注推断依据",
            "关键事实必须先 VERIFIED 再陈述",
        ]
    )

    def update_known(self, fact: Fact) -> None:
        # 去重：同 fact 覆盖 source/confidence
        for i, existing in enumerate(self.known):
            if existing.fact == fact.fact:
                self.known[i] = fact
                return
        self.known.append(fact)

    def add_unknown(self, gap: Gap) -> None:
        self.unknown.append(gap)

    def render(self, *, max_tokens: int = 500) -> str:
        """渲染为 markdown 段落，可注入到 system prompt 末尾。"""
        lines = ["## Knowledge Frontier", ""]
        if self.known:
            lines.append("### KNOWN")
            for f in self.known[-5:]:  # 仅取最近 5 条
                lines.append(f"- [{f.confidence:.0%}] {f.fact} (src: {f.source})")
            lines.append("")
        if self.inferred:
            lines.append("### INFERRED")
            for i in self.inferred[-3:]:
                lines.append(f"- [{i.confidence:.0%}] {i.claim} (basis: {i.basis})")
            lines.append("")
        if self.unknown:
            lines.append("### UNKNOWN")
            for u in self.unknown[-5:]:
                lines.append(f"- [{u.importance}] {u.area}")
            lines.append("")
        lines.append("### BOUNDARY")
        for r in self.boundary_rules:
            lines.append(f"- {r}")
        # 简单 token 截断（按字符估算 1 token ≈ 4 chars）
        text = "\n".join(lines)
        if len(text) > max_tokens * 4:
            text = text[:max_tokens * 4] + "\n... (truncated)"
        return text


# ==== 工作记忆中的 frontier 单例 ====

_session_frontier: KnowledgeFrontier | None = None

def get_frontier() -> KnowledgeFrontier:
    global _session_frontier
    if _session_frontier is None:
        _session_frontier = KnowledgeFrontier()
    return _session_frontier

def reset_frontier() -> None:
    """新会话时调用。"""
    global _session_frontier
    _session_frontier = KnowledgeFrontier()


def frontier_self_check(claim: str) -> Literal["ALLOWED", "WARN", "BLOCK"]:
    """对照 frontier 检查 claim 是否越界。

    Returns:
        ALLOWED — claim 在 KNOWN 区
        WARN    — claim 在 INFERRED 区
        BLOCK   — claim 命中 UNKNOWN 区
    """
    frontier = get_frontier()
    # 简化匹配：包含检查
    for f in frontier.known:
        if f.fact in claim or claim in f.fact:
            return "ALLOWED"
    for i in frontier.inferred:
        if i.claim in claim or claim in i.claim:
            return "WARN"
    for u in frontier.unknown:
        if u.area in claim:
            return "BLOCK"
    return "WARN"  # 默认 WARN，提示需要补充 evidence
```

#### 1.7.4 Hook 集成（P158-A/B 联动）

```python
# extensions/anti_hallucination/hooks.py
from __future__ import annotations

from typing import Any

def install_anti_hallucination_hooks(hook_registry: Any) -> None:
    """向 F-102 LoopHook 注册 pre_reply_hook 与 post_query_hook。"""
    from .confidence_marker import pre_reply_hook as marker_hook
    from .negative_retrieval import negative_retrieval
    from .frontier_tracker import get_frontier, render_frontier

    @hook_registry.register("pre_reply_hook")
    def _scan_and_verify(reply: str, history: list[dict], **_kw: Any) -> dict:
        patched, warnings = marker_hook(reply, history)
        return {"reply": patched, "warnings": warnings}

    @hook_registry.register("post_query_hook")
    def _inject_frontier(query: str, history: list[dict], **_kw: Any) -> dict:
        """在 query 发起时把 frontier 渲染注入 system prompt。"""
        frontier = get_frontier()
        frontier_md = frontier.render()
        return {"system_prompt_appendix": frontier_md}

    @hook_registry.register("query_detected_negation")
    def _auto_negation(query: str, **_kw: Any) -> dict | None:
        """问句含否定语义时自动触发 negative_retrieval。"""
        from .negative_retrieval import extract_negation_targets
        if not extract_negation_targets(query):
            return None
        # 仅返回 metadata，由 Orchestrator 决定是否真正执行 retrieval
        return {"trigger_negation_retrieval": True, "query": query}
```

#### 1.7.5 输出风格约束（P158-A 协同）

```python
# extensions/anti_hallucination/output_style.py
"""CLAUDE.md / 输出风格中关于置信度标注的约束片段。"""

OUTPUT_STYLE_FRAGMENT = """
## 置信度标注规则

对每个事实主张必须显式标注：
- [VERIFIED] 来自刚抓取的代码 / 搜索结果
- [INFERRED] 从可见证据推断（非直接证据）
- [UNCERTAIN] 可能错，需要查证
- [UNKNOWN] 完全不知道

格式示例：
- [VERIFIED] (source: Read src/auth/login.py) def authenticate() 接受 username/password
- [INFERRED] 项目可能用 Poetry (basis: 存在 pyproject.toml)
- [UNKNOWN] 生产部署架构

仅对"关键事实"标注（API 签名、版本号、文件路径、数字、专有名词），
不对每个名词标注以避免噪音。
"""

CLAUDE_MD_FRAGMENT = """
## 抗幻觉基线（F-158 启用时追加）

1. 任何 API 签名 / 版本号 / 文件路径陈述前必须 VERIFIED
2. "是否用过 X" 类问题默认走 Grep 验证后回答
3. UNKNOWN 区不主动断言，先列出 unknown 让用户决策
4. 严格模式：strict_verify=true 时未验证 claim 被 Hook 拦截
"""
```

### 1.8 核心流程

```
[用户问句 "项目是否用了 Poetry?"]
  ↓
P158-B extract_negation_targets("是否用了 Poetry")
  → ["Poetry"]
  ↓
P158-B negative_retrieval(question)
  → Grep("Poetry", scope="project")
  → NegEvidence(count=0, sample="无匹配")
  ↓
NegationAnswer.render()
  → "**结论**: 未找到 Poetry 的使用证据"
  ↓
[Agent 在对话中引用该结论 + 标记 VERIFIED, source=Grep]
  ↓
P158-A pre_reply_hook(scan reply, history)
  → 检查 reply 中是否有其他未 VERIFIED 事实主张
  → 若有：补充 warnings 列表
  ↓
P158-C get_frontier() → render_frontier()
  → 注入 system prompt 末尾（仅会话开始 / 关键决策点刷新）
  ↓
[最终 reply 含 [VERIFIED] 标注 + 否定检索结论]
```

### 1.9 与现有架构的对齐

| 维度 | 现状 | F-158 落地后 |
|------|------|-------------|
| 事实主张可靠性 | ❌ 一视同仁 | ✅ 4 档置信度显式标注 |
| 否定类问题回答 | ❌ 模型凭印象断言 | ✅ Grep/WebFetch 证据化 |
| 知识边界 | ❌ 模型假装全知 | ✅ KNOWN/INFERRED/UNKNOWN/BOUNDARY 四区块 |
| 幻觉拦截 | ❌ 无 | ✅ pre_reply_hook scan + warnings |
| 跨会话 frontier | ❌ 无 | ✅ Working Memory 单例（F-166 落地后扩展） |
| 与 F-119 协同 | — | ✅ register_section 注入标注说明 |
| 与 F-130 协同 | — | ✅ frontier 比例驱动 Profile 切换 |
| 解耦合规 | — | ✅ 零 `src/` 改动 |

### 1.10 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 置信度标注噪音 | 输出变长，可读性下降 | 仅对"关键事实"标注，不对每个名词 |
| 强制验证误伤 | 用户写示例代码触发 | VERIFY_EXCEPTIONS 清单 + 代码块/注释豁免 |
| 模型机械打标 | 假装标注但不真信 | Hook 抽查 + 显式 source 校验（缺 source 的 [VERIFIED] 视为 [INFERRED]） |
| 否定检索对冷门库误判 | 小项目判定"不存在" | 同时检查官方文档，confidence 降至 0.5 |
| frontier 渲染占 token | 长会话膨胀 | 仅取最近 5 条 KNOWN + 3 条 INFERRED + 5 条 UNKNOWN；max_tokens 截断 |
| UNKNOWN 区块过度膨胀 | Agent 频繁声明 UNKNOWN | 用户可临时关闭 frontier 注入；Agent 主动补 KNOWN 后自动清理 UNKNOWN |
| Hook 拦截破坏用户体验 | 用户明确要"凭印象答" | CLI 开关 `anti_hallucination.strict_verify=false`；query 中含 `/no_verify` 前缀绕过 |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|----------|
| 2026-07-22 | 初始创建 | 本文档 | 与 F-130 格式对齐；映射到 DC-A §4.4 F-158 |

### 2.2 待验证项

- P158-A `ConfidenceMarker` 4 档（VERIFIED/INFERRED/UNCERTAIN/UNKNOWN）在 LLM 输出中可被正则识别（建议 5 个真实对话 sample 测试）
- `VERIFY_RULES` 不会对"用户写示例代码 / 注释 / 代码块"等场景误触发
- P158-B `extract_negation_targets` 识别中英文否定类问句（覆盖 "是否用了 / does X use / 项目中是否有"）
- P158-B `negative_retrieval` 在小项目 / 冷门库时正确给出"未找到 + 证据"，confidence 计算合理
- P158-C `KnowledgeFrontier.render_frontier` 长度可控（<500 tokens / 默认 max_tokens）
- P158-C `frontier_self_check` 对 UNKNOWN 区断言返回 BLOCK
- 稳定性门禁全量（Stage 1-5 + 7-9）通过
- Orchestrator 单元测试（排除 `manual_e2e_f38.py`）通过

---

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `ConfidenceMarker` dataclass 含 4 档 `level` + 可选 `source`，`render()` 输出符合 `[LEVEL] (source: TOOL TARGET) claim` 格式 | 📋 |
| 2 | `VERIFY_RULES` 至少 4 条规则（函数签名 / semver / import / 类定义） | 📋 |
| 3 | `scan_for_unmarked_claims` 在 reply 含 semver / 函数签名 / import 时返回，对代码块 / 注释豁免 | 📋 |
| 4 | `pre_reply_hook` 返回 `(reply, warnings)` 元组，warn 列表含完整证据 | 📋 |
| 5 | `extract_negation_targets` 对中英文否定类问句返回非空 targets | 📋 |
| 6 | `negative_retrieval` 对每个 target 调用注入的 `grep_fn`，返回 `NegationAnswer` 含完整 evidence | 📋 |
| 7 | `KnowledgeFrontier` 4 字段齐全（known/inferred/unknown/boundary_rules），支持 `update_known` / `add_unknown` | 📋 |
| 8 | `render_frontier` 输出 4 区块 markdown，含 KNOWN/INFERRED/UNKNOWN/BOUNDARY | 📋 |
| 9 | `frontier_self_check` 对 UNKNOWN 区断言返回 BLOCK | 📋 |
| 10 | 3 子特性在 `import extensions.anti_hallucination` 时自动注册 | 📋 |
| 11 | `install_anti_hallucination_hooks` 向 F-102 hook_registry 注册 3 个 hook | 📋 |
| 12 | `OUTPUT_STYLE_FRAGMENT` / `CLAUDE_MD_FRAGMENT` 文档化输出风格约束 | 📋 |
| 13 | 稳定性门禁 + 抗幻觉 E2E 测试通过 | 📋 |

### 3.2 落地路径（推荐顺序）

1. **P158-A 先行** — ConfidenceMarker + VERIFY_RULES + scan_for_unmarked_claims + pre_reply_hook 是最独立、可立即验证的子特性
2. **P158-B 紧随** — extract_negation_targets + negative_retrieval 复用 P158-A 的 grep_fn 注入
3. **P158-C 收尾** — KnowledgeFrontier + render_frontier + frontier_self_check + 工作记忆单例
4. **P158-D 远期（依赖 F-166）** — 跨会话 frontier 持久化到 Episodic Memory

### 3.3 与 F-119 / F-130 的协同点

- **F-119 `register_section`** → P158-A 通过 `register_section("anti_hallucination_guide", builder=...)` 注入标注说明
- **F-119 `dump_effective_system_prompt`** → 验证 anti_hallucination_guide 已注入
- **F-130 Profile 体系** → P158-C 的 frontier 比例（UNKNOWN / KNOWN > 30%）可作为 Profile 切换依据（暂不实现，预留接口）
- **F-102 Hook 扩展点** → P158-A/B 通过 `hook_registry.register("pre_reply_hook", ...)` 复用现有拦截点

### 3.4 与 F-159 (JIT) 的协同

- P158-A `ConfidenceMarker.source` 可引用 F-159 JIT 抓取结果（先落地 P158-A，F-159 后续接续）
- F-159 的 `RequestContext(intent, hint)` API 与 P158-B `extract_negation_targets` 形成互补：JIT 显式触发，否定检索自动触发

---

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-22 | 初始创建 | DC-A §4.4 映射表基础上落地 F-158 抗幻觉基线协议；覆盖 DC-005 置信度 + DC-009 否定检索 + DC-020 边界追踪三个 P0 高杠杆项；按 Wave 1 优先级推进 |
