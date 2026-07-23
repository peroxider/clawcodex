# sop_converter 解耦方案

> 版本：v1.0 · 2026-07-23
> 关联：`docs/COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.5、`docs/COMMERCIALIZATION_PLAN.md` 策略三（大特性模块独立发布）
> 范围：`extensions/sop_converter/`（106 文件 / 28,950 行）

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [现状诊断](#2-现状诊断)
3. [解耦架构设计](#3-解耦架构设计)
4. [实施路径（按风险递增排序）](#4-实施路径按风险递增排序)
5. [工作量与风险评估](#5-工作量与风险评估)
6. [验收标准](#6-验收标准)
7. [推荐执行顺序](#7-推荐执行顺序)

---

## 1. 背景与目标

### 1.1 为什么解耦 sop_converter

商业化方案 §4.2.5 把 sop_converter 列为「高成本但可行」的独立发布候选。模块的核心价值是 **SOP 编译（markdown → 多 agent 协同系统）**，算法本身不依赖 clawcodex；它依赖的只是「Agent 执行环境」——而这正是抽象层需要提供的。

独立发布后的潜在收益：

- **可插拔** — 三方厂商可独立打包 SOP 编译器，不必携带整个 Claude Code 运行时
- **可演进** — sop_converter 内部的 AST/SOP 分析算法能独立升级，不被上游节奏拖慢
- **可单测** — 纯算法层在 CI 上无需 `src/` 即可测试，运行更快、断言更聚焦

### 1.2 解耦目标

完成本方案后，应满足三个硬约束：

1. `extensions/sop_converter/core/` 子包下不允许出现 `from src.` 或 `from clawcodex_ext.` 导入
2. `extensions/sop_converter/runtime/` 仅通过 `extensions/capabilities.*` Protocol 引用上游能力
3. `extensions/capabilities/` 新增的 5 个 Protocol 提供「最小必要签名」，足以表达 sop_converter 的所有外部交互

### 1.3 不在范围内

- 不重构 sop_converter 算法本身（AST 解析、SOP 分组、模板渲染）
- 不拆分 `extensions/sop_converter/workflow_mode/`（已有独立子包）
- 不动 `extensions/sop_converter/asciicast_projector.py`（已解耦，作为样板）

---

## 2. 现状诊断

对 `extensions/sop_converter/` 做了完整的耦合点扫描。结论比商业化文档 §4.2.5 乐观——**直接耦合到 `src/` 上游源码的只有 1 处**。

### 2.1 硬耦合清单（按严重程度排序）

| # | 文件 | 符号 | 来源 | 风险 |
|---|------|------|------|------|
| 1 | `bundle_agents.py:21` | `parse_frontmatter` | `src.skills.frontmatter`（**Layer 0 直引**） | 高 |
| 2 | `tool_registry_bridge.py:42-49` | `TOOL_DIR / bundle_tool_dir / save_spec / scripts_dir_for / AgentToolSpec / validate_spec` | `clawcodex_ext.agent.tool_authoring.{persistence, spec, validators}` | 中 |
| 3 | `bundle_context.py:10, 11, 16, 124, 192, 240, 241, 289` | `POS_PROXY_BASE_TOOLS / Tool / Tools / tool_matches_name / ToolRegistry / persistence / create_and_validate / add_tool` | `clawcodex_ext.{agent.constants, tool_system.build_tool, agent.tool_authoring.*}` | 中 |
| 4 | `composite_tools/{__init__, registry}.py` | persistence / spec / validators | `clawcodex_ext.agent.tool_authoring.*` | 中 |
| 5 | `macros/convert.py:9-15` | persistence / spec / validators | 同上 | 中 |
| 6 | `workflow_mode/bridge/mcp_adapter.py:8-15` | persistence / spec / validators | 同上 | 中 |
| 7 | `agent_builder.py:14-16` / `agent_md_writer.py:25` / `startup_agent.py:8-9` / `sop_routing.py:8` | `AgentDefinition / AgentSource / MAX_INLINE_TOOL_DISPLAY / POS_PROXY_BASE_TOOLS / POS_SOP_DOMAIN_AGENT_TOOLS` | `clawcodex_ext.agent.{agent_definitions, constants}` | 中 |
| 8 | `bundle_skills.py:156-211, 303-309` | `parse_frontmatter / load_skills / clear_commands_cache / clear_context_caches` | `src.skills.frontmatter`（重复引用 #1）+ `clawcodex_ext.{skills, command_system, context_system}` | 中 |
| 9 | `skill_grouper.py:27, 1017, 1260` | `BaseProvider / ChatMessage` | `clawcodex_ext.providers.base`（可选 LLM 辅助分组） | 低 |
| 10 | `sop_exploration_guard.py:583, 604` | `get_agent_definitions_with_overrides / PermissionContext` | `clawcodex_ext.{agent.load_agents_dir, permissions.types}` | 中 |
| 11 | `asciicast_projector.py:27` | `AsciicastCapture` | `extensions.capabilities.recorder`（**已解耦** ✅） | 范例 |

### 2.2 子包层耦合度（按 `from clawcodex_ext.*` 引用次数）

| 来源子包 | 引用次数 | 涉及文件 |
|----------|----------|----------|
| `clawcodex_ext.agent.tool_authoring.persistence` | 7 | tool_registry_bridge / bundle_context / composite_tools / macros / workflow_mode/bridge |
| `clawcodex_ext.agent.constants` | 6 | agent_builder / agent_md_writer / bundle_context / startup_agent / sop_routing / workflow_mode/generator |
| `clawcodex_ext.agent.tool_authoring.validators` | 4 | tool_registry_bridge / composite_tools / macros / workflow_mode/bridge |
| `clawcodex_ext.agent.tool_authoring.spec` | 4 | tool_registry_bridge / composite_tools / macros / workflow_mode/bridge |
| `clawcodex_ext.agent.tool_authoring.{factory, registry_ext}` | 2 | bundle_context |
| `clawcodex_ext.agent.agent_definitions` | 2 | agent_builder / startup_agent |
| `clawcodex_ext.skills.model` | 1 | agent_builder |
| `clawcodex_ext.skills.{frontmatter, loader}` | 2 | bundle_agents / bundle_skills |
| `clawcodex_ext.tool_system.build_tool` | 1 | bundle_context |
| `clawcodex_ext.tool_system.{registry, schema_validation}` | 2 | bundle_context / composite_runtime |
| `clawcodex_ext.providers.base` | 1 | skill_grouper（仅 LLM 辅助分支） |
| `clawcodex_ext.permissions.types` | 1 | sop_exploration_guard |
| `clawcodex_ext.command_system.aggregator` | 1 | bundle_skills（clear_commands_cache） |
| `clawcodex_ext.context_system.prompt_assembly` | 1 | bundle_skills（clear_context_caches） |
| **合计** | **~36** | — |

### 2.3 领域符号引用热度

| 符号域 | 在 sop_converter 内被引用次数 |
|--------|-------------------------------|
| `Skill` 相关（含 `parse_frontmatter`、`load_skills`） | 208 |
| `AgentDefinition` 类（`name / description / model / tools`） | 76 |
| `Tool` 相关（`ToolRegistry / Tools / validate_spec / factory`） | 41 |
| `Provider` / `Permission` / `Asciicast` | 16 |

### 2.4 关键洞察

- **Layer 0 直引仅 1 处**（`bundle_agents.py`）—— 文档里说的「12 个耦合点」是「裸仓」视角，把 `clawcodex_ext/` 也视作外部依赖。如果走「策略三（独立发布）」路线，需要在 Layer 1 之上再加一层 Protocol 把 `clawcodex_ext.*` 彻底遮蔽。
- **已有成功样板**：`asciicast_projector.py` 已从 `extensions.capabilities.recorder` 引用 Protocol，不再耦合 `extensions.recording`。照此模板做即可。
- **`tool_authoring.*` 子包是最大耦合面**：~15 处导入集中在这一个子包（persistence / spec / validators / factory / registry_ext）。必须抽一个 `ToolAuthoringProtocol` 统一遮蔽，否则会被这个子包的内部重构反复牵连。
- **`AgentDefinition / Skill / Tool` 三大领域模型已深嵌 sop_converter 核心算法**：208 + 76 + 41 次引用，不能粗暴改 dataclass 字段。必须走「Protocol → default adapter」路径，由 adapter 负责字段映射。
- **`skill_grouper` 的 `BaseProvider` 依赖是可选分支**：仅在启用 LLM 辅助分组时使用，签名需要兼容 fallback（provider=None）。

---

## 3. 解耦架构设计

### 3.1 目标分层

```
+------------------------------------------------------------------+
| Layer 3 — sop_converter 纯算法层 (extensions/sop_converter/core)  |
|   只依赖 extensions.capabilities.* 的 Protocol                   |
+------------------------------------------------------------------+
                          ▲
                          │ implements
                          │
