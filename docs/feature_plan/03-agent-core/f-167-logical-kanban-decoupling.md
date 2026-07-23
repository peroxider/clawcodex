# F-167: logical_kanban 解耦 — 中低成本独立发布（DC-LKB）

> 状态: 📋 规划中
> 章节: `docs/feature_plan/03-agent-core/f-167-logical-kanban-decoupling.md`
> 最后更新: 2026-07-23
> 设计来源: `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.3
> 关联: DC-LKB（logical_kanban 独立包化）、F-126/F-132/F-141/F-143/F-149/F-151（logical_kanban 内部迭代）

---

## §0 元信息

| 字段 | 值 |
|------|---|
| 文档性质 | Wave 3 P0 · 独立包解耦（中低成本 · 6-10 周） |
| 覆盖范围 | `clawcodex_ext/logical_kanban/` 全部 51 个文件、20,171 行 |
| 前置依赖 | 无（logical_kanban 自身已稳定） |
| 协同 | `extensions/capabilities/` Protocol 体系、`clawcodex_ext.feature_gate`、`clawcodex_ext.tool_system.protocol.ToolResult` |
| 解耦原则 | ✅ 全部新增代码落在 `extensions/lkb/` + `lkb/` 独立包，零 `src/` 侵入；`clawcodex_ext.logical_kanban/` 退化为 re-export shim |
| 落地形态 | 独立 PyPI 包 `lkb` + `lkb` MCP server + CLI `lkb` 命令 + 向后兼容的 `clawcodex_ext.logical_kanban` shim |

---

## §1 设计规划

### 1.1 背景

`logical_kanban` 是 5 大特性中**最内聚、对外依赖最薄**的模块——核心算法（任务分解、规则引擎、ATP 求解、模糊验证、IR 渲染）完全自洽。`COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.3 已识别出 4 个具体的耦合点：

| 耦合类型 | 替换难度 | 性质 |
|----------|----------|------|
| `feature_gate` | 简单 | 进程内单例，可独立内联 |
| `ChatMessage` | 简单 | 纯 dataclass（2 字段） |
| `ToolResult` | 简单 | 纯 dataclass（lkb 只用 3/8 字段） |
| `ToolContext` | 零运行时依赖 | 仅 TYPE_CHECKING 注解 |

但耦合点是**入口**，**底层代码量**和**消费者网络**才是工作量的主体。

### 1.2 当前状态实测（2026-07-23）

通过 `grep` + `Read` 全面盘点 `clawcodex_ext/logical_kanban/`：

**4 个耦合点的实际形态**：

| 耦合点 | 文件 | 行号 | 类型 | 真实使用形态 |
|--------|------|------|------|--------------|
| `feature_gate` | `flags.py` | 5 | 模块级 import | 仅 `get_registry()` + `register_defaults()`，3 个 `is_*_enabled()` 包装 |
| `ChatMessage` | `llm_fact_extractor.py` | 15 | 模块级 import | 构造 `ChatMessage(role="user", content=...)`（line 85） |
| `ChatMessage` | `ambiguity_detector.py` | 146 | 函数内 import | 同上模式 |
| `ChatMessage` | `solver_adapter.py` | 1792 | 函数内 import | 同上模式 |
| `ToolResult` | `adapters.py` | 7 | 模块级 import | 构造 `ToolResult(name=..., is_error=True, output=...)`（line 152） |
| `ToolContext` | `rule_engine.py` | 25 | TYPE_CHECKING | 注解 + `from_context(context: "ToolContext")` |
| `ToolContext` | `service.py` | 72 | TYPE_CHECKING | 22 个函数签名注解 |
| `ToolContext` | `orchestrator.py` | 23 | TYPE_CHECKING | `validate_task_transition(context: "ToolContext", ...)` |
| `ToolContext` | `context_adapter.py` | 19 | TYPE_CHECKING | `_get_runtime` / `_snapshot_cache_key` 等 5 处 |
| `ToolContext` | `decomposer.py` | 37 | TYPE_CHECKING | 多个方法签名 |
| `ToolContext` | `decomposer.py` | 756 | **运行时** ⚠️ | `_build_validation_context()` 直接 `ToolContext(workspace_root=..., session_id=...)` 实例化,后续写 `ctx.tasks[task_id] = ...` |

**关键发现**（verifier 验证 2026-07-23）：

- 5 个文件 (`rule_engine.py` / `service.py` / `orchestrator.py` / `context_adapter.py` / `decomposer.py`) 的 `if TYPE_CHECKING:` 块导入 `ToolContext`，**仅作类型注解**
- **唯一运行时使用**：`decomposer.py:756` `_build_validation_context()` 静态方法内 `from clawcodex_ext.tool_system.context import ToolContext` + `ToolContext(workspace_root=Path("."), session_id="decomposer-validation")` 实例化（line 759），后续 `ctx.tasks[task_id] = ...` 属性写入
- 其余运行时路径全部走 `getattr(context, "tasks")` / `context.workspace_root` / `context.logical_kanban` 鸭子访问
- **运行时硬依赖 = 1 处**：decomposer 的 `_build_validation_context`。**修正方案**见 §3.6。

### 1.3 lkb 公开 API 消费者网络

通过 `grep -r "from clawcodex_ext.logical_kanban" --include="*.py" | grep -v "^.../clawcodex_ext/logical_kanban/" | wc -l` 实测（verifier 验证 2026-07-23）：**34 个外部文件** 依赖 lkb 的公开 API。

| 消费者 | 性质 | 导入面 |
|--------|------|--------|
| `clawcodex_ext/command_system/lkb_command.py` | slash 命令 | 5 处延迟导入 |
| `clawcodex_ext/cli/lkb_method_cmd/commands.py` | CLI 命令 | 16 处导入 |
| `clawcodex_ext/tui/widgets/task_list.py` | TUI 控件 | `LkbStatus` |
| `clawcodex_ext/tool_system/tools/todo_write.py` | tool 适配 | `prepare_todo_write` |
| `clawcodex_ext/tool_system/tools/task_decompose.py` | tool 适配 | `TaskDecomposer`, `get_audit_log`, `is_logical_kanban_enabled` |
| `clawcodex_ext/tool_system/tools/tasks_v2.py` | tool 适配 | `task_lkb_view`, `task_list_view`, `prepare_task_change`, `is_logical_kanban_enabled`, `Clarification`, `get_logical_kanban` |
| `clawcodex_ext/agent/agent_definitions.py` | agent 定义 | `is_logical_kanban_enabled` |
| `tests/logical_kanban/*`（21 个测试文件） | 单元测试 | 全部 `from clawcodex_ext.logical_kanban import ...` |
| `tests/clawcodex_ext/logical_kanban/*` | 子包测试 | 同上 |

**结论**：解耦后必须保证这 34 个 `import` 不破坏——否则回归成本爆炸。设计模式必然是 **"保留旧路径作为 re-export shim"**。

