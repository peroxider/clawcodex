# F-112: GATE 门禁处理器

> 状态: 📋 规划中
> 章节: docs/feature_plan/02-orchestrator/f-112-gate-processor.md
> 最后更新: 2026-06-24

## §1 设计规划

### 1.1 目标

处理工作流中的 GATE 阶段——人类审批、自动阈值、回滚。

### 1.2 三种审批模式

1. **manual** — 通过 ClarificationQueue（F-39）暂停工作流，等待人类审批/拒绝
2. **auto** — 基于 ValidatorSpec 自动判定，所有 validator 通过即 approve
3. **threshold** — LLM-as-judge 评分，达到阈值自动 approve，否则进入 manual

### 1.3 复用 F-44（Human Review Gate）

- `issue review --approve/--reject` 扩展为 `workflow gate --approve/--reject`
- `PENDING_REVIEW` 状态扩展为 `GATE_PENDING` 工作流级状态
- workspace 保留策略沿用

### 1.4 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/gate_handler.py` | `GateHandler` 核心 | 📋 |
| `extensions/orchestrator/workflow_engine/gate_modes.py` | manual/auto/threshold 三种模式 | 📋 |
| `extensions/orchestrator/workflow_engine/gate_rollback.py` | 回滚逻辑 | 📋 |

## §2 进度跟踪

### 2.1 当前瓶颈

尚未开始。依赖 F-110 引擎核心 + F-39 ClarificationQueue。

## §3 实施细节

### 3.1 验收标准

1. manual 模式正确触发 ClarificationQueue 暂停
2. auto 模式 validator 全部通过即 approve
3. threshold 模式 LLM 评分达到阈值自动 approve
4. rollback 正确恢复阶段状态

### 3.2 依赖与协同

- 前置: F-110（工作流引擎核心）
- 复用: F-39（ClarificationQueue）
- 复用: F-44（Human Review Gate）

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