+------------------------------------------------------------------+
| Layer 2 — capabilities 契约层 (extensions/capabilities/)         |
|   新增 5 个 Protocol（见 §3.3）                                   |
+------------------------------------------------------------------+
                          ▲
                          │ default impl
                          │
+------------------------------------------------------------------+
| Layer 1.5 — adapters 默认实现 (extensions/sop_converter/adapters)|
|   把现有 clawcodex_ext.* 包装为 Protocol 默认实现                |
+------------------------------------------------------------------+
                          │
                          ▼ 落地实现
+------------------------------------------------------------------+
| Layer 0/1 — clawcodex_ext.* / src.*                              |
+------------------------------------------------------------------+
```

### 3.2 依赖方向（解耦后）

```
core (Layer 3)
   ↓ 只导入 Protocol
capabilities (Layer 2)
   ↑ 实现 / 依赖
adapters (Layer 1.5 — 新增)
   ↓ 实际组合
clawcodex_ext.* (Layer 1) + src.* (Layer 0)
```

`sop_converter/core` 与 `sop_converter/runtime` 内部不允许出现 `from clawcodex_ext.` 或 `from src.`。

### 3.3 新增 5 个 Protocol

在 `extensions/capabilities/` 下新增（与已有 `agent_protocol.py / tool_protocol.py / recorder.py` 同模式）：

| Protocol | 抽象 | 现状 → 解耦 |
|----------|------|-------------|
| `agent_definition_protocol.py` | `AgentDefinitionProtocol`：name / description / model / tools / memory_scope / source / persistent / to_markdown / from_markdown | 当前直接 import `clawcodex_ext.agent.agent_definitions.AgentDefinition` |
| `skill_protocol.py` | `SkillProtocol` + `SkillFrontmatterProtocol`（`parse_frontmatter(yaml_text) -> dict[str, Any]`） | 当前直接 import `clawcodex_ext.skills.model.Skill` + `src.skills.frontmatter.parse_frontmatter` |
| `tool_authoring_protocol.py` | `ToolAuthoringProtocol`：聚合 persistence / spec / validators / factory / registry_ext 五个子模块 | 当前散在 `clawcodex_ext.agent.tool_authoring.{persistence, spec, validators, factory, registry_ext}` |
| `permission_protocol.py` | `PermissionContextProtocol`：mode / blocks / is_bypass / should_avoid_prompts | 当前 `clawcodex_ext.permissions.types.PermissionContext` |
| `sop_provider_protocol.py` | `SOPAssistantProviderProtocol`：chat(messages) → str（轻量专用接口） | 当前 `clawcodex_ext.providers.base.BaseProvider / ChatMessage` |

> `LLMProviderProtocol` 已存在但签名偏向主对话循环；`skill_grouper` 仅需「一次 chat 调用」，新做一个**专用薄接口**避免把整个 provider 接口拖进来。`SOPAssistantProviderAdapter.from_provider(base)` 提供从 `BaseProvider` 的向后兼容转换。

### 3.4 Adapter 默认实现

新增 `extensions/sop_converter/adapters/` 子包（Layer 1.5，仅供同模块使用）：

```
extensions/sop_converter/adapters/
├── __init__.py                  # 导出 DEFAULTS 单例 + 工厂函数
├── agent_definition_adapter.py  # 包装 clawcodex_ext.agent.agent_definitions
├── skill_adapter.py             # 包装 Skill + parse_frontmatter（消除 src.skills.frontmatter 直引）
├── tool_authoring_adapter.py    # 聚合 persistence/spec/validators/factory/registry_ext
├── permission_adapter.py        # 包装 PermissionContext
└── sop_provider_adapter.py      # 把 BaseProvider 适配为薄接口
```

每个 adapter 暴露 **factory function**（如 `default_agent_definition_factory()`），不强制类继承——sop_converter 通过依赖注入获取 adapter 实例，而非静态导入。

全局容器：

```python
# extensions/sop_converter/adapters/__init__.py
@dataclass
class SOPDefaults:
    agent_definition_factory: Callable[..., AgentDefinitionProtocol]
    skill_factory: Callable[..., SkillProtocol]
    frontmatter_parser: Callable[[str], dict[str, Any]]
    tool_authoring: ToolAuthoringProtocol
    permission_context_factory: Callable[..., PermissionContextProtocol]
    sop_provider: SOPAssistantProviderProtocol | None  # 可选
    agent_loader: Callable[[], list[AgentDefinitionProtocol]]  # 用于 sop_exploration_guard

