# F-118: 动态任务分解引擎

> 状态: 🟢 全部实现（核心 10 项 + §4 后续增强 7 项全部落地）
> 章节: docs/feature_plan/02-orchestrator/f-118-dynamic-decomposition.md
> 最后更新: 2026-07-21

## §0 当前实现

F-118 不再新建一套 subagent 运行时，也不复用仅适用于交互会话的
`fork_subagent`。当前实现建立在已有的 collaboration mode 和
`CoordinatorModeRunner` 上：

1. `TaskDecomposer` 从 issue 或 CLI prompt 生成有界的 seed task graph。
2. `TaskPlan` 校验任务 ID、依赖、wave、并行上限和循环依赖。
3. 计划写入工作区 `.orchestrator_control/task_decomposition.json`。
4. `SwarmModeRunner` 把结构化计划交给现有 coordinator，由 coordinator 按 wave
   调度 worker，并要求每个 worker 返回事实、改动、测试和风险。
5. Agent 完成后继续走 orchestrator 原有 verification 和同步流程。

实现入口：

- `extensions/orchestrator/task_decomposition/` — `__init__.py` (18 行) + `models.py` (78 行) + `planner.py` (355 行)
- `extensions/orchestrator/modes/swarm.py` (79 行) — `SwarmModeRunner` 桥接 `CoordinatorModeRunner`
- `extensions/orchestrator/mode_selector.py` (191 行) — `mode:swarm` label + heuristic router + `KNOWN_MODES` 注册表
- `clawcodex_ext/cli/parser.py` — `--swarm` / `--decompose` / `--effort normal|swarm` 三个 CLI flag
- `clawcodex_ext/cli/dispatch.py` — L410-432 把 swarm 请求转换为 TaskDecomposer + build_swarm_prompt

测试覆盖：`tests/orchestrator/test_task_decomposition.py` + `tests/services/test_swarm.py`，**41/41 通过**（耗时 5.02s）。

### 0.1 触发方式

```bash
# 独立 CLI，自动进入 headless coordinator 模式
clawcodex --swarm "refactor the provider layer and verify compatibility"
clawcodex --decompose "refactor the provider layer and verify compatibility"
clawcodex --effort swarm "refactor the provider layer and verify compatibility"
```

Orchestrator workflow：

```yaml
modes:
  enabled: [single, swarm]
  default: single
  router:
    kind: heuristic
  swarm:
    max_subtasks: 8
    max_parallel: 3
    max_waves: 6
```

Issue 可用 `mode:swarm` 强制触发；`mode:auto` 或无 mode 标签时，router 会把
`swarm`、`decompose`、`multi-step`、`parallel tasks`、`complex bug` 等描述路由到
swarm。

## §1 能力范围

| 能力 | 当前实现 |
|------|----------|
| 任务复杂度分析 | mode router 负责 single/pipeline/coordinator/debate/swarm 选择 |
| 子任务分解 | 显式列表提取；没有列表时生成 investigate → implement → verify seed plan |
| 依赖分析 | `depends_on` + 拓扑 wave；循环和未知依赖直接拒绝 |
| 执行模式 | 同 wave 并行、跨 wave 串行；并行数量有硬上限 |
| 子 agent 调度 | 复用 coordinator 的 Agent/SendMessage/TaskStop worker 运行时 |
| 结果合并 | coordinator prompt 强制结构化汇总 worker 事实、改动、测试和风险 |
| 验证循环 | coordinator 可创建有界 repair task；最终仍走原有 orchestrator verification |
| 可恢复证据 | seed plan 持久化到 `.orchestrator_control/task_decomposition.json` |
| 执行证据校验 | worker 按 schema 写入 `task_evidence/<task-id>.json`（status / evidence / timestamps），`validate_task_execution` 在 coordinator 完成后校验：全部 completed、有非空证据、依赖顺序（mtime 排序）、并行峰值 ≤ max_parallel。**per-task 文件中的 timestamp 仅作为 worker 声明，依赖顺序以 host 文件 mtime 为准。** |
| session 合约注入 | `SwarmModeRunner.run()` 在 coordinator 运行前注入 4 个 session 属性：`session.task_decomposition_path`（plan 文件路径）、`session.task_decomposition`（seed plan 的 dict snapshot）、`session.prompt_override`（含 evidence 指令的 swarm prompt）、`session.run_kind = "swarm"`。上层调用者（report_writer、dashboard）可通过这些属性感知 swarm 上下文。 |

## §2 设计约束

1. F-118 不依赖 F-110 声明式工作流引擎。
2. F-118 不使用 `fork_subagent`。fork 在非交互和 coordinator 场景下有意关闭。
3. 任务数、wave 数、并行数必须有界，不能让模型无限拆分。
4. 同一文件不能由两个并行 worker 同时编辑；有重叠时必须串行。
5. task graph 是运行证据，不是新的持久化 workflow DSL。

