# F-115: 检查点与恢复

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-115-checkpoint-recovery.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

工作流级检查点持久化，支持从任意阶段恢复执行。

### 1.2 检查点格式

```json
{
  "workflow_name": "arc-research",
  "workflow_version": "1.0",
  "current_stage": 12,
  "completed_stages": [1, 2, ..., 11],
  "stage_results": {
    "1": { "status": "success", "outputs": ["goal.md"], "timestamp": "..." }
  },
  "decision_history": [
    { "stage": 15, "outcome": "refine", "timestamp": "..." }
  ],
  "cost_accumulated_usd": 12.34,
  "started_at": "2026-06-18T10:00:00Z",
  "last_checkpoint": "2026-06-18T14:30:00Z"
}
```

### 1.3 复用策略

- 复用 ARC 原子写入模式（temp file + rename）
- 复用 Orchestrator `SessionStorage`（F-49）存储 Agent session transcript
- 复用 State Journal Writer（F-91~F-96）写入工作流级事件日志

### 1.4 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/checkpoint.py` | 检查点写入/读取/验证 | 📋 |
| `extensions/orchestrator/workflow_engine/resume.py` | 从检查点恢复执行 | 📋 |
| `extensions/orchestrator/workflow_engine/artifact_resolver.py` | 跨阶段产物路径解析 | 📋 |

## §2 进度跟踪

尚未开始。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