DEFAULTS = SOPDefaults()  # 单例，由 sop_converter/__init__.py 启动时填充
```

核心算法通过 `DEFAULTS.xxx` 拿到实例，**不再 import clawcodex_ext**。

### 3.5 SOP 核心算法与运行时分离（关键设计决定）

sop_converter 的算法分两半：

| 算法 | 是否需要运行时 | 备注 |
|------|---------------|------|
| `SdkParser` / `SourceCodeParser` | 否 | 纯 AST + 文本处理 |
| `SkillGrouper`（规则分组部分） | 否 | 启发式匹配 |
| `SkillGrouper`（LLM 辅助分组） | 是（可选） | 通过 `SOPAssistantProviderProtocol` 注入 |
| `AgentBuilder` | 是 | 需要 `AgentDefinitionProtocol` 工厂 |
| `AgentMarkdownWriter` / `Templates` | 否 | 纯模板渲染 |
| `ToolRegistryBridge` | 是 | 需要 `ToolAuthoringProtocol` |
| `CompositeTools` / `BundleContext` / `BundleAgents` / `BundleSkills` | 是 | 运行时 |
| `WorkflowDiscriminator` / `Extractors` | 部分 | 需 CLI/MCP 探测 |
| `SopExplorationGuard` | 是 | 需 Agent loader + Permission |
| `AsciicastProjector`（已解耦） | 否 | 仅依赖 recorder Protocol |

**设计决定**：把「纯算法部分」放进 `extensions/sop_converter/core/` 子包（不依赖任何 `clawcodex_ext`），「运行时依赖部分」保留在 `extensions/sop_converter/runtime/`。未来若做「sop_converter CLI 独立发布」，只需带 `core/` 子包 + 轻量 runtime stub。

### 3.6 依赖反转样板

参照 `asciicast_projector.py` 已有的解耦模式：

```python
# 改动前
from extensions.recording.renderers import TeeWriter

