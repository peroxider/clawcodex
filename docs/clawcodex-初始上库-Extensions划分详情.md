# ClawCodex 扩展层（extensions/）划分详情

# 按特性（feature）划分的 Part 矩阵

> 对 `extensions/` 全部 25 个有意义的子目录（剔除 `__pycache__/`）做 **100% 覆盖校验**（无遗漏、无重复归属）。
> 分组遵循「**按特性内聚**」而非「按代码量均分」：体量悬殊的目录可能因为职责相近合并到同一 Part，孤儿目录会就近归入。
> 划分目标与 Layer 1 文档对齐 — **便于多人并行开发时各自锁定一组 `extensions/` 子目录，避免互相踩踏**。

---

## 总览

| Part | 主题 | 归属路径数 | 一句话定位 |
|---|---:|---:|---|
| **Part A** | 自主编排核心 | 2 | Orchestrator 编排器主体 + 解耦运行时的实验性孵化层 |
| **Part B** | 智能体生态 + 公共 API | 4 | agent session 持久化 + 三方 agent 注册 / 团队记忆 / 跨子系统 dashboard 聚合 / 公共 Python API 入口 |
| **Part C** | 协议契约 + 通信端口 | 2 | Layer 1→2 Protocol 接口边界 + bridge / transports 适配层 |
| **Part D** | 远程 / IDE 集成 | 2 | Hermes Remote Agent API + Trae IDE 集成 |
| **Part E** | LLM 提供者 + 多模型 | 2 | LiteLLM 转发垫片 + 多模型占位 |
| **Part F** | 工具 / 技能 / 上下文扩展 | 3 | skills_ext + tool_system_ext + context_providers — 上游 skills/tool/context 的解耦补丁层 |
| **Part G** | 智能子系统（提示工程） | 1 | prompt_lab — 提示变体与实验度量 |
| **Part H** | 录制 / 守护 / 权限 | 3 | asciicast 录制 + worker supervisor + 二开权限 |
| **Part I** | Plan Graph 运行时（Logical Kanban） | 1 | lkb — 独立子包，Plan Graph 权威存储（Task-v2） |
| **Part J** | Local Session 可视化 | 1 | visualizer — 独立 Web App，Gantt / Timeline / 性能分析 |
| **Part K** | SOP → Agent 编译器 | 1 | sop_converter — 把专业 SOP 编译为可执行 agent + skill |
| **Part L** | IM Message Gateway | 1 | im_gateway — IM 平台 UDS daemon（微信 / Slack / 等） |
| **Part M** | 社区雷达（特殊归属） | 1 | community_radar — SR-5.1 全新独立子系统，**实际位于 `clawcodex_ext/community_radar/`（Layer 1）**，因"无 `src/` 对应物、纯扩展"按性质应属 Layer 2，故单列 |

> **说明**：各 Part 的 impl 体量不在本文档强制均衡 — `orchestrator/` 单目录就 ~183K 行（agent_runner.py 一个文件），按特性归入 Part A 不再切分；同样地 `extensions/recording/auto_demo.py` ~26K 行与其他录制基础设施同属 Part H，不刻意打散。
>
> **Part M 的特殊性**：本 Part 仅含一个目录但路径不在 `extensions/` 下 — 该目录符合"全新独立子系统"的所有特征（无上游对应物、`src/*` 零侵入、商业化评估为零成本脱离），按 CLAUDE.md 黄金法则 #6 应归 Layer 2。之所以单列 Part M 而非"忽略"，是为了在 Layer 2/3 视角下完整呈现**所有"全新独立子系统"**，便于跨层 owner 在做合并/迁移/拆分规划时一次性看到全貌。

---

## Part A — 自主编排核心（Orchestration & Autonomy Core）

**主题**：自治模式 / Cron / Issue Tracker 主编排器，及解耦运行时的实验性孵化层。

