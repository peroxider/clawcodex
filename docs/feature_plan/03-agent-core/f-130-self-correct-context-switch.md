# F-130: 自校正上下文切换 — 元认知"换脑"机制

> 状态: 📋 规划中
> 章节: docs/feature_plan/03-agent-core/f-130-self-correct-context-switch.md
> 最后更新: 2026-07-14
> 设计来源: F-119 动态上下文拼接基础上的元认知自校正扩展

## §1 设计规划

### 1.1 背景

当前 Agent 的上下文（system prompt）在会话启动后基本固定 — 7 个静态段 + 几个动态段在 `build_full_system_prompt_blocks()` 时一次性决定，之后无论 Agent 是否陷入循环、是否反复犯同一错误，**上下文不会自动调整**。

F-119 提供了"零件可插拔"（`register_section` / `override_section` / `unregister_section`），但缺少"零件坏了自动换"的闭环：

- **循环检测** — 缺乏对 Agent 行为模式的实时监控，不知道何时该换
- **策略 Profile** — 缺乏预定义的上下文切换方案，不知道换成什么
- **切换引擎** — 缺乏自动触发切换的机制，不知道如何换
- **Agent 自定义** — 切换策略完全硬编码则无法适应不同场景，Agent 需要能根据具体情况调整策略内容

### 1.2 目标

在 F-119 的 section registry 基础设施之上，构建一套**元认知自校正机制**，让 Agent 在检测到循环/错误时，能像人一样"换个脑子" — 以不同的上下文视角重新解题。

核心原则：

1. **不硬编码** — 策略 Profile 基于模板，Agent 可在运行时自定义调整部分内容
2. **消费 F-119** — 上下文切换本质上是批量调用 F-119 的 `register_section` / `unregister_section` / `override_section`
3. **轻量检测** — 循环检测器基于 Agent 运行轨迹的简单信号（重复 tool call、重复错误），不引入复杂 ML
4. **可扩展** — 检测器、Profile、切换策略均可注册扩展

### 1.3 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工时 |
|:----:|--------|------|:----:|:--------:|
| P130-A | 循环检测器框架 | 注册式检测器，检查 Agent 运行轨迹（tool call 序列、错误模式、输出重复度）；检测到触发信号时 emit 事件 | 📋 | 2-3d |
| P130-B | 策略 Profile 模板系统 | Profile 以模板定义（哪些 section 要覆盖/插入/禁用、tags 筛选、append_system_prompt 模板），模板含 `{{placeholders}}` 供 Agent 填充 | 📋 | 2-3d |
| P130-C | Agent 自定义调整入口 | Agent 通过 tool call 或内部 API 修改 Profile 中的占位符内容、增删 section 覆盖项、调整触发条件 | 📋 | 2-3d |
| P130-D | 上下文切换引擎 | 接收 P130-A 的切换信号，调用 F-119 API 批量卸载旧 Profile 的 section、加载新 Profile 的 section；支持切换回滚 | 📋 | 2-3d |
| P130-E | 运行轨迹分析器 | 从运行历史中提取 `last_error_summary`、`repeated_patterns`、`suggested_approach`，填充到 Profile 模板占位符 | 📋 | 1-2d |
| P130-F | 默认 Profile 集 | 内置 3-4 个策略 Profile（默认/调试/创新/回溯），通过模板系统定义，Agent 可覆盖 | 📋 | 1d |
| P130-G | 编排器集成 | Orchestrator 在 `VerificationFailed` / `HookFailedError` 时触发 P130-A 检测，必要时自动切换 Profile | 📋 | 1-2d |
| P130-H | 稳定性门禁 + 自校正 E2E 测试 | 覆盖循环检测、Profile 切换、Agent 自定义、回滚 4 条路径 | 📋 | 1-2d |

### 1.4 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-119 Section Registry | **前置** | P130-D 切换引擎直接调用 `register_section` / `unregister_section` / `override_section` / `disable_section` |
| F-119 Prompt Dump | **协同** | P130-E 轨迹分析器消费 `dump_effective_system_prompt` 获取当前上下文快照 |
| F-38 Verification + Report | **消费者** | Orchestrator 在 `VerificationFailed` 时触发 P130-A 检测 |
| F-39 Issue Re-run Labels | **协同** | `agent:retry` 标签可指定切换到的 Profile（如 `agent:retry --profile debug`） |
| F-102 Hook Extensions | **协同** | P130-D 切换引擎可作为 P102-D LoopHook 的 `pre_llm` 阶段调用源 |