### 1.4 目标

1. **独立 PyPI 包** `lkb`（Logical Kanban Boards）—— 用户可 `pip install lkb` 而无需 clawcodex 全套
2. **独立 MCP server** `lkb-mcp`（基于 `extensions/capabilities/` Protocol），暴露 `decompose_task()` / `validate_task()` / `explain(task_id)` / `audit(task_id)` 4 个工具
3. **独立 CLI** `lkb` —— 暴露 `decompose` / `validate` / `explain` / `audit` 4 个子命令
4. **向后兼容**：仓库内 `clawcodex_ext.logical_kanban` 路径**继续可用**（通过 re-export shim），34 个旧 `import` 不需改动
5. **零 `src/` 侵入**：所有改动落在 `extensions/lkb/` + `lkb/` + `clawcodex_ext/logical_kanban/`（仅 re-export）
6. **保留 feature_gate 生态**：`clawcodex_ext.feature_gate` 继续作为可选依赖注入，缺失时回退到 lkb 内置简化版

### 1.5 非目标

- ❌ 不拆分 `service.py`（2092 行）或 `solver_adapter.py`（1944 行）—— 内部模块结构保留，只迁移位置
- ❌ 不改公开 API 签名（34 个外部调用点零修改）
- ❌ 不引入新依赖（z3/clingo/datalog 是 optional dep，F-142 已处理）
- ❌ 不重写规则引擎（F-132 R-001..R-006 + F-150 R-METHOD-* 全部保留）
- ❌ 不动 F-141（causal）、F-143（llm_facts）、F-149（decomposer）、F-151（method reuse）、F-155（acceptance template）的功能逻辑

---

## §2 解耦策略

### 2.1 总体策略：In-Place 抽取 + Re-export Shim

将 `clawcodex_ext/logical_kanban/` 的实现完整复制到新位置 `extensions/lkb/src/lkb/`，原位置退化为 re-export shim。三步走：

```
阶段 A：扩展层落地
  extensions/lkb/                   # Layer 2 包装层
    __init__.py                     # 转发到 lkb 真实包
    pyproject.toml                  # 独立包元数据（声明 clawcodex_ext.* 为可选）
    adapter.py                      # 把 clawcodex_ext.feature_gate/ToolContext 等注入 lkb
    capabilities.py                 # 实现 extensions/capabilities/ 中定义的 Protocol

阶段 B：独立 PyPI 包落地
  extensions/lkb/src/lkb/           # 真实代码（从 clawcodex_ext/logical_kanban/ 整体迁移）
    __init__.py
    types.py                        # 包含内联 ToolResult、ChatMessage 替代品
    flags.py                        # 本地化 feature_gate（降级实现）
    runtime.py                      # 解耦的 LogicalKanbanRuntime
    decomposer.py
    rule_engine.py
    solver_adapter.py
    service.py
    ... (全部 51 个文件)

阶段 C：兼容垫片
  clawcodex_ext/logical_kanban/     # 仅 re-export + 极少适配代码
    __init__.py                     # from lkb import * + 注册到 clawcodex_ext.feature_gate
    flags.py                        # 委托给 lkb.flags，但注册到 clawcodex_ext.feature_gate
    adapters.py                     # 复用 clawcodex_ext.tool_system.protocol.ToolResult
    runtime.py                      # 兼容 context.logical_kanban 注入路径
    ... (空文件，imports 由 __init__.py 重新导出)
```

### 2.2 为什么是「In-Place」而不是「整体迁移 + 删除原位置」

| 选项 | 优点 | 缺点 |
|------|------|------|
| **In-Place（推荐）** | 34 个旧 `import` 零修改；feature_gate 兼容可选 | 双份代码路径（但 99% re-export 编译期折叠） |
| **整体迁移 + 改 import** | 路径干净 | 34 处 import 改动 + 测试 fixture 改动 + 大量回归风险 |
| **整体迁移 + 删除原位置** | 最干净 | 同上 + 仓库内其他模块需要条件性 import |

In-Place 是「中低成本」的核心——把改动局限在 `extensions/lkb/`（新）+ `clawcodex_ext/logical_kanban/__init__.py`（re-export），34 个外部消费者的 diff 接近零。

---

## §3 四个耦合点的具体重构

### 3.1 `feature_gate` — 降级到 lkb 内置简化版

**当前代码**（`clawcodex_ext/logical_kanban/flags.py`）：

```python
from clawcodex_ext.feature_gate import get_registry, register_defaults

FEATURE_NAME = "logical_kanban"
CAUSAL_FEATURE_NAME = "LKB_CAUSAL"
LLM_FACTS_FEATURE_NAME = "LKB_LLM_FACTS"

def is_logical_kanban_enabled() -> bool:
    register_defaults()
    return get_registry().is_enabled(FEATURE_NAME)

def is_causal_verification_enabled() -> bool:
    register_defaults()
    if not is_logical_kanban_enabled():
        return False
    return get_registry().is_enabled(CAUSAL_FEATURE_NAME)

def is_llm_facts_enabled() -> bool:
    register_defaults()
    if not is_logical_kanban_enabled():
        return False
    return get_registry().is_enabled(LLM_FACTS_FEATURE_NAME)
```

**重构后**（`extensions/lkb/src/lkb/flags.py`）：

```python
"""LKB feature flags with graceful fallback to clawcodex_ext.feature_gate."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

FEATURE_NAME = "logical_kanban"
CAUSAL_FEATURE_NAME = "LKB_CAUSAL"
LLM_FACTS_FEATURE_NAME = "LKB_LLM_FACTS"

# LKB 内置简化版 FeatureRegistry — 仅支持 env 变量 + 默认值。
# 不支持 deps/mutex/config persistence（lkb 用不到），保持最小实现。
@dataclass
class _LkbFeatureFlag:
    name: str
    default: bool = False

@dataclass
class _LkbRegistry:
    _flags: dict[str, _LkbFeatureFlag] = field(default_factory=dict)

    def register(self, flag: _LkbFeatureFlag) -> None:
        self._flags[flag.name] = flag

    def is_enabled(self, name: str) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        env_val = os.environ.get(f"LKB_FEATURE_{name}")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        return flag.default


_LKB_REGISTRY = _LkbRegistry()
for _flag in (
    _LkbFeatureFlag(FEATURE_NAME, default=True),
    _LkbFeatureFlag(CAUSAL_FEATURE_NAME, default=False),
    _LkbFeatureFlag(LLM_FACTS_FEATURE_NAME, default=False),
):
    _LKB_REGISTRY.register(_flag)


def _try_clawcodex_feature_gate():
    """可选注入 clawcodex_ext.feature_gate（如在 clawcodex 环境内运行）。"""
    try:
        from clawcodex_ext.feature_gate import get_registry, register_defaults

        register_defaults()
        return get_registry()
    except ImportError:
        return None


def is_logical_kanban_enabled() -> bool:
    claw_reg = _try_clawcodex_feature_gate()
    if claw_reg is not None:
        return claw_reg.is_enabled(FEATURE_NAME)
    return _LKB_REGISTRY.is_enabled(FEATURE_NAME)


def is_causal_verification_enabled() -> bool:
    if not is_logical_kanban_enabled():
        return False
    claw_reg = _try_clawcodex_feature_gate()
    if claw_reg is not None:
        return claw_reg.is_enabled(CAUSAL_FEATURE_NAME)
    return _LKB_REGISTRY.is_enabled(CAUSAL_FEATURE_NAME)


def is_llm_facts_enabled() -> bool:
    if not is_logical_kanban_enabled():
        return False
    claw_reg = _try_clawcodex_feature_gate()
    if claw_reg is not None:
        return claw_reg.is_enabled(LLM_FACTS_FEATURE_NAME)
    return _LKB_REGISTRY.is_enabled(LLM_FACTS_FEATURE_NAME)
```

