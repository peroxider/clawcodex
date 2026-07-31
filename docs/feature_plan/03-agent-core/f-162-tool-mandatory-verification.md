# F-162: 工具强制验证 — 关键事实的硬约束拦截

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-162-tool-mandatory-verification.md`
> 最后更新: 2026-07-22
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-006

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 2 P1 工具化组（中等门槛，~2-3 月可落地） |
| 覆盖 DC | DC-006 工具强制验证 |
| 前置依赖 | F-119 Section Registry + F-102 Hook 扩展点 + F-158-A ConfidenceMarker + F-159 JIT 合成 |
| 协同 | F-158 软警告（VERIFY_RULES）→ F-162 硬拦截；F-159 JIT（自动抓取）；F-130 Profile（拦截记录可作 Profile 切换依据） |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/tool_verification/`，零 `src/` 侵入 |
| 落地形态 | pre_reply_hook 拦截器 + 规则扩展集 + 例外判定器 + JIT 桥接 + 灰度开关 |

---

## §1 设计规划

### 1.1 背景

F-158 已经定义了 `VERIFY_RULES`（API 签名 / 版本号 / import 路径 / 类定义）与 `scan_for_unmarked_claims`，但**只做"软警告"**：

```python
# F-158 P158-A 的行为（仅警告）
def pre_reply_hook(reply: str, history: list[dict]) -> tuple[str, list[str]]:
    claims = scan_for_unmarked_claims(reply, history=history)
    warnings = []
    for c in claims:
        warnings.append(f"⚠️ 未经验证: '{c.claim}' 命中规则 {c.rule.tool}")
    return reply, warnings  # ← 仅返回警告，不中断
```

**问题**：警告 ≠ 拦截。当 Agent 在关键事实（API 签名 / 版本号 / 库存在性）上产生幻觉时，仅"⚠️"无法阻止其继续输出错误信息。用户在长对话中容易忽略警告。

**F-162 的定位**：把"关键事实必须经过工具验证"从**软约束（warning）** 升级为**硬约束（block）**，与 F-158 形成**双层防御**：
- F-158 软警告：所有事实主张的可信度标注（VERIFIED/INFERRED/UNCERTAIN/UNKNOWN）
- F-162 硬拦截：关键事实（API / 版本 / 库 / 路径）必须先调工具，否则 `Reply.action("verify", rule)` 强制中断

### 1.2 目标

- 让"关键事实不经工具验证"成为**默认被拦截**的行为而非"需要用户主动核查"
- 让"声称的 API 签名 / 版本号 / 库存在性"在用户侧可直接信任（VERIFIED 标签由系统保障）
- 与 F-158 软警告、F-159 JIT 自动抓取协同：拦截时**自动触发 JIT 抓取证据**，而非简单阻断
- 灰度可控：默认 `mode=warn`，关键项目可升级到 `mode=block`，普通项目不受影响

### 1.3 非目标 (Out of Scope)

- 不替代 F-158 置信度标注（仅升级其中"关键事实"维度的硬约束语义）
- 不立即扩展到非 Python 语言（先 Python → JS/Go/Rust 远期）
- 不替代 CI 静态检查（ruff / mypy）；F-162 是**运行时拦截**，CI 是**构建时拦截**
- 不做完整 "call graph 重建 + 自动 mock 工具调用"（仅在缺失工具调用时提示需调用）
- 不替代用户主动 `Verify-Run` slash command；F-162 是被动拦截，slash command 是主动核查

### 1.4 子特性分解

| 编号 | 子特性 | 覆盖 DC | 状态 | 工时 |
|:----:|--------|:-------:|:----:|:----:|
| P162-A | VERIFY_RULES 扩展集（继承 F-158） | DC-006 核心 | 📋 | 2-3d |
| P162-B | pre_reply_hook 硬拦截器 | DC-006 核心 | 📋 | 3-4d |
| P162-C | 例外清单 + 上下文判定 | DC-006 例外 | 📋 | 1-2d |
| P162-D | JIT 联动桥接（拦截时自动抓取） | DC-006 + DC-003 | 📋 | 2-3d |
| P162-E | 灰度开关 + 拦截模式 | DC-006 部署 | 📋 | 1d |
| P162-F | 拦截审计日志 | DC-006 运营 | 📋 | 1d（远期） |

### 1.5 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-119 Section Registry | **强协同** | P162-A 通过 `register_section` 注入 `tool_verification_rules` section，让模型看到当前激活规则 |
| F-102 Hook Extensions | **强协同** | P162-B 复用 F-102 的 `LoopHook.pre_reply` 拦截点；与 F-158 共用 hook 链 |
| F-158 ConfidenceMarker | **协同** | P162-A 规则集 `extends` F-158 `VERIFY_RULES`；P162-B 命中时自动建议 `[VERIFIED, source=...]` 标注 |
| F-159 JIT 合成 | **协同（核心）** | P162-D 拦截时不直接阻断，而是调用 `F-159.synthesize(target)` 自动抓取证据；抓取成功 → 补标注继续；抓取失败 → 真正拦截 |
| F-130 Profile | **协同** | P162-E 拦截模式可作 Profile 配置项（`strict` Profile 默认 `mode=block`，`default` Profile 默认 `mode=warn`） |
| F-163 对抗质疑器（Wave 2） | **下游消费者** | Critic 可引用 F-162 拦截历史作为 "claim 无验证" 的反证证据 |

