# F-116: 工作流可观测性集成

> 状态: ✅ 已完成（核心实现 + 集成层落地 + 集成测试覆盖）
> 章节: docs/feature_plan/02-orchestrator/f-116-workflow-observability.md
> 最后更新: 2026-07-15

## §1 设计规划

### 1.1 目标

将工作流执行事件集成到 ClawCodex 的可视化和审计体系。

### 1.2 集成点

| 来源特性 | 复用内容 | 工作流适配 |
|---------|---------|-----------|
| F-91~F-96 Visualizer | State Journal NDJSON | workflow_stage_start / workflow_gate_request / workflow_decision / workflow_complete |
| F-91~F-96 Visualizer | Gantt 图 | 阶段执行时间渲染为 Gantt 条形图 |
| F-45 Audit Trail | Tool-call NDJSON | 工作流级事件写入 tool-events |
| F-40 ProgressSink | 进度报告协议 | WorkflowProgressSink 报告阶段完成百分比 |
| F-20 Progress Reporting | 检查点触发的进度报告 | 每阶段完成后触发 ProgressReportTool |

### 1.3 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/observability.py` | `WorkflowObservability`（State Journal 事件写入 + NDJSON 审计）+ `WorkflowProgressSink`（ProgressSink 协议 + `PhaseComplete` 转发） | ✅ |
| `extensions/orchestrator/workflow_engine/audit.py` | `WorkflowAuditEvent`（frozen dataclass NDJSON Schema）+ `WorkflowAuditWriter`（`~/.clawcodex/workflow-events/{name}/events.ndjson` 追加写入） | ✅ |

> **注**：原规划的 `progress.py` 未单独拆分，WorkflowProgressSink 直接放在 `observability.py` 中（与 F-114 builtin.py 同款策略：避免小文件碎片）。

### 1.4 集成点落地

| 来源特性 | 复用内容 | 工作流适配 | 状态 |
|---------|---------|-----------|:----:|
| F-91~F-96 Visualizer | State Journal NDJSON | `WorkflowObservability.write_stage_start/complete/failed/gate_request/result/decision/workflow_complete/error/cost_event` 9 个事件写入 | ✅ |
| F-91~F-96 Visualizer | Gantt 图 | stage 事件包含 `duration_seconds` 字段；Gantt 渲染由 Visualizer 消费 | ✅ |
| F-45 Audit Trail | Tool-call NDJSON | `WorkflowAuditWriter` 独立路径 `~/.clawcodex/workflow-events/{name}/events.ndjson`，与 `tool_event_log` 互补 | ✅ |
| F-40 ProgressSink | 进度报告协议 | `WorkflowProgressSink.on_stage_complete` 转发为 `PhaseComplete(phase, progress, message)` 给下游 sink | ✅ |
| F-20 Progress Reporting | 检查点触发的进度报告 | `workflow_orchestrator.py:321` 实例化 `WorkflowObservability`，每阶段完成后触发 | ✅ |

### 1.5 集成层

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_orchestrator.py` | `__init__` 中实例化 `WorkflowProgressSink`(L99) + `WorkflowAuditWriter`(L105) + `WorkflowObservability`(L321)；作为引擎入口的桥接层 | ✅ |
| `extensions/orchestrator/workflow_engine/__init__.py` | 导出 `WorkflowObservability` / `WorkflowProgressSink` / `WorkflowAuditEvent` / `WorkflowAuditWriter` | ✅ |
| `tests/orchestrator/test_workflow_engine_integration.py` | `test_observability_imports` 覆盖三个类可导入 | ✅ |

## §2 进度跟踪

### 2.1 当前状态

✅ **核心实现 + 集成层全部完成**（2026-06-26 → 2026-07-15）。三个集成点（State Journal / ProgressSink / Audit Trail）全部落地，与 `WorkflowOrchestrator` 集成，集成测试覆盖。

### 2.2 已完成里程碑

- ✅ `WorkflowObservability`（294 行）— 9 个 write 方法覆盖 stage/gate/decision/cost/complete/error 全生命周期
- ✅ `WorkflowProgressSink`（观测文件内）— 实现 ProgressSink 协议，`on_stage_complete` 触发 `PhaseComplete` 事件给下游 sink
- ✅ `WorkflowAuditWriter`（284 行）— `WorkflowAuditEvent` frozen dataclass + NDJSON 追加写入
- ✅ `WorkflowOrchestrator` 集成层（`workflow_orchestrator.py`）— 实例化三类组件并桥接引擎事件
- ⚠️ **未提供独立单元测试** — 仅由 `test_workflow_engine_integration.py` 的 `test_observability_imports` 覆盖导入；三个类的行为测试未独立成文（P2 改进项）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-06-26 | `7d10f4b8` 实现声明式工作流引擎核心及编排器集成 | F-116 三个核心类（`WorkflowObservability` / `WorkflowProgressSink` / `WorkflowAuditWriter`）随 F-110 一起落地 + `WorkflowOrchestrator` 集成 |
| 2026-07-08 | `af0c31dc` 统一代码风格修复 | ruff 风格合规 |
| 2026-07-15 | 文档同步 | 更新 F-116 实现状态（覆盖原 📋 规划中标记），标注缺失独立单测的 P2 改进项 |