**关键设计**：
- **优先级**：clawcodex_ext.feature_gate（如可用） > 内置简化版
- **env 变量命名**：内置版用 `LKB_FEATURE_*`，与 clawcodex 的 `CLAWCODEX_FEATURE_*` 不冲突
- **默认行为**：`logical_kanban` 默认 **True**（lkb 是独立产品时直接可用），`LKB_CAUSAL` / `LKB_LLM_FACTS` 默认 False

**`clawcodex_ext/logical_kanban/flags.py`（兼容 shim）**：

```python
"""Compatibility shim — delegate to lkb.flags with clawcodex_ext.feature_gate registration."""

from lkb.flags import (  # noqa: F401
    CAUSAL_FEATURE_NAME,
    FEATURE_NAME,
    LLM_FACTS_FEATURE_NAME,
    is_causal_verification_enabled,
    is_llm_facts_enabled,
    is_logical_kanban_enabled,
)

# 在 clawcodex 环境内，向 clawcodex_ext.feature_gate 注册 lkb 的 flags，
# 这样 clawcodex 的 `--enable LKB_CAUSAL` 也能控制 lkb 行为。
def _register_with_clawcodex() -> None:
    try:
        from clawcodex_ext.feature_gate import FeatureFlag, get_registry, register_defaults

        register_defaults()
        reg = get_registry()
        reg.register(FeatureFlag(name=FEATURE_NAME, default=True))
        reg.register(FeatureFlag(name=CAUSAL_FEATURE_NAME, default=False))
        reg.register(FeatureFlag(name=LLM_FACTS_FEATURE_NAME, default=False))
    except ImportError:
        pass


_register_with_clawcodex()
```

### 3.2 `ChatMessage` — 内联 dataclass + Protocol 兼容

**当前代码**（`clawcodex_ext/logical_kanban/llm_fact_extractor.py:15`）：

```python
from clawcodex_ext.providers.base import ChatMessage
...
response = self.provider.chat([ChatMessage(role="user", content=prompt)])
```

**lkb 内部使用模式**：3 处全部只构造 `ChatMessage(role="user", content=prompt)`，从不读取其字段（因为返回值是 `provider.chat(...)` 返回的 `ChatResponse`，与入参无关）。

**重构后**（`extensions/lkb/src/lkb/types.py`）：

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LkbChatMessage:
    """lkb-local replacement for clawcodex_ext.providers.base.ChatMessage.
    
    Compatible with any BaseProvider that accepts objects with .role/.content attrs.
    Independent of clawcodex_ext.providers.
    """
    role: str
    content: str


class _ProviderLike(Protocol):
    """Minimal protocol — lkb only needs .chat(messages)."""
    def chat(self, messages: list[Any]) -> Any: ...
```

**替换调用点**（3 处）：

```python
# llm_fact_extractor.py:85
response = self.provider.chat([LkbChatMessage(role="user", content=prompt)])

# ambiguity_detector.py:148
response = self.llm_fallback_provider.chat([LkbChatMessage(role="user", content=prompt)])

# solver_adapter.py:1794
response = self.provider.chat([LkbChatMessage(role="user", content=prompt)])
```

**关键设计**：lkb 不强制 `LkbChatMessage == ChatMessage`。如果用户传入 `BaseProvider`（如 clawcodex 环境），lkb 构造 `LkbChatMessage` 实例，由于 `BaseProvider.chat()` 只读 `.role`/`.content` 属性，**Protocol 兼容**。如果用户传入其他 provider SDK（如 LiteLLM），`LkbChatMessage` 也是 duck-type 兼容的。

### 3.3 `ToolResult` — 内联 dataclass

**当前代码**（`clawcodex_ext/logical_kanban/adapters.py:152`）：

```python
return ToolResult(
    name=tool_name,
    is_error=True,
    output={"success": False, ...},
)
```

**lkb 只用了 3 个字段**：`name` / `is_error` / `output`。`ToolResult` 完整定义有 8 个字段 + 1 个 property（verifier 验证 2026-07-23：`name, output, is_error, tool_use_id, content_type, new_messages, context_modifier, mcp_meta` + `data` property），其余 5 个字段 + 1 个 property lkb 完全不用。

**重构后**（`extensions/lkb/src/lkb/types.py`）：

```python
@dataclass(frozen=True)
class LkbToolResult:
    """lkb-local replacement for clawcodex_ext.tool_system.protocol.ToolResult.
    
    Mirrors the 3 fields lkb actually uses. Independent of clawcodex_ext.tool_system.
    """
    name: str
    output: Any
    is_error: bool = False
```

**替换调用点**（`adapters.py` 中的 `_denied_result`）：

```python
return LkbToolResult(
    name=tool_name,
    is_error=True,
    output={"success": False, "status": "denied", ...},
)
```

**`clawcodex_ext/logical_kanban/adapters.py`（兼容 shim）**：

```python
"""Compatibility shim — convert LkbToolResult to clawcodex_ext ToolResult at boundary."""

from lkb.adapters import (  # noqa: F401
    _accepted_lkb,
    _denied_result,
    maybe_commit_task_update,
    maybe_commit_todo_write,
    prepare_task_change,
    prepare_todo_write,
)
from lkb.types import LkbToolResult
from clawcodex_ext.tool_system.protocol import ToolResult


def _to_clawcodex_result(lkb_result: LkbToolResult | None) -> ToolResult | None:
    """Convert LkbToolResult → clawcodex ToolResult (when called from clawcodex tools)."""
    if lkb_result is None:
        return None
    return ToolResult(
        name=lkb_result.name,
        output=lkb_result.output,
        is_error=lkb_result.is_error,
    )