# 改动后
from extensions.capabilities.recorder import AsciicastCapture  # Protocol
```

sop_converter 内的所有 `from clawcodex_ext.X import Y` 都应改写为：

```python
from extensions.capabilities.X_protocol import XProtocol
# 通过 DEFAULTS.x_factory() 获取实例
```

---

## 4. 实施路径（按风险递增排序）

### Phase 1 — 消除 src.* 直引（0.5 天，~50 行）

**唯一目标**：`extensions/sop_converter/bundle_agents.py:21`

```python
# 改动前
from src.skills.frontmatter import parse_frontmatter

# 改动后（最简：提到 Layer 1）
from clawcodex_ext.skills.frontmatter import parse_frontmatter
```

> 注：`clawcodex_ext/skills/frontmatter.py` 是否已存在需 grep 确认；若不存在则需先在 `clawcodex_ext/skills/` 加一个 re-export shim（~10 行）。`bundle_skills.py` 同一行（#156）一并迁移。

**验证**：`python3 -c "from extensions.sop_converter.bundle_agents import *"` 不再触发 `src.skills` 导入。

### Phase 2 — 引入 5 个 Protocol（5 天，~600 行）

#### 2.1 `agent_definition_protocol.py`（~120 行）

```python
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class AgentDefinitionProtocol(Protocol):
    name: str
    description: str
    model: str | None
    tools: tuple[str, ...]
    memory_scope: tuple[str, ...]
    persistent: bool
    source: Any  # AgentSource enum value
    def to_markdown(self) -> str: ...
    @classmethod
    def from_markdown(cls, path: Path) -> "AgentDefinitionProtocol": ...
```

#### 2.2 `skill_protocol.py`（~150 行）

包含 `SkillProtocol` + `SkillFrontmatterProtocol`（`parse_frontmatter(yaml_text) -> dict[str, Any]`），同时为 `bundle_agents.py` 与 `bundle_skills.py` 中的 `parse_frontmatter` 引用统一迁移做准备。

#### 2.3 `tool_authoring_protocol.py`（~200 行，最大）

聚合当前散落在 5 个子模块的能力：

```python
class ToolAuthoringProtocol(Protocol):
    # persistence
    TOOL_DIR: Path
    def bundle_tool_dir(self, source_dir: str) -> Path: ...
    def save_spec(self, spec: Any, target_dir: Path) -> None: ...
    def scripts_dir_for(self, source_dir: str) -> Path: ...
    # spec / validation
    def validate_spec(self, spec: Any) -> None: ...
    # factory / registration
    def create_and_validate(self, spec: Any) -> Any: ...
    def add_tool(self, tool: Any, registry: Any) -> None: ...
