# F-115: 检查点与恢复

> 状态: 🚧 实现中（核心代码已落地，待补齐测试与恢复完备性）
> 章节: docs/feature_plan/02-orchestrator/f-115-checkpoint-recovery.md
> 最后更新: 2026-07-10

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
    "1": {
      "status": "completed",
      "outputs": ["goal.md"],
      "error": null,
      "cost_usd": 0.12,
      "duration_seconds": 45.2,
      "timestamp": "2026-06-18T10:05:00Z"
    }
  },
  "decision_history": [
    [15, 3]
  ],
  "cost_accumulated_usd": 12.34,
  "started_at": "2026-06-18T10:00:00Z",
  "last_checkpoint": "2026-06-18T14:30:00Z"
}
```

> **说明**：`decision_history` 当前保存为 `engine._decision_count` 的 `items()` 列表（`[stage_id, count]`），用于决策回环次数检测。后续将统一为与 `DecisionHistory` 一致的记录格式。

### 1.3 复用策略

- 复用 ARC 原子写入模式（temp file + rename）。
- 复用 Orchestrator `SessionStorage`（F-49）存储 Agent session transcript。
- 复用 State Journal Writer（F-96-A）写入工作流级事件日志。

### 1.4 实现文件

| 文件路径 | 变更描述 | 状态 |
|---------|---------|:----:|
| `extensions/orchestrator/workflow_engine/checkpoint.py` | `Checkpoint` / `CheckpointManager` / `WorkflowResumer` / `ArtifactResolver` 统一实现 | ✅ |
| `extensions/orchestrator/workflow_engine/engine.py` | 阶段完成后调用 `_save_checkpoint`；支持 `execute(from_stage=...)` | ✅ |
| `extensions/orchestrator/workflow_engine/workflow_orchestrator.py` | `run()` 自动检测并加载检查点；成功后清理、失败后保存 | ✅ |
| `tests/orchestrator/test_checkpoint_recovery.py` | 检查点读写、恢复、ArtifactResolver 单元测试 | 📋 |

> **注**：原规划中的独立 `resume.py` 与 `artifact_resolver.py` 已合并到 `checkpoint.py` 中，作为 `WorkflowResumer` 与 `ArtifactResolver` 类，减少小文件碎片。

### 1.5 子特性分解

| 子特性 | 描述 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| F-115-A | 检查点数据模型 `Checkpoint`（字段序列化/反序列化） | ✅ | P0 |
| F-115-B | 原子写入检查点管理器 `CheckpointManager.save/load/exists/delete` | ✅ | P0 |
| F-115-C | 引擎集成：阶段完成后自动保存检查点 | ✅ | P0 |
| F-115-D | 编排器集成：`WorkflowOrchestrator` 自动恢复与清理检查点 | ✅ | P0 |
| F-115-E | 状态恢复：`WorkflowResumer.resume` / `CheckpointManager.restore_state` | ✅ | P0 |
| F-115-F | 产物路径解析：`ArtifactResolver` 支持 `${stage:<id>:output:<name>}` | ✅ | P2 |
| F-115-G | `ArtifactResolver` 在 StageRunner / Engine 中实际接入 | 📋 | P2 |
| F-115-H | 决策历史完整恢复（`DecisionHistory` + `engine._decision_count`） | 📋 | P1 |
| F-115-I | 检查点版本兼容与校验（schema version、必填字段检查） | 📋 | P1 |
| F-115-J | 单元测试覆盖 | 📋 | P0 |

## §2 进度跟踪

### 2.1 当前基线

核心代码已实现并通过 import smoke test：

- `Checkpoint` 数据模型支持 `to_dict()` / `from_dict()` 往返序列化。
- `CheckpointManager` 使用 temp file + `os.replace` 原子写入，提供 `save/load/exists/delete/restore_state`。
- `DeclarativeWorkflowEngine` 在每个阶段完成后调用 `_save_checkpoint()`，并支持 `execute(from_stage=...)` 从指定阶段继续执行。
- `WorkflowOrchestrator.run()` 在启动时自动检测检查点、恢复 `stage_results`/`stage_statuses`、计算 `from_stage`。
- 工作流成功时 `CheckpointManager.delete()` 清理检查点；失败时保存最终状态以便再次恢复。
- `WorkflowResumer` 与 `ArtifactResolver` 已作为统一模块导出。

### 2.2 剩余缺口

1. **缺少独立单元测试**：当前仅在 `tests/orchestrator/test_workflow_engine_integration.py` 中验证 `CheckpointManager` 可导入，缺少对检查点读写、恢复、清理、ArtifactResolver 路径替换等行为覆盖。
2. **`ArtifactResolver` 未接入实际执行链路**：`ArtifactResolver.resolve()` 已实现，但 `StageRunner._build_stage_prompt()` 与 `engine.py` 均未调用它解析产物路径模板，跨阶段产物引用仍为"规划能力"。
3. **决策历史恢复不完整**：
   - `engine._decision_count` 在保存时写入 checkpoint，但运行时从未被更新（决策次数统计实际由 `DecisionHandler._history` 维护）。
   - 恢复时未回填 `engine._decision_count`，也未恢复 `DecisionHandler` 的 `DecisionHistory`，导致从检查点恢复后决策回环/收敛检测可能失效。
4. **检查点版本与兼容性校验缺失**：`Checkpoint.from_dict()` 对未知字段/旧格式仅做静默降级，缺少 `schema_version` 字段和显式校验错误。
5. **状态字段未完全持久化**：`WorkflowState.metadata`、`rollback_events`、`issue_context`、`finished_at` 当前未写入检查点，恢复后这些上下文丢失。
6. **`Checkpoint.metadata` 字段未导出**：`Checkpoint` 包含 `metadata`，但 `to_dict()` 未将其序列化。
7. **`WorkflowResumer` 直接访问 `engine.cost_tracker._total_usd` 私有属性**：恢复成本累计值依赖私有字段，未来 `CostTracker` 重构时可能失效。

### 2.3 下一步计划

1. 补齐 `tests/orchestrator/test_checkpoint_recovery.py`（P0）。
2. 统一决策历史来源：让 `engine._decision_count` 与 `DecisionHandler._history` 使用同一数据源，并在恢复时回填（P1）。
3. 在 `Checkpoint` 中增加 `schema_version` 字段，实现向后兼容校验（P1）。
4. 将 `WorkflowState.metadata`、`rollback_events`、`issue_context` 等纳入检查点持久化范围（P1）。
5. 在 `StageRunner._build_stage_prompt()` 或引擎阶段输入解析中接入 `ArtifactResolver`（P2）。
6. 为 `CostTracker` 提供公共 `set_total_usd()` / `load_state()` 接口，替换 `WorkflowResumer` 对私有属性的访问（P2）。

## §3 实施细节

### 3.1 检查点写入时机

```
DeclarativeWorkflowEngine.execute()
  └── 阶段执行成功
        └── _save_checkpoint(stage.id)
              └── CheckpointManager.save(state, decision_history)
                    └── temp file → os.replace(checkpoint.json)
