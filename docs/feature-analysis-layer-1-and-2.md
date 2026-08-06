# 特性群分析：clawcodex_ext 与 extensions

> 生成日期：2026-07-25
> 依据：CLAUDE.md 三层解耦架构（Layer 1 = clawcodex_ext/ 下游补丁层，Layer 2 = extensions/ 独立新子系统层）

---

## clawcodex_ext/（Layer 1 — 下游补丁层）

与 `src/` 对应模块耦合的增强/覆盖，共 **6 大特性群**。

> **粗体** = 无直接 `src/` 镜像但因与 agent 运行时耦合而正确驻留 `clawcodex_ext/` 的包。

### 1. 🧠 Agent 运行时生态

| 包 | 上游对应 | 说明 |
|----|---------|------|
| `agent/` | ✔ `src/agent/` | 注册表、策略、Bundled Agents（code_reviewer/docs_writer/test_runner）、Tool Authoring（bash/http/python SDK 可创作工具）、Background Runner、Subagent/Fork、会话管理、验证、转录、Side Question、Chain Filter |
| `assistant/` | ✔ `src/assistant/` | 会话选择器/历史 |
| `tasks/` | ✔ `src/tasks/` | F-94 后台会话管理（BgSession、`/bg` 命令族、全局 index、跨进程 discover） |
| `skills/` | ✔ `src/skills/` | Skills 模型、Bundled Skills 注册 |
| `hooks/` | ✔ `src/hooks/` | PreToolUse / PostToolUse / Stop / Notification / PostSampling hook 运行时 |
| `types/` | ✔ `src/types/` | 消息内容块（Text/Image/ToolUse/ToolResult/Thinking）、流事件（Delta/ToolCall/PhaseComplete）、序列化 |
| **`away_summary/`** | ↔ 耦合 agent + command_system | 离开摘要生成（Config/Controller/Service、Fingerprint、Registration、Prompt 构建）；依赖 `src.command_system.types` + `clawcodex_ext.types` |
| **`goal/`** | ↔ 耦合 agent 会话 | Spec-1 Goal 边界（ThreadGoal 模型、命令、Protocol、门禁） |
| **`dreaming/`** | ↔ 耦合 agent memory | F-100 后台记忆合并（4-phase 合并 prompt、mtime 文件锁、Config、Service 主循环） |

### 2. 🖥️ 用户界面层

| 包 | 上游对应 | 说明 |
|----|---------|------|
| `cli/` + `cli_core/` | ↔ 补丁 `src.entrypoints` | CLI 命令全套：auth/model/provider/tool/sop/channels/gateway/lkb/stats/diag/session_migrate/telemetry；子命令注册模式、运行时命令（`/model`、`/provider`）、解析器、权限 |
| `command_system/` | ✔ `src/command_system/` | 斜杠命令运行时（命令发现、聚合、参数替换、执行管线） |
| `tui/` | ↔ 补丁 `src.entrypoints` | TUI 扩展（App、Screens、Widgets、AgentBridge、消息定义） |
| `frontend/` | ↔ 补丁 `src.entrypoints` | 前端注册（headless/repl/tui 三种，Protocol + Registry + `@register_frontend` 装饰器） |
| `entrypoints/` | ✔ `src/entrypoints/` | 惰性入口导出（HeadlessOptions、TUIOptions、run_headless/run_tui） |
| `repl/` | ↔ 扩展 REPL | REPL 扩展 |
| **`runtime/`** | ↔ 耦合 agent 运行时 | RuntimeContext + RuntimeOptions |

### 3. 🔗 桥接与通信

| 包 | 上游对应 | 说明 |
|----|---------|------|
| `bridge/` | ✔ `src/bridge/` | 多会话桥接：API、JWT、消息、轮询、REPL 桥、UDS 工作密文、Worktree、Capacity Wake、Session ID 兼容、Flush Gate、入站附件/消息 |
| `messaging/` | ↔ 桥接子模块 | 消息子系统 |
| `transports/` | ↔ 桥接子模块 | 传输层 |
| `remote/` | ↔ 桥接子模块 | 远程实现 |

### 4. 🔐 认证、权限与安全