### 1.5 实现文件

**新建文件**:

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `extensions/self_correct/__init__.py` | — | 子系统入口，注册默认检测器 + Profile 集 |
| `extensions/self_correct/loop_detector.py` | P130-A | `LoopDetector` 框架 + `register_detector` 注册式 API；内置 `RepeatedToolCallDetector` / `RepeatedErrorDetector` |
| `extensions/self_correct/profile_registry.py` | P130-B | `ProfileTemplate` dataclass + `register_profile` + `instantiate(template, fillers)` 模板填充 |
| `extensions/self_correct/agent_customizer.py` | P130-C | Agent 自定义调整入口：`update_profile(profile_id, overrides)` / `adjust_placeholder(key, value)` |
| `extensions/self_correct/context_switcher.py` | P130-D | `switch_to(profile_id, runtime_ctx)` 批量调用 F-119 API，记录切换历史 |
| `extensions/self_correct/trace_analyzer.py` | P130-E | `analyze_run_history(run_log)` → `RunAnalysis` 含 `last_error_summary` / `repeated_patterns` / `suggested_approach` |
| `extensions/self_correct/profiles/default.py` | P130-F | 默认 Profile 集定义 |
| `extensions/self_correct/capabilities.py` | — | Protocol 接口契约（`Detector` / `ProfileProvider` / `Customizer`） |
| `tests/self_correct/test_loop_detector.py` | P130-H | 循环检测器测试 |
| `tests/self_correct/test_profile_registry.py` | P130-H | Profile 模板填充 + 自定义测试 |
| `tests/self_correct/test_context_switcher.py` | P130-H | 切换引擎 + 回滚测试 |
| `tests/self_correct/test_e2e.py` | P130-H | 端到端：检测 → 自定义 → 切换 → 验证 |

**修改文件**:

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/__init__.py` | `install_self_correct_extensions()` 在 import 时注册默认检测器 + Profile 集 |
| `extensions/orchestrator/orchestrator.py` | 在 `VerificationFailed` catch 块中插入 `LoopDetector.feed()` + `ContextSwitcher.maybe_switch()` |
| `tests/stability_gate/test_stage5_extensions.py` | 增加 `extensions.self_correct` 模块导入断言 |
| `docs/feature_plan/README.md` | 总表 + 变更历史加入 F-130 |

### 1.6 核心 API 设计

#### 1.6.1 循环检测器框架（P130-A）

```python
# extensions/self_correct/loop_detector.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

# ==== 检测信号 ====

@dataclass
class DetectionSignal:
    """检测器发出的切换信号。"""
    detector_id: str
    signal_type: str  # "repeated_tool_call" | "repeated_error" | "stuck" | "user_trigger"
    confidence: float  # 0.0 ~ 1.0
    profile_hint: str | None = None  # 建议切换到的 Profile ID
    evidence: dict[str, Any] = field(default_factory=dict)  # 检测依据

# ==== 检测器注册 ====

_detectors: list[Callable[[list[dict[str, Any]]], DetectionSignal | None]] = []

def register_detector(
    detector: Callable[[list[dict[str, Any]]], DetectionSignal | None],
) -> None:
    """注册一个循环检测器。
    
    Args:
        detector: 接收 Agent 运行轨迹（list of turn dicts），
                  返回 DetectionSignal 或 None（无信号）。
    """
    _detectors.append(detector)

def detect(
    run_trace: list[dict[str, Any]],
) -> DetectionSignal | None:
    """遍历所有检测器，返回置信度最高的信号（或 None）。"""
    best: DetectionSignal | None = None
    for detector in _detectors:
        try:
            signal = detector(run_trace)
            if signal is not None:
                if best is None or signal.confidence > best.confidence:
                    best = signal
        except Exception:
            pass
    return best


# ==== 内置检测器 ====