```

调用方（`clawcodex_ext/tool_system/tools/tasks_v2.py`）拿到的是 `ToolResult`，通过 shim 边界适配。

### 3.4 `ToolContext` — 零运行时改动

**所有 `ToolContext` 引用都在 `if TYPE_CHECKING:` 块内**（`rule_engine.py:22-25`、`service.py:71-76`、`orchestrator.py:22-23`、`context_adapter.py:18-19`、`decomposer.py:34-37`）。**运行时仅通过 `getattr(context, "tasks")` / `context.workspace_root` / `context.logical_kanban` 鸭子访问**。

**重构方式**：保留所有 `if TYPE_CHECKING: from clawcodex_ext.tool_system.context import ToolContext` 不变。但因为 lkb 现在是独立包，`clawcodex_ext` 不是必装依赖，**必须降级为字符串前向引用**：

```python
# 改前（依赖 clawcodex_ext.tool_system.context）
if TYPE_CHECKING:
    from clawcodex_ext.tool_system.context import ToolContext

def _session_id(context: "ToolContext") -> str | None:
    return getattr(context, "session_id", None)

# 改后（lkb 独立）
# TYPE_CHECKING 块改为字符串注解，lkb 不需要导入具体类
def _session_id(context: Any) -> str | None:
    return getattr(context, "session_id", None)
```

**关键设计**：
- 函数签名内的 `"ToolContext"` 字符串注解改为 `Any`（PEP 563 已通过 `from __future__ import annotations` 启用，全部字符串化）
- 保留 `# type: context` 注释 or `# type: ToolContext-like` 给 IDE / mypy
- 任何 `isinstance(context, ToolContext)` / `issubclass(..., ToolContext)` 的运行时检查（实测：**0 处**）不需要改

### 3.5 运行时契约：`get_logical_kanban(context)`

当前实现（`runtime.py:41-49`）：

```python
def get_logical_kanban(context: Any) -> "LogicalKanbanRuntime":
    runtime = getattr(context, "logical_kanban", None)
    if runtime is None:
        runtime = LogicalKanbanRuntime()
        try:
            context.logical_kanban = runtime
        except AttributeError:
            pass
    return runtime
```

**已经是鸭子访问**（仅通过 `getattr`/`setattr`），**零运行时依赖**。lkb 直接复制即可。

### 3.6 `ToolContext` 运行时实例化（verifier 校验发现）—— 新增解耦点

**问题**：`decomposer.py:751-793` 的 `_build_validation_context` 静态方法直接 `ToolContext(workspace_root=Path("."), session_id="decomposer-validation")` 实例化。这是 lkb 内部**唯一**对 `clawcodex_ext.tool_system.context.ToolContext` 的运行时硬依赖（被设计文档初稿误判为 TYPE_CHECKING-only，verifier 校验 2026-07-23 发现）。

**真实使用形态**（`decomposer.py:756-792`）：

```python
ctx = ToolContext(workspace_root=Path("."), session_id="decomposer-validation")
for task in existing_tasks:
    task_id = task.get("id") or task.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        continue
    ctx.tasks[task_id] = dict(task)            # 写 .tasks 字典
for task in tasks:
    ctx.tasks[task.proposed_task_id] = {...}   # 写 .tasks 字典
# ... 镜像 blockedBy/blocks
return ctx
```

实际只使用 3 个字段：`workspace_root` / `session_id` / `tasks`（作为可变 dict）。其余 30+ 个 ToolContext 字段全部走默认值。

**重构后**（`extensions/lkb/src/lkb/types.py`）：

```python
@dataclass(slots=True)
class LkbValidationContext:
    """lkb-local minimal context for internal validation.
    
    Mirrors the 3 fields lkb actually uses in _build_validation_context.
    Independent of clawcodex_ext.tool_system.context.ToolContext.
    Duck-compatible with any object exposing .workspace_root / .session_id / .tasks.
    """
    workspace_root: Path
    session_id: str | None = None
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
```

**替换调用点**（`extensions/lkb/src/lkb/decomposer.py:756-793`）：

```python
from pathlib import Path
from lkb.types import LkbValidationContext

@staticmethod
def _build_validation_context(
    tasks: tuple[ProposedTask, ...],
    existing_tasks: tuple[dict[str, Any], ...],
) -> "LkbValidationContext":
    ctx = LkbValidationContext(
        workspace_root=Path("."),
        session_id="decomposer-validation",
    )
    for task in existing_tasks:
        task_id = task.get("id") or task.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            continue
        ctx.tasks[task_id] = dict(task)
    # ... 其余填充逻辑保持不变
    return ctx
```

**关键设计**：

1. **下游兼容性**：所有消费 `_build_validation_context` 返回值的下游代码（validator / context_adapter）都通过 `getattr(ctx, "tasks")` 鸭子访问，所以 `LkbValidationContext` 行为 100% 等价。
2. **`get_logical_kanban(ctx)`**：内部逻辑还是 `getattr(ctx, "logical_kanban", None)`，会 fallback 到新建 `LogicalKanbanRuntime()`，与 ToolContext 上挂载运行时一致。
3. **`clawcodex_ext/logical_kanban/decomposer.py`（兼容 shim）**：当从 clawcodex 工具（如 `task_decompose`）调用 lkb 时，shim 需要把 `LkbValidationContext` 包装为 `ToolContext`（仅在 clawcodex 内运行时需要）。Shim 实现：

```python
# clawcodex_ext/logical_kanban/decomposer.py (shim)
from lkb.decomposer import (
    ProposedTask,
    DecompositionPlan,
    TaskDecomposer as _LkbTaskDecomposer,
    _build_validation_context as _lkb_build_validation_context,
)
from lkb.types import LkbValidationContext


def _to_clawcodex_ctx(lkb_ctx: LkbValidationContext):
    """Convert LkbValidationContext → clawcodex ToolContext (boundary adapter)."""
    from clawcodex_ext.tool_system.context import ToolContext

    ctx = ToolContext(workspace_root=lkb_ctx.workspace_root)
    ctx.session_id = lkb_ctx.session_id
    ctx.tasks.update(lkb_ctx.tasks)
    return ctx


class TaskDecomposer(_LkbTaskDecomposer):
    """Subclass that overrides _build_validation_context to emit ToolContext."""

    @staticmethod
    def _build_validation_context(
        tasks: tuple[ProposedTask, ...],
        existing_tasks: tuple[dict[str, Any], ...],
    ):
        lkb_ctx = _lkb_build_validation_context(tasks, existing_tasks)
        return _to_clawcodex_ctx(lkb_ctx)
```

4. **独立运行时**：lkb standalone 用户拿到的就是 `LkbValidationContext`，validator 通过鸭子访问正常工作，不依赖 `ToolContext`。

**工作量**：~50 行（`LkbValidationContext` dataclass + shim `_to_clawcodex_ctx` + `TaskDecomposer` 子类）。已计入 §5 阶段 2.2（移除 TYPE_CHECKING 导入时同时处理此处）。

---

## §4 包结构与发布

### 4.1 目录结构

