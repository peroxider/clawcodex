# F-50: SOP 转换器源码固化（子特性 A-G）

> 状态: 🟡 部分完成（A/B/C/D/E/F/G ✅；F-50.11.4 🔭）
> 章节: docs/feature_plan/04-architecture-sdk/f-50-sop-converter.md
> 最后更新: 2026-07-21

## §1 设计规划

### 1.1 背景与目标

SOP 转换器主体（`SourceCodeParser` + 增强 `SkillGrouper` + `AgentMarkdownWriter`）已固化（F-50 核心 + F-55 分组策略增强 ✅）。子特性 F-50-A~G 将 SOP 转换扩展为工作流式 Agents 协作脚本：对 **Python 源码目录** 做 AST 扫描，判别是否具备固定编排特征，提取 `WorkflowGraph`，再生成 `workflow.yaml`、阶段 Agent 与 Bridge。

**命名说明**: F-50-B 提取 IR 使用 `ExtractedStage`（`extractors/models.py`），**不要**与 F-110 运行时 `StageNode`（`workflow_engine/workflow_state.py`，由 YAML 解析）混用。二者由 F-50-D emitter 衔接。

### 1.2 子特性总览

| 子特性 | 名称 | 描述 | 状态 | 优先级 |
|--------|------|------|:----:|:------:|
| F-50-A | 工作流判别器 | 扫描源码 AST，启发式评分，分流 sdk / hybrid / fwa | ✅ | P1 |
| F-50-B | 工作流结构提取器 | 从源码提取 phase/stage/workflow，构建 `WorkflowGraph`（Generic ✅；Arc ✅） | ✅ | P0 |
| F-50-C | 阶段能力映射器 | 将 phase→capability 映射到可用 Agent 类型 | ✅ | P1 |
| F-50-D | 工作流 Schema 生成器 | 从阶段 DAG + Agent map 生成 workflow.yaml | ✅ | P0 |
| F-50-E | Agent 定义生成器 | 从工作流模式生成 agent 定义 markdown | ✅ | P0 |
| F-50-F | 源码桥接器生成器 | wrapper/hybrid 阶段的 Python / CLI Bridge + Tool 注册 | ✅ | P1 |
| F-50-G | 提取器适配器库 | 按项目选择专用提取器（Generic ✅ / Arc ✅） | ✅ | P1 |

### 1.3 F-50-A: 工作流判别器

**目标**: 自动判断输入 **Python 源码目录** 是否具备固定编排工作流特征，决定使用标准 SDK 模式还是工作流模式。

**输入**: `sop convert <source_dir>` 时的目录路径（**不是** SOP markdown 头部；markdown 适配属于 F-50-G 范畴）。

**判别特征**（启发式评分，`heuristics.py` + 共享 `ast_helpers.py`）：

| 特征 | 检测方式 | 权重 | 匹配模式 |
|------|---------|:----:|---------|
| 阶段枚举 | `IntEnum`/`Enum` 子类 | 0.25 | `class Stage(IntEnum)`；类名/成员名含 `STAGE`/`PHASE`/`STEP`/`PIPELINE`（**不区分大小写、子串匹配**）；或 ≥2 个递增整型成员（权重 ×0.6） |
| 状态转换 | 模块级字典字面量 | 0.20 | `NEXT_STAGE = {Stage.A: Stage.B}`；或键名与枚举成员 >50% 重叠（弱匹配） |
| IO 契约 | `@dataclass` 字段 | 0.20 | 含 `input_files` 和/或 `output_files` |
| 控制流决策 | 函数名前缀 | 0.15 | `decide_*` / `should_*` / `check_gate` / `resolve_stage` / `resolve_*`（**非**函数体内字符串 `pivot`/`proceed`） |
| 阶段实现目录 | 目录名 | 0.10 | 根下存在 `stage_impls/` / `stages/` / `pipeline/` 且含 `.py` |
| GATE 定义 | 变量名含 `GATE` | 0.10 | `GATE_STAGES = frozenset({Stage.ANALYZE})` |

**判别结果**（`THRESHOLD_SDK=0.3`, `THRESHOLD_FWA=0.7`）:

| 模式 | 条件 |
|------|------|
| **sdk** | `total_score < 0.3` |
| **hybrid** | `0.3 ≤ total_score < 0.7`，或 `total_score ≥ 0.7` 但未通过 FWA 组合门 |
| **fwa** | `total_score ≥ 0.7` **且** FWA 组合门成立 |

**FWA 组合门**（`fwa_qualified`，实现多于早期「仅看分数」草案）:

- `(stage_enum ∧ state_transition)`，或
- `(stage_enum ∧ gate_definition)`

避免仅有 IO 契约 / 决策函数 / 阶段目录、但无阶段枚举与 DAG 的项目被标为 fwa，与 F-50-B/D 提取能力对齐。

**CLI 集成**:
```bash
clawcodex-dev sop convert <source_dir>                    # 自动判别（--mode auto，默认）
clawcodex-dev sop convert <source_dir> --mode sdk          # 强制标准模式
clawcodex-dev sop convert <source_dir> --mode hybrid       # 强制混合模式
clawcodex-dev sop convert <source_dir> --mode fwa          # 强制工作流模式
clawcodex-dev sop convert <source_dir> --preview           # 打印判别 + WorkflowGraph 摘要
clawcodex-dev sop convert <source_dir> --json --validate   # JSON 判别结果，仅校验不写文件
```

