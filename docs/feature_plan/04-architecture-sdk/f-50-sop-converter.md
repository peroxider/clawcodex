# F-50: SOP 转换器源码固化（子特性 A-G）

> 状态: 📋 规划中（子特性 A-G 待实现）
> 章节: docs/feature_plan/04-architecture-sdk/f-50-sop-converter.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 背景与目标

SOP 转换器主体（`SourceCodeParser` + 增强 `SkillGrouper` + `AgentMarkdownWriter`）已固化（F-50 核心 + F-55 分组策略增强 ✅）。本节记录未实现的子特性 F-50-A~G，用于将 SOP 转换扩展为工作流式的 Agents 协作脚本。

### 1.2 子特性总览

| 子特性 | 名称 | 描述 | 状态 | 优先级 |
|--------|------|------|:----:|:------:|
| F-50-A | 工作流判别器 | 解析 SOP markdown 头部，决定是否需要多阶段工作流 | 📋 | P1 |
| F-50-B | 工作流结构提取器 | 从源码各节提取 phase/stage/workflow，构建 DAG | 📋 | P0 |
| F-50-C | 阶段能力映射器 | 将 phase→capability 映射到可用 Agent 类型 | 📋 | P1 |
| F-50-D | 工作流 Schema 生成器 | 从阶段 DAG + Agent map 生成 workflow.yaml | 📋 | P0 |
| F-50-E | Agent 定义生成器 | 从工作流模式生成 agent 定义 markdown | 📋 | P0 |
| F-50-F | 源码桥接器生成器 | 从 SourceOperation → Tool → CLI 桥接 | 📋 | P1 |
| F-50-G | 提取器适配器库 | 多种 markdown 结构适配（规范/非规范） | 📋 | P1 |

### 1.3 F-50-A: 工作流判别器

**目标**: 自动判断输入源码是否具备固定编排工作流特征，决定使用标准 SDK 模式还是工作流模式。

**判别特征**（启发式评分）：

| 特征 | 检测方式 | 权重 | 匹配模式 |
|------|---------|:----:|---------|
| 阶段枚举 | `IntEnum`/`Enum` 子类 | 0.25 | `class Stage(IntEnum)` |
| 状态转换 | 字典字面量，键值均为枚举值 | 0.20 | `NEXT_STAGE = {A: B}` |
| IO 契约 | dataclass 含 `input_files`/`output_files` | 0.20 | `StageContract(...)` |
| 控制流决策 | 函数含 `pivot`/`refine`/`proceed`/`gate` | 0.15 | `def decide_pivot(...)` |
| 阶段实现目录 | 目录名 `stage_impls/`/`stages/`/`pipeline/` | 0.10 | 含多个阶段实现文件 |
| GATE 定义 | `frozenset`/`set` 命名含 `GATE` | 0.10 | `GATE_STAGES = frozenset(...)` |

**判别结果**: score < 0.3 → 标准 SDK 模式 | 0.3~0.7 → 混合模式 | ≥ 0.7 → 工作流模式

**CLI 集成**:
```bash
clawcodex-dev sop convert <source_dir>              # 自动判别（默认）
clawcodex-dev sop convert <source_dir> --mode sdk    # 强制标准模式
clawcodex-dev sop convert <source_dir> --mode fwa    # 强制工作流模式
```

**实现文件**:
| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/discriminator.py` | `WorkflowDiscriminator` 核心 | 📋 |
| `extensions/sop_converter/workflow_mode/heuristics.py` | 6 种启发式检测规则 | 📋 |
| `extensions/sop_converter/workflow_mode/models.py` | `DiscriminationResult` 数据模型 | 📋 |

### 1.4 F-50-B: 工作流结构提取器

**目标**: 从目标应用的 Python 源码中提取阶段定义、转换规则、GATE 逻辑、DECISION 回环为 `WorkflowGraph`。

**架构：可插拔提取器模式**
```python
class WorkflowExtractorBase(ABC):
    @abstractmethod
    def extract_stages(self, source_dir: Path) -> list[StageNode]: ...
    @abstractmethod
    def extract_transitions(self, source_dir: Path) -> list[Transition]: ...
    @abstractmethod
    def extract_gates(self, source_dir: Path) -> dict[int, GateSpec]: ...
    @abstractmethod
    def extract_decisions(self, source_dir: Path) -> dict[int, DecisionSpec]: ...
    @abstractmethod
    def extract_contracts(self, source_dir: Path) -> dict[int, StageContract]: ...

    def extract(self, source_dir: Path) -> WorkflowGraph:
        return WorkflowGraph(stages=..., transitions=..., gates=..., decisions=..., contracts=...)