> 仅有 `extensions/orchestrator/` 一个目录就贡献了 extensions/ 里 60%+ 的 impl 体量（`agent_runner.py` 单文件 ~183K 行），因此独立成 Part；`orchestrator_runtime/` 是该编排器的仓内解耦渐进迁移实现，按 "同一编辑器 / 同一设计评审组" 原则就近归入。原纳入的 `extensions/agent/`（session 持久化辅助）因命名与 Part B 的 `agents/` 易混淆，移至 **Part B** 收纳。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/orchestrator/` | Orchestrator 编排器主体：`agent_runner` / `git_sync` / `tracker` 适配（GitHub / Gitee / GitCode / Linear / LocalTracker）/ `workflow` 加载 / `prompt_builder` / `workspace` 管理 / `status_dashboard` / `asciicast_sink` / `approval_policy` 等 |
| `extensions/orchestrator_runtime/` | Orchestrator 解耦运行时子模块（仓内孵化层）：`adapters/`（clawcodex_compat / clawcodex_agent_runtime / clawcodex_coordinator / clawcodex_im_channel / clawcodex_session_storage / clawcodex_bootstrap_state）、`protocols/`（agent_runtime / backend / coordinator / git_backend / im_channel / intent_focus / messages / diagnostics 的 Protocol 声明）、`utils/`（消息 / 诊断 / 引导状态 / git 后端 / 意图聚焦等实现） |

#### Part A.1 — Issue Intake（Issue 入口 / 拉取适配）

负责从外部 tracker 把 Issue 拉进来、注册本地副本、补齐遗漏字段、生成澄清问题、解锁不清前提。

**关键文件**：
- `extensions/orchestrator/issue.py`（Issue 数据模型）
- `extensions/orchestrator/tracker.py`（`TrackerAdapter` 核心契约 + 数据模型 + 7 个能力 Protocol + `supports()`，facade re-export）＋ `intent.py`（`Intent`/`Command` 语义、标签与 `/agent` 命令解析、优先级合并）＋ `tracker_kinds.py`（kind 注册表 / 配置校验 / `create_tracker_adapter` 工厂）
- `extensions/orchestrator/issue_registry/`（子包：`models.py` / `storage.py` / `state_machine.py` / `clarification.py` / `feedback.py` / `intent.py` + `__init__.py` facade，`IssueRegistry` 组合 5 个 mixin）
- `extensions/orchestrator/issue_state_cache.py` / `clarification.py` / `clarification_queue.py` / `premise_check.py`
- 子包 `linear/` / `local_tracker/` / `repo_tracker/`（后者按能力拆为 `client.py`（HTTP+issue 层）/ `normalizers.py`（归一化纯函数）/ `pull_requests.py`（PR 生命周期 mixin）/ `adapter.py`）（**`issue_clarifier/` 子包迁至 A.13**）

**对外接口**：`TrackerAdapter` / `Intent` / `Command` / `PullRequestRef` / `IssueRegistry` / `IssueStatus` / `create_tracker_adapter`

**抽出后边界**：仅负责"拉取 / 注册 / 状态缓存 / 前提校验"，澄清交互下沉至 A.13。

#### Part A.2 — Agent Runtime（代理运行时 / 多模式执行）

每条 issue 拉起一个 `AgentRunner` 子会话；协调单 / 协同 / 辩论 / 流水线 / Swarm 五种执行模式。

**关键文件**：`extensions/orchestrator/{agent_runner.py, approval_policy.py, prompt_builder.py, tool_event_log.py, debug_log.py}`（**`modes/` 子包迁至 A.9**；provider/model 选择逻辑预留抽至 A.10）

**对外接口**：`AgentRunner` / `AgentSession` / `RetryItem` / `PromptBuilder` / `ApprovalPolicy` / `AgentConfig`

**抽出后边界**：仅保留"单 agent 会话生命周期 + 审批 / 提示 / 调试"，多 agent 模式运行时下沉至 A.9，per-stage provider/model 选择下沉至 A.10。

#### Part A.3 — Git Sync（Workspace 与 Git 操作）

为每个 issue 切分支、commit → 验证 → rebase → push、产出 PR；workspace 准备与跨仓 hook。

**关键文件**：`extensions/orchestrator/{git_sync.py}`（**`workspace.py` / `workspace_locator.py` / `workspace_verify.py` / `report_writer.py` 迁至 A.14**）

**对外接口**：`GitSyncService` / `GitSyncResult` / `PRRebaseResult` / `VerificationFailed` / `HookFailedError`

**抽出后边界**：仅保留"分支 + commit + rebase + push + PR"主链路，workspace 生命周期与运行报告下沉至 A.14。

#### Part A.4 — Verification Gate（验证闸门与规则回路）

跑"先复现后修复"前置闸门；接 review 反馈回灌规则库、隔离 PR/issue 规则、审计绕过检测。

**关键文件**：`extensions/orchestrator/{repro_gate.py}`（**`review_feedback.py` / `rules_learner.py` 迁至 A.15**）

**对外接口**：`ReproGateResult` / `evaluate_repro_gate`

**抽出后边界**：仅保留"先复现后修复"前置闸门，review 反馈回灌 + 规则学习下沉至 A.15。

#### Part A.5 — Notification Sink（进度事件出口）

把 agent / orchestrator 的进度事件分流到 TUI / 飞书 / asciicast / IM gateway / state journal / dashboard，供下游可视化与协同使用。

**关键文件**：`extensions/orchestrator/{progress_sink.py, progress_reporter.py（shim）, asciicast_sink.py, channel_sink.py, feishu_activity_sink.py, im_gateway_client.py}`（**`status_dashboard.py` / `state_journal_sink.py` 迁至 A.16**）

**对外接口**：`ProgressSink`(Protocol) / `CompositeProgressSink` / `ToolContextProgressSink` / `ImChannel`

**抽出后边界**：仅保留"进度事件 → 多消费者 fan-out（含 asciicast / 飞书 / IM gateway）"，session 状态可视化下沉至 A.16。

#### Part A.6 — Workflow Engine（声明式工作流引擎）

加载 `workflow.md`、编排阶段 / 检查点 / 成本预算 / 回滚 / 任务分解，运行 `WorkflowOrchestrator`。

**关键文件**：`extensions/orchestrator/{workflow.py, workflow_orchestrator.py, workflow_store.py, templates/}` + 子包 `workflow_engine/`(14 子模块，**`observability.py` / `audit.py` 迁至 A.11**)（**`task_decomposition/` 子包迁至 A.12**）

**对外接口**：`WorkflowLoader` / `WorkflowParseError` / `WorkflowOrchestrator` / `DeclarativeWorkflowEngine` / `EngineConfig` / `WorkflowResult` / `StageRunner` / `CheckpointManager` / `CostBudget`

**抽出后边界**：仅保留"加载 workflow.md → 阶段编排 → 检查点 / 预算 / 回滚"，workflow 阶段级可观测下沉至 A.11，动态任务分解下沉至 A.12。

#### Part A.7 — Core Scheduling（中枢调度 / 高频演进）

编排器"中枢神经"：单实例 `Orchestrator` 协调 A.1-A.6；按 issue 特征选模式、注册状态、报告兜底。所有大型特性入口都汇集于此。

**关键文件**：`extensions/orchestrator/{orchestrator.py, mode_router.py, mode_selector.py}`

**对外接口**：`Orchestrator`（顶层）/ `HeuristicRouter` / `LLMRouter` / `Router` / `ModeSelector`

#### Part A.8 — Operational Surface（运维接入层）

CLI / 控制接口 / 日志 / 事件总线 / 视图 / 配置 schema；供外部脚本、Issue 命令族、dashboard 调用 `Orchestrator`。

**关键文件**：`extensions/orchestrator/{control_socket.py, event_tailer.py, logging_setup.py, session_viewer.py, state_journal.py}` + 子包 `cli/`(9) + 子包 `config/`(2) + 子包 `events/`(4)

**对外接口**：`ControlSocketServer` / `EventTailer` / `StateJournalWriter` / `SessionViewer` / `EventLevel` / `EventEmitter` / `AgentConfig` / `HooksConfig`

> **拆分背景（粗粒度）**：上述 A.1-A.8 对应 F-182 完整设计（见 `docs/feature_plan/02-orchestrator/f-182-subfeature-decoupling.md`）。A.7 跨子包引用最多（编排全栈），依赖 A.1-A.6 的对外接口；A.8 依赖 A.7 的 `Orchestrator` 实例。A.1-A.6 各自边界清晰，可独立迁移；A.9-A.16 为按职责细分的子包（详见下方）。

#### Part A.9 — Multi-Agent Coordination（多 agent 协作模式）

专管"单 / 协同 / 流水线 / 辩论 / Swarm"五种执行模式的协调器，与单 agent 运行时解耦。

**关键文件**：`extensions/orchestrator/multi_agent/modes/`（7 文件：`__init__.py` / `base.py` / `coordinator.py` / `debate.py` / `pipeline.py` / `single.py` / `swarm.py`）

**对外接口**：`ModeRunner`(Protocol) / `ModeDecision` / `DEFAULT_MODE` / `register` / `get` / `available` / `CoordinatorModeRunner` / `PipelineModeRunner` / `DebateModeRunner` / `SwarmModeRunner` / `SingleModeRunner`

#### Part A.10 — Per-Stage Provider/Model Routing（按阶段 provider/model 选择 / P2）

汇总跨 A.2 / A.6 / `config/schema.py` 的 provider/model 选择逻辑，由 F-19 / F-66 主线衍生。**优先级 P2**，待 `contracts/provider.py` 形状确定后再启动。

**关键文件**：`extensions/orchestrator/provider_routing/`（新子包）+ `extensions/orchestrator/contracts/provider_routing.py`；同时抽离 `config/schema.py` 中 `pipeline_stage_models` / `debate_judge_model` / `debate_proposer_models` / `router_model` / `agent.stages` 字段，`agent_runner.py` 的 `_snapshot_provider` / `_snapshot_model`，以及 `modes/pipeline.py` / `modes/debate.py` / `modes/swarm.py` 中 model 选择逻辑

**对外接口**：`ProviderRouter` / `StageProvider` / `StageModel` / `provider_for_stage(stage_id) -> Provider` / `model_for_stage(stage_id) -> str`

#### Part A.11 — Workflow Observability（workflow 阶段级可观测）

专管 workflow 阶段级埋点 + 审计轨迹，独立于 workflow_engine 状态机。

**关键文件**：`extensions/orchestrator/workflow_observability/`（`observability.py` / `audit.py`）

**对外接口**：`WorkflowObservability`（主写入器）/ `AuditTrail` / `write_stage_start` / `write_stage_end` / `emit`

#### Part A.12 — Dynamic Task Decomposition（动态任务分解）

专管"动态拆解复杂 issue 为子任务"。

**关键文件**：`extensions/orchestrator/task_decomposition/`（`__init__.py` / `models.py` / `planner.py`）

**对外接口**：`Subtask` / `TaskPlan` / `TaskDecomposer` / `build_swarm_prompt` / `validate_task_execution` / `write_task_plan`

#### Part A.13 — Issue Clarifier（issue 自动澄清）

专管"issue 描述不清时自动生成澄清问题"。

**关键文件**：`extensions/orchestrator/issue_clarifier/`（7 文件：`__init__.py` / `cache.py` / `gate.py` / `models.py` / `parser.py` / `prompt.py` / `service.py`）

**对外接口**：`IssueClarifierService` / `IssueClarificationGate` / `ClarifierCache` / `ClarifyQuestion` / `ClarifyResult` / `build_fingerprint` / `format_clarification_request`

#### Part A.14 — Workspace Management（workspace 生命周期与运行报告）

专管 workspace 准备、定位、verify 与运行报告落地。

**关键文件**：`extensions/orchestrator/workspace/`（`workspace.py` / `workspace_locator.py` / `workspace_verify.py` / `report_writer.py`）

**对外接口**：`Workspace` / `WorkspaceConfig` / `WorkspaceManager` / `WorkspaceHookError` / `_slug_from_workspace` / `get_workspace_root` / `resolve_for_cli` / `print_workspace_info` / `write_orchestrator_metadata` / `generate_verify_script` / `generate_workspace_readme` / `RunReport` / `ReportResult` / `write()`

#### Part A.15 — Review Rules Ingestion（Review 反馈回灌规则库）

专管"检视意见 → 规则库 → 下次生成"闭环。

**关键文件**：`extensions/orchestrator/review_rules/`（`review_feedback.py` / `rules_learner.py`）

**对外接口**：`ReviewFollowup` / `ReviewFeedbackService` / `RuleStore` / `RuleEngine` / `JudgeResult` / `ExtractTracker` / `BatchedLLMJudge`

#### Part A.16 — Session & Status Dashboard（会话状态仪表）

专管"会话级状态可视化"。

**关键文件**：`extensions/orchestrator/dashboard/`（`status_dashboard.py` / `state_journal_sink.py`）

**对外接口**：`SessionStatus` / `DashboardState` / `ClarificationEntry` / `StatusDashboard` / `StateJournalSink`

#### Part A.17 — Built-in Skills Registry（内置 Skills 注册中心 / P2 候选，暂缓）

跨 A.2 / A.4 的 skills 逻辑统一抽象，**P2 暂缓**，等 F-119 主线触底后再启动。

**关键文件**：待 F-119 主线触底后另立 F-N 单独规划

**对外接口**：待 `SkillRegistry`(Protocol) 形状确定后声明

> **拆分背景**：上述 A.1-A.16 + A.17 候选对应 F-182 完整设计（见 `docs/feature_plan/02-orchestrator/f-182-subfeature-decoupling.md`），用于把编排器（`extensions/orchestrator/`）按职责切分为多个**独立解耦子特性**，便于多人并行维护与按子特性迁移。每个子特性对应一组文件 + 对外接口，**子特性之间互不交叉**。其中：
> - **A.1 / A.3 / A.4 / A.5 / A.6** 各自边界清晰，可独立迁移
> - **A.7（中枢调度）**跨子包引用最多（编排全栈），依赖 A.1-A.6 的对外接口
> - **A.8（运维接入层）**依赖 A.7 的 `Orchestrator` 实例
> - **A.9 - A.16** 在 A.1-A.6 内已按职责细分，互不重叠
> - **A.10** 属 P2（按阶段 provider/model 路由），需先确定 `contracts/provider.py` 形状
> - **A.17** 暂缓，等 F-119 主线触底

### Part A 子特性 × 文件总览表

> 总览 A.1-A.17 子特性对应的文件路径（项目相对路径）。其中 A.1-A.8 为已存在子包（仓库中可直接 Glob 到）；A.9-A.16 为按职责细分的目标子包（目录尚未新建，拆分逻辑见 F-182）；A.17 为 P2 暂缓项。

| 子特性 | 对应文件（项目相对路径） |
|---|---|
| **A.1** Issue Intake | `extensions/orchestrator/{issue.py, tracker.py, intent.py, tracker_kinds.py, issue_state_cache.py, clarification.py, clarification_queue.py, premise_check.py}` + 子包 `issue_registry/`（`models.py` / `storage.py` / `state_machine.py` / `clarification.py` / `feedback.py` / `intent.py` + facade）/ `linear/` / `local_tracker/` / `repo_tracker/`（`client.py` / `normalizers.py` / `pull_requests.py` / `adapter.py`） |
| **A.2** Agent Runtime | `extensions/orchestrator/{agent_runner.py, approval_policy.py, prompt_builder.py, tool_event_log.py, debug_log.py}` |
| **A.3** Git Sync | `extensions/orchestrator/git_sync.py` |
| **A.4** Verification Gate | `extensions/orchestrator/repro_gate.py` |
| **A.5** Notification Sink | `extensions/orchestrator/{progress_sink.py, progress_reporter.py, asciicast_sink.py, channel_sink.py, feishu_activity_sink.py, im_gateway_client.py}` |
| **A.6** Workflow Engine | `extensions/orchestrator/{workflow.py, workflow_orchestrator.py, workflow_store.py, templates/}` + 子包 `extensions/orchestrator/workflow_engine/`（14 子模块） |
| **A.7** Core Scheduling | `extensions/orchestrator/{orchestrator.py, mode_router.py, mode_selector.py}` |
| **A.8** Operational Surface | `extensions/orchestrator/{control_socket.py, event_tailer.py, logging_setup.py, session_viewer.py, state_journal.py}` + 子包 `extensions/orchestrator/cli/`（9 文件）/ `config/`（2 文件）/ `events/`（4 文件） |
| **A.9** Multi-Agent Coordination | `extensions/orchestrator/multi_agent/modes/`（`__init__.py` / `base.py` / `coordinator.py` / `debate.py` / `pipeline.py` / `single.py` / `swarm.py`，共 7 文件） |
| **A.10** Per-Stage Provider/Model Routing | `extensions/orchestrator/provider_routing/`（新子包）+ `extensions/orchestrator/contracts/provider_routing.py`；抽离自 `extensions/orchestrator/config/schema.py` / `agent_runner.py` / `multi_agent/modes/{pipeline.py, debate.py, swarm.py}` |
| **A.11** Workflow Observability | `extensions/orchestrator/workflow_observability/`（`observability.py` / `audit.py`） |
| **A.12** Dynamic Task Decomposition | `extensions/orchestrator/task_decomposition/`（`__init__.py` / `models.py` / `planner.py`） |
| **A.13** Issue Clarifier | `extensions/orchestrator/issue_clarifier/`（`__init__.py` / `cache.py` / `gate.py` / `models.py` / `parser.py` / `prompt.py` / `service.py`，共 7 文件） |
| **A.14** Workspace Management | `extensions/orchestrator/workspace/`（`workspace.py` / `workspace_locator.py` / `workspace_verify.py` / `report_writer.py`） |
| **A.15** Review Rules Ingestion | `extensions/orchestrator/review_rules/`（`review_feedback.py` / `rules_learner.py`） |
| **A.16** Session & Status Dashboard | `extensions/orchestrator/dashboard/`（`status_dashboard.py` / `state_journal_sink.py`） |
| **A.17** Built-in Skills Registry | 当前 `extensions/orchestrator/` 内无对应文件；skills 主逻辑位于 `clawcodex_ext/skills/`（Layer 1），与编排器解耦；待 F-119 主线触底后另立 F-N |

---

## Part B — 智能体生态 + 公共 API（Agent Ecosystem & Public API）

**主题**：agent 数据/会话生命周期（`agent/` + `agents/`）、跨子系统只读 dashboard 聚合、对外面向 SDK 的 Python API 入口 — 把所有"与 agent 持久形态相关的目录"集中到一处。

> 四个目录均围绕「**第三方扩展作者如何在 agent 数据层接入 ClawCodex**」这条主线：单 agent 会话持久化（`agent/`，singular，仅 1 文件）/ 多 agent 注册与团队记忆（`agents/`，plural）/ 跨子系统数据展示（`agent_dashboard`）/ 通过 Python SDK 接入编排（`api`）。其中 `agent/` 与 `agents/` 命名相近（单复数），合并到一个 Part 以消除歧义。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/agent/` 🚧 | **单 agent** session 持久化辅助（singular）：`session_persist.py` 提供 `load_from_session_storage` / `save_to_session_storage`，orchestrator 跑 issue 时读取历史会话使用；体量极小（1 文件 ~14K 行），但与 `agents/`（plural）概念不同 — 前者面向「单会话实例」、后者面向「多 agent 注册 / 团队记忆」。**实际为 Layer 1 补丁**：docstring 自述「Extracted from `src/agent/session.py`」，由 `clawcodex_ext/agent/session.py:85,147` 调用（Layer 1 反向依赖 Layer 2，违反三层架构）。**迁移计划**：迁至 `clawcodex_ext/agent/session_persist.py` 并删除本目录 |
| `extensions/agents/` | **三方 agent** 注册与团队记忆机制（plural）：`team_memory.py`（~37K 行，团队级 memory）、`team_memory_integration.py`、`team_memory_policy.py`；`__init__.py` 暴露 `register()` 默认以 `source="extensions"` 注册。也负责 `*.md` agent 定义文件的发现 |
| `extensions/agent_dashboard/` | F-120 跨子系统只读聚合（dashboard 数据层，无渲染）：`DashboardStore` 单例 + `DashboardSourceRegistry` + `GoalDashboardSource` / `TasksDashboardSource` 等 source 注册；TUI `/dashboard` 命令、Visualizer Web tab、模型工具 `DashboardList` / `DashboardGet` 都从这里读 |
| `extensions/api/` | 公共 Python API（`OrchestrationSubsystem` / `QueryConfig` / `QueryRunner` / `QueryEvent`），Python SDK 通过这一层调用编排与查询子系统；`query.py` 是查询循环主体（~34K 行）。**注意**：其中 `query_middleware.py`（`enforce_request_delay` / `handle_rate_limit_error`）实际为 Layer 1 补丁 🚧，docstring 自述「Extracted from `src/query/query.py`」，由 `clawcodex_ext/query/query.py:1216,1326` 调用；**迁移计划**：迁至 `clawcodex_ext/query/query_middleware.py`，其余 4 个文件（`__init__.py` / `orchestration.py` / `query.py` / `debug_log.py`）保留在 Layer 2 |

