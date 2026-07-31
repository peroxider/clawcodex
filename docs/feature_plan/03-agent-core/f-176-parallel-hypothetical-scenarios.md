# F-176: 假设并行情景 — 多假设并行验证（DC-011）

> 状态: 📋 规划中  
> 设计来源: [动态上下文总览](../dynamic-context-index.md) — DC-011

## §0 元信息

| 字段 | 值 |
|------|---|
| 覆盖 DC | DC-011 假设并行情景 |
| Wave | Wave 3 / P2 |
| 前置依赖 | F-118 子 agent 编排、F-158 置信度协议 |
| 落地形态 | 假设注册表 + 隔离执行分支 + 证据综合器 |

## §1 设计规划

将互斥或竞争性的解释显式登记为假设，在隔离上下文中并行收集证据，最后按证据强度收敛；任何尚未排除的分支都不得被伪装为确定结论。

## §2 子特性与验收

| 编号 | 子特性 | 验收 |
|------|--------|------|
| P176-A | 假设登记与预算 | 每个分支有前提、验证动作和 token/时间上限 |
| P176-B | 隔离并行执行 | 一个分支的草稿不污染其他分支 |
| P176-C | 证据收敛 | 输出支持/反驳证据、剩余不确定性与推荐动作 |

## §3 风险

并行分支会放大成本；仅对高不确定性或高影响决策启用，并设定最大分支数。

## §4 实施规格

**文件落点**：`extensions/hypothetical_scenarios/{models,planner,executor,synthesizer}.py`、`tests/hypothetical_scenarios/`。`Scenario` 必须包含假设、验证问题、最少三步推演、预算和证据；`Comparison` 固定输出 cost / maintainability / risk / reversibility / dependencies 五维评分及未决项。

`explore(decision, scenarios, *, max_concurrency=3, depth=3)` 经 F-118 创建隔离子任务；每个分支使用独立 scratchpad 与 `scenario_id`，禁止写入共享结论。超过 token、时间或工具预算的分支标为 `INCONCLUSIVE`，而不是静默丢弃。

实施顺序：数据契约与预算器 → 并行执行适配器 → 评分综合器 → F-158/F-160 集成。验收包括：分支互不污染；每个有效分支达到三步；预算耗尽可见；综合器保留分歧并在证据不足时请求人工决策。