| 包 | 上游对应 | 说明 |
|----|---------|------|
| `auth/` | ✔ `src/auth/` | API 密钥源检测、OAuth 流程、AWS/Gemini/Claude AI 认证、Codex OAuth/Store |
| `permissions/` | ✔ `src/permissions/` | Bash 安全检测（危险模式）、规则权限检查、自动模式分类、ClassificationCache |
| **`feature_gate/`** | ↔ 全系统耦合 | 运行时特性开关（FeatureRegistry、`@feature_gated` 装饰器、ConfigStore、`/feature` 命令） |
| **`diagnostics/`** | ↔ 耦合 query/agent 循环 | F-108 冻结检测看门狗（FreezeSettings、Watchdog、Dump/Resolution 助手） |

### 5. 📚 上下文、记忆与知识

| 包 | 上游对应 | 说明 |
|----|---------|------|
| `context_system/` | ✔ `src/context_system/` | 上下文构建、Prompt 装配、CLAUDE.md 加载、Git 上下文快照 |
| `memory/` | ✔ `src/memory/` | 作用域感知记忆提示构建（user/team scope） |
| `memdir/` | ✔ `src/memdir/` | 记忆目录系统（find_relevant_memories、memory_age） |
| `constants/` | ✔ `src/constants/` | 常量 |
| **`intent_forecast/`** | ↔ 耦合 command_system + session_intelligence | 意图预测（ForecastResult/Suggestion、Context Builder、Learning、Fallback、Focus、Service）；依赖 `src.command_system` + `clawcodex_ext.session_intelligence` |
| **`session_intelligence/`** | ↔ 耦合 agent 会话 | 会话智能辅助（SessionIndex、Summarizer、Queue） |

### 6. 🏗️ 服务化基础设施

| 包 | 上游对应 | 说明 |
|----|---------|------|
| `services/` | ✔ `src/services/` | **25+ 子服务**：`analytics`（分析）、`api`（API）、`bridge`（桥接）、`channels`（频道）、`chrome`（Chrome）、`compact`（压缩）、`computer_use`（计算机使用）、`context_collapse`（上下文折叠）、`feature_gate`（特性门禁）、`ide`（IDE）、`im_gateway`（IM 网关）、`kairos`、`langfuse`（可观测）、`lodestone`、`mcp`（MCP）、`monitor`（监控）、`oauth`（OAuth）、`periodic`（定时）、`pipe_ipc`（管道 IPC）、`proactive`（主动式）、`skill_search`（技能搜索）、`swarm`（Swarm 协调）、`templates`（模板）、`tool_execution`（工具执行）、`ultraplan`（超长规划）、`voice`（语音） |
| `providers/` | ✔ `src/providers/` | Provider 扩展（LiteLLM 适配器、媒体注册、模型发现钩子、OpenAI Compatible） |
| `tool_system/` | ✔ `src/tool_system/` | 工具定义、团队感知工具池、上游 re-export |
| `utils/` | ✔ `src/utils/` | 工具函数 |
| `settings/` | ✔ `src/settings/` | 设置 |
| `query/` | ✔ `src/query/` | 查询扩展 |
| `coordinator/` | ✔ `src/coordinator/` | 协调器模式 |
| `bootstrap/` | ✔ `src/bootstrap/` | 进程初始化/状态 |
| **`compact_service/`** | ↔ 耦合 agent 会话 | 对话压缩服务（CompactBoundaryMetadata、PreservedSegment、边界消息标记） |
| **`cron_system/`** | ↔ 耦合 services | Cron 执行引擎（CronFields、Jitter 配置、运行记录 NDJSON） |
| **`native/`** | ↔ 耦合 tool_system | F-81 原生模块系统：音频捕获、图像 diff、URL Scheme 注册、修饰键检测；懒加载 + 降级（optional dep 缺失时纯 Python fallback） |
| **`multimodel/`** | ↔ 耦合 providers | 多模型调度路由（Fusion/MajorityVote/Scoring 聚合器、Router、SessionBridge、ProviderSlot） |
| **`models/`** | ↔ 耦合 providers | 模型配置注册（`register_model_config()` API） |
| **`buddy/`** | ↔ 耦合 agent 会话 | 语音助手（Companion、Soul、Sprite、Notification、Observer） |
| **`daemon/`** | ↔ Layer 1 补丁 `extensions.daemon` | F-84 Daemon 钩子（特性门禁注册、CLI 动词注册） |
| **`orchestrator/`** | ↔ Layer 1 补丁 `extensions.orchestrator` | 过期注册表同步补丁（daemon 进程间 IssueRegistry 一致性） |
| **`agent_mention/`** | ↔ 耦合 agent | Agent Mention 功能 |
| **`configuration/`** | ↔ 耦合全系统 | 作用域配置发现/可变/合约（JSON Schema、领域推断、Settings Extension 注册） |
| **`debug/`** | ↔ 开发期 | 调试辅助 |
| **`state/`** | — | 存档占位（已归档子系统引用） |
| **`capabilities/`** | — | 能力桥接 re-export（→ `extensions.capabilities`） |
| **`logical_kanban/`** | — | → `lkb` 的兼容 shim（`from lkb import *`） |