**实现文件**:

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/discriminator.py` | `WorkflowDiscriminator` 核心 | ✅ |
| `extensions/sop_converter/workflow_mode/heuristics.py` | 6 种启发式检测规则 | ✅ |
| `extensions/sop_converter/workflow_mode/models.py` | `DiscriminationResult` / 阈值常量 | ✅ |
| `extensions/sop_converter/workflow_mode/scan_context.py` | AST 扫描缓存（A/B 共享） | ✅ |
| `extensions/sop_converter/workflow_mode/pipeline.py` | `discriminate_and_extract` | ✅ |

**测试**: `tests/misc/test_workflow_discriminator.py`（fixture: `fixture_sdk_project` / `fixture_hybrid_project` / `fixture_fwa_project`）

### 1.4 F-50-B: 工作流结构提取器

**目标**: 从目标应用的 Python 源码中提取阶段定义、转换规则、GATE 逻辑、DECISION 回环为 `WorkflowGraph`。

**IR 类型**: 阶段节点为 `ExtractedStage`（非 F-110 `StageNode`）。

**架构：可插拔提取器模式**
```python
class WorkflowExtractorBase(ABC):
    @abstractmethod
    def extract_stages(self, source_dir: Path) -> list[ExtractedStage]: ...
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

**实现行为**:

- `disc.mode` 为 `sdk` 时不提取；`hybrid` / `fwa` 时调用 `ExtractorRegistry.get_extractor(...).extract(...)`。
- **`hybrid` 模式跳过 `extract_decisions`**（decisions 为空），fwa 才解析决策函数。
- 提取质量标记: `extraction_quality` = `full` | `partial` | `coarse`（目录/file 推断阶段时为 `inferred=True`）。
- 空图时 pipeline 回退 SDK-only 输出并打 warning。

**子特性**:

| 编号 | 名称 | 状态 | 描述 |
|------|------|:----:|------|
| F-50.11.1 | 提取器基类 + 通用 AST 策略 | ✅ | `WorkflowExtractorBase` + `GenericPipelineExtractor` |
| F-50.11.2 | 提取器注册表 | ✅ | `ExtractorRegistry`；未注册名回退 Generic |
| F-50.11.3 | 提取结果预览模式 | ✅ | `--preview` + `format_workflow_preview` |
| F-50.11.4 | 交互式补全模式 | 🔭 | 提取失败时生成 `TODO:` 模板（未实现） |

**实现文件**:

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/extractors/base.py` | `WorkflowExtractorBase` | ✅ |
| `extensions/sop_converter/workflow_mode/ast_helpers.py` | Python AST 通用分析（F-50-A/B 共享） | ✅ |
| `extensions/sop_converter/workflow_mode/extractors/registry.py` | `ExtractorRegistry` | ✅ |
| `extensions/sop_converter/workflow_mode/extractors/models.py` | `ExtractedStage` / `WorkflowGraph` 等 | ✅ |
| `extensions/sop_converter/workflow_mode/extractors/preview.py` | 人类可读摘要 | ✅ |
| `extensions/sop_converter/workflow_mode/extractors/adapters/generic.py` | 通用 Python 管线适配器 | ✅ |


**测试**: `tests/misc/test_workflow_extractor.py`, `tests/misc/test_arc_extractor.py`

### 1.5 F-50-C: 阶段能力映射器

**目标**: 分析每个阶段的实现代码，提取外部依赖和能力特征，推荐执行模式（agent_native / wrapper / hybrid）。

**能力分类**: `LLM_CALL`, `ACADEMIC_API`, `WEB_SEARCH`, `CODE_EXECUTION`, `FILE_IO`, `EXTERNAL_CLI`, `DOMAIN_SPECIFIC`, `DATA_PROCESSING`, `HTTP_API`

**执行模式推荐矩阵**（`capability/analyzer.recommend_execution_mode`）:

| | fragility < 0.3 | fragility 0.3~0.6 | fragility > 0.6 |
|---|---|---|---|
| complexity < 0.4 | agent_native | agent_native | wrapper |
| complexity 0.4~0.7 | agent_native | hybrid | wrapper |
| complexity > 0.7 | hybrid | wrapper | wrapper |

**实现文件**:

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/capability/mapper.py` | `StageCapabilityMapper` | ✅ |
| `extensions/sop_converter/workflow_mode/capability/analyzer.py` | 复杂度/脆弱度评分 | ✅ |
| `extensions/sop_converter/workflow_mode/capability/patterns.py` | 已知 API/LLM/CLI 模式库 | ✅ |
| `extensions/sop_converter/workflow_mode/capability/models.py` | 数据模型 | ✅ |
| `extensions/sop_converter/workflow_mode/capability/arc_mapper.py` | ARC 阶段 → per-stage Skill 合成 | ✅ |

**测试**: `tests/misc/test_stage_capability_mapper.py`, `tests/misc/test_arc_mapper.py`

### 1.6 F-50-D: 工作流 Schema 生成器

**目标**: 定义并生成声明式工作流 YAML 格式，支持 DAG、GATE、DECISION、回环、契约验证。

**实现要点**（对齐 A-B + F-110 模板）:
- **不**使用独立顶层 `transitions:` 列表；边信息 flatten 到 `stages[].depends_on`
- GATE/DECISION 采用 **合成独立阶段**（`kind: gate` / `kind: decision`），非 agent 节点内联
- compile-side 仅 `emitter.py` + `dag_validator.py`；**不**在 sop_converter 实现 `workflow_schema.py` / `parser.py`
- F-110 round-trip 校验 **仅 tests**（`WorkflowSchema.from_dict` + `build_dag_order`）
- 输出 YAML 顶层字段为 `version: "1.0"`（非 `schema_version`；与 F-110 解析器一致）

**Schema 核心结构**（精简）:
```yaml
version: "1.0"
name: <workflow-name>
stages:
  - id: <int>
    name: <label>
    kind: agent | gate | decision
    phase: <kebab-case>
    depends_on: [<int>, ...]
    prompt: |
      ...
    agent_config:
      execution_mode: agent_native | wrapper | hybrid
      agent: <agent-name>
      tools: [...]
    gate_mode: manual | auto | threshold      # kind: gate
    gate_rollback_to: <int>
    decision_outcomes:                        # kind: decision
      <outcome>:
        next: <int>
        rollback_to: <int>
        max_times: <int>
    validators:
      - type: file_exists
        path: <pattern>
config:
  workspace: "."
```