### 1.6 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/tool_verification/__init__.py` | — | 子系统入口；注册 rules / interceptor / exceptions |
| `extensions/tool_verification/rules.py` | P162-A | 扩展 F-158 `VERIFY_RULES`；新增 `STRICT_RULES`（必须拦截的规则集）；规则分组（API / version / import / class / path / lib） |
| `extensions/tool_verification/interceptor.py` | P162-B | `pre_reply_interceptor(reply, history, mode)` 三档返回：pass / warn-and-rewrite / block |
| `extensions/tool_verification/exceptions.py` | P162-C | `VERIFY_EXCEPTIONS` 扩展 + `is_exception_context(text, span)` 上下文判定（含代码块 / 注释 / 示例 / 教程性陈述） |
| `extensions/tool_verification/jit_bridge.py` | P162-D | `verify_or_fetch(claim, rule, jit)` 调用 F-159 synthesize 自动抓取 |
| `extensions/tool_verification/jit_compat.py` | P162-D 适配 | `F159CompatAdapter` 把 F-159 `synthesize(intent) -> SynthesisResult` 适配为 F-162 期望的 `fetch(rule, target) -> dict` 接口；绕过 `register_section` 持久化（`scope="one_shot"` 语义）；注入 `timeout_ms` 包装 |
| `extensions/tool_verification/mode.py` | P162-E | `VerificationMode` enum（`off` / `warn` / `block` / `strict`）+ `Profile -> mode` 映射 + CLAUDE.md 配置解析 |
| `extensions/tool_verification/audit.py` | P162-F | NDJSON 拦截记录（rule / claim / decision / fetch_attempt / outcome） |
| `extensions/tool_verification/capabilities.py` | — | Protocol 接口契约（`RuleMatcher` / `Interceptor` / `ExceptionJudge` / `JITBridge`） |
| `extensions/tool_verification/hooks.py` | P162-B | 在 F-102 LoopHook 链注册 `tool_verification.intercept` |
| `tests/tool_verification/test_rules.py` | P162-A | 6 类别规则 pattern 命中测试 |
| `tests/tool_verification/test_interceptor.py` | P162-B | 三档返回行为 + history 上下文感知 |
| `tests/tool_verification/test_exceptions.py` | P162-C | 5 类例外上下文判定 |
| `tests/tool_verification/test_jit_bridge.py` | P162-D | mock F-159.synthesize，验证抓取成功 → 继续 / 抓取失败 → 拦截 |
| `tests/tool_verification/test_mode.py` | P162-E | mode 切换 + Profile 映射 |
| `tests/tool_verification/test_e2e.py` | 全部 | 端到端：输出命中规则 → 拦截器触发 → JIT 抓取 → 标注补全 → 通过 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_tool_verification_extensions()` 在 import 时注册 interceptor / JIT bridge |
| `clawcodex_ext/hooks/_pluggy_adapter.py` | 在 `pre_reply_hook` 链追加 `tool_verification.intercept`（F-158 警告 → F-162 拦截） |
| `extensions/anti_hallucination/rules.py` | `VERIFY_RULES` 标 `severity="warn"`；新增 `STRICT_RULES` 标 `severity="block"`（与 F-158 解耦的契约边界） |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.tool_verification` 模块导入断言 |
| `docs/feature_plan/README.md` | F-Number 状态总表 + 变更历史加 F-162 |
| `docs/feature_plan/dynamic-context-index.md` | DC→F 映射、依赖与全局验收总则 |

### 1.7 核心 API 设计

#### 1.7.1 规则扩展（P162-A）