---

## extensions/（Layer 2 — 独立新子系统）

共 **9 大特性群**。

### 1. 🤖 编排器 & 自动工作流（最重量级）

| 包 | 说明 |
|----|------|
| `orchestrator/` | **自主编排器核心**：AgentRunner（会话启动/恢复）、Workspace 管理、Issue 注册与追踪、5 种 Tracker 适配器（GitHub / Gitee / GitCode / Linear / Local Tracker）、Git 同步链（pre-commit hook → pre-push verification → post-sync hook → PR 创建）、验证门禁（test/build/lint 命令执行）、报告写入（双写 .md + .ndjson）、Clarification / ClarificationQueue、Workflow 引擎/加载器、任务分解、审批策略（ApprovalPolicy）、AsciicastSink / ChannelSink、CLI 管理（`orchestrator server start` / `issue list` / `resume session`） |
| `orchestrator_runtime/` | 解耦运行时（Phase 0-2）：Protocols + Adapters + Utils，逐步替换旧 orchestrator，入口受 `ORCHESTRATOR_USE_RUNTIME=1` 控制 |
| `context_providers/` | 3 种参考上下文注入提供者：`from_issue`（Issue 追踪）、`from_ci`（CI 状态）、`from_config`（YAML 配置片段）；均通过 `register_section()` 在模块加载时自注册 |

### 2. 🏭 守护进程 & 后台服务

| 包 | 说明 |
|----|------|
| `daemon/` | **F-84 长驻 Supervisor**：Worker 工厂注册（Cron Worker / Remote Control Worker / Task Worker）、进程生命周期管理（spawn / restart / graceful shutdown）、指数退避重启、State 文件 I/O + Liveness 探针、CLI 入口（`daemon server start|stop|status|restart`） |
| `im_gateway/` | **IM 消息网关**：POSIX UDS 监听、REPL/orchestrator 客户端连接管理、Agent Registry 注册主机代理、WeChat 适配器（P2 计划） |

### 3. 📋 LKB（逻辑看板）— 独立 PyPI 包

| 包 | 说明 |
|----|------|
| `lkb/` | **独立包 `lkb`**：规则引擎（Datalog / Clingo / Z3 三种后端，通过 SolverAdapter 统一接口）、一阶逻辑 ATP（Prover9 / Vampire / Mace4）、多世界校验（MultiWorldValidator、FuzzyPatterns）、模糊匹配与歧义检测、本体图谱（OntologyGraph）、规划调度器（SchedulingSolver、ATP-constrained）、真值维护（TMS）、验收模板（AcceptanceTemplate + Governance + Seed）、外部配置 Lint（ExternalConfig）、方法库/治理审核（MethodLibrary/Governance）、审计（Audit）、LLM 事实提取、MCP 服务（validate/decompose/explain/audit）、CLI 入口 |

### 4. 📄 SOP 编译器

| 包 | 说明 |
|----|------|
| `sop_converter/` | **三层映射**：SDK 解析器（SdkParser → atomic_tools）→ Skill 聚合器（SkillGrouper → SkillSpec）→ Agent 构建器（AgentBuilder → AgentDefinition）；工作流模式（Extractors + Generator + Schema + Capability + Bridge）、运行时（CompositeTools、Macros）、依赖/启发式分析（DependencyAnalyzer、Heuristics） |

### 5. 🧪 协议契约层 & 外部 API