---

## Part C — 协议契约 + 通信端口（Protocol Contracts & Communication Ports）

**主题**：层间契约（Layer 1→2 Protocol 边界）+ bridge/transports 适配层（多会话桥接 + 传输层）。

> 二者都是「**跨层 / 跨进程的协议层**」：`capabilities/` 定义上游 `src/` 与下游 `clawcodex_ext/` / `extensions/` 之间的接口边界（抽象协议）；`ports/` 定义进程间 / 远程 session 与本地 REPL 之间的传输适配。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/capabilities/` | Layer 2 Protocol 接口边界：`agent_protocol` / `adapter_protocol` / `acp_protocol` / `dashboard_entry` 等 Protocol 集合；只声明签名（`typing.Protocol`），不包含实现；改动需全员评审（CLAUDE.md 三层架构黄金法则 #4） |
| `extensions/ports/` | 桥接 + 传输端口：`bridge/`（`bridge_main` / `remote_bridge_core` / `repl_bridge` / `session_runner`）+ `transports/`（`hybrid_v1` / `serial_uploader` / `websocket_v1`） — 把多个 REPL 会话、远程客户端与本机 bridge daemon 拼起来 |

---

## Part D — 远程 / IDE 集成（Remote & IDE Integration）

**主题**：对外暴露的远程调用入口 — Hermes 协议、字节 Trae IDE 桥接。

> 二者均服务「**让外部协议或 IDE 客户端驱动 ClawCodex agent**」：Hermes 协议（`remote_api`）/ IDE 插件（`trae`）。属于 ClawCodex 的「对外协议层」。`im_gateway/` 因业务领域（IM 平台）独立、UDS 长连接 + host agent 运行时独特 → 拆为 **Part L**。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/remote_api/` | Hermes 兼容的 Remote Agent API：`core.py`（~48K 行，Hermes 协议主要实现）/ `cli.py` / `auth.py` / `errors.py` / `normalization.py` — 让外部客户端以 Hermes 协议调用 agent |
| `extensions/trae/` | F-66 Trae IDE 集成（Layer 2，完全解耦）：`mcp_bridge.py`（让 Trae IDE 通过 MCP 反向调用 ClawCodex，~21K 行）+ `acp_cli_adapter.py`（把 trae-cli 包装为伪 ACP server，~13K 行）；二者互为正反，形成 MCP↔ACP 双向闭环 |