```python
# extensions/tool_verification/rules.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class RuleCategory(str, Enum):
    """规则分组。"""
    API_SIGNATURE = "api_signature"     # 函数/类签名
    VERSION = "version"                  # semver 版本号
    IMPORT = "import"                    # import 路径
    LIB_EXISTENCE = "lib_existence"      # 库/包存在性
    FILE_PATH = "file_path"              # 文件路径
    CONFIG_KEY = "config_key"            # 配置项 / 字段


class RuleSeverity(str, Enum):
    """规则严重性。"""
    WARN = "warn"           # F-158 行为：仅警告
    BLOCK = "block"         # F-162 默认：必须拦截
    STRICT = "strict"       # F-162 strict 模式：即使有 tool call 也要二次验证


@dataclass
class VerifyRule:
    """强制验证规则（扩展 F-158 的 VerifyRule）。"""
    pattern: re.Pattern
    category: RuleCategory
    tool: str                       # 应当调用的工具
    reason: str                     # 拦截原因（向用户展示）
    severity: RuleSeverity = RuleSeverity.BLOCK
    allow_with_citation: bool = True  # 有 [VERIFIED, source=...] 标注时是否放行


# ==== 扩展 F-158 的 VERIFY_RULES ====

STRICT_RULES: list[VerifyRule] = [
    # API 签名（必须 Read 源文件）
    VerifyRule(
        pattern=re.compile(r"\bdef\s+\w+\s*\([^)]*\)\s*[:->]"),
        category=RuleCategory.API_SIGNATURE,
        tool="Read",
        reason="函数签名必须从源文件确认",
        severity=RuleSeverity.BLOCK,
    ),
    VerifyRule(
        pattern=re.compile(r"\bclass\s+\w+\s*[:\(]"),
        category=RuleCategory.API_SIGNATURE,
        tool="Read",
        reason="类定义必须从源文件确认",
        severity=RuleSeverity.BLOCK,
    ),
    # 版本号（必须 WebFetch）
    VerifyRule(
        pattern=re.compile(r"\b\d+\.\d+\.\d+(?:[-+][\w.]+)?"),
        category=RuleCategory.VERSION,
        tool="WebFetch",
        reason="semver 版本号必须查证官方源",
        severity=RuleSeverity.BLOCK,
    ),
    # import 路径（必须 Grep）
    VerifyRule(
        pattern=re.compile(r"^\s*(?:from\s+[\w.]+\s+)?import\s+[\w.]+", re.MULTILINE),
        category=RuleCategory.IMPORT,
        tool="Grep",
        reason="import 路径必须确认存在",
        severity=RuleSeverity.BLOCK,
    ),
    # 库名（在 claims 中提及 "项目使用 X" / "X 是依赖"）
    VerifyRule(
        pattern=re.compile(r"(?:项目|应用|代码|系统)\s*(?:使用|采用|依赖|基于)\s*([A-Z][A-Za-z0-9_-]{2,})"),
        category=RuleCategory.LIB_EXISTENCE,
        tool="Grep",
        reason="库使用声明必须 Grep 验证",
        severity=RuleSeverity.BLOCK,
    ),
    # 关键文件路径（必须 Read）
    VerifyRule(
        pattern=re.compile(r"(?:见|参考|位于|在)\s+[`/]?([\w./_-]+\.\w+)[`/]?"),
        category=RuleCategory.FILE_PATH,
        tool="Read",
        reason="文件路径引用必须确认存在",
        severity=RuleSeverity.WARN,  # 误伤率高，保留 warn
    ),
    # 配置项（必须 Read 配置文件）
    VerifyRule(
        pattern=re.compile(r"(?:配置项|环境变量|参数)\s+[`'\"]?([A-Z][A-Z_]{2,})[`'\"]?"),
        category=RuleCategory.CONFIG_KEY,
        tool="Read",
        reason="配置项名必须查证",
        severity=RuleSeverity.WARN,
    ),
]


def find_strict_claims(
    text: str,
    *,
    history: list[dict] | None = None,
    severity: RuleSeverity | None = None,
) -> list[dict]:
    """扫描文本，提取命中 BLOCK/STRICT 规则的 claim 列表。

    Args:
        text: Agent 输出文本
        history: 对话历史（用于判断该类规则是否已通过工具调用）
        severity: 限定严重性（None = 全部 BLOCK+）

    Returns:
        list of {"claim": str, "rule": VerifyRule, "start": int, "end": int}
    """
    severity = severity or RuleSeverity.BLOCK
    history = history or []
    invoked = _extract_invoked_tools(history)

    claims: list[dict] = []
    for rule in STRICT_RULES:
        if severity == RuleSeverity.BLOCK and rule.severity == RuleSeverity.WARN:
            continue
        for m in rule.pattern.finditer(text):
            # 已被工具调用过 → 跳过
            if rule.tool in invoked and not rule.allow_with_citation:
                continue
            claims.append({
                "claim": m.group(),
                "rule": rule,
                "start": m.start(),
                "end": m.end(),
            })
    return claims


def _extract_invoked_tools(history: list[dict]) -> set[str]:
    """从 history 提取已调用的工具集合。"""
    out: set[str] = set()
    for turn in history:
        tc = turn.get("tool_call") or {}
        if tc.get("name"):
            out.add(tc["name"])
    return out
```

#### 1.7.2 拦截器（P162-B）

```python
# extensions/tool_verification/interceptor.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from extensions.tool_verification.rules import (
    STRICT_RULES, RuleSeverity, VerifyRule, find_strict_claims,
)
from extensions.tool_verification.exceptions import (
    is_exception_context,
)


class InterceptDecision(str, Enum):
    PASS = "pass"               # 不拦截，原样输出
    REWRITE = "rewrite"         # 自动改写，补 VERIFIED 标注
    BLOCK = "block"             # 必须中断，要求工具调用


@dataclass
class InterceptResult:
    decision: InterceptDecision
    modified_reply: str                     # 处理后的 reply（REWRITE 时含新增标注）
    warnings: list[str]                     # 警告（给用户 / log）
    blocked_claims: list[dict]              # 被拦截的 claim 列表
    suggested_actions: list[dict]           # 建议的工具调用（BLOCK 时）


