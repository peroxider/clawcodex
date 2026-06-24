# F-116: 工作流可观测性集成

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-116-workflow-observability.md
> 最后更新: 2026-06-24

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
| `extensions/orchestrator/workflow_engine/observability.py` | State Journal 事件写入 | 📋 |
| `extensions/orchestrator/workflow_engine/progress.py` | WorkflowProgressSink | 📋 |
| `extensions/orchestrator/workflow_engine/audit.py` | 工作流级审计事件 | 📋 |

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