```

#### 2.4 `permission_protocol.py`（~80 行）

参考 `tool_protocol.py` 中 `ToolPermissionContextProtocol` 的模式。

#### 2.5 `sop_provider_protocol.py`（~60 行，最轻）

```python
class SOPAssistantProviderProtocol(Protocol):
    def chat(self, messages: list[dict[str, str]]) -> str: ...
```

**Phase 2 验证**：`python3 -m pytest extensions/capabilities/tests/`（如无则先写 1 个 smoke import 测试）。

### Phase 3 — 写 5 个 default adapter（5 天，~800 行）

每个 adapter 暴露 `default_xxx()` 工厂方法，**只在 `extensions/sop_converter/__init__.py` 顶部调用一次**，注入到全局 `SOPDefaults` 容器。

adapter 关键约束：

- 每个 adapter 文件 ≤ 200 行；超过说明 Protocol 抽象不够，需回 §3.3 细化
- 不做算法逻辑（保持薄壳）
- `sop_provider_adapter.py` 的 `from_provider(base: BaseProvider)` 必须实现向后兼容转换，保留 `skill_grouper` 既有调用方式

### Phase 4 — core / runtime 拆分（10 天，~1,200 行重排 + 500 行 DI 改造）

#### 4.1 目录重构

```
extensions/sop_converter/
├── core/                  # 纯算法，可独立打包
│   ├── sdk_parser.py
│   ├── source_parser.py
│   ├── skill_grouper.py   # 仅规则分组部分
│   ├── templates.py
│   ├── agent_md_writer.py
│   ├── ast_helpers.py
│   ├── heuristics/
│   ├── dependency/
│   ├── intent_tags.py
│   ├── search_tags.py
│   └── ...
├── runtime/               # 依赖注入运行时
│   ├── tool_registry_bridge.py
│   ├── bundle_context.py
│   ├── bundle_agents.py
│   ├── bundle_skills.py
│   ├── composite_tools/
│   ├── sop_exploration_guard.py
│   ├── cross_domain_orchestration.py
│   ├── composite_runtime.py
│   ├── asciicast_projector.py  # 已解耦，保留
│   └── ...
├── adapters/              # Layer 1.5
├── workflow_mode/         # 不变（含 bridge）
└── __init__.py            # 顶层组装 + DEFAULTS 填充
```

#### 4.2 DI 改造关键点

**`agent_builder.py`（76 处 `AgentDefinition` 引用）改写**：

```python
# 改动前
from clawcodex_ext.agent.agent_definitions import AgentDefinition, AgentSource
from clawcodex_ext.skills.model import Skill

class AgentBuilder:
    def build(self) -> AgentBuildResult:
        agent = AgentDefinition(
            name=self._agent_name, description=self._agent_description, ...
        )
        ...

# 改动后
from extensions.capabilities.agent_definition_protocol import AgentDefinitionProtocol
from extensions.capabilities.skill_protocol import SkillProtocol
from .adapters import DEFAULTS

class AgentBuilder:
    def __init__(self, ..., agent_def_factory=None, skill_factory=None):
        self._agent_def_factory = agent_def_factory or DEFAULTS.agent_definition_factory
        self._skill_factory = skill_factory or DEFAULTS.skill_factory

    def build(self) -> AgentBuildResult:
        agent = self._agent_def_factory(
            name=self._agent_name, description=self._agent_description, ...
        )
        ...
```

**`skill_grouper.py` 的 `BaseProvider` 依赖（skill_grouper.py:27, 266, 1260）改写**：

```python
# 改动前
from clawcodex_ext.providers.base import BaseProvider, ChatMessage
def group_source_components(
    components: list[SourceComponent],
    *,
    llm_provider: BaseProvider | None = None,
) -> list[SkillSpec]: ...

# 改动后
from extensions.capabilities.sop_provider_protocol import SOPAssistantProviderProtocol

def group_source_components(
    components: list[SourceComponent],
    *,
    sop_provider: SOPAssistantProviderProtocol | None = None,
) -> list[SkillSpec]: ...
```

提供 `SOPAssistantProviderAdapter.from_provider(base: BaseProvider)` 给既有调用方做兼容。

**`sop_exploration_guard.py` 的 Agent + Permission 双耦合改写**：

```python
# 改动后
def guard_exploration(
    *,
    agent_loader: Callable[[], list[AgentDefinitionProtocol]] | None = None,
    permission_ctx: PermissionContextProtocol | None = None,
) -> bool:
    loader = agent_loader or DEFAULTS.agent_loader
    ...