```
extensions/lkb/                          # Layer 2 包装层（lifecycle + MCP + 协议）
├── pyproject.toml                       # 独立 PyPI 包元数据
├── README.md                            # 用户文档
├── CHANGELOG.md
├── src/
│   └── lkb/                             # 独立 PyPI 包源代码
│       ├── __init__.py                  # 公开 API 入口（~586 行 from 旧 __init__.py）
│       ├── types.py                     # LkbChatMessage / LkbToolResult / 其他 dataclass
│       ├── flags.py                     # feature_gate 降级实现
│       ├── runtime.py                   # LogicalKanbanRuntime（鸭子访问）
│       ├── context_adapter.py           # tool context 适配
│       ├── decomposer.py                # 任务分解（F-149）
│       ├── rule_engine.py               # F-132 R-001..R-006
│       ├── solver_adapter.py            # 多 solver 适配
│       ├── solver_pipeline.py
│       ├── solver_atp.py                # F-142 ATP 求解
│       ├── service.py                   # 核心服务（propose/validate/commit）
│       ├── causal.py                    # F-141 因果验证
│       ├── llm_fact_extractor.py        # F-143 LLM 事实抽取
│       ├── ambiguity_detector.py        # 模糊歧义检测
│       ├── audit.py                     # 审计日志
│       ├── explain.py                   # 推理链解释
│       ├── adapters.py                  # tool 适配（LkbToolResult）
│       ├── method_library.py            # F-150
│       ├── method_seed.py               # F-151
│       ├── method_proposer.py
│       ├── method_governance.py
│       ├── method_coverage.py
│       ├── method_prompt.py
│       ├── acceptance_template.py       # F-155
│       ├── acceptance_template_seed.py
│       ├── acceptance_template_governance.py
│       ├── acceptance_template_prompt.py
│       ├── external_config.py           # F-154
│       ├── external_config_lint.py
│       ├── ontology_graph.py
│       ├── operation_schema.py
│       ├── scheduling_solver.py         # F-152
│       ├── truth_maintenance.py         # TMS
│       ├── commit_gate_fuzzy.py
│       ├── fuzzy_patterns.py
│       ├── fuzzy_types.py
│       ├── multiworld_validator.py
│       ├── world_generator.py
│       ├── glossary.py
│       ├── ir.py
│       ├── ir_hash.py
│       ├── ir_renderer.py
│       ├── predicate_extractor.py
│       ├── metrics.py
│       ├── solver_limits.py
│       └── atp/                         # F-142 ATP 求解器后端
│           ├── __init__.py
│           ├── base.py
│           ├── prover9.py
│           ├── mace4.py
│           └── vampire.py
├── mcp/                                 # lkb MCP server 入口
│   ├── __init__.py
│   ├── server.py                        # @server.list_tools() + @server.call_tool()
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── decompose.py                 # decompose_task() 工具
│   │   ├── validate.py                  # validate_task() 工具
│   │   ├── explain.py                   # explain(task_id) 工具
│   │   └── audit.py                     # audit(task_id) 工具
│   └── README.md
├── cli/                                 # lkb CLI 入口（独立 `lkb` 命令）
│   ├── __init__.py
│   ├── main.py                          # typer / argparse 入口
│   ├── decompose_cmd.py
│   ├── validate_cmd.py
│   ├── explain_cmd.py
│   └── audit_cmd.py
└── tests/                               # lkb 独立测试套件
    ├── __init__.py
    ├── test_*.py                        # 从 tests/logical_kanban/ 迁移
    └── ...

clawcodex_ext/logical_kanban/            # 兼容 shim（原地保留）
├── __init__.py                          # `from lkb import *` + 注册 feature_gate
├── flags.py                             # 委托给 lkb.flags + 向 clawcodex_ext.feature_gate 注册
├── adapters.py                          # 委托给 lkb.adapters + LkbToolResult → ToolResult 适配
├── runtime.py                           # 委托给 lkb.runtime
└── ... (其他文件 = 简单 re-export shim)
```

### 4.2 独立包元数据（`extensions/lkb/pyproject.toml` 草案）

```toml
[build-system]
requires = ["setuptools>=77.0.3", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "lkb"
version = "0.1.0"
description = "Logical Kanban Boards — formal task decomposition with rule engines and ATP solvers"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [
    {name = "Claw Codex Team"},
]
keywords = ["task-decomposition", "rule-engine", "atp-solver", "task-kanban"]

dependencies = [
    # 核心算法无外部依赖（仅 stdlib）
]

[project.optional-dependencies]
# 可选 ATP 求解器后端（F-142）
prover9 = ["prover9-py>=0.0.5"]  
z3 = ["z3-solver>=4.12"]
clingo = ["clingo>=5.6"]
# 可选 clawcodex 集成（feature_gate / ToolContext）
clawcodex = []  # 检测 clawcodex_ext.* 是否可用即可

[project.scripts]
lkb = "lkb.cli.main:main"

[project.entry-points.mcp_servers]
lkb = "lkb.mcp.server:create_server"
```

### 4.3 MCP server 接口契约（`extensions/lkb/mcp/server.py`）

基于 `extensions/capabilities/tool_protocol.py` 已有 Protocol 设计：

```python
from mcp.server import Server
from mcp.types import Tool, TextContent

from lkb import TaskDecomposer, LogicalKanbanService
from lkb.types import FactsSnapshot

server = Server("lkb")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="decompose_task",
            description="Decompose a goal into a validated task plan (returns DecompositionPlan JSON)",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Natural-language goal"},
                    "context": {"type": "object", "description": "Optional context snapshot"},
                    "use_methods": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["goal"],
            },
        ),
        Tool(
            name="validate_task",
            description="Validate a proposed task state transition without committing",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "change": {"type": "object"},
                },
                "required": ["task_id", "change"],
            },
        ),
        Tool(
            name="explain",
            description="Explain the reasoning chain for a task (proof trace, repair suggestions)",
            inputSchema={
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        Tool(
            name="audit",
            description="Return the audit log for a task (proposals, validations, commits, denials)",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "since": {"type": "string", "format": "date-time"},
                },
                "required": ["task_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "decompose_task":
        decomposer = TaskDecomposer()
        plan = decomposer.decompose(
            goal=arguments["goal"],
            context=arguments.get("context", {}),
            method_refs=tuple(arguments.get("use_methods", [])),
        )
        return [TextContent(type="text", text=plan.to_json())]
    elif name == "validate_task":
        # ... 类似实现
        ...
```

### 4.4 CLI 接口契约（`extensions/lkb/cli/main.py`）