---

## Part E — LLM 提供者 + 多模型（Providers & Multi-Model）

**主题**：第三方 LLM 提供者接入（LiteLLM）+ 多模型路由/调度。

> 这两个目录是「**LLM 后端」**这一主题 — `providers_ext/` 是已经迁到 `clawcodex_ext.providers._litellm_adapter` 的 deprecated 转发垫片。两者均不大，但归并避免单 Part 孤儿。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/providers_ext/` | LiteLLM Provider 转发垫片（`__init__.py` 从 `clawcodex_ext.providers._litellm_adapter` re-export，保留旧路径以兼容既有 mock 与下游 fork）；新代码应直接 import `clawcodex_ext.providers._litellm_adapter` |

---

## Part F — 工具 / 技能 / 上下文扩展（Tools / Skills / Context Extensions）

**主题**：上游 `src/skills/` / `src/tool_system/` / `src/context_system/` 的解耦补丁扩展层。

> 与 `clawcodex_ext/skills/` / `clawcodex_ext/tool_system/` / `clawcodex_ext/context_system/` 一一对应，但走 `extensions/` 路线（Layer 2+）— 主要面向**三方扩展作者**而非上游兼容。三者都遵循 "不修改 `src/`，仅在 Layer 2 注册/包装" 的解耦原则，是真正意义上的「扩展」。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/skills_ext/` | Skills 扩展层：`SkillRegistryExt`（包装上游 loader + bundle 支持）+ `bundles.py`（skill bundle 定义）+ `agent_config.py`（per-agent skill 配置）+ `paths.py` + `cache.py` + `hooks.py` + `bundled/` 子包 |
| `extensions/tool_system_ext/` | Tool System 扩展层：`bundles.py`（tool bundle 定义）+ `registry_ext.py`（扩展 `ToolRegistry` 添 bundle 支持）+ `agent_config.py`（agent 工具配置 dataclass）+ `registration.py` + `team_filter.py`；与 `patches/tool_system/` 配合快速适配上游 |
| `extensions/context_providers/` | F-119 参考上下文提供者实现（`__init__.py` 时即触发 `register_section`）：`from_issue.py`（issue 上下文，order=55）/ `from_ci.py`（CI 状态，order=56）/ `from_config.py`（YAML 片段注入，order=57）— 展示 `register_section` API 的三种典型用法 |

---

## Part G — 智能子系统：提示工程（Intelligent Subsystems: Prompt Lab）

**主题**：提示工程实验（variant、A/B metric）— 在 agent loop 之外的提示层抽象。

> `prompt_lab` 体现 "**如何让 ClawCodex 在提示层自我迭代**"：变体管理 / 实验分派 / 度量收敛。纯 Python 第三方扩展（无独立子包结构、无运行时 daemon）。`sop_converter/` 因职责独立（编译 SOP → agent + skill，是另一类智能抽象）→ 拆为 **Part K**；`lkb/` 因自带 `pyproject.toml` 独立子包形态 → 拆为 **Part I**；`visualizer/` 因具备完整独立 Web App 形态 → 拆为 **Part J**。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/prompt_lab/` | F-119 A/B variant 框架 skeleton（P119-E）：`VariantManager` + `ExperimentAssignment` + `MetricsSink` + `NDJSONMetricsSink`；纯 stdlib 无三方依赖，提供提示变体管理 / 实验分派 / 指标落地三件套 |

---

## Part H — 录制 / 守护 / 权限（Recording, Daemon & Permissions）

**主题**：演示 / 回放录制（recording）+ 长跑守护进程（daemon）+ 权限补丁（permissions）。

> 三个目录分别对应「**录得下**」（recording）、「**跑得稳**」（daemon）、「**管得住**」（permissions）三个不同维度，同属于「**支撑 ClawCodex 运行的横切关注点**」 — 业务代码不依赖它们，但生产部署都需要它们，因此归并为一个 Part。`visualizer/` 因具备完整独立 Web App 形态 → 拆为 **Part J**。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/recording/` | F-REC asciicast v2 录制（演示 / 回放 / 审计）：`asciicast_writer.py` + `asciicast_writer.AsciicastCapture`/`AsciicastWriter` + `config.RecordingConfig` + `registry`（适配器注册） + `_factories.py` + `auto_demo.py`（自动 demo 录制，~26K 行） + `cast_to_mp4_cli.py` + `cli.py`（~28K 行）；适配器就近放在各子系统目录（如 `extensions/orchestrator/asciicast_sink.py`） |
| `extensions/daemon/` | F-84 长跑守护进程（worker supervisor）：`supervisor`（主循环）+ `lifecycle`（spawn / restart / graceful shutdown）+ `worker_registry`（kind → factory）+ `state`（状态文件 IO + liveness probe）+ `config.DaemonConfig` + `constants` + `errors` + `cli.py`（~16K 行） + `worker_main.py` 等；与 `extensions/orchestrator/orchestrator_runtime/` 不同，本目录负责的是 ClawCodex 整体的 worker 托管 |
| `extensions/permissions/` 🚧 | 二开权限扩展：但 `perms_reader.py` 实际为 Layer 1 补丁，docstring 自述「Extracted from `src/permissions/modes.py`」，由 `clawcodex_ext/permissions/modes.py:142,155` 调用（Layer 1 反向依赖 Layer 2）。**迁移计划**：迁至 `clawcodex_ext/permissions/perms_reader.py` 并删除本目录 |