def pre_reply_interceptor(
    reply: str,
    history: list[dict],
    *,
    mode: str = "warn",
    jit_bridge: Any | None = None,          # 注入 F-159 桥接；为 None 时仅拦截不抓取
) -> InterceptResult:
    """F-162 核心拦截器。

    Args:
        reply: Agent 输出文本
        history: 对话历史
        mode: "off" / "warn" / "block" / "strict"
        jit_bridge: F-159 JIT 桥接（用于自动抓取证据）

    Returns:
        InterceptResult — 调用方根据 decision 决定放行 / 重写 / 拦截
    """
    if mode == "off":
        return InterceptResult(InterceptDecision.PASS, reply, [], [], [])

    claims = find_strict_claims(reply, history=history)
    # 过滤例外上下文
    active_claims = [
        c for c in claims
        if not is_exception_context(reply, c["start"], c["end"])
    ]

    if not active_claims:
        return InterceptResult(InterceptDecision.PASS, reply, [], [], [])

    warnings = [
        f"⚠️ '{c['claim']}' 命中规则 {c['rule'].category.value} → 应调工具 {c['rule'].tool} ({c['rule'].reason})"
        for c in active_claims
    ]

    if mode == "warn":
        return InterceptResult(
            decision=InterceptDecision.PASS,
            modified_reply=reply,
            warnings=warnings,
            blocked_claims=[],
            suggested_actions=[],
        )

    # mode == "block" / "strict"
    if jit_bridge is None:
        # 无 JIT 桥接 → 直接拦截（不自动抓取）
        return InterceptResult(
            decision=InterceptDecision.BLOCK,
            modified_reply=reply,
            warnings=warnings,
            blocked_claims=active_claims,
            suggested_actions=[
                {"tool": c["rule"].tool, "target": _infer_target(c["claim"]), "reason": c["rule"].reason}
                for c in active_claims
            ],
        )

    # 有 JIT 桥接 → 自动抓取 + 改写
    modified_reply = reply
    blocked: list[dict] = []
    for c in active_claims:
        target = _infer_target(c["claim"])
        evidence = jit_bridge.fetch(c["rule"], target)
        if evidence and evidence.get("verified"):
            # 抓取成功 → 在 claim 后追加 [VERIFIED, source=...]
            citation = f" [VERIFIED, source={evidence['tool']} {evidence['target']}]"
            modified_reply = (
                modified_reply[:c["end"]] + citation + modified_reply[c["end"]:]
            )
        else:
            # 抓取失败 → 加入 blocked
            blocked.append(c)

    if blocked:
        return InterceptResult(
            decision=InterceptDecision.BLOCK,
            modified_reply=modified_reply,
            warnings=warnings,
            blocked_claims=blocked,
            suggested_actions=[
                {"tool": c["rule"].tool, "target": _infer_target(c["claim"]), "reason": c["rule"].reason}
                for c in blocked
            ],
        )

    return InterceptResult(
        decision=InterceptDecision.REWRITE,
        modified_reply=modified_reply,
        warnings=warnings,
        blocked_claims=[],
        suggested_actions=[],
    )


def _infer_target(claim: str) -> str:
    """从 claim 抽取工具调用目标（简化：从引号/反引号中抽取）。"""
    import re
    m = re.search(r"[`'\"]([^`'\"]+)[`'\"]", claim)
    if m:
        return m.group(1)
    # 退而求其次：返回 claim 本身
    return claim.strip()
```

#### 1.7.3 例外判定（P162-C）

```python
# extensions/tool_verification/exceptions.py
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ExceptionContext:
    """例外上下文类型。"""
    is_code_block: bool = False          # 围栏代码块内
    is_inline_code: bool = False         # 行内代码（反引号包裹）
    is_comment: bool = False            # 注释行
    is_example_intent: bool = False     # 上下文出现 "示例" / "例如" / "example"
    is_tutorial_intent: bool = False    # 上下文出现 "教程" / "tutorial" / "如何"
    is_documentation: bool = False      # 上下文出现 "文档" / "documentation" / "docstring"


# 例外关键词（出现在 claim 所在行或前后 2 行）
EXAMPLE_KEYWORDS = re.compile(r"(?:示例|例子|例如|比如|如下|举个例子|example|sample|for instance|e\.g\.)", re.IGNORECASE)
TUTORIAL_KEYWORDS = re.compile(r"(?:教程|如何|怎么|步骤|tutorial|how to|step by step)", re.IGNORECASE)
DOC_KEYWORDS = re.compile(r"(?:文档|说明|手册|documentation|docs|docstring)", re.IGNORECASE)


def is_exception_context(text: str, start: int, end: int) -> bool:
    """判定 claim 所在位置是否属于例外上下文。

    Args:
        text: 完整文本
        start: claim 起始位置
        end: claim 结束位置

    Returns:
        True = 应跳过拦截（处于例外上下文）
    """
    ctx = ExceptionContext()

    # 1. 围栏代码块（``` ... ```）
    fence_spans = [
        (m.start(), m.end())
        for m in re.finditer(r"```.*?```", text, re.DOTALL)
    ]
    ctx.is_code_block = any(s <= start < e for s, e in fence_spans)

    # 2. 行内代码（`...`）
    ctx.is_inline_code = bool(re.search(r"`[^`\n]*`", text[max(0, start - 100):min(len(text), end + 100)]))

    # 3. 注释行（# 或 // 开头）
    line_start = text.rfind("\n", 0, start) + 1
    line_prefix = text[line_start:start]
    ctx.is_comment = bool(re.match(r"^\s*(?:#|//|/\*|\*)", line_prefix))

    # 4. 上下文窗口（claim 前后 200 字）检测意图关键词
    window_start = max(0, start - 200)
    window_end = min(len(text), end + 200)
    window = text[window_start:window_end]

    ctx.is_example_intent = bool(EXAMPLE_KEYWORDS.search(window))
    ctx.is_tutorial_intent = bool(TUTORIAL_KEYWORDS.search(window))
    ctx.is_documentation = bool(DOC_KEYWORDS.search(window))

    # 例外规则：
    # - 代码块 + 注释 → 永远例外
    # - 行内代码 + 示例意图 → 例外
    # - 教程意图 + 文档意图 → 例外
    if ctx.is_code_block or ctx.is_comment:
        return True
    if ctx.is_inline_code and ctx.is_example_intent:
        return True
    if ctx.is_tutorial_intent and ctx.is_documentation:
        return True
    return False
