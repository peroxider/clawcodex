# F-111: StageRunner 适配器

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-111-stage-runner.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

桥接 `DeclarativeWorkflowEngine` 与 `AgentRunner`，将阶段执行适配为 `AgentRunner` 可消费的工作单元。

### 1.2 适配器设计

```python
class StageRunner:
    async def run(self, stage_node: StageNode,
                  state: WorkflowState) -> StageRunResult:
        # 构建合成 Issue
        synthetic_issue = Issue(
            identifier=f"stage-{stage_node.id:02d}",
            title=f"[{stage_node.phase}] {stage_node.name}",
            body=self._build_stage_prompt(stage_node, state),
            labels=[f"workflow-stage", f"workflow-{stage_node.phase}"],
        )
        # 构建 Workspace（共享目录，非 git）
        workspace = self._build_workspace(stage_node, state)
        # 调用 AgentRunner
        agent_runner = AgentRunner(agent_config=self._build_agent_config(stage_node))
        session = AgentSession(issue=synthetic_issue, workspace=workspace)
        return await agent_runner.run(session, self.config.workflow_config)
```

### 1.3 设计决策

| # | 决策 | 理由 |
|---|------|------|
| DD-5 | 方案 A（合成 Issue 适配器）优先 | 保留 AgentRunner 的全部稳健机制 |
| DD-6 | Workspace 使用共享模式（F-42） | 阶段间共享 workspace_dir，不需要 git 隔离 |
| DD-7 | 备选方案 B（QueryRunner）保留 | 如适配开销过大，可切换 |

### 1.4 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/stage_runner.py` | `StageRunner` + AgentRunner 适配器 | 📋 |

## §2 进度跟踪

### 2.1 当前瓶颈

尚未开始。依赖 F-110 核心引擎定义。

### 2.2 下一步计划

F-110 核心循环完成后接入。

## §3 实施细节

### 3.1 验收标准

1. 合成 Issue 可被 AgentRunner 正常消费
2. 阶段输出通过 ValidatorSpec 验证
3. GATE/DECISION 阶段正确桥接

### 3.2 依赖与协同

- 前置: F-110（声明式工作流引擎核心）
- 复用: F-42（Shared Workspace）
- 复用: AgentRunner

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