```python
import argparse
from lkb import TaskDecomposer, LogicalKanbanService, get_logical_kanban

def main():
    parser = argparse.ArgumentParser(prog="lkb")
    sub = parser.add_subparsers(dest="command", required=True)

    # decompose
    p_decomp = sub.add_parser("decompose", help="Decompose a goal into tasks")
    p_decomp.add_argument("goal", help="Natural-language goal")
    p_decomp.add_argument("--methods", nargs="*", default=[], help="Method library refs")

    # validate
    p_val = sub.add_parser("validate", help="Validate a proposed task change")
    p_val.add_argument("--task-id", required=True)
    p_val.add_argument("--change", required=True, help="JSON change spec")

    # explain
    p_explain = sub.add_parser("explain", help="Explain task reasoning")
    p_explain.add_argument("task_id")

    # audit
    p_audit = sub.add_parser("audit", help="Return audit log")
    p_audit.add_argument("task_id")
    p_audit.add_argument("--since", help="ISO 8601 timestamp")

    args = parser.parse_args()
    # ... dispatch
```

---

## §5 迁移步骤（6 阶段）

### 阶段 1：基础设施准备（~2 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 1.1 | 创建 `extensions/lkb/` 目录结构 + `pyproject.toml` | ~100 行 |
| 1.2 | 实现 `lkb/types.py`（LkbChatMessage / LkbToolResult） | ~30 行 |
| 1.3 | 实现 `lkb/flags.py`（降级 feature_gate） | ~80 行 |
| 1.4 | 配置 `[tool.uv]` workspace 成员（如果是 uv workspace） | ~20 行 |

### 阶段 2：核心算法层迁移（~5 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 2.1 | 复制 `service.py`、`decomposer.py`、`rule_engine.py`、`solver_adapter.py`、`solver_pipeline.py`、`solver_atp.py` 到 `lkb/` | ~6,000 行机械搬运 |
| 2.2 | 移除文件内的 `from clawcodex_ext.tool_system.context import ToolContext`（改为 `Any` 注解） | ~5 处 |
| 2.3 | 移除 `from clawcodex_ext.providers.base import BaseProvider`（保留 Protocol 占位） | ~3 处 |
| 2.4 | 替换 `ChatMessage` → `LkbChatMessage`（3 处构造点） | ~3 行修改 |
| 2.5 | 替换 `ToolResult` → `LkbToolResult`（1 处构造点） | ~5 行修改 |
| 2.6 | 替换 `from clawcodex_ext.feature_gate import ...` → 本地 `_try_clawcodex_feature_gate()` | ~3 处 |

### 阶段 3：周边模块迁移（~3 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 3.1 | 迁移 `adapters.py` / `runtime.py` / `context_adapter.py` | ~600 行 |
| 3.2 | 迁移 `audit.py` / `explain.py` / `causal.py` / `commit_gate_fuzzy.py` | ~2,500 行 |
| 3.3 | 迁移 `method_*` + `acceptance_template_*` 系列（F-150/F-151/F-155） | ~3,000 行 |
| 3.4 | 迁移 `external_config.py` / `external_config_lint.py` / `ontology_graph.py` / `operation_schema.py` | ~1,500 行 |
| 3.5 | 迁移 `fuzzy_*` / `multiworld_validator.py` / `world_generator.py` / `truth_maintenance.py` / `predicate_extractor.py` | ~3,000 行 |
| 3.6 | 迁移 `glossary.py` / `ir.py` / `ir_hash.py` / `ir_renderer.py` / `metrics.py` / `solver_limits.py` | ~1,500 行 |
| 3.7 | 迁移 `atp/` 子包（F-142） | ~600 行 |
| 3.8 | 实现 `lkb/__init__.py` 公开 API（聚合 from 原 `clawcodex_ext/logical_kanban/__init__.py` 的 586 行 re-export） | ~600 行 |

### 阶段 4：兼容 shim 层（~2 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 4.1 | 重写 `clawcodex_ext/logical_kanban/__init__.py` 为 `from lkb import *` + 少量定制 | ~50 行 |
| 4.2 | 重写 `clawcodex_ext/logical_kanban/flags.py` 为委托 + 注册到 `clawcodex_ext.feature_gate` | ~30 行 |
| 4.3 | 重写 `clawcodex_ext/logical_kanban/adapters.py` 为委托 + `LkbToolResult → ToolResult` 适配 | ~30 行 |
| 4.4 | 删除或简化其余文件（其他模块改为 re-export 占位） | ~50 行 |
| 4.5 | 添加 `clawcodex_ext/logical_kanban/__init__.py` 的 deprecation 警告（可选） | ~5 行 |

### 阶段 5：MCP server + CLI（~3 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 5.1 | 实现 `lkb/mcp/server.py` 框架（基于 mcp SDK） | ~100 行 |
| 5.2 | 实现 4 个 MCP 工具（decompose_task / validate_task / explain / audit） | ~400 行 |
| 5.3 | 实现 `lkb/cli/main.py` + 4 个子命令 | ~300 行 |
| 5.4 | 编写 `extensions/lkb/mcp/README.md` + `extensions/lkb/README.md` | ~300 行 |

### 阶段 6：测试与文档（~3 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 6.1 | 迁移 `tests/logical_kanban/`（21 个测试文件）到 `extensions/lkb/tests/` | ~3,000 行 |
| 6.2 | 修改测试中的 `from clawcodex_ext.logical_kanban import ...` → `from lkb import ...` | ~50 行 |
| 6.3 | 运行 `extensions/lkb/tests/` 全部测试通过 | — |
| 6.4 | 运行 `tests/stability_gate/` 全部测试通过（验证仓库内未破坏） | — |
| 6.5 | 运行 `tests/clawcodex_ext/logical_kanban/test_canonical_ir_glossary.py` 验证 shim 兼容 | — |
| 6.6 | 编写 `docs/lkb-standalone.md` 用户文档 | ~300 行 |
| 6.7 | 更新 `CLAUDE.md` / `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` 标记 logical_kanban 已解耦 | ~50 行 |

### 总工作量估算

| 阶段 | 工作日 | 代码行数（含注释+测试） |
|------|--------|-------------------------|
| 阶段 1-3（迁移） | 10 | ~5,500 行（含原代码搬运 + 局部修改） |
| 阶段 4（shim） | 2 | ~200 行 |
| 阶段 5（MCP + CLI） | 3 | ~1,100 行 |
| 阶段 6（测试 + 文档） | 3 | ~3,700 行 |
| **合计** | **18 工作日（~6 周）** | **~10,500 行** |

**实际新增代码**：~1,500 行（types / flags / shim / MCP / CLI）。其余 ~9,000 行是搬运 + 测试 + 文档。