---

## Part I — Plan Graph 运行时（Logical Kanban）

**主题**：ClawCodex Task-v2 的持久化 / 校验后 Plan Graph 权威存储 — 由 `extensions/lkb/` 独享，自带 `pyproject.toml`，按可独立发布的子包形态存在。

> `lkb/` 因具备独立 `pyproject.toml`（`lkb==0.2.0`）和自成一体的 src / cli / mcp / tests / README 结构，已演化为**独立子包**形态 — 与 Part G 的 prompt_lab / sop_converter（纯第三方扩展）有本质区别。其完整设计见仓内 `extensions/lkb/README.md`（15K 行详细文档）。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/lkb/` | LKB（Logical Kanban）Plan Graph 运行时：`pyproject.toml`（独立子包 `lkb==0.2.0`）+ `src/lkb/`（核心实现，含双图共用一致性内核 / NodeRef / Canonical Assertion IR / TMS / 审计解释能力）+ `cli/`（独立 CLI）+ `mcp/tools/`（独立 MCP 服务）+ `tests/`（自有测试树）+ `README.md`（15K 行详细说明）；ClawCodex Task-v2 的持久化 / 校验后 Plan Graph 权威存储，受 `LKB_PLAN_GRAPH` feature flag 控制 |

---

## Part J — Local Session 可视化（Local Session Visualizer）

**主题**：与 ClawCodex agent session 配套的独立 Web 可视化应用 — Gantt 图 / Timeline / 性能分析。

> `extensions/visualizer/` 已具备**完整独立 Web App 形态**（前端 + builders + fixtures），与 Part H 的 recording / daemon / permissions 在「成熟度 / 依赖面 / 部署形态」上完全不同：visualizer 是一个独立部署的 Web 应用，而 Part H 是后台托管类组件。为避免跨 Part owner 协作时的耦合，独立成 Part。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/visualizer/` | Local Session 可视化（独立 Web App）：Gantt 图 / 时间线 / 性能分析；`__init__.py`（版本 `0.1.0`） + `_rendering.py` + `cli.py` + `builders/`（可视化构建器目录） + `fixtures/`；F-167 起 `asciicast` dashboard source 适配器已迁出至 `extensions.recording.visualizer_dashboard_source`，避免循环依赖 |

---

## Part K — SOP → Agent 编译器（SOP → Agent Compiler）

**主题**：把专业 SOP（Standard Operating Procedure）编译为可执行的 Agent + Skill — 是 "**让 ClawCodex 拥有 SOP 级业务知识**" 的工具链。