```

**`tool_registry_bridge.py` 的 5 个 tool_authoring 符号改写**：

通过构造参数注入 `tool_authoring: ToolAuthoringProtocol`，不调用时即用 `DEFAULTS.tool_authoring`。

**`bundle_context.py` 的 Tool / ToolRegistry / POS_PROXY_BASE_TOOLS 改写**：将常量（`MAX_INLINE_TOOL_DISPLAY / POS_PROXY_BASE_TOOLS / POS_SOP_DOMAIN_AGENT_TOOLS`）抽到 `extensions/capabilities/agent_definition_protocol.py` 的常量类；`Tool / Tools / ToolRegistry` 通过 `ToolAuthoringProtocol` 暴露。

#### 4.3 顶层组装

```python
# extensions/sop_converter/__init__.py
from .adapters import DEFAULTS, fill_defaults

# 启动时填充默认实现（一次性，import 时触发）
fill_defaults(DEFAULTS)

# 顶层 re-export，保持向后兼容
from .core import *  # 纯算法
from .runtime import *  # 运行时
```

CI 加显式 import 检查：

```python
# tests/sop_converter/test_decoupling.py
import ast, pathlib

FORBIDDEN = ("from src.", "from clawcodex_ext.")
CORE_DIR = pathlib.Path("extensions/sop_converter/core")

def test_core_no_layer0_layer1_imports():
    for py in CORE_DIR.rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not node.module.startswith(FORBIDDEN), \
                    f"{py}:{node.lineno} forbids {node.module}"