与 `COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.3 估算的 **~1,000-1,500 行** 吻合。

---

## §6 兼容性矩阵

### 6.1 旧 import 兼容

| 旧 import | 新 import | 行为 |
|-----------|-----------|------|
| `from clawcodex_ext.logical_kanban import X` | `from lkb import X` | ✅ 通过 shim 完全兼容 |
| `from clawcodex_ext.logical_kanban.adapters import prepare_todo_write` | `from lkb.adapters import prepare_todo_write` | ✅ 兼容 |
| `from clawcodex_ext.logical_kanban.flags import is_logical_kanban_enabled` | `from lkb.flags import is_logical_kanban_enabled` | ✅ 兼容（行为等价） |
| `from clawcodex_ext.logical_kanban.types import FactsSnapshot` | `from lkb.types import FactsSnapshot` | ✅ 兼容 |
| `from clawcodex_ext.logical_kanban.runtime import get_logical_kanban` | `from lkb.runtime import get_logical_kanban` | ✅ 兼容 |
| `from clawcodex_ext.tool_system.protocol import ToolResult`（lkb 内部使用） | `from lkb.types import LkbToolResult` | ⚠️ 类型不同，**仅在适配边界**转换 |

### 6.2 功能兼容

| 功能 | 兼容情况 |
|------|----------|
| `is_logical_kanban_enabled()` | ✅ 行为等价（clawcodex 内注册到 `clawcodex_ext.feature_gate`，外部用 `LKB_FEATURE_*`） |
| `is_causal_verification_enabled()` | ✅ 同上 |
| `is_llm_facts_enabled()` | ✅ 同上 |
| `TaskDecomposer.decompose()` | ✅ 100% 兼容（不依赖 ToolContext 运行时） |
| `LogicalKanbanService.run()` | ✅ 100% 兼容 |
| `SolverAdapter.query()` | ✅ 100% 兼容（ATP 后端通过 optional deps） |
| `get_logical_kanban(context)` | ✅ 100% 兼容（鸭子访问） |
| `_denied_result()` 返回 ToolResult | ✅ shim 边界适配为 `clawcodex_ext.tool_system.protocol.ToolResult` |

### 6.3 行为差异（已知）

| 差异 | 说明 | 影响范围 |
|------|------|----------|
| `feature_gate` 默认值 | 在 lkb 独立运行时 `LKB_CAUSAL` / `LKB_LLM_FACTS` 默认 False（与原 clawcodex 一致） | 仅 standalone 用户 |
| `feature_gate` env 变量 | clawcodex 内用 `CLAWCODEX_FEATURE_*`，独立 lkb 用 `LKB_FEATURE_*` | 仅 standalone 用户 |
| ToolResult 类型边界 | shim 在 `clawcodex_ext.tool_system.tools.todo_write` 调用 lkb 时做 `LkbToolResult → ToolResult` 转换（零运行时开销） | 仅 clawcodex 集成点 |

---

## §7 风险与回滚

### 7.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| **搬运过程遗漏**（某个文件未迁移） | 中 | 高 | 阶段 6 全量测试覆盖；CI 强制 `test-gate` 通过 |
| **ToolContext 字符串化遗漏**（某处真的运行时 isinstance 检查） | 低 | 高 | 实测 0 处；阶段 3.2 移除 TYPE_CHECKING 导入时手动复核每个文件 |
| **feature_gate 语义差异**（CLI `--enable LKB_CAUSAL` 不生效） | 低 | 中 | shim 主动注册到 `clawcodex_ext.feature_gate` |
| **atp 后端可选依赖**（Prover9 / Vampire / Clingo 缺失） | 低 | 低 | F-142 已处理（try/except ImportError） |
| **34 个外部 import 路径中断** | 极低 | 极高 | 阶段 4 shim 设计确保零 diff；测试 6.4 验证 |
| **重构期间 lkb 内部功能破坏**（F-132/F-149 等回归） | 低 | 高 | 阶段 6.3 全量测试 + 阶段 6.4 stability_gate |

### 7.2 回滚方案

阶段 4（shim 层）之前的任意阶段，回滚 = 删除 `extensions/lkb/`，恢复 `clawcodex_ext/logical_kanban/` 原始实现。

阶段 4 之后（即 shim 已上线），回滚 = 恢复 shim 文件为完整实现版本（git revert 即可，因为 shim 文件本身就是从 git 历史可恢复的旧版本）。

**最坏情况回滚时间**：~30 分钟（恢复 + 测试）。

### 7.3 验证门禁

阶段 4 完成时必须通过：

```bash
# 1. 仓库内功能未破坏
python3 -m pytest tests/stability_gate/ -q --tb=short -x

# 2. lkb 单元测试通过（含原 21 个测试文件，已迁移路径）
python3 -m pytest extensions/lkb/tests/ -q --tb=short -x

# 3. lkb 在 clawcodex 集成场景下通过（旧 import 路径）
python3 -m pytest tests/clawcodex_ext/logical_kanban/ -q --tb=short -x