```

- 每个阶段完成后保存一次检查点。
- 保存失败仅记录 debug 日志，不中断工作流执行。
- `WorkflowOrchestrator.shutdown()` 在优雅关闭时也会保存一次最终状态。

### 3.2 检查点恢复流程

```
WorkflowOrchestrator.run()
  └── checkpoint exists?
        ├── 是 → CheckpointManager.load()
        │            ├── 恢复 stage_results / stage_statuses
        │            └── from_stage = max(completed_stages) + 1
        └── DeclarativeWorkflowEngine.execute(from_stage=from_stage)
                  └── 标记前置阶段为 COMPLETED
                  └── 从 from_stage 继续执行
```

> **注意**：当前恢复流程由 `WorkflowOrchestrator` 完成，`WorkflowResumer.resume()` 提供备用入口但尚未被主流程使用。

### 3.3 产物路径解析

`ArtifactResolver` 支持如下模板：

```yaml
stages:
  - id: 2
    name: report-review
    phase: review
    prompt: "Review the report at ${stage:1:output:report.md}"
```

解析规则：

1. 若 `stage_results[1].artifacts["report.md"]` 存在，返回该路径。
2. 否则若提供 `workspace_dir`，降级为 `<workspace_dir>/stage_01/report.md`。
3. 否则保留原模板字符串不变。

### 3.4 错误处理策略

- 检查点文件不存在：`CheckpointError`。
- JSON 损坏：`CheckpointError`（带原始解析异常）。
- 保存失败：记录日志，不阻断工作流。
- 恢复后发现 `from_stage` 不在 DAG 中：从 DAG 起始位置执行。
- 阶段状态字段非法：`StageStatus` 无法识别时降级为 `COMPLETED`。

## §4 验收标准

1. `CheckpointManager.save()` 原子写入 `checkpoint.json`，崩溃后不产生半写文件。
2. `CheckpointManager.load()` 能正确读取并反序列化之前保存的检查点。
3. `WorkflowOrchestrator` 在存在检查点时自动恢复，从中断阶段继续执行，已完成阶段不再重复运行。
4. 工作流成功完成后检查点被删除；失败后检查点保留并更新最终状态。
5. `ArtifactResolver.resolve()` 能正确替换 `${stage:<id>:output:<name>}` 模板。
6. 新增 `tests/orchestrator/test_checkpoint_recovery.py`，覆盖：检查点读写、`from_stage` 恢复、失败保留/成功清理、`ArtifactResolver` 路径解析。
7. 检查点 schema 增加 `schema_version` 字段，旧版本检查点能降级读取或给出明确错误。
8. 决策历史在恢复后保持连续，回环次数与收敛检测行为与未中断一致。

## §5 风险与约束

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 检查点保存失败导致无法恢复 | 高 | 原子写入避免文件损坏；保存失败仅记录日志不中断当前执行 |
| 恢复后决策回环检测失效 | 中 | F-115-H 统一 `DecisionHistory` 恢复 |
| `ArtifactResolver` 未接入导致跨阶段产物引用失效 | 中 | 当前为规划能力；F-115-G 在 StageRunner 中接入 |
| 检查点版本不兼容导致恢复失败 | 中 | F-115-I 增加 `schema_version` 与降级逻辑 |
| `WorkflowResumer` 访问私有属性 | 低 | F-115 后续提供 `CostTracker` 公共状态加载接口 |
| 检查点包含敏感产物路径 | 低 | 检查点保存在工作区 `.orchestrator_workspace/checkpoints/`，随工作区生命周期管理 |

## §6 已拟定的设计决定

| ID | 决定 | 原因 |
|----|------|------|
| DD-F115-1 | `resume.py` 与 `artifact_resolver.py` 合并到 `checkpoint.py` | 三者均为检查点相关轻量类，合并后减少小文件碎片，便于统一维护 |
| DD-F115-2 | 检查点采用 JSON 格式 + 原子写入 | JSON 便于人工调试；原子写入保证崩溃安全 |
| DD-F115-3 | 每个阶段完成后保存检查点 | 粒度适中，既能从中断处恢复，又避免每轮 Agent 调用都写盘 |
| DD-F115-4 | 检查点保存失败不中断工作流 | 检查点是辅助恢复机制，不应成为主流程的单点故障 |
| DD-F115-5 | `WorkflowOrchestrator` 负责自动检测与恢复检查点 | Orchestrator 掌握 issue 生命周期，最适合决定何时恢复/清理 |
| DD-F115-6 | `ArtifactResolver` 路径模板采用 `${stage:<id>:output:<name>}` | 与常见构建系统 artifact 引用风格一致，易于扩展 |

## §7 依赖与协同

- **前置**：F-110（WorkflowEngine 需要运行时状态与阶段执行钩子）、F-111（StageRunner 生成阶段产物与输出）、F-113（DECISION 阶段历史需要被恢复）。
- **协同**：F-114（阶段验证结果可作为检查点状态的一部分）、F-116（可观测性通过 EventBus 发射 `workflow_start`/`stage_complete` 等事件）。
- **复用**：复用 F-49 的 `SessionStorage` 持久化 Agent session transcript；复用 F-96-A 的 `StateJournalWriter` 记录工作流事件。
- **无上游侵入**：所有实现位于 `extensions/orchestrator/workflow_engine/`，符合解耦原则。

## §8 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-07-10 | 补全子特性、进度跟踪、验收标准、风险、设计决定、依赖协同；同步代码落地状态 | 核心代码已实现，补齐规划缺口 |
