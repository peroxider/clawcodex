# F-110: 声明式工作流引擎核心

> 状态: ✅ 已完成（F-110-A~F 全量落地，依赖 F-111~F-116 同步实施）
> 章节: docs/feature_plan/02-orchestrator/f-110-workflow-engine.md
> 最后更新: 2026-07-15

## §1 设计规划

### 1.1 背景与目标

读取 `workflow.yaml`，按 DAG 顺序调度 Agent，管理 GATE/DECISION/回环，提供工作流级错误恢复和成本追踪。

### 1.2 方案架构

```python
class DeclarativeWorkflowEngine:
    """声明式工作流引擎 — 解释执行 workflow.yaml"""

    def __init__(self, workflow: WorkflowSchema, config: EngineConfig):
        self.workflow = workflow
        self.config = config
        self.state = WorkflowState(workflow)
        self.stage_runner = StageRunner(config)
        self.cost_tracker = CostTracker(config.cost_budget)

    async def execute(self, from_stage: int | None = None) -> WorkflowResult:
        # DAG 遍历 + 顺序执行 + 事件发射
        ...
```

### 1.3 与 Orchestrator 的关系

```
DeclarativeWorkflowEngine
  ├── 复用 → AgentRunner (F-1) / stagnation detection (F-51) / ProgressSink (F-40)
  ├── 复用 → Verification Pipeline (F-38) / State Journal Writer (F-91~F-96)
  ├── 复用 → ClarificationQueue (F-39) / CostTracker
  └── 新增 → StageRunner 适配器
```

### 1.4 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| F-110-A | 核心执行循环 — DAG 遍历 + 顺序执行 + 事件发射 | ✅ | P0 |
| F-110-B | 阶段调度 — 调用 StageRunner 执行单个阶段 | ✅ | P0 |
| F-110-C | 输出验证 — 调用 ValidatorSpec 执行阶段输出验证 | ✅ | P0 |
| F-110-D | 错误处理策略 — timeout/failure/cost-exceeded 可配置处理 | ✅ | P0 |
| F-110-E | 工作流级事件总线 — stage_start/stage_complete/gate_request 等 | ✅ | P0 |
| F-110-F | 成本追踪与预算控制 — 阶段级 + 全局预算 + 预警阈值 | ✅ | P0 |

### 1.5 实现文件

#### F-110 核心模块

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/engine.py` | `DeclarativeWorkflowEngine` 核心（DAG 拓扑排序 + `execute(from_stage)` + `_run_agent_stage`/`_run_gate_stage`/`_run_decision_stage` + 错误策略分发） | ✅ |
| `extensions/orchestrator/workflow_engine/workflow_state.py` | `WorkflowState` / `StageNode` / `StageResult` / `StageStatus` / `StageKind` | ✅ |
| `extensions/orchestrator/workflow_engine/event_bus.py` | `EventBus` + 同步事件发射 + State Journal 写入 + 12 个便捷事件方法 | ✅ |
| `extensions/orchestrator/workflow_engine/cost.py` | `CostBudget` + `CostTracker`（阶段级 + 全局预算 + 预警阈值 + `load_state` 恢复） | ✅ |
| `extensions/orchestrator/workflow_engine/errors.py` | 11 个异常类型（`WorkflowEngineError` 继承树） | ✅ |

#### 依赖协同模块（F-111~F-116）

| 文件路径 | 关联特性 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/stage_runner.py` | F-111 StageRunner 适配器（499 行，Agent/Gate/Decision 三类执行） | ✅ |
| `extensions/orchestrator/workflow_engine/gate_handler.py` | F-112 GATE 门禁处理器 | ✅ |
| `extensions/orchestrator/workflow_engine/gate_rollback.py` | F-112 GATE 拒绝回滚处理 | ✅ |
| `extensions/orchestrator/workflow_engine/decision_handler.py` | F-113 DECISION 决策处理器（回环计数 + 收敛检测） | ✅ |
| `extensions/orchestrator/workflow_engine/rollback.py` | F-113 阶段回滚管理器（`RollbackManager` + `StageSnapshot`） | ✅ |
| `extensions/orchestrator/workflow_engine/validators/__init__.py` | F-114 `ContractValidator` 注册表 + 6 种同步内置验证器（file_exists/file_size/regex/line_count/json_schema/custom） | ✅ |
| `extensions/orchestrator/workflow_engine/validators/llm_judge.py` | F-114 LLM-as-judge 验证器（多接口适配 + 降级评分） | ✅ |
| `extensions/orchestrator/workflow_engine/validators/custom.py` | F-114 自定义命令验证器（cwd/env/timeout/shell） | ✅ |
| `extensions/orchestrator/workflow_engine/checkpoint.py` | F-115 检查点持久化（`Checkpoint` / `CheckpointManager` / `WorkflowResumer` / `ArtifactResolver`） | ✅ |
| `extensions/orchestrator/workflow_engine/observability.py` | F-116 `WorkflowObservability` + `WorkflowProgressSink` | ✅ |
| `extensions/orchestrator/workflow_engine/audit.py` | F-116 `WorkflowAuditEvent` + `WorkflowAuditWriter` | ✅ |