```

**子特性**:
| 编号 | 名称 | 状态 | 描述 |
|------|------|:----:|------|
| F-50.11.1 | 提取器基类 + 通用 AST 策略 | 📋 | 抽象基类 + 5 种通用启发式提取 |
| F-50.11.2 | 提取器注册表 | 📋 | 按项目名自动选择提取器 |
| F-50.11.3 | 提取结果预览模式 | 📋 | `--preview` 输出人类可读摘要 |
| F-50.11.4 | 交互式补全模式 | 🔭 | 提取失败时生成 `TODO:` 模板 |

**实现文件**:
| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/extractors/base.py` | `WorkflowExtractorBase` | 📋 |
| `extensions/sop_converter/workflow_mode/extractors/ast_helpers.py` | Python AST 通用分析工具 | 📋 |
| `extensions/sop_converter/workflow_mode/extractors/registry.py` | `ExtractorRegistry` | 📋 |
| `extensions/sop_converter/workflow_mode/extractors/models.py` | 数据模型 | 📋 |
| `extensions/sop_converter/workflow_mode/extractors/adapters/arc.py` | AutoResearchClaw 适配器 | 📋 |
| `extensions/sop_converter/workflow_mode/extractors/adapters/generic.py` | 通用 Python 管线适配器 | 📋 |

### 1.5 F-50-C: 阶段能力映射器

**目标**: 分析每个阶段的实现代码，提取外部依赖和能力特征，推荐执行模式（agent_native / wrapper / hybrid）。

**能力分类**: `LLM_CALL`, `ACADEMIC_API`, `WEB_SEARCH`, `CODE_EXECUTION`, `FILE_IO`, `EXTERNAL_CLI`, `DOMAIN_SPECIFIC`, `DATA_PROCESSING`, `HTTP_API`

**执行模式推荐矩阵**:
| | fragility < 0.3 | fragility 0.3~0.6 | fragility > 0.6 |
|---|---|---|---|
| complexity < 0.4 | agent_native | agent_native | wrapper |
| complexity 0.4~0.7 | agent_native | hybrid | wrapper |
| complexity > 0.7 | hybrid | wrapper | wrapper |

**实现文件**:
| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/capability/mapper.py` | `StageCapabilityMapper` | 📋 |
| `extensions/sop_converter/workflow_mode/capability/analyzer.py` | 复杂度/脆弱度评分 | 📋 |
| `extensions/sop_converter/workflow_mode/capability/patterns.py` | 已知 API/LLM/CLI 模式库 | 📋 |
| `extensions/sop_converter/workflow_mode/capability/models.py` | 数据模型 | 📋 |

### 1.6 F-50-D: 工作流 Schema 生成器

**目标**: 定义并生成声明式工作流 YAML 格式，支持 DAG、GATE、DECISION、回环、契约验证。

**Schema 核心结构**（精简）:
```yaml
schema_version: "1.0"
name: <workflow-name>
stages:
  - id: <int>
    name: <kebab-case>
    agent: <agent-type>
    phase: <phase-label>
    execution_mode: agent_native | wrapper | hybrid
    gate:
      enabled: <bool>
      approval_mode: manual | auto | threshold
    decision:
      outcomes:
        <outcome-name>:
          next: <stage-id>
          rollback_to: <stage-id>
          max_times: <int>
transitions:
  - from: <stage-id>
    to: <stage-id>
error_handling:
  on_stage_timeout: retry | retry_then_skip | halt