def _repeated_tool_call_detector(trace: list[dict]) -> DetectionSignal | None:
    """检测相同 tool call 参数序列重复 ≥3 次。"""
    if len(trace) < 3:
        return None
    recent = trace[-3:]
    # 检查最近的 tool call 是否相同
    calls = [t.get("tool_call", {}) for t in recent if "tool_call" in t]
    if len(calls) < 3:
        return None
    if calls[0] == calls[1] == calls[2]:
        return DetectionSignal(
            detector_id="repeated_tool_call",
            signal_type="repeated_tool_call",
            confidence=0.8,
            profile_hint="debug",
            evidence={"pattern": calls[0], "count": 3},
        )
    return None

def _repeated_error_detector(trace: list[dict]) -> DetectionSignal | None:
    """检测相同错误反复出现。"""
    errors = [t for t in trace if t.get("error")]
    if len(errors) < 2:
        return None
    # 比较最近两次错误
    if errors[-1].get("error") == errors[-2].get("error"):
        return DetectionSignal(
            detector_id="repeated_error",
            signal_type="repeated_error",
            confidence=0.7,
            profile_hint="debug",
            evidence={"error": errors[-1]["error"], "count": len(errors)},
        )
    return None
```

#### 1.6.2 策略 Profile 模板系统（P130-B）

```python
# extensions/self_correct/profile_registry.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class ProfileTemplate:
    """策略 Profile 模板 — 不完全硬编码，含占位符和自定义点。
    
    Agent 可通过 P130-C 的 ``adjust_placeholder`` 在运行时填充/修改
    占位符内容，实现"Agent 自定义调整部分内容"。
    """
    id: str
    name: str
    description: str
    
    # section 覆盖：{section_id: content_template | None}
    # None = 禁用该段，str 含 {{placeholder}} 占位符
    section_overrides: dict[str, str | None] = field(default_factory=dict)
    
    # 新插入的 section：{new_id: insert_config}
    # insert_config = {content_template, after_id, cache_scope}
    insert_sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    
    # tags 筛选：只包含匹配这些 tags 的注册 section
    tags_filter: list[str] = field(default_factory=list)
    
    # 追加到末尾的系统提示模板（含 {{placeholder}}）
    append_system_prompt_template: str | None = None
    
    # 自定义占位符默认值
    placeholders: dict[str, str] = field(default_factory=dict)
    
    # 切换触发条件：匹配哪些 signal_type 时自动建议切换到本 Profile
    trigger_signals: list[str] = field(default_factory=list)


_profiles: dict[str, ProfileTemplate] = {}

def register_profile(profile: ProfileTemplate) -> None:
    """注册一个策略 Profile。"""
    _profiles[profile.id] = profile

def get_profile(profile_id: str) -> ProfileTemplate | None:
    return _profiles.get(profile_id)

def list_profiles() -> list[ProfileTemplate]:
    return list(_profiles.values())

