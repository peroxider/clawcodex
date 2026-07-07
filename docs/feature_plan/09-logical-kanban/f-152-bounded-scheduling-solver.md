# F-152 Bounded Scheduling Solver (OR-Tools CP-SAT)

## Goal

为 LKB 引入 **封闭调度子问题的求解能力**：当用户给定资源约束、时间窗口、任务间依赖时，使用 [Google OR-Tools CP-SAT](https://developers.google.com/optimization) 求解最优调度。这是对 F-149 分解能力的**补充**，不是替代——只在子问题封闭时启用。

LKB 的核心使命是"分解 + 校验"。CP-SAT 的核心使命是**调度**：在已分解好的任务集合上，按资源约束寻找最优执行顺序与时间安排。两者正交，可组合。

## Scope

### In-Scope

- `SchedulingSolver` service（基于 OR-Tools CP-SAT）。
- 任务-资源映射 schema：
  - `Resource`：工程师 / 设备 / CI runner 等，有 capacity、availability windows、skill tags。
  - `SchedulingTask`：从 `ProposedTask` 派生的可调度单元，含 duration、earliest_start、latest_finish、required_skills、predecessors。
  - `Schedule`：求解结果——每个 task 的 start_time / assigned_resource。
- 约束类型：
  - `no_overlap`：同一资源同一时间最多一个任务。
  - `cumulative`：资源累计容量约束（如 N 个 CI runner）。
  - `interval`：`start` / `duration` / `end` 区间变量。
  - `first` / `last`：时窗约束。
  - `before` / `after`：依赖约束（task A 必须在 task B 完成后开始）。
- 优化目标：
  - `makespan`（最小化总工期）— 默认。
  - `resource_level`（最小化资源使用）— 可选。
  - `weighted_completion`（加权完成时间）— 可选。
- 与 `TaskDecompose` 工具的可选集成：当用户输入含 `resources` / `deadline` / `max_makespan` 时，触发 SchedulingSolver 二次求解。
- 优雅降级：OR-Tools 不可用时（依赖缺失），`SchedulingSolver` 抛 `SchedulingUnavailable`，上层捕获并跳过。
- **白名单扩展（必做）**：`DecompositionPlan.scheduling_constraints` / `.schedule` 字段的 dataclass 在 `decomposer.py`；如需 LLM 在 `lkbMetadata` 中携带调度标记（如 `scheduling_required: true`），需同步扩展 `_LKB_METADATA_KEYS` 与 `_validate_lkb_metadata`（参考 F-150 做法）。

### Out-of-Scope

- 开放域任务分解（仍由 F-149 LLM 完成）。
- 资源谈判 / 团队协调（人为活动）。
- 长期排程（>1 季度）：CP-SAT 在大 horizon 上性能下降；MVP 仅支持 ≤30 天 horizon。
- 与 PDDL / HDDL planner 的集成（已否决）。

## 当前基线

- F-149 `DecompositionPlan` 包含 `dependencies: tuple[tuple[str, str], ...]`，但**不包含时间约束**。
- LKB 现有 `Layer1RuleEngine` 处理状态转换 + 依赖校验，**不处理时间窗口**。
- F-142 `SolverPipeline` 集成 Z3 / Vampire / Prover9 做**逻辑一致性证明**，但**不做调度优化**。
- 没有 `Resource` 抽象，也没有 capacity / skill 的概念。

**缺口**：用户输入"5 个任务，2 个工程师，1 周内完成"时，LKB 只能校验依赖图，不能给出具体执行计划。

## 实施进度

### Phase 1 — 依赖集成（~0.5 周）

1. 在 `pyproject.toml` 增加 `ortools>=9.8` 到 `dependencies`（或 `[project.optional-dependencies] scheduling`）。
2. `clawcodex_ext/logical_kanban/scheduling_solver.py` 顶部 `try: from ortools.sat.python import cp_model; except ImportError: CP_MODEL = None`。
3. 定义 `SchedulingUnavailable` 异常。

### Phase 2 — 数据结构（~1 周）

1. `Resource` dataclass：
   - `resource_id: str`
   - `capacity: int`（默认 1）
   - `availability: tuple[tuple[int, int], ...]`（time window 列表）
   - `skills: frozenset[str]`
2. `SchedulingTask` dataclass：
   - `task_id: str`
   - `duration: int`（时间单位：分钟/小时，调用方决定）
   - `earliest_start: int | None`
   - `latest_finish: int | None`
   - `required_skills: frozenset[str]`
   - `predecessors: tuple[str, ...]`
   - `priority: int`（用于加权目标）
3. `Schedule` dataclass：
   - `assignments: dict[str, tuple[int, int, str]]`（task_id → (start, end, resource_id)）
   - `makespan: int`
   - `objective_value: int`
   - `status: Literal["optimal", "feasible", "infeasible", "timeout"]`

### Phase 3 — CP-SAT 建模与求解（~1.5 周）

1. `SchedulingSolver.schedule(tasks, resources, *, horizon: int, objective: str = "makespan", timeout_seconds: float = 5.0) -> Schedule`。
2. 变量建模：
   - `task.start: IntVar(0, horizon)`
   - `task.end: IntVar(0, horizon)`
   - `task.interval: IntervalVar(start, duration, end)`
   - `task.assigned_resource: IntVar(0, len(resources))`
3. 约束：
   - `model.AddNoOverlap([t.interval for t in tasks if same resource])`
   - `model.AddCumulative([...], [capacities])` — 多资源容量约束。
   - `model.Add(task.end <= task.latest_finish)` — 时窗。
   - `model.Add(task.start >= task.earliest_start)` — 时窗。
   - `model.Add(predecessor.end <= task.start)` — 依赖。
   - `model.AddAllowedAssignments([task.interval], skill_compatibility_matrix)` — 技能匹配。
4. 目标：
   - 默认：`model.Minimize(max(task.end for task in tasks))` — makespan。
   - 可选：加权完成时间、资源 level。
5. 求解：`solver.parameters.max_time_in_seconds = timeout_seconds`。
6. 返回 `Schedule`，失败时返回 `status=infeasible` 并附原因。

### Phase 4 — 与 LKB 集成（~1 周）

1. `DecompositionPlan` 增加可选字段 `scheduling_constraints: dict[str, Any] | None`，包含 `resources` / `deadline` / `objective`。
2. `TaskDecomposer.decompose()` 完成后，若 `scheduling_constraints` 不为 None，调用 `SchedulingSolver` 二次求解。
3. 求解结果回填到 `DecompositionPlan.schedule: Schedule | None`。
4. LKB 校验 `Schedule`：
   - 每个 task 的 `assigned_resource` 必须在 `Resource` 列表中。
   - 每个 task 的 `[start, end]` 与依赖图一致。
   - 时窗约束满足。
5. `TaskDecompose` 工具的输出 schema 增加 `schedule: dict | None`。

### Phase 5 — 测试（~1 周）

1. 单元测试：
   - 2 任务 1 资源，无依赖，求 makespan 最优。
   - 5 任务 2 资源，full mesh 依赖，验证 critical path 正确。
   - 时窗冲突 → `status=infeasible`。
   - 技能不匹配 → 任务未被分配或 infeasible。
   - 超时（timeout=0.001s）→ `status=timeout`，不抛异常。
2. 集成测试：
   - TaskDecompose 输入含 `scheduling_constraints`，输出含 `schedule`。
   - 优雅降级：mock `cp_model` 为 None，验证上层捕获 `SchedulingUnavailable`。
3. 黄金集：定义 3 个现实场景（如"5 个 migration 任务 × 2 个 DBA × 1 周 deadline"），验证求解合理。

## 验收标准

- [ ] OR-Tools 依赖加入 `pyproject.toml`，可选 `extras_require=["scheduling"]`。
- [ ] `SchedulingSolver` 在 N≤20 任务 + M≤5 资源 + horizon≤30 天的规模下 <1s 求解。
- [ ] 支持 4 种约束类型：`no_overlap` / `cumulative` / `interval` / `before` / `after` + 时窗。
- [ ] 支持 3 种目标：`makespan` / `weighted_completion` / `resource_level`。
- [ ] `DecompositionPlan.scheduling_constraints` / `.schedule` 字段可选，向后兼容。**注意**：该字段 dataclass 在 `decomposer.py`（不在 `types.py`）；如同步扩展 `lkbMetadata` 携带调度标记，需扩展 `_LKB_METADATA_KEYS` 与 `_validate_lkb_metadata`（参考 F-150）。
- [ ] OR-Tools 不可用时优雅降级，不破坏 F-149 现有功能。
- [ ] LKB 校验 `Schedule` 一致性（依赖、时窗、资源）。
- [ ] `TaskDecompose` 工具输出 schema 增加 `schedule` 字段。
- [ ] 现有 319 个 logical_kanban 测试 + 13 个 F-149 测试 + F-150/F-151 测试全部通过。
- [ ] 新增至少 25 个 F-152 单元测试（含 5 个真实场景黄金集）。

## 风险与约束

| 风险 | 缓解 |
|------|------|
| OR-Tools 学习曲线陡峭 | 封装为高层 API（`SchedulingSolver`），调用方不直接接触 cp_model |
| CP-SAT 在大 horizon 上慢 | MVP 仅支持 ≤30 天；大场景未来用 time-bucketing 扩展 |
| 时间单位不一致 | `SchedulingTask.duration` 明确"调用方决定单位"，docstring 强调 |
| 资源/技能建模过简化 | MVP 不建模资源疲劳度、交接成本；后续 F-N 扩展 |
| OR-Tools license (Apache 2.0) | 与项目 license 兼容，无问题 |
| 与 F-149 的依赖图不一致 | LKB 二次校验 `Schedule.dependencies` ⊆ `DecompositionPlan.dependencies` |
| 调度结果被用户拒绝 | `Schedule` 是建议性的；用户可在 TaskUpdate 中覆盖实际执行时间 |

## 已拟定的设计决定

1. **CP-SAT 仅作为可选后端**：与 F-142 引入 Vampire/Prover9 一致，通过 SolverPipeline 风格的可插拔架构接入。
2. **不存储调度历史**：每次求解独立，无持久化（避免与具体项目强耦合）。
3. **时间单位由调用方决定**：`SchedulingTask.duration` 不强制单位，docstring 明确"minute / hour / day 任选，跨任务一致即可"。
4. **求解结果仅作为建议**：LKB 校验但不强制 task 在指定时间开始——执行灵活性保留给用户。
5. **不引入 PDDL**：CP-SAT 模型直接用 Python API 构建，不经过 PDDL 中间表示。

## 依赖与协同

**依赖**：
- F-149（DecompositionPlan / ProposedTask 数据结构）
- F-150（method 的 subtask_template 可作为 duration 默认值参考）
- OR-Tools（外部库，Apache 2.0）

**被依赖**：
- F-153（方法库治理中"项目级 method"的 duration 等字段可由 SchedulingSolver 求解填充）

**协同**：
- 与 F-142（SolverPipeline）：F-142 做**逻辑一致性**证明（cycle / 不一致），F-152 做**调度优化**（时间 / 资源）。两者互补。
- 与 F-141（causal layer）：调度结果可与因果层联动——关键路径上的 task 失败时触发级联重排。

## 文件变更清单

```
NEW  clawcodex_ext/logical_kanban/scheduling_solver.py     # ~350 行
MOD  clawcodex_ext/logical_kanban/__init__.py              # +10 行（export）
MOD  clawcodex_ext/logical_kanban/decomposer.py            # +60 行（schedule/scheduling_constraints 字段 + 可选 scheduling pass）
MOD  clawcodex_ext/tool_system/tools/task_decompose.py     # +15 行（输出 schedule）
MOD  pyproject.toml                                        # +3 行（ortools optional dep）
NEW  tests/logical_kanban/test_f152_scheduling_solver.py   # ~300 行
```

**注意**：`DecompositionPlan` dataclass 在 `decomposer.py`（不在 `types.py`）。`types.py` 仅含 `FactsSnapshot` / `ValidationIssue` / `ValidationRun` / `ValidationResult`。新增字段应改 `decomposer.py`。

## 估算工作量

| 阶段 | 工时 |
|------|------|
| Phase 1 — 依赖集成 | 0.5 周 |
| Phase 2 — 数据结构 | 1 周 |
| Phase 3 — CP-SAT 建模 | 1.5 周 |
| Phase 4 — 与 LKB 集成 | 1 周 |
| Phase 5 — 测试 | 1 周 |
| **总计** | **5 周** |