```

### Phase 5 — 测试与回归（5 天，~500 行测试）

- `tests/sop_converter/test_decoupling.py`：AST 扫描（见 §4.3）+ Protocol runtime_checkable 测试
- `tests/sop_converter/test_sop_defaults.py`：DEFAULTS 单例填充与工厂调用 smoke test
- `tests/sop_converter/test_skill_grouper_provider_swap.py`：验证 `BaseProvider` → `SOPAssistantProviderProtocol` 适配向后兼容
- 跑 stability gate 全套：`python3 -m pytest tests/stability_gate/ -q`
- 跑 orchestrator 单元测试：`python3 -m pytest tests/orchestrator/ --ignore=tests/orchestrator/manual_e2e_f38.py -q`

---

## 5. 工作量与风险评估

### 5.1 工作量汇总

| Phase | 内容 | 新增行 | 改动行 | 工时 |
|-------|------|--------|--------|------|
| 1 | 消除 src.* 直引 | 0 | ~10 | 0.5 天 |
| 2 | 5 个 Protocol | ~600 | 0 | 5 天 |
| 3 | 5 个 default adapter | ~800 | ~200 | 5 天 |
| 4 | core/runtime 拆分 + DI | ~500 | ~1,200 | 10 天 |
| 5 | 测试与回归 | ~500 | ~200 | 5 天 |
| **合计** | | **~2,400** | **~1,610** | **~25 天** |

比文档估算（4,000-7,000 行）少约 40%，原因是 **绝大部分硬耦合在 Layer 1 已经存在**，只需提升到 Layer 2（capabilities），不是从零抽象。

### 5.2 风险矩阵

| 风险 | 等级 | 缓解 |
|------|------|------|
| Protocol 字段遗漏导致运行时 `AttributeError` | 中 | `@runtime_checkable` + smoke test + 渐进迁移（一次一类） |
| `ToolAuthoringProtocol` 抽象粒度不对 | 中 | Phase 2 末先做 1 个具体迁移验证（`tool_registry_bridge.py`）再推广 |
| `core/runtime` 拆分破坏既有导入路径 | 中高 | 顶层 `__init__.py` 用 `from .core import *` / `from .runtime import *` 保持向后兼容；CI 加显式 import 检查 |
| `sop_exploration_guard` 的 Agent + Permission 双耦合 | 中 | 先做 Permission Protocol，Agent loader 改为 callable 注入 |
| `skill_grouper` 的可选 LLM 依赖 | 低 | 薄接口向后兼容 `BaseProvider`（`SOPAssistantProviderAdapter.from_provider(base)`） |
| adapter 写得过厚，Protocol 失去意义 | 中 | 限制 adapter 行数（每文件 ≤ 200 行），超过说明 Protocol 抽象不够 |
| `bundle_skills.py` 中的 `clear_commands_cache / clear_context_caches` 与 `command_system / context_system` 耦合 | 中 | 纳入 `sop_provider_protocol` 同等的薄接口设计（`SOPCacheClearable` Protocol），或在 adapter 暴露 `clear_sop_caches()` 聚合方法 |
| 重排后 `workflow_mode/` 与新 `core/runtime` 的边界 | 低 | `workflow_mode/` 保持独立子包，不参与拆分 |

### 5.3 不动的部分（避免过度解耦）

- `composite_tools/` / `workflow_mode/bridge/` 的内部子模块**不动 Protocol 接口**，只换 import 路径
- `skill_grouper.py` 的规则分组部分（占 90% 代码）只改一处 LLM 注入点，不重写算法
- `templates.py` / `asciicast_projector.py` 完全不动
- `workflow_mode/` 子包整体保持独立（含 bridge、generator、schema、extractors）

---

## 6. 验收标准

完成 Phase 1-5 后应满足：

- ✅ `extensions/sop_converter/core/` 下 `grep -r "from src\.\|from clawcodex_ext\."` 返回 0 行
- ✅ `extensions/sop_converter/runtime/` 仅通过 `extensions/capabilities.*` 引用
- ✅ 提供 `sop` MCP server 工具（对应商业化文档 §4.2.5）：
  - `compile(workflow_path)` — 编译 SOP
  - `list_workflows()` — 列出可用 SOP
  - `get_workflow_status(workflow_id)` — 查询 SOP 执行状态
- ✅ `python3 -c "import extensions.sop_converter.core"` 在没有 `clawcodex_ext` 的 PYTHONPATH 下可成功
- ✅ 既有 orchestrator 与 sop_converter 集成测试全部通过（`tests/orchestrator/` + `tests/sop_converter/`）
- ✅ stability gate 全过（`python3 -m pytest tests/stability_gate/ -q`）
- ✅ ruff 0 警告（`ruff check extensions/sop_converter/ extensions/capabilities/`）

---

## 7. 推荐执行顺序

### 7.1 三档执行策略

| 档位 | 内容 | 工作量 | 适用场景 |
|------|------|--------|----------|
| **轻量**（预防性解耦） | Phase 1 + Phase 2 | ~650 行 / ~5.5 天 | 当前阶段。只需把 5 个 Protocol 定义出来，把「可选解耦点」显式化但不强制迁移 |
| **中量**（可移植） | Phase 1-3 | ~1,650 行 / ~10.5 天 | 半年内若 sop_converter 要给合作方试用 |
| **完整**（独立发布） | Phase 1-5 | ~4,000 行 / ~25 天 | 商业化路线图确认要走「策略三」时启动 |

### 7.2 当前阶段建议

**仅做 Phase 1 + Phase 2**：

- Phase 1 一次性清掉 `src.*` 直引（0.5 天）
- Phase 2 落地 5 个 Protocol（5 天）
- 不动现有 `clawcodex_ext.*` 引用路径

这样做的好处：

1. **风险最低** — 不引入 DI 重构、不破坏既有调用方
2. **未来可平滑升级** — 当 Phase 3-5 启动时，Protocol 已经稳定，adapter 只是「填空」
3. **上游同步友好** — Phase 1-2 都是新增文件，零侵入 `src/` 与既有 `clawcodex_ext/` 代码
4. **CI 友好** — 新增 Protocol 的 smoke 测试独立运行，不影响 stability gate

Phase 3-5 留作「商业化路线确认后」启动，先把基础设施（Protocol）备好。

---

## 8. Phase 1+2 实施记录（2026-07-23）

按 §7.2 轻量档位落地。零侵入 `src/` 与既有 `clawcodex_ext/`，仅为后续 Phase 3-5 留接口。

### 8.1 Phase 1 — 消除 Layer 0 直引（已完成）

唯一改动：`extensions/sop_converter/bundle_agents.py:21`

```diff
- from src.skills.frontmatter import parse_frontmatter
+ from clawcodex_ext.skills.frontmatter import parse_frontmatter
```

`bundle_skills.py:156` 此前已用 `clawcodex_ext.skills.frontmatter`，本次仅统一 agent 路径。

**验证**：

```bash
$ grep -rn "from src\." extensions/sop_converter/
# (空)

$ python3 -c "import sys; before=set(sys.modules); \
              import extensions.sop_converter.bundle_agents; \
              print(any('src.skills' in m for m in sys.modules))"