def instantiate(
    template: ProfileTemplate,
    fillers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """将模板实例化为具体的切换指令。
    
    合并默认占位符与传入填充值，替换所有 {{placeholder}}。
    """
    resolved = dict(template.placeholders)
    if fillers:
        resolved.update(fillers)
    
    def _fill(text: str) -> str:
        for key, value in resolved.items():
            text = text.replace("{{" + key + "}}", value)
        return text
    
    section_overrides = {
        sid: _fill(content) if content is not None else None
        for sid, content in template.section_overrides.items()
    }
    insert_sections = {
        nid: {k: _fill(v) if isinstance(v, str) else v for k, v in cfg.items()}
        for nid, cfg in template.insert_sections.items()
    }
    append_text = (
        _fill(template.append_system_prompt_template)
        if template.append_system_prompt_template
        else None
    )
    
    return {
        "profile_id": template.id,
        "section_overrides": section_overrides,
        "insert_sections": insert_sections,
        "tags_filter": template.tags_filter,
        "append_system_prompt": append_text,
    }
```

#### 1.6.3 Agent 自定义调整入口（P130-C）

```python
# extensions/self_correct/agent_customizer.py
"""Agent 可在运行时通过此 API 调整 Profile 的内容。

使用方式：
  1. Agent 通过 tool call 调用 ``adjust_profile_placeholder``
  2. 或 Agent 在对话中自然指出问题，由编排器解析后调用
  3. 调整仅在当前会话生效，不影响 Profile 模板定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class SessionProfileOverride:
    """当前会话的 Profile 自定义覆盖。
    
    与 ProfileTemplate 分离：模板是类定义，这里是实例级别的调整。
    """
    profile_id: str
    # 自定义占位符值（覆盖模板中的默认值）
    placeholders: dict[str, str] = field(default_factory=dict)
    # 额外添加的 section 覆盖（追加到模板已有的 section_overrides 之上）
    extra_overrides: dict[str, str | None] = field(default_factory=dict)
    # 禁用模板中的某些 section（默认不启用）
    disabled_sections: set[str] = field(default_factory=set)
    # 额外追加到末尾的提示文本
    extra_append: str | None = None

_session_overrides: dict[str, SessionProfileOverride] = {}

def adjust_placeholder(
    profile_id: str,
    key: str,
    value: str,
) -> None:
    """Agent 自定义调整一个占位符（如 ``last_error_summary``）。"""
    if profile_id not in _session_overrides:
        _session_overrides[profile_id] = SessionProfileOverride(profile_id=profile_id)
    _session_overrides[profile_id].placeholders[key] = value

def add_override(
    profile_id: str,
    section_id: str,
    content: str | None,
) -> None:
    """Agent 额外添加/禁用某个 section 的覆盖。"""
    if profile_id not in _session_overrides:
        _session_overrides[profile_id] = SessionProfileOverride(profile_id=profile_id)
    _session_overrides[profile_id].extra_overrides[section_id] = content

def disable_section_in_profile(
    profile_id: str,
    section_id: str,
) -> None:
    """Agent 禁用 Profile 中的某个 section。"""
    if profile_id not in _session_overrides:
        _session_overrides[profile_id] = SessionProfileOverride(profile_id=profile_id)
    _session_overrides[profile_id].disabled_sections.add(section_id)

def get_merged_profile(
    profile_id: str,
    runtime_fillers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """合并模板定义 + 会话自定义覆盖，返回最终的切换指令。
    
    这是切换引擎实际调用的函数。
    """
    from .profile_registry import get_profile, instantiate
    
    template = get_profile(profile_id)
    if template is None:
        raise ValueError(f"Unknown profile: {profile_id}")
    
    override = _session_overrides.get(profile_id)
    
    # 合并占位符：模板默认值 → 会话自定义 → 运行时填充
    fillers = dict(template.placeholders)
    if override:
        fillers.update(override.placeholders)
    if runtime_fillers:
        fillers.update(runtime_fillers)
    
    # 实例化模板
    instance = instantiate(template, fillers)
    
    # 应用会话自定义覆盖
    if override:
        for sid, content in override.extra_overrides.items():
            instance["section_overrides"][sid] = content
        for sid in override.disabled_sections:
            instance["section_overrides"][sid] = None
        if override.extra_append:
            existing = instance.get("append_system_prompt") or ""
            instance["append_system_prompt"] = existing + "\n\n" + override.extra_append
    
    return instance
```

#### 1.6.4 上下文切换引擎（P130-D）

```python
# extensions/self_correct/context_switcher.py
"""切换引擎：接收检测信号，执行上下文切换。

通过 F-119 的 API 实现实际的 section 卸载/加载。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class SwitchRecord:
    """一次上下文切换的记录。"""
    timestamp: str
    from_profile: str | None  # None = 初始状态
    to_profile: str
    trigger: str  # signal_type
    rollback_possible: bool = True

_switch_history: list[SwitchRecord] = []
_current_profile: str | None = None

def switch_to(
    profile_id: str,
    runtime_ctx: dict[str, Any] | None = None,
    *,
    trigger: str = "manual",
) -> dict[str, Any]:
    """切换到指定 Profile。
    
    1. 通过 ``get_merged_profile`` 获取最终切换指令
    2. 调用 F-119 API 执行切换
    3. 记录切换历史
    """
    from .agent_customizer import get_merged_profile
    from clawcodex_ext.context_system.section_registry import (
        register_section,
        unregister_section,
    )
    from clawcodex_ext.context_system.section_override import (
        override_section,
        disable_section,
    )
    
    # 获取合并后的切换指令
    instance = get_merged_profile(profile_id, runtime_fillers={
        k: str(v) for k, v in (runtime_ctx or {}).items()
        if isinstance(v, (str, int, float))
    })
    
    # 记录当前 Profile（用于回滚）
    global _current_profile
    from_profile = _current_profile
    
    # 执行切换：section overrides
    for section_id, content in instance.get("section_overrides", {}).items():
        if content is None:
            disable_section(section_id)
        else:
            override_section(section_id, content, reason=f"self-correct switch to {profile_id}")
    
    # 执行切换：插入新 section
    for new_id, cfg in instance.get("insert_sections", {}).items():
        from clawcodex_ext.context_system.section_registry import register_section
        register_section(
            new_id,
            builder=lambda _ctx, c=cfg.get("content", ""): c,
            order=cfg.get("order", 55),
            cache_scope=cfg.get("cache_scope", "session"),
            tags=cfg.get("tags", ["self-correct"]),
        )
    
    # 记录切换
    _current_profile = profile_id
    import datetime
    record = SwitchRecord(
        timestamp=datetime.datetime.utcnow().isoformat(),
        from_profile=from_profile,
        to_profile=profile_id,
        trigger=trigger,
    )
    _switch_history.append(record)
    
    return instance

def rollback() -> dict[str, Any] | None:
    """回滚到上一个 Profile。"""
    if len(_switch_history) < 2:
        return None
    # 找到上一个可回滚的切换
    for i in range(len(_switch_history) - 2, -1, -1):
        prev = _switch_history[i]
        if prev.rollback_possible:
            return switch_to(prev.to_profile, trigger="rollback")
    return None

def get_history() -> list[SwitchRecord]:
    return list(_switch_history)
```

#### 1.6.5 运行轨迹分析器（P130-E）

```python
# extensions/self_correct/trace_analyzer.py
"""分析 Agent 运行历史，提取用于 Profile 占位符填充的信息。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class RunAnalysis:
    """运行轨迹分析结果。"""
    last_error_summary: str = ""
    repeated_patterns: list[str] = field(default_factory=list)
    suggested_approach: str = ""
    changed_files: list[str] = field(default_factory=list)
    verification_count: int = 0
    failure_count: int = 0

def analyze_run_history(
    run_log: list[dict[str, Any]],
    *,
    max_errors: int = 3,
) -> RunAnalysis:
    """分析运行历史，提取关键信息供 Profile 占位符使用。
    
    分析结果会被填充到 Profile 模板的 ``{{last_error_summary}}``、
    ``{{repeated_patterns}}``、``{{suggested_approach}}`` 等占位符中。
    """
    analysis = RunAnalysis()
    
    errors = [t for t in run_log if t.get("error") or t.get("verification") == "failed"]
    analysis.failure_count = len(errors)
    analysis.verification_count = sum(
        1 for t in run_log if t.get("verification") is not None
    )
    
    if errors:
        # 提取最近错误的摘要
        recent = errors[-max_errors:]
        summary_parts = []
        for e in recent:
            err_msg = e.get("error", "") or e.get("verification_output", "")
            if err_msg:
                summary_parts.append(f"- {err_msg[:200]}")
        analysis.last_error_summary = "\n".join(summary_parts)
        
        # 检测重复模式
        from collections import Counter
        error_texts = [e.get("error", "") or e.get("verification_output", "")[:50] for e in errors]
        repeated = [text for text, count in Counter(error_texts).items() if count >= 2]
        analysis.repeated_patterns = repeated
        
        # 建议方向
        if analysis.failure_count >= 3:
            analysis.suggested_approach = (
                "当前方案已尝试多次未成功，建议从完全不同方向重新分析根因，"
                "不要在前几次尝试的基础上打补丁。"
            )
        elif analysis.verification_count > 0:
            analysis.suggested_approach = (
                "验证失败，建议先确认测试环境是否正确，再逐行检查改动。"
            )
    
    return analysis
```

#### 1.6.6 默认 Profile 集（P130-F）

```python
# extensions/self_correct/profiles/default.py
from extensions.self_correct.profile_registry import ProfileTemplate, register_profile

# ==== Profile: 默认（标准编码脑）====
register_profile(ProfileTemplate(
    id="default",
    name="标准模式",
    description="默认编码上下文，不做特殊调整。",
    section_overrides={},
    tags_filter=[],
    trigger_signals=[],
))

# ==== Profile: 调试（debug 脑）====
register_profile(ProfileTemplate(
    id="debug",
    name="调试模式",
    description="Agent 反复犯错时切换 — 慢下来、仔细检查、逐步验证。",
    section_overrides={
        "tone_style": (
            "## 谨慎模式\n"
            "慢慢来，仔细检查每一步。在做出任何修改前，先确认理解正确。"
        ),
        "doing_tasks": (
            "## 调试策略\n"
            "1. 先确认问题复现条件，确保能稳定复现\n"
            "2. 每次只改一个地方，改完后立即验证\n"
            "3. 如果同一个测试连续失败 {{max_retries}} 次，停下来重新分析根因\n"
            "4. 不要重复同样的尝试 — 新方案必须解释为什么之前的方案无效\n"
            "5. 输出完整的推理过程，不要省略中间步骤"
        ),
        "output_efficiency": (
            "## 可读性优先\n"
            "输出完整的推理过程，不要省略中间步骤。"
        ),
    },
    append_system_prompt_template=(
        "<system-reminder>\n"
        "## 上一轮教训\n"
        "{{last_error_summary}}\n\n"
        "## 重复模式\n"
        "{{repeated_patterns}}\n\n"
        "## 本次规则\n"
        "- 不要重复同样的尝试\n"
        "- 在尝试新方案之前，先解释为什么之前的方案无效\n"
        "- 如果仍然不确定，列出至少 3 种可能的根因并逐一排除\n"
        "</system-reminder>"
    ),
    placeholders={
        "max_retries": "3",
        "last_error_summary": "无",
        "repeated_patterns": "无",
    },
    trigger_signals=["repeated_tool_call", "repeated_error", "stuck"],
))

# ==== Profile: 创新（creative 脑）====
register_profile(ProfileTemplate(
    id="creative",
    name="发散模式",
    description="常规思路走不通时切换 — 从完全不相关方向思考。",
    section_overrides={
        "doing_tasks": (
            "## 发散思维\n"
            "从完全不相关的方向思考，欢迎非常规方案。\n\n"
            "### 强制换框\n"
            "1. 写出当前正在尝试的方案（已经试过的）\n"
            "2. 写出至少 3 个完全不同的方向\n"
            "3. 选择最不可能成功的方向，解释为什么它可能有效\n"
            "4. 如果新方向又失败，回到步骤 2"
        ),
        "tone_style": (
            "## 大胆尝试\n"
            "不追求完美，优先探索可能性。先跑通，再优化。"
        ),
    },
    tags_filter=["exploration", "alternatives"],
    placeholders={
        "last_error_summary": "无",
    },
    trigger_signals=["stuck", "creative_requested"],
))

# ==== Profile: 回溯（review 脑）====
register_profile(ProfileTemplate(
    id="review",
    name="回溯模式",
    description="需要系统性地回顾和整理已有信息时切换。",
    section_overrides={
        "doing_tasks": (
            "## 回溯策略\n"
            "1. 先列出所有已收集的信息和已做的尝试\n"
            "2. 检查是否有遗漏的关键信息\n"
            "3. 从 Issue/PR 描述重新读起，确认理解正确\n"
            "4. 逐条比对需求和实现，找出差异"
        ),
        "output_efficiency": (
            "## 完整性优先\n"
            "对于每个发现，列出依据和来源。"
        ),
    },
    tags_filter=["review", "analysis"],
    trigger_signals=["stuck", "user_trigger"],
))
```

### 1.7 核心切换流程

```
[Agent 运行轨迹] → P130-A LoopDetector.detect(trace)
                         │
                         ▼ 检测到信号
              ┌─ signal_type: "repeated_error"
              │  confidence: 0.8
              │  profile_hint: "debug"
              │
              ▼
         P130-E TraceAnalyzer.analyze_run_history(run_log)
              │
              │  → last_error_summary: "AssertionError: ..."
              │  → repeated_patterns: ["test_create_user failed"]
              │  → suggested_approach: "重新分析根因"
              │
              ▼
         P130-C Agent 可在此调整
              │  adjust_placeholder("debug", "last_error_summary", ...)
              │  add_override("debug", "tone_style", "## 更谨慎...")
              │
              ▼
         P130-D ContextSwitcher.switch_to("debug", runtime_ctx)
              │
              │  1. get_merged_profile("debug", fillers) ← 合并模板+自定义
              │  2. override_section("tone_style", new_content)    ← F-119 API
              │  3. override_section("doing_tasks", debug_content) ← F-119 API
              │  4. override_section("output_efficiency", ...)    ← F-119 API
              │  5. register_section("self_correct_reminder", ...) ← F-119 API
              │
              ▼
         [下次 query 开始，Agent 使用新上下文]
              │
              ▼ 如果再次失败
         P130-D ContextSwitcher.rollback()
              │  → 回到上一个 Profile
              │  → 或者尝试下一个 Profile（creative）
              ▼
         [继续执行]
```

### 1.8 与现有架构的对齐

| 维度 | 现状 | F-130 落地后 |
|------|------|-------------|
| 上下文切换 | ❌ 无 | ✅ 检测→分析→切换闭环 |
| 循环检测 | ❌ 无 | ✅ 注册式检测器框架 |
| 策略 Profile | ❌ 硬编码固定上下文 | ✅ 模板 + Agent 自定义 |
| 占位符填充 | ❌ 无 | ✅ `{{placeholder}}` 模板系统 |
| Agent 自定义 | ❌ 无 | ✅ `adjust_placeholder` / `add_override` |
| 切换历史 | ❌ 无 | ✅ `SwitchRecord` + rollback |
| 编排器集成 | ❌ 无 | ✅ `VerificationFailed` → 自动切换 |
| 依赖 F-119 | — | ✅ 直接消费 F-119 API |
| 解耦合规 | ✅ | ✅ 新增代码全在 `extensions/self_correct/` |

### 1.9 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 循环检测假阳性 | 不该切换时切换，可能打断正常工作的 Agent | 检测器返回 `confidence` 分数，引擎只在 `>=0.7` 时自动切换；低分只记录不行动 |
| Profile 模板占位符过多 | Agent 需要填充大量占位符，认知负担重 | 默认值保底；只暴露最关键的 2-3 个占位符（`last_error_summary`、`repeated_patterns`）；其余靠模板默认值 |
| Agent 自定义覆盖破坏 Profile 效果 | Agent 调整了关键 section 导致 Profile 失效 | 回滚能力（`rollback()`）可在自定义过度时恢复；切换历史可审计 |
| 频繁切换导致上下文震荡 | 短时间内多次切换，Agent 行为不稳定 | 冷却期：切换后 N 轮内不再自动切换（默认 5 轮）；手动切换不受限 |
| 与 F-119 的解耦依赖强耦合 | 如果 F-119 API 变更，切换引擎需要适配 | 切换引擎仅依赖 F-119 的 `register_section` / `unregister_section` / `override_section` / `disable_section` 四个函数，适配层薄 |

## §2 进度跟踪

### 2.1 已完成里程碑

| 日期 | 里程碑 | 涉及文件 | 验证方式 |
|------|--------|---------|---------|
| 2026-07-14 | 初始创建 | 本文档 | 与 F-119 格式对齐 |

### 2.2 待验证项

- P130-A 循环检测器在正常执行时零假阳性（benchmark 10 轮正常交互）
- Profile 模板 `{{placeholder}}` 填充在缺失键时优雅降级（保留原始文本）
- `ContextSwitcher.rollback()` 在连续切换 3 次后仍能正确回滚
- `TraceAnalyzer` 在空轨迹/无错误轨迹下不抛异常
- 稳定性门禁全量（Stage 1-5 + 7-9）通过
- Orchestrator 单元测试（排除 manual_e2e_f38.py）通过

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `register_detector(fn)` 后，`detect(trace)` 调用 fn 并返回合理的 DetectionSignal | 📋 |
| 2 | `_repeated_tool_call_detector` 在 3 次相同 tool_call 时返回 signal，不足时不返回 | 📋 |
| 3 | `ProfileTemplate` 含 `{{placeholder}}` 的模板通过 `instantiate` 填充后正确替换 | 📋 |
| 4 | `adjust_placeholder("debug", "last_error_summary", "msg")` 后，`get_merged_profile` 返回的 append_system_prompt 包含该内容 | 📋 |
| 5 | `switch_to("debug", runtime_ctx)` 调用后，F-119 注册表中 debug Profile 的 section 覆盖生效 | 📋 |
| 6 | `rollback()` 恢复到上一个 Profile，且不中断当前会话 | 📋 |
| 7 | `TraceAnalyzer.analyze_run_history` 在有/无错误时均正常返回 | 📋 |
| 8 | 默认 Profile 集（default / debug / creative / review）在 import 时自动注册 | 📋 |
| 9 | 编排器在 `VerificationFailed` 时自动触发 `LoopDetector.detect()` | 📋 |
| 10 | 稳定性门禁 + 自校正 E2E 测试通过 | 📋 |

### 3.2 落地路径（推荐顺序）

1. **P130-B（Profile 模板系统）+ P130-F（默认 Profile 集）先行** — 定义模板数据结构和内置 Profile，不依赖检测器
2. **P130-C（Agent 自定义调整入口）落地** — Agent 可手动调整 Profile 占位符，验证模板系统灵活性
3. **P130-E（轨迹分析器）落地** — 为占位符填充提供数据源
4. **P130-D（上下文切换引擎）落地** — 基于 F-119 API 实现切换逻辑，**此时 Agent 可手动触发切换**
5. **P130-A（循环检测器框架）落地** — 实现自动检测，完成闭环
6. **P130-G（编排器集成）落地** — 在 Orchestrator 的 `VerificationFailed` 路径中插入自动切换
7. **P130-H（测试 + 门禁）全程伴随** — 每个 P130-X 落地后立即补测试

### 3.3 与 F-119 的协同点

- **F-119 的 `register_section`** → P130-D 切换引擎批量注册新 section
- **F-119 的 `unregister_section`** → P130-D 切换前卸载旧 Profile 的 section
- **F-119 的 `override_section`** → P130-D 覆盖 Profile 中指定的 section
- **F-119 的 `disable_section`** → P130-D 禁用 Profile 中不需要的 section
- **F-119 的 `dump_effective_system_prompt`** → P130-E 轨迹分析器获取当前上下文快照

**与 F-39 的协同**：
- `agent:retry --profile debug` 命令行显式指定 Profile
- `agent:follow-up` 保留当前 Profile 继续执行

## §4 DC-A 补充分解：模式与继承链

本节将 DC-001、DC-002 中未被 P130-A~H 覆盖的语义纳入 F-130，避免另开重复 F-Number。

| 编号 | 子特性 | 实施范围 | 验收 |
|------|--------|----------|------|
| P130-I | ContextNode 继承链 | `Global → Task → Subtask → Loop` 四层运行时实例；子级按 section id 覆盖父级 | 最大深度 3；`effective_sections()` 顺序稳定；子级销毁不修改父级 |
| P130-J | Mode Stack 与冲突策略 | named Mode、工具 allow/deny、知识锚点、样式和显式优先级 | 冲突可解释；deny 始终优先；默认仅允许单 Mode，叠加需显式启用 |
| P130-K | 上下文 diff 与审计 | `diff(ctx_a, ctx_b)`、mode stack 与覆盖来源 | diff 显示新增/删除/覆盖及来源；可由 F-177 snapshot 调用 |

**文件落点**：`extensions/self_correct/{context_node,mode_registry,context_diff}.py`、`extensions/self_correct/profiles/`、`tests/self_correct/test_context_node.py`、`test_mode_registry.py`、`test_context_diff.py`。

```python
@dataclass(frozen=True)
class ContextNode:
    parent: "ContextNode | None"
    scope: Literal["session", "task", "subtask", "loop"]
    sections: Mapping[str, SectionRef]
    invariants: tuple[Invariant, ...]

def effective_sections(node: ContextNode) -> list[SectionRef]: ...
def diff_context(a: ContextNode, b: ContextNode) -> ContextDiff: ...
def activate_modes(modes: list[str], *, allow_blend: bool = False) -> EffectiveMode: ...
```

实施顺序：ContextNode/不变量 → ProfileTemplate 适配 → mode registry 与冲突解析 → diff/audit → F-119/F-177 集成。Mode 不得直接扩大用户权限；工具 deny、会话级用户约束和 F-162 强制验证规则均为不可被子级覆盖的不变量。

## §5 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-14 | 初始创建 | 在 F-119 section registry 基础上规划元认知自校正上下文切换机制 |
