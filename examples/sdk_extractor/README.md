# SDK Extractor — PatternExtractor 兼容示例

## 目的

本文档是 **将任意 SDK/项目编译为多智能体工作流（Multi-Agent Workflow）** 的参考设计示例。正式实现位于 `extensions.sop_converter.workflow_mode.extractors.pattern`，本目录只保留兼容导入入口。

当你有一个新的 SDK、框架或项目需要转换为 SOP 工作流时，可以参照此示例编写一个**自定义提取器（Custom Extractor）**，将项目中的 pipeline 定义（阶段枚举、状态转移、关卡、决策、契约）解析为 `WorkflowGraph` IR。

## 背景

`clawcodex` 的 SOP Converter 提供了一套工作流提取框架：

```
WorkflowExtractorBase (抽象基类)
  ├── GenericPipelineExtractor  (通用提取器，覆盖大多数 Python 项目)
  └── 你的自定义提取器         (针对特定 SDK 约定优化)
```

`GenericPipelineExtractor` 通过 `SourceScanContext` 自动扫描项目中的枚举类、字典映射等通用模式，适用于大多数项目。但对于有**特定约定**的 SDK（如特定的目录结构、变量命名约定、执行器映射表），编写一个**定制提取器**可以获得更精确的提取结果。

## 架构模式

### 三层结构

```
┌─────────────────────────────────────────────────┐
│  YourCustomExtractor(WorkflowExtractorBase)     │
│  ├── 配置驱动：PipelineConfig 描述 SDK 约定       │
│  ├── 扫描策略：SourceScanContext 缓存 AST        │
│  └── 降级策略：精确 → 目录推断 → 粗粒度扫描      │
├─────────────────────────────────────────────────┤
│  WorkflowExtractorBase (抽象契约)                │
│  ├── extract_stages()      → list[ExtractedStage]│
│  ├── extract_transitions() → list[Transition]   │
│  ├── extract_gates()       → dict[int, GateSpec]│
│  ├── extract_decisions()   → dict[int, ...]     │
│  └── extract_contracts()   → dict[int, ...]     │
├─────────────────────────────────────────────────┤
│  SourceScanContext (AST 缓存 + 枚举发现)          │
│  WorkflowGraph (输出 IR)                        │
└─────────────────────────────────────────────────┘
```

### 核心设计原则

1. **配置驱动** — 所有 SDK 特定的约定（路径、变量名、枚举名）通过 `PipelineConfig` 注入，而不是硬编码
2. **共享扫描** — 使用 `SourceScanContext` 缓存 AST 解析结果，避免重复解析
3. **分层降级** — 精确提取失败时自动降级到目录推断或粗粒度扫描
4. **可组合** — 提取器可以组合多个策略，不同阶段的提取可以有不同的精度

## 如何适配一个新的 SDK

### 步骤 1：分析 SDK 约定

识别你的 SDK 中的以下模式：

| 模式 | 描述 | 示例 |
|------|------|------|
| **阶段枚举** | 定义工作流阶段的枚举类 | `class BuildStage(Enum)` |
| **阶段序列** | 定义阶段执行顺序的映射 | `STAGE_SEQUENCE = {…}` |
| **状态转移** | 定义阶段间转移的映射 | `NEXT_STAGE_MAP = {…}` |
| **关卡(Gate)** | 需要人工审批的阶段 | `APPROVAL_GATES = frozenset({…})` |
| **决策(Decision)** | 分支/回退逻辑 | `DECISION_ROLLBACK = {…}` |
| **契约(Contract)** | 阶段的输入/输出文件 | `CONTRACT_MAP = {…}` |

### 步骤 2：创建 PipelineConfig

```python
from extensions.sop_converter.workflow_mode.extractors.pattern import PipelineConfig

my_sdk_config = PipelineConfig(
    name="my-sdk",
    description="My SDK pipeline extractor",
    # 标识 pipeline 目录的文件组合
    pipeline_marker_files=[
        ("stages.py", "pipeline"),
        ("contracts.py", "pipeline"),
    ],
    # 变量名匹配模式（正则）
    executor_table_patterns=["STAGE_EXECUTORS", "_STAGE_EXECUTORS"],
    sequence_var_pattern="STAGE_SEQUENCE",
    transition_var_pattern="NEXT_STAGE|PREVIOUS_STAGE",
    decision_var_pattern="DECISION_ROLLBACK",
    contract_var_pattern="CONTRACT",
    # 决策阶段名称回退列表
    decision_stage_names=["RESEARCH_DECISION", "DECISION"],
)
```

### 步骤 3：实例化提取器

```python
from extensions.sop_converter.workflow_mode.extractors.pattern import PatternExtractor

extractor = PatternExtractor(config=my_sdk_config, mode="fwa")
graph = extractor.extract("/path/to/my-sdk-project")
```

## 示例代码说明

正式模块 `workflow_mode/extractors/pattern.py` 包含完整实现；本目录的 `pattern_extractor.py` 仅转发旧导入路径。实现提供：

1. ✅ **配置驱动** — 所有 SDK 约定通过 `PipelineConfig` 传入
2. ✅ **SourceScanContext 复用** — 通过 `_ensure_scan()` 懒加载并缓存 AST
3. ✅ **5 种提取方法** — stages / transitions / gates / decisions / contracts
4. ✅ **分层降级** — 精确 AST 解析 → 目录推断 → 粗粒度文件扫描
5. ✅ **错误处理** — 每个方法独立容错，失败时返回空值而非崩溃
6. ✅ **完整文档** — 每个方法都有 docstring 说明设计意图和扩展点

## 与 ArcExtractor 的对比

| 维度 | 旧 ArcExtractor | 新 PatternExtractor |
|------|----------------|-------------------|
| 路径假设 | 硬编码 `researchclaw/pipeline/` | 配置驱动 |
| 变量名 | 硬编码字符串 | 正则模式匹配 |
| 枚举名 | 硬编码 `RESEARCH_DECISION` | 可配置回退列表 |
| 扫描缓存 | 每次提取都重新解析文件 | SourceScanContext 复用 |
| 降级策略 | 无（失败即返回空） | 三层降级 |
| 可复用性 | 仅 ARC 项目 | 任意 SDK 项目 |
| 文档 | 少量注释 | 完整设计文档 |

## 进阶扩展

- **支持非 Python 项目** — 将 `SourceScanContext` 替换为其他语言的 AST 解析器
- **支持 YAML/TOML 配置** — 从 `pipeline.yaml` 或 `workflow.toml` 解析阶段定义
- **远程 pipeline 定义** — 从 API/数据库加载阶段定义而不是本地文件
- **动态注册** — 通过 `ExtractorRegistry.register_adapter()` 将自定义提取器注册到系统