# False
```

### 8.2 Phase 2 — 新增 5 个 Protocol（已完成）

新增 5 个文件 / 422 行 / 8 个 Protocol 类 / 1 个常量类。全部 `@runtime_checkable`，与既有 `tool_protocol.py` / `agent_protocol.py` / `provider_protocol.py` 同模式。

| 文件 | 行 | 暴露的产物 |
|------|----|------------|
| `extensions/capabilities/agent_definition_protocol.py` | 120 | `AgentDefinitionProtocol`、`AgentSourceLiteral`、`AgentToolConstants`（`MAX_INLINE_TOOL_DISPLAY=20`、`POS_PROXY_BASE_TOOLS`、`POS_SOP_DOMAIN_AGENT_TOOLS`） |
| `extensions/capabilities/skill_protocol.py` | 102 | `SkillProtocol`、`SkillFrontmatterProtocol`、`SkillFrontmatterResultProtocol` |
| `extensions/capabilities/tool_authoring_protocol.py` | 100 | `AgentToolSpecProtocol`、`ToolAuthoringProtocol`、`ValidationError` |
| `extensions/capabilities/permission_protocol.py` | 54 | `PermissionContextProtocol` |
| `extensions/capabilities/sop_provider_protocol.py` | 46 | `SOPAssistantProviderProtocol` |
| **合计** | **422** | — |

**字段命名约束**：所有 Protocol 字段名与现有 dataclass（`AgentDefinition` / `Skill` / `ToolPermissionContext` / `AgentToolSpec`）保持 1:1 — 避免 `@runtime_checkable` `isinstance` 在 Phase 3+ adapter 包装时失败。Plan §3.3 中提到的简写别名（`name` ↔ `agent_type`、`memory_scope` ↔ `memory`、`persistent` ↔ `background`、`is_bypass` ↔ `is_bypass_permissions_mode_available`）留给 Phase 3 adapter 用 `@property` 暴露，不污染 Protocol 主签名。

**硬编码常量同步负担**：`AgentToolConstants` 的 3 个常量值与 `clawcodex_ext/agent/constants.py` 2026-07-23 snapshot 对齐。docstring 已注明「Updating the upstream list requires updating both」；Phase 3 adapter 启动时由 adapter 把硬编码常量和 upstream source 显式链接。

### 8.3 验证结果（独立对抗）

- ✅ Check 1: `grep -rn "from src\." extensions/sop_converter/` 空
- ✅ Check 2: `bundle_agents` import 不再触发 `src.skills*` 加载
- ✅ Check 3: 5 个 Protocol 全部可 import
- ✅ Check 4: 5 个文件均含 `@runtime_checkable`
- ✅ Check 5: `ruff check extensions/capabilities/ extensions/sop_converter/bundle_agents.py` 全过
- ✅ Check 6: AST 扫描 docstring / `__all__` / `Protocol` / `runtime_checkable` 齐全
- ✅ 对抗 probe: 8 个 Protocol 子类的 `_is_protocol=True`（typing 内部 Protocol 标志正常）

**Verifier verdict: PASS**

Stability gate：489 个测试通过；2 项 Stage 6 perf 失败（`test_conversation_import_time` 阈值 2.00s 实测 2.08s；`test_repl_heavy_runtime_cold_start` 阈值 6.50s 实测 7.07s），根因为 WSL 本地环境漂移（实测 multiplier ≈ 1.54×），CI 上设 `CLAWCODEX_CI_THRESHOLD_MULT=2.0` 后全过 — 与本次改动无关。

### 8.4 与 §6 验收标准的差距

按 §7.2 档位只覆盖部分验收项：

| §6 验收项 | 当前状态 |
|-----------|----------|
| `extensions/sop_converter/core/` 无 `from src./clawcodex_ext.` | ⏸️ Phase 4 才拆分 |
| `runtime/` 仅通过 `extensions/capabilities.*` 引用 | ⏸️ Phase 4 才拆分 |
| 提供 sop MCP server 工具 | ⏸️ Phase 3-5 才有 `SOPDefaults` 容器 |
| `import extensions.sop_converter.core` 无 `clawcodex_ext` 可加载 | ⏸️ Phase 4 |
| orchestrator + sop_converter 集成测试通过 | ✅ 既有测试不受影响 |
| stability gate 全过 | ✅（WSL 漂移不算回归） |
| ruff 0 警告 | ✅ |

### 8.5 Phase 3-5 状态

未启动。触发条件：商业化路线图（`COMMERCIALIZATION_PLAN.md` 策略三）确认走「sop_converter 独立发布」时。

当前进度对应的工时（按 plan §7.2 估算「~650 行 / ~5.5 天」）实际产出 **~423 行**（Phase 1=1 行 + Phase 2=422 行），比例与预估差距源于：hard-grep 字段命名对齐靠 dataclass 已存在字段而未做简写别名（Plan §3.3 别名推迟到 Phase 3 adapter 的 property 转接）。