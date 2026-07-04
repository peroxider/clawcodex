# F-110: 声明式工作流引擎核心

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-110-workflow-engine.md
> 最后更新: 2026-06-24

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
| F-110-A | 核心执行循环 — DAG 遍历 + 顺序执行 + 事件发射 | 📋 | P0 |
| F-110-B | 阶段调度 — 调用 StageRunner 执行单个阶段 | 📋 | P0 |
| F-110-C | 输出验证 — 调用 ValidatorSpec 执行阶段输出验证 | 📋 | P0 |
| F-110-D | 错误处理策略 — timeout/failure/cost-exceeded 可配置处理 | 📋 | P0 |
| F-110-E | 工作流级事件总线 — stage_start/stage_complete/gate_request 等 | 📋 | P0 |
| F-110-F | 成本追踪与预算控制 — 阶段级 + 全局预算 + 预警阈值 | 📋 | P0 |

### 1.5 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/engine.py` | `DeclarativeWorkflowEngine` 核心 | 📋 |
| `extensions/orchestrator/workflow_engine/workflow_state.py` | 工作流运行时状态 | 📋 |
| `extensions/orchestrator/workflow_engine/event_bus.py` | 事件总线 + State Journal 写入 | 📋 |
| `extensions/orchestrator/workflow_engine/cost.py` | `CostTracker` + `CostBudget` | 📋 |
| `extensions/orchestrator/workflow_engine/errors.py` | 异常类型定义 | 📋 |

## §2 进度跟踪

### 2.1 当前瓶颈

尚未开始实现。依赖 F-111~F-116 子特性顺序实施。

### 2.2 下一步计划

按 F-110-A→B→C→D→E→F 顺序实施。

## §3 实施细节

### 3.1 验收标准

1. 读取 `workflow.yaml` 自动构建 DAG
2. 按 DAG 顺序执行各阶段
3. GATE/DECISION 阶段正确处理
4. 超时/失败/预算超额可配置处理

### 3.2 依赖与协同

- 复用: AgentRunner(F-1), F-51, F-40, F-38, F-91~F-96, F-39
- 前置: F-111(StageRunner), F-114(验证器)

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