| 包 | 说明 |
|----|------|
| `capabilities/` | **层间契约（Layer 1 ↔ Layer 2 边界）**：17 个 Protocol（`adapter_protocol`、`agent_protocol`、`daemon_protocol`、`event_protocol`、`headless_protocol`、`permission_protocol`、`provider_protocol`、`skill_protocol`、`sop_provider_protocol`、`task_protocol`、`team_memory_protocol`、`tool_authoring_protocol`、`tool_protocol`、`acp_protocol`、`context_protocol`、`automation_state_protocol`、`agent_definition_protocol`）+ `recorder.py` + `headless_runner.py` + `dashboard_entry.py` |
| `api/` | **公共 Python API**：OrchestrationSubsystem（编排器子系统）、QueryRunner/Config/Event（查询循环）、QueryMiddleware、DebugLog |
| `remote_api/` | Hermes 兼容远程 Agent API |

### 6. 📊 可视化 & 仪表盘

| 包 | 说明 |
|----|------|
| `visualizer/` | **独立 Web 可视化器（F-167）**：甘特图、时间线、性能分析、看板；Pyodide 运行时、NDJSON/JSONLog 解析器、数据模型、Protocol、Builder、静态前端（CSS/JS） |
| `agent_dashboard/` | **F-120 跨系统只读聚合器**：DashboardStore（进程单例）+ DashboardSourceRegistry + 数据来源（GoalSource / OrchestratorSource / SOPSource / TasksSource）+ Model 工具（DashboardGet / DashboardList） |

### 7. 🔌 扩展集成层

| 包 | 说明 |
|----|------|
| `skills_ext/` | Skills 扩展：SkillRegistryExt（Bundled Skills）、AgentConfig（per-agent 技能配置）、路径解析、生命周期钩子、缓存 |
| `tool_system_ext/` | 工具扩展：Tool Bundle 定义（TOOL_BUNDLES、MODE_BUNDLES）、扩展注册表、Agent 工具配置 |
| `providers_ext/` | LiteLLM Provider（Phase K 迁至 `clawcodex_ext.providers._litellm_adapter`，此为向后兼容 shim） |
| `permissions/` | 权限扩展（`settings_perms` 结构化显式检查） |
| `agent/` | 代理扩展（`session_persist`: `save_to_session_storage` / `load_from_session_storage`） |
| `agents/` | 第三方 Agent 注册辅助（AgentRegistry 的 source="extensions" 快捷方式） |
| `ports/` | 桥接端口定义（bridge_main、transport 基类） |
| `trae/` | Trae IDE 对接指南（P66-E 文档） |

### 8. 🔬 实验与辅助系统

| 包 | 说明 |
|----|------|
| `prompt_lab/` | **F-119 Prompt A/B 框架**：VariantManager、ExperimentAssignment、NDJSONMetricsSink、MetricsSink/VariantProvider Protocol |
| `recording/` | **Asciicast v2 录制器**：AsciicastWriter、Capture、RecordableSourceRegistry、REPL Source 适配器、自包含校验器 |
| `multimodel/` | 多模型（占位） |

### 9. 📡 社区雷达（语义属 Layer 2，物理需迁移）

| 包 | 当前路径 | 说明 |
|----|---------|------|
| **`community_radar/`** | `clawcodex_ext/` → **应迁至 `extensions/`** | **SR-5.1 社区特性雷达**：完全独立的子系统，零依赖 agent 运行时。GitHub 趋势扫描（Fetcher）、特性提取（Extractor）、分类（FeatureClassifier / LLMClassifier）、评分（Scorer）、去重（Deduplicator）、通知（Notifier）、报告生成（Reporter / Jinja2Reporter）、Issue 平台同步（IssuePlatforms / IssueSync）、Pipeline 编排（CommunityRadarPipeline）、Cron 集成、CLI、Source 注册、Dockerfile / Makefile |

---

## 代码布局偏差摘要

语义层与物理位置不一致的只有一个包：

| 模块 | 当前位置 | 语义归属 | 耦合特征 | 建议 |
|------|---------|---------|---------|------|
| `community_radar` | `clawcodex_ext/` ❌ | `extensions/` ✅ | 对 `src.` / `clawcodex_ext.` **零导入依赖**，完全自包含 | 迁至 `extensions/community_radar/` |

其他无 `src/` 镜像的包（`away_summary`、`intent_forecast`、`session_intelligence`、`dreaming`、`goal`、`native`、`feature_gate` 等）因与 agent 运行时耦合（导入 `src.command_system`、`src.agent`、`clawcodex_ext.types` 等），留在 `clawcodex_ext/` 符合 Layer 1 定义。