# 4. lkb 独立可用（脱离 clawcodex 安装）
cd extensions/lkb && pip install -e . && lkb --help
cd extensions/lkb && lkb-mcp --help  # 或 mcp dev lkb
```

---

## §8 与上游策略的协同

### 8.1 与「策略一：全部合入」的关系

若选择策略一（推荐），F-167 解耦后的 `extensions/lkb/` 自然作为**二开模组**被合入主仓库（Layer 2）。`clawcodex_ext/logical_kanban/` shim 保持与 `extensions/lkb/src/lkb/` 同步（通过 CI 自动校验 re-export 完整性）。

### 8.2 与「策略二：补丁安装」的关系

策略二下，F-167 解耦的 `lkb` 包可直接发布到内部 PyPI（不依赖 clawcodex_ext），用户在 `pip install clawcodex` + 应用补丁 + `pip install lkb` 后使用。

### 8.3 与「策略三：大特性独立发布」的关系

F-167 是策略三的具体落地：`lkb` 作为独立 PyPI 包，`lkb-mcp` 作为独立 MCP server，`lkb` 作为独立 CLI。这与 §5 推荐路径一致。

---

## §9 验收标准

| 维度 | 验收 |
|------|------|
| **功能性** | lkb 单元测试 100% 通过；clawcodex 内 34 个旧 import 调用 100% 行为不变 |
| **独立性** | `pip install lkb` 后 lkb 可独立运行（无 clawcodex_ext / src / src.* 依赖） |
| **MCP** | `lkb-mcp --help` 可启动；4 个工具（decompose_task / validate_task / explain / audit）可被 Claude Desktop / Cline 调用 |
| **CLI** | `lkb decompose "Build user auth"` 可输出 DecompositionPlan JSON |
| **性能** | lkb 冷启动 < 500ms（无 ATP solver 加载）；含 z3 后端 < 2s；含 clingo 后端 < 3s |
| **文档** | `extensions/lkb/README.md` + `extensions/lkb/mcp/README.md` + `docs/lkb-standalone.md` 完整 |
| **CI** | `.github/workflows/ci.yml` 中新增 `lkb-test` job（`pip install lkb && pytest extensions/lkb/tests/`） |
| **解耦原则** | 零 `src/` 侵入；`git diff src/` 应为空 |

---

## §10 依赖与协同

| 依赖项 | 类型 | 说明 |
|--------|------|------|
| `extensions/capabilities/tool_protocol.py` | 已有 | F-167 复用 Protocol 定义 |
| `extensions/capabilities/adapter_protocol.py` | 已有 | F-167 shim 层用 |
| `clawcodex_ext.feature_gate` | 可选 | shim 阶段保留为可选注入 |
| `mcp>=1.27.2` | 新增 | MCP server 需要（pyproject.toml 已有） |
| `typer[all]>=0.12.0` | 已有 | CLI 需要（pyproject.toml 已有） |

| 协同项 | 关系 |
|--------|------|
| F-126（logical_kanban MVP） | 上游功能已稳定，F-167 不改逻辑 |
| F-132（R-001..R-006 规则引擎） | 同步搬运到 `lkb/rule_engine.py` |
| F-141（causal verification） | 同步搬运到 `lkb/causal.py` |
| F-142（external ATP） | 同步搬运到 `lkb/atp/`，保留 optional deps |
| F-143（LLM facts） | 同步搬运到 `lkb/llm_fact_extractor.py` |
| F-149（task decomposition） | 同步搬运到 `lkb/decomposer.py` |
| F-150/F-151/F-155（method library + acceptance template） | 同步搬运到 `lkb/method_*` + `lkb/acceptance_template_*` |
| F-152（scheduling solver） | 同步搬运到 `lkb/scheduling_solver.py` |
| F-154（external config） | 同步搬运到 `lkb/external_config.py` |
| F-166（memory layering W/E） | 协同：lkb 可选用 Episodic Memory 存储 `latest_denials` |

---

## 附录 A：关键文件路径速查

| 旧位置 | 新位置 | 性质 |
|--------|--------|------|
| `clawcodex_ext/logical_kanban/__init__.py` | `extensions/lkb/src/lkb/__init__.py` | 完整迁移 |
| `clawcodex_ext/logical_kanban/{51 个 .py}` | `extensions/lkb/src/lkb/{同名}` | 完整迁移 |
| `clawcodex_ext/logical_kanban/__init__.py`（shim） | `clawcodex_ext/logical_kanban/__init__.py` | re-export shim |
| `clawcodex_ext/logical_kanban/flags.py`（shim） | `clawcodex_ext/logical_kanban/flags.py` | 委托 + 注册 |
| `clawcodex_ext/logical_kanban/adapters.py`（shim） | `clawcodex_ext/logical_kanban/adapters.py` | 委托 + 适配 |
| `clawcodex_ext/logical_kanban/runtime.py`（shim） | `clawcodex_ext/logical_kanban/runtime.py` | 委托 |
| `tests/logical_kanban/*`（21 文件） | `extensions/lkb/tests/` | 迁移 + import 改写 |
| `tests/clawcodex_ext/logical_kanban/test_canonical_ir_glossary.py` | 保留原位 | 验证 shim 兼容 |

## 附录 B：MCP 工具详细输入输出契约

### B.1 `decompose_task(goal, context?, use_methods?) → DecompositionPlan`

```json
// 输入
{
  "goal": "Build a CLI tool to monitor GitHub PRs",
  "context": {
    "tasks": {},                      // 可选：现有 tasks 快照
    "workspace_root": "/path/to/repo"  // 可选
  },
  "use_methods": ["exploratory-prototyping", "tdd-red-green"]
}

// 输出（DecompositionPlan.to_dict()）
{
  "decompositionRunId": "dec-abc123",
  "goal": "Build a CLI tool...",
  "tasks": [
    {
      "proposedTaskId": "task-001",
      "subject": "Design CLI argument parser",
      "description": "...",
      "activeForm": "Designing CLI argument parser",
      "acceptanceCriteria": ["argparse interface defined", "..."],
      "blockedBy": [],
      "lkbMetadata": {"methodRef": "exploratory-prototyping"}
    }
  ],
  "dependencies": [["task-002", "task-001"]],
  "assumptions": ["GitHub API rate limit allows polling"],
  "ambiguityReport": null,
  "validationRun": {
    "validationRunId": "val-xyz789",
    "result": "pass",
    "proofTrace": [...],
    "issues": []
  }
}
```

### B.2 `validate_task(task_id, change) → ValidationRun`

```json
// 输入
{
  "task_id": "task-001",
  "change": {
    "kind": "transition_status",
    "payload": {"status": "completed"}
  }
}

// 输出
{
  "validationRunId": "val-xyz789",
  "taskId": "task-001",
  "result": "pass",
  "engine": "layer1-python",
  "engineVersion": "1.0.0",
  "inputFactsHash": "sha256:...",
  "rulesetHash": "sha256:...",
  "durationMs": 12,
  "derivedFacts": ["Done(task-001)"],
  "proofTrace": [
    {"step": "rule_R-005", "passed": true, "evidence": "..."}
  ],
  "issues": []
}
```

### B.3 `explain(task_id) → {summary, proof_trace, repair_suggestions}`

```json
// 输入
{ "task_id": "task-001" }

// 输出
{
  "taskId": "task-001",
  "summary": "Task task-001 was blocked by task-002 (not completed). Validation rule R-002 prevented transition to in_progress.",
  "proofTrace": [
    {"rule": "R-001", "result": "violated", "evidence": "Blocked(task-001) because Done(task-002)=false"}
  ],
  "repairSuggestions": [
    {
      "kind": "complete_prerequisite",
      "target": "task-002",
      "description": "Complete task-002 before starting task-001",
      "priority": 1
    }
  ]
}
```

### B.4 `audit(task_id, since?) → list[AuditEvent]`

```json
// 输入
{ "task_id": "task-001", "since": "2026-07-20T00:00:00Z" }

// 输出
[
  {
    "eventId": "evt-001",
    "timestamp": "2026-07-22T10:30:00Z",
    "type": "proposal",
    "taskId": "task-001",
    "actor": "orchestrator",
    "details": {"changeKind": "transition_status", "payload": {...}}
  },
  {
    "eventId": "evt-002",
    "timestamp": "2026-07-22T10:30:01Z",
    "type": "validation_run",
    "taskId": "task-001",
    "details": {"validationRunId": "val-xyz789", "result": "pass"}
  },
  {
    "eventId": "evt-003",
    "timestamp": "2026-07-22T10:30:02Z",
    "type": "commit",
    "taskId": "task-001",
    "details": {"commitId": "cmt-abc", "committed": true}
  }
]
```

---

## 附录 C：参考文档

- `docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.3 — 原始耦合点评估
- `docs/COMMERCIALIZATION_PLAN.md` — 商业化总方案
- `docs/ARCHITECTURE.md` — 三层架构总览
- `extensions/capabilities/tool_protocol.py` — Protocol 契约
- `CLAUDE.md` §「二次开发解耦原则」— 解耦设计原则
- `tests/logical_kanban/` — 现有测试套件（迁移源）
- `clawcodex_ext/feature_gate/registry.py` — 原 feature_gate 实现（参考降级版设计）

---

> 维护：本文档是 logical_kanban 解耦的 **唯一权威设计源**。任何代码层面的改动若与本文档不一致，必须先更新本文档再改代码。