```

#### 1.7.4 JIT 联动（P162-D）

```python
# extensions/tool_verification/jit_compat.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from contextlib import contextmanager

from extensions.jit_context import synthesize, Intent  # F-159 实际入口
from extensions.tool_verification.rules import VerifyRule


@contextmanager
def _timeout_guard(timeout_ms: int):
    """F-162 自实现的超时保护（F-159 synthesize 不接受 timeout 参数）。"""
    # 简化实现：依赖 F-102 注册的 signal-based timeout；此处仅作结构示例
    try:
        yield
    except TimeoutError:
        raise


class F159CompatAdapter:
    """把 F-159 `synthesize(intent) -> SynthesisResult` 适配为 F-162 期望的 `fetch(rule, target) -> dict`。

    关键差异（F-162 与 F-159 实际签名的契约边界）：
    - F-159 接受单 positional `intent: Intent`；F-162 需要 kwargs 形式 `fetch(rule, target)`
    - F-159 默认会调用 `register_section` 持久化到 F-119；F-162 要求 `scope="one_shot"` 不持久化
    - F-159 不接受 timeout 参数；F-162 通过 `_timeout_guard` 包装注入 `timeout_ms`
    """

    def __init__(self, *, persist_to_registry: bool = False, timeout_ms: int = 5000):
        self.persist_to_registry = persist_to_registry
        self.timeout_ms = timeout_ms

    def fetch(self, rule: VerifyRule, target: str) -> dict:
        """F-162 拦截器调用的入口。返回 dict 与 interceptor._build_jit_bridge 对齐。"""
        try:
            intent = self._build_intent(rule, target)
            with _timeout_guard(self.timeout_ms):
                # 调用 F-159 实际 API（positional intent）
                result = synthesize(intent)
            # scope="one_shot" 语义：当 persist_to_registry=False 时跳过 register_section
            # （具体跳过逻辑由 F-159 在 Intent.tags 含 "tool_verification" 时识别）
            if result and getattr(result, "content", None):
                return {
                    "verified": True,
                    "tool": rule.tool,
                    "target": target,
                    "excerpt": result.content[:200],
                }
            return {"verified": False, "tool": rule.tool, "target": target,
                    "error": "JIT returned empty content"}
        except TimeoutError:
            return {"verified": False, "tool": rule.tool, "target": target,
                    "error": "JIT fetch timeout"}
        except Exception as e:
            return {"verified": False, "tool": rule.tool, "target": target,
                    "error": f"JIT fetch error: {e}"}

    def _build_intent(self, rule: VerifyRule, target: str) -> Intent:
        """根据规则类别构造 F-159 Intent dataclass（F-159 §1.7 字段）。"""
        intent_templates = {
            "api_signature": f"读取 {target} 中相关函数/类定义",
            "version": f"查证 {target} 的最新版本号",
            "import": f"在项目中确认 {target} 是否被 import",
            "lib_existence": f"在项目中确认 {target} 是否使用",
            "file_path": f"确认 {target} 文件路径是否存在",
            "config_key": f"查证配置项 {target} 的语义",
        }
        description = intent_templates.get(rule.category.value, f"查证 {target}")
        return Intent(
            description=description,
            target=target,
            tool_hint=rule.tool,
            tags=["tool_verification", rule.category.value],
        )
```

```python
# extensions/tool_verification/jit_bridge.py
from __future__ import annotations

from typing import Any

from extensions.tool_verification.rules import VerifyRule
from extensions.tool_verification.jit_compat import F159CompatAdapter


def verify_or_fetch(
    rule: VerifyRule,
    target: str,
    *,
    jit: Any | None = None,                  # 可选：注入的 F-159 兼容适配器
    timeout_ms: int = 5000,
) -> dict:
    """通过 F-159 JIT 抓取证据的高层接口（拦截器间接调用）。

    Args:
        rule: 命中的验证规则
        target: 待验证目标（如 "src/foo.py" / "https://pypi.org/project/x/"）
        jit: F-159 兼容适配器（None 时构造默认实例，scope="one_shot"）
        timeout_ms: 单次抓取超时

    Returns:
        dict {verified, tool, target, excerpt?, error?} — 与 interceptor.jit_bridge.fetch 接口对齐
    """
    bridge = jit or F159CompatAdapter(persist_to_registry=False, timeout_ms=timeout_ms)
    return bridge.fetch(rule, target)
```

#### 1.7.5 灰度策略（P162-E）

```python
# extensions/tool_verification/mode.py
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass


class VerificationMode(str, Enum):
    """F-162 拦截模式。"""
    OFF = "off"               # 完全关闭
    WARN = "warn"             # 仅警告，不拦截（F-158 默认行为）
    BLOCK = "block"           # 拦截关键事实，但允许已有 VERIFIED 标注
    STRICT = "strict"         # 即使有 VERIFIED 标注也二次验证（最严）


@dataclass
class VerificationPolicy:
    """完整拦截策略。"""
    mode: VerificationMode = VerificationMode.WARN
    enabled_categories: set[str] | None = None      # None = 全部类别
    bypass_in_examples: bool = True                  # 示例上下文 bypass
    bypass_in_documentation: bool = True             # 文档上下文 bypass
    auto_fetch_via_jit: bool = True                  # 拦截时自动 JIT 抓取
    audit_to_file: bool = False                       # 是否写审计日志