---

## 附录：代码规模统计

> 统计口径：`.py` 文件，排除 `__pycache__`、`.egg-info`。
> `▲` = 无 `src/` 镜像但合理驻留的包。`*` = services 含 25+ 子服务，仅列汇总。

### clawcodex_ext/ 各特性群

| # | 特性群 | 包 | 文件数 | 代码行数 | 群小计 |
|---|--------|----|-------|---------|-------|
| 1 | 🧠 Agent 运行时生态 | `agent` | 51 | 11,003 | |
|   | | `assistant` | 2 | 265 | |
|   | | `tasks` | 9 | 1,985 | |
|   | | `skills` | 31 | 11,797 | |
|   | | `hooks` | 15 | 3,651 | |
|   | | `types` | 4 | 1,381 | |
|   | | `away_summary` ▲ | 10 | 1,910 | |
|   | | `goal` ▲ | 14 | 4,366 | |
|   | | `dreaming` ▲ | 8 | 1,837 | |
|   | | **小计** | **144** | **38,195** | **38,195** |
| 2 | 🖥️ 用户界面层 | `cli` + `cli_core` | 43 | 9,519 | |
|   | | `command_system` | 34 | 10,718 | |
|   | | `tui` | 95 | 19,330 | |
|   | | `frontend` | 9 | 1,844 | |
|   | | `entrypoints` | 4 | 3,108 | |
|   | | `repl` | 11 | 10,043 | |
|   | | `runtime` ▲ | 4 | 651 | |
|   | | **小计** | **200** | **55,213** | **55,213** |
| 3 | 🔗 桥接与通信 | `bridge` | 30 | 6,388 | |
|   | | `messaging` | 6 | 384 | |
|   | | `transports` | 7 | 1,283 | |
|   | | `remote` | 3 | 750 | |
|   | | **小计** | **46** | **8,805** | **8,805** |
| 4 | 🔐 认证、权限与安全 | `auth` | 8 | 1,551 | |
|   | | `permissions` | 26 | 7,742 | |
|   | | `feature_gate` ▲ | 6 | 1,172 | |
|   | | `diagnostics` ▲ | 4 | 928 | |
|   | | **小计** | **44** | **11,393** | **11,393** |
| 5 | 📚 上下文、记忆与知识 | `context_system` | 16 | 5,018 | |
|   | | `memory` | 2 | 132 | |
|   | | `memdir` | 9 | 2,038 | |
|   | | `constants` | 1 | 64 | |
|   | | `intent_forecast` ▲ | 17 | 3,178 | |
|   | | `session_intelligence` ▲ | 5 | 359 | |
|   | | **小计** | **50** | **10,789** | **10,789** |
| 6 | 🏗️ 服务化基础设施 | `services` * | 257 | 55,069 | |
|   | | `providers` | 32 | 7,493 | |
|   | | `tool_system` | 78 | 22,507 | |
|   | | `utils` | 30 | 6,713 | |
|   | | `settings` | 5 | 1,028 | |
|   | | `query` | 12 | 6,754 | |
|   | | `coordinator` | 3 | 746 | |
|   | | `bootstrap` | 2 | 8 | |
|   | | `compact_service` ▲ | 2 | 239 | |
|   | | `cron_system` ▲ | 15 | 3,886 | |
|   | | `native` ▲ | 5 | 1,191 | |
|   | | `multimodel` ▲ | 32 | 2,340 | |
|   | | `models` ▲ | 2 | 146 | |
|   | | `buddy` ▲ | 9 | 1,401 | |
|   | | `daemon` ▲ | 1 | 71 | |
|   | | `orchestrator` ▲ | 4 | 539 | |
|   | | `configuration` ▲ | 3 | 1,462 | |
|   | | `debug` ▲ | 3 | 1,381 | |
|   | | `state` ▲ | 4 | 1,021 | |
|   | | `capabilities` ▲ | 2 | 145 | |
|   | | `logical_kanban` ▲ | 51 | 166 | |
|   | | **小计** | **552** | **114,306** | **114,306** |
| | **clawcodex_ext 总计** | **6 群** | **1,036** | **238,701** | **238,701** |