checkpoint:
  enabled: <bool>
  strategy: per_stage | per_phase
```

**实现文件**:
| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/schema/workflow_schema.py` | Schema 数据模型 | 📋 |
| `extensions/sop_converter/workflow_mode/schema/parser.py` | YAML 解析 + 验证 | 📋 |
| `extensions/sop_converter/workflow_mode/schema/dag_validator.py` | DAG 完整性检查 | 📋 |
| `extensions/sop_converter/workflow_mode/schema/validator_spec.py` | ValidatorSpec 类型定义 | 📋 |
| `extensions/sop_converter/workflow_mode/schema/discovery.py` | 工作流文件发现 | 📋 |

### 1.7 F-50-E: Agent 定义生成器

**目标**: 从 `WorkflowGraph` + `CapabilityProfile` 批量生成阶段 Agent 定义文件。

三种 Agent 模板:
- **Agent-native**: 完整 frontmatter + 任务描述 + 执行步骤 + 质量要求
- **Wrapper**: 精简版，核心为 `wrapper_command` + 输出验证
- **Hybrid**: 混合步骤指导 + Bridge 调用

**实现文件**:
| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/generator/agent_def_gen.py` | `AgentDefinitionGenerator` | 📋 |
| `extensions/sop_converter/workflow_mode/generator/templates/` | Jinja2 Agent 模板目录 | 📋 |
| `extensions/sop_converter/workflow_mode/generator/skill_gen.py` | Skill 定义生成 | 📋 |
| `extensions/sop_converter/workflow_mode/generator/tool_gen.py` | 工具注册代码生成 | 📋 |
| `extensions/sop_converter/workflow_mode/generator/overview_gen.py` | Overview Agent 生成 | 📋 |

### 1.8 F-50-F: 源码桥接器生成器

**目标**: 生成 Bridge 模块，使 Agent 可以通过 Python API 调用目标应用的单阶段执行。

**Bridge 架构**:
```
Agent (Wrapper 模式)
  ├── 方式 A: CLI Bridge — subprocess 调用目标应用 CLI
  └── 方式 B: Python Bridge — import 目标应用模块
          ├── Bridge 类（生成）
          │     ├── execute_stage(stage_id, project_dir, overrides)
          │     ├── validate_outputs(stage_id, project_dir)
          │     └── get_artifacts(stage_id, project_dir)
          └── MCP Tool 注册（生成）
```

**实现文件**:
| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/bridge/generator.py` | `BridgeGenerator` | 📋 |
| `extensions/sop_converter/workflow_mode/bridge/templates/` | Bridge 代码模板 | 📋 |
| `extensions/sop_converter/workflow_mode/bridge/mcp_adapter.py` | Bridge → MCP Tool 适配 | 📋 |
| `extensions/sop_converter/workflow_mode/bridge/health_check.py` | 安装检测与诊断 | 📋 |

### 1.9 F-50-G: 提取器适配器库

**目标**: 提供常见 FWA 项目的提取器适配器。

| 适配器 | 目标项目 | 优先级 |
|--------|---------|:------:|
| `ArcExtractor` | AutoResearchClaw | P0 |
| `GenericPipelineExtractor` | 通用 Python 管线 | P0 |

### 1.10 已实现的基础设施

| 组件 | 状态 | 位置 |
|------|:----:|------|
| SOP 转换器核心 | ✅ | `extensions/sop_converter/` |
| 分组策略增强（F-55） | ✅ | `skill_grouper.py` |
| SourceCodeParser | ✅ | SOP 解析基础设施 |
| AgentMarkdownWriter | ✅ | Agent 定义 markdown 生成 |

## §2 进度跟踪

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | SOP 转换器核心固化 | `extensions/sop_converter/` |
| 2026-06 | F-55 分组策略增强 | `skill_grouper.py` |

### 2.2 当前瓶颈

F-50-A~G 尚未开始实现。建议按 A→B→C→D→E→F→G 顺序推进。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-24 | 补全详细设计（子特性 A-G 完整设计） | 对齐 FEATURE_PLAN.legacy.md |