## §3 已完成

- [x] `TaskPlan` / `Subtask` 数据模型和校验
- [x] 显式任务提取和三阶段 fallback 分解
- [x] 依赖拓扑排序和 bounded waves
- [x] 计划 JSON 原子落盘（`.orchestrator_control/task_decomposition.json`）
- [x] `SwarmModeRunner` + coordinator 调度
- [x] `mode:swarm`、heuristic router 和 mode registry
- [x] `--swarm` / `--decompose` / `--effort swarm`
- [x] `build_swarm_prompt` 生成含 evidence 指令的 coordinator prompt（per-task 写入 `task_evidence/<task-id>.json`，host mtime 做依赖排序，不在并行 worker 间共享文件）
- [x] `validate_task_execution` 执行证据校验（全部 completed、非空证据、依赖顺序、并行峰值 ≤ max_parallel）
- [x] 单元测试覆盖计划、路由、配置、runner、CLI parser 和 evidence 校验（7 个 evidence 专项测试）

## §4 后续增强（已全部实现）

- [x] 用可注入 LLM planner 对 seed plan 做结构化重写，而不是只让 coordinator 在 prompt
  中自行细化。当前 `TaskDecomposer` 已支持 `llm_client` + `planner_strategy` 注入点，
  `_llm_rewrite_plan` 实现了 `refine` 和 `restructure` 两种策略，带 JSON 解析和错误回退。
- [x] 将 worker 的完成状态和证据按 schema 回写 task graph，并在缺失时硬失败。当前
  `validate_task_execution` 能从 `task_evidence/*.json` 读取证据，
  `_backfill_evidence` 在验证通过后将证据回写到 `task_decomposition.json` 和
  `session.task_decomposition`。
- [x] 接入每个 subtask 的独立 token/cost 计量和 issue 级美元预算。`Subtask` 模型已含
  `token_cost` / `budget` 字段，`SwarmModeRunner` 注入 `cost_tracker` 参数，
  `_backfill_evidence` 回写 `token_cost`。
- [x] daemon 崩溃后根据 task graph 状态从未完成 wave 恢复，而不是整轮重跑。`_resolve_or_resume`
  检查 `swarm_checkpoint.json` checkpoint，`_write_checkpoint` 在 `finally` 块写入。
- [x] 为文件所有权冲突增加静态检查，而不只依赖 coordinator 指令。`Subtask` 已含
  `affected_files` 字段，`TaskPlan._check_file_conflicts` 在 `validate()` 时检查
  同 wave 文件重叠，`_from_explicit_tasks` 通过 `_FILE_REF` 正则提取文件路径。
- [x] 在 `SwarmModeRunner.run()` 启动前清理 `task_evidence/` 目录，避免 F-39 retry 场景
  下旧 evidence 文件残留导致 `validate_task_execution` 假阳性失败。
- [x] CLI `--swarm` 模式（`dispatch.py` 中的 `Issue(id="cli-swarm")`）不经过 orchestrator
  的正常 issue 跟踪流程：无 `IssueRecord` 持久化、无 summary comment、无 PR 创建。已
  在 CLI 模式下打印 stderr 说明告知用户这一限制。

## §5 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始探索文档 | 四文档合并 |
| 2026-07-02 | `5e1cfdab` enable multi-agent coordinator mode in headless flow | F-118 的运行时前置（coordinator 入口开放） |
| 2026-07-08 | `af0c31dc` 统一代码风格修复 | ruff 风格合规 |
| 2026-07-11 | 完成 bounded swarm MVP，改为复用 coordinator | 避免重复运行时和非交互 fork 冲突 |
| 2026-07-20 | `2f7b0cff` F-118 task decomposition and F-124 issue clarifier MVP | TaskDecomposer + SwarmModeRunner + 模式路由 + CLI 集成 + 单元测试正式合入（核心 commit） |
| 2026-07-21 | 文档同步 | 补全 commit hash 与实现统计（行数 / 测试通过数），状态行增补 §4 待办标注 |
| 2026-07-21 | 文档补全 | 补全 §1 能力表（执行证据校验、session 合约注入）、§3 已完成列表（build_swarm_prompt / validate_task_execution / 7 个 evidence 专项测试）、§4 后续增强（task_evidence 清理、文件冲突静态检查、CLI 模式限制、每项附实现状态说明）
| 2026-07-21 | §4 七项全部实现 | 文件冲突静态检查、task_evidence 清理、LLM planner 注入、证据回写、token/cost 计量、checkpoint 恢复、CLI 模式限制说明；41/41 测试通过，稳定性门禁 Stage 1-5 全通过 |