### extensions/ 各特性群

| # | 特性群 | 包 | 文件数 | 代码行数 | 群小计 |
|---|--------|----|-------|---------|-------|
| 1 | 🤖 编排器 & 自动工作流 | `orchestrator` | 101 | 43,735 | |
|   | | `orchestrator_runtime` | 27 | 3,263 | |
|   | | `context_providers` | 4 | 276 | |
|   | | **小计** | **132** | **47,274** | **47,274** |
| 2 | 🏭 守护进程 & 后台服务 | `daemon` | 15 | 2,681 | |
|   | | `im_gateway` | 3 | 729 | |
|   | | **小计** | **18** | **3,410** | **3,410** |
| 3 | 📋 LKB（逻辑看板） | `lkb` (src) | 51 | 19,715 | |
|   | | `lkb` (mcp) | 6 | 277 | |
|   | | `lkb` (cli) | 1 | 111 | |
|   | | `lkb` (tests) | 16 | 6,254 | |
|   | | **小计** | **74** | **26,357** | **26,357** |
| 4 | 📄 SOP 编译器 | `sop_converter` | 159 | 30,316 | **30,316** |
| 5 | 🧪 协议契约层 & API | `capabilities` | 21 | 2,282 | |
|   | | `api` | 5 | 968 | |
|   | | `remote_api` | 12 | 2,665 | |
|   | | **小计** | **38** | **5,915** | **5,915** |
| 6 | 📊 可视化 & 仪表盘 | `visualizer` | 28 | 6,273 | |
|   | | `agent_dashboard` | 11 | 1,665 | |
|   | | **小计** | **39** | **7,938** | **7,938** |
| 7 | 🔌 扩展集成层 | `skills_ext` | 10 | 995 | |
|   | | `tool_system_ext` | 6 | 537 | |
|   | | `providers_ext` | 2 | 51 | |
|   | | `permissions` | 2 | 130 | |
|   | | `agent` | 2 | 360 | |
|   | | `agents` | 4 | 1,408 | |
|   | | `ports` | 10 | 5,945 | |
|   | | **小计** | **36** | **9,426** | **9,426** |
| 8 | 🔬 实验与辅助系统 | `prompt_lab` | 6 | 232 | |
|   | | `recording` | 21 | 5,326 | |
|   | | `multimodel` | 0 | 0 | |
|   | | **小计** | **27** | **5,558** | **5,558** |
| 9 | 📡 社区雷达（待迁移） | `community_radar` | 38 | 15,098 | **15,098** |
|   | 补充 | `trae`（对接指南） | 3 | 873 | 873 |
| | **extensions 总计** | **9 群** | **506** | **151,457** | **151,457** |

### 全项目汇总

| 层级 | 目录 | 特性群 | 文件数 | 代码行数 | 占比 |
|------|------|--------|-------|---------|------|
| Layer 1 | `clawcodex_ext/` | 6 群 | 1,036 | 238,701 | 61.2% |
| Layer 2 | `extensions/` | 9 群 | 506 | 151,457 | 38.8% |
| **合计** | | **15 群** | **1,542** | **390,158** | **100%** |

### 各群重量级分布（按代码行数降序）

```
Layer 1 — 服务化基础设施  114,306  ██████████████████████████████████ 29.3%
Layer 1 — 用户界面层        55,213  ████████████████                14.2%
Layer 1 — Agent 运行时生态  38,195  ████████████                    9.8%
Layer 2 — 编排器            47,274  █████████████                    12.1%
Layer 2 — SOP 编译器        30,316  ████████                        7.8%
Layer 2 — LKB 看板          26,357  ███████                         6.8%
Layer 2 — 社区雷达(待迁移)  15,098  ████                            3.9%
Layer 1 — 认证/权限/安全    11,393  ███                             2.9%
Layer 1 — 上下文/记忆       10,789  ███                             2.8%
Layer 1 — 桥接/通信          8,805  ██                              2.3%
Layer 2 — 扩展集成层         9,426  ██                              2.4%
Layer 2 — 可视化/仪表盘      7,938  ██                              2.0%
Layer 2 — 协议/API           5,915  █                               1.5%
Layer 2 — 实验/辅助系统      5,558  █                               1.4%
Layer 2 — 守护进程           3,410  ▉                               0.9%
```