> `sop_converter/` 体现 "**如何把结构化的流程文档编译为可执行 agent**"：SDK 规范 → 原子工具 → workflow 步骤 → Agent + Skill 三段映射。虽与 Part G 的 `prompt_lab` 同属"智能抽象"，但**业务领域、输入输出形态、依赖路径都完全不同**：prompt_lab 做提示变体的运行时实验度量，sop_converter 做 SOP 的一次性离线编译；前者面向 prompt，后者面向 SDK Spec。前后端各需独立 owner 锁定。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/sop_converter/` | SOP → Agent 编译器：`SdkParser`（SDK 规范解析）→ atomic_tools / workflow steps → Agent + Skill；`agent_catalog.py`（~18K 行，agent 目录注册）+ `agent_builder.py` + `agent_md_writer.py` + `agent_catalog_resolver.py` + `__init__.py`（导出注册入口） + `adapters/`（三段映射适配） |

---

## Part L — IM Message Gateway（IM 平台 UDS 网关）

**主题**：IM 平台（微信 / Slack 等）触达 ClawCodex agent 的 UDS 长连接网关 daemon — 长跑、有 host agent、与其他"对外协议层"运行时形态截然不同。

> `im_gateway/` 与 Part D 的 `remote_api`（Hermes 协议）/`trae`（IDE 集成）虽然都属于"对外触角"，但**业务领域与运行时形态不同**：Part D 是请求-应答 / IDE 调用的协议层；`im_gateway/` 是长跑 daemon + UDS 监听 + host agent（`server.py` ~24K 行），通过 `clawcodex-dev gateway server start|stop|status|restart` 控制生命周期，是 ClawCodex 的"IM 触达网关"。其 v1 仅交付生命周期 + PID/lock/stale-socket/health；P2 起才会接入微信适配器与完整 `GatewayIpcProtocol` listener。

| 归属路径 | 一句话职责 |
|---|---|
| `extensions/im_gateway/` | IM Message Gateway daemon（UDS 长连）：`server.py`（~24K 行，UDS 监听主进程）+ `host_agent.py`（默认宿主 agent）+ CLI 通过 `clawcodex-dev gateway server start|stop|status|restart` 控制；面向微信 / Slack 类即时通讯平台，让 IM 用户消息路由到 ClawCodex agent |

---

## Part M — 社区雷达（Community Radar, SR-5.1，特殊归属）

**主题**：SR-5.1 开源社区新特性雷达 — 监控 GitHub / Gitee / GitCode 等平台的 release / commit / PR / issue 流，按路线图关键词分类与打分，输出 weekly / monthly digest（双语 + Jinja2 模板渲染），并自动把 MAJOR 级别特性同步到 GitCode / GitHub / Gitee 的 issue tracker。

> **路径错位说明**：本特性的实际代码路径是 **`clawcodex_ext/community_radar/`（Layer 1）**，不是 `extensions/`。`clawcodex_ext/community_radar/__init__.py` 模块 docstring 明确写道：*"This package implements SR-5.1 (Community Feature Radar) entirely inside `clawcodex_ext/*` so it never touches `src/*` and stays clear of the upstream-sync audit."* — 也就是说它**完全没有上游对应物**，也未对 `src/` 做任何侵入性修改。
>
> 按 CLAUDE.md 黄金法则 #6「**对上游模块的增强/覆盖 → `clawcodex_ext/`；全新的独立子系统 → `extensions/`**」，community_radar 应归 Layer 2 才对。但因开发时机早于"无对应物即应放 Layer 2"的规则成熟期，已稳定运行在 `clawcodex_ext/`。本文档据此特殊情况新增 Part M 章节记录事实，并在「待办」段建议未来可迁出到 `extensions/community_radar/`。
>
> 商业化文档 `docs/COMMERCIALIZATION_PLAN.md §4.2.1` 评估其为 **"✅ 零成本脱离"**：仅依赖 Python 标准库 + httpx/litellm/jinja2 等通用三方，零外部项目内依赖，38 文件 / ~15K 行；理论上可作为独立 PyPI 包发布，迁移到 `extensions/community_radar/` 不损失任何功能。

| 归属路径（实际） | 一句话职责 |
|---|---|
| `clawcodex_ext/community_radar/` | SR-5.1 社区雷达主体：`registry`（WatchSource 注册表 + PHASE1/PHASE2 默认源）/ `fetcher`（GitHub/Gitee/GitCode API 并发抓取）/ `extractor`（从 release/commit/PR 抽取特性记录）/ `classifier`（路线图关键词 + 跨域分类守卫）/ `deduplicator`（去重）/ `scorer`（popularity/maturity/adaptation_cost/strategic_value/architecture_fit 五维打分）/ `llm_classifier`（通过 LiteLLM 调 LLM 做 MAJOR/MINOR 重要性分类，含 1 小时 fingerprint 缓存）/ `reporter`（dual-write 双写）+ `templates/weekly_digest.md.j2` `templates/monthly_digest.md.j2` + `i18n`（zh/en 字符串表）/ `notifier`（多渠道摘要推送）/ `cron_integration`（F-22 Cron 适配：`install_cron_task`/`ensure_cron_installed`，默认 `task_id="community-radar-weekly"`）/ `issue_platforms`（GitCode/GitHub/Gitee 平台抽象 + `resolve_target`）/ `issue_sync`（F-119 自动为 MAJOR 特性创建 issue，支持 ask/skip/retry 关闭模式）/ `discover`（GitHub Search 自动发现候选源）/ `pipeline`（`CommunityRadarPipeline.run_scan` + `run_community_scan` 一键扫描入口）/ `cli`（`clawcodex-dev community-radar scan\|source\|config\|status\|issue-sync` 子命令，通过 `clawcodex_ext.cli.subcommand_registry.register("community-radar")` 注册到下游 CLI dispatcher，**完全不解 `src/`**）/ `models` + `config` + `__init__`（公开 surface 与配置） |

### 与其他 Part 的关系

| 关联 Part | 关系类型 | 说明 |
|---|---|---|
| **Part D**（`extensions/remote_api/` Hermes 协议） | 同类但路径错位 | 二者都是"无上游对应物、纯扩展子系统"，但 community_radar 路径在 Layer 1，remote_api 在 Layer 2 |
| **Part K**（`extensions/sop_converter/`） | 同类 | "全新独立子系统"标准范例，与 community_radar 同性质，验证了"按性质应属 Layer 2"的判断 |
| **Part H**（`extensions/daemon/`） | 间接关系 | F-22 `clawcodex_ext.cron_system` 是 daemon 体系的一部分；community_radar 通过 `cron_integration.install_cron_task` 复用其调度能力，**不依赖 daemon 模块本身** |
| **Part B**（`extensions/api/` 公共 API） | 潜在协同 | 未来若把 community_radar 暴露为 SDK 调用（`CommunityRadarPipeline.run_scan`），可注册到 `extensions/api/`，对外提供 Python SDK 入口 |
| **Part H**（`extensions/permissions/`） | 间接关系 | `pipeline._resolve_api_key_for_model` 调用 `src.config.load_config` 读取 LLM provider API key — 这是 Layer 0 调用，**仅用于读配置，非修改**；不破坏"零侵入"承诺 |

### 关键文件位置（速查）

| 用途 | 路径 |
|---|---|
| 模块入口与 re-export 列表 | `clawcodex_ext/community_radar/__init__.py` |
| Pipeline 编排器（一键扫描） | `clawcodex_ext/community_radar/pipeline.py` (`CommunityRadarPipeline.run_scan`, `run_community_scan`) |
| CLI 子命令实现 | `clawcodex_ext/community_radar/cli.py` (`run`, `register_community_radar_subcommand`) |
| 默认 WatchSource 注册表 | `clawcodex_ext/community_radar/registry.py` (`DEFAULT_SOURCES`, `PHASE1_SOURCES`, `PHASE2_SOURCES`) |
| Issue 同步主逻辑 | `clawcodex_ext/community_radar/issue_sync.py` (`sync_features_to_issues`, `sync_single_feature`) |
| Cron 任务适配 | `clawcodex_ext/community_radar/cron_integration.py` (`install_cron_task`, `DEFAULT_CRON_TASK_ID = "community-radar-weekly"`) |
| 双语字符串表 | `clawcodex_ext/community_radar/i18n.py` (`STRINGS`, `Language`, `get_text`) |
| Jinja2 模板 | `clawcodex_ext/community_radar/templates/{weekly,monthly}_digest.md.j2` |
| 单元测试（17 文件） | `clawcodex_ext/community_radar/tests/`（classifier/cli/config/cron_integration/deduplicator/extractor/fetcher/jinja2_reporter/llm_classifier/models/notifier/proposals/registry/reporter/scorer/pipeline/issue_platforms/issue_sync） |

---

| Part | 归属路径 | impl 大致体量 | 锁定者 |
|---|---|---:|---|
| **Part A** | `extensions/orchestrator/` | 极大（~190K 行，单目录 ~60%+） | Part A — 主编排器 + 孵化层 |
| **Part A** | `extensions/orchestrator_runtime/` | 中（孵化中） | Part A — 同上 |
| **Part B** | `extensions/agent/` 🚧 | 小（1 文件 ~14K 行，session_persist）| Part B — 智能体生态 + SDK（**待迁出至 `clawcodex_ext/agent/`**） |
| **Part B** | `extensions/agents/` | 中（~50K 行 team_memory） | Part B — 同上 |
| **Part B** | `extensions/agent_dashboard/` | 中（~25K 行） | Part B — 同上 |
| **Part B** | `extensions/api/` | 大（query.py ~34K 行） | Part B — 同上 |
| **Part C** | `extensions/capabilities/` | 小（接口边界，Protocol 集合） | Part C + 团队负责人共同锁定（变更需全员评审） |
| **Part C** | `extensions/ports/` | 中（bridge+transports 合计 ~6K 行） | Part C — 通信端口 |
| **Part D** | `extensions/remote_api/` | 大（core.py ~48K 行） | Part D — 远程 / IDE 集成 |
| **Part D** | `extensions/trae/` | 中（mcp_bridge ~21K + acp_cli_adapter ~13K） | Part D — 同上 |
| **Part E** | `extensions/providers_ext/` | 极小（转发垫片，已 deprecated） | Part E — LLM 提供者（与 Layer 1 `clawcodex_ext/providers/` 协同） |
| **Part F** | `extensions/skills_ext/` | 中（~12K 行+ bundled） | Part F — skills/tool/context 扩展层 |
| **Part F** | `extensions/tool_system_ext/` | 中（~13K 行） | Part F — 同上 |
| **Part F** | `extensions/context_providers/` | 小（~8K 行，P119-I 参考实现） | Part F — 同上 |
| **Part G** | `extensions/prompt_lab/` | 小（~5K 行 skeleton） | Part G — 智能子系统（提示工程） |
| **Part H** | `extensions/recording/` | 大（auto_demo ~26K + cli ~28K） | Part H — 横切基础设施（录制 / 守护 / 权限） |
| **Part H** | `extensions/daemon/` | 中（cli ~16K + supervisor/lifecycle） | Part H — 同上 |
| **Part H** | `extensions/permissions/` 🚧 | 中（`perms_reader.py` 二开权限补丁） | Part H — 同上（**待迁出至 `clawcodex_ext/permissions/`**） |
| **Part I** | `extensions/lkb/` | 中（独立子包，含 src/cli/mcp/tests） | Part I — Plan Graph 运行时（独立子包，单独锁定） |
| **Part J** | `extensions/visualizer/` | 中（含 builders/fixtures） | Part J — Local Session 可视化（独立 Web App） |
| **Part K** | `extensions/sop_converter/` | 中（agent_catalog ~18K + adapters） | Part K — SOP → Agent 编译器 |
| **Part L** | `extensions/im_gateway/` | 中（server.py ~24K 行 + host_agent） | Part L — IM Message Gateway |
| **Part M** | `clawcodex_ext/community_radar/`（Layer 1 路径，Layer 2 性质） | 中（38 文件 ~15K 行 + 17 个测试文件） | Part M — 社区雷达（特殊归属；详见 Part M 章节，待办：未来可迁出至 `extensions/community_radar/`） |

---

## Layer 错放清查报告（2026-08-04）

**背景**：扫描 `extensions/` 下 22 个目录，结合 4 个判定信号（docstring 是否自述「Extracted from src/...」、上游 `src/` 是否调用、实际调用方在哪个 Layer、是否有 `pyproject.toml`），发现 **3 个文件** 属于 Layer 1 补丁被错放进 Layer 2。这些文件被 `clawcodex_ext/`（Layer 1）模块反向 import，形成 **Layer 1 → Layer 2 的依赖方向**，违反 CLAUDE.md 三层架构（黄金法则 #2：Layer 1 只可 import `src.`，不应跨层 import `extensions.`）。

### 🔴 错放清单（按依赖链顺序）

| 当前路径 | 目标路径 | docstring 自述 | 上游 `src/` | 实际调用方（Layer 1） | 触发违规 |
|---|---|---|---|---|---|
| `extensions/agent/session_persist.py` | `clawcodex_ext/agent/session_persist.py` | "Extracted from `src/agent/session.py` so the upstream Session class remains free of orchestrator-specific SessionStorage / TailFollower concerns" | `src/agent/session.py` | `clawcodex_ext/agent/session.py:85,147` | Layer 1 → Layer 2 |
| `extensions/api/query_middleware.py` | `clawcodex_ext/query/query_middleware.py` | "Extracted from `src/query/query.py` so that the upstream query loop remains free of orchestrator-specific rate-limiting and debugging concerns" | `src/query/query.py` | `clawcodex_ext/query/query.py:1216,1326` | Layer 1 → Layer 2 |
| `extensions/permissions/perms_reader.py` | `clawcodex_ext/permissions/perms_reader.py` | "Extracted from `src/permissions/modes.py` so the upstream mode resolution stays free of F-47-specific config aggregation concerns" | `src/permissions/modes.py` | `clawcodex_ext/permissions/modes.py:142,155` | Layer 1 → Layer 2 |

### 📋 附带影响

| 目录 | 现状 | 迁移后处置 |
|---|---|---|
| `extensions/agent/` | 仅 1 文件（`session_persist.py`） | 整目录删除 |
| `extensions/permissions/` | 仅 1 文件（`perms_reader.py`） | 整目录删除 |
| `extensions/api/` | 5 文件（`__init__.py` / `orchestration.py` / `query.py` / `query_middleware.py` / `debug_log.py`） | 仅 `query_middleware.py` 迁出，其余 4 个保留（Public SDK API 应继续留在 Layer 2） |

### 🧪 测试归属连带变化

| 当前测试 | 迁移后归属 |
|---|---|
| `tests/api/test_query_middleware_rate_limit_fallback.py` | `tests/clawcodex_ext/query/test_query_middleware_rate_limit_fallback.py` |
| `tests/test_session_chain.py`（测 `extensions/agent/session_persist._inject_parent_uuids`） | `tests/clawcodex_ext/agent/test_session_chain.py` |
| `tests/permissions/`（主测 `clawcodex_ext.permissions`，已部分归 Layer 1） | 迁完后剩余测试均归 `tests/clawcodex_ext/permissions/`；原 Part H `tests/permissions/` 计数需重新核对 |

### ✅ 其余 19 个目录 —— 全部正确归属 Layer 2（无需迁移）

| 类别 | 目录 | 证据 |
|---|---|---|
| 独立子系统（独立 pyproject） | `extensions/lkb/`、`extensions/visualizer/` | 含 `pyproject.toml`，独立可发布子包 |
| 核心子系统 | `extensions/orchestrator/`、`extensions/orchestrator_runtime/`、`extensions/remote_api/`、`extensions/sop_converter/`、`extensions/ports/`、`extensions/trae/`、`extensions/im_gateway/`、`extensions/daemon/` | 全新独立子系统，无上游对应物 |
| Layer 2→Layer 1 契约 | `extensions/capabilities/` | `typing.Protocol` 接口边界（CLAUDE.md 黄金法则 #4 指定） |
| 三方扩展注册中心 | `extensions/skills_ext/`、`extensions/tool_system_ext/`、`extensions/context_providers/`、`extensions/agents/`、`extensions/prompt_lab/`、`extensions/recording/` | 注册中心 / Bundle / 配置扩展 |
| 公共聚合层 | `extensions/agent_dashboard/` | F-120 跨子系统只读聚合，非补丁 |
| Public SDK API | `extensions/api/` 中除 `query_middleware.py` 外的 4 个文件 | SDK 入口 |
| 向后兼容垫片 | `extensions/providers_ext/` | docstring 自述 deprecated, 仅保留旧路径 namespace |

### 🔧 推荐迁移顺序

1. **第一步（最干净）**：迁 `extensions/agent/session_persist.py` → `clawcodex_ext/agent/session_persist.py`，整目录删除。同步迁移 `tests/test_session_chain.py`。
2. **第二步（同模式）**：迁 `extensions/permissions/perms_reader.py` → `clawcodex_ext/permissions/perms_reader.py`，整目录删除。同步核查 `tests/permissions/` 归属。
3. **第三步（混合目录）**：迁 `extensions/api/query_middleware.py` → `clawcodex_ext/query/query_middleware.py`，保留 `extensions/api/` 其余 4 个文件。同步迁移 `tests/api/test_query_middleware_rate_limit_fallback.py`。
4. **每步完成后**：跑 `python3 -m pytest tests/stability_gate/ -q --tb=short -x` 与 `python3 -m pytest tests/orchestrator/ --ignore=tests/orchestrator/manual_e2e_f38.py -q`，确保无回归。

> 本节为审计结果存档，**不替代具体迁移 PR 的 review**。每步迁移应在 PR 描述中引用本节作为动机，并在 docstring 与 import path 同步更新后再次跑稳定性门禁。

---

## 排除项（不算任何 Part）

| 路径 | 原因 |
|---|---|
| `extensions/__init__.py` | 顶层初始化文件，不归属任何 Part |

---

## 与 Layer 1 文档（`clawcodex_ext/`）的对应关系

| Layer 1 文档 Part | Layer 2/3 文档（本文档）Part | 备注 |
|---|---|---|
| P1 — L1 Agent 核心 | Part A（编排核心）与 Part B（智能体生态）相关 | Layer 1 侧重 agent loop；Layer 2/3 侧重编排上层 |
| P2 — Command/Query/Bridge/Providers | Part C（ports）+ Part E（providers_ext，延伸） | providers 实际主体在 Layer 1 |
| P3 — Services Group A + Buddy | Part L（im_gateway 独立 IM 网关） | Layer 2/3 im_gateway 走 UDS 而非上游；语音 / 频道类对应仍在 Layer 1 |
| P4 — Services Group B | （无直接对应） | Layer 1 服务群在 Layer 2/3 不重复实现 |
| P5 — CLI 与入口 | （无直接对应 — `extensions/` 不放 CLI 主入口；CLI 主入口在 Layer 1） | 但 Part B 的 `api/` Python 入口承担类似角色 |
| P6 — TUI/REPL/前端 | Part J（visualizer 独立 Web App）+ Part B（agent_dashboard 数据源） | TUI 主渲染在 Layer 1，extensions 仅 dashboard 数据源 + 独立可视化 App |
| P7 — 权限/鉴权/钩子 | Part H（permissions 延伸） | 权限主体在 Layer 1 |
| P8 — 智能子系统 | Part F（context_providers）+ Part G（prompt_lab）+ Part K（sop_converter）+ Part I（lkb 独立子包） | 部分对应 |
| P9 — 调度/基础设施 | Part D（daemon）+ Part C（ports）+ Part H（daemon 延伸） | 调度基础设施重在 Layer 1 cron_system，Layer 2/3 是其外部壳 |
| （无 Layer 1 对应项 — 路径错位） | Part M（community_radar，实际位于 `clawcodex_ext/community_radar/`） | **特殊归属**：本应归 Layer 2（无上游对应物的全新独立子系统），但实际在 Layer 1；详见 Part M 章节路径错位说明 |

> **结论**：本文档独立于 Layer 1 划分详情，不重复 Layer 1 内容；只在 Part 之间按特性分组，方便 owner 锁定自己负责的 extensions/ 子目录。

---

## Layer 2/3 测试归属矩阵（tests/）

### 测试归属总览（按 Part）

| Part | tests 路径 | tests 行数 | 测试文件数 | 归属类型 | 备注 |
|---|---|---:|---:|---|---|
| **Part A** | `tests/orchestrator/` | **33,177** | 69 | 严格归属 | 单目录体量最大的测试集，含 F-38/F-39/F-42/F-45/F-49/F-120/F-121 等多个 feature 编号测试；`manual_e2e_f38.py` 需 LocalTracker + bare-origin temp dir，CI 通过 `--ignore` 排除 |
| **Part B** | `tests/api/` + `tests/extensions/agent_dashboard/` + `tests/extensions/agents/` + `tests/test_session_chain.py`（延伸） | **3,347+** | 18+ | 严格归属 + 延伸 | `api/` 主测 query 循环（含 `query_middleware` 速率限制回退，迁移后归 `tests/clawcodex_ext/query/`），agent_dashboard 测 DashboardStore + 7 个 source，agents 测 team_memory 四件套；`tests/test_session_chain.py` 测 `extensions/agent/session_persist._inject_parent_uuids`，迁移后归 `tests/clawcodex_ext/agent/` |
| **Part C** | `tests/extensions/capabilities/` + `tests/transports/` + `tests/bridge/`（延伸） | **10,445** | 42 | 延伸覆盖 | `tests/extensions/capabilities/` 测 dashboard_entry Protocol；`tests/transports/` 测 `extensions/ports/transports/`（hybrid_v1/serial_uploader/websocket_v1）；`tests/bridge/` 跨 Layer 1+2 bridge |
| **Part D** | `tests/remote_api/` + `tests/trae/` | **2,348** | 6 | 严格归属 | remote_api 测 Hermes 协议（remote_api.py/cli.py/stdlib_server.py），trae 测 MCP bridge + ACP adapter + ACP protocol |
| **Part E** | （无） | 0 | 0 | — | `extensions/providers_ext/` 已 deprecated，测试随主体迁出 |
| **Part F** | `tests/extensions/tool_system_ext/` | **156** | 1 | 严格归属 | 仅测 team_filter；`extensions/skills_ext/` 与 `extensions/context_providers/` 暂无独立测试（待 P119 系列继续扩展时补齐） |
| **Part G** | （无） | 0 | 0 | — | `extensions/prompt_lab/` 是 P119-E skeleton，metrics sink 默认 NDJSON 可由调用方自行测试 |
| **Part H** | `tests/extensions/recording/` + `tests/extensions/daemon/` | **5,723** | 21 | 严格归属 | recording 测 asciicast writer + auto demo + 多种 sink/observer/projector + 4 个 e2e；daemon 测 supervisor/lifecycle/state/worker_registry/cli + e2e_supervisor。注：`tests/permissions/` 主要测 `clawcodex_ext.permissions`（Layer 1）—— 待 `extensions/permissions/perms_reader.py` 🚧 迁出后，perms 相关测试应一并归 `tests/clawcodex_ext/permissions/` |
| **Part I** | `extensions/lkb/tests/`（内嵌） | （见 lkb 子包） | — | 内嵌测试 | LKB 独立子包自带完整 tests 树（`unit/` + `integration/` + `repository/` + `concurrency/` + `smoke/` + `ui/` + `conftest.py`），不属于顶层 `tests/lkb/` |
| **Part J** | `tests/test_visualizer/` + `tests/visualizer/` | **3,330** | 8 | 严格归属 | `test_visualizer/` 测布局/解析/服务/ws 等核心组件（7 文件），`tests/visualizer/` 测 dashboard 路由（1 文件）；F-167 起 visualizer_dashboard_source 已迁出至 `extensions.recording.visualizer_dashboard_source` |
| **Part K** | `tests/sop_converter/` | **475** | 4 | 严格归属 | 测解耦（`test_decoupling.py`）/ 打包 / skill 分组 / SOP 默认值；体量小因 sop_converter 主要是离线编译器，单测聚焦关键路径 |
| **Part L** | （无专属） | 0 | 0 | 无测试 | `extensions/im_gateway/` 暂无独立测试；`tests/services/im_gateway/`（19 文件）测的是 Layer 1 `clawcodex_ext.services.im_gateway`，不属本 Part。Part L v1 仅交付生命周期 + PID/lock/stale-socket/health，集成测试通过手测完成，P2 起才会补对应测试 |
| **Part M** | `clawcodex_ext/community_radar/tests/`（内嵌） | **4,896** | 18 | 内嵌测试 | 路径与源码同级（`clawcodex_ext/community_radar/tests/`），按"源码邻近测试"原则放置，与传统 `tests/` 目录并列存在；17 个测试文件覆盖 classifier/cli/config/cron_integration/deduplicator/extractor/fetcher/jinja2_reporter/llm_classifier/models/notifier/proposals/registry/reporter/scorer/pipeline/issue_platforms/issue_sync 等所有子模块 |

### 测试归属汇总（速查表）

| 归属 | tests 行数 | tests 文件数 |
|---|---:|---:|
| **Part A** — Orchestration Core | 33,177 | 69 |
| **Part B** — Agent Ecosystem + Public API | 3,347 | 18 |
| **Part C** — Protocol Contracts & Comm Ports | 10,445 | 42 |
| **Part D** — Remote & IDE Integration | 2,348 | 6 |
| **Part E** — LLM Providers（deprecated） | 0 | 0 |
| **Part F** — Tools/Skills/Context Extensions | 156 | 1 |
| **Part G** — Prompt Lab | 0 | 0 |
| **Part H** — Recording/Daemon/Permissions | 5,723 | 21 |
| **Part I** — LKB（内嵌 tests） | 见子包 | — |
| **Part J** — Local Session Visualizer | 3,330 | 8 |
| **Part K** — SOP → Agent Compiler | 475 | 4 |
| **Part L** — IM Message Gateway | 0 | 0 |
| **Part M** — Community Radar（内嵌 tests） | 4,896 | 18 |
| **合计** | **63,897** | **187+** |

> Part E / Part G / Part L 测试覆盖为零，对应三种不同原因：Part E（已 deprecated）、Part G（skeleton 未交付）、Part L（生命周期层 v1 仅交付外壳，P2 才补）。这三种状态应在 owner 锁定时分别处理。
>
> Part M 的测试在源码路径内（`clawcodex_ext/community_radar/tests/`）而非顶层 `tests/`，这是"源码邻近测试"模式 — 适用于可独立打包发布的子包（与 Part I lkb 自带 tests 同模式），与 Part A–L 顶层 `tests/<part>/` 模式形成两种风格对照。社区雷达未来若迁至 `extensions/community_radar/`，测试路径选择（迁到 `tests/community_radar/` 或保留内嵌）应在迁移决策时一并考虑。
>
> Part H 测试行数（5,723）实际归属仅 recording + daemon，而 `tests/permissions/`（15 文件 ~3,420 行）主要测 `clawcodex_ext.permissions`（Layer 1）— 这是"测试目录在 tests/ 下但被测对象在 Layer 1"的典型案例，文档明示以避免 owner 误锁。

### 与 CI / 稳定性门禁的关系

- **CI `.github/workflows/ci.yml` 的 `test-gate` job** 默认排除 `tests/orchestrator/manual_e2e_f38.py`（需 LocalTracker + bare-origin temp dir），其余 Part A 单元测试均跑
- **稳定性门禁 `tests/stability_gate/`**（9,040 行）**不**属于本文档的 Layer 2/3 归属 — 它是"端到端稳定性守卫"，横跨 Layer 0/1/2 测核心 CLI/TUI/REPL/Agent 等系统级入口
- **LKB 独立测试**（`extensions/lkb/tests/`）通过 `lkb` 子包自身的 pytest 配置运行，与主仓 CI 部分独立
- **community_radar 内嵌测试**（`clawcodex_ext/community_radar/tests/`）通过 `pytest clawcodex_ext/community_radar/tests/` 单独运行，与主仓 `tests/` 目录并列

---

- [ ] **Part I / lkb 子包迁移**：lkb 拥有独立 `pyproject.toml`，未来可能拆分为独立 PyPI 包；届时 `extensions/lkb/` 应迁出 `extensions/` 树，与本文档同步更新（已独立成 Part I owner 锁定）
- [ ] **Part E / providers_ext deprecated**：与 `clawcodex_ext.providers._litellm_adapter` 重复，Phase K 迁移完成后建议删除 `extensions/providers_ext/` 整目录
- [ ] **Part F / context_providers**：P119-I 已交付，但与 P119-E（`prompt_lab`）分别落地于 Part F / Part G，未来如果两者继续扩展，需要按"agent → context → 提示实验"一条主线重新评估分组边界
- [ ] **测试目录**：本文档仅覆盖 `extensions/` 源目录；其 `tests/orchestrator/`、`tests/recording/` 等测试目录归属见各自的测试 owner
- [ ] **Part M / community_radar 路径归位评估**：现位于 `clawcodex_ext/community_radar/`（Layer 1），但本质是无 `src/` 对应物的全新独立子系统（CLAUDE.md 黄金法则 #6 应归 Layer 2）。商业化文档 §4.2.1 评估"零成本脱离"，理论上可迁至 `extensions/community_radar/` 后独立打包。决策要点：(1) 是否同步 F-22 Cron 适配层迁移；(2) CLI 注册 `clawcodex_ext.cli.subcommand_registry.register("community-radar")` 是否随之迁移；(3) issue_sync 依赖的 GitCode/GitHub/Gitee token 配置路径是否重构。完成迁移后本文档 Part M 章节将相应更新为"已迁出 Layer 1"或"保留 Layer 1，标注历史原因"。