#### 集成层

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_orchestrator.py` | `WorkflowOrchestrator` 集成层（注入 AgentRunner/CheckpointManager/AuditWriter，桥接 Orchestrator 与引擎） | ✅ |
| `extensions/orchestrator/orchestrator.py` | `Orchestrator.__init__` 新增 `workflow_yaml_path` 参数 | ✅ |
| `extensions/api/orchestration.py` | `OrchestrationSubsystem.__init__` 透传 `workflow_yaml_path` | ✅ |
| `tests/orchestrator/test_workflow_engine_integration.py` | 集成测试（15 用例：导入 + YAML 解析 + DAG 排序 + 初始化 + 参数透传） | ✅ |

## §2 进度跟踪

### 2.1 当前状态

✅ **全部完成**（2026-06-26 → 2026-07-15）。F-110-A~F 六项子特性 + F-111~F-116 全部依赖协同模块已落地，共 4353 行代码，集成测试 15/15 通过（耗时 4.91s）。

### 2.2 已完成里程碑

- ✅ `DeclarativeWorkflowEngine` 核心执行循环（Kahn 拓扑排序 + from_stage 恢复）
- ✅ StageRunner 适配器注入（延迟注入，支持 Agent/Gate/Decision 三类执行）
- ✅ 契约验证器集成（`ContractValidator.validate_all` 在 AGENT 阶段完成后调用）
- ✅ 错误处理策略（`on_error: fail | skip | retry | rollback` + 11 个异常类型）
- ✅ 事件总线（12 类事件 + State Journal 双写 + 处理器注册）
- ✅ 成本追踪（阶段级 + 全局预算 + 80% 预警 + `CostExceededError` 抛错）
- ✅ GATE 门禁（auto/manual/threshold 三模式 + 拒绝回滚）
- ✅ DECISION 决策（回环计数 + 收敛检测 + `DecisionExhaustedError`/`ConvergenceError`）
- ✅ 检查点恢复（每阶段完成后 `CheckpointManager.save` + `WorkflowResumer`）
- ✅ 可观测性集成（`WorkflowProgressSink` + `WorkflowAuditWriter`）

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 | 落地证据 |
|---|--------|:----:|---------|
| 1 | 读取 `workflow.yaml` 自动构建 DAG | ✅ | `WorkflowSchema.from_yaml`（`engine.py:104`）+ `build_dag_order`（Kahn 算法，`engine.py:125`） |
| 2 | 按 DAG 顺序执行各阶段 | ✅ | `DeclarativeWorkflowEngine.execute` 主循环（`engine.py:284`） |
| 3 | GATE/DECISION 阶段正确处理 | ✅ | GATE：`gate_handler.py` + `gate_rollback.py`（F-112）；DECISION：`decision_handler.py` + `rollback.py`（F-113） |
| 4 | 超时/失败/预算超额可配置处理 | ✅ | `StageTimeoutError` / `StageFailureError` / `CostExceededError` + `StageNode.on_error`（fail/skip/retry/rollback） |

### 3.2 依赖与协同

- 复用: AgentRunner(F-1), F-51, F-40, F-38, F-91~F-96, F-39 — 全部已落地
- 前置: F-111（StageRunner ✅）、F-114（验证器 ✅）— 已实现并接入
- 协同: F-112 GATE / F-113 DECISION+Rollback / F-115 检查点 / F-116 可观测性 — 全部完成

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-26 | `7d10f4b8` 实现声明式工作流引擎核心及编排器集成 | F-110 主特性落地（engine.py / workflow_state.py / event_bus.py / cost.py / errors.py + workflow_orchestrator.py 集成层） |
| 2026-06-30 | `60efebac` 工作流引擎易用性问题修复以及优化 | 修复模板与错误处理细节 |
| 2026-07-02 | `5c52396c` F-50 工作流模式（判别/提取/能力映射/YAML/Agent/Bridge 全链路） | F-50 SOP 全链路打通，工作流模式正式上线 |
| 2026-07-08 | `12f2cfbc` 工作流引擎模板优化 + 中断恢复问题修复 | 模板收敛 + 检查点恢复路径 |
| 2026-07-08 | `af0c31dc` 统一代码风格修复 | ruff 风格合规 |
| 2026-07-10 | `4347333b` 重构契约验证器以支持依赖注入 | F-114 验证器 DI 化（workspace_dir / llm_client 注入） |
| 2026-07-10 | `a8455e9e` 增强检查点功能支持完整工作流状态恢复 | F-115 完整状态恢复（含 decision_history + cost_tracker 序列化） |
| 2026-07-14 | `2179b4c4` F-54 issue show 命令无法显示 agent 实时状态，补齐 diagnostics_callback 传递链路 | workflow_orchestrator 透传 diagnostics_callback |
| 2026-07-15 | `1f62aba8` 修复工作流模式下验证阶段 bug | 验证器在 AGENT 阶段失败的错误分类修正 |
| 2026-07-15 | 文档同步 | 更新 F-110 实现状态（覆盖原 📋 规划中标记） |