**CLI**: hybrid/fwa 模式自动 emit；可选 `--strict-workflow-yaml` 在校验失败时 abort。sdk 模式无 workflow graph，不 emit。

**实现文件**:

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/schema/emitter.py` | `graph_to_engine_yaml_dict` / `emit_engine_workflow_yaml` | ✅ |
| `extensions/sop_converter/workflow_mode/schema/dag_validator.py` | DAG 完整性检查 | ✅ |
| `extensions/sop_converter/workflow_mode/schema/validator_spec.py` | ValidatorSpec 类型定义 | ✅ |

**测试**: `tests/misc/test_sop_workflow_emitter.py`

### 1.7 F-50-E: Agent 定义生成器

**目标**: 从 `WorkflowGraph` + `StageAgentMap` 批量生成阶段 Agent 定义文件。

三种 Agent 模板:
- **Agent-native**: 完整 frontmatter + 任务描述 + 执行步骤 + 质量要求
- **Wrapper**: 精简版，核心为 `wrapper_command` + 输出验证
- **Hybrid**: 混合步骤指导 + Bridge 调用

**CLI**: hybrid/fwa 模式默认 `emit_stage_agents`；也可用 `--emit-stage-agents` 强制开启。

**实现文件**:

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/generator/agent_def_gen.py` | `AgentDefinitionGenerator` | ✅ |
| `extensions/sop_converter/workflow_mode/generator/templates/` | Jinja2 Agent 模板目录 | ✅ |
| `extensions/sop_converter/workflow_mode/generator/skill_gen.py` | Skill 定义生成 | ✅ |
| `extensions/sop_converter/workflow_mode/generator/tool_gen.py` | 工具注册代码生成 | ✅ |
| `extensions/sop_converter/workflow_mode/generator/overview_gen.py` | Overview Agent 生成 | ✅ |

**测试**: `tests/misc/test_agent_def_generator.py`

### 1.8 F-50-F: 源码桥接器生成器

**目标**: 生成 Bridge 模块，使 wrapper/hybrid 阶段 Agent 可通过 subprocess 调用单阶段执行。

**Bridge 架构**:
```
Agent (wrapper / hybrid)
  ├── 方式 A: CLI Bridge — subprocess 调用目标应用 CLI          ✅
  │     └── 生成脚本内嵌 CLI_PREFIX，调用:
  │           {cli} execute-stage --stage-id N --project-dir DIR [--stage-name NAME]
  └── 方式 B: Python Bridge — importlib 加载阶段模块            ✅
          ├── 生成脚本 (*_bridge.py)
          │     ├── execute_stage(stage_id, project_dir, overrides)
          │     ├── validate_outputs(stage_id, project_dir)
          │     └── get_artifacts(stage_id, project_dir)
          ├── health.json 诊断（health_check.py）
          └── AgentToolSpec 注册（mcp_adapter.py → *-execute-stage）
```

**CLI 入口发现**（方式 A，`cli_discovery.py`）:
- `--bridge-cli "<prefix>"` 显式指定（可含空格，如 `python path/to/app_cli.py`）
- 否则读取 `pyproject.toml` 的 `[project.scripts]`，优先匹配 `--name` / 目录名

**与 F-52 边界**: 逐方法 SDK Tool 注册由 `tool_registry_bridge.py` 承担（**源码目录 convert 默认开启**；`--no-register-tools` 可关）；F-50-F 仅负责 **按 stage_id 调度** 的 Bridge。

**CLI**: 需 `--emit-bridge`；`--bridge-mode python`（默认）或 `--bridge-mode cli`；可选 `--bridge-cli <cmd>`。

