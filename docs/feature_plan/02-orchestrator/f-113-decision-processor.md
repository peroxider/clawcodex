# F-113: DECISION 决策处理器

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-113-decision-processor.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

处理工作流中的决策点——多结果分支、回环、收敛检测。

### 1.2 核心逻辑

```python
class DecisionHandler:
    def resolve(self, node: StageNode, result: StageRunResult,
                history: DecisionHistory) -> int | None:
        outcome = self._parse_outcome(result)  # proceed / pivot / refine / ...
        decision_spec = node.decision.outcomes[outcome]

        # 回环次数检查
        if decision_spec.max_times is not None:
            times = history.count(outcome, node.id)
            if times >= decision_spec.max_times:
                return self._resolve_exhaust(decision_spec)

        # 收敛检查
        if decision_spec.convergence_check:
            if history.is_degenerate(outcome, node.id):
                return self._resolve_convergence(node)

        return decision_spec.next or decision_spec.rollback_to
```

### 1.3 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/decision_handler.py` | `DecisionHandler` | 📋 |
| `extensions/orchestrator/workflow_engine/decision_history.py` | 决策历史 + 收敛检测 | 📋 |
| `extensions/orchestrator/workflow_engine/rollback.py` | 阶段目录快照 + 版本化回滚 | 📋 |

## §2 进度跟踪

尚未开始。

## §3 实施细节

### 3.1 验收标准

1. 支持 proceed/pivot/refine 等多结果分支
2. 回环次数超限正确回滚
3. 收敛检测正确识别退化循环

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