# ==== Profile → Policy 映射（F-130 协同） ====

PROFILE_POLICIES: dict[str, VerificationPolicy] = {
    "default": VerificationPolicy(
        mode=VerificationMode.WARN,
        bypass_in_examples=True,
        auto_fetch_via_jit=True,
    ),
    "strict": VerificationPolicy(
        mode=VerificationMode.BLOCK,
        bypass_in_examples=False,                      # strict 不允许示例 bypass
        auto_fetch_via_jit=True,
        audit_to_file=True,
    ),
    "review": VerificationPolicy(
        mode=VerificationMode.STRICT,
        bypass_in_examples=False,
        auto_fetch_via_jit=False,                     # review 模式不自动抓取，让 reviewer 看到原始 claim
        audit_to_file=True,
    ),
    "debug": VerificationPolicy(
        mode=VerificationMode.WARN,
        bypass_in_examples=True,
        auto_fetch_via_jit=True,
    ),
}


def policy_for_profile(profile_id: str | None) -> VerificationPolicy:
    """根据当前 Profile 获取拦截策略。"""
    if profile_id is None or profile_id not in PROFILE_POLICIES:
        return PROFILE_POLICIES["default"]
    return PROFILE_POLICIES[profile_id]


def parse_policy_from_claudemd(claudemd_text: str) -> VerificationPolicy:
    """从 CLAUDE.md 解析 tool_verification 块（YAML 片段）。"""
    import re
    m = re.search(
        r"```yaml\s*\n#\s*tool_verification\s*\n(.*?)```",
        claudemd_text,
        re.DOTALL,
    )
    if not m:
        return VerificationPolicy()
    yaml_text = m.group(1)
    # 简化解析（避免引入 yaml 依赖）
    policy = VerificationPolicy()
    for line in yaml_text.splitlines():
        line = line.strip()
        if line.startswith("mode:"):
            try:
                policy.mode = VerificationMode(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("bypass_in_examples:"):
            policy.bypass_in_examples = line.endswith("true")
        elif line.startswith("auto_fetch_via_jit:"):
            policy.auto_fetch_via_jit = line.endswith("true")
        elif line.startswith("audit_to_file:"):
            policy.audit_to_file = line.endswith("true")
    return policy
```

#### 1.7.6 Hook 集成（P162-B 注册）

```python
# extensions/tool_verification/hooks.py
from __future__ import annotations

from typing import Any

from extensions.tool_verification.interceptor import pre_reply_interceptor
from extensions.tool_verification.mode import policy_for_profile
from extensions.tool_verification.jit_bridge import verify_or_fetch


def tool_verification_pre_reply_hook(
    reply: str,
    history: list[dict],
    *,
    profile_id: str | None = None,
    jit: Any | None = None,
    policy_override: Any | None = None,
) -> dict:
    """F-102 LoopHook 集成的 pre_reply 拦截器。

    Returns:
        {
            "decision": "pass" | "rewrite" | "block",
            "reply": str,                # 可能改写后的 reply
            "warnings": list[str],
            "blocked_claims": list[dict],
            "suggested_actions": list[dict],
        }
    """
    policy = policy_override or policy_for_profile(profile_id)

    if policy.mode.value == "off":
        return {"decision": "pass", "reply": reply, "warnings": [], "blocked_claims": [], "suggested_actions": []}

    jit_bridge = _build_jit_bridge(policy, jit) if policy.auto_fetch_via_jit else None

    result = pre_reply_interceptor(
        reply,
        history,
        mode=policy.mode.value,
        jit_bridge=jit_bridge,
    )

    return {
        "decision": result.decision.value,
        "reply": result.modified_reply,
        "warnings": result.warnings,
        "blocked_claims": result.blocked_claims,
        "suggested_actions": result.suggested_actions,
    }


def _build_jit_bridge(policy, jit):
    """构造 JIT 桥接 callable（适配 interceptor.jit_bridge 接口）。"""
    if jit is None:
        return None

    class _Bridge:
        def fetch(self, rule, target):
            evidence = verify_or_fetch(rule, target, jit=jit)
            return {
                "verified": evidence.verified,
                "tool": evidence.tool,
                "target": evidence.target,
                "excerpt": evidence.excerpt,
                "error": evidence.error,
            }
    return _Bridge()
```

#### 1.7.7 审计日志（P162-F）

```python
# extensions/tool_verification/audit.py
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AuditRecord:
    """单次拦截审计记录。"""
    timestamp: float
    profile_id: str | None
    mode: str
    decision: str                              # pass / rewrite / block
    claim: str
    rule_category: str
    tool: str
    target: str
    jit_attempted: bool
    jit_verified: bool
    error: str = ""


def write_audit_record(record: AuditRecord, path: Path) -> None:
    """追加一条 NDJSON 审计记录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def default_audit_path() -> Path:
    """默认审计日志路径（~/.cache/clawcodex/tool_verification_audit.ndjson）。"""
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache / "clawcodex" / "tool_verification_audit.ndjson"
```

### 1.8 核心流程

```
[Agent 输出 reply]
    ↓
[F-102 LoopHook.pre_reply 链]
    ├─→ [F-158 scan_for_unmarked_claims]    # 软警告（已有）
    │       ↓ warnings 累积
    ├─→ [F-162 pre_reply_interceptor]        # 硬拦截（新增）
    │       ├─ mode=off → 直接 pass
    │       ├─ mode=warn → 仅追加 warnings
    │       ├─ mode=block → 命中规则后:
    │       │   ├─ 调 is_exception_context 过滤
    │       │   ├─ 剩余 claim 调 JIT bridge:
    │       │   │   ├─ verify_or_fetch 成功 → REWRITE（追加 [VERIFIED, source=...]）
    │       │   │   └─ verify_or_fetch 失败 → BLOCK（返回 suggested_actions）
    │       │   └─ jit bridge=None → 直接 BLOCK
    │       └─ mode=strict → 同 block 但不放过已有 VERIFIED 标注（强制二次验证）
    ↓
[Orchestrator 决策]:
    ├─ decision=pass → 原样输出
    ├─ decision=rewrite → 输出 modified_reply（含 VERIFIED 标注）
    └─ decision=block → 不输出 reply，先调 suggested_actions 中的工具，再回到 Agent
```

### 1.9 与现有架构的对齐

| 对齐点 | 说明 |
|-------|------|
| F-119 Section Registry | 通过 `register_section("tool_verification_rules", ...)` 让模型看到当前激活的 STRICT_RULES；可读出每条规则的 reason / 类别 |
| F-102 LoopHook | 在 `pre_reply_hook` 链追加 `tool_verification.intercept`；保留 F-158 `anti_hallucination.scan_and_verify` 在前 |
| F-158 ConfidenceMarker | F-162 的 `allow_with_citation=True` 时，有 `[VERIFIED, source=...]` 标注可放行；规则集直接 `extends` F-158 `VERIFY_RULES` 数据结构 |
| F-159 JIT 合成 | P162-D 通过 `extensions.jit_context.synthesize` 抓取证据；不持久化（`scope="one_shot"`），不污染 Section Registry |
| F-130 Profile | F-130 切换 Profile 时，hook 链自动重读 `policy_for_profile(current_profile)`；strict Profile 默认 BLOCK |
| F-118 子 agent | 不直接依赖；F-163 对抗质疑器可消费 F-162 审计日志作为 "未验证 claim" 反证 |
| 解耦 | 全部落在 `extensions/tool_verification/`；F-102 hook 注册在 `clawcodex_ext/hooks/_pluggy_adapter.py`；零 `src/` 侵入 |

### 1.10 风险与缓解

| 风险 | 描述 | 缓解 |
|------|------|------|
| **误伤正常对话** | 用户写示例代码或讨论教程时频繁触发 | P162-C 例外上下文判定（5 维：代码块 / 注释 / 示例意图 / 教程意图 / 文档意图）；P162-E 默认 `mode=warn` 不阻断 |
| **过度严格破坏响应** | `strict` 模式下每次都二次验证，token 翻倍 | P162-E 三档（warn/block/strict）+ Profile 映射；`default` Profile 默认 warn；用户可临时 `mode=off` |
| **JIT 抓取本身可能误导** | F-159 抓取的证据可能不准确 | F-162 只信任 F-159 显式 `verified=True` 字段；F-159 已通过 F-159-A `source` 引用回链 |
| **规则维护成本** | 6 类规则 regex 容易过时 | 每条规则独立 dataclass，附 `category` + `tool` + `reason`；新增规则不需改拦截器 |
| **审计日志膨胀** | strict 模式下 audit log 高速增长 | P162-F 走 NDJSON 追加；项目级 `.gitignore` 默认忽略 `~/.cache/clawcodex/` |
| **与 F-158 重复** | F-158 已做软警告，F-162 再做硬拦截可能双倍噪音 | F-162 hook 注册在 F-158 之后，warnings 仅记入 `warnings` 字段，UI 层合并展示 |
| **多语言支持滞后** | 当前 STRICT_RULES 仅覆盖 Python 风格 | P162-A 规则分组（category），未来加 `JSRuleSet` / `GoRuleSet` 即可扩展；不需改拦截器 |

---

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 说明 |
|:----:|--------|------|
| 2026-07-22 | 初始文档创建 | DC-A §4.4 映射表基础上落地 F-162 工具强制验证；覆盖 DC-006；Wave 2 P1 第一个落地；与 F-119 / F-102 / F-158 / F-159 / F-130 / F-163 协同；解耦落地于 `extensions/tool_verification/`，零 `src/` 侵入 |

### 2.2 待验证项

| 编号 | 验证项 | 关联子特性 |
|:----:|--------|:----------:|
| 1 | `STRICT_RULES` 6 类 pattern 命中预期文本与边界 case | P162-A |
| 2 | `is_exception_context` 5 维判定（代码块 / 注释 / 示例意图 / 教程意图 / 文档意图） | P162-C |
| 3 | `pre_reply_interceptor` 三档返回（pass / warn / block / strict） | P162-B |
| 4 | JIT 桥接抓取成功 → REWRITE 路径 | P162-D |
| 5 | JIT 桥接抓取失败 → BLOCK 路径 | P162-D |
| 6 | JIT 桥接未注入 → BLOCK 路径（无抓取） | P162-D |
| 7 | Profile 切换 → policy 自动重读 | P162-E |
| 8 | CLAUDE.md `tool_verification` YAML 解析 | P162-E |
| 9 | NDJSON 审计日志写入 | P162-F |
| 10 | Hook 链顺序：F-158 warnings → F-162 intercept | 集成 |
| 11 | 与 F-119 `register_section("tool_verification_rules", ...)` 集成 | 集成 |
| 12 | 与 F-130 `profile_hint` 联动（strict Profile 自动启用 BLOCK） | 集成 |
| 13 | E2E：含 F-159 JIT mock 的端到端拦截 → 抓取 → 标注 → 放行 | 集成 |

---

## §3 实施细节

### 3.1 验收标准

**功能完整性**：
- [ ] 6 类规则 pattern 命中正确（不漏报 / 不误报代码块 / 注释 / 教程上下文）
- [ ] 三档拦截模式（warn / block / strict）行为差异可见
- [ ] JIT 桥接抓取成功 → REWRITE；失败 → BLOCK；未注入 → BLOCK
- [ ] Profile 切换即时生效（`policy_for_profile` 实时查询）
- [ ] CLAUDE.md `tool_verification` YAML 解析生效

**质量门禁**：
- [ ] Stage 5 扩展测试 `extensions.tool_verification` 模块导入通过
- [ ] `tests/tool_verification/` 13 个测试用例全 PASS
- [ ] ruff check `extensions/tool_verification/` 无 error
- [ ] 与 F-158 / F-159 集成测试无回归

**运营可见性**：
- [ ] NDJSON 审计日志可被 `jq` 查询（schema 稳定）
- [ ] `warnings` 与 `blocked_claims` 在 UI 层可分别展示
- [ ] Profile 切换日志包含 F-162 policy 变更（与 F-130 协同）

### 3.2 落地路径（推荐顺序）

1. **P162-A 先行** — `STRICT_RULES` 与 `find_strict_claims` 落地，先跑纯规则扫描测试
2. **P162-C 紧随** — `is_exception_context` 实现，配合 P162-A 测试验证误伤率
3. **P162-B 拦截器** — `pre_reply_interceptor` 三档返回，先不接 JIT
4. **P162-E 灰度** — `VerificationPolicy` + `policy_for_profile` + CLAUDE.md 解析
5. **P162-D JIT 桥接** — 接入 F-159 `synthesize`，先 mock 测试后真实联调
6. **P162-F 审计** — NDJSON 写入 + `default_audit_path`
7. **集成到 F-102 LoopHook** — `tool_verification_pre_reply_hook` 注册
8. **集成测试** — F-158 warnings → F-162 intercept 顺序；F-130 Profile 切换

### 3.3 与 F-119 / F-130 / F-158 / F-159 / F-163 的协同点

- **F-119 `register_section`** → 注册 `tool_verification_rules` section，`order=40`（F-158 之后，F-160 之前），让模型看到当前激活规则
- **F-119 `dump_effective_system_prompt`** → 验证 `tool_verification_rules` section 已注入
- **F-102 LoopHook** → P162-B 在 `pre_reply_hook` 链注册 `tool_verification.intercept`；与 F-158 共用 hook 链（F-158 先 F-162 后）
- **F-158 `ConfidenceMarker`** → F-162 命中规则但已有 `[VERIFIED, source=...]` 标注时，`allow_with_citation=True` 放行
- **F-159 `synthesize`** → P162-D 通过 `F159CompatAdapter` 适配层调用 `synthesize(intent: Intent) -> SynthesisResult`；adapter 处理三处契约差异：(1) 把 `fetch(rule, target)` 转为 positional `Intent`；(2) `persist_to_registry=False` 跳过 `register_section` 持久化（`scope="one_shot"` 语义）；(3) `_timeout_guard` 包装注入 `timeout_ms`（F-159 不原生支持）
- **F-130 Profile** → `PROFILE_POLICIES` 映射表：default/warn、strict/block、review/strict、debug/warn；切换 Profile 时 policy 自动重读
- **F-163 对抗质疑器** → Critic 可读 F-162 审计日志作为 "claim 无验证" 的反证证据；P162-F audit log 是 Critic 的可消费输入

### 3.4 与 F-158 (软警告) 的边界

F-158 与 F-162 **不重复**，定位分层：

| 维度 | F-158 软警告 | F-162 硬拦截 |
|------|-------------|-------------|
| 规则 | `VERIFY_RULES`（4 类） | `STRICT_RULES`（6 类，extends F-158） |
| 行为 | 返回 warnings | 返回 decision（pass/rewrite/block） |
| 触发 | 任何未标记 claim | 命中 STRICT 规则的关键事实 |
| 默认 | 全启用 | 默认 `warn` 模式（不拦截） |
| 与模型交互 | 警告气泡 | 拦截 + suggested_actions |
| Hook 顺序 | 前置（先警告） | 后置（拦截生效） |

**关键差异**：F-158 让"所有事实主张"都可标注；F-162 让"关键事实"必须经工具验证才能输出。

---

## §4 变更记录

| 日期 | 作者 | 变更 |
|:----:|------|------|
| 2026-07-22 | 起草 | 初始创建 | DC-A §4.4 映射表基础上落地 F-162 工具强制验证；覆盖 DC-006；Wave 2 P1 第一个落地 F-N；是 F-158 软警告的硬约束升级（双层防御：F-158 标注 + F-162 拦截）；与 F-119 / F-102 / F-158 / F-159 / F-130 / F-163 协同；解耦落地于 `extensions/tool_verification/`，零 `src/` 侵入 |