**实现文件**:

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/sop_converter/workflow_mode/bridge/generator.py` | `BridgeGenerator`（python / cli） | ✅ |
| `extensions/sop_converter/workflow_mode/bridge/cli_discovery.py` | CLI 入口发现 + `split_cli_prefix` | ✅ |
| `extensions/sop_converter/workflow_mode/bridge/dispatch.py` | 共享 stage dispatch 表 | ✅ |
| `extensions/sop_converter/workflow_mode/bridge/templates/python_bridge.py.j2` | Python Bridge 模板 | ✅ |
| `extensions/sop_converter/workflow_mode/bridge/templates/cli_bridge.py.j2` | CLI Bridge 模板 | ✅ |
| `extensions/sop_converter/workflow_mode/bridge/mcp_adapter.py` | Bridge → AgentToolSpec | ✅ |
| `extensions/sop_converter/workflow_mode/bridge/health_check.py` | 安装检测与诊断（python / cli） | ✅ |

**测试**: `tests/misc/test_bridge_generator.py`, `tests/misc/test_bridge_mcp_adapter.py`

### 1.9 F-50-G: 提取器适配器库

**目标**: 为常见 FWA 项目提供专用提取器（`_detect_adapter_name` 推荐 extractor 名，`ExtractorRegistry` 解析）。

| 适配器 | 目标项目 | 状态 | 优先级 |
|--------|---------|:----:|:------:|
| `GenericPipelineExtractor` | 通用 Python 管线 | ✅ | P0 |
| `ArcExtractor` | AutoResearchClaw（目录名/pyproject 含 autoresearch 或 `.arc-workflow`）；核心提取与映射已实现并通过单测 | ✅ | P0 |

未注册适配器名时回退 `GenericPipelineExtractor`。CLI: `--extractor <name>` 可覆盖自动选择。

### 1.10 CLI 工作流产物开关（汇总）

`sop convert <source_dir>` 在判别/提取之后：

| Flag |       默认       | 产物 |
|------|:--------------:|------|
| `--out <dir>` |       关        | bundle 根目录；**无此项则** Agent / yaml / bridge **不落盘** |
| `--emit-workflow-yaml` | 关（**hybrid/fwa 自动开**） | `{out}/workflow.yaml` |
| `--emit-stage-agents` | 关（**hybrid/fwa 自动开**） | 阶段 Agent markdown |
| `--emit-bridge` | 关（**hybrid/fwa 自动开**） | `{out}/bridge/*_bridge.py` + health.json |
| `--bridge-mode cli` |     python     | CLI Bridge（subprocess） |
| `--bridge-cli <cmd>` |      推断,只在 --bridge-mode cli 时生效       | 覆盖 CLI 入口 |
| SDK Tool 注册 |     **开**      | wrapper 脚本 + Tool spec → `{out}/agent-tools/` 或 `~/.clawcodex/agent-tools/` |
| `--no-register-tools` |       —        | 关闭 SDK 方法 Tool 注册 |
| `--preview` |       关        | 仅打印摘要，不写文件、不注册 Tool |
| `--validate` |       关        | 仅校验，不注册 Tool |

### 1.11 已实现的基础设施

| 组件 | 状态 | 位置 |
|------|:----:|------|
| SOP 转换器核心 | ✅ | `extensions/sop_converter/` |
| 分组策略增强（F-55） | ✅ | `skill_grouper.py` |
| SourceCodeParser | ✅ | SOP 解析基础设施 |
| AgentMarkdownWriter | ✅ | Agent 定义 markdown 生成 |
| Tool Registry Bridge（F-52 相关） | ✅ | `tool_registry_bridge.py` |
| Composite Tools（macro 层） | 🟡 | `composite_tools/`；CLI 已接线，stage agent 引用待泛化 |
| Type Schema（Pydantic → JSON Schema） | ✅ | `type_schema.py` |
| Bundle 运行时加载 | ✅ | `bundle_agents.py`, `bundle_workflow.py` |

## §3 设计答疑

本节汇总 F-50 / `sop convert` 实现与使用中的常见问题（以当前代码为准）。

### Q1. F-50-A 为何除了分数还有 FWA 组合门？

**A.** 仅 `total_score ≥ 0.7` 时，项目可能只有 IO 契约、决策函数、阶段目录等信号，**没有**阶段枚举与 DAG，仍会被标为 fwa，但 F-50-B/D 无法可靠提取流转关系。

**组合门**（`fwa_qualified`）要求：

- `(stage_enum ∧ state_transition)`，或
- `(stage_enum ∧ gate_definition)`

因此 **实现比早期「只看分数」的草案更严**；高分但未过组合门 → **hybrid**。

---

### Q2. 阶段枚举名必须大小写完全匹配 `STAGE`/`PHASE` 吗？

**A.** **不需要。** `ast_helpers._STAGE_NAME_RE` 使用 `re.IGNORECASE` 且为**子串匹配**：`Stage`、`Phase`、`PipelineStep` 均可。  
若无关键词但 ≥2 个递增整型枚举成员，仍可能以 ×0.6 权重识别为阶段枚举。

---

### Q3. `ExtractedStage` 和 F-110 的 `StageNode` 是什么关系？

**A.** **不同概念，不要混用。**

| | F-50-B `ExtractedStage` | F-110 `StageNode` |
|--|-------------------------|-------------------|
| 来源 | 源码 AST 提取 IR | `workflow.yaml` 解析后的运行时节点 |
| 衔接 | F-50-D emitter 生成 YAML | 工作流引擎执行 |

设计文档 §1.4 伪代码曾写 `StageNode`，实现 deliberately 使用 `ExtractedStage` 避免与 orchestrator 冲突。

---

### Q4. Python Bridge 与 CLI Bridge 有何区别？何时生成、何时使用？

**A.** 对外形态相同（均生成 `{out}/bridge/{project}_bridge.py`，Agent 通过 `{project}-execute-stage` 调用）；**内部执行方式不同**：

| | Python Bridge（`--bridge-mode python`，默认） | CLI Bridge（`--bridge-mode cli`） |
|--|---------------------------------------------|----------------------------------|
| 执行 | `importlib` 加载 `stage_impls/*.py` 并调函数 | `subprocess` 调目标 CLI：`{cli} execute-stage --stage-id …` |
| 前提 | 同 venv 可 import 源码 | CLI 在 PATH 上，或 `--bridge-cli` 指定命令 |

**何时生成**：`sop convert` + 有 `WorkflowGraph` + `--emit-bridge`（**hybrid/fwa 默认开**）+ 至少一个 **wrapper/hybrid** 阶段。  
**何时使用**：仅 wrapper/hybrid 阶段 Agent 运行时调 Bridge；**agent_native** 阶段直接调 SDK Tool，不走 Bridge。

**CLI 入口**：`--bridge-cli "python path/to/cli.py"` 显式指定；否则从 `pyproject.toml` 的 `[project.scripts]` 推断。未安装 entry point 时用 `python …/cli.py` 即可，不必在 PATH 上。

---

### Q5. 不加 `--out` 会产出什么？

**A.** Convert **仍会执行**（判别、分组、终端摘要）；但 **bundle 目录内文件不会落盘**：

| 产物 | 无 `--out` | 有 `--out` |
|------|:----------:|:----------:|
| Agent markdown / workflow.yaml / bridge | ❌ | ✅ |
| SDK Tool 注册（默认开） | ✅ 写到 `~/.clawcodex/agent-tools/` | ✅ 写到 `{out}/agent-tools/` |
| `--skills <dir>` | ✅ 写到指定目录 | ✅ |

`--preview` / `--validate`：不写文件、不注册 Tool。

---

### Q6. 各工作流模式下还要加哪些参数？

**A.** 参见 §1.10；要点：

| 模式 | 工作流专属产物 |
|------|----------------|
| **sdk** | 无 WorkflowGraph；仅 `--out` 时分组 Agent |
| **hybrid** | 仅需 `--out`；yaml / 阶段 Agent / bridge **默认 emit**（与 fwa 一致） |
| **fwa** | 仅需 `--out`；yaml / 阶段 Agent / bridge **默认 emit** |

SDK Tool 注册：**三种模式均默认开**；用 `--no-register-tools` 关闭。

---

### Q7. 重复 `sop convert` 时，SDK Tool 注册会覆盖已有工具吗？

**A.** **同名会覆盖，但不是整目录清空。**

实现：`register_component_tools(..., persist=True, overwrite=True)`（`overwrite` 默认 **True**，CLI 未暴露关闭项）。

| 内容 | 再次 convert（同名 / 同路径） |
|------|--------------------------------|
| Tool spec `{name}.json` | **覆盖**（`save_spec` 整文件重写） |
| Wrapper 脚本 `agent-tools/scripts/*.py` | **覆盖**（同模块 hash 则同文件名） |
| Bridge Tool `{project}-execute-stage.json` | **覆盖** |

**不会自动发生：**

1. **删除本次未再注册的旧 Tool** — 源码中已删除的方法，其 `{tool}.json` / 旧 wrapper **可能残留**。
2. **模块路径变更** — wrapper 文件名含模块 hash，路径变了会**新增**脚本，**旧脚本可能仍在**。
3. **不同 `--out`** — 各自写入 `{out}/agent-tools/` 或全局 `~/.clawcodex/agent-tools/`，互不影响。

**建议**：需要干净 bundle 时，convert 前删除 `{out}/agent-tools/`，或使用新的 `--out` 目录。

**跳过注册**：`--no-register-tools`，或 `--preview` / `--validate`（不写入、不注册）。

**运行时**：磁盘 spec 已覆盖后，已启动的 clawcodex 进程是否立即加载新 Tool 取决于 registry 加载时机；文件层面已是新内容。

---

### Q8. `--register-tools` 还要手动加吗？

**A.** **不需要。** 源码目录 `sop convert` **默认注册** SDK 方法 Tool；用 **`--no-register-tools`** 关闭。  
`--register-tools` 仍接受（与默认等价，兼容旧脚本）。

---

### Q9. 当前 `sop convert` 各参数的作用与自动化状态？

**A.** 以下按职责分组列出全部参数，标注默认值、各模式下的触发方式、以及是否可进一步自动化。

#### 输出路径类

| 参数 | 默认 | 作用 | 自动？ |
|------|:----:|------|:------:|
| `--out <dir>` | 无 | bundle 根目录。**无此参数则 Agent / yaml / bridge 均不落盘** | ❌ 不可自动（用户必须指定路径） |
| `--skills <dir>` | 无 | 额外输出 Skill markdown 到指定目录 | ❌ 不可自动（可选副作用） |

#### 工作流产物开关

| 参数 | 默认 | SDK | hybrid | fwa | 自动？ |
|------|:----:|:---:|:------:|:---:|:------:|
| `--emit-workflow-yaml` | off | N/A | ✅ 自动开 | ✅ 自动开 | ✅ 已完成 |
| `--emit-stage-agents` | off | N/A | ✅ 自动开 | ✅ 自动开 | ✅ 已完成 |
| `--emit-bridge` | off | N/A | ✅ 自动开 | ✅ 自动开 | ✅ 已完成 |

#### Bridge 微调

| 参数 | 默认 | 作用 | 自动？ |
|------|:----:|------|:------:|
| `--bridge-mode python\|cli` | `python` | 选 Python import 还是 subprocess 桥接 | ✅ 默认够用，极少需要改 |
| `--bridge-cli <cmd>` | 自动推断 | 覆盖 CLI 入口命令 | ✅ 已自动从 `pyproject.toml` 推断 |

> **Python vs CLI 模式说明**：
>
> | | Python 模式（默认） | CLI 模式 |
> |--|-------------------|----------|
> | 执行方式 | `importlib` 直接 import `stage_impls/*.py` 调函数 | `subprocess` 起子进程调目标 CLI 命令 |
> | 类似 | `from stage_impls.analyze import run; run()` | `subprocess.run(["my-app", "execute-stage", "--stage-id", "1"])` |
> | 前提 | 同 venv 可 import 源码 | CLI 在 PATH 上，或通过 `--bridge-cli` 指定 |
>
> **不需要人为判断模式**。能用 `import` 加载源码就用 python 模式（默认，覆盖 95% 场景）。源码是独立 CLI 工具、与当前 venv 隔离、或启动时需要 CLI 级参数解析才切 `--bridge-mode cli`。遇到 import 报错时切过去即可，无自动检测。

#### Tool 注册

| 参数 | 默认 | 作用 | 自动？ |
|------|:----:|------|:------:|
| `--register-tools` | **开** | SDK 方法 → Tool 注册（与默认等价，兼容旧脚本） | ✅ 已完成 |
| `--no-register-tools` | — | 关闭 Tool 注册 | ❌ 手动 opt-out |

#### 判别/提取控制

| 参数 | 默认 | 作用 | 自动？ |
|------|:----:|------|:------:|
| `--mode auto\|sdk\|hybrid\|fwa` | `auto` | 强制覆盖判别结果 | ✅ 已自动判别，仅 debug 时手动 |
| `--extractor <name>` | 自动检测 | 覆盖提取器选择 | ✅ 已自动检测，仅 debug 时手动 |
| `--strict-workflow-yaml` | off | YAML 校验失败时 abort 而非 warn | ❌ 严格模式需显式声明 |

#### 通用分组/过滤

| 参数 | 默认 | 作用 | 自动？ |
|------|:----:|------|:------:|
| `--strategy component\|keyword\|io\|llm` | `component` | 分组策略 | ✅ 有合理默认 |
| `--all` | off | 包含所有 public 方法（默认仅外部接口） | ❌ 用户意图开关 |
| `--max-groups <N>` | 0（不限） | 限制分组数量 | ✅ 默认不限 |
| `--mapping-rules <file>` | 无 | 自定义映射规则 | ❌ 高级定制 |
| `--llm-provider <p>` | 无 | LLM 语义分组提供者 | ❌ 仅 `--strategy llm` 时需要 |
| `--llm-model <m>` | 无 | LLM 模型 | ❌ 同上 |
| `--name <name>` | 目录名 | Agent 名称 | ✅ 默认目录名够用 |
| `--requirements <text>` | 空 | 需求描述 | ❌ 用户提供 |
| `--preview` | off | 预览摘要，不写文件 | ❌ 显式用户意图 |
| `--validate` / `--json` | off | 校验 / JSON 输出 | ❌ 显式用户意图 |

#### 自动化分析

**已自动化的：**

1. SDK Tool 注册 — 默认开，`--register-tools` 现在是 no-op（兼容旧脚本保留）。
2. hybrid/fwa 模式一键 emit — `--emit-workflow-yaml` / `--emit-stage-agents` / `--emit-bridge` 在 hybrid/fwa 下全自动开（有非空 `WorkflowGraph` 即 emit）。sdk 模式无 workflow graph，不 emit。

效果：三种模式的 CLI 统一为 `sop convert ./src --out ./bundle`，无需记谁要加什么 flag。

**不建议自动化的：**

| 参数 | 原因 |
|------|------|
| `--out` | 路径不可能猜 |
| `--preview` / `--validate` / `--json` | 互斥的用户意图，不能替用户选 |
| `--all` | 改变提取范围，语义上有 tradeoff |
| `--strict-workflow-yaml` | 严格模式应显式 opt-in |
| `--bridge-mode cli` | 极少数项目才需要，默认 python 覆盖 95% |
| `--mode` / `--extractor` | 已是 auto，手动只在 debug |

---

### Q10. Stage Agent 的 Skill / Tool 调用链路是怎样的？

**A.** 从源码到最终 Stage Agent markdown，经过以下步骤，每步的命名来源和对齐关系如下：

```
SourceCodeParser.parse()
  └─ 提取 SourceComponent + SourceOperation
       operation.name = "search_docs" / "ClassName.method_name"    ← 原始名

group_source_components() ─────────────────────────────────────────  分组
  └─ SkillSpec.allowed_tools = ["search_docs", "ClassName.m", ...]  ← 原始名

StageCapabilityMapper.map() ───────────────────────────────────────  匹配
  ├─ 三轮匹配 (filename → operations → IO) 找 stage ↔ skill
  ├─ 命中: profile.mapped_skill = skill.name
  │         profile.recommended_tools = list(skill.allowed_tools)   ← 拷贝旧名 ⚠️
  └─ 未命中: mapped_skill = None, recommended_tools = []
              mapping_confidence = 0.0 → generate_stage_agents 跳过

register_component_tools() ─────────────────────────────────────────  注册
  ├─ 注册 ToolSpec → 返回 name_map: {"search_docs" → "search-docs"}
  ├─ skill.allowed_tools 改写为 kebab-case                          ← 注册名
  └─ profile.recommended_tools 同步为注册名                          ← 修复后对齐

generate_stage_agents() ────────────────────────────────────────────  生成
  对每个 stage (mapping_confidence > 0.0):
    agent_name  = profile.mapped_agent   (如 "search-ops-agent")
    skills      = ["{mapped_skill}-skill"]  (如 "search_ops-skill")
    tools       = profile.recommended_tools (如 "search-docs")
```

**各产物命名对齐关系**：

| 产物 | 路径/引用 | 来源 |
|------|----------|------|
| Agent markdown | `.claude/agents/{mapped_skill}-agent.md` | `profile.mapped_agent` |
| Agent → skill 引用 | frontmatter `skills: ["{mapped_skill}-skill"]` | `profile.mapped_skill + "-skill"` |
| Skill 文件 | `{--skills}/<skill.name>-skill.md` | 来自 `grouped_skills`，与 agent 引用一致 |
| Agent → tool 引用 | frontmatter `tools: ["search-docs", ...]` | `profile.recommended_tools`（已同步注册名） |
| Tool 注册 spec | `agent-tools/search-docs.json` | `register_component_tools` 写入 |

**关键点**：

1. **Tool 名对齐**：`profile.recommended_tools` 原在 tool 注册前拷贝，导致 stage agent 引用旧名（snake_case）。已在 `commands.py` 中修复：注册后同步 `profile.recommended_tools`。
2. **Skill 文件不自动生成**：`generate_stage_agents` 默认 `write_skills=False`，仅写 agent markdown 不写 SKILL.md。Skill 文件由 `--skills <dir>` 统一从 `grouped_skills` 产出，stage agent 通过 `{mapped_skill}-skill` 引用它们。
3. **未匹配 stage 不再生成空壳**：`mapping_confidence=0.0` 且无 `mapped_skill` 的 stage 被跳过（见 Q9 根因分析）。

---

### Q11. 如何判别是否产出 WorkflowGraph？整个判定链是怎样的？

**A.** `sop convert <source_dir>` 后是否产生 `workflow_graph`，经过两层判定：

#### 第一层：模式判别（F-50-A）

`WorkflowDiscriminator.discriminate()` 跑 6 条启发式规则，每条返回 `(是否命中, 分数)`：

| 规则 | 权重 | 检测方式 |
|------|:----:|---------|
| `stage_enum` | 0.25 | `IntEnum`/`Enum` 子类，类名/成员名含 `STAGE`/`PHASE`/`STEP`/`PIPELINE`（不区分大小写、子串匹配）；或 ≥2 个递增整型成员（权重 ×0.6） |
| `state_transition` | 0.20 | 模块级字典 `NEXT_STAGE = {Stage.A: Stage.B}`；或键名与枚举成员 >50% 重叠（弱匹配） |
| `io_contract` | 0.20 | `@dataclass` 含 `input_files` / `output_files` |
| `control_flow` | 0.15 | `decide_*` / `should_*` / `check_gate` / `resolve_stage` / `resolve_*` 函数名前缀 |
| `stage_dirs` | 0.10 | 根下存在 `stage_impls/` / `stages/` / `pipeline/` 且含 `.py` |
| `gate_definition` | 0.10 | 变量名含 `GATE`，如 `GATE_STAGES = frozenset({...})` |

总分与阈值比较（`THRESHOLD_SDK=0.3`, `THRESHOLD_FWA=0.7`）：

```
total < 0.3                   → sdk    → 不提取 workflow graph
0.3 ≤ total < 0.7             → hybrid → 提取
total ≥ 0.7 且过 FWA 组合门    → fwa    → 提取
total ≥ 0.7 但没过组合门       → hybrid → 提取
```

**FWA 组合门**：`(stage_enum ∧ state_transition)` 或 `(stage_enum ∧ gate_definition)`。高分但无阶段枚举/DAG → hybrid。

#### 第二层：结构提取（F-50-B）

`extract_workflow()` 只在 hybrid / fwa 时执行。调用 `GenericPipelineExtractor.extract()`：

```
extract_stages()
  ├─ 从 pick_primary_stage_enum 挑出的枚举成员生成 ExtractedStage
  ├─ 找不到枚举 → 从 stage_impls/ 目录推断
  └─ 都找不到 → 从 .py 文件名粗推断（仅 allow_coarse=true 时）

extract_transitions()   ← 扫描字典映射
extract_gates()         ← 扫描 frozenset
extract_decisions()     ← 扫描 decide_* 函数（hybrid 跳过）
extract_contracts()     ← 扫描 @dataclass
```

核心判断：`graph.is_empty()` = `len(stages) == 0`。空图 → `extract_workflow()` 返回 `None` → `commands.py` 中 `if workflow_graph:` 为 False → 不走 stage agent 生成。

#### 实例：JiuwenAgent 的判定链路

```
源码: class PriorityLevel(IntEnum): HIGH=0, LOW=1, NORMAL=2
  → is_stage_like_enum: True (≥2 递增整数, ×0.6)
  → stage_enum 得分 0.15 (0.25 × 0.6)
  → 其他 5 条规则全部未命中 → 总分 0.15
  → 0.15 < 0.3 → hybrid（而非 sdk，因 ≥0.3？否：0.15 < 0.3 → sdk！）
```

> **纠正**：JiuwenAgent 总分 0.15 < 0.3，严格来说应判为 **sdk**，不提取 workflow graph。如果出现 stage agent，说明实际总分 ≥0.3（可能还有其他弱信号叠加），或使用了 `--mode hybrid` 强制。具体情况以 `--preview` 输出为准。

无论哪种情况，关键防护链是：提取出 stage → 匹配不到 skill → `mapping_confidence=0.0` → 修复后 `generate_stage_agents` 跳过空壳。

---

### Q12. REPL / Overview 跑流水线时，为何常误走 Explore/Bash 而非自动委派 Stage Agent？如何改善？

**A.** 这是 **FWA bundle 运行时路由** 的易用性问题（与 `sop convert` 生成物相关，但修改点在 **clawcodex REPL + SOP prompt**，非 ARC pipeline 本体）。  
W1 验证（AutoResearchClaw3）中已复现：Stage 11 完成后用户说「本地执行 stage 10 代码、收集指标」，Overview **自行 Read/Grep/Bash**，未自动 `@AutoResearchClaw-experiment-run-agent` 进入 Stage 12。

#### 根因（三层）

| 层 | 现象 | 说明 |
|----|------|------|
| **用户话术 vs pipeline 编号** | 「执行 stage 10 代码」≠「执行 Stage 10 阶段任务」 | 前者易被理解为 `python stage-10/experiment/main.py`；正式收指标进 `stage-12/runs/` 属于 **Stage 12 EXPERIMENT_RUN** |
| **Overview 合规不足** | SOP 要求「只路由、不代跑 SDK」 | 模型仍倾向 Explore / Bash；`format_overview_stage_pipeline_block` 已写规则，**执行率不够** |
| **Bundle 未加载** | `Unknown agent` / `loaded 6 agents` | 未 `clawcodex-dev --agent ./.clawcodex/AutoResearchClaw3` 时，`@agent-AutoResearchClaw-*` 不可见（仅 built-in + workspace agents） |

相关实现锚点：

- Overview 流水线编排：`extensions/sop_converter/sop_prompts.py` → `format_overview_stage_pipeline_block` / `SOP_OVERVIEW_ROUTING`
- Stage agent 短 prompt：`stage_agent_sop_body()`
- `@agent` 可见性：`clawcodex_ext/agent/load_agents_dir.py` → `get_agents_for_mentions()` + `_agent_dir_override`
- REPL 校验：`clawcodex_ext/command_system/input_processing.py` → `format_unknown_agent_mention_error`
- 启动注入 bundle：`clawcodex_ext/cli/dispatch.py` → `_resolve_startup_agent()`

## §2 进度跟踪

**完成度概览（2026-07-21）**：子特性 A/C/D/E/F 与 Generic 提取路径已落地；Arc 提取与映射核心已实现并通过单测；剩余缺口主要为 F-50.11.4、Composite macro 写入 stage agent frontmatter、REPL W2 验证。ARC 全量 bundle E2E 落盘为 AutoResearchClaw 项目自身的集成验证债务，已从 F-50 范围移除。

### 2.1 已完成

| 日期 | 里程碑 | 涉及文件 |
|------|--------|---------|
| 2026-06 | SOP 转换器核心固化 | `extensions/sop_converter/` |
| 2026-06 | F-55 分组策略增强 | `skill_grouper.py` |
| 2026-06-29 | F-50-C~F；F-50-D 合成 gate/decision 节点 | `workflow_mode/capability/` … `bridge/` |
| 2026-06-29 | F-50-A/B 判别 + 提取 + CLI 接线 | `workflow_mode/discriminator.py` … `pipeline.py`, `clawcodex_ext/cli/sop_cmd/commands.py` |
| 2026-06-30 | F-50-F CLI Bridge（方式 A）实现 | `bridge/cli_discovery.py`, `bridge/dispatch.py`, `bridge/templates/cli_bridge.py.j2` |
| 2026-06-30 | F-50-B decision 解析修复 | `_parse_decision_func` 字符串 outcome 不再静默丢弃 |
| 2026-07-01 | 状态同步：F-50-F → ✅；fwa 模式一键默认 emit 已落地 | 文档更新 |
| 2026-07-01 | 稳定性修复：空壳 agent guard、skill 名称对齐、参数简化 | `commands.py`, `agent_def_gen.py`, `capability/models.py` |
| 2026-07-02 | 稳定性修复：stage agent 委派失败/spawn 失败修复 | `load_agents_dir.py`, `commands.py`, `input_processing.py` |
| 2026-07-02 | 稳定性修复：stage agent pipeline 工具不可用、--agent 启动 skill 未加载 | `tool_registry_bridge.py`, `run_agent.py`, `dispatch.py`, `repl/core.py` |
| 2026-07-02 | Stage agent prompt 优化：SOP_INTERACTIVE_TERMINAL_STOP_LOSS 等规则落地 | `sop_prompts.py`, `sop_routing.py`, `task_guide.py` |
| 2026-07-02 | 增量功能：Composite Tools（复合工具注册与 workflow.yaml 旁车） | `composite_tools/` (builtin, registry) |
| 2026-07-21 | 范围收敛：移除 `ArcExtractor` E2E 全量 bundle 落盘瓶颈 | ARC 全量 bundle convert 是 AutoResearchClaw 项目自身集成验证债务，与 F-50 通用能力解耦；F-50-G Arc 适配器核心保持 ✅ |
| 2026-07-02 | 增量功能：Type Schema 解析（Pydantic → JSON Schema） | `type_schema.py` |
| 2026-07-02 | 增量功能：Artifact 语义描述库 | `workflow_mode/generator/artifact_semantics.py` |
| 2026-07-02 | F-50-G `ArcExtractor` 核心提取落地（stages/transitions/gates/decisions/contracts） | `workflow_mode/extractors/adapters/arc.py` |
| 2026-07-02 | F-50-C ARC 阶段 Skill 合成 + CLI 接线 | `capability/arc_mapper.py`, `commands.py` → `ensure_arc_stage_skills` |
| 2026-07-02 | Composite Tools CLI 接线（注册 + workflow sidecar emit） | `commands.py` → `register_composite_tools` / `emit_composite_workflow_yaml` |
| 2026-07-02 | F-50 单测覆盖：Arc 提取/映射、Composite、Bundle、Artifact | `test_arc_extractor.py`, `test_arc_mapper.py`, `test_composite_tools.py`, `test_bundle_workflow.py`, `test_artifact_semantics.py` |

### 2.2 当前瓶颈

| 缺口 | 说明 |
|------|------|
| F-50.11.4 交互补全 | 提取失败时 `TODO:` 模板（🔭，未实现） |
| Composite Tools 集成 | CLI 已接线；**缺口** = stage agent frontmatter **通用**引用 macro tools（目前仅 `agent_teams-skill` / Overview 文档路径） |
| **REPL 流水线易用性（Q12）** | Stage agent 提示词优化（STOP_LOSS 规则）已落地；委派 compliance 与 stage 编号歧义已改善，**W2 手动验证待做**（见 `docs/guide/autoresearchclaw-repl-sop-verification.md`） |

### 2.3 验证产物（本地）

| 目录 | 证明内容 | 备注 |
|------|---------|------|
| `_verify_f50/` / `_verify_f50_demo/` | FWA fixture 全量 bundle（`workflow.yaml` + bridge + agents） | 来源 `tests/fixtures/fixture_fwa_project` |
| `_verify_arc_full/` | ARC SDK Tool 注册 dump + bridge smoke | 本地 AutoResearchClaw 验证产物；不做为 F-50 完成标准 |
| `_verify_arc_bundle/` | pipeline 子目录 partial convert | 仅 `pipeline-agent.md` + tool specs |
| `tests/fixtures/fixture_arc_project/` | ArcExtractor 最小 fixture（3 stages） | CI 可跑，不依赖 AutoResearchClaw 仓库 |

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-29 | 实现 F-50-C~F；F-50-D 对齐 A-B 合成 gate/decision 策略 | C-G 设计稿 §3.4.2 内联 GATE 与 F-110 不兼容 |
| 2026-06-30 | 文档对齐实现：A/B 状态、FWA 组合门、ExtractedStage 命名、CLI flags、缺口清单 | 代码审查与实现不一致项收敛 |
| 2026-06-30 | SDK Tool 注册改为源码 convert 默认开启；`--no-register-tools` 可关 | 降低 sop convert 参数负担 |
| 2026-07-01 | 同步完成状态：F-50-F → ✅；移除已解决的瓶颈项；fwa 一键默认 emit 已于 CLI 接线中落地 | 代码审查 + 状态收敛 |
| 2026-07-01 | 新增 §3 设计答疑（FWA 组合门、Bridge、CLI 开关、Tool 覆盖策略等） | 实施与使用问答归档 |
| 2026-07-01 | hybrid 模式 emit 三件套改为自动（与 fwa 一致）；文档同步 | 降低 SOP convert 参数负担 |
| 2026-07-02 | §3 新增 Q12：REPL/Overview 流水线易用性 backlog（U-01~U-09） | W1 验证复盘：委派 vs Explore/Bash、stage 编号歧义 |
| 2026-07-02 | §2 进度同步：ArcExtractor 核心提取 ✅、Composite CLI 接线 ✅；更新瓶颈与验证产物清单 | 代码审查 + 单测（36 项 F-50 相关用例通过） |
