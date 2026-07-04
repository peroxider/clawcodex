# F-118: 动态任务分解引擎

> 状态: 🔭 探索中
> 章节: docs/feature_plan/02-orchestrator/f-118-dynamic-decomposition.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

单次复杂任务实时分解为多个 subagent 并行/串行执行，动态规划子任务、调度 wave、合并结果。

### 1.2 能力范围

| 能力 | 说明 | 对标 Claude Code |
|------|------|-----------------|
| 任务复杂度分析 | 判断任务是否需要分解（单步 vs 多步） | Plan Mode |
| 子任务分解 | 将复杂任务拆分为原子 phase | EnterPlanMode/ExitPlanMode |
| 依赖分析 | 判断子任务间是否可并行 | 依赖图分析 |
| 执行模式选择 | sequential vs parallel | sequential / parallel waves |
| 子 agent 调度 | 调用 fork_subagent/Agent() 执行 | Agent(...) |
| 结果合并 | 去重、筛选、合并子 agent 输出 | 脚本级合并 |
| 验证循环 | adversarial verification / loop-until-done | 六种模式组合 |

### 1.3 触发方式

```bash
# 单次任务触发
clawcodex --swarm "create a simple calculator app with NextJS backend"
# 或
clawcodex --decompose "refactor this codebase to use async/await"

# Session 设置（自动模式）
clawcodex --effort swarm
```

### 1.4 与声明式工作流引擎的区分

| 决策 | 声明式工作流引擎（F-110） | 动态任务分解（F-118） |
|------|--------------------------|---------------------|
| 编排脚本 | 人类可审阅的 YAML | 内部生成的子任务列表（不可见） |
| 持久化 | workflow.yaml 保存到磁盘 | 不持久化 |
| 检查点 | per-stage | 无（仅 session 恢复） |
| 成本预算 | 阶段级 | 累计消耗 |
| CLI 命令 | `clawcodex-dev workflow run` | `clawcodex --swarm` |

### 1.5 设计约束

1. 动态任务分解**不依赖**声明式工作流引擎的任何代码
2. 动态任务分解**复用** `fork_subagent`、`Agent()` 工具、现有 `AgentRunner`
3. 命名上严禁使用 "workflow" 一词，使用 "swarm" / "decompose" / "task_decomposition"

## §2 进度跟踪

### 2.1 当前瓶颈

探索阶段，尚未实现。

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
