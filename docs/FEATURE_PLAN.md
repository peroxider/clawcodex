# ClawCodex 特性规划与设计文档

> 文档路径: `docs/FEATURE_PLAN.md`
> 版本: v3.16（F-108 Freeze Detection & Auto-Recovery 规划）
> 更新日期: 2026-06-23 | 上游同步: f32e6b0 (dev-decoupling-refactor-b24b8cb)
>
> **v3.16 变更（F-108 Freeze Detection & Auto-Recovery 规划）**：
>   - F-108 Freeze Detection & Auto-Recovery：全链路代码审计发现 8 个卡死风险点（2 CRITICAL + 3 HIGH + 2 MEDIUM + 1 LOW），采用四层混合方案解决——Layer 0 快速修复（Permission/AskUser 超时、headless future 硬超时、Tool 级超时）、Layer 1 轻量冻结检测（FreezeDetector）、Layer 2 配置化硬超时防护、Layer 3 自动恢复策略、Layer 4 诊断命令。新增 8 子特性 P108-A~H，总预计 7 天。
>   - 附录 F-Number 快速索引同步更新：F-108 新增。
>
> **v3.15 变更（F-107 PowerShell 支持增强规划）**：
>   - F-107 PowerShell 支持增强作为跨平台适配特性纳入规划管线，§2.19 记录完整详细设计。新增 8 子特性 P107-A~H，覆盖工具 schema 扩展、进程启动适配、命令分类、安全分析、技能传播等全链路，总预计 6-8 天。
>   - 附录 F-Number 快速索引同步更新：F-107 新增。
>
> **v3.10 变更（F-49 状态修正——代码实现交叉验证）**：
>   - F-49 Phase 0.4（全场景会话恢复统一闭包）：§1.4.3 从 📋 设计草稿中 → ✅ 已完成（`Session.resume()` JSONL 消息加载、REPL/TUI/CLI 三端 resume 路径修复、Cron/Orch .json 快照写入，已在 `clawcodex_ext/agent/session.py` + `clawcodex_ext/repl/core.py` + `clawcodex_ext/tui/app.py` + `clawcodex_ext/cli/dispatch.py` + `clawcodex_ext/agent/background_runner.py` 完整落地）。
>   - F-49 Phase 5（session.json + transcript.jsonl 合并）：§1.4.5 从 📋 规划中 → ✅ 已完成（P5-A~G 全部落地：`Session.save()` 不再写 session.json、`Session.load()` 读 enhanced transcript JSONL、cost_restore 读尾行、session_persist 写 session_init 首行、metadata.json 精简单字段）。
>   - 附录 F-Number 快速索引同步更新：F-49 状态修正。
>
> **v3.11 变更（F-71 SnipTool 完成 + 多特性状态对齐）**：
>   - F-71 SnipTool 实现：「历史消息片段截取工具」落地 `clawcodex_ext/tool_system/tools/snip.py`（282 行）。支持按索引范围/角色/关键词过滤对话历史，text/json/summary 三种输出格式，只读且并发安全。注册于 `ALL_STATIC_TOOLS`（共 42 工具），别名 `context_snip` / `history_snip`。稳定性门禁 245/245 全绿。F-71 状态从 📋 规划中 → 🔄 进行中。
>   - F-62 Chrome 自动化：从 📋 规划中 → ✅ 已完成（`src/services/chrome/` Playwright/MCP/Null 三后端 + 7 个 chrome_* 工具已注册到 `EXTENSION_TOOLS`）。
>   - F-65 Langfuse 可观测性：从 🔄 进行中 → ✅ 已完成（`src/services/analytics/` + `src/services/langfuse/` 全链路实现）。
>   - F-67 Buddy/Proactive：从 📋 规划中 → ✅ 已完成（`src/buddy/` 8 文件完整实现：companion/observer/soul/sprites/types/prompt/notification/feature）。
>   - F-88 Explore/Plan Agent：从 📋 规划中 → ✅ 已完成（P88-A~D 全部完成：内置 Agent 定义 + `routing.py` 自动路由 + `report_store.py` 双格式写盘；17 个新单测）。
>   - 附录 F-Number 快速索引同步更新：F-62/F-65/F-67/F-71/F-88 状态修正。
>
> **v3.12 变更（F-102 Agent Loop Hook 扩展点规划）**：
>   - Agent loop 代码审计发现 5 个 hook 缺口：pre-LLM 通用扩展钩子、post-LLM/pre-tool 恢复策略注册表、outbox 类型化、formal plugin hook registry、逐 turn 回调注册。
>   - F-102 作为基础设施特性纳入规划管线，§2.18 记录完整详细设计。新增 5 子特性 P102-A~E，总预计 9-15 天。
>   - 附录 F-Number 快速索引同步更新：F-102 新增。
>
> **v3.14 变更（代码实现交叉验证——§五 Cron / §七 CCB 特性状态修正）**：
>   - F-22 Cron 系统执行引擎：Phase B（存储与模型对齐）、Phase C（调度器语义对齐）、Phase D（执行队列与结果追踪）、Phase E（skills 与用户命令）经代码验证全部完成，状态同步更新。5.3.2 文件清单补充 runs.py/status.py/schedule.py 三个已实现模块。
>   - F-65 Langfuse 可观测性：§七 CCB 总览表从 🔄 进行中 → ✅ 已完成（代码位于 `src/services/langfuse/` 933 行，客户端/Sink/Exporter 全链路已完整实现）。
>   - F-67 Buddy/Proactive：§七 CCB 总览表从 ❌ 未实现 → ✅ 已完成（代码位于 `clawcodex_ext/buddy/` 1,371 行 8 模块完整实现 + CLI 命令已注册）。
>   - F-69 Budget/Poor Mode：§七领先优势节从 📋 规划中 → 🔄 进行中（代码位于 `clawcodex_ext/query/token_budget.py` 159 行，BudgetTracker/ContinueDecision/StopDecision 等已实现）。
>   - F-70 Plugin 系统：§七 CCB 总览表从 ❌ 未实现 → 🔄 进行中（代码位于 `src/plugins/` 8 文件 1,070 行，注册表/加载器/依赖/校验/市场等基础框架已存在）。
>   - 附录 F-Number 快速索引同步更新：以上 F-Number 状态修正。
>
>
> **v3.9 变更（代码审计综合对齐）**：
>   - F-9 /goal 命令：§2.6 从 📋 待实现 → ✅ 已完成（`clawcodex_ext/goal/` 9 文件 2538 行完整实现：状态机/持久化/续跑/Tool/prompt/CLI 命令 6 大子系统全）。
>   - F-11 sessionStorage 容量限制：状态确认 ✅ 已完成（`src/services/session_storage.py` 已有 `MAX_CACHED_SESSION_FILES=1000` 容量上限逻辑，PROGRESS.md 同步修正）。
>   - F-37 PR 检视意见自动修复闭环：确认状态为 ✅ 已完成（`extensions/orchestrator/review_feedback.py` 157 行 + GitSync follow-up 全链路；PROGRESS.md §1.2 同步修正）。
>   - F-64 Voice Mode：从 📋 规划中 → 🔄 接口层已完成（`src/services/voice/` 检测 + STT 抽象类 188 行，运行时集成待补）。
>   - F-65 Langfuse 可观测性：从 📋 规划中 → 🔄 进行中（`src/services/analytics/` 事件/元数据/导出 sink 共 247 行，Langfuse SDK 集成待补）。
>   - F-70 Plugin 系统：从 📋 规划中 → 🔄 进行中（`src/plugins/` 8 文件 1070 行：注册表/加载器/依赖/校验/市场/IDE集成/MCP集成等已有基础框架）。
>   - F-78 Issue 语义澄清流程：从 📋 规划中 → ✅ 已完成（`extensions/orchestrator/clarification.py` + `clarification_queue.py` 共 865 行：三通道优先机制完整实现）。
>   - F-80 Agent 间自主观察与消息交互：从 📋 规划中 → ✅ 已完成（`clawcodex_ext/tool_system/tools/task_inspect.py` + `task_directives.py` 共 642 行，已在 `EXTENSION_TOOLS` 注册）。
>   - 附录 F-Number 快速索引同步更新：以上 8 个 F-Number 状态修正。
>
> **v3.6 变更（F-100 + F-73 状态对齐）**：
>   - F-100 Dreaming 后台记忆整合系统 §2.16 标题状态从 📋 设计中改为 🔄 进行中（100.1~100.7 七子特性全 ✅，Phase A/C/D/E 已完成，Phase B 30min TTL 增强待补；106 单测 + 12 门禁 + 6 E2E 场景全绿）。
>   - F-73 从待开始更新为“本地已完成 / 远端待验证”。
>   - GitCode workflow 目标配置、local CI fallback、pre-commit、mypy required gate、package smoke、release preflight、publish helper 与安全扫描 helper 已落地。
>   - mypy 已从 advisory 提升为阻塞门禁；duplicate-module 发现问题已修复，legacy 类型债务以 `pyproject.toml` 显式 baseline 管理，后续逐项收缩。
>   - 因当前仓库 GitCode Pipeline / CodeCheck / Release 附件 / PyPI token 能力尚待开通，远端执行与生产发布仍保留为后续验证项。
>
> **v3.4 变更（代码实现审计对齐）**：全面修正 5 项特性状态与代码不对齐。
>   - F-37 PR 检视意见自动修复：📋 规划中 → ✅ 已完成（PullRequestFeedback/ReviewFeedbackConfig/ReviewFeedbackService/Orchestrator review follow-up 全部落地）
>   - F-46 permission_mode 正交拆分：📋 规划中 → 🔄 进行中（F-46.0：headless auto-override 已实现；F-46.1：三字段正交拆分待后续）
>   - F-54 运行期可观测性：目录标记与状态对齐为 🔄 进行中
>   - F-12 cacheWarning 容量限制：状态补充为 🔄 进行中（CacheWarning 类已在 clawcodex_ext/utils/cache_warning.py 实现）
>
> **v3.1 变更（代码检视审计）**：完成全量功能实现状态代码交叉验证。主要修正：F-40 (ProgressReporter Sink) 状态从 📋 规划中 → ✅ 已完成。该特性已在 `extensions/orchestrator/progress_sink.py` 完整落地（`ProgressSink` Protocol / `CompositeProgressSink` / `ToolContextProgressSink`），`progress_reporter.py` 降级为 shim。
>
> **v3.0 变更（目录重构）**：从目录视角合并同类项，原 10 章压缩为 **8 章 + 附录**。已完成特性降级为一行注记；F-40 被割裂的设计稿归入所属子节；§9(CCB 对标)与§10(Python 生态补缺)合并为单章并按子领域分组；跨章节重复概念去重。本文件保留 v2.17 所有内容，仅做结构重组。

---


## 目录

- [ClawCodex 特性规划与设计文档](#clawcodex-特性规划与设计文档)
  - [目录](#目录)
  - [项目概述与边界约束](#项目概述与边界约束)
    - [项目定位](#项目定位)
    - [当前架构（三层解耦）](#当前架构三层解耦)
    - [核心约束](#核心约束)
    - [约束起源](#约束起源)
  - [已归档功能模块](#已归档功能模块)
  - [一、Orchestrator 系统](#一orchestrator-系统)
    - [Orchestrator 系统概述](#orchestrator-系统概述)
    - [1.1.1 LocalTracker 本地 Issue 文档源设计（F-36 ✅）](#111-localtracker-本地-issue-文档源设计f-36-)
    - [1.1.2 PR 检视意见自动修复闭环（F-37 ✅）](#112-pr-检视意见自动修复闭环f-37-)
    - [1.1.3 验证与报告闭环（F-38 ✅）](#113-验证与报告闭环f-38-)
    - [1.1.4 Issue 重跑入口（F-39 ✅）](#114-issue-重跑入口f-39-)
    - [1.2.1 Shared/Sequential Workspace（F-42 ✅）](#121-sharedsequential-workspacef-42-)
    - [1.2.2 ProgressReporter Sink 重构（F-40 ✅）](#122-progressreporter-sink-重构f-40-)
    - [1.3.1 AgentRunner 空转检测机制（F-51 ✅）](#131-agentrunner-空转检测机制f-51-)
    - [1.3.2 运行期可观测性与 stuck-run debug（F-54 🔄）](#132-运行期可观测性与-stuck-run-debugf-54-)
        - [改造点清单](#改造点清单)
        - [消息流向全图](#消息流向全图)
        - [验收标准](#验收标准)
        - [风险与约束](#风险与约束)
        - [已拟定的设计决定](#已拟定的设计决定)
        - [依赖与协同](#依赖与协同)
    - [1.4.4 会话格式分层参考图（全场景一览）（F-49 ✅）](#144-会话格式分层参考图全场景一览f-49-)
        - [全场景 resume 能力矩阵（Phase 0.4 完成后）](#全场景-resume-能力矩阵phase-04-完成后)
    - [1.4.5 session.json + transcript.jsonl 合并（F-49-P5 ✅）](#145-sessionjson--transcriptjsonl-合并f-49-p5-)
        - [问题现状：三文件的冗余与不一致风险](#问题现状三文件的冗余与不一致风险)
        - [目标：从 3 文件减为 2 文件，消除消息冗余](#目标从-3-文件减为-2-文件消除消息冗余)
        - [文件格式规范](#文件格式规范)
        - [读写流程对比](#读写流程对比)
        - [具体改造点](#具体改造点)
        - [向后兼容策略](#向后兼容策略)
        - [方案对比验证](#方案对比验证)
        - [验收标准](#验收标准-1)
        - [风险与约束](#风险与约束-1)
        - [依赖与协同](#依赖与协同-1)
    - [1.4.6 parentUuid 链 + walkChainBeforeParse 读取过滤（F-103 ✅）](#146-parentuuid-链--walkchainbeforeparse-读取过滤f-103-)
        - [问题现状](#问题现状)
        - [核心设计](#核心设计)
        - [改造点清单](#改造点清单-1)
        - [验收标准](#验收标准-2)
        - [风险与约束](#风险与约束-2)
        - [已拟定的设计决定](#已拟定的设计决定-1)
        - [依赖与协同](#依赖与协同-2)
    - [1.5.1 声明式工作流引擎核心（F-1.10 📋）](#151-声明式工作流引擎核心f-110-)
    - [1.5.2 StageRunner 适配器（F-1.11 📋）](#152-stagerunner-适配器f-111-)
    - [1.5.3 GATE 门禁处理器（F-1.12 📋）](#153-gate-门禁处理器f-112-)
    - [1.5.4 DECISION 决策处理器（F-1.13 📋）](#154-decision-决策处理器f-113-)
    - [1.5.5 阶段契约验证器（F-1.14 📋）](#155-阶段契约验证器f-114-)
    - [1.5.6 检查点与恢复（F-1.15 📋）](#156-检查点与恢复f-115-)
    - [1.5.7 工作流可观测性集成（F-1.16 📋）](#157-工作流可观测性集成f-116-)
    - [1.6.1 动态任务分解引擎（F-118 🔭）](#161-动态任务分解引擎f-118-)
  - [二、Agent 核心能力](#二agent-核心能力)
    - [2.1 Agent 阶段性进度汇报（F-20 ✅）](#21-agent-阶段性进度汇报f-20-)
    - [2.2 Team 成员管理（Phase-7）（F-2 ✅）](#22-team-成员管理phase-7f-2-)
    - [2.3 结构化输出增强（Outlines）（F-4 ✅）](#23-结构化输出增强outlinesf-4-)
    - [2.4 MCP 扩展功能（F-3 ✅）](#24-mcp-扩展功能f-3-)
      - [2.4.1 待增强（F-3 ✅）](#241-待增强f-3-)
    - [2.5 Agent 记忆作用域隔离（F-13 ✅）](#25-agent-记忆作用域隔离f-13-)
    - [2.6 /goal 命令（目标管理）（F-9 ✅）](#26-goal-命令目标管理f-9-)
    - [2.7 ExecuteExtraTool 延迟工具系统（F-10 📋）](#27-executeextratool-延迟工具系统f-10-)
      - [2.7.1 功能说明（F-10 📋）](#271-功能说明f-10-)
      - [2.7.2 核心机制（F-10 📋）](#272-核心机制f-10-)
      - [2.7.3 实现文件（F-10 📋）](#273-实现文件f-10-)
    - [2.8 工具/Skill 调用统计（跨会话）（F-75 ✅）](#28-工具skill-调用统计跨会话f-75-)
      - [统计所有 skill 调用](#统计所有-skill-调用)
      - [统计工具 vs skill 调用比例](#统计工具-vs-skill-调用比例)
      - [统计某个 agent 的调用](#统计某个-agent-的调用)
      - [2.8.10 基于使用频率的工具/Skill 裁剪（F-75 ✅）](#2810-基于使用频率的工具skill-裁剪f-75-)
      - [2.8.11 SOP 转化模式（F-75 ✅）](#2811-sop-转化模式f-75-)
      - [2.8.12 业务 Agent 长期使用（新窗口重连）（F-75 ✅）](#2812-业务-agent-长期使用新窗口重连f-75-)
    - [2.9 CreateAgentTool 动态工具创建（F-18 ✅）](#29-createagenttool-动态工具创建f-18-)
    - [2.10 sessionStorage 容量限制（F-11 ✅）](#210-sessionstorage-容量限制f-11-)
    - [2.11 cacheWarning 容量限制（F-12 ✅）](#211-cachewarning-容量限制f-12-)
    - [2.12 Issue 语义澄清流程（自主模式扩展）（F-78 ✅）](#212-issue-语义澄清流程自主模式扩展f-78-)
    - [2.13 Auto 模式 (TRANSCRIPT\_CLASSIFIER)（F-16 ✅）](#213-auto-模式-transcript_classifierf-16-)
    - [2.14 Agent 间自主观察与消息交互（F-80 ✅）](#214-agent-间自主观察与消息交互f-80-)
    - [2.15 Ctrl+C/B 即时中断响应优化（F-99 ✅）](#215-ctrlcb-即时中断响应优化f-99-)
    - [2.16 Dreaming 后台记忆整合系统（F-100 🔄）](#216-dreaming-后台记忆整合系统f-100-)
      - [背景](#背景)
      - [现状（clawcodex 侧）](#现状clawcodex-侧)
      - [方案](#方案)
      - [任务拆分](#任务拆分)
      - [风险与缓解](#风险与缓解)
      - [依赖](#依赖)
      - [实施落地（2026-06-18）](#实施落地2026-06-18)
    - [2.18 Agent Loop Hook 扩展点增强（F-102 🔄）](#218-agent-loop-hook-扩展点增强f-102-)
      - [背景](#背景-1)
      - [子特性分解](#子特性分解)
      - [影响范围](#影响范围)
      - [实现文件清单](#实现文件清单)
      - [核心注入点（query.py）](#核心注入点querypy)
      - [验收标准](#验收标准-3)
      - [依赖与协同](#依赖与协同-3)
      - [测试](#测试)
      - [后续验证项](#后续验证项)
    - [2.19 PowerShell 支持增强（F-107 📋）](#219-powershell-支持增强f-107-)
      - [当前基线](#当前基线)
      - [子特性分解](#子特性分解-1)
      - [详细设计](#详细设计)
        - [P107-A — 工具 schema 扩展 + shell 检测](#p107-a--工具-schema-扩展--shell-检测)
        - [P107-B — 进程启动层适配](#p107-b--进程启动层适配)
        - [P107-C — 工具 Prompt 适配](#p107-c--工具-prompt-适配)
        - [P107-D — 命令分类适配](#p107-d--命令分类适配)
        - [P107-E — 命令语义适配](#p107-e--命令语义适配)
        - [P107-F — PowerShell 安全分析](#p107-f--powershell-安全分析)
        - [P107-G — 技能系统 shell 传播](#p107-g--技能系统-shell-传播)
        - [P107-H — Shell 基础设施统一](#p107-h--shell-基础设施统一)
      - [验收标准](#验收标准-4)
      - [不纳入范围](#不纳入范围)
      - [风险与约束](#风险与约束-3)
      - [已拟定的设计决定](#已拟定的设计决定-2)
      - [依赖与协同](#依赖与协同-4)
      - [实施建议顺序](#实施建议顺序)
      - [测试](#测试-1)
      - [修改文件](#修改文件)
    - [2.20 Freeze Detection \& Auto-Recovery（F-108 📋）](#220-freeze-detection--auto-recoveryf-108-)
      - [当前基线（卡死风险点审计）](#当前基线卡死风险点审计)
      - [方案架构：四层混合方案（Layer 0 ~ Layer 4）](#方案架构四层混合方案layer-0--layer-4)
      - [子特性分解](#子特性分解-2)
      - [详细设计](#详细设计-1)
        - [P108-A — Permission/AskUser 超时（Layer 0，#2 #3）](#p108-a--permissionaskuser-超时layer-02-3)
        - [P108-B — Headless Query Future 超时（Layer 0，#5）](#p108-b--headless-query-future-超时layer-05)
        - [P108-C — Tool 执行超时（Layer 0，#6）](#p108-c--tool-执行超时layer-06)
        - [P108-D — FreezeDetector 冻结检测（Layer 1）](#p108-d--freezedetector-冻结检测layer-1)
        - [P108-E — 超时配置 schema 扩展（Layer 2）](#p108-e--超时配置-schema-扩展layer-2)
        - [P108-F — Agent loop / turn / tool 三层硬超时（Layer 2）](#p108-f--agent-loop--turn--tool-三层硬超时layer-2)
        - [P108-G — 自动恢复策略（Layer 3）](#p108-g--自动恢复策略layer-3)
        - [P108-H — freeze-report CLI 子命令（Layer 4）](#p108-h--freeze-report-cli-子命令layer-4)
      - [实施建议顺序](#实施建议顺序-1)
      - [验收标准](#验收标准-5)
      - [关键设计决定](#关键设计决定)
      - [依赖与协同](#依赖与协同-5)
  - [三、CLI 与配置系统](#三cli-与配置系统)
    - [3.1 CLI 模型供应商与模型切换设计（F-43 ✅）](#31-cli-模型供应商与模型切换设计f-43-)
    - [3.3 Permission Settings Schema 重构设计（F-47 ✅）](#33-permission-settings-schema-重构设计f-47-)
  - [四、Architecture \& SDK 下沉](#四architecture--sdk-下沉)
    - [4.2 SOP 转换器源码固化设计（F-50 ✅）](#42-sop-转换器源码固化设计f-50-)
      - [4.2.1 SOP 转换器分组策略增强设计（F-55 ✅）](#421-sop-转换器分组策略增强设计f-55-)
      - [4.2.2 工作流判别器（F-50.10 📋）](#422-工作流判别器f-5010-)
      - [4.2.3 工作流结构提取器（F-50.11 📋）](#423-工作流结构提取器f-5011-)
      - [4.2.4 阶段能力映射器（F-50.12 📋）](#424-阶段能力映射器f-5012-)
      - [4.2.5 工作流 Schema 生成器（F-50.13 📋）](#425-工作流-schema-生成器f-5013-)
      - [4.2.6 Agent 定义生成器（工作流模式扩展）（F-50.14 📋）](#426-agent-定义生成器工作流模式扩展f-5014-)
      - [4.2.7 源码桥接器生成器（F-50.15 📋）](#427-源码桥接器生成器f-5015-)
      - [4.2.8 提取器适配器库（F-50.16 📋）](#428-提取器适配器库f-5016-)
    - [4.3 Python SDK 方法注册为 Tool（F-52 ✅）](#43-python-sdk-方法注册为-toolf-52-)
    - [4.4 Tool 自动暴露为 CLI 斜杠命令（F-53 📋）](#44-tool-自动暴露为-cli-斜杠命令f-53-)
        - [背景](#背景-2)
        - [设计目标](#设计目标)
        - [架构](#架构)
        - [命令行格式](#命令行格式)
        - [实现切片](#实现切片)
        - [验收标准](#验收标准-6)
        - [风险与约束](#风险与约束-4)
        - [依赖与协同](#依赖与协同-6)
  - [五、Cron 系统执行引擎（F-22 🔄）](#五cron-系统执行引擎f-22-)
    - [5.1 背景与目标（F-22 🔄）](#51-背景与目标f-22-)
    - [5.2 参考实现边界（F-22 🔄）](#52-参考实现边界f-22-)
    - [5.3 当前 ClawCodex 状态诊断（F-22 🔄）](#53-当前-clawcodex-状态诊断f-22-)
      - [5.3.1 fallback 工具层（F-22 🔄）](#531-fallback-工具层f-22-)
      - [5.3.2 下游扩展核心模块（F-22 🔄）](#532-下游扩展核心模块f-22-)
      - [5.3.3 关键运行路径断点（F-22 🔄）](#533-关键运行路径断点f-22-)
    - [5.4 完整还原的目标行为（F-22 🔄）](#54-完整还原的目标行为f-22-)
      - [5.4.0 2026-06 最新 CCB 对比缺口复核（F-22 🔄）](#540-2026-06-最新-ccb-对比缺口复核f-22-)
    - [5.5 目标架构（F-22 🔄）](#55-目标架构f-22-)
    - [5.6 实施阶段（F-22 🔄）](#56-实施阶段f-22-)
      - [Phase A — runtime-first 接线 ✅ 已完成](#phase-a--runtime-first-接线--已完成)
      - [Phase B — 存储与模型语义对齐 ✅ 已完成](#phase-b--存储与模型语义对齐--已完成)
      - [Phase C — scheduler 语义对齐 ✅ 已完成](#phase-c--scheduler-语义对齐--已完成)
      - [Phase D — 执行队列与结果追踪 ✅ 已完成](#phase-d--执行队列与结果追踪--已完成)
      - [Phase E — skills 与用户命令 ✅ 已完成](#phase-e--skills-与用户命令--已完成)
      - [Phase F — teammate / agent ownership](#phase-f--teammate--agent-ownership)
    - [5.7 文件格式（F-22 🔄）](#57-文件格式f-22-)
      - [durable task 文件](#durable-task-文件)
      - [lock 文件](#lock-文件)
    - [5.8 测试计划（F-22 🔄）](#58-测试计划f-22-)
    - [5.9 手工验收流程（F-22 🔄）](#59-手工验收流程f-22-)
    - [5.10 实施顺序与完成标准（F-22 🔄）](#510-实施顺序与完成标准f-22-)
    - [5.11 CCB 对比发现的补充缺口（F-22 🔄）](#511-ccb-对比发现的补充缺口f-22-)
      - [5.11.1 Feature Gate 系统——isKilled 运行时 kill 开关（F-22-G1 ✅）](#5111-feature-gate-系统iskilled-运行时-kill-开关f-22-g1-)
      - [5.11.2 远程 Jitter 实时配置（F-22-G2 ✅）](#5112-远程-jitter-实时配置f-22-g2-)
      - [5.11.3 One-shot 反向 Jitter（整点提前）（F-22-G3 ✅）](#5113-one-shot-反向-jitter整点提前f-22-g3-)
      - [5.11.4 Permanent 免过期任务机制（F-22-G4 ✅）](#5114-permanent-免过期任务机制f-22-g4-)
      - [5.11.5 锁注册式清理与 PID 存活探测增强（F-22-G5 ✅）](#5115-锁注册式清理与-pid-存活探测增强f-22-g5-)
      - [5.11.6 工具 Prompt 指引文档增强（F-22-G6 ✅）](#5116-工具-prompt-指引文档增强f-22-g6-)
      - [5.11.7 Analytics 遥测事件注入（F-22-G7 ✅）](#5117-analytics-遥测事件注入f-22-g7-)
      - [5.11.8 inFlight 防重复触发机制（F-22-G8 ✅）](#5118-inflight-防重复触发机制f-22-g8-)
      - [5.11.9 ClawCodex 已有但 CCB 缺失的优势特性（F-22-A1 ~ A6 ✅）](#5119-clawcodex-已有但-ccb-缺失的优势特性f-22-a1--a6-)
      - [5.11.10 补充缺口实施优先级矩阵（F-22 🔄）](#51110-补充缺口实施优先级矩阵f-22-)
      - [5.11.11 分析缺口与已有 F22-R/G 交叉映射（F-22 🔄）](#51111-分析缺口与已有-f22-rg-交叉映射f-22-)
        - [lastFiredAt 跨进程重启风险（Phase C 增强说明）](#lastfiredat-跨进程重启风险phase-c-增强说明)
        - [SDK daemon 模式（dir / lockIdentity 独立运行）（F-22-G9 📋）](#sdk-daemon-模式dir--lockidentity-独立运行f-22-g9-)
        - [cronToHuman(utc) UTC 模式显示（F-22-G10 📋）](#crontohumanutc-utc-模式显示f-22-g10-)
      - [5.11.12 Cron 任务累计防护——CCB 4 层设计对照审查（F-22-D1~D4 📋）](#51112-cron-任务累计防护ccb-4-层设计对照审查f-22-d1d4-)
        - [第 1 层 — sourceId 级 Dedup（核心防护）](#第-1-层--sourceid-级-dedup核心防护)
        - [第 2 层 — 进程所有者活体检测（防死锁）](#第-2-层--进程所有者活体检测防死锁)
        - [第 3 层 — 调度器 inFlight 防重触](#第-3-层--调度器-inflight-防重触)
        - [第 4 层 — 调度锁（跨进程互斥）](#第-4-层--调度锁跨进程互斥)
        - [附加保护措施对照](#附加保护措施对照)
        - [总结](#总结)
  - [六、会话恢复增强（F-49 / F-103 ✅）](#六会话恢复增强f-49--f-103-)
    - [6.1 问题现状（F-49 / F-103 ✅）](#61-问题现状f-49--f-103-)
    - [6.2 CCB 对比发现的补充缺口（F-49 / F-103 ✅）](#62-ccb-对比发现的补充缺口f-49--f-103-)
      - [6.2.1 缺口 1：退出时打印 Resume Hint（S-R1 📋）（F-49 / F-103）](#621-缺口-1退出时打印-resume-hints-r1-f-49--f-103)
      - [6.2.2 缺口 2：Resume 后历史消息渲染不完整（S-R2 📋）（F-49 / F-103）](#622-缺口-2resume-后历史消息渲染不完整s-r2-f-49--f-103)
      - [6.2.3 缺口 3：`--continue` CLI 快捷命令（S-R3 📋）（F-49 / F-103）](#623-缺口-3--continue-cli-快捷命令s-r3-f-49--f-103)
      - [6.2.5 缺口 5：REPL 端会话浏览器（S-R5 📋）（F-49 / F-103）](#625-缺口-5repl-端会话浏览器s-r5-f-49--f-103)
      - [6.2.6 缺口 6：`--fork-session` 支持（S-R6 📋）（F-49 / F-103）](#626-缺口-6--fork-session-支持s-r6-f-49--f-103)
      - [6.2.7 缺口 7：Session 标签与按标签恢复（S-R7 📋）（F-49 / F-103）](#627-缺口-7session-标签与按标签恢复s-r7-f-49--f-103)
      - [6.2.4 缺口 4：Resume 时元数据与状态恢复不完整（S-R4 📋）（F-49 / F-103）](#624-缺口-4resume-时元数据与状态恢复不完整s-r4-f-49--f-103)
    - [6.3 补充缺口实施优先级矩阵（F-49 / F-103 ✅）](#63-补充缺口实施优先级矩阵f-49--f-103-)
  - [七、CCB 对标缺口（F-60~F-90 🔄）](#七ccb-对标缺口f-60f-90-)
    - [7.0 Python 生态特性规划（合并来源：原 §十）](#70-python-生态特性规划合并来源原-十)
    - [CCB 子系统覆盖状态总览](#ccb-子系统覆盖状态总览)
    - [7.1 进程间通信与远程控制（F-60 ✅）](#71-进程间通信与远程控制f-60-)
      - [F-60（✅ 已归档）](#f-60-已归档)
    - [7.2 浏览器与桌面操控（F-60 ✅）](#72-浏览器与桌面操控f-60-)
      - [F-61（✅ 已归档）](#f-61-已归档)
      - [F-62（✅ 已归档）](#f-62-已归档)
    - [7.3 通知与语音（F-60 ✅）](#73-通知与语音f-60-)
      - [F-63（✅ 已归档）](#f-63-已归档)
      - [Voice Mode 语音输入（F-64 ✅）](#voice-mode-语音输入f-64-)
      - [子特性分解](#子特性分解-3)
      - [核心数据模型](#核心数据模型)
      - [核心接口](#核心接口)
      - [本地 Whisper 实现示例](#本地-whisper-实现示例)
      - [Edge TTS 实现示例](#edge-tts-实现示例)
      - [集成到 Tool 工厂](#集成到-tool-工厂)
      - [依赖](#依赖-1)
    - [7.4 可观测性与协议（F-60 ✅）](#74-可观测性与协议f-60-)
      - [F-65（✅ 已归档）](#f-65-已归档)
      - [ACP 协议支持（F-66 📋）](#acp-协议支持f-66-)
      - [背景](#背景-3)
      - [子特性分解](#子特性分解-4)
      - [核心数据模型](#核心数据模型-1)
      - [核心接口](#核心接口-1)
      - [Stdio 传输实现示例](#stdio-传输实现示例)
      - [WebSocket 传输实现示例](#websocket-传输实现示例)
      - [ACP 服务端 WebSocket 入口](#acp-服务端-websocket-入口)
      - [集成到 Tool 工厂](#集成到-tool-工厂-1)
      - [依赖](#依赖-2)
    - [7.5 高级 Agent 模式（F-60 ✅）](#75-高级-agent-模式f-60-)
      - [F-67（✅ 已归档）](#f-67-已归档)
      - [Native 原生模块系统（Python 可实现部分）（F-81 🔭）](#native-原生模块系统python-可实现部分f-81-)
      - [背景](#背景-4)
      - [子特性分解](#子特性分解-5)
      - [架构设计](#架构设计)
      - [音频捕获模块](#音频捕获模块)
      - [图像差异对比模块](#图像差异对比模块)
      - [URL Handler 模块](#url-handler-模块)
      - [依赖](#依赖-3)
      - [Remote Control Server 远程控制服务（F-82 🔄）](#remote-control-server-远程控制服务f-82-)
      - [背景](#背景-5)
      - [子特性分解](#子特性分解-6)
      - [架构设计](#架构设计-1)
      - [核心数据模型](#核心数据模型-2)
      - [认证中间件](#认证中间件)
      - [Worker 调度与长轮询](#worker-调度与长轮询)
      - [FastAPI 应用工厂](#fastapi-应用工厂)
      - [依赖](#依赖-4)
      - [Hermes Gateway 参考实现（OpenAI 兼容 API 服务器）（F-90 ✅）](#hermes-gateway-参考实现openai-兼容-api-服务器f-90-)
        - [参考 API 端点](#参考-api-端点)
        - [可复用设计模式](#可复用设计模式)
        - [关键文件（参考路径）](#关键文件参考路径)
        - [F-82 选型建议](#f-82-选型建议)
        - [依赖与协同（v3 新增）](#依赖与协同v3-新增)
      - [F-83（✅ 已归档）](#f-83-已归档)
      - [F-84（✅ 已归档）](#f-84-已归档)
    - [7.6 模板系统（F-60 ✅）](#76-模板系统f-60-)
      - [F-85（✅ 已归档）](#f-85-已归档)
      - [F-86（✅ 已归档）](#f-86-已归档)
      - [Workflow Scripts 工作流脚本（F-87 ✅）](#workflow-scripts-工作流脚本f-87-)
      - [F-88（✅ 已归档）](#f-88-已归档)
    - [CCB 对标实施总览](#ccb-对标实施总览)
    - [实施建议顺序（已落地特性说明）](#实施建议顺序已落地特性说明)
    - [clawcodex 对比 CCB 的领先优势](#clawcodex-对比-ccb-的领先优势)
      - [优势 1: Orchestrator 自动 Issue→PR 流水线](#优势-1-orchestrator-自动-issuepr-流水线)
      - [优势 2: Verification Gate（F-38 📋）](#优势-2-verification-gatef-38-)
      - [优势 3: SOP 编译器](#优势-3-sop-编译器)
      - [优势 4: LiteLLM Provider（100+ 模型统一接口）](#优势-4-litellm-provider100-模型统一接口)
      - [优势 5: Manager/Worker 增强通信（TaskInspect/TaskDirectives）](#优势-5-managerworker-增强通信taskinspecttaskdirectives)
      - [Feature Gate 运行时特性开关系统（F-68 📋）](#feature-gate-运行时特性开关系统f-68-)
        - [背景](#背景-6)
        - [子特性分解](#子特性分解-7)
        - [架构建议](#架构建议)
        - [包结构](#包结构)
        - [FeatureFlag 类型定义](#featureflag-类型定义)
        - [FeatureRegistry 实现](#featureregistry-实现)
        - [@feature\_gated 装饰器实现](#feature_gated-装饰器实现)
        - [条件注册用法](#条件注册用法)
        - [集成点](#集成点)
        - [依赖](#依赖-5)
      - [Budget / Poor Mode 资源节俭模式（F-69 🔄）](#budget--poor-mode-资源节俭模式f-69-)
        - [背景](#背景-7)
        - [子特性分解](#子特性分解-8)
        - [行为矩阵设计](#行为矩阵设计)
        - [Agent 循环 Hook 点（具体集成位置）](#agent-循环-hook-点具体集成位置)
        - [配置模型集成](#配置模型集成)
        - [依赖](#依赖-6)
      - [Plugin 插件系统基础框架（F-70 📋）](#plugin-插件系统基础框架f-70-)
        - [背景](#背景-8)
        - [子特性分解](#子特性分解-9)
        - [BasePlugin 协议（精确接口）](#baseplugin-协议精确接口)
        - [Plugin 示例](#plugin-示例)
        - [架构](#架构-1)
        - [插件发现路径](#插件发现路径)
        - [依赖](#依赖-7)
      - [内置工具补齐（缺失工具批量实现）（F-71 📋）](#内置工具补齐缺失工具批量实现f-71-)
        - [背景](#背景-9)
        - [子特性分解](#子特性分解-10)
        - [实现模式（参考 `src/tool_system/build_tool.py`）](#实现模式参考-srctool_systembuild_toolpy)
        - [工具注册](#工具注册)
        - [依赖](#依赖-8)
      - [Multi-API 原生适配器扩展（F-72 📋）](#multi-api-原生适配器扩展f-72-)
        - [背景](#背景-10)
        - [子特性分解](#子特性分解-11)
        - [架构](#架构-2)
        - [NativeProvider 基类（继承现有关）](#nativeprovider-基类继承现有关)
        - [OpenAI 适配器示例](#openai-适配器示例)
        - [自动选择与工厂](#自动选择与工厂)
        - [依赖](#依赖-9)
      - [F-73（✅ 已归档）](#f-73-已归档)
      - [Sandbox / SSH Remote 沙箱远程执行（F-74 📋）](#sandbox--ssh-remote-沙箱远程执行f-74-)
        - [背景](#背景-11)
        - [子特性分解](#子特性分解-12)
        - [架构](#架构-3)
        - [SandboxExecutor 抽象接口](#sandboxexecutor-抽象接口)
        - [本地执行器示例](#本地执行器示例)
        - [Docker 执行器核心逻辑](#docker-执行器核心逻辑)
        - [BashTool 集成点](#bashtool-集成点)
        - [使用模式](#使用模式)
        - [依赖](#依赖-10)
    - [实施总览](#实施总览)
    - [实施建议顺序](#实施建议顺序-2)
  - [八、Multi-Session 可视化分析平台（F-91~F-96 ✅）](#八multi-session-可视化分析平台f-91f-96-)
  - [其余项目](#其余项目)
        - [缓存策略](#缓存策略)
      - [10.1.6 AR-5.1.2 候选特性抽取与分类（F-91 ✅）](#1016-ar-512-候选特性抽取与分类f-91-)
        - [Feature Record 数据模型](#feature-record-数据模型)
        - [抽取流水线](#抽取流水线)
      - [10.1.7 AR-5.1.3 评分与报告系统（F-91 ✅）](#1017-ar-513-评分与报告系统f-91-)
        - [评分模型](#评分模型)
        - [报告生成](#报告生成)
        - [Community Digest 模板示例](#community-digest-模板示例)
      - [10.1.8 AR-5.1.4 Cron 集成（F-91 ✅）](#1018-ar-514-cron-集成f-91-)
      - [10.1.9 三方集成组件（F-91 ✅）](#1019-三方集成组件f-91-)
      - [10.1.10 与 ClawCodex 现有能力的协同（F-91 ✅）](#10110-与-clawcodex-现有能力的协同f-91-)
      - [10.1.11 文件结构（F-91 ✅）](#10111-文件结构f-91-)
      - [10.1.12 实施阶段（F-91 ✅）](#10112-实施阶段f-91-)
      - [10.1.13 验收标准（F-91 ✅）](#10113-验收标准f-91-)
      - [10.1.14 风险与约束（F-91 ✅）](#10114-风险与约束f-91-)
      - [10.1.15 已拟定的设计决定（F-91 ✅）](#10115-已拟定的设计决定f-91-)
      - [10.1.16 依赖与协同（F-91 ✅）](#10116-依赖与协同f-91-)
  - [十一、Agent 执行性能优化（F-105 ✅ / F-106 ✅）](#十一agent-执行性能优化f-105---f-106-)
  - [附录：F-Number 快速索引](#附录f-number-快速索引)



## 项目概述与边界约束

### 项目定位

ClawCodex 是 Anthropic Claude Code 的 Python 移植版，同时扩展多 Provider 支持，目标成为功能完整的 AI Agent CLI 工具。

### 当前架构（三层解耦）

```
src/
├── upstream/            # Layer 1: 上游快照（git archive 提取的原始代码）
│   └── v2025_04/        #     具体版本标签镜像
├── capabilities/        # Layer 2: ClawCodex Protocol 接口定义
│   ├── agent_protocol.py
│   ├── tool_protocol.py
│   ├── context_protocol.py
│   ├── provider_protocol.py
│   ├── event_protocol.py          # ToolEvent 接口
│   ├── headless_protocol.py       # HeadlessOptions 接口
│   └── headless_runner.py          # 可插拔 headless 后端分发器
├── orchestrator/        # Layer 3: 自主模式编排（完全新增，无上游依赖）
├── api/                 # Layer 3: 公共 Python API（完全新增，无上游依赖）
└── ...                  # 其余为上游原有模块
```

**层约束（upstream-sync audit 强制）：**
- `src.upstream` → 只能被 `src.capabilities` 依赖
- `src.capabilities` → 不能导入 `src.upstream`
- `src.orchestrator` / `src.api` → 只能从 `src.capabilities` 导入，不能直接导入 `src.upstream`

---

> **约束层级**: 项目级（所有 downstream/custom 开发必须遵守）
> **约束目标**: 防止二开代码污染 `src/*` 上游形状兼容区，确保未来上游同步不产生大量本地补丁累积

### 核心约束

1. **默认路径**: 所有 downstream/custom 开发默认进入根级 `clawcodex_ext/*`；**不得**在 `src/*` 中直接添加项目专属逻辑。

2. **`src/*` 定位**: `src/*` 被视为上游形状/core 兼容区，除非文件被明确标注为项目自主拥有，否则只接受：
   - 从 `clawcodex_ext/*` 向上的 thin forwarding seams
   - 最小适配层（adapter/wrapper）
   - 上游同步带来的必要更新
   - 窄范围 bug fix

3. **明确接受 minimal patch 的文件**（仅限这些文件可接受 thin forwarding/adapter 改动）：
   - `src/cli.py`
   - `src/entrypoints/tui.py`
   - `src/repl/*`
   - `src/tui/*`
   - `src/runtime/*`（未来）

4. **`src/upstream/<rev>/*`**: 仅作为上游快照同步区，**不得**在此路径下添加任何 downstream 代码。

5. **二开功能目标路径**（示例）:
   - `clawcodex_ext/cli` — CLI parser/dispatch 下游实现
   - `clawcodex_ext/tui` — TUI 下游定制
   - `clawcodex_ext/frontend` — Frontend 协议/注册表
   - `clawcodex_ext/runtime` — Runtime context factory
   - `clawcodex_ext/skills` — 下游技能/hook 扩展

6. **新功能实现流程**: 新 downstream 特性、frontend 行为、runtime 接线、命令、UI 定制、provider/tool 编排变更应首先在 `clawcodex_ext/*` 实现；对 `src/*` 的改动仅限于 thin forwarding seams。

### 约束起源

此约束将 F-34/F-35 的 CLI/TUI 前端解耦边界推广至全项目级别。最初来源于 `CONTRIBUTING.md` 中的 CLI/TUI 二开边界规则，已不能满足多层次解耦架构（upstream-sync layer + capabilities layer + orchestrator/api layer + downstream extension layer）的需求。本约束确保 downstream 扩展开发默认在 `clawcodex_ext/*` 进行，而不是直接修改上游形状文件，从而在未来的上游快照同步中避免大量本地补丁累积。

F-34/F-35 中"CLI/TUI 新功能"的描述扩展为全项目范围：所有 frontend 行为、runtime 接线、命令、UI 定制、provider/tool 编排均受此约束约束。

---

---

## 已归档功能模块

> **已实现功能已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)**
>
> 以下列出的所有功能模块已在归档文档中详细记录（v2.5 范围）：
> - §一 核心 Agent 系统
> - §二 三层解耦架构（Layer Isolation）
> - §三 Provider 层（含 §3.3 LiteLLM Provider 替换，R-7）
> - §四 工具系统
> - §五 开源替代组件（R-1~R-6）
> - §六 后台运行 + 恢复同步
> - §七 Bridge Phase 8-11 多 Session Daemon 桥接器
> - §八 Agent Loop Consolidation (Stage 4)
> - §九 Advisor Token 计数与状态显示
> - §十 REPL 与 TUI 增强
> - §十一 TUI 响应性修复
> - §十二~十五 TaskInspect/TaskDirectives、ProgressReportTool、TUI 权限模式选择器、会话恢复浏览器
> - §十六 Orchestrator 自主模式（含 §16.4 生产强化 F-1.1~1.4、§16.5 三通道澄清 F-1.5~1.11、§16.6 CLI 运维界面 F-1.13）
> - §十七 MCP 协议扩展
> - §十八 Agent 间自主观察与消息交互
> - §十九 SOP 转化模式
> - §二十 Skills System Extension（F-23）

---


## 一、Orchestrator 系统


### Orchestrator 系统概述
**状态**: ✅ 已完成（Symphony 集成）
**目标**: 支持 `clawcodex --workflow WORKFLOW.md` 自主运行模式

> 核心组件、生产强化（F-1.1~F-1.4）、Issue 语义澄清三通道（F-1.5~F-1.11）、Orchestrator CLI 运维界面（F-1.13）等子特性全部已归档。
> 详细架构、组件清单、配置形态与命令清单见 [ARCHIVED_FEATURES.md §16](./ARCHIVED_FEATURES.md#十六orchestrator-自主模式symphony-集成)。
>
> 仍处规划/设计阶段、保留详细设计稿的子节如下：
> - §1.1.2 PR 检视意见自动修复闭环设计（F-37，📋 规划中）
> - §1.3.2 运行期可观测性与 stuck-run debug（F-54，🔄 进行中 — debug_log.py / tool_event_log.py / ObservabilityConfig schema 已落地，query-runner heartbeat 与 CLI 诊断字段待补）
>
> 已完成但仍保留设计稿的子节：
> - §1.2.2 ProgressReporter Sink 协议重构设计（F-40，✅ 已完成 — `ProgressSink`/`CompositeProgressSink`/`ToolContextProgressSink` 已在 `progress_sink.py` 落地，`progress_reporter.py` 降级为兼容 shim）
> - 已完成的 LocalTracker（F-36）、验证与报告闭环（F-38）、Issue 重跑入口（F-39）、Coordinator 轻量工具集（F-41）、Shared / Sequential Workspace（F-42）、Tool-call 审计旁路（F-45）、人工检视闸门（F-44）与 AgentRunner 空转检测（F-51）详见 [ARCHIVED_FEATURES.md §二十一](./ARCHIVED_FEATURES.md#二十一2026-06-02-已实现功能归档)。

### 1.1.1 LocalTracker 本地 Issue 文档源设计（F-36 ✅）
**状态**: ✅ 已完成

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.1](./ARCHIVED_FEATURES.md#二十一1-f-36-localtracker-本地-issue-文档源)。

### 1.1.2 PR 检视意见自动修复闭环（F-37 ✅）
**状态**: ✅ 已完成（核心链路已验证）
**优先级**: P0
**目标**: 将"基于 PR 网页检视意见自动修改并更新 PR"的能力产品化到 `extensions/orchestrator`，形成 issue → implementation PR → review feedback → follow-up fix → push update 的自动闭环。

> 完整实现（PullRequestFeedback / ReviewFeedbackConfig / ReviewFeedbackService / Orchestrator review follow-up 轮询 / GitSync follow-up 模式）已在 `extensions/orchestrator/` 落地。详细落地记录见 [ARCHIVED_FEATURES.md §二十一.9 F-37 PR 检视意见自动修复闭环](./ARCHIVED_FEATURES.md#二十一9-f-37-pr-检视意见自动修复闭环)。
### 1.1.3 验证与报告闭环（F-38 ✅）
**状态**: ✅ 已完成

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.2](./ARCHIVED_FEATURES.md#二十一2-f-38-orchestrator-验证与报告闭环)。

### 1.1.4 Issue 重跑入口（F-39 ✅）
**状态**: ✅ 已完成（Sub-A~F）

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.3](./ARCHIVED_FEATURES.md#二十一3-f-39-orchestrator-issue-重跑入口)。

### 1.2.1 Shared/Sequential Workspace（F-42 ✅）
**状态**: ✅ 已完成

> `workspace.strategy: isolated | shared | sequential` 落地。详见 [ARCHIVED_FEATURES.md §二十一.5](./ARCHIVED_FEATURES.md#二十一5-f-42-sharedsequential-workspace-策略)。

### 1.2.2 ProgressReporter Sink 重构（F-40 ✅）
**状态**: ✅ 已完成（代码已全部落地）

> Protocol 设计、架构对比、关键组件（ProgressSink / CompositeProgressSink / ToolContextProgressSink / ProgressReporter shim）、改造点、进度计算、验收标准、风险与实施阶段的完整设计文档已归档至 [ARCHIVED_FEATURES.md §二十一.7 F-40 ProgressReporter Sink 重构](./ARCHIVED_FEATURES.md#二十一7-f-40-progressreporter-sink-重构)。

---

### 1.3.1 AgentRunner 空转检测机制（F-51 ✅）
**状态**: ✅ 已完成

> 内置空转检测逻辑。详见 [ARCHIVED_FEATURES.md §二十一.8](./ARCHIVED_FEATURES.md#二十一8-f-51-agentrunner-空转检测)。

### 1.3.2 运行期可观测性与 stuck-run debug（F-54 🔄）

```
场景：headless agent 在 issue 开发中途陷入迷茫 / operator 想人工介入

1. 触发条件（任一）:
   a) orchestrator 检测到 agent 连续多轮无进展（F-51 空转检测）
   b) operator 通过 dashboard 看到 agent stuck
   c) operator 通过 F-49 Phase 1 的 socket 手动触发 pause

2. Operator 执行:
   $ clawcodex --resume <run_id>

3. 内部流程:
   a) Session.resume(run_id)
      → 读取 ~/.clawcodex/sessions/{run_id}/metadata.json
        (model="claude-sonnet-4-20250514", provider="anthropic", cwd="/workspace")
      → 读取 ~/.clawcodex/sessions/{run_id}/transcript.jsonl
      → 重建完整的 Conversation（UserMessage / AssistantMessage 交替列表）
      → 恢复到前台 REPL，LLM context 与 agent 中断时一致

   b) REPL 启动后显示:
      "Resumed session <run_id> from orchestrator run (issue: F-42-shared-workspace)"
      "Agent was at turn 5/20, last tool: Read(src/config/schema.py)"
      ┌─────────────────────────────────────────────┐
      │ 历史消息回放（最近 3 轮）                       │
      │ ... agent 的思考过程和工具调用结果全部可见 ...    │
      └─────────────────────────────────────────────┘


   c) operator 输入:
      > 这个 Read 结果不对，你应该看 src/config/__init__.py 的默认值

      → 这条输入作为新的 UserMessage 写入 transcript.jsonl
      → LLM 继续响应，新输出追加到 transcript
      → operator 可以多轮交互，完全接管 agent 的下一步

   d) 退出 REPL 时:
      - 选择 "detach"（保持 session 打开，headless 可继续）
      - 或 "agent_finished"（标记 run 完成）
      - 或 "re-orchestrate"（退出后自动启动新的 headless run 从当前状态继续）
```

**恢复后的对话完整性保证**：

```
Session.resume() 恢复的 transcript 内容:
┌─ turn 0 ──────────────────────────────────┐
│ UserMessage:    初始 prompt                │
│ AssistantMessage: 思考 + tool_use Read     │
│ UserMessage:    tool_result (文件内容)      │
├─ turn 1 ──────────────────────────────────┤
│ AssistantMessage: 思考 + tool_use Edit     │
│ UserMessage:    tool_result (编辑结果)      │
├─ ...                                      │
├─ turn N ──────────────────────────────────┤
│ AssistantMessage: 思考（stuck 时的最后输出） │
│ UserMessage:    (空 — operator 即将介入)    │
├─ operator 介入 ───────────────────────────┤
│ UserMessage:    "这个 Read 结果不对..."    │ ← 新写入
│ AssistantMessage: 新的 LLM 响应             │ ← 新写入
└───────────────────────────────────────────┘
```

**`--resume` 与正在运行的 headless agent 的并发安全**：

| 场景 | 行为 | 原理 |
|------|------|------|
| agent 已结束 | ✅ 正常恢复，进入交互 REPL | session 无其他人持有 |
| agent 正在运行中 | ✅ 恢复后获得"截至当前的历史快照"，不可写入（readonly），agent 继续运行不受影响 | `transcript.jsonl` 的文件锁 + `SessionStorage` 的 append-only 语义 |
| agent 正在运行 + operator 想接管 | socket 发送 `pause` → agent 挂起 → `--resume` 进入可写 REPL | 依赖 F-49 Phase 1 的 socket 控制通道 |
| 两个 operator 同时 `--resume` | 各自获得独立的历史快照，最后写入者胜 | 同 `SessionStorage` 的常规并发行为 |

**Phase 0.3 — 大内容文件引用**

`SessionStorage._replace_large_content()` 会将大 tool result 自动替换为 `{"type": "ref", "ref_id": "<uuid>"}`，实际内容存入 `~/.clawcodex/sessions/<run_id>/content/<uuid>`。这是 SessionStorage 内置行为，AgentRunner 无需感知。

但需要考虑：

- **workspace 相对路径**：如果 tool result 包含长文件内容（如 `Read` 工具读取了大型文件），文件引用路径不应硬编码为 `~/.clawcodex/` 绝对路径，否则跨机器恢复时路径失效。`metadata.json` 中的 `cwd` 字段用于辅助恢复时进行路径解析。
- **清理策略**：orchestrator 的 cleanup 策略（`retention_days`）与普通 session 一致，F-11（sessionStorage 容量限制）已覆盖此场景。

**当前文件结构（F-49 统一后）**：

```
# 主转录（Message 级别，可 resume）
~/.clawcodex/sessions/{run_id}.json        ← Session 快照（含 cost 计数）
~/.clawcodex/sessions/{run_id}/
  ├── metadata.json                         ← 元数据
  ├── transcript.jsonl                      ← Message 对话转录（每行一个 Message dict）
  └── content/                              ← 大内容文件引用

# 辅助日志（非 Message 级别，不可用于 resume）
~/.clawcodex/tool-events/{run_id}/events.ndjson
  └── 每行 8 字段：ts / tool / params / approved / deny_reason / permission_mode / turn / session_run_id
      （F-45 审计旁路，50MB rotate）

{workspace}/.orchestrator_control/runs/{run_id}/debug.ndjson
  └── 每行 {ts, stage, ...fields}
      （F-49 debug 日志，best-effort 写入）
```

注意：旧的 `{workspace}/.event_logs/{issue_id}.ndjson` 格式已于 F-49 Phase 0 中完全移除，不再存在。

注意：`~/.clawcodex/sessions/{run_id}.json`（Session 快照）不是必选项 —— 它由 `Session.save()` 产生，包含 `conversation`、`cost`、`provider`、`model` 等完整元数据。orchestrator 若只写 `transcript.jsonl`，则 `session_resume.resume_session()` 也可工作（它会从 transcript 重建 message 列表 + 从 metadata 恢复 model/provider）。`Session.save()` 额外提供 `cost` 快照用于 resume 时恢复 token/费用计数，建议保留。

**改造后的事件流数据流向图**：

```
AgentRunner.run()
  │
  ├── run() 开始
  │     ├── SessionStorage(session_id=run_id)
  │     ├── .init_metadata(model, cwd, title)
  │     └── .write_raw(user_prompt_msg_dict)
  │
  ├── 循环 per turn:
  │     ├── 累积 TextDelta → text_buf list
  │     ├── 累积 ToolCallEvent → tool_use_buf list
  │     ├── 累积 ToolResultEvent → tool_result_buf dict[tool_use_id]
  │     │
  │     ├── TurnComplete:
  │     │     ├── 组装 AssistantMessage(text_buf + tool_use_buf)
  │     │     ├── .write_raw(assistant_msg_dict)
  │     │     ├── 组装 UserMessage(tool_result_buf.values())
  │     │     ├── .write_raw(user_msg_dict)
  │     │     ├── 清空 text_buf, tool_use_buf, tool_result_buf
  │     │     └── 若还有下一 turn → .write_raw(continuation_msg_dict)
  │     │
  │     └── F-45 逻辑独立并行：
  │           └── _append_tool_event_log(event)  ← 只写 events.ndjson，不干扰 Message 流
  │
  ├── SessionComplete:
  │     └── .flush()
  │
  └── 异常退出（agent crash / timeout / KeyboardInterrupt）:
        └── .flush()  ← 确保已累积但未 flush 的消息不丢失
```

**Phase 1 — Unix Socket 控制通道**（2-3天）

| 新增文件 | 说明 |
|----------|------|
| `extensions/orchestrator/control_socket.py` | `ControlSocket` 类：在 `{workspace}/.run_control/{issue_id}.sock` 监听 Unix domain socket；暴露 `poll_commands() → AsyncIterator[ControlCommand]` 和 `send_events()` |
|  | `ControlCommand` dataclass：`cmd: Literal["pause", "resume", "inject", "stop", "detach", "takeover"]` + `payload: str` |
|  | `EventFrame` dataclass：事件序列化帧 `{type, data, ts}` 供 socket 客户端流式接收 |

关键接口：

```python
# control_socket.py
@dataclass
class ControlCommand:
    cmd: Literal["pause", "resume", "inject", "stop", "detach", "takeover"]
    payload: str = ""  # resume 时附带 prompt，inject 时附带 hint

class ControlSocket:
    """Bidirectional control via Unix domain socket."""

---

#### 1.3.3 Tool-call 审计旁路设计（F-45 ✅）
**状态**: ✅ 已完成

> 为工具调用增加审计日志旁路。详见 [ARCHIVED_FEATURES.md §二十一.6](./ARCHIVED_FEATURES.md#二十一6-f-45-tool-call-审计旁路)。

#### 1.3.4 Coordinator 轻量工具集（F-41 ✅）
**状态**: ✅ 已完成

> Coordinator 配置独立轻量工具集（Read、WebSearch、WebFetch）。详见 [ARCHIVED_FEATURES.md §二十一.4](./ARCHIVED_FEATURES.md#二十一4-f-41-coordinator-轻量工具集)。

#### 1.4.2 Issue 会话统一存储与实时介入协议（F-49 ✅）

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

#### 1.4.3 全场景会话恢复统一闭包（F-49 Phase 0.4 ✅ — Session Resume 统一）

**状态**: ✅ 已完成
**优先级**: P1
**依赖**: F-49 Phase 0 ~ 0.3（统一事件存储），F-21（后台运行 + 恢复同步）

##### 问题现状：SessionStorage 回退路径的消息缺失

F-49 Phase 0 统一了事件存储格式（全部使用 `~/.clawcodex/sessions/{run_id}/transcript.jsonl`），但在 `--resume` 恢复链上仍然存在一个关键缺口：

```
Session.resume(sid)                          # src/agent/session.py:135
  → Session.load(sid)                        # 尝试 ~/.clawcodex/sessions/{sid}.json
    ├── 找到 → 返回完整 Session（含 Conversation.messages）✅
    └── 未找到 → load_from_session_storage()  # 回退到 SessionStorage 目录格式
         → 仅恢复 metadata（session_id, model, start/end time）
         → conversation=Conversation()        # ← 空的！
```

| 消费方 | resume 后的处理 | 行为 |
|--------|---------------|------|
| **REPL** `repl/app.py:136` | `_sync_conversation_from_transcript()` 从 JSONL 重新填充 | ✅ 全量恢复 |
| **TUI** `tui/app.py:229` | 仅 `if self.session.conversation.messages: self._replay_history()` | ❌ 格式 B 恢复后消息为空，不会 replay 历史 |
| **CLI** `dispatch.py` | 无显式 transcript 同步 | ❌ 格式 B 恢复后 conversation 空 |
| **Cron bg_runner** | 仅写 JSONL，不写 .json 快照 | ⚠️ 只能走 SessionStorage 回退 |
| **Orchestrator** | 仅写 JSONL，不写 .json 快照 | ⚠️ 只能走 SessionStorage 回退 |

核心矛盾：**CLI/TUI 的 `--resume` 对于 Cron/Orchestrator 写入的会话只能恢复出一个空壳**，必须依赖每个消费者自行补丁。

##### 目标

彻底消除上述差距，使所有场景的 `--resume` 行为一致且可递归恢复：

```
所有写入方（CLI / REPL / TUI / Cron / Orchestrator）
       │ 统一写 SessionStorage JSONL
       ▼
~/.clawcodex/sessions/<sid>/transcript.jsonl
       │
       ▼ --resume 统一消费
Session.resume(sid) → 返回的 Session.conversation.messages 非空
       │
       ▼ 递归 resume
再次 Session.resume(sid) → 与退出前状态一致
```

##### 设计

**A. `Session.resume()` 自愈修复（核心，一处修复全局生效）**

在 `Session.resume()` 的 SessionStorage 回退路径末尾，增加从 JSONL 加载消息的逻辑：

```python
# load_from_session_storage 之后，conversation 为空时：
if not loaded.conversation.messages:
    try:
        from src.services.session_storage import SessionStorage
        storage = SessionStorage(session_id=session_id)
        entries = storage.read_transcript()
        from src.types.messages import message_from_dict
        messages = [message_from_dict(e) for e in entries]
        loaded.conversation.messages = messages
    except Exception:
        pass  # 不阻断 resume
```

效果：**一处修复，CLI/REPL/TUI/Cron/Orchestrator 全场景受益**。REPL 的 `_sync_conversation_from_transcript()` 将成为冗余（但保留作为防御性 double-check）。

**B. `Session.save()` 双写一致性保障**

当前 `Session.save()` 同时写 `.json` 快照 + JSONL。但对于从 SessionStorage 回退路径恢复的会话（conversation 通过 A 补全后），首次 `save()` 把 `.json` 快照写出来，后续 `--resume` 就走快路径 `Session.load()` 了。

**C. 新增：Cron `background_runner.py` 运行结束写 `.json` 快照**

```python
# 在 _run_agent_headless() 末尾，调用 session.save() 写 .json 快照
session.save()  # 让 agent 结束后也能通过快路径 --resume
```

**D. 新增：Orchestrator `agent_runner.py` 运行结束写 `.json` 快照**

```python
# 在 AgentRunner.run() 末尾，调用 session.save() 写 .json 快照
session.save()
```

##### 改造点清单

**Phase 0.4.1 — 核心修复：`Session.resume()` 加载 JSONL 消息**（0.5 天）

| 文件 | 改动 |
|------|------|
| `src/agent/session.py` | `Session.resume()` 的 SessionStorage 回退分支末尾，增加从 `SessionStorage.read_transcript()` 加载 messages 到 `conversation.messages` 的逻辑 |
| `(无)` | 不修改 `load_from_session_storage()` / `session_persist.py` — 保持原有契约 |

验收：`Session.resume(run_id)` for orchestrator-run 返回的 `session.conversation.messages` 非空。

**Phase 0.4.2 — 统一 clean-up：移除冗余的 caller 侧 transcript 同步**（0.5 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/repl/core.py` | 保留 `_sync_conversation_from_transcript()` 作为防御性 double-check；在方法开头检查若 `session.conversation.messages` 已非空则直接 return |
| `clawcodex_ext/repl/app.py` | 无改动（仍保留 `_sync_conversation_from_transcript` 调用） |

验收：REPL resume 后 conversation 正常，`_sync_conversation` 成为 quick-return no-op。

**Phase 0.4.3 — TUI resume 路径修复**（0.5 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/tui/entrypoint.py` | `Session.resume()` 调用后，增加 `resume_session_with_tail()` 调用中的 transcript 消息加载（或依赖 Phase 0.4.1 核心修复已生效） |
| `clawcodex_ext/tui/app.py` | `on_mount()` 中的 `if self.session.conversation.messages:` 改为无条件调用 `_replay_history()`（若 messages 为空则不渲染）或由核心修复保证非空 |

验收：`clawcodex --tui --resume <run_id>` 显示 orchestrator run 的完整历史。

**Phase 0.4.4 — CLI dispatch resume 路径修复**（0.5 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/cli/dispatch.py` | `Session.resume()` 调用后，确保 `conversation.messages` 非空（若 Phase 0.4.1 已修复则自动生效） |

验收：`clawcodex --resume <run_id>` 进入 REPL 后显示历史消息。

**Phase 0.4.5 — Cron/Orchestrator 运行结束写 .json 快照**（1 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/agent/background_runner.py` | `_run_agent_headless()` 末尾（finally 块中）调用 `session.save()` 确保 `.json` 快照写入 |
| `extensions/orchestrator/agent_runner.py` | `run()` 末尾（SessionComplete / 异常退出时）调用 `session.save()` 确保 `.json` 快照写入 |

验收：Cron/Orchestrator 执行后，`~/.clawcodex/sessions/<run_id>.json` 存在，可通过快路径 `Session.load()` 恢复。

**Phase 0.4.6 — 递归 resume 一致性验收**（0.5 天）

| 文件 | 改动 |
|------|------|
| `tests/test_session_resume_unified.py` | 新增测试：orchestrator 场景的 JSONL → `Session.resume()` → `Session.save()` → 再次 `Session.resume()` → 消息与第一次一致 |

验收：三轮递归 resume 消息内容不变。

##### 消息流向全图

```
                    ┌─────────────────────────┐
                    │  CLI / REPL / TUI 交互    │
                    │  Session.save()           │
                    │    → .json (快照)         │
                    │    → JSONL (追加)         │
                    └──────────┬──────────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Cron bg_runner       │
                    │  storage.write_msg()  │
                    │    → JSONL (追加)     │
                    │  结束 → session.save()│
                    │    → .json (快照)     │
                    └──────────┬──────────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Orchestrator        │
                    │  _flush_transcript() │
                    │    → JSONL (追加)    │
                    │  结束 → session.save()│
                    │    → .json (快照)    │
                    └──────────┴──────────────┘
                                        │
                                        ▼
~/.clawcodex/sessions/<sid>/
  ├── <sid>.json            # 全量快照（所有写入方最终都会产生）
  └── <sid>/
        ├── transcript.jsonl  # 追加日志（统一格式）
        └── metadata.json

                                        │
                                        ▼
                              Session.resume(<sid>)
                                ├── Session.load() → .json 快照 ✅
                                └── fallback → JSONL 加载消息 ✅ (Phase 0.4.1)
```

##### 验收标准

| # | 验收场景 | 预期行为 |
|---|---------|---------|
| 1 | CLI 交互 → exit → --resume | 完整 Conversation，消息不变 |
| 2 | REPL 交互 → exit → --resume | 完整 Conversation，消息不变 |
| 3 | TUI 交互 → exit → --resume (TUI 或 REPL) | 完整 Conversation，历史可见 |
| 4 | Cron bg_runner 运行 → --resume | 完整 Conversation，含所有 tool_use / tool_result |
| 5 | Orchestrator agent_runner 运行 → --resume | 完整 Conversation，含所有 tool_use / tool_result |
| 6 | Cron/Orch → --resume → exit → 再次 --resume | 递归一致 |
| 7 | 跨场景混合写入（eg: Orchestrator 写 → --resume REPL 追加 → exit → --resume TUI） | 所有消息（原始 + 追加）完整 |
| 8 | `.json` 快照不存在时，`--resume` 也能恢复 | 依赖 SessionStorage JSONL fallback |

##### 风险与约束

| 风险 | 缓解措施 |
|------|---------|
| `Session.resume()` 的 SessionStorage fallback 路径加载 JSONL 后，`conversation.messages` 可能包含大量消息，超出 `max_history`（默认 2000） | 加载后不截断 — `max_history` 仅在新 `add_message()` 时生效；或与 `Conversation.from_dict()` 保持行为一致 |
| JSONL 中的 malformed 行导致部分消息缺失 | 与 `session_resume.resume_session()` 行为一致：跳过 malformed 行并记录 warning |
| `_sync_conversation_from_transcript()` 在 REPL 中变为冗余但仍被调用 | 加 early-return 检查：`if self.session.conversation.messages: return`，O(1) 开销 |
| `session.save()` 从 Cron/Orchestrator 调用时可能缺失 provider / model 信息 | 在 `AgentRunner.run()` 中 `session.provider` 和 `session.model` 已设置；`load_from_session_storage` 返回的 model 字段也可用 |

##### 已拟定的设计决定

1. **核心修复在 `Session.resume()` 完成**（一处修复，全局受益），而非在每个消费者处加补丁。
2. **`.json` 快照在 Cron/Orchestrator 结束时写入**，保证下次 resume 走快路径，同时也作为备份。
3. **保留 REPL 的 `_sync_conversation_from_transcript()`**，改为防御性 double-check（early return 模式），不破坏现有行为。
4. **不修改 `SessionStorage`** — 所有改动在消费侧（`Session.resume()`、`background_runner.py`、`agent_runner.py`）。
5. **POS Converter 不涉及** — 它是编译期代码生成工具，不产生运行时会话日志。

##### 依赖与协同

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-49 Phase 0 ~ 0.3 | 硬依赖 | 格式统一是基础 |
| F-21 bg + `--resume` | 行为参考 | Ctrl+B / TailFollower 的用户体验作为 resume 设计基线 |
| F-40 ProgressSink | 无依赖 | Phase 0.4 不涉及事件分发变更 |
| F-48 解耦约束 | 架构约束 | 改动尽量少入侵 `src/`；`Session.resume()` 是上游文件，接受微小修改 |
| `src/services/session_storage.py` | 硬依赖 | 复用现有 `read_transcript()` 和 `message_from_dict()` |

---

### 1.4.4 会话格式分层参考图（全场景一览）（F-49 ✅）

```
Message 类型体系 (src/types/messages.py)
┌───────────────────────────────────────────┐
│  Message (role, content, uuid, timestamp) │
│  ├── UserMessage                          │
│  ├── AssistantMessage                     │
│  ├── SystemMessage                        │
│  └── ProgressMessage                      │
│                                           │
│  message_to_dict() / message_from_dict()  │
│  ← 标准序列化契约                         │
└───────────────────┬───────────────────────┘
                    │
════════════════════╪═══════════════════════════
         运行时内存   │  持久化层
                    │
                    ▼
┌───────────────────────────────────────────┐
│  SessionStorage (src/services/             │
│    session_storage.py)                     │
│                                           │
│  ~/.clawcodex/sessions/<sid>/             │
│    ├── transcript.jsonl   ← JSONL 格式    │
│    ├── metadata.json      ← SessionMetadata│
│    └── content/           ← 大内容引用     │
│                                           │
│  write_message(Message) → message_to_dict │
│    → f.write(json.dumps(msg_dict) + '\n') │
│  read_transcript() → f.readlines()        │
│    → message_from_dict(entry) → Message[] │
└───────────────────┬───────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    │               │               │
    ▼               ▼               ▼
┌─────────┐  ┌──────────┐  ┌──────────────┐
│ Session  │  │ .json    │  │ SessionStorage│
│ .save()  │  │ 快照文件  │  │ JSONL 追加   │
│ (双写)   │  │(快路径)   │  │(慢路径/增量) │
└─────┬───┘  └────┬─────┘  └──────┬───────┘
      │           │               │
      └───────────┼───────────────┘
                  │
                  ▼
         Session.resume(sid)
           ├── Session.load()
           │    (找到 .json → 快 ⚡)
           └── load_from_session_storage()
                + JSONL 消息加载 (Phase 0.4.1)
                (未找到 .json → 但 JSONL 可用)
                  → conversation.messages 非空 ✅
```

##### 全场景 resume 能力矩阵（Phase 0.4 完成后）

| 写入方 | 写入形式 | resume 快路径 | resume 慢路径 | 递归 resume |
|--------|---------|:------------:|:------------:|:----------:|
| CLI 交互 | `.json` + JSONL | ✅ | ✅ | ✅ |
| REPL 交互 | `.json` + JSONL | ✅ | ✅ | ✅ |
| TUI 交互 | `.json` + JSONL | ✅ | ✅ | ✅ |
| Cron bg_runner | JSONL + 结束写 `.json` | ✅ (事后) | ✅ (运行中) | ✅ |
| Orchestrator | JSONL + 结束写 `.json` | ✅ (事后) | ✅ (运行中) | ✅ |
| POS Converter | 不适用 | N/A | N/A | N/A |


---
### 1.4.5 session.json + transcript.jsonl 合并（F-49-P5 ✅）

**状态**: ✅ 已完成
**优先级**: P1
**工作量**: 2-3天
**依赖**: F-49 Phase 0 ~ 0.4（统一事件存储 + 全场景会话恢复）
**特性标识**: F-49-P5

##### 问题现状：三文件的冗余与不一致风险

当前每个会话目录 `~/.clawcodex/sessions/<sid>/` 包含 **3 个持久化文件**：

| 文件 | 生产者 | 写策略 | 内容 |
|------|--------|--------|------|
| `session.json` | `Session.save()` | 覆写（会话退出时） | provider + 全量消息 + cost 块 |
| `metadata.json` | `SessionStorage` | 覆写（每次变更） | model, cwd, title, tags, cost 等 |
| `transcript.jsonl` | `SessionStorage.flush()` / `TranscriptWriter` | 追加写 | 逐行 Message dict + cost_block 事件 |

核心问题：

```
1. 消息双重存储：session.json 存全量消息数组，transcript.jsonl 也存逐行消息（磁盘 2×，且可能不一致）
2. provider 字段仅存在于 session.json，transcript.jsonl 无此信息
3. 三条写路径 → 数据不一致风险高（time-of-check-to-time-of-use）
4. cost 块同时写入 metadata.json 和 transcript.jsonl 两处
```

##### 目标：从 3 文件减为 2 文件，消除消息冗余

```
现状:  sessions/xxx/  ├── session.json      (全量消息 + provider + cost)
                       ├── metadata.json     (摘要字段 + cost)
                       └── transcript.jsonl  (逐行消息 + cost_block)

目标:  sessions/xxx/  ├── metadata.json      (精简摘要，仅列表用)
                       └── transcript.jsonl  (增强: 首行 session_init + 消息行 + 末行 session_snapshot)
```

消除 `session.json` 全量消息转储，所有必要信息（provider + 消息 + cost）由 `transcript.jsonl` 单一文件承载。

##### 文件格式规范

**`transcript.jsonl`**（增强格式）：

```
第 1 行:  {"type":"session_init","session_id":"...","provider":"openai",
           "model":"claude-sonnet-4-20250514","created_at":"2026-06-16T09:03:02"}

第 2~N 行: {"type":"message","role":"user","content":[...],"uuid":"...","timestamp":"..."}
           {"type":"message","role":"assistant","content":[...],"uuid":"...","timestamp":"..."}
           {"type":"cost_block","cost":{"total_cost_usd":0.01,...}}              (每轮费用快照)

最后 1 行: {"type":"session_snapshot","cost":{...},"updated_at":"2026-06-16T10:00:00"}
           (每次 Session.save() 追加，可被后续 snapshot 覆盖)
```

行类型：
| `type` | 写时机 | 用途 |
|--------|--------|------|
| `session_init` | 会话创建时写入第 1 行 | `Session.load()` 读 provider + model + created_at |
| `message` | 每轮消息写入 | 恢复会话消息列表 |
| `cost_block` | 每轮结束后写入 | 流式回放费用变化 |
| `session_snapshot` | `Session.save()` 时追加 | `cost_restore` 读最后一行恢复 cost 计数器 |

**`metadata.json`**（精简为仅列表摘要）：

```json
{
  "session_id": "...",
  "model": "claude-sonnet-4-20250514",
  "title": "session-xxx",
  "start_time": 1781571782.727674,
  "last_updated": 1781571782.735989,
  "message_count": 42,
  "tags": ["orchestrator"]
}
```

移出字段：`cwd`, `total_cost`, `last_user_input`, `agent_name`, `cost` 全部从 metadata 移除，改从 `transcript.jsonl` 首行/末行读取。

##### 读写流程对比

| 操作 | 现状（3 文件） | Phase 5 后（2 文件） |
|------|:-------------:|:------------------:|
| `Session.save()` | 写 session.json（覆写）+ 追加 cost_block 到 transcript.jsonl | 追加 `session_snapshot` 行到 transcript.jsonl + 更新 metadata.json |
| `Session.load(sid)` | 读 session.json → O(1) 全量反序列化 | 读 transcript.jsonl 第 1 行（provider） + 扫描所有 message 行 + 读最后 1 行（cost） |
| `SessionStorage.flush()` | 追加消息行到 transcript.jsonl | 不变 |
| `cost_restore.restore_cost_state_for_session()` | 读 session.json 的 cost 块 | 读 transcript.jsonl 最后一行（`tail -1` → O(1)） |
| `SessionStorage.list_sessions()` | 读 metadata.json（O(1) per session） | 不变 |
| `TailFollower` | `tail -f transcript.jsonl` | 不变 |

##### 具体改造点

| 编号 | 文件 | 改动说明 | 工作量 |
|:----:|------|---------|:------:|
| P5-A | `src/agent/session.py` `save()` | 删除 session.json 写入；改为追加 `type:"session_snapshot"` 行到 transcript.jsonl | 0.5天 |
| P5-B | `src/agent/session.py` `load()` | 改为读 transcript.jsonl：首行→provider/model/created_at；扫描 message 行→conversation；尾行→cost | 1天 |
| P5-C | `src/services/cost_restore.py` | 改为读 transcript.jsonl 最后一行（`tail -1`）获取 cost 块 | 0.5天 |
| P5-D | `src/agent/session.py` `resume()` | 依赖 P5-B 自动生效；删除 `Session.load()` 回退到 `load_from_session_storage` 的逻辑 | 0.25天 |
| P5-E | `extensions/agent/session_persist.py` | `save_to_session_storage()` 写入 transcript.jsonl 第 1 行 `session_init`（含 provider + model）；删除多余的 cost_block 双写 | 0.5天 |
| P5-F | `src/services/session_storage.py` | metadata.json 精简：移除 cwd, total_cost, last_user_input, agent_name, cost 字段 | 0.5天 |
| P5-G | `src/agent/transcript.py` `TranscriptWriter` | 可选：支持写入 `session_init` 类型行（复用已有序列化逻辑） | 0.25天 |
| P5-H | 旧 session 迁移脚本 | `clawcodex-dev session migrate --from-3-file` 读取旧 `.json` 转换为新的 transcript.jsonl 格式 | 1天 |

##### 向后兼容策略

- **读取降级**：`Session.load()` 检测到 `session.json` 存在且 `transcript.jsonl` 的第 1 行不是 `session_init` 类型时，自动回退到旧格式（从 session.json 读取 provider 和消息）
- **只读旧会话**：旧 session.json 不会自动删除，用户可在确认 Phase 5 稳定后手动运行迁移脚本
- **Phase 5 内部可开关**：通过 Feature Gate `F49_P5_ENABLED=true/false` 控制新写入路径
- **`metadata.json` 字段兼容**：reader 对 metadata.json 中缺失的 cwd/cost 等字段有默认值处理

##### 方案对比验证

| 维度 | 现状（3 文件） | 方案 A（纯 JSONL） | 方案 B（Hybrid） | **方案 C（JSONL + 精简 meta）** |
|------|:------------:|:----------------:|:--------------:|:---------------------------:|
| 文件数 | 3 | 1 | 1 | **2** |
| 消息冗余 | 2 份（.json + .jsonl） | 无冗余 | 无冗余 | **无冗余** |
| 列表 O(1) | ✅ | ❌（需 scan 到尾行） | ✅ | **✅** |
| 恢复 O(1) | ✅（.json） | ❌（scan 消息） | ✅（先读 header） | **❌（需 scan 消息，但 N 通常 < 2000）** |
| cost_restore O(1) | ✅ | ✅（tail -1） | ✅ | **✅（tail -1）** |
| 追加写性能 | ✅ | ✅ | ❌（每轮覆写头部） | **✅** |
| 数据一致风险 | 中（3 文件） | 低（单文件） | 低 | **低** |
| 迁移难度 | 基线 | 高（全量变更） | 中 | **低（6 个文件改动）** |

##### 验收标准

| # | 场景 | 预期 |
|---|------|------|
| 1 | REPL 交互 → exit → `Session.load()` | provider + 全量消息 + cost 正确恢复，无 session.json 依赖 |
| 2 | Cron bg_runner 运行 → exit | transcript.jsonl 最后一行是 `session_snapshot`，含正确 cost |
| 3 | `cost_restore.restore_cost_state_for_session()` | 从 transcript.jsonl `tail -1` 恢复 cost 计数器 |
| 4 | `SessionStorage.list_sessions()` | 50 个会话读取 < 200ms（仅读 metadata.json） |
| 5 | 旧 session.json 仅存在时 `Session.load()` | 自动降级读取旧格式，日志提示建议迁移 |
| 6 | Phase 5 写入后 `TailFollower` | 不变行为：增量追加行正确触发 |
| 7 | 消息一致性：save → load → 再次 save → 再次 load | 消息条数、顺序、uuid 完全一致 |

##### 风险与约束

- **恢复性能降级**：`Session.load()` 从 O(1) 变为 O(N)。实测 N=500 条消息时，JSONL 扫描 < 50ms，属于可接受范围
- **并发写 tail 行**：`session_snapshot` 使用追加写而非覆写，可能存在多个 snapshot 行。reader 应取最后一行（已设计为 `tail -1`）
- **迁移脚本**：建议 Phase 5 稳定运行 1 周后再批量迁移旧会话，期间维持读降级兼容
- **`cwd` 从 metadata 移除**：`session_resume._adjust_paths()` 需要 cwd 做路径调整。改为从 transcript.jsonl 首行 `session_init` 读取，或运行时由 `AgentRunner.run()` 注入

##### 依赖与协同

- **F-49 Phase 0 ~ 0.4**：前置依赖，统一事件存储 + 全场景会话恢复
- **F-91 ~ F-96 Visualizer**：`session.json` 的移除需要 Visualizer 的数据管道适配新的 transcript.jsonl 首行/尾行格式
- **F-97 Telemetry**：须确认遥测事件读的是 transcript.jsonl 而非 session.json
- **F-54 可观测性**：`state_journal.ndjson` 无冲突（独立文件，与 session 存储无关）

### 1.4.6 parentUuid 链 + walkChainBeforeParse 读取过滤（F-103 ✅）

**状态**: ✅ 已完成
**目标**: 引入 CCB 的 `parentUuid` 链式消息关联 + `walkChainBeforeParse` 字节级链裁剪，彻底消除 `/rewind`/fork/死分支导致的 on-disk 与 in-memory 状态不一致问题。

##### 问题现状

| 场景 | ClawCodex 当前行为 | CCB 行为 |
|------|-------------------|----------|
| `/rewind` 后磁盘 | 旧消息仍在 transcript.jsonl，**下次 --resume 恢复全部**（含已回退的内容） | 旧消息是"死分支"，**读路径自动跳过** |
| `/rewind` 后新对话 | 新消息追加到末尾，与旧消息混在一起 | 新消息 `parentUuid` 指向回退目标，形成清晰的分支拓扑 |
| Fork 会话 | 复制/重写整个 transcript | 新会话 `parentUuid` 指向原会话 leaf，天然 fork |
| `--resume` 恢复 | 全量读 → 全量重建（含死分支） | `walkChainBeforeParse` → 字节级裁剪 → 只解析活跃链 |
| `_engine_messages` vs `conversation.messages` | 两套列表需手动同步（已修 `--resume`，但 `/rewind` 仍有 bug） | 单一消息列表，`parentUuid` 显式编码关系 |

##### 核心设计

**A. 消息存储格式升级：增加 `parentUuid` 字段**

当前 `transcript.jsonl` 每条消息的 JSON 格式增加一个可选字段：

```json
{
  "uuid": "a1b2c3d4-...",
  "parentUuid": "e5f6g7h8-...",   // ← 新增：指向父消息的 uuid
  "role": "user",
  "content": "...",
  "timestamp": "..."
}
```

- `parentUuid: null` → 根消息（对话首条）
- `parentUuid: "<uuid>"` → 指向链中的父消息
- 写入时由 `SessionStorage.write_message()` 或 `save_to_session_storage()` 负责设置

**B. 引入 `walkChainBeforeParse()` 字节级链裁剪**

在 `SessionStorage.read_transcript()` 或 `Session.load()` 中新增过滤步骤：

```
read_transcript() 流程 (当前):
  transcript.jsonl → read all lines → JSON.parse each → return all

read_transcript() 流程 (升级后):
  transcript.jsonl → read raw bytes → walkChainBeforeParse()
    → 扫描 {"parentUuid": 前缀建索引
    → 从末行 leaf 走链回根
    → 只保留活跃链的 byte 区间 + 元数据行
    → 丢弃死分支（rewind/fork 遗留）
  → JSON.parse (仅过滤后的 buffer)
  → return active chain messages
```

关键优化门禁：只有当死分支占比 > 50% 时才执行 concat，避免小会话的性能浪费（与 CCB 的 `SKIP_PRECOMPACT_THRESHOLD` 对标）。

**C. `buildConversationChain()` 链重建**

在消息解析后，从 leaf message 沿 `parentUuid` 走回根，构建有序的消息列表：

```python
def build_conversation_chain(messages: dict[str, Message], leaf_uuid: str) -> list[Message]:
    chain = []
    current = leaf_uuid
    while current:
        msg = messages.get(current)
        if not msg:
            break
        chain.append(msg)
        current = msg.parent_uuid
    chain.reverse()
    return chain
```

**D. `/rewind` 持久化语义变革**

| 层面 | 当前行为 | 升级后行为 |
|------|---------|-----------|
| 内存 | `conversation.messages = msgs[:orig_idx]` | 不变（截断内存列表） |
| `_engine_messages` | `= []`（清空） | 不变 |
| 磁盘 | **不变**（append-only，旧消息永远保留） | **不变**（append-only，旧消息成为死分支） |
| `save_transcript()` 后 | 通过 UUID 去重跳过已写消息，死分支永远存在 | 新消息的 `parentUuid` 指向目标消息，**死分支在读取时被 `walkChainBeforeParse` 裁剪** |

**E. `Session.resume()` / `--resume` 读取路径升级**

```
Session.resume(sid)
  → Session.load(sid)
    → transcript.jsonl 存在？
      → YES: read_raw_bytes() → walkChainBeforeParse() → parseJSONL() → build_conversation_chain() → return Session(conversation=active_chain)
      → NO: fallback 旧格式兼容
```

##### 改造点清单

| 子特性 | 文件 | 说明 | 状态 |
|--------|------|------|:----:|
| **P103-A** | `src/services/session_storage.py` | `write_message()`/`write_raw()` 增加 `parentUuid` 参数；`flush()` 写入时附带该字段 | ✅ 已完成 |
| **P103-B** | `clawcodex_ext/agent/chain_filter.py` | 新增 `walk_chain_before_parse()` 字节级链裁剪函数（移植 CCB 算法）；门禁阈值常量 `DEAD_BRANCH_RATIO=0.5` | ✅ 已完成 |
| **P103-C** | `clawcodex_ext/agent/chain_filter.py` | 新增 `build_conversation_chain()` 从 leaf 沿 parentUuid 重建有序链 | ✅ 已完成 |
| **P103-D** | `clawcodex_ext/agent/session.py` | `read_transcript()` 改造：集成 `walkChainBeforeParse` + `buildConversationChain`，默认只返回活跃链；保留 `chain_filter=False` 逃生口供 Visualizer/遥测使用 | ✅ 已完成 |
| **P103-E** | `extensions/agent/session_persist.py` | `save_to_session_storage()` 计算并写入 `parentUuid`（从 `conversation.messages` 上一条消息的 uuid 获取） | ✅ 已完成 |
| **P103-F** | `extensions/agent/session_persist.py` | `Session.save()` / `save_transcript()` 透传 `parentUuid` 到 `save_to_session_storage()` | ✅ 已完成 |
| **P103-G** | `clawcodex_ext/agent/session.py` | `Session.load()` / `resume()` 集成新读取路径（`walkChainBeforeParse` 门禁 + `buildConversationChain`） | ✅ 已完成 |
| **P103-H** | `clawcodex_ext/repl/core.py` | `_sync_conversation_from_transcript()` 可选适配新格式（读端已走 `Session.load()`，无需单独修改；保留防御性 double-check） | ✅ 已完成（复用） |
| **P103-I** | `tests/test_session_f103_chain.py` | 验证：① 写入 chain → 读取 chain 一致 ② rewind 后新消息形成分支 ③ `walkChainBeforeParse` 正确裁剪死分支 ④ `--resume` 只恢复活跃链 | ✅ 已完成（22 测试） |
| **P103-J** | 旧 session 兼容 | 旧格式 transcript 无 `parentUuid` → `walkChainBeforeParse` 退化为全量读（无死分支可裁），`buildConversationChain` 退化为全量返回 | ✅ 已完成 |

##### 验收标准

| # | 场景 | 预期 | 测试 |
|---|------|------|------|
| 1 | 新格式写入：user → assistant → user → assistant 四轮 | 每条消息的 `parentUuid` 指向正确的父消息 | `TestInjectParentUuids::test_chain_topology` |
| 2 | `/rewind` → 新消息 → `save_transcript()` | 新消息的 `parentUuid` 指向回退目标，旧消息仍在磁盘但成为死分支 | `test_rewind_creates_fork_topology` |
| 3 | 上述场景后 `--resume` | 只恢复活跃链（回退后的消息），死分支消息不可见 | `test_load_returns_active_chain_after_rewind` |
| 4 | 混合场景：repl 交互 → exit → 再次 `--resume` → 递归一致 | 消息条数、顺序、关系与 exit 前一致 | `test_load_returns_active_chain_after_rewind` |
| 5 | `walkChainBeforeParse` 门禁：死分支 < 50% 时跳过 | 小会话性能无退化 | `test_low_dead_branch_ratio_skips_filter` |
| 6 | `walkChainBeforeParse` 门禁：死分支 > 50% 时执行 | 大会话（>100 条消息 + 多次 rewind）恢复速度优于全量 parse | `test_high_dead_branch_ratio_filters` |
| 7 | 旧格式 transcript 无 `parentUuid` 字段 | 降级为全量读，不报错，消息完整 | `test_load_returns_all_when_legacy_no_parentUuid` |
| 8 | `/rewind` → exit → 再次 `--resume` | 不会复活已回退的消息（**当前行为的 bug 修复验证**） | `test_load_returns_active_chain_after_rewind` |

##### 风险与约束

| 风险 | 缓解措施 |
|------|---------|
| `walkChainBeforeParse` 字节扫描增加读路径延迟（小会话） | 死分支比例门禁（< 50% 跳过） + 绝对大小门禁（< 10KB 跳过） |
| 旧 transcript 无 `parentUuid` → 全量读 | 降级逻辑：检测 Json 中 `parentUuid` 缺失则跳过过滤 |
| 新写入消息的 `parentUuid` 计算需要知道最后一条消息的 uuid | `session.conversation.messages[-1].uuid`（现有字段） |
| Visualizer/遥测/state_journal 需要全量数据 | 保留 `chain_filter=False` 逃生口，跳过链过滤 |
| `_engine_messages` 和 `conversation.messages` 的同步问题 | 本特性不改变同步方式（`_engine_messages` 仍作为引擎快照保留），但链式结构为未来统一提供了基础 |

##### 已拟定的设计决定

1. **`parentUuid` 是写入时计算，非读取时推导** — 写入时从 `conversation.messages[-1].uuid` 获取，确保准确性（F-103 实现采用"总是 recompute"策略，不信任 pre-existing 值）
2. **`walkChainBeforeParse` 作为字节级预过滤，不参与 JSON 解析** — 与 CCB 保持一致：只扫描 `{"parentUuid":` 前缀做字节定位，不 parse 整行
3. **兼容旧格式通过检测 `parentUuid` 字段缺失** — 不引入版本号/feature gate
4. **`chain_filter=False` 保留给元数据/分析消费者** — Visualizer、遥测、session_browser 等需要完整数据的场景
5. **不与 F-49 Phase 5 冲突** — Phase 5 改变了文件格式（JSONL + 精简 metadata），F-103 在此基础上增加字段。Phase 5 需先稳定
6. **最新 leaf 优先** — 多 leaf 场景用 `max(line_indices)` 选最新写入的分支（rewind 后的新分支而非死分支，即使死分支更长）

##### 依赖与协同

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-49 Phase 5（`session.json` + `transcript.jsonl` 合并） | 硬依赖 | F-103 的 `parentUuid` 字段需要追加到 `transcript.jsonl` 中；Phase 5 先需稳定 |
| `src/services/session_storage.py` | 核心改动 | 三个新函数 + `read_transcript()` 改造 |
| `extensions/agent/session_persist.py` | 写入路径改动 | `save_to_session_storage()` 计算 `parentUuid` |
| `clawcodex_ext/agent/session.py` | 读取路径改动 | `Session.load()`/`resume()` 集成链过滤 |
| F-91 ~ F-96 Visualizer | 兼容约束 | 数据管道需适配新格式 / 使用 `chain_filter=False` |
| F-97 Telemetry | 兼容约束 | 遥测读 `chain_filter=False` 不受影响 |




### 1.5.1 声明式工作流引擎核心（F-1.10 📋）

**状态**: 📋 规划中  
**优先级**: P0  
**目标**: 读取 `workflow.yaml`，按 DAG 顺序调度 Agent，管理 GATE/DECISION/回环，提供工作流级错误恢复和成本追踪。

**引擎核心**：

```python
class DeclarativeWorkflowEngine:
    """声明式工作流引擎 — 解释执行 workflow.yaml"""

    def __init__(self, workflow: WorkflowSchema, config: EngineConfig):
        self.workflow = workflow
        self.config = config
        self.state = WorkflowState(workflow)
        self.stage_runner = StageRunner(config)
        self.cost_tracker = CostTracker(config.cost_budget)

    async def execute(self, from_stage: int | None = None) -> WorkflowResult:
        current = self._resolve_start(from_stage)
        while current is not None:
            node = self.workflow.get_stage(current)
            self.state.mark_running(current)
            self._emit_event("stage_start", current)

            try:
                result = await self.stage_runner.run(node, self.state)
                if not self._validate_outputs(node, result):
                    result = await self._handle_validation_failure(node, result)

                self.cost_tracker.record(current, result.cost_usd)
                self.state.write_checkpoint(current, result)
                self._emit_event("stage_complete", current, result)

                if node.gate and node.gate.enabled:
                    decision = await self._handle_gate(node, result)
                    if decision == "reject":
                        current = node.gate.rollback_on_reject
                        continue

                if node.decision:
                    outcome = self._parse_decision(result)
                    current = self._resolve_decision(node, outcome)
                    continue

                current = self.workflow.next_stage(current)

            except StageTimeoutError:
                current = self._handle_timeout(node)
            except StageFailureError:
                current = self._handle_failure(node)
            except CostBudgetExceeded:
                current = self._handle_cost_exceeded(node)

        return self.state.finalize()
```

**与 Orchestrator 的关系**：


```
DeclarativeWorkflowEngine
  ├── 复用 → AgentRunner (F-1)
  │            └── stagnation detection (F-51)
  │            └── loop detection
  │            └── rate limit circuit breaker
  │            └── session transcript persistence
  ├── 复用 → ProgressSink (F-40)
  │            └── 工作流级进度报告
  ├── 复用 → Verification Pipeline (F-38)
  │            └── 阶段输出的验证
  ├── 复用 → State Journal Writer (F-91~F-96)
  │            └── 工作流事件的 NDJSON 日志
  ├── 复用 → ClarificationQueue (F-39)
  │            └── GATE 的人类审批通道
  ├── 复用 → CostTracker (F-1 已有)
  │            └── 阶段级成本统计
  └── 新增 → StageRunner 适配器
               └── 将阶段包装为 AgentRunner 可执行的 Issue
```

**子特性**：

| 编号 | 名称 | 状态 | 描述 |
|------|------|------|------|
| F-1.10.1 | 核心执行循环 | 📋 | DAG 遍历 + 顺序执行 + 事件发射 |
| F-1.10.2 | 阶段调度 | 📋 | 调用 StageRunner 执行单个阶段 |
| F-1.10.3 | 输出验证 | 📋 | 调用 ValidatorSpec 执行阶段输出验证 |
| F-1.10.4 | 错误处理策略 | 📋 | timeout/failure/cost-exceeded 的可配置处理 |
| F-1.10.5 | 工作流级事件总线 | 📋 | stage_start/stage_complete/gate_request 等事件 |
| F-1.10.6 | 成本追踪与预算控制 | 📋 | 阶段级预算 + 全局预算 + 预警阈值 |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/engine.py` | `DeclarativeWorkflowEngine` 核心 | 📋 |
| `extensions/orchestrator/workflow_engine/workflow_state.py` | 工作流运行时状态 | 📋 |
| `extensions/orchestrator/workflow_engine/event_bus.py` | 事件总线 + State Journal 写入 | 📋 |
| `extensions/orchestrator/workflow_engine/cost.py` | `CostTracker` + `CostBudget` | 📋 |
| `extensions/orchestrator/workflow_engine/errors.py` | 异常类型定义 | 📋 |

---

### 1.5.2 StageRunner 适配器（F-1.11 📋）

**状态**: 📋 规划中  
**优先级**: P0  
**目标**: 桥接 `DeclarativeWorkflowEngine` 与 `AgentRunner`，将阶段执行适配为 `AgentRunner` 可消费的工作单元。

**适配器设计**：

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

**设计决策**：

| # | 决策 | 理由 |
|---|------|------|
| DD-5 | 方案 A（合成 Issue 适配器）优先 | 保留 AgentRunner 的全部稳健机制 |
| DD-6 | Workspace 使用共享模式（F-42） | 阶段间共享 `workspace_dir`，不需要 git 隔离 |
| DD-7 | 备选方案 B（QueryRunner）保留 | 如适配开销过大，可切换 |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/stage_runner.py` | `StageRunner` + AgentRunner 适配器 | 📋 |

---

### 1.5.3 GATE 门禁处理器（F-1.12 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 处理工作流中的 GATE 阶段——人类审批、自动阈值、回滚。

**三种审批模式**：

1. **manual** — 通过 ClarificationQueue（F-39）暂停工作流，等待人类审批/拒绝
2. **auto** — 基于 ValidatorSpec 自动判定，所有 validator 通过即 approve
3. **threshold** — LLM-as-judge 评分，达到阈值自动 approve，否则进入 manual

**复用 F-44（Human Review Gate）**：

- `issue review --approve/--reject` 扩展为 `workflow gate --approve/--reject`
- `PENDING_REVIEW` 状态扩展为 `GATE_PENDING` 工作流级状态
- workspace 保留策略沿用（GATE 暂停时保留阶段产物供检查）

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/gate_handler.py` | `GateHandler` 核心 | 📋 |
| `extensions/orchestrator/workflow_engine/gate_modes.py` | manual/auto/threshold 三种模式 | 📋 |
| `extensions/orchestrator/workflow_engine/gate_rollback.py` | 回滚逻辑 | 📋 |

---

### 1.5.4 DECISION 决策处理器（F-1.13 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 处理工作流中的决策点——多结果分支、回环、收敛检测。

**核心逻辑**：

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

**收敛检测**：追踪同一 decision outcome 的连续触发次数 + 阶段输出 diff，判定退化循环。

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/decision_handler.py` | `DecisionHandler` | 📋 |
| `extensions/orchestrator/workflow_engine/decision_history.py` | 决策历史 + 收敛检测 | 📋 |
| `extensions/orchestrator/workflow_engine/rollback.py` | 阶段目录快照 + 版本化回滚 | 📋 |

---

### 1.5.5 阶段契约验证器（F-1.14 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 执行阶段输出的机器可验证 DoD 检查。

**内置 Validator 实现**：

| 类型 | 实现 | 优先级 |
|------|------|--------|
| `file_exists` | `Path.exists()` | P0 |
| `file_size` | `Path.stat().st_size` | P0 |
| `regex` | `re.findall()` + `min_matches` | P0 |
| `json_schema` | `jsonschema.validate()` | P1 |
| `line_count` | `len(file.readlines())` | P0 |
| `llm_judge` | LLM 评估 + 分数阈值 | P1 |
| `custom` | `subprocess.run()` + exit code | P2 |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/validators/__init__.py` | `ContractValidator` + 注册表 | 📋 |
| `extensions/orchestrator/workflow_engine/validators/builtin.py` | 6 种内置 Validator | 📋 |
| `extensions/orchestrator/workflow_engine/validators/llm_judge.py` | LLM-as-judge | 📋 |
| `extensions/orchestrator/workflow_engine/validators/custom.py` | 自定义命令 | 📋 |

---

### 1.5.6 检查点与恢复（F-1.15 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 工作流级检查点持久化，支持从任意阶段恢复执行。

**检查点格式**：

```json
{
  "workflow_name": "arc-research",
  "workflow_version": "1.0",
  "current_stage": 12,
  "completed_stages": [1, 2, ..., 11],
  "stage_results": {
    "1": { "status": "success", "outputs": ["goal.md"], "timestamp": "..." }
  },
  "decision_history": [
    { "stage": 15, "outcome": "refine", "timestamp": "..." }
  ],
  "cost_accumulated_usd": 12.34,
  "started_at": "2026-06-18T10:00:00Z",
  "last_checkpoint": "2026-06-18T14:30:00Z"
}
```

**复用策略**：
- 复用 ARC 已有的原子写入模式（temp file + rename）
- 复用 Orchestrator 的 `SessionStorage`（F-49）存储每阶段 Agent session transcript
- 复用 State Journal Writer（F-91~F-96）写入工作流级事件日志

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/checkpoint.py` | 检查点写入/读取/验证 | 📋 |
| `extensions/orchestrator/workflow_engine/resume.py` | 从检查点恢复执行 | 📋 |
| `extensions/orchestrator/workflow_engine/artifact_resolver.py` | 跨阶段产物路径解析 | 📋 |

---

### 1.5.7 工作流可观测性集成（F-1.16 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 将工作流执行事件集成到 ClawCodex 的可视化和审计体系。

**集成点**：

| 来源特性 | 复用内容 | 工作流适配 |
|---------|---------|-----------|
| F-91~F-96 Visualizer | State Journal NDJSON | `workflow_stage_start`/`workflow_gate_request`/`workflow_decision`/`workflow_complete` |
| F-91~F-96 Visualizer | Gantt 图 | 阶段执行时间渲染为 Gantt 条形图 |
| F-45 Audit Trail | Tool-call NDJSON | 工作流级事件写入 `~/.clawcodex/tool-events/` |
| F-40 ProgressSink | 进度报告协议 | `WorkflowProgressSink` 报告阶段完成百分比 |
| F-20 Progress Reporting | 检查点触发的进度报告 | 每阶段完成后触发 `ProgressReportTool` |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/orchestrator/workflow_engine/observability.py` | State Journal 事件写入 | 📋 |
| `extensions/orchestrator/workflow_engine/progress.py` | `WorkflowProgressSink` | 📋 |
| `extensions/orchestrator/workflow_engine/audit.py` | 工作流级审计事件 | 📋 |

---

---


---



### 1.6.1 动态任务分解引擎（F-118 🔭）

**状态**: 🔭 长期规划（本特性规划文档仅做方向性定义）  
**优先级**: P2  
**目标**: 单次复杂任务实时分解为多个 subagent 并行/串行执行，动态规划子任务、调度 wave、合并结果。

**能力范围**：

| 能力 | 说明 | 对标 Claude Code |
|------|------|-----------------|
| 任务复杂度分析 | 判断任务是否需要分解（单步 vs 多步） | Plan Mode |
| 子任务分解 | 将复杂任务拆分为原子 phase | EnterPlanMode/ExitPlanMode |
| 依赖分析 | 判断子任务间是否可并行 | 依赖图分析 |
| 执行模式选择 | sequential vs parallel | sequential / parallel waves |
| 子 agent 调度 | 调用 `fork_subagent`/`Agent()` 执行 | Agent(...) |
| 结果合并 | 去重、筛选、合并子 agent 输出 | 脚本级合并（零 token） |
| 验证循环 | adversarial verification / loop-until-done | 六种模式组合 |

**触发方式**：

```bash
# 单次任务触发（类似 ultracode 关键字）
clawcodex --swarm "create a simple calculator app with NextJS backend"
# 或
clawcodex --decompose "refactor this codebase to use async/await"

# Session 设置（自动模式）
clawcodex --effort swarm
# 此后每个实质性任务自动分解
```

**与声明式工作流引擎的区分原则**：

| 决策 | 声明式工作流引擎（F-1.10） | 动态任务分解（F-118） |
|------|--------------------------|---------------------|
| 编排脚本 | 人类可审阅的 YAML | 内部生成的子任务列表（不可见） |
| 持久化 | ✅ workflow.yaml 保存到磁盘 | ❌ 不持久化 |
| 检查点 | ✅ per-stage | ❌ 无（仅 session 恢复） |
| 成本预算 | ✅ 阶段级 | ⚠️ 累计消耗 |
| 命名空间 | `workflow` / `workflow_engine` | `swarm` / `decompose` / `task_decomposition` |
| CLI 命令 | `clawcodex-dev workflow run` | `clawcodex --swarm` |

**实现位置**: 

```
extensions/orchestrator/
├── workflow_engine/          # F-1.10~F-1.16（声明式，长期管线）
│   └── engine.py            # DeclarativeWorkflowEngine
└── task_decomposition/      # F-118（动态，单次任务）
    └── engine.py            # TaskDecompositionEngine（未来规划）
```

**设计约束**：
1. 动态任务分解**不依赖**声明式工作流引擎的任何代码（避免概念混淆）
2. 动态任务分解**复用** `fork_subagent`、`Agent()` 工具、现有 `AgentRunner`
3. 命名上严禁使用 "workflow" 一词，使用 "swarm" / "decompose" / "task_decomposition"

---

---


---

## 二、Agent 核心能力

### 2.1 Agent 阶段性进度汇报（F-20 ✅）
**状态**: ✅ 已完成（F-20）
**目标**: 在 Agent 编排中阶段性将结果汇报至任务看板，将任务看板提取为工具

> 三组合实现方案（检查点触发 + ProgressReportTool + ToolContext.tasks）、架构设计、工具 Schema、与现有组件集成点等已归档。
> 详见 [ARCHIVED_FEATURES.md §十六（Orchestrator 自主模式 16.x）](./ARCHIVED_FEATURES.md#十六orchestrator-自主模式symphony-集成) 与对应进度归档 [ARCHIVED_PROGRESS.md F-20](./ARCHIVED_PROGRESS.md#f-20-agent-阶段性进度汇报)。

---

### 2.2 Team 成员管理（Phase-7）（F-2 ✅）

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

### 2.3 结构化输出增强（Outlines）（F-4 ✅）
**状态**: ✅ 已完成（F-4）
**目标**: 使用 Outlines 预生成约束替代 json.loads + 手动验证

> 适配器已完整实现并迁移至 `clawcodex_ext/agent/_outlines_adapter.py`。详细设计（适用场景、数据模型、实现文件）已归档至 [ARCHIVED_FEATURES.md §二十三.5 F-4 结构化输出增强](./ARCHIVED_FEATURES.md#二十三5-f-4-结构化输出增强)。

### 2.4 MCP 扩展功能（F-3 ✅）
**状态**: ✅ 已完成（基础功能已完成，持续增强）
**目标**: 完整的 MCP 协议支持

> 5 项基础传输与硬化能力（Stdio / HTTP+SSE / WebSocket / OAuth / HTTPS+XSS 硬化）已归档。
> 详见 [ARCHIVED_FEATURES.md §十七（MCP 协议扩展）](./ARCHIVED_FEATURES.md#十七mcp-协议扩展) 与对应进度归档 [ARCHIVED_PROGRESS.md F-3](./ARCHIVED_PROGRESS.md#f-3-mcp-协议扩展)。

#### 2.4.1 待增强（F-3 ✅）
| 功能 | 优先级 | 说明 | 状态 |
|------|--------|------|:----:|
| MCP 资源缓存 | P2 | 减少重复获取 — LRU 缓存 + TTL (`clawcodex_ext/mcp_ext.py`) | ✅ 已完成 |
| MCP Batch 工具调用 | P2 | 批量工具执行 — `McpBatchCallTool` (`clawcodex_ext/mcp_ext.py`) | ✅ 已完成 |
| MCP Progress 通知 | P3 | 长任务进度报告 — `extract_mcp_progress()` + wrapper (`clawcodex_ext/mcp_ext.py`) | ✅ 已完成 |

---

### 2.5 Agent 记忆作用域隔离（F-13 ✅）
**状态**: ✅ 已完成

> 详细设计与验证记录已归档至 [ARCHIVED_FEATURES.md §二十一.7 F-13 Agent 记忆作用域隔离](./ARCHIVED_FEATURES.md#二十一7-f-13-agent-记忆作用域隔离)。

### 2.6 /goal 命令（目标管理）（F-9 ✅）
**状态**: ✅ 已完成（2026-06-19 代码审计确认）| **实现位置**: `clawcodex_ext/goal/` 9 文件 2538 行
**目标**: 为长时间运行任务提供持久化目标、自动续跑、token 用量监控与恢复能力，避免用户需要反复输入“继续”。

> 完整设计（功能说明、状态机、核心机制、Token 追踪、Blocked/Completion 审计、提示词注入、持久化恢复、实现文件清单、UI 展示、测试覆盖）已归档至 [ARCHIVED_FEATURES.md §äºåå F-9 /goal 命令](./ARCHIVED_FEATURES.md#二十四f-9-goal-命令目标管理)。

---

### 2.7 ExecuteExtraTool 延迟工具系统（F-10 📋）
**状态**: 📋 规划中
**目标**: 按需加载延迟工具，支持语义搜索

#### 2.7.1 功能说明（F-10 📋）
完整的延迟工具按需加载系统，支持子代理（Async Agent）执行：

| 组件 | 功能 |
|------|------|
| SearchExtraToolsTool | TF-IDF 工具索引语义搜索 |
| ExecuteExtraTool | 通过名称和参数执行延迟工具 |
| validateInput 校验 | 调用前校验防止崩溃 |
| ASYNC_AGENT_ALLOWED_TOOLS | 子代理可执行延迟工具 |

#### 2.7.2 核心机制（F-10 📋）
| 机制 | 说明 |
|------|------|
| 工具延迟加载 | 工具按名称和参数动态执行，非预加载 |
| 语义搜索 | TF-IDF 索引支持自然语言工具搜索 |
| 子代理执行 | Async Agent 可调用延迟工具 |
| 输入校验 | execute 前 validateInput 防止无效调用 |

#### 2.7.3 实现文件（F-10 📋）
| 文件 | 位置 | 状态 |
|------|------|------|
| ExecuteExtraTool | `packages/builtin-tools/src/tools/ExecuteTool/ExecuteTool.ts` | 待实现 |
| SearchExtraToolsTool | `packages/builtin-tools/src/tools/SearchExtraToolsTool/` | 待实现 |
| ASYNC_AGENT_ALLOWED_TOOLS | `constants/tools.ts` | 待配置 |
| 延迟工具提示 | `constants/prompts.ts` | 待配置 |

---

### 2.8 工具/Skill 调用统计（跨会话）（F-75 ✅）

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

#### 统计所有 skill 调用
grep '"kind":"skill"' ~/.clawcodex/tool_stats.jsonl | jq '.skill' | sort | uniq -c | sort -rn

#### 统计工具 vs skill 调用比例
grep -E '"kind":"(tool|skill)"' ~/.clawcodex/tool_stats.jsonl | jq -s 'group_by(.kind) | map({kind: .[0].kind, count: length})'

#### 统计某个 agent 的调用
grep '"agent_id":"orchestrator-001"' ~/.clawcodex/tool_stats.jsonl | jq -s 'group_by(.kind) | map({kind: .[0].kind, count: length, avg_ms: (map(.dur_ms) | add / length)})'
```

#### 2.8.7 数据清理（F-75 ✅）
日志文件需定期归档或设置 TTL（建议保留最近 90 天数据）。

#### 2.8.8 实时查询（F-75 ✅）
**不支持**。如需实时展示（如 TUI 状态栏），需另建汇总表预聚合。

#### 2.8.9 替代方案：基于 Transcript 的轻量级统计（F-75 ✅）
如果只关心**调用频率和成功率**（不需要耗时），可直接解析现有 Transcript 文件，无需新建日志系统。

**数据来源**:

```
~/.clawcodex/transcripts/<agent_id>.jsonl
```

每行是一个 `Message`，其中包含 `ToolUseBlock`：

```json
{"type": "user", "content": [{"type": "tool_use", "id": "2", "name": "Read", "input": {"path": "foo.py"}}]}
{"type": "assistant", "content": [{"type": "tool_use", "id": "3", "name": "Edit", ...}]}
{"type": "user", "content": [{"type": "tool_result", "tool_use_id": "2", "content": "...", "is_error": false}]}
```

**统计维度**:

| 维度 | 支持 | 说明 |
|------|------|------|
| 调用频率 | ✅ | 按 tool/skill 名称统计 |
| 成功率 | ✅ | ToolResult.is_error 可判断 |
| 执行耗时 | ❌ | Transcript 不记录执行时长 |
| Skill 调用 | ⚠️ | 取决于 Skill 是否走 ToolUseBlock |

**查询示例**:

```bash
# 统计所有工具调用次数
grep '"type":"tool_use"' ~/.clawcodex/transcripts/*.jsonl | jq '.content[].name' | sort | uniq -c | sort -rn

# 统计某个 agent 的工具调用
grep '"type":"tool_use"' ~/.clawcodex/transcripts/agent-123.jsonl | jq -s 'group_by(.content[].name) | map({tool: .[0].content[].name, count: length})'

# 统计错误率（需配对 ToolUse → ToolResult）
# 由于 ToolUse 和 ToolResult 通过 id/tool_use_id 关联，需要更复杂的脚本
```

**优缺点对比**:

| 方案 | 优势 | 劣势 |
|------|------|------|
| **Transcript 方案** | 无需新增日志写入；已有数据 | 无耗时；Skill 覆盖不确定；解析稍复杂 |
| **JSON Lines 日志方案** | 包含耗时；字段完整；格式统一 | 需新增写入逻辑；数据冗余 |

**决策建议**:
- 仅需调用频率/成功率 → 用 Transcript 方案
- 需耗时统计 → 用 JSON Lines 日志方案

#### 2.8.10 基于使用频率的工具/Skill 裁剪（F-75 ✅）
基于工具和 Skill 的使用频率统计，可自动识别并裁剪低使用率组件，减少 Bundle 大小和上下文开销。

**裁剪策略**:

| 策略 | 说明 |
|------|------|
| **自动隐藏** | 低频工具从默认 bundle 移到 `bare` 模式，需显式引用 |
| **提示建议** | 统计报告提示"X 工具过去 90 天仅使用 N 次，可考虑移除" |
| **按需加载** | 低频工具默认不加载，使用前需 `ExecuteExtraTool` 引用 |

**配置参数**:

```yaml
tool_pruning:
  enabled: true
  lookback_days: 90          # 统计回溯周期
  low_usage_threshold: 0.01  # 使用率 < 1% 则标记为低频
  cooldown_days: 30          # 工具存在 > 30 天才纳入裁剪统计
  action: "hide"             # "hide" | "suggest" | "remove"
```

**实现逻辑**:

```python
def get_rarely_used_tools(lookback_days=90, threshold=0.01, cooldown_days=30) -> list[str]:
    """返回应裁剪的工具列表"""
    stats = parse_transcript_stats(lookback_days=lookback_days)
    total = sum(stats.values())
    now = time.time()
    for name, count in stats.items():
        usage_rate = count / total
        if usage_rate < threshold:
            # 冷却期判断（工具创建时间 > cooldown_days）
            if tool_exists_longer_than(name, days=cooldown_days):
                yield name
```

**注意事项**:

| 注意点 | 说明 |
|--------|------|
| 学习曲线 | 新工具初期使用率低不代表价值低，需冷却期保护 |
| 核心工具 | `Read/Edit/Bash` 等高频核心工具不受影响 |
| 保留 fallback | 低频工具仍可通过 `bare` 模式访问 |

#### 2.8.11 SOP 转化模式（F-75 ✅）
将标准作业流程（SOP）拆解为 Agent 架构，实现工作流的可复用、可观测、可编排。

**三层映射关系**:

| 工作流组件 | Agent 架构 | 示例 |
|-----------|-----------|------|
| SOP (标准作业流程) | Agent | 数据分析 Agent、CI/CD Agent、ML Pipeline Agent |
| 工作流步骤 | Skill | `deploy_service`、`run_etl`、`train_model` |
| SDK 接口 | 原子工具 | `s3_upload`、`k8s_apply`、`spark_submit` |

**架构示例**:

```
CI/CD Agent
├── Skill: build_image
│   ├── tool: docker_build()
│   ├── tool: docker_tag()
│   └── tool: docker_push()
├── Skill: deploy_service
│   ├── tool: k8s_apply()
│   ├── tool: health_check()
│   └── tool: rollback_if_failed()
└── Skill: notify_team
    ├── tool: slack_send()
    └── tool: email_send()
```

**转化过程（Skill + Template + Config）**:

| 层面 | 形式 | 说明 |
|------|------|------|
| **转化执行器** | Skill | 需要 LLM 判断如何分组、如何命名 |
| **产出物规范** | Template | Agent/Skill 定义的结构规范 |
| **映射规则** | Config | SDK method → tool 的映射表 |

```
Skill（执行器）+ Template（产出物规范）+ Config（映射规则）
```

**转化 Skill 示例**:

```python
class ConvertPOSToAgent:
    """将 SOP 转换为 Agent 的 Skill"""

    async def execute(self, sdk_spec: str, requirements: str) -> AgentDefinition:
        # 1. 解析 SDK 接口 → 需要理解 API 语义（LLM）
        atomic_tools = await self._parse_sdk_methods(sdk_spec)

        # 2. 按业务逻辑分组 → 需要判断相关性（LLM）
        skills = await self._group_into_skills(atomic_tools, requirements)

        # 3. 填充 Agent 定义模板
        return self._fill_template(skills)
```

**优势**:

| 优势 | 说明 |
|------|------|
| 可复用性 | 原子工具可在不同 Skill/Agent 间共享 |
| 可观测性 | 每步工具调用独立记录，便于调试 |
| 容错粒度 | 可在工具级别重试，而非整个工作流 |
| 动态编排 | Agent 可根据上下文选择不同的 Skill 执行路径 |

**与 F-18 CreateAgentTool 的关系**:

F-18 解决"工具创建工具"（Meta Tool 能力），此模式解决"工作流转化为 Agent"。两者结合可实现：SDK 接口 → 原子工具 → Skill 组合 → Agent 定义 → 动态注册。

**实现清单**:

| 文件 | 说明 |
|------|------|
| `src/pos_converter/__init__.py` | 模块入口 |
| `src/pos_converter/sdk_parser.py` | SDK 解析（支持 OpenAPI JSON / URL / 简单方法列表） |
| `src/pos_converter/skill_grouper.py` | Skill 分组（静态 MappingRule + LLM 辅助） |
| `src/pos_converter/agent_builder.py` | Agent 构建 + 持久化（`~/.clawcodex/agents/<name>.json`） |
| `src/pos_converter/convert_pos_skill.py` | `/convert-pos-to-agent` Skill 实现 |
| `src/pos_converter/templates.py` | 模板定义 |
| `src/skills_ext/bundled/pos_to_agent.py` | bundled skill 注册（解耦上游） |

**三层映射实现**:

```
SdkParser.parse()           → list[SdkMethod]  (原子工具)
SkillGrouper.group()       → list[SkillSpec]  (Skill 规范)
AgentBuilder.build()       → AgentDefinition (Agent 定义)
persist_converted_agent()   → ~/.clawcodex/agents/<name>.json
```

**使用方式**:

1. **斜杠命令**（REPL/TUI 中）:
   ```bash
   /convert-pos-to-agent docker_build,k8s_apply::CI/CD pipeline
   ```
   别名: `/pos-to-agent`

2. **CLI 子命令**（Linux/macOS shell）:
   ```bash
   clawcodex-dev pos convert <sdk_spec> [--out <output_dir>] [--requirements "<requirements>"] [--name <agent_name>]
   ```
   示例:
   ```bash
   clawcodex-dev pos convert docker_build,k8s_apply --out ./.clawcodex --requirements "CI/CD pipeline" --name cicd-agent
   ```
   支持从 `workflow.md` 文件解析前端元数据并输出 Agent/Workflow/Skill 定义文件。

3. **Python API**（编程调用）:
   ```python
   from extensions.pos_converter import convert_pos_to_agent
   result = convert_pos_to_agent(sdk_spec="docker_build,k8s_apply", requirements="CI/CD pipeline")
   ```

#### 2.8.12 业务 Agent 长期使用（新窗口重连）（F-75 ✅）
将 SOP 转化的 Agent 作为主 Agent 长期使用，并支持在新窗口中重新连接。

**核心能力**:

| 能力 | 说明 | 实现 |
|------|------|------|
| **持久化** | Agent 定义保存到文件 | `~/.clawcodex/agents/<name>.json` |
| **主 Agent 指定** | 启动时指定使用哪个 Agent | `clawcodex --agent <name>` 或配置文件 |
| **窗口重连** | 新窗口连接到已运行的 Agent | Session ID / Named Pipe |

**Agent 持久化格式**:

```json
// ~/.clawcodex/agents/cicd-agent.json
{
  "name": "cicd-agent",
  "description": "自动化部署 Agent",
  "model": "claude-sonnet",
  "tools": ["k8s_apply", "docker_push", "health_check"],
  "skills": ["deploy_service", "rollback"],
  "memory_scope": ["project", "team"],
  "persistent": true
}
```

**启动方式**:

```bash
# 方式一：启动时指定
clawcodex --agent cicd-agent

# 方式二：配置为默认
# ~/.clawcodex/settings.json
{
  "default_agent": "cicd-agent"
}

# 方式三：daemon 模式长期运行
clawcodex --daemon --agent cicd-agent
# 新窗口 attach
clawcodex attach cicd-agent
```

**Daemon + Attach 架构**:

```
终端 1: clawcodex --daemon --agent cicd-agent
        └── cicd-agent 进程运行中，保持状态
               ↓
终端 2: clawcodex attach cicd-agent
        └── 连接到已有 Agent 会话，继续交互
```

**需要新增的组件**:

| 组件 | 文件 | 说明 |
|------|------|------|
| Agent 存储 | `src/agent/agent_persistence.py` | 读写 `~/.clawcodex/agents/` |
| Agent 加载器 | `src/agent/agent_loader.py` | 启动时加载指定 Agent |
| Attach 协议 | `src/agent/attach.py` | 连接到已有 Agent 会话 |

**与现有组件的集成**:

| 现有组件 | 集成点 |
|---------|--------|
| `agent/agent_definitions.py` | Agent 定义模型 |
| `agent/session.py` | Session 持久化 |
| `agent/run_agent.py` | 主 Agent 启动逻辑 |
| `repl/core.py` | REPL 启动入口 |
| `src/entrypoints/headless.py` | Daemon 模式支持 |

---

### 2.9 CreateAgentTool 动态工具创建（F-18 ✅）
**状态**: ✅ 已完成
**目标**: Agent 可根据三方 CLI/API 规范动态创建工具，实现"工具创建工具"的 Meta Tool 能力

> 详细设计（架构设计、AgentToolSpec 规范、三种 call_impl 安全限制、安全性约束、持久化机制、与现有系统集成、实现文件清单）已归档至 [ARCHIVED_FEATURES.md §二十三.1 F-18 CreateAgentTool 动态工具创建](./ARCHIVED_FEATURES.md#二十三1-f-18-createagenttool-动态工具创建)。

---

### 2.10 sessionStorage 容量限制（F-11 ✅）
**状态**: ✅ 已完成
**目标**: 防止长时间运行的 daemon/swarm 会话导致内存泄漏

> 完整设计（功能说明、问题场景、实现文件）已归档至 [ARCHIVED_FEATURES.md §äºåäº F-11 sessionStorage 容量限制](./ARCHIVED_FEATURES.md#二十五f-11-sessionstorage-容量限制)。


### 2.11 cacheWarning 容量限制（F-12 ✅）
**状态**: ✅ 已完成

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.14 cacheWarning 容量限制](./ARCHIVED_FEATURES.md#二十一14-cachewarning-容量限制f-12)。

---
### 2.12 Issue 语义澄清流程（自主模式扩展）（F-78 ✅）
**状态**: ✅ 已完成（2026-06-19 代码审计确认）
**优先级**: P1
**目标**: 当 Issue 语义模糊时，通过**三通道优先机制**获取澄清——本地操作员（Dashboard/ClarificationQueue）优先，作者 @mention 兜底

> 三通道优先机制（Dashboard / ClarificationQueue / @mention）、平台能力对比、整体流程图、各通道详细设计、ClarificationStatus 枚举（含冲突处理 `DUPLICATE_REJECTED` / `STALE_REJECTED` / `CONFLICT_RESOLVED`）、多渠道冲突处理状态机、CLI `clarify` 命令、TrackerAdapter 评论接口与 GitHub/Gitee/GitCode 实现、IssueRegistry 澄清字段持久化、PromptBuilder 澄清内容注入、escalation 策略与配置等已归档。
> 详见 [ARCHIVED_FEATURES.md §16.5（Issue 语义澄清流程）](./ARCHIVED_FEATURES.md#十六orchestrator-自主模式symphony-集成) 与对应进度归档 [ARCHIVED_PROGRESS.md F-1.x 子特性](./ARCHIVED_PROGRESS.md#f-1x-orchestrator-自主模式f-1-子特性全部完成)。

---


### 2.13 Auto 模式 (TRANSCRIPT_CLASSIFIER)（F-16 ✅）

**状态**: ✅ 已完成（F-16）
**目标**: 基于 LLM 的自动权限模式切换，减少交互疲劳

> `auto_mode_classify()` 完整实现在 `src/permissions/check.py`：覆盖 Bash、Read、Write/Edit、Agent、MCP 等工具类型。配套 `DenialTracker` 支持拒绝计数与自动升级。详细设计（工作原理、模式对比、循环切换逻辑、分类器 prompt 设计、实施阶段）已归档至 [ARCHIVED_FEATURES.md §二十三.2 F-16 Auto 模式](./ARCHIVED_FEATURES.md#二十三2-f-16-auto-模式-transcript_classifier)。

---

### 2.14 Agent 间自主观察与消息交互（F-80 ✅）
**状态**: ✅ 已完成（2026-06-19 代码审计确认）
**优先级**: P1
**目标**: 实现 Manager Agent 全自动观察 Worker Agent 状态并注入指令，支持优先级队列和权限审批

> 角色定义（Manager / Worker 通过工具组合自动识别）、核心工具（`TaskInspect` + `TaskDirectives`）、优先级队列（`queue_pending_message` priority 字段 + `drain_pending_messages` 按优先级消费）、工具可见性过滤（仅 Manager 可调用）、权限规则传递与 Phase M1-M5 实施阶段已归档。
> 详见 [ARCHIVED_FEATURES.md §十八（Agent 间自主观察与消息交互）](./ARCHIVED_FEATURES.md#十八agent-间自主观察与消息交互) 与对应进度归档 [ARCHIVED_PROGRESS.md F-29（TaskInspect/TaskDirectives 工具注册）](./ARCHIVED_PROGRESS.md#f-29-taskinspecttaskdirectives-工具注册)。

---

### 2.15 Ctrl+C/B 即时中断响应优化（F-99 ✅）

**状态**: ✅ 已完成（2026-06-17）| **优先级**: P0
**目标**: 解决 LLM 流式响应 + 工具执行阶段按 Ctrl+C/Ctrl+B 需要 10~30s 才生效的 UX 问题，目标 < 500ms。

> 完整设计（问题根因、三层方案架构、改造点清单、验收标准、风险与约束、设计决定、依赖与协同）已归档至 [ARCHIVED_FEATURES.md §äºåå­ F-99 Ctrl+C/B 即时中断响应优化](./ARCHIVED_FEATURES.md#二十六f-99-ctrlcb-即时中断响应优化)。

### 2.16 Dreaming 后台记忆整合系统（F-100 🔄）

**状态**: 🔄 进行中（主体已落地，Phase B 待补） | **优先级**: P2 | **登记日期**: 2026-06-17 | **完成日期**: 2026-06-18

**目标**: 从上游 fork 移植 dreaming 子系统（`DreamTask` 后台探索 + `autoDream` 自动 consolidate auto-memory + `/dream` slash skill），让 clawcodex 拥有"空闲时自我整合记忆"的能力。后续章节"背景 / 现状 / 方案 / 任务"对应 `PROGRESS.md` 十三节。

#### 背景

上游 `claude-code-best` 在 `KAIROS` / `KAIROS_DREAM` 特性开关下提供完整的 dreaming：

- `src/services/autoDream/` — 后台 consolidate 服务（`autoDream.ts` 调度、`config.ts` 配置、`consolidationLock.ts` 文件锁、`consolidationPrompt.ts` 总结 prompt）
- `src/tasks/DreamTask/DreamTask.ts` — Dream 任务实现
- `src/skills/bundled/dream.ts` — `/dream` slash skill
- `src/components/tasks/DreamDetailDialog.tsx` — TUI 详情对话框
- `docs/features/auto-dream.md` + `docs/features/kairos.md` — 设计文档

#### 现状（clawcodex 侧）

clawcodex 已在多处为 dreaming 预留"字面量桩"，但**没有运行实现**：

| 位置 | 现状 | 缺口 |
|------|------|------|
| `src/tasks_core.py:38` | `TaskType` literal 已声明 `"dream"` | 无对应 Task 类 |
| `src/tasks_core.py:75` | `_TASK_ID_PREFIXES["dream"] = "d"` | 无 |
| `src/task_registry.py:184` | 注释标记 Dream 为 out-of-scope | 无 |
| `tests/tasks/test_task_registry.py:202` | `assert get_task_by_type("dream") is None` | 需解锁 |
| `extensions/skills_ext/bundles.py:36` | bundle 列表里有 `"dream"` | 无 skill 实现（引用悬空） |
| `clawcodex_ext/cron_system/runtime.py:126` | 文档提及 dream 为 permanent cron | 未注册 |
| `clawcodex_ext/cron_system/tools.py:82` | dream 列入免清理名单 | 未注册 |

#### 方案

1. **`DreamTask` 实现**（`src/tasks/dream/dream_task.py`）
   - 继承 `LocalAgentTask` 模式
   - 调度：周期 24h + 立即触发入口
   - 行为：扫描未关联 / 低信号 auto-memory → 调 LLM 总结 → 写回索引
2. **`autoDream` 服务**（`clawcodex_ext/dreaming/service.py`）
   - 周期 loop + 错误隔离（单次失败不影响下次）
   - 复用 `src/memory/` 已有的 auto-memory 读写 API
3. **`consolidationLock`**（`clawcodex_ext/dreaming/lock.py`）
   - 基于 `clawcodex_ext/cron_system/dist_lock.py`，TTL 30min
   - 防止多进程同时 consolidate
4. **`/dream` slash skill**（`extensions/skills_ext/builtin/dream.py`）
   - 替换 `bundles.py:36` 悬空引用
   - 支持子命令：`/dream run` / `/dream status` / `/dream once`
5. **永久 cron 集成**（`clawcodex_ext/cron_system/builtin_tasks.py`）
   - 注册 `dream` / `catch-up` / `morning-checkin` 三件套
   - 启动时若未注册自动补齐

#### 任务拆分

| 任务 | 预计工时 | 依赖 |
|------|:--------:|------|
| 100.1 `DreamTask` 类 | 1天 | — |
| 100.2 `autoDream` 服务主循环 | 1天 | 100.1 |
| 100.3 `consolidationLock` | 0.5天 | 100.2 |
| 100.4 `/dream` slash skill | 0.5天 | 100.1 |
| 100.5 永久 cron 集成 | 0.5天 | 100.2 |
| 100.6 解锁 test 不变量 | 0.25天 | 100.1 |
| 100.7 测试 + 门禁 | 1天 | 全部 |

合计：4.75 天（约 1 人周）

#### 风险与缓解

- **LLM 成本**：默认 24h 周期 + `dreaming.interval_hours` 可配
- **写回竞态**：复用 `extensions/orchestrator/workspace.py` 的 workspace lock
- **特性开关**：不引入 `KAIROS` / `KAIROS_DREAM`，直接实现
- **TUI 暂缓**：本期不做 `DreamDetailDialog`，先 CLI + skill

#### 依赖

| 依赖 | 类型 |
|------|------|
| `src/tasks_core.py` 已有 literal | 内置 |
| `clawcodex_ext/cron_system/dist_lock.py` | 复用 |
| `src/memory/`（auto-memory） | 复用 |
| `extensions/orchestrator/workspace.py` lock | 复用 |
| `/mnt/c/Workspace/claude-code-best/...` | 参考实现 |

#### 实施落地（2026-06-18）

主体已实现（100.1~100.7 七子特性全 ✅，Phase A/C/D/E 已完成）。完整子特性状态、阶段进度、测试覆盖与剩余工作（Phase B 30min TTL 增强）见 [`docs/PROGRESS.md` 十三节](./PROGRESS.md#十三dreaming-后台记忆整合系统f-100)。

| 类别 | 落地位置 |
|------|---------|
| DreamTask | `src/tasks/dream/dream_task.py` |
| autoDream 服务 | `clawcodex_ext/dreaming/service.py`（runner 工厂可注入） |
| consolidationLock | `clawcodex_ext/dreaming/lock.py`（PID + mtime 锁；30min TTL 增强待 Phase B） |
| `/dream` slash skill | `extensions/skills_ext/bundled/dream.py`（`run`/`once`/`status`/`help` 子命令） |
| 永久 cron 集成 | `clawcodex_ext/dreaming/cron_integration.py`（`DREAM_DEFAULT_CRON="0 3 * * *"` + well-known task_id=`dream`） |
| 测试 | `tests/dreaming/` 106 单测 + 6 E2E + `tests/stability_gate/` 12 门禁 |

---
### 2.18 Agent Loop Hook 扩展点增强（F-102 🔄）

**状态**: 🔄 进行中（P102-A~E 全部实现，待 mypy 严格模式验证） | **优先级**: P1 | **登记日期**: 2026-06-22

**目标**: 填补 agent loop（`query()`）中 5 个 hook 扩展点缺口，为 F-68 Feature Gate / F-70 Plugin 系统提供基础设施，使新特性无需修改 `query()` 函数体即可注入自定义逻辑。

#### 背景

对 `clawcodex_ext/query/query.py` 的代码审计发现，agent loop 虽然已有 7 类 18 个扩展点（压缩流水线、ProgressSink、StopHooks、TokenBudget、ToolContext、F-45 审计、F-75 统计），但均为**命名参数式**硬编码扩展，缺少统一的、可注册的钩子注册表。新特性（如 F-69 Budget Mode 在 pre-LLM 注入提示）需要直接修改 `query()` 函数体。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工时 |
|:----:|--------|------|:----:|:--------:|
| P102-A | **pre-LLM 通用扩展钩子** | 在 `query()` Phase 0（压缩流水线）之后、`_call_model_sync` 之前添加 `call_hooks("pre_llm", messages, system_prompt) -> (messages, system_prompt)` 回调链 | ✅ 已实现 | 2-3天 |
| P102-B | **post-LLM 恢复策略注册表** | 将 B.1/B.2 阶段的 `if/elif` 硬编码恢复链（max_tokens/PTL/media_size）改为注册式 `RecoveryStrategy` 列表 | ✅ 已实现 | 3-5天 |
| P102-C | **outbox 类型化** | `ToolContext.outbox` 从 `list[dict]` 改为 `list[OutboxEvent]` Union dataclass | ✅ 已实现 | 1-2天 |
| P102-D | **formal plugin hook registry** | 新增 `register_loop_hook(name, fn, phase)` API，统一管理 pre_llm / post_llm / pre_tool / post_tool / on_turn_end 等阶段的钩子注册与去注册 | ✅ 已实现 | 2-3天 |
| P102-E | **逐 turn 回调注册** | `QueryState` 添加 `on_turn_start` / `on_turn_end` callback 列表 | ✅ 已实现 | 1-2天 |

#### 影响范围

| 依赖特性 | 关系 | 说明 |
|---------|------|------|
| F-68 Feature Gate | **消费者** | P102-A pre-LLM 钩子是条件启用的注入点 |
| F-69 Budget Mode | **消费者** | P102-A pre-LLM 钩子用于注入节俭提示 |
| F-70 Plugin 系统 | **前置依赖** | P102-D formal registry 是插件注册机制的基础 |
| F-84 Context Collapse | **协同** | P102-B 恢复策略注册表可替代当前 CollapseEngine 特殊参数 |

#### 实现文件清单

**新建文件**

| 文件 | 子特性 | 说明 |
|------|:------:|------|
| `clawcodex_ext/query/hook_registry.py` | P102-D | `LoopHookPhase` / `LoopHook` / `register_loop_hook` / `call_hooks` / `clear_hooks` |
| `clawcodex_ext/query/outbox_types.py` | P102-C | `CronPromptEvent` / `CronMissedEvent` / `GenericOutboxEvent` / `outbox_event_from_dict` |
| `clawcodex_ext/query/recovery_strategies.py` | P102-B | `RecoveryContext` / `RecoveryStrategy` / 6 个内置策略 + 注册/注销/查询 API |
| `tests/clawcodex_ext/query/test_hook_registry.py` | P102-D | register/unregister/call_hooks/priority/clear/exception 隔离 |
| `tests/clawcodex_ext/query/test_outbox_types.py` | P102-C | Event dataclass / getitem / contains / from_dict / 类型标注验证 |
| `tests/clawcodex_ext/query/test_recovery_strategies.py` | P102-B | 内置策略注册/优先级/escalate/fallback/条件判断 |
| `docs/F-102-IMPLEMENTATION.md` | — | 实现总结（归档用） |

**修改文件**

| 文件 | 子特性 | 改动说明 |
|------|:------:|---------|
| `clawcodex_ext/query/query.py` | P102-A~E | 注入 5 处 hook（pre_llm / post_llm / pre_tool / post_tool / on_turn_end）+ 替换恢复链为注册式策略 |
| `clawcodex_ext/query/transitions.py` | P102-E | `QueryState` 添加 `on_turn_start_callbacks` / `on_turn_end_callbacks` |
| `clawcodex_ext/tool_system/context.py` | P102-C | `outbox: list[dict]` → `list[OutboxEvent]` |
| `clawcodex_ext/cron_system/runtime.py` | P102-C | `on_fire` / `on_fire_task` / `on_missed` 改用 `CronPromptEvent` / `CronMissedEvent` |
| `clawcodex_ext/repl/core.py` | P102-C | `_drain_cron_outbox` 兼容 `hasattr(entry, "get")` + legacy dict fallback |
| `clawcodex_ext/command_system/builtins.py` | P102-C | `_append_cron_outbox` 改用 `CronPromptEvent` |
| `clawcodex_ext/query/agent_loop_compat.py` | P102-C | 读取兼容 `hasattr(entry, "get")` |
| `tool_system/tools/ask_user_question.py` | P102-C | `GenericOutboxEvent.from_dict` |
| `tool_system/tools/brief.py` | P102-C | `GenericOutboxEvent.from_dict` |
| `tool_system/tools/send_user_message.py` | P102-C | `GenericOutboxEvent.from_dict` |
| `tool_system/tools/structured_output.py` | P102-C | `GenericOutboxEvent.from_dict` |
| `tool_system/tools/ask_issue_author.py` | P102-C | `GenericOutboxEvent.from_dict` |

#### 核心注入点（query.py）

| 注入位置 | Phase | 说明 |
|---------|-------|------|
| `while True` 顶部 | `on_turn_start` | P102-E: 调用 `state.on_turn_start_callbacks` |
| Phase 0 压缩流水线之后 | `pre_llm` | P102-A: `call_hooks("pre_llm", messages, system_prompt)` → 修改后传给 `_call_model_sync` |
| LLM 响应返回后 | `post_llm` | P102-D: `call_hooks("post_llm", assistant_messages, tool_use_blocks)` → 修改后进入工具执行或恢复 |
| no-follow-up 分支 | recovery | P102-B: 将 `max_tokens` / `PTL` / `media_size` 硬编码 `if/elif/continue` 链替换为 `find_recovery_strategies` + 策略执行 |
| `_run_tools_partitioned` 之前 | `pre_tool` | P102-D: `call_hooks("pre_tool", tool_use_blocks)` → 修改后执行工具 |
| `_run_tools_partitioned` 之后 | `post_tool` | P102-D: `call_hooks("post_tool", tool_results)` → 修改后 yield |
| state 重建之前 | `on_turn_end` | P102-E: 调用 `state.on_turn_end_callbacks` + `call_hooks("on_turn_end", state)` |

#### 验收标准

| # | 验收项 | 状态 |
|:--:|--------|:----:|
| 1 | `register_loop_hook("pre_llm", fn)` 注册后，`query()` 每次 LLM 调用前调用 `fn(messages, system_prompt)` | ✅ 实现 |
| 2 | `register_recovery_strategy(err_type, fn)` 注册后，API 返回对应错误时优先调用注册的恢复策略 | ✅ 实现 |
| 3 | `ToolContext.outbox` 元素有类型标注，`mypy --strict` 通过 | 🔄 实现待验证（无 mypy 运行环境） |
| 4 | 现有 245/245 稳定性门禁 + 全部 orchestrator 测试通过 | 🔄 待验证（无 pytest 运行环境） |

#### 依赖与协同

| 依赖 | 类型 | 说明 |
|------|------|------|
| `clawcodex_ext/query/query.py` | 核心文件 | 5 处 hook 注入点 + 恢复链替换均在 `query()` 函数中 |
| `clawcodex_ext/query/hook_registry.py` | 新建文件 | P102-D 的公共注册表，F-68 / F-69 / F-70 的注入点 |
| `clawcodex_ext/query/outbox_types.py` | 新建文件 | P102-C 类型化基础设施，被 `tool_system/context.py` 导入 |
| `clawcodex_ext/query/recovery_strategies.py` | 新建文件 | P102-B 恢复策略注册表，内置 6 个策略覆盖 max_tokens/PTL/media_size |
| `clawcodex_ext/tool_system/context.py` | 修改文件 | `outbox` 字段类型从 `list[dict]` 改为 `list[OutboxEvent]` |
| `clawcodex_ext/cron_system/runtime.py` | 消费者 | cron outbox drain 适配 `CronPromptEvent` / `CronMissedEvent` |
| `clawcodex_ext/repl/core.py` | 消费者 | `_drain_cron_outbox` 兼容 dataclass 读取 |

#### 测试

新建 3 个测试文件，覆盖 hook_registry / outbox_types / recovery_strategies 的核心 API：

| 文件 | 覆盖内容 |
|------|---------|
| `tests/clawcodex_ext/query/test_hook_registry.py` | register/unregister/call_hooks/priority/clear/exception 隔离 |
| `tests/clawcodex_ext/query/test_outbox_types.py` | CronPromptEvent/CronMissedEvent/GenericOutboxEvent/getitem/contains/from_dict/ToolContext 类型标注 |
| `tests/clawcodex_ext/query/test_recovery_strategies.py` | 内置策略注册/优先级/escalate/fallback/条件判断 |

所有测试通过 Python 运行时验证（`py_compile` + 手动 assert）。

#### 后续验证项

1. **mypy `--strict` 验证**：在 `clawcodex_ext/query/` 和 `clawcodex_ext/tool_system/` 上运行 `mypy --strict`，确认无类型错误
2. **稳定性门禁全量运行**：运行 `pytest tests/ -q`，确认 245/245 通过
3. **集成测试**：注册一个 dummy `pre_llm` hook 和 recovery strategy，验证 `query()` loop 正确调用


### 2.19 PowerShell 支持增强（F-107 📋）

**状态**: 📋 规划中 | **优先级**: P2 | **登记日期**: 2026-06-23

**目标**: 让 ClawCodex 的 BashTool 能够感知并适配 Windows 原生 shell（PowerShell），涵盖工具级 shell 选择、PowerShell 兼容的进程启动与 CWD 追踪、PowerShell 命令集分类/安全/只读/语义适配，以及 Windows 平台自动检测与优雅降级。

#### 当前基线

| 组件 | 当前行为 | 文件 |
|------|---------|------|
| 进程启动 | 硬编码 `["bash", "-lc", wrapped]` | `clawcodex_ext/tool_system/tools/bash/bash_tool.py:349` |
| 后台执行 | 硬编码 `["bash", "-lc", wrapped]` | `clawcodex_ext/tool_system/tools/bash/background.py:76` |
| 工具名 | `BASH_TOOL_NAME = "Bash"` | `clawcodex_ext/tool_system/tools/bash/bash_tool.py:199,608` |
| CWD 追踪 | `pwd > {path}` + `{ cmd; }; __rc=$?` 包装 | `bash_tool.py:338-339` |
| 搜索分类 | 仅 POSIX 命令集（`grep`/`find`/`cat`/`ls`） | `search_classification.py` |
| 只读验证 | 仅 POSIX 命令集 | `read_only_validation.py` |
| 命令语义 | 仅 POSIX 退出码解释（`grep` RC=1=无匹配） | `command_semantics.py` |
| 安全分析 | `tree-sitter-bash` AST 解析器 | `permissions/bash_security.py` |
| 破坏性警告 | bash 特有正则模式 | `destructive_warnings.py` |
| 工具 Prompt | bash 语法范例、bash 文档 | `prompt.py` |

**已有基础设施**：Hook 系统已有 `shell_invocation.py` 中的 `build_powershell_args` / `find_powershell_path`，但仅适用于 hook 执行，BashTool 完全未接入。

#### 子特性分解

| # | 子特性 | 改动文件 | 改动量 | 风险 | 预计工时 |
|:-:|--------|----------|:------:|:----:|:--------:|
| **A** | 工具 schema 扩展 + shell 检测 | `bash_tool.py` | ~80 行 | 低 | 0.5d |
| **B** | 进程启动层适配（argv 生成 + CWD 包装） | `bash_tool.py`, `background.py` | ~120 行 | 低 | 1d |
| **C** | 工具 Prompt 适配 | `prompt.py` | ~60 行 | 低 | 0.5d |
| **D** | 命令分类适配（PowerShell 命令集） | `search_classification.py`, `read_only_validation.py` | ~120 行 | 中 | 1d |
| **E** | 命令语义 & 退出码适配 | `command_semantics.py` | ~40 行 | 低 | 0.5d |
| **F** | PowerShell 安全分析 | `bash_security.py` + 新建 `powershell_parser/` | ~200 行 | 中 | 1.5d |
| **G** | 技能系统 shell 传播 | `skill.py`, `runtime_substitution.py` | ~30 行 | 中 | 0.5d |
| **H** | Shell 基础设施统一（hooks + BashTool 共用） | 新建 `utils/shell_resolver.py` | ~80 行 | 低 | 0.5d |

**预计总工时**: 6-8 天

#### 详细设计

##### P107-A — 工具 schema 扩展 + shell 检测

在 `BashTool.input_schema.properties` 中新增可选字段：

```python
"shell": {
    "type": "string",
    "enum": ["bash", "powershell", "auto"],
    "description": "Shell to use for execution. 'auto' detects platform default.",
    "default": "auto",
}
```

添加检测函数 `_resolve_shell(shell_param, command)` -> `(shell_kind, argv_list)`，在 `_bash_call` 开头 resolve。

##### P107-B — 进程启动层适配

`_build_shell_argv(shell, wrapped_command)`:
- `shell=="powershell"` → `[pwsh_path, "-NoProfile", "-NonInteractive", "-Command", wrapped_command]`
- 默认 → `["bash", "-lc", wrapped_command]`

CWD 追踪包装：
- `shell=="powershell"` → `{command}; $__rc = $LASTEXITCODE; (Get-Location).Path | Out-File -Encoding UTF8 {path}; exit $__rc`
- 默认 → 当前 `{ cmd }); __rc=$?; pwd > {path} 2>/dev/null; exit $__rc`

后台 CWD 包装同理。

##### P107-C — 工具 Prompt 适配

在 `get_bash_prompt()` 中标注支持 `shell` 参数，添加 PowerShell 路径写法说明（反斜杠、引号差异）、`$LASTEXITCODE` vs `$?` 提示。

##### P107-D — 命令分类适配

`search_classification.py` 新增 PowerShell 等效命令集：
- **搜索**: `Select-String`/`sls`、`Get-ChildItem`/`gci`、`Get-Command`/`gcm`
- **读取**: `Get-Content`/`gc`/`type`、`Get-Item`/`gi`、`Measure-Object`/`measure`
- **静默**: `New-Item`/`ni`/`md`、`Remove-Item`/`ri`/`rm`/`del`、`Move-Item`/`mi`、`Copy-Item`/`ci`/`cp`、`Set-Content`/`sc`、`Set-Location`/`sl`/`cd`

分类函数根据 shell 参数选择对应的命令集。只读验证同理。

##### P107-E — 命令语义适配

PowerShell 退出码语义不同：原生 cmdlet 不设 `$LASTEXITCODE`（除非显式 exit），外部程序才用退出码。
- `Select-String` → 0=found, 1=not_found, 2=error（与 grep 同语义）
- 默认：`$LASTEXITCODE` 0=成功，非 0=失败

##### P107-F — PowerShell 安全分析

不引入 `tree-sitter-powershell`（社区版本不稳定），采用启发式正则 + `Get-Command` 探测：

| bash 级别 | PowerShell 等效 |
|-----------|----------------|
| safe (`echo`, `true`) | `Write-Host`, `$true`, 纯管道 |
| read_only (`cat`, `grep`) | `Get-Content`, `Select-String`（纯读 cmdlet） |
| write (`sed -i`, `>` 重定向) | `Set-Content`, `Out-File`, `Add-Content` |
| destructive (`rm -rf`, `DROP TABLE`) | `Remove-Item -Recurse -Force`, `Clear-*`, `Invoke-SqlCmd` |
| dangerous (`sudo`, `eval`) | `Invoke-Expression`/`iex`, `Start-Process -Verb RunAs` |

##### P107-G — 技能系统 shell 传播

技能 markdown 已能声明 `shell: powershell` frontmatter，但 `_make_shell_executor` 创建 BashTool 调用时**未传播 shell 类型**。
改动：`_make_shell_executor` 接受 `shell: str | None` 参数 → `_exec` 闭包中调用 `BashTool.call({"command": c, "shell": shell}, ...)`。

##### P107-H — Shell 基础设施统一

将 `build_powershell_args()` / `find_powershell_path()` 从 `clawcodex_ext/hooks/shell_invocation.py` 提取到 `clawcodex_ext/utils/shell_resolver.py`，hooks 和 BashTool 都引用同一份实现。添加 `resolve_shell(shell_type) -> (shell_kind, argv_fn, str)` 统一入口。

#### 验收标准

| # | 验收项 | 验收方式 |
|:-:|--------|---------|
| 1 | `BashTool.call({"command":"...", "shell":"powershell"})` 调用 pwsh 执行 | 单元测试 + Windows 手动验证 |
| 2 | `BashTool.call({"command":"...", "shell":"auto"})` 在 win32 上自动选择 PowerShell | 单元测试 mock `sys.platform` |
| 3 | PowerShell 纯 cmdlet pipeline（`Get-ChildItem \| Select-String "txt"`）被正确分类为 search/read | `test_search_classification.py` |
| 4 | `Select-String` RC=1 正确解释为"无匹配"而非"失败" | `test_command_semantics.py` |
| 5 | `Remove-Item -Recurse -Force` 被标记为 destructive | `test_bash_security.py` |
| 6 | 技能 frontmatter `shell: powershell` 实际生效 | 集成测试 |
| 7 | hooks + BashTool 共用 `shell_resolver.py`，`find_powershell_path()` 单点维护 | 导入测试 |
| 8 | 稳定性门禁全量通过 | `pytest tests/stability_gate/ -q --tb=short -x` |

#### 不纳入范围

- **`cmd.exe` 支持**：保留 README 中原生 cmd.exe 不支持的声明
- **PowerShell 7 vs Windows PowerShell 5.1 行为差异**：统一通过 `pwsh`（PS 6+）路径，Windows PowerShell 仅作为 fallback
- **PowerShell 特有的 `-Encoding`/`-ErrorAction` 参数自动适配**：由 agent 在 prompt 指导下自行书写
- **PowerShell 工作流（PSWorkflow）**、**PowerShell DSC**：不在 AI coding agent 场景内

#### 风险与约束

| 风险 | 等级 | 缓解措施 |
|------|:----:|---------|
| Windows CI 无 runner | 中 | 本地手动验证；`sys.platform` mock 覆盖单元测试 |
| `pwsh` 在 Windows Server Core 镜像上不可用 | 低 | `find_powershell_path()` 返回 None 时报清晰错误 |
| PowerShell `$LASTEXITCODE` 行为复杂（原生 cmdlet vs 外部命令） | 中 | 在 prompt 中强调行为差异，语义层仅覆盖明确的 cmdlet |
| CWD 追踪在 PowerShell 路径含空格/Unicode 时的可靠性 | 低 | 使用 `Out-File -Encoding UTF8` + 与 bash 路径相同的 OSError 容错 |

#### 已拟定的设计决定

1. **工具不重命名** — 保持 `BashTool` / `Bash` 作为向后兼容名，因为上游 TS 也是 `BashTool`。在 prompt 和注释中说明 shell 参数可切换解释器。
2. **`"auto"` 检测规则** — 仅当 `sys.platform == "win32"` 且 `find_powershell_path()` 返回非 None 时默认 PowerShell；否则默认 bash。
3. **CWD 追踪优雅降级** — 若 PowerShell 的 CWD 读取失败，工具不失败，仅不更新 context.cwd——与 bash 路径的 OSError 处理一致。
4. **不引入 `tree-sitter-powershell`** — 当前 `tree-sitter-bash` 是 ~1,500 行替代方案的结果。PowerShell 语法更复杂（社区版本不稳定），安全分析用启发式正则 + `Get-Command` 探测足够。

#### 依赖与协同

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-48（`src/` 解耦） | 软约束 | P107-H 的 `shell_resolver.py` 落在 `clawcodex_ext/utils/` 中，不侵入 `src/` |
| F-43（CLI Provider 命令） | 可选 | 若添加 `/shell` 运行时命令切换默认 shell，依赖 F-43 的 `RuntimeContext` 框架 |
| 现有 `clawcodex_ext/hooks/shell_invocation.py` | 代码源 | P107-H 从中提取通用逻辑到 `shell_resolver.py`，保留 hooks 侧导入兼容 |

#### 实施建议顺序

```
Phase 1 (1-2d): [H] 基础设施统一 ──→ [A] schema + shell 检测 ──→ [B] 进程启动适配
  打通端到端执行路径

Phase 2 (2-3d): [C] Prompt 适配 ──→ [D] 命令分类 ──→ [E] 语义适配
  完善模型侧使用体验

Phase 3 (2-3d): [F] 安全分析 ──→ [G] 技能传播
  补全安全和技能集成
```

#### 测试

| 文件 | 覆盖内容 |
|------|---------|
| `tests/tool_system/tools/bash/test_shell_selection.py` | P107-A/B: shell 参数解析、argv 生成、CWD 包装 |
| `tests/tool_system/tools/bash/test_powershell_classification.py` | P107-D: PowerShell 命令集分类 |
| `tests/permissions/test_powershell_security.py` | P107-F: PowerShell 安全分析 |
| `tests/tool_system/tools/skill/test_shell_propagation.py` | P107-G: 技能 shell 传播 |
| `tests/utils/test_shell_resolver.py` | P107-H: 统一入口 |

#### 修改文件

| 文件 | 子特性 | 改动说明 |
|------|:------:|---------|
| `clawcodex_ext/tool_system/tools/bash/bash_tool.py` | P107-A/B | 添加 `shell` schema 字段 + `_resolve_shell` + `_build_shell_argv` + `_build_cwd_wrapper` |
| `clawcodex_ext/tool_system/tools/bash/background.py` | P107-B | `spawn_background_bash` 接受 `shell` 参数，改用 `_build_bg_wrapper` |
| `clawcodex_ext/tool_system/tools/bash/prompt.py` | P107-C | 添加 shell 选择指导和 PowerShell 语法提示 |
| `clawcodex_ext/tool_system/tools/bash/search_classification.py` | P107-D | 新增 `PWSH_SEARCH_COMMANDS` / `PWSH_READ_COMMANDS` / `PWSH_SILENT_COMMANDS` |
| `clawcodex_ext/tool_system/tools/bash/read_only_validation.py` | P107-D | 新增 `PWSH_READONLY_COMMANDS` |
| `clawcodex_ext/tool_system/tools/bash/command_semantics.py` | P107-E | `interpret_command_result` 接受 `shell` 参数，新增 `PWSH_COMMAND_SEMANTICS` |
| `clawcodex_ext/permissions/bash_security.py` | P107-F | `check_bash_command_safety` 接受 `shell` 参数，新增 PowerShell 安全分级映射 |
| `clawcodex_ext/permissions/powershell_security.py` | P107-F | 新建：PowerShell 命令安全分析（启发式正则） |
| `clawcodex_ext/tool_system/tools/skill.py` | P107-G | `_make_shell_executor` 接受并传播 `shell` 参数 |
| `clawcodex_ext/utils/shell_resolver.py` | P107-H | 新建：`build_powershell_args` / `find_powershell_path` / `resolve_shell` 统一入口 |
| `clawcodex_ext/hooks/shell_invocation.py` | P107-H | 降级为 `shell_resolver.py` 的 re-export 或删除 |


### 2.20 Freeze Detection & Auto-Recovery（F-108 📋）

**状态**: 📋 规划中 | **优先级**: P0 | **登记日期**: 2026-06-23

**目标**: 系统性解决 clawcodex 偶发软件卡死与 LLM 对话卡死问题。全链路代码审计发现 8 个卡死风险点（2 CRITICAL + 3 HIGH + 2 MEDIUM + 1 LOW），采用四层混合方案（Layer 0 快速修复 + Layer 1 冻结检测 + Layer 2 硬超时 + Layer 3 自动恢复 + Layer 4 诊断命令），确保用户在卡死发生后 < 30s 内自动恢复或收到明确诊断。

**详细设计**: `docs/PROGRESS.md §十八 F-108 Freeze Detection & Auto-Recovery`

#### 当前基线（卡死风险点审计）

经对 `clawcodex_ext/agent/run_agent.py`、`clawcodex_ext/entrypoints/headless.py`、`clawcodex_ext/tui/agent_bridge.py`、`clawcodex_ext/query/query.py`、`extensions/api/query.py`、`clawcodex_ext/providers/anthropic_provider.py`、`src/utils/stream_watchdog.py` 全链路代码审计，发现以下 8 个卡死风险点：

| # | 卡死点 | 位置 | 严重度 | 现有防护 | 根因 |
|---|--------|------|:------:|----------|------|
| 1 | **API 流式响应无任何 chunk 到达** | `_call_model_sync` → `provider.chat_stream_response()` | **CRITICAL** | ✅ StreamWatchdog (90s) + F-99 read_timeout (5s) | LLM 服务端卡死/网络断开 |
| 2 | **TUI 权限弹窗不响应 → 工作线程永久阻塞** | `AgentBridge._permission_handler` → `done.wait()` | **CRITICAL** | ❌ 无超时 | UI bug / 模态弹窗未渲染 |
| 3 | **AskUserQuestion 弹窗不响应 → 同上** | `AgentBridge._ask_user_handler` → `done.wait()` | **CRITICAL** | ❌ 无超时 | UI bug / 模态弹窗未渲染 |
| 4 | **Agent loop 转永久死循环（LLM 不停调用工具）** | `query()` while-true 循环 | **HIGH** | ❌ 只有 max_turns 计次防护 | LLM 行为失控 |
| 5 | **headless future 永远不完成** | `QueryRunner.stream()` → `future = run_in_executor()` | **HIGH** | ❌ 无硬超时（仅有 30s heartbeat） | 工作线程死锁/挂起 |
| 6 | **Bash/Edit 工具执行挂起（子进程永久等待）** | tool_system tools/ | **HIGH** | ❌ 无工具级超时 | 子进程 I/O 阻塞 |
| 7 | **TUI 主渲染线程死锁** | Textual 事件循环 | **MEDIUM** | ❌ 无 UI 级 watchdog | `_post()` 队列满/竞争条件 |
| 8 | **conversation persistence 阻塞** | `session.save_transcript()` + `add_message()` | **LOW** | ❌ 有 try/except 但 I/O 可能挂住 | 磁盘故障/NFS 挂住 |

#### 方案架构：四层混合方案（Layer 0 ~ Layer 4）

```
      ┌─────────────────────────────────────────────────┐
      │                 Layer 4: 诊断命令                │
      │     freeze-report / diag viewer / SIGUSR1 dump   │
      ├─────────────────────────────────────────────────┤
      │               Layer 3: 自动恢复                   │
      │  permission 超时→auto-deny │ tool 超时→cancel      │
      │  turn 超时→abort │ agent 超时→保存已做完部分       │
      ├─────────────────────────────────────────────────┤
      │               Layer 2: 硬超时防护                  │
      │  CLAWCODEX_AGENT_LOOP_TIMEOUT (600s)             │
      │  CLAWCODEX_TURN_TIMEOUT (300s)                   │
      │  CLAWCODEX_TOOL_TIMEOUT (120s)                   │
      │  CLAWCODEX_PERMISSION_TIMEOUT (30s)              │
      │  CLAWCODEX_FREEZE_THRESHOLD (60s)                │
      ├─────────────────────────────────────────────────┤
      │             Layer 1: 冻结检测 (FreezeDetector)     │
      │  on_event/on_text_chunk 打 heartbeat              │
      │  watchdog 线程每 10s 检查 → 超时 60s → dump 线程栈  │
      ├─────────────────────────────────────────────────┤
      │             Layer 0: 快速修复（立即生效）           │
      │  P108-A: done.wait(timeout=30) → auto-deny        │
      │  P108-B: asyncio.wait_for(future, 300)            │
      │  P108-C: asyncio.wait_for(tool_exec, 120)          │
      └─────────────────────────────────────────────────┘
```

#### 子特性分解

| # | 子特性 | 改动文件 | 改动量 | 风险 | 预计工时 |
|:-:|--------|----------|:------:|:----:|:--------:|
| **A** | Permission/AskUser `done.wait()` 超时 → auto-deny | `clawcodex_ext/tui/agent_bridge.py` | ~20 行 | 低 | 0.5d |
| **B** | headless query future `asyncio.wait_for(300)` | `extensions/api/query.py` | ~10 行 | 低 | 0.5d |
| **C** | Tool 执行 `asyncio.wait_for(120)` | `clawcodex_ext/tool_system/` | ~50 行 | 中 | 1d |
| **D** | FreezeDetector 冻结检测 + thread stack dump | 新建 `clawcodex_ext/diagnostics/freeze_detector.py` | ~200 行 | 低 | 1.5d |
| **E** | 超时配置 schema 扩展（env + AgentConfig） | `extensions/orchestrator/config/schema.py` + `clawcodex_ext/settings/` | ~80 行 | 低 | 1d |
| **F** | Agent loop / turn / tool 三层硬超时贯穿 | `clawcodex_ext/query/query.py` + `_call_model_sync` | ~150 行 | 中 | 1.5d |
| **G** | 自动恢复策略实现（超时→cancel→继续） | `clawcodex_ext/tui/agent_bridge.py` + `extensions/api/query.py` | ~100 行 | 中 | 1.5d |
| **H** | freeze-report CLI 子命令 + diag viewer | 新建 CLI 命令 | ~150 行 | 低 | 1d |

**预计总工时**: 7 天

#### 详细设计

##### P108-A — Permission/AskUser 超时（Layer 0，#2 #3）

修改 `clawcodex_ext/tui/agent_bridge.py` 中 `_permission_handler` 和 `_ask_user_handler` 的 `done.wait()` 调用，添加 `timeout=30.0` 参数。超时后：

```python
# _permission_handler: 超时 → auto-deny
done.wait(timeout=30.0)
if not done.is_set():
    outcome["allowed"] = False
    outcome["enable"] = False  # 不记住此决定

# _ask_user_handler: 超时 → 返回空 dict
done.wait(timeout=30.0)
if not done.is_set():
    outcome["answers"] = {}
```

**恢复行为**: 当前 turn 继续执行（工具被拒绝不会中断 agent loop），用户无明显感知。

##### P108-B — Headless Query Future 超时（Layer 0，#5）

修改 `extensions/api/query.py` 中 `QueryRunner.stream()` 的 `await future` 调用：

```python
exit_code = await asyncio.wait_for(future, timeout=300.0)
```

超时触发 `TimeoutError` → `SessionComplete(reason="timeout")` → 下游 `AgentRunner.run()` 正常退出，不丢失已完成的 turn 结果。

##### P108-C — Tool 执行超时（Layer 0，#6）

在 `StreamingToolExecutor` 或等效工具调度路径中，用 `asyncio.wait_for` 包裹工具异步调用，默认 120s。超时触发 `CancelledError` → agent loop 继续下一 turn。

```python
try:
    result = await asyncio.wait_for(
        execute_tool(tool_call, context),
        timeout=_resolve_tool_timeout(tool_call.name),
    )
except asyncio.TimeoutError:
    result = ToolResult(is_error=True, error=f"Tool {tool_call.name} timed out after 120s")
```

##### P108-D — FreezeDetector 冻结检测（Layer 1）

新建 `clawcodex_ext/diagnostics/freeze_detector.py`，作为解耦扩展：

```python
class FreezeDetector:
    """监控 agent loop 活动，检测到冻结时 dump 诊断信息。

    机制：
    - on_event / on_text_chunk 回调时调用 .heartbeat() 打时间戳
    - 后台 watchdog 线程每 10s 检查 .check()
    - 连续 60s 无心跳 → dump threading.enumerate() 全线程栈 → 写入 debug_log.ndjson
    """

    def __init__(self, threshold: float = 60.0, check_interval: float = 10.0):
        self._threshold = threshold
        self._check_interval = check_interval
        self._last_heartbeat: float = time.monotonic()
        self._lock = threading.Lock()
        self._watchdog: threading.Thread | None = None

    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic()

    def check(self) -> bool:
        """返回 True 表示检测到冻结且已 dump 诊断信息。"""
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed >= self._threshold:
            stacks = self._dump_thread_stacks()
            # 写入 debug_log.ndjson
            append_debug_event(None, "freeze_detected",
                elapsed_seconds=round(elapsed, 1),
                thread_stacks=stacks,
            )
            return True
        return False

    def _dump_thread_stacks(self) -> list[dict]:
        """获取所有线程的当前栈帧。"""
        result = []
        for tid, frame in sys._current_frames().items():
            stack = "".join(traceback.format_stack(frame))
            result.append({"thread_id": tid, "stack": stack})
        return result

    def start(self) -> None:
        if self._watchdog is not None:
            return
        self._watchdog = threading.Thread(target=self._run, daemon=True, name="freeze-detector")
        self._watchdog.start()

    def _run(self) -> None:
        while True:
            time.sleep(self._check_interval)
            self.check()
```

**注入方式**: 通过 `on_event` / `on_text_chunk` / `on_thinking_chunk` 钩子注入，不对 `src/` 做任何修改。`AgentBridge._run_agent_in_thread` 中创建 detector 实例并传给 `run_query_as_agent_loop`。

**效果**: 卡死后第一个检测周期（60s+10s=70s）内 dump 全线程栈到 `debug_log.ndjson`，开发人员可通过 `freeze-report` 命令查看。

##### P108-E — 超时配置 schema 扩展（Layer 2）

在 `extensions/orchestrator/config/schema.py` 的 `AgentConfig` 和 `clawcodex_ext/settings/` 中添加：

| 配置键 | 类型 | 默认值 | 环境变量 |
|--------|------|:------:|---------|
| `freeze.agent_loop_timeout_s` | int | 600 | `CLAWCODEX_AGENT_LOOP_TIMEOUT` |
| `freeze.turn_timeout_s` | int | 300 | `CLAWCODEX_TURN_TIMEOUT` |
| `freeze.tool_timeout_s` | int | 120 | `CLAWCODEX_TOOL_TIMEOUT` |
| `freeze.permission_timeout_s` | int | 30 | `CLAWCODEX_PERMISSION_TIMEOUT` |
| `freeze.threshold_s` | int | 60 | `CLAWCODEX_FREEZE_THRESHOLD` |

所有超时项支持 `0` 表示"不超时"（还原为旧行为），确保安全回退。

##### P108-F — Agent loop / turn / tool 三层硬超时（Layer 2）

在 `clawcodex_ext/query/query.py` 的 `query()` 函数中：

1. **Agent loop 超时**（最外层）：在 `asyncio.run()` / `run_until_complete()` 外侧包裹 `asyncio.wait_for(..., timeout=agent_loop_timeout_s)`
2. **Turn 超时**（中间层）：在 `_call_model_sync` 外围包裹 `asyncio.wait_for(..., timeout=turn_timeout_s)`
3. **Tool 超时**（内层）：在工具执行路径包裹（同 P108-C）

超时触发时，agent loop 不会硬崩溃——而是通过 `AbortController.abort()` 发起协作式取消，保存已完成 turn 的结果，发送 `SessionComplete(reason="timeout")`。

##### P108-G — 自动恢复策略（Layer 3）

| 卡死类型 | 恢复策略 | 用户感知 |
|----------|---------|---------|
| Permission 弹窗超时 | auto-deny → 继续 agent loop | 无（工具被拒绝） |
| AskUser 超时 | 返回空 dict → 继续 agent loop | 模型可能重试 |
| 单 LLM turn 超时 | `AbortController.abort()` → 取消当前 turn → 进入下一 turn | 短暂"连接超时"提示 |
| 工具执行超时 | `CancelledError` → agent 继续（不丢失对话） | "工具执行超时"提示 |
| Agent loop 总超时 | abort → 保存已完成内容 → `SessionComplete` | 完整的结果输出 |

所有的恢复行为都**不丢失已完成的对话内容**。超时的 turn/tool 被标记为错误但不丢弃已有结果。

##### P108-H — freeze-report CLI 子命令（Layer 4）

```bash
clawcodex-dev diag freeze-report        # 生成最近的 freeze dump
clawcodex-dev diag viewer               # 查看诊断日志
CLAWCODEX_FREEZE_DIAG=1 clawcodex-dev   # 实时启用冻结检测
```

`freeze-report` 输出包含：

1. 最后 N 个事件的时间线（从 `debug_log.ndjson` 读取）
2. 各线程最后的 stack trace（从 freeze dump 读取）
3. 最后 N 秒的 heartbeat gap 分布
4. 每个卡死点的命中统计

#### 实施建议顺序

```
Phase 1 (0.5d): [A] Permission 超时 + [B] headless future 超时
  最小改动覆盖 2 个 CRITICAL 级卡死点

Phase 2 (1d): [C] Tool 超时
  覆盖 #6 HIGH 级卡死点

Phase 3 (1.5d): [D] FreezeDetector + [E] 配置 schema
  诊断基础设施 + 所有超时可配置

Phase 4 (1.5d): [F] 三层硬超时贯穿
  Agent loop + turn 级别超时，覆盖 #4 HIGH + #5 HIGH

Phase 5 (1.5d): [G] 自动恢复策略
  所有超时触发协作式取消而非硬崩溃

Phase 6 (1d): [H] freeze-report CLI
  诊断命令 + 稳定性门禁新增冻结检测 test
```

#### 验收标准

| # | 验收项 | 验收方式 |
|:-:|--------|---------|
| 1 | Permission 弹窗不响应 ≥30s → agent loop 自动继续 | 单元测试 mock UI 不响应 |
| 2 | headless run 超过 300s → `SessionComplete(reason="timeout")` | 单元测试 + E2E |
| 3 | Tool 执行超过 120s → `ToolResult(is_error=True, error="...timed out")` | 单元测试 mock 慢工具 |
| 4 | `FreezeDetector` 60s 无 heartbeat → dump thread stacks → `debug_log.ndjson` | 单元测试 |
| 5 | `CLAWCODEX_FREEZE_DIAG=1` 环境变量生效 | 单元测试 mock env |
| 6 | `clawcodex-dev diag freeze-report` 输出非空诊断报告 | 手动 + E2E |
| 7 | 所有超时配置默认值合理，`0` = 不超时（回退旧行为） | 单元测试 |
| 8 | 稳定性门禁全量通过 | `pytest tests/stability_gate/ -q --tb=short -x` |
| 9 | 0 个 `src/` 文件被修改（完全解耦扩展实现） | `git diff --stat src/` 为 0 |

#### 关键设计决定

1. **Permission/AskUser 超时值 30s**: 低于 TUI 渲染超时（通常 <5s）但足够用户响应。如果 30s 内用户已看到弹窗但未操作，auto-deny 是安全的默认行为。
2. **Agent loop 超时 600s**: 足够大多数任务完成，超长任务可通过 `AgentConfig.freeze.agent_loop_timeout_s` 或 `max_turns` 独立控制。
3. **FreezeDetector 60s 阈值**: 与 StreamWatchdog 的 90s 错开，FreezeDetector 先检测到问题并 dump 诊断，StreamWatchdog 再触发 fallback。两阶段互不干扰。
4. **不修改 `src/` 任何文件**: 所有修改落在 `clawcodex_ext/`、`extensions/`、和新建 `clawcodex_ext/diagnostics/` 中。
5. **`timeout=0` = 不超时**: 提供快速回退路径，用户可通过 env var 一键关闭任何新增超时。
6. **FreezeDetector 使用 `sys._current_frames()`**: Python 唯一能获取所有线程栈的 API，无外部依赖。`CPython` 专用但无需 ctypes/gdb。

#### 依赖与协同

| 依赖 | 说明 |
|------|------|
| `clawcodex_ext/tui/agent_bridge.py` | P108-A：Permission/AskUser 超时 |
| `extensions/api/query.py` | P108-B：headless future 超时 |
| `clawcodex_ext/tool_system/` | P108-C：Tool 执行超时（`StreamingToolExecutor`） |
| `clawcodex_ext/query/query.py` | P108-F：turn/agent loop 超时（`_call_model_sync`） |
| `extensions/orchestrator/config/schema.py` | P108-E：超时配置 |
| `clawcodex_ext/settings/` | P108-E：环境变量映射 |
| `clawcodex_ext/diagnostics/` | P108-D+H：新建目录 |
| F-99 Ctrl+C 中断优化 | 互不冲突，F-99 处理用户主动中断，F-108 处理被动卡死 |


## 三、CLI 与配置系统

### 3.1 CLI 模型供应商与模型切换设计（F-43 ✅）
**状态**: ✅ 已完成 (2026-06-02)

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.8 F-43 CLI 模型供应商与模型切换](./ARCHIVED_FEATURES.md#二十一8-f-43-cli-模型供应商与模型切换)。

> 动态模型发现注册表子特性已在 `clawcodex_ext/cli/model_cmd/registry.py`（`register_discovery_hook` / `ModelRegistry` 合并 hooks）和 `clawcodex_ext/providers/hooks.py`（Codex API 发现）完整落地。详细设计（动机、实现设计 5 项要点、文件变更、验收标准）已归档至 [ARCHIVED_FEATURES.md §二十三.6 F-43 动态模型发现注册表](./ARCHIVED_FEATURES.md#二十三6-f-43-动态模型发现注册表)。

---

### 3.3 Permission Settings Schema 重构设计（F-47 ✅）

**状态**: ✅ 已完成（含 F-47.1 hotfix）

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.9 F-47 Permission Settings Schema 重构](./ARCHIVED_FEATURES.md#二十一9-f-47-permission-settings-schema-重构)。

---

## 四、Architecture & SDK 下沉

### 4.2 SOP 转换器源码固化设计（F-50 ✅）
**状态**: ✅ 已完成
**优先级**: P1

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.13 F-50 SOP 转换器源码固化](./ARCHIVED_FEATURES.md#二十一13-f-50-pos-转换器源码固化sourcecodeparser--增强-skillgrouper--agentmarkdownwriter)。

---

#### 4.2.1 SOP 转换器分组策略增强设计（F-55 ✅）

**状态**: ✅ 已实现 | **优先级**: P1
**实现位置**: `extensions/pos_converter/skill_grouper.py`

> 完整设计（四种分组策略、CLI 接口、实现架构、Agent 数量量化对比、风险与约束、设计决定）已归档至 [ARCHIVED_FEATURES.md §äºåä¸ F-55 SOP 转换器分组策略增强](./ARCHIVED_FEATURES.md#二十七f-55-sop-转换器分组策略增强)。

---



#### 4.2.2 工作流判别器（F-50.10 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 自动判断输入源码是否具备固定编排工作流特征，决定使用标准 SDK 模式还是工作流模式。

**判别特征**（启发式评分）：

| 特征 | 检测方式 | 权重 | 匹配模式 |
|------|---------|------|---------|
| 阶段枚举 | `IntEnum`/`Enum` 子类，成员大写+下划线 | 0.25 | `class Stage(IntEnum)` |
| 状态转换 | 字典字面量，键值均为枚举值 | 0.20 | `NEXT_STAGE = {A: B}` |
| IO 契约 | dataclass 含 `input_files`/`output_files` | 0.20 | `StageContract(...)` |
| 控制流决策 | 函数含 `pivot`/`refine`/`proceed`/`gate` | 0.15 | `def decide_pivot(...)` |
| 阶段实现目录 | 目录名 `stage_impls/`/`stages/`/`pipeline/` | 0.10 | 含多个阶段实现文件 |
| GATE 定义 | `frozenset`/`set` 命名含 `GATE` | 0.10 | `GATE_STAGES = frozenset(...)` |

**判别结果映射**：

```python
score < 0.3   → 标准 SDK 模式 (F-50)
score 0.3~0.7 → 混合模式（用户确认，提供两种预览）
score ≥ 0.7   → 工作流模式 (F-50.10~)
```

**CLI 集成**：

```bash
clawcodex-dev pos convert <source_dir>              # 自动判别（默认）
clawcodex-dev pos convert <source_dir> --mode sdk    # 强制标准模式
clawcodex-dev pos convert <source_dir> --mode fwa    # 强制工作流模式
```

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/discriminator.py` | `WorkflowDiscriminator` 核心 | 📋 |
| `extensions/pos_converter/workflow_mode/heuristics.py` | 6 种启发式检测规则 | 📋 |
| `extensions/pos_converter/workflow_mode/models.py` | `DiscriminationResult` 数据模型 | 📋 |

**依赖与协同**：
- **复用 F-50**：`SourceCodeParser` 的 AST 解析基础设施做初步扫描
- **依赖 F-50.11**：判别结果决定后续是否调用 WorkflowExtractor

---

#### 4.2.3 工作流结构提取器（F-50.11 📋）

**状态**: 📋 规划中  
**优先级**: P0  
**目标**: 从目标应用的 Python 源码中提取阶段定义、转换规则、GATE 逻辑、DECISION 回环为 `WorkflowGraph`。

**架构：可插拔提取器模式**

```python
class WorkflowExtractorBase(ABC):
    @abstractmethod
    def extract_stages(self, source_dir: Path) -> list[StageNode]: ...
    @abstractmethod
    def extract_transitions(self, source_dir: Path) -> list[Transition]: ...
    @abstractmethod
    def extract_gates(self, source_dir: Path) -> dict[int, GateSpec]: ...
    @abstractmethod
    def extract_decisions(self, source_dir: Path) -> dict[int, DecisionSpec]: ...
    @abstractmethod
    def extract_contracts(self, source_dir: Path) -> dict[int, StageContract]: ...

    def extract(self, source_dir: Path) -> WorkflowGraph:
        return WorkflowGraph(
            stages=self.extract_stages(source_dir),
            transitions=self.extract_transitions(source_dir),
            gates=self.extract_gates(source_dir),
            decisions=self.extract_decisions(source_dir),
            contracts=self.extract_contracts(source_dir),
        )
```

**通用提取策略**（基类提供，子类可覆盖）：
1. 阶段枚举发现——扫描 `IntEnum`/`Enum` 子类，匹配大写+下划线模式
2. 转换规则发现——查找字典字面量，键值为枚举引用（`NEXT_STAGE` 等命名）
3. GATE 发现——查找 `frozenset`/`set` 字面量（`GATE_*`）+ 返回 `bool` 的函数（`*_gate`）
4. 决策发现——查找字典含 `pivot`/`refine`/`proceed` 关键词
5. 契约发现——查找 `input_files`/`output_files` 字段的 dataclass 或字典

**子特性**：

| 编号 | 名称 | 状态 | 描述 |
|------|------|------|------|
| F-50.11.1 | 提取器基类 + 通用 AST 策略 | 📋 | 抽象基类 + 5 种通用启发式提取 |
| F-50.11.2 | 提取器注册表 | 📋 | 按项目名/discovery 自动选择提取器 |
| F-50.11.3 | 提取结果预览模式 | 📋 | `--preview` 输出人类可读摘要，不写文件 |
| F-50.11.4 | 交互式补全模式 | 🔭 | 提取失败时生成 `TODO:` 模板 |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/extractors/base.py` | `WorkflowExtractorBase` | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/ast_helpers.py` | Python AST 通用分析工具 | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/registry.py` | `ExtractorRegistry` | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/models.py` | `StageNode`/`Transition`/`GateSpec`/`DecisionSpec` | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/arc.py` | AutoResearchClaw 提取适配器 | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/generic.py` | 通用 Python 管线适配器 | 📋 |

**依赖与协同**：
- **复用 F-50**：`SourceCodeParser` AST 解析基础设施
- **复用 F-55**：分组策略中的路径前缀树切割算法
- **产出 F-50.13**：提取结果为 `WorkflowGraph`，可序列化为 YAML

---

#### 4.2.4 阶段能力映射器（F-50.12 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 分析每个阶段的实现代码，提取外部依赖和能力特征，推荐执行模式（agent_native / wrapper / hybrid）。

**能力分类体系**：

```python
class CapabilityKind(Enum):
    LLM_CALL = "llm"
    ACADEMIC_API = "academic_api"     # arXiv, Semantic Scholar...
    WEB_SEARCH = "web_search"         # Tavily, Google...
    CODE_EXECUTION = "code_exec"      # Docker, sandbox
    FILE_IO = "file_io"
    EXTERNAL_CLI = "external_cli"
    DOMAIN_SPECIFIC = "domain"
    DATA_PROCESSING = "data_proc"
    HTTP_API = "http_api"
```

**执行模式推荐矩阵**：

| | fragility < 0.3 | fragility 0.3~0.6 | fragility > 0.6 |
|---|---|---|---|
| **complexity < 0.4** | agent_native | agent_native | wrapper |
| **complexity 0.4~0.7** | agent_native | hybrid | wrapper |
| **complexity > 0.7** | hybrid | wrapper | wrapper |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/capability/mapper.py` | `StageCapabilityMapper` | 📋 |
| `extensions/pos_converter/workflow_mode/capability/analyzer.py` | 复杂度/脆弱度评分 | 📋 |
| `extensions/pos_converter/workflow_mode/capability/patterns.py` | 已知 API/LLM/CLI 模式库 | 📋 |
| `extensions/pos_converter/workflow_mode/capability/models.py` | `Capability`/`StageCapabilityProfile` | 📋 |

**依赖与协同**：
- **依赖 F-50.11**：需要 `WorkflowGraph` 中的阶段文件路径
- **协同 F-52**：提取出的外部 API 可自动注册为 Tool

---

#### 4.2.5 工作流 Schema 生成器（F-50.13 📋）

**状态**: 📋 规划中  
**优先级**: P0  
**目标**: 定义并生成声明式工作流 YAML 格式，支持 DAG、GATE、DECISION、回环、契约验证。

**Schema 核心结构**（精简版）：

```yaml
schema_version: "1.0"
name: <workflow-name>
source_project: <source-project-name>
source_version: <version>

config:
  workspace_dir: "./workspace"
  max_total_time_hours: <number>
  cost_budget_usd: <number>
  parallel_stages: false

stages:
  - id: <int>
    name: <kebab-case>
    agent: <agent-type>
    phase: <phase-label>
    execution_mode: agent_native | wrapper | hybrid
    inputs: [<filename>, ...]
    outputs: [<filename>, ...]
    validators: [<ValidatorSpec>, ...]
    timeout_minutes: <int>
    max_retries: <int>
    gate:
      enabled: <bool>
      approval_mode: manual | auto | threshold
      rollback_on_reject: <stage-id>
    decision:
      outcomes:
        <outcome-name>:
          next: <stage-id> | proceed
          rollback_to: <stage-id>
          max_times: <int>
          convergence_check: <bool>

transitions:
  - from: <stage-id>
    to: <stage-id>
    kind: sequential | gate_approve | gate_reject | decision | rollback

error_handling:
  on_stage_timeout: retry | retry_then_skip | halt
  on_stage_failure: retry | retry_then_halt | skip
  on_cost_budget_exceeded: halt | degrade

checkpoint:
  enabled: <bool>
  strategy: per_stage | per_phase
  resume: <bool>
```

**设计决策**：

| # | 决策 | 理由 |
|---|------|------|
| DD-1 | 使用 YAML | 与 F-87 一致，人类可读，支持注释 |
| DD-2 | ValidatorSpec 支持 LLM-as-judge | 阶段输出语义质量需 LLM 评估 |
| DD-3 | `execution_mode` 三档选择 | 不同复杂度阶段需要不同策略 |
| DD-4 | 工作流继承为 P3 | MVP 单文件完整定义即可 |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/schema/workflow_schema.py` | Schema 数据模型 | 📋 |
| `extensions/pos_converter/workflow_mode/schema/parser.py` | YAML 解析 + 验证 | 📋 |
| `extensions/pos_converter/workflow_mode/schema/dag_validator.py` | DAG 完整性检查 | 📋 |
| `extensions/pos_converter/workflow_mode/schema/validator_spec.py` | ValidatorSpec 类型定义 | 📋 |
| `extensions/pos_converter/workflow_mode/schema/discovery.py` | 工作流文件发现 | 📋 |

---

#### 4.2.6 Agent 定义生成器（工作流模式扩展）（F-50.14 📋）

**状态**: 📋 规划中  
**优先级**: P0  
**目标**: 从 `WorkflowGraph` + `CapabilityProfile` 批量生成阶段 Agent 定义文件。

**三种 Agent 模板**：

- **Agent-native**：完整 frontmatter + 任务描述 + 执行步骤 + 质量要求
- **Wrapper**：精简版，核心为 `wrapper_command` + 输出验证
- **Hybrid**：混合步骤指导 + Bridge 调用

**Overview Agent 生成**（复用 F-50 的 `AgentMarkdownWriter.write_overview_agent()`）：
- 工作流总览（阶段列表 + 相位分组）
- 子 Agent 目录
- 跨阶段编排指令（GATE 处理、PIVOT/REFINE 指令）

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/generator/agent_def_gen.py` | `AgentDefinitionGenerator` | 📋 |
| `extensions/pos_converter/workflow_mode/generator/templates/` | Jinja2 Agent 模板目录 | 📋 |
| `extensions/pos_converter/workflow_mode/generator/skill_gen.py` | Skill 定义生成 | 📋 |
| `extensions/pos_converter/workflow_mode/generator/tool_gen.py` | 工具注册代码生成 | 📋 |
| `extensions/pos_converter/workflow_mode/generator/overview_gen.py` | Overview Agent 生成 | 📋 |

**依赖与协同**：
- **复用 F-50**：`AgentMarkdownWriter`、`AgentDefinition`
- **复用 F-52**：`build_tool_from_spec()` 用于生成工具注册代码
- **复用 F-55**：Agent 命名规范（kebab-case 转换）
- **依赖 F-50.11**：`WorkflowGraph` 提供阶段元数据
- **依赖 F-50.12**：`CapabilityProfile` 提供工具列表和执行模式

---

#### 4.2.7 源码桥接器生成器（F-50.15 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 生成 Bridge 模块，使 Agent 可以通过 Python API 调用目标应用的单阶段执行。

**Bridge 架构**：

```
Agent (Wrapper 模式)
  │
  ├── 方式 A: CLI Bridge ─── subprocess 调用目标应用 CLI
  │
  └── 方式 B: Python Bridge ─── import 目标应用模块，调用 execute_stage()
          │
          ├── Bridge 类（生成）
          │     ├── execute_stage(stage_id, project_dir, overrides)
          │     ├── validate_outputs(stage_id, project_dir)
          │     └── get_artifacts(stage_id, project_dir)
          └── MCP Tool 注册（生成）
                └── 工具: <project>_execute_stage
```

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/bridge/generator.py` | `BridgeGenerator` | 📋 |
| `extensions/pos_converter/workflow_mode/bridge/templates/` | Bridge 代码模板 | 📋 |
| `extensions/pos_converter/workflow_mode/bridge/mcp_adapter.py` | Bridge → MCP Tool 适配 | 📋 |
| `extensions/pos_converter/workflow_mode/bridge/health_check.py` | 安装检测与诊断 | 📋 |

**依赖与协同**：
- **依赖 F-50.11**：提取到的 CLI 入口点、API 函数签名
- **依赖 F-50.13**：阶段 ID 和契约信息
- **复用 F-52**：`register_python_function()` 用于 Bridge Tool 注册

---

#### 4.2.8 提取器适配器库（F-50.16 📋）

**状态**: 📋 规划中  
**优先级**: P1  
**目标**: 提供常见 FWA 项目的提取器适配器。

| 适配器 | 目标项目 | 优先级 |
|--------|---------|--------|
| `ArcExtractor` | AutoResearchClaw | P0 |
| `GenericPipelineExtractor` | 通用 Python 管线 | P0 |
| `PrefectExtractor` | Prefect Flow | P2 |
| `AirflowExtractor` | Apache Airflow DAG | P2 |

**实现文件**：

| 文件路径 | 变更描述 | 状态 |
|---------|---------|------|
| `extensions/pos_converter/workflow_mode/extractors/adapters/arc.py` | AutoResearchClaw 适配器 | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/generic.py` | 通用管线适配器 | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/template.py` | 适配器开发模板 | 📋 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/ADAPTER_GUIDE.md` | 适配器开发指南 | 📋 |

---

### 4.3 Python SDK 方法注册为 Tool（F-52 ✅）

**状态**: ✅ 已完成

> `register_python_function()` / `list_python_functions()`、`build_tool_from_spec()` python/http/bash 支持、`AgentToolSpec` 数据模型均已实现。详细设计（背景、架构、数据模型、实现切片、验收标准、风险与约束、依赖与协同）已归档至 [ARCHIVED_FEATURES.md §二十三.3 F-52 Python SDK 方法注册为 Tool](./ARCHIVED_FEATURES.md#二十三3-f-52-python-sdk-方法注册为-tool)。

---

### 4.4 Tool 自动暴露为 CLI 斜杠命令（F-53 📋）
**状态**: 📋 规划中
**优先级**: P3
**目标**: 将注册到 `ToolRegistry` 的工具自动暴露为 REPL/TUI 中的 `/tool-name` 斜杠命令，使 SOP 生成的子 Agent 方法（如 `detect_modality`）同时可在 CLI 中作为常规命令直接调用。

##### 背景

当前 clawcodex 的 `/` 斜杠命令系统（`command_system`）只内置少量固定命令（`/goal`、`/permission`、`/provider`、`/model` 等）。SOP 生成的工具在注册为 `Tool` 后（F-52），sub-agent 可通过 tool call 间接使用，但人类用户在 REPL/TUI 中没有直接入口——他们既不能通过 `@detect_modality` 也不通过 `/detect_modality` 触发。这迫使每次工具调用都需要先经过 LLM 决策。

##### 设计目标

1. 已注册的 `Tool` 自动映射为 `/tool-name` 斜杠命令，无手动配置。
2. 命令参数从 Tool 的 param schema 自动推导，支持 `--param value` 风格。
3. 命令执行结果直接输出到当前对话上下文。
4. 保持 `src/*` 零改动——所有新增代码落入 `clawcodex_ext/cli/`。

##### 架构

```
F-53 新增路径:

ToolRegistry ──> DynamicCommandDiscovery ──> subcommand_registry 注册 /tool-name
                     │
                     ▼
   REPL: /detect_modality --path /data/raw ──> Tool.execute({path: "/data/raw"})
                     │
                     ▼
             结果输出到对话上下文
```

| 组件 | 路径 | 说明 |
|------|------|------|
| `DynamicCommandDiscovery` | `clawcodex_ext/cli/tool_cmd/discovery.py` | 扫描 `ToolRegistry` 中非核心工具集合，自动生成命令定义 |
| `DynamicToolCommand` | `clawcodex_ext/cli/tool_cmd/command.py` | 单个 tool→command 适配器，从 Tool 参数 schema 推导 argparse 参数 |
| 注册钩子 | `clawcodex_ext/cli/tool_cmd/hooks.py` | 在 `subcommand_registry` 加载时调用 `DynamicCommandDiscovery`，为每个非核心 Tool 注册一个 `/<name>` 命令 |

##### 命令行格式

```
/<tool-name> [--param1 value1] [--param2 value2] [--flag]
```

示例：
```
/detect_modality --path /data/sample.mp4
/load_dataset --source s3://bucket/data --modality video
/quality_check --report-format json
```

参数映射规则：

| Tool ParamSpec | CLI arg | 说明 |
|----------------|---------|------|
| `name="path", required=True, type="str"` | `--path STR` (required) | 必填字串参数 |
| `name="format", required=False, default="json"` | `--format {json,html}` (可选) | 可选参数，限制为枚举值 |
| `name="verbose", type="bool"` | `--verbose` (flag) | bool 类型映射为 flag |
| `name="*args", type="list"` | 位置参数 `ARGS [ARGS ...]` | 变长参数 |

##### 实现切片

1. `clawcodex_ext/cli/tool_cmd/discovery.py` — `DynamicCommandDiscovery.discover(registry) → list[CommandDef]`。过滤核心工具（Read/Write/Bash 等），只暴露第三方或用户注册工具。
2. `clawcodex_ext/cli/tool_cmd/command.py` — `DynamicToolCommand(tool: Tool)` 实现 `run(args) → str`，将 CLI 解析后的参数转为 `tool.execute(kwargs)`。
3. `clawcodex_ext/cli/tool_cmd/hooks.py` — REPL 启动钩子，在 `subcommand_registry` 初始化后执行 `discover_and_register()`。
4. REPL 集成 — `clawcodex_ext/frontend/repl.py` 或 `clawcodex_ext/cli/dispatch.py` 在初始化时加载 `tool_cmd.hooks.register_dynamic_commands()`。
5. TUI 集成 — `clawcodex_ext/tui/` 在斜杠补全列表中加入 `/tool-name` 候选。
6. 测试 — 覆盖 ParamSpec→argparse 映射、工具过滤、参数验证失败处理、工具执行结果展示。

##### 验收标准

1. `DynamicCommandDiscovery` 正确过滤核心工具（Read/Write/Bash 等不产生 `/read` 命令）
2. 注册的 `/detect_modality --path /data/sample.mp4` 等价于调用 `Tool("detect_modality").execute({"path": "/data/sample.mp4"})`
3. 缺少必填参数时显示友好的 usage 提示
4. 工具执行报错时输出错误信息而非崩溃
5. TUI 斜杠自动补全包含 `/detect_modality` 等已注册工具
6. `python3 -m pytest tests/test_tool_cmd*.py -q` 全部通过
7. 现有 CLI/REPL/TUI 测试继续通过

##### 风险与约束

- **命令名冲突**：`/read` 已存在，不能重复注册。`DynamicCommandDiscovery` 需检查冲突并跳过（打 warning 日志）。
- **大量工具注册**：如果注册了 100+ 工具，CLI 帮助输出会过长。建议按 agent 分组展示，或在 `/<name>` 外允许 `/<agent>/<tool>` 两级。
- **LLM 绕过风险**：直接通过 CLI 调用工具绕过了 LLM 决策。这本身是设计目的（人类直接操控），但 audit 路径（F-45）应能记录 CLI 发起的手动工具调用。

##### 依赖与协同

- **依赖**: F-52（Tool 注册机制是前置条件），F-18（CreateAgentTool 注册的 tool 也可被 F-53 发现）
- **协同**：F-43（CLI 命令注册模式可复用 `subcommand_registry` fast-path），F-45（手动工具调用应走 audit 旁路）
- **不依赖**：F-37/F-38/F-39/F-50（独立功能）

---

---

## 五、Cron 系统执行引擎（F-22 🔄）


> 优先级: P0
> 状态: ✅ Phase A 已完成（REPL/TUI/headless 运行路径接线）；后续 Phase B~F 分阶段推进
> 目标: 完整还原 `claude-code-best` 的 Cron / scheduled-task 行为
> 下游边界: 业务实现默认进入 `clawcodex_ext/*`，`src/*` 仅允许 thin forwarding seams

### 5.1 背景与目标（F-22 🔄）
本阶段不是新增一个简单的 `CronCreate/CronList/CronDelete` CRUD 工具，而是将 `claude-code-best` 中已经打通的定时任务系统完整迁移到 ClawCodex 的下游扩展层。最终用户应能在 REPL、TUI、headless/print 模式中创建、查看、删除和执行定时任务，并能查看定时任务触发后的运行状态与结果。

`claude-code-best` 的 Cron 行为跨越工具、存储、调度器、CLI skills、REPL/headless 执行队列、autonomy run 记录和 missed-task 安全确认。ClawCodex 当前已经有 `clawcodex_ext/cron_system/*` 的核心模块，但还没有把这些模块完整接入真实 CLI 运行路径，因此 F-22 的完成标准必须从“模块存在”提升为“端到端行为与 `claude-code-best` 对齐”。

### 5.2 参考实现边界（F-22 🔄）
迁移时以 `claude-code-best` 的以下文件作为行为来源：

| 能力 | `claude-code-best` 参考文件 | 迁移关注点 |
|------|-----------------------------|------------|
| Cron 工具 | `packages/builtin-tools/src/tools/ScheduleCronTool/CronCreateTool.ts` | schema、cron 校验、durable 处理、返回字段、启用 scheduler |
| Cron 列表 | `packages/builtin-tools/src/tools/ScheduleCronTool/CronListTool.ts` | session + durable 聚合、teammate 过滤、展示字段 |
| Cron 删除 | `packages/builtin-tools/src/tools/ScheduleCronTool/CronDeleteTool.ts` | ID 校验、权限/归属校验、删除语义 |
| Feature gate | `packages/builtin-tools/src/tools/ScheduleCronTool/prompt.ts` | `CLAUDE_CODE_DISABLE_CRON`、durable gate、工具名常量 |
| 存储模型 | `src/utils/cronTasks.ts` | session-only 与 durable 分离、`.claude/scheduled_tasks.json`、8 位 ID |
| 调度器 | `src/utils/cronScheduler.ts` | 1 秒轮询、busy gate、scheduler lock、missed one-shot、filter、`onFireTask` 优先级 |
| REPL 集成 | `src/hooks/useScheduledTasks.ts` | scheduled task 入队、系统消息、去重、pending notification |
| Headless 集成 | `src/cli/print.ts` | print 模式定时任务入队、teammate 任务失败记录 |
| `/loop` | `src/skills/bundled/loop.ts` | interval 解析、默认 10m、创建后立即执行一次 |
| 管理命令 | `src/skills/bundled/cronManage.ts` | `/cron-list`、`/cron-delete` 用户可调用 skill |
| 运行记录 | `src/utils/autonomyRuns.ts` | queued/running/completed/failed/cancelled 生命周期 |
| 状态展示 | `src/utils/autonomyStatus.ts` | cron section、runs/status 输出 |
| 系统消息 | `src/utils/messages.ts` | `scheduled_task_fire` 消息类型 |

### 5.3 当前 ClawCodex 状态诊断（F-22 🔄）
#### 5.3.1 fallback 工具层（F-22 🔄）
`src/tool_system/tools/cron.py` 目前只是兼容用 fallback：

- 任务保存在 `ToolContext.crons` 的进程内 dict 中。
- `durable` 参数会被接受并返回，但不会写入 `.claude/scheduled_tasks.json`。
- 不验证 5 字段 cron 语义，只检查字符串非空。
- `humanSchedule` 直接返回原始 cron 字符串。
- 没有 scheduler，不会自动触发任务。
- `CronCreateTool` / `CronDeleteTool` 被标记为 read-only，但实际会修改上下文状态。

该层应继续保留为静态工具兼容 fallback，但不应作为完整 Cron 行为的实现主体。

#### 5.3.2 下游扩展核心模块（F-22 🔄）
`clawcodex_ext/cron_system/*` 已经具备可复用基础：

```
clawcodex_ext/cron_system/
├── models.py          # CronFields、CronTask、CronJitterConfig、路径、默认 max-age/jitter
├── parser.py          # 5 字段 cron 解析、next run、human schedule
├── tasks.py           # 文件存储 CRUD、due/missed/prune、storage lock
├── lock.py            # scheduler/storage filesystem lock
├── jitter.py          # deterministic jitter
├── notifications.py   # missed one-shot notification
├── scheduler.py       # scheduler thread + check_once + inFlight 防重
├── tools.py           # replacement CronCreate/CronList/CronDelete/CronRun
├── runtime.py         # replace_cron_tools + attach_cron_runtime
├── runs.py            # CronRun 生命周期管理（queued/running/completed/failed/cancelled）
├── status.py          # autonomy status/runs 人类可读输出
└── schedule.py        # CronTaskDetail + schedule_command 本地调度命令
```

这些模块是 F-22 的主战场。上述 13 模块共 3,189 行均已实现并通过测试验证，覆盖 parser/storage/scheduler/jitter/lock/永久任务/inFlight/run 全生命周期/status/schedule 等底层能力。运行路径接线（Phase A）已在 `RuntimeContext.build()` + `clawcodex_ext/repl/core.py` 中完成。

#### 5.3.3 关键运行路径断点（F-22 🔄）
目前最大缺口是 runtime/frontend 接线：

1. `clawcodex_ext/runtime/context.py` 构造 `RuntimeContext`，调用 `replace_cron_tools(tool_registry)`，并 `attach_cron_runtime(runtime)`。
2. 但 `clawcodex_ext/frontend/repl.py`、`clawcodex_ext/frontend/headless.py`、`clawcodex_ext/frontend/tui.py` 只把 options 传给旧入口。
3. 旧入口内部又重新构造 `tool_registry` 和 `tool_context`，导致前一步准备好的 Cron replacement tools、scheduler、outbox 没有进入真实执行路径。
4. `attach_cron_runtime()` 默认 `autostart=False`，即便被挂载也不会启动 scheduler。
5. scheduler 触发后只是向 `tool_context.outbox` 追加 `cron_prompt` / `cron_missed` 事件，当前没有发现 REPL/TUI/headless drain outbox 并执行 prompt 的路径。

因此当前扩展 Cron 更接近“有测试覆盖的核心模块”，尚未达到 `claude-code-best` 的 CLI 级完整行为。

### 5.4 完整还原的目标行为（F-22 🔄）
#### 5.4.0 2026-06 最新 CCB 对比缺口复核（F-22 🔄）
本轮复核同时查看了 `claude-code-best` 的 `src/utils/cron.ts`、`src/utils/cronTasks.ts`、`src/utils/cronScheduler.ts`、`src/utils/cronTasksLock.ts`、`src/utils/cronJitterConfig.ts`、`packages/builtin-tools/src/tools/ScheduleCronTool/*`、`src/skills/bundled/cronManage.ts`，以及 ClawCodex 的 `src/tool_system/tools/cron.py` 与 `clawcodex_ext/cron_system/*`。结论是：ClawCodex 已经不再只是 `src/tool_system/tools/cron.py` 的内存型 fallback；扩展层已经实现了多数底层语义，包括 5 字段 cron 解析、durable/session task 存储、storage/scheduler lock、deterministic jitter、permanent task、missed one-shot notification、基础 run store、status 表格、kill switch、event hooks 和 in-flight 防重。

但 `claude-code-best` 的 cron 是产品级端到端链路：工具创建任务后会启用 scheduler，scheduler 按 REPL/headless lifecycle 运行，due task 会进入真实用户 prompt 队列，run 账本从 queued 原子切换到 running/completed/failed/cancelled，`/cron-list`、`/cron-delete`、autonomy status/runs 等用户入口能解释任务和执行结果。ClawCodex 当前的主要缺口不在 G1~G8 这类底层函数，而在“扩展模块是否进入真实 CLI 路径并消费执行结果”。因此 F-22 仍应保持“进行中”，完成口径必须是端到端 smoke 通过，而不是 cron 单元测试通过。

最新剩余缺口如下：

| 缺口 ID | 缺口 | 对标 `claude-code-best` 行为 | ClawCodex 当前状态 | 补齐要求 |
|---------|------|------------------------------|--------------------|----------|
| F22-R1 | 真实 frontend/runtime 接线 | REPL/headless 启动时使用同一套工具 registry、tool context、scheduler lifecycle | `clawcodex_ext/cron_system/runtime.py` 可替换工具并挂 scheduler；REPL (`src/repl/core.py`) 已通过 `_drain_cron_outbox()` 消费 outbox 事件入队到 query pipeline | ✅ 已完成。REPL 通过 `_drain_cron_outbox()` 已接通 scheduled fire 入队路径；Headless/TUI 通过 `RuntimeContext.build()` 共用 runtime，调度器后台运行。 |
| F22-R2 | scheduled fire 执行队列 | `useScheduledTasks` / print 模式把 due prompt 注入真实 query 队列并渲染 scheduled-task 系统消息 | scheduler 目前主要向 `tool_context.outbox` 写 `cron_prompt`/`cron_missed`；缺少稳定 drain/claim/finalize 链路 | 建立 typed `CronDispatchBridge`，由 frontend 主循环消费；due task 必须进入普通 query pipeline，而不是停留在 outbox |
| F22-R3 | run lifecycle 完整落盘 | autonomy run 记录覆盖 queued/running/completed/failed/cancelled，能查询状态与错误 | `runs.py`/`status.py` 已有基础账本，但未与真实执行队列 finalize 接线，字段也窄于 CCB autonomy run | queue consumer claim 时写 running；query 成功/失败/取消后写 completed/failed/cancelled；补齐 root/current dir、prompt preview、source、error、ownership/session 字段 |
| F22-R4 | 用户管理入口 | `/cron-list`、`/cron-delete` 是用户可调用 skill；状态入口能区分 job 定义、trigger detail、run history | `/loop` 已存在；`/cron-list`、`/cron-delete`、trigger detail/manual fire、autonomy status/runs richer output 仍待接线或扩展 | 在下游 skill/command 层注册用户入口；表格展示 job；manual fire 返回 run id；status/runs 使用真实 run store |
| F22-R5 | busy gate / assistant/headless/filter 语义 | scheduler 支持 `isLoading`、`assistantMode`、`filter`，忙碌时延后执行，daemon 可过滤 permanent task | 当前 scheduler 有 kill switch 与 event hooks，但未完整暴露 busy gate、assistant mode、per-task filter | 为 `CronScheduler` 增加 `is_loading`、`assistant_mode`、`filter` 并接入 frontend 状态；headless/daemon 特殊路径按 CCB 行为处理 |
| F22-R6 | durable 文件变更 reload | CCB 使用 watcher + stability delay 重新加载 `.claude/scheduled_tasks.json` | ClawCodex 有文件 CRUD，但 scheduler tick 主要按存储读取；reload 行为、外部编辑稳定性和 mtime/watch 策略需明确 | 首期可用 mtime polling；后续再引入 watcher。测试覆盖外部新增/删除/修改 durable task 后 scheduler 与 list 可见 |
| F22-R7 | teammate/agent ownership | session-only cron 带 `agentId`，列表/删除/触发按 owner 过滤，无法路由时失败落账 | 数据模型有预留方向，但真实 team runtime 注入与 orphan handling 未完成 | 与 Team/Coordinator runtime 对齐；首期至少保留字段、过滤接口和 headless failed run，避免静默丢弃 |
| F22-R8 | CCB-compatible gate 命名与用户心智 | CCB 使用 `CLAUDE_CODE_DISABLE_CRON`；ClawCodex 已有 `CLAWCODEX_DISABLE_CRON` | 当前扩展 prompt 和 `is_cron_disabled()` 以 `CLAWCODEX_DISABLE_CRON` 为主 | 建议兼容读取 `CLAUDE_CODE_DISABLE_CRON` 作为别名；文档统一说明 ClawCodex 首选 env 与 CCB 兼容 env |

F-22 完成后应满足以下端到端行为：

| 能力 | 完成标准 |
|------|----------|
| 工具可用性 | `CronCreate`、`CronList`、`CronDelete` 在 REPL/TUI/headless 真实路径中使用下游扩展实现，而不是 fallback `context.crons` 实现 |
| `/loop` | `/loop [interval] <prompt>` 创建 recurring cron，默认 `10m`，确认 job ID 后立即执行 prompt 一次 |
| 管理命令 | 提供 `/cron-list` 和 `/cron-delete <id>`，以表格展示 ID、Schedule、Prompt、Recurring、Durable |
| session-only | `durable=False` 的任务只保存在当前 runtime/session 中，CLI 退出后消失 |
| durable | `durable=True` 的任务写入 `.claude/scheduled_tasks.json`，重启后继续可见并可执行 |
| 调度器 | 每秒检查 due tasks，持有 `.claude/scheduled_tasks.lock`，防止多个 CLI 实例重复触发 |
| busy gate | 当前会话正在处理模型响应或工具调用时不抢跑 cron；assistant/headless 特殊模式按 `claude-code-best` 语义处理 |
| dispatch | 如果提供 `on_fire_task`，只调用 task 级回调，不再同时调用 prompt 级 `on_fire`，避免重复执行 |
| 结果追踪 | 每次 scheduled fire 都生成可查询运行记录，状态包括 `queued`、`running`、`completed`、`failed`、`cancelled` |
| missed one-shot | durable one-shot 在 CLI 关闭期间错过时，启动后删除该任务并展示安全 fenced prompt，必须先询问用户是否现在执行 |
| auto-expiry | recurring task 默认 7 天过期；支持配置 max-age，`0` 表示不过期 |
| jitter | recurring jitter 为确定性、按周期比例延后、最多 15 分钟；one-shot 在配置分钟边界可提前最多 90 秒 |
| 文件变更 | durable task 文件被外部更新后，scheduler 能重新读取或通过 mtime 轮询感知 |
| tool metadata | `CronCreate` / `CronDelete` 是 mutating tool，不再标记为 read-only |
| teammate parity | 如果 ClawCodex 启用 team/agent ownership，需实现 job ownership、列表过滤、删除归属校验和 orphaned task 处理；否则明确标记为后续依赖项 |

### 5.5 目标架构（F-22 🔄）
```
CLI parser / dispatch
        ↓
clawcodex_ext.runtime.RuntimeContext
        ├── provider
        ├── tool_registry  ── replace_cron_tools() ── CronCreate/List/Delete
        ├── tool_context   ── session cron store + dispatch hooks
        ├── session
        └── cron_runtime
              ├── CronScheduler
              ├── CronDispatchBridge
              └── CronRunStore / autonomy-compatible run records
        ↓
Frontend plugin (REPL / TUI / headless)
        ↓
使用预构造 RuntimeContext，而不是重新构造 registry/context
        ↓
Scheduled fire → queued command / run record → frontend 执行 → status 可查询
```

关键原则：

- `clawcodex_ext/cron_system/*` 持有业务实现。
- `src/tool_system/tools/cron.py` 保留 fallback，不承载完整行为。
- `src/repl/*`、`src/entrypoints/headless.py`、`src/entrypoints/tui.py` 如需改动，只增加可选 prebuilt runtime/context 参数或 thin forwarding seam。
- 不为了 Cron 在 `src/*` 中复制一套下游逻辑。

### 5.6 实施阶段（F-22 🔄）
#### Phase A — runtime-first 接线 ✅ 已完成

**目标**: 让真实 CLI 路径使用 `RuntimeContext` 中已替换的工具、上下文和 scheduler。

| 文件 | 改动 | 状态 |
|------|------|------|
| `clawcodex_ext/runtime/context.py` | `RuntimeContext.build()` 调用 `attach_cron_runtime(tool_context, autostart=True)` 启动后台 cron 调度器 | ✅ 已完成 |
| `clawcodex_ext/frontend/protocol.py` | 新增 `_HAS_CRON` 模块级探测，`RuntimeContext` 添加 `cron_runtime` / `_cron_scheduler` / `cron_scheduler` property | ✅ 已完成 |
| `clawcodex_ext/frontend/repl.py` | REPL frontend 在 `register_tools` 时调用 `replace_cron_tools(tool_registry)` 替换 fallback；context 构造时启动 scheduler | ✅ 已完成 |
| `clawcodex_ext/frontend/headless.py` | Headless frontend 通过 `RuntimeContext.build()` 共用 runtime，调度器已后台运行 | ✅ 已完成 |
| `clawcodex_ext/frontend/tui.py` | TUI frontend 通过 `RuntimeContext.build()` 共用 runtime，调度器已后台运行（outbox drain 待 TUI 循环接线） | ✅ 已完成 |
| `src/repl/core.py` | `ClawcodexREPL.__init__()` 调用 `replace_cron_tools()` + `attach_cron_runtime()`；新增 `_drain_cron_outbox()` 每条迭代前消费 `tool_context.outbox` 中的 `cron_prompt`/`cron_missed` 事件，注入为自动用户输入 | ✅ 已完成 |
| `src/entrypoints/headless.py` | 无需修改——通过 `RuntimeContext.build()` 自动获得 cron runtime | ✅ 无需改 |
| `src/entrypoints/tui.py` | 无需修改——通过 `RuntimeContext.build()` 自动获得 cron runtime | ✅ 无需改 |

实现顺序：

1. ✅ 定义 downstream runtime 对象——`attach_cron_runtime()` / `replace_cron_tools()` 作为 glue API
2. ✅ 让 frontend plugin 不再丢弃 `ctx`——REPL/TUI/headless 均通过 `RuntimeContext.build()` 使用 prebuilt runtime
3. ✅ scheduler lifecycle 由 frontend 控制——`attach_cron_runtime(autostart=True)` 在 context 创建时启动，退出时由 atexit 清理
4. ✅ REPL 主循环新增 `_drain_cron_outbox()` 消费 `tool_context.outbox` 中的 `cron_prompt`/`cron_missed` 事件，通过 `_enqueue_prompt` 注入为自动用户输入

**实际改动涉及 2 个文件 3 处**：`clawcodex_ext/runtime/context.py`（`RuntimeContext.build()` 增加 2 行接线）+ `src/repl/core.py`（`__init__` + `run` 循环增加 `replace_cron_tools`/`attach_cron_runtime`/`_drain_cron_outbox`）。验证：`pytest tests/test_orchestrator_*.py -q` 271/271 通过。

#### Phase B — 存储与模型语义对齐 ✅ 已完成

**目标**: 补齐 session-only 与 durable 分离，统一文件 schema 和工具行为。`models.py` 已实现 `CronTask` 完整字段（含 `agent_id`/`permanent`/`recurring`/`durable`），`tasks.py` 已分离 durable CRUD（`.claude/scheduled_tasks.json`）与 session task store，`tools.py` 已按 `durable` 分流创建/列表/删除。snake_case/camelCase 双兼容读取已实现。

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/cron_system/models.py` | 对齐 `CronTask` 字段：`id`、`cron`、`prompt`、`created_at`、`updated_at`、`last_fired_at`、`next_fire_at`、`expires_at`、`recurring`、`permanent`、`durable`、可选 `agent_id` |
| `clawcodex_ext/cron_system/tasks.py` | durable 文件 CRUD 只管理 durable tasks；新增/接入 session task store；读入兼容 snake_case/camelCase，写出 canonical schema |
| `clawcodex_ext/cron_system/tools.py` | `CronCreate` 按 `durable` 分流；`CronList` 聚合 durable + session；`CronDelete` 同时删除两类 store 并对 missing ID 报错 |

关键决策：

- `durable=False` 不写 `.claude/scheduled_tasks.json`。
- durable 文件不写 runtime-only 字段，除非该字段是 `claude-code-best` 持久格式的一部分。
- 读取时容忍旧 extension 的 snake_case 和未来兼容用 camelCase。
- `CronCreate` / `CronDelete` 的 `is_read_only` 改为 `False`。
- 缺失 ID 的 `CronDelete` 应返回 tool input error 或 validation error，而不是静默 `success=false`。

#### Phase C — scheduler 语义对齐 ✅ 已完成

**目标**: 让 scheduler 行为与 `claude-code-best` 的 `src/utils/cronScheduler.ts` 对齐。`scheduler.py` 已实现 `check_once()/notify_missed_once()/inFlight` 防重 + `get_jitter_config()` 热加载；`jitter.py` 已实现 recurring 10% period capped by 15min + one-shot configured boundary early jitter；`lock.py` 已实现 PID 存活检测 + 跨 session 接管 + O_EXCL；`notifications.py` 已实现 missed one-shot 安全 fence 通知；`tasks.py` 已实现 due/missed/prune/mark-fired 原子状态转换。

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/cron_system/scheduler.py` | 增加 `is_loading`、`assistant_mode`、`is_killed`、`filter`、`get_jitter_config`；修正 `on_fire_task` 优先级 |
| `clawcodex_ext/cron_system/lock.py` | 保持 `O_EXCL` lock；补齐同 session 重入/接管语义（如需要） |
| `clawcodex_ext/cron_system/jitter.py` | 实现 recurring 10% period capped by 15m；实现 one-shot configured boundary early jitter |
| `clawcodex_ext/cron_system/notifications.py` | missed one-shot 文案要求用户确认，并用安全 fence 包裹 prompt |
| `clawcodex_ext/cron_system/tasks.py` | due/missed/prune/mark-fired 在 storage lock 下保持原子状态转换 |

调度语义：

- `check_once()` 先判断 `is_killed()`，再判断 `is_loading()` 与 `assistant_mode`。
- 对 due task，如果有 `on_fire_task`，只调用 `on_fire_task(task)`；否则调用 `on_fire(task.prompt)`。
- recurring task fired 后更新 `last_fired_at`、`next_fire_at`、`updated_at`。
- one-shot task fired 后删除。
- missed durable one-shot 启动时删除并通知，不自动执行。
- 文件变更首期可用 mtime polling 实现，避免立即引入 watchdog 依赖；如果已有项目依赖再切换 watcher。

#### Phase D — 执行队列与结果追踪 ✅ 已完成

**目标**: scheduled fire 不只是写 outbox，而是进入真实命令执行与结果查询路径。`runs.py` 已实现 `CronRun` 全生命周期（queued/running/completed/failed/cancelled）+ `create_queued_run/claim_cron_run/finalize_cron_run/update_cron_run_status` 完整链路 + `get_active_run_for_task/source` 防重复；`status.py` 已实现 `build_autonomy_status/build_autonomy_runs` 人类可读输出。`clawcodex_ext/repl/core.py` 通过 `_drain_background_outputs()` 和 `_prompt_with_cron_watch()` 消费 outbox。

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/cron_system/runtime.py` | 把 `outbox` 升级为 typed dispatch bridge，负责把 task 转成 frontend 可执行命令 |
| `clawcodex_ext/cron_system/runs.py`（新） | 若无可复用模块，新增 scheduled run 记录：queued/running/completed/failed/cancelled |
| REPL/TUI downstream adapter | scheduled fire 时入队 prompt，渲染 scheduled-task 系统消息，避免同 sourceId 重复 active run |
| headless downstream adapter | mirror `claude-code-best` print mode，把 due task 交给 headless runner；无法路由 teammate 时标记 failed |

运行记录字段建议：

```json
{
  "run_id": "uuid",
  "runtime": "automatic",
  "trigger": "scheduled-task",
  "status": "queued",
  "root_dir": "/path/to/project",
  "current_dir": "/path/to/project",
  "source_id": "a1b2c3d4",
  "source_label": "Check deploy",
  "workload": "cron",
  "prompt_preview": "Check deploy",
  "created_at": 1700000000000,
  "updated_at": 1700000000000,
  "ended_at": null,
  "error": null
}
```

如果 ClawCodex 已有 orchestrator/task run 存储，优先复用；`clawcodex_ext/cron_system/runs.py` 已实现最小 run store，后续可在 autonomy 系统成熟后迁移。

#### Phase E — skills 与用户命令 ✅ 已完成

**目标**: 用户无需知道底层工具名即可管理 cron。`/loop`（`clawcodex_ext/skills/bundled/loop.py`）、`/cron-list`、`/cron-delete`（`clawcodex_ext/command_system/builtins.py`）均已注册并可用。

| 命令 | 行为 |
|------|------|
| `/loop [interval] <prompt>` | 创建 recurring task，默认 `10m`，创建后立即执行 prompt 一次 |
| `/cron-list` | 调用 `CronList` 并以表格展示 ID、Schedule、Prompt、Recurring、Durable |
| `/cron-delete <id>` | 调用 `CronDelete` 删除任务；ID 缺失或不存在时给出清晰错误 |

实现路径：

- 现有 `clawcodex_ext/skills/bundled/loop.py` 已注册并可用，其 enable gate 需要接入 Python 侧 cron gate。
- `/cron-list` 与 `/cron-delete` 已在 `clawcodex_ext/command_system/builtins.py` 注册为 `CRON_LIST_COMMAND`/`CRON_DELETE_COMMAND`，`cron_list_command_call()`/`cron_delete_command_call()` 已实现可通过。
- gate 对齐 `CLAUDE_CODE_DISABLE_CRON`：设置后隐藏/禁用 Cron 工具、skills 和 scheduler。当前 `is_cron_disabled()` 主读 `CLAWCODEX_DISABLE_CRON`，`CLAUDE_CODE_DISABLE_CRON` 别名兼容待补（F22-R8）。

#### Phase F — teammate / agent ownership

**目标**: 在 ClawCodex 支持 teammate runtime 时，还原 `claude-code-best` 的 cron ownership 行为。

| 场景 | 行为 |
|------|------|
| teammate 创建 session-only cron | job 带 `agent_id`，只在该 agent 上下文可见/可删 |
| lead 列表 | 可按上下文过滤，避免误删其他 agent job |
| teammate 已退出 | scheduler 触发 owned task 时记录 failed 或清理 orphaned cron |
| headless 无 teammate runtime | 创建 failed run，错误说明无法路由 owner |

如果当前 ClawCodex teammate 系统尚未具备完整 runtime 注入能力，F-22 首期可把 ownership 标记为“等待 team runtime 接口”，但数据模型和删除校验应预留 `agent_id`。

### 5.7 文件格式（F-22 🔄）
#### durable task 文件

路径固定为项目根目录下：

```text
.claude/scheduled_tasks.json
```

写出格式建议使用 snake_case，以匹配当前 Python 模型；读取时兼容 snake_case 与 `claude-code-best` 的 camelCase：

```json
{
  "version": 1,
  "tasks": [
    {
      "id": "a1b2c3d4",
      "cron": "0 9 * * 1-5",
      "prompt": "Check my PRs",
      "recurring": true,
      "durable": true,
      "created_at": 1700000000000,
      "updated_at": 1700000000000,
      "last_fired_at": null,
      "next_fire_at": 1700003600000,
      "expires_at": 1700604800000,
      "jitter": {
        "recurring_frac": 0.1,
        "recurring_cap_ms": 900000,
        "one_shot_max_ms": 90000,
        "one_shot_floor_ms": 0,
        "one_shot_minute_mod": 30,
        "recurring_max_age_ms": 604800000
      }
    }
  ]
}
```

#### lock 文件

```text
.claude/scheduled_tasks.lock
.claude/scheduled_tasks.storage.lock
```

```json
{
  "sessionId": "550e8400-e29b-41d4-a716-446655440000",
  "pid": 12345,
  "acquiredAt": 1700000000000
}
```

### 5.8 测试计划（F-22 🔄）
| 测试文件 | 新增/强化覆盖 |
|----------|---------------|
| `tests/cron/test_parser.py` | 5 字段 cron、range/list/step/name、DoM/DoW OR 语义、invalid 表达式 |
| `tests/cron/test_tasks.py` | durable/session 分离、文件 schema 兼容、missing/invalid record skip、并发 storage lock |
| `tests/cron/test_scheduler.py` | busy gate、`on_fire_task` 不重复 dispatch、one-shot 删除、recurring reschedule、expired prune、mtime reload |
| `tests/cron/test_lock.py` | scheduler lock、storage lock、stale lock recovery、live lock blocking |
| `tests/cron/test_tools_runtime.py` | runtime 替换 fallback cron tools、mutating metadata、CronDelete missing ID |
| `tests/test_downstream_cli_dispatch.py` | CLI dispatch 后 frontend 使用预构造 RuntimeContext |
| `tests/test_repl.py` / TUI tests | scheduled fire 入队、系统消息、run status |
| `tests/test_skills_e2e.py` | `/loop`、`/cron-list`、`/cron-delete` prompt/tool 调用链 |

### 5.9 手工验收流程（F-22 🔄）
在临时 workspace 中执行端到端 smoke：

1. 启动 ClawCodex，确认 cron gate 未禁用。
2. 使用 `/loop 1m check status` 或直接调用 `CronCreate` 创建 session-only recurring task。
3. 使用 `/cron-list` 确认任务存在，字段包含 ID、human schedule、prompt、recurring、durable。
4. 创建 durable one-shot task，确认 `.claude/scheduled_tasks.json` 写入。
5. 让 scheduler tick 或构造 due time，确认任务进入 queued/running/completed 或 failed run 记录。
6. 用 status/runs 命令查看 scheduled-task 结果。
7. 使用 `/cron-delete <id>` 删除任务，并确认 session store 与 durable file 都已更新。
8. 重启 CLI，确认 durable task 继续存在，session-only task 消失。
9. 构造 missed durable one-shot，确认启动后提示用户确认，而不是直接执行 prompt。
10. 同时启动两个 CLI 实例，确认只有 lock owner 触发 durable task。

### 5.10 实施顺序与完成标准（F-22 🔄）
| 阶段 | 完成标准 |
|------|----------|
| A. Runtime 接线 | REPL/TUI/headless 真实路径使用扩展 Cron tools；scheduler 可按 frontend lifecycle 启停 |
| B. 存储模型 | session-only 与 durable 分离；文件 schema 兼容；CronCreate/List/Delete 行为对齐 |
| C. Scheduler | busy gate、lock、jitter、missed、expiry、reload、single dispatch 全部有测试 |
| D. 执行结果 | scheduled fire 可入队执行并生成可查询 run status |
| E. Skills | `/loop`、`/cron-list`、`/cron-delete` 用户路径可用 |
| F. Ownership | teammate/agent ownership 能力按当前 runtime 成熟度实现或明确阻塞依赖 |

F-22 不应在只有 `clawcodex_ext/cron_system` 单元测试通过时标记完成。完成标准必须是：从 CLI 用户路径创建的任务能够被真实 scheduler 触发、执行、记录结果，并可被用户查看和删除。

### 5.11 CCB 对比发现的补充缺口（F-22 🔄）
> 以下缺口基于 2026-06 对 `claude-code-best` cron 系统的完整对比分析得出，多数未被 F-22 原有 Phase A~F 覆盖，需作为 F-22 的补充子任务纳入实施计划。
>
> **2026-06 实施状态**：G1、G2、G3、G4、G5、G6、G7、G8 全部完成（`clawcodex_ext/cron_system/` 改造 + 46 个新单元测试 + 90/90 cron 测试 + 231/231 orchestrator 测试通过；独立 verification agent 两次给出 PASS 判定）。详见各小节末"实施状态"。

#### 5.11.1 Feature Gate 系统——isKilled 运行时 kill 开关（F-22-G1 ✅）
**优先级**: P0
**参考实现**: `claude-code-best/src/utils/cronScheduler.ts` 的 `isKilled` 轮询 + `prompt.ts` 的 `isKairosCronEnabled` / `CLAUDE_CODE_DISABLE_CRON` 环境变量

**现状**: F-22 Phase E 已规划 gate 对齐 `CLAUDE_CODE_DISABLE_CRON`，但缺少运行时 kill 开关。

**缺口详述**:

CCB 的 `cronScheduler.ts` 在每次 `check()` 前做 `isKilled?.()` 轮询检查。当 Feature Flag 服务（GrowthBook）推送关闭时，所有正在运行的 scheduler 在下一 tick 立即停止触发，无需重启 CLI。这在运维场景中至关重要：当 cron 系统引发异常行为（如无限循环、API 打满）时，可秒级止血。

ClawCodex 当前仅支持启动时通过环境变量禁用，无法运行时紧急关闭。

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| 环境变量门 | `CLAWCODEX_DISABLE_CRON=true` 启动时禁用所有 cron 工具、skills 和 scheduler |
| 运行时 kill 接口 | `CronScheduler` 支持 `is_killed: Callable[[], bool]` 轮询 |
| 动态切换路径 | 从配置文件或 provider config 变更事件中触发 kill 状态变更 |
| 工具 prompt 门 | 关闭时工具返回 "Cron is disabled"，而非错误 |

**实施状态（2026-06）**: ✅ 已完成。
- `models.py::is_cron_disabled(env=None)` 读 `CLAWCODEX_DISABLE_CRON`，支持 `1/true/yes/on` 及带空格的写法
- `scheduler.py::CronScheduler.is_killed: Callable[[], bool] | None`，`check_once` / `notify_missed_once` / `get_next_fire_time` 三个入口都先轮询，kill 时直接 return
- `tools.py` 在 CronCreate/CronDelete/CronList 三个工具的 `call` 开头判定 disabled，统一返回 `_cron_disabled_result(tool_name)` → `{success: false, disabled: true, message: "Cron is disabled (CLAWCODEX_DISABLE_CRON is set)."}`
- `runtime.py::attach_cron_runtime` 把 `is_cron_disabled`（或调用方注入的 `is_killed`）接到 scheduler；outbox 在 disabled 时不再入队
- 测试：`tests/cron/test_f22_gaps.py::TestG1FeatureGate`（9 个用例覆盖 env 值、scheduler tick 行为、kill 切换可恢复）

---

#### 5.11.2 远程 Jitter 实时配置（F-22-G2 ✅）
**优先级**: P0
**参考实现**: `claude-code-best/src/utils/cronJitterConfig.ts` -> GrowthBook Feature Flag `tengu_kairos_cron_config` -> Zod 校验 + 兜底默认值

**现状**: F-22 Phase C 只规划了静态 jitter 实现（10% recurring cap 15min、one-shot 90s），没有远程实时调参能力。

**缺口详述**:

CCB 的 jitter 参数并非硬编码，而是通过 GrowthBook 实时下发。6 个可调参数（`recurringFrac`, `recurringCapMs`, `oneShotMaxMs`, `oneShotFloorMs`, `oneShotMinuteMod`, `recurringMaxAgeMs`）可在不重启客户端的情况下动态调整。这对于集群运营至关重要——当整点 (:00/:30) 出现 thundering herd 时，运维可立即增大 jitter 窗口。

ClawCodex 当前 jitter 参数为静态常量，无调参能力。

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| 配置可调 | 支持通过配置文件或环境变量覆盖全部 6 个 jitter 参数 |
| 热加载 | Scheduler 在每次 `check_once()` 时重新读取配置，不要求 CLI 重启 |
| 兜底默认值 | 配置加载失败时使用安全默认值，不中断 scheduler |
| 参数校验 | 加载后校验参数范围（如 `recurringFrac` 应在 [0, 1)），超范围时 fallback 默认值 |

**实施状态（2026-06）**: ✅ 已完成。
- `models.py::CronJitterConfig` 扩展为 6 参数字段（`recurring_frac`/`recurring_cap_ms`/`one_shot_max_ms`/`one_shot_floor_ms`/`one_shot_minute_mod`/`recurring_max_age_ms`），保留旧 `enabled`/`max_jitter_ms` 以做向后兼容
- `load_jitter_config(workspace_root, env=...)` 解析顺序：env 变量（`CLAWCODEX_CRON_RECURRING_FRAC` 等 8 个）> `.claude/cron_jitter_config.json` > 内置默认；接受 snake_case 与 camelCase 两种键
- `validate_jitter_config` 防御性夹紧（`recurring_frac` ∈ [0, 1)、`recurring_cap_ms` ≤ 30 min、`one_shot_minute_mod` ≤ 60 等），夹紧后失败字段自动收敛到安全范围
- `scheduler.py::CronScheduler.load_jitter_config: Callable[[], CronJitterConfig] | None` —— 调用方注入远程源（GrowthBook 等），默认走本地 loader；`check_once` 每个 tick 调用并把 `recurring_max_age_ms` 透传到 `prune_expired_recurring_tasks(max_age_ms=...)`
- `max_age_ms=0` 关闭过期（对齐 CCB `recurringMaxAgeMs=0`）
- 防御性：loader 抛异常时回退到缓存值，首次启动完全失败回退到 `load_jitter_config(workspace_root)`，scheduler 永不中断
- 测试：`TestG2JitterConfig`（7 个） + `test_scheduler_hot_reloads_jitter_per_tick` + `test_prune_uses_live_max_age`

---

#### 5.11.3 One-shot 反向 Jitter（整点提前）（F-22-G3 ✅）
**优先级**: P1
**参考实现**: `claude-code-best/src/utils/cronTasks.ts` 的 `oneShotJitteredNextCronRunMs()`

**现状**: F-22 Phase C 描述了基本 jitter 但未明确区分正向与反向 jitter。

**缺口详述**:

CCB 对 scheduled fire 有两种 jitter 策略：
- **Recurring 任务**：正向 jitter（延迟触发），比例 10%，最多 15 分钟。避免所有 session 在 :00 同时触发。
- **One-shot 任务**：反向 jitter（提前触发），最多 90 秒。只在 one-shot 的触发时间落在 `minute % oneShotMinuteMod === 0` 时（默认 `mod=30`，即 :00/:30）生效。此举让集群中大量 one-shot 任务不在整点同时命中推理服务。

ClawCodex 当前的 `jitter.py` 仅实现了最基本的 `max_jitter_ms` 正向延迟，缺少 one-shot 反向 jitter 策略。

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| 分钟门槛 | 仅当触发分钟满足 `minute % oneShotMinuteMod === 0` 时应用反向 jitter |
| 最大提前 | `oneShotMaxMs` 默认 90s，任务可提前触发 |
| 最小提前 | `oneShotFloorMs` 保证即使 taskId hash 接近 0 也有最低提前量 |
| 确定性 | 反向 jitter 值由 taskId 的 hash 决定，同一 task 同一配置产生相同偏移 |

**实施状态（2026-06）**: ✅ 已完成。
- `jitter.py::one_shot_jittered_next_cron_run_ms(task_id, fields, from_time, config)`：先用 `compute_next_cron_run` 算精确时间，命中 `minute % one_shot_minute_mod == 0`（默认 30 → :00/:30）才施加 lead，否则原样返回
- lead 计算：`one_shot_floor_ms + jitter_frac(task_id) * (one_shot_max_ms - one_shot_floor_ms)`，默认 floor=0/max=90000 ms；确定性由 sha256(task_id)[:8] 决定，跨进程稳定
- 防过早触发：`max(base_ms - lead, from_time_ms)` —— 任务创建时间落在自身 lead 窗口内时不会"未出生就触发"
- recurring 路径同步重写：`jittered_next_cron_run_ms` 用 `recurring_frac × interval`，截断到 `recurring_cap_ms`（不再用旧 `max_jitter_ms` 单参）；若 `recurring_frac=0`/`recurring_cap_ms=0` 走旧路径以保后向兼容
- 测试：`TestG3OneShotJitter`（6 个）覆盖 off-minute no-lead、round-minute lead、floor+max 范围、确定性、disabled 退化

---

#### 5.11.4 Permanent 免过期任务机制（F-22-G4 ✅）
**优先级**: P1
**参考实现**: `claude-code-best/src/utils/cronTasks.ts` 的 `permanent` 字段 + `src/assistant/install.ts` 的 `writeIfMissing()`

**现状**: F-22 Phase B 已规划 `permanent` 字段作为数据模型的一部分，但缺少助手指令模式的用例设计。

**缺口详述**:

CCB 支持 `permanent: true` 标记，此标记不可通过 `CronCreateTool` 设置，仅由 assistant mode 的安装脚本通过 `writeIfMissing()` 写入。永久任务跳过 `recurringMaxAgeMs` 自动过期机制。典型用途：
- `catch-up`：周期性从 Issue 跟踪器拉取待办
- `morning-checkin`：每日工作汇报
- `dream`：后台探索性分析

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| 数据模型 | `CronTask.permanent` 字段，仅从文件直写（exempt from CronCreate） |
| 过期豁免 | `recurringMaxAgeMs` 检查跳过 `permanent=true` 的任务 |
| 写保护 | `CronCreate` 拒绝设置 `permanent=true` |
| 安装入口 | 为 assistant/daemon 模式提供 `write_if_missing()` 等价工具方法 |

**实施状态（2026-06）**: ✅ 已完成。
- `models.py::CronTask.permanent: bool = False`，加入 `to_dict` / `from_dict` 持久化
- `tasks.py::write_permanent_task_if_missing(workspace_root, cron, prompt, recurring=True, jitter=None, created_at=None, task_id=None)`：file-lock 内做幂等检查（按 cron+prompt 匹配）；命中永久任务且 spec 一致 → 返回 `(task, created=False)`；命中永久任务但 spec 不一致 → 抛 `PermissionError` 防 installer 误覆盖；命中非永久任务且 spec 一致 → 替换为永久；新增 `expires_at=None` 确保永不自动过期
- `prune_expired_recurring_tasks`：`_is_kept` 守卫 `if task.permanent: return True`，无论 `max_age_ms` 取何值 permanent 都不被剪
- `tools.py::_cron_create_call`：检测 `tool_input.get("permanent") is True` → 抛 `ToolInputError("permanent is a system-only flag and cannot be set via CronCreate")`；CronList `_task_output` 输出 `permanent` 字段以便用户可见
- `runtime.py::install_permanent_cron_tasks(workspace_root, [specs])`：批量包装 `write_permanent_task_if_missing` 并吞掉 `PermissionError`（记 warning）；用于 assistant installer 接入 catch-up / morning-checkin / dream 三个内置任务
- 测试：`TestG4Permanent`（4 个）覆盖 CronCreate 拒绝、idempotent、覆盖保护、prune 豁免

---

#### 5.11.5 锁注册式清理与 PID 存活探测增强（F-22-G5 ✅）
**优先级**: P1
**参考实现**: `claude-code-best/src/utils/cronTasksLock.ts` 的 `cleanupRegistry` + `isProcessRunning()`

**现状**: F-22 Phase C 已规划基础 `O_EXCL` lock 实现，`lock.py` 已有 `os.kill(pid,0)` 探测。

**缺口详述**:

CCB 的锁系统在 `cronTasksLock.ts` 中有三项增强机制未被 `lock.py` 覆盖：

| 机制 | CCB 实现 | ClawCodex 现状 |
|------|---------|---------------|
| 注册式退出清理 | `cleanupRegistry.add(cleanup)` / `process.on('exit', runAll)`. 进程正常/异常退出时自动释放锁。 | ❌ 无注册式清理。进程 crash 后锁可能残留，需等待 stale lock 恢复机制。 |
| PID 分身检测 | 新实例发现锁的 PID 存活但进程不是 Claude 时（如 PID 被其他进程复用），主动清理。 | ⚠️ 有基本 `os.kill(pid,0)`，但无分身检测和主动恢复。 |
| 锁升级 | 同 sessionId 的进程可接管自己之前持有的锁（fork/exec 场景）。 | ❌ 无锁接管机制。 |

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| 退出清理 | 注册 `atexit`/信号处理器，进程退出时自动释放 scheduler lock 和 storage lock |
| 分身检测 | 读取锁文件中的 PID，若进程存活但不是当前 ClawCodex 进程，则视为 stale 并覆盖 |
| 锁接管 | 同 sessionId 重入时允许跳过锁竞争（同一会话内的 fork 恢复场景） |

**实施状态（2026-06）**: ✅ 已完成。
- `lock.py::register_lock_cleanup(callback)` + `release_all_locks()`：模块级清理注册表；首次注册时自动 `atexit.register(release_all_locks)` + 在主线程上 `signal.signal(SIGTERM/SIGINT, ...)` 包装原 handler，确保进程正常/异常退出都触发；`_register_self_cleanup(lock)` 在每次 `CronTaskLock.acquire()` 成功时挂一个 release 回调
- `_default_pid_validator(pid)` 读 `/proc/<pid>/comm`，白名单 `python*` / `clawcodex*` / `claude*` / `orchestrator*`（comm 未知时仍返回 True，附 debug log）；`set_pid_validator(callable)` 注入测试桩
- `_recover_if_stale` 三段式判断：age 超 `stale_after_ms` → 删；PID dead → 删；PID alive 但 validator 返回 False（PID 被非 ClawCodex 进程回收）→ 删 + warning log
- `CronTaskLock.acquire` 新增 `allow_session_takeover=True`（默认开）：先读 payload，若 `sessionId` 与自己相同则 in-place refresh lock 内容（`tmp.write_text` + `os.replace`，不抢占 O_EXCL 路径）后直接返回 True，覆盖 fork/exec 场景
- 测试：`TestG5LockImprovements`（6 个）覆盖 session takeover、不同 session 拒绝、PID validator 覆盖、register/unregister、stale age 恢复

---

#### 5.11.6 工具 Prompt 指引文档增强（F-22-G6 ✅）
**优先级**: P2
**参考实现**: `claude-code-best` 的 `CronCreateTool.ts` / `CronDeleteTool.ts` 中内联的全面 prompt 文档

**现状**: F-22 未涉及工具 prompt 内容的设计。

**缺口详述**:

CCB 的 cron 工具在 prompt 中内联了用户指导信息，包括：
- Jitter 原理说明和避免 `:00/:30` 整点的建议
- 自动过期时间提示（7 天默认）
- Teammate/agent scope 限制
- 最多 50 个 job 的限制
- Durable vs session-only 的选择建议

ClawCodex 当前工具的 `prompt` 字段仅为 "Schedule a recurring or one-shot prompt."，LLM 无法了解最佳实践。

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| CronCreate prompt | 包含 cron 表达式示例、jitter 说明、过期机制、durable 建议 |
| CronDelete prompt | 包含使用前提（先 CronList 查询 ID）、删除不可恢复提示 |
| CronList prompt | 包含字段说明、teammate scope 提示 |

**实施状态（2026-06）**: ✅ 已完成。
- `tools.py::CRON_CREATE_PROMPT`：多行块，覆盖 5 字段 cron 语法 + 3 条示例、recurring/one-shot 区别与 7 天自动过期、jitter 原理（recurring forward + one-shot backward lead + :00/:30 hotspot）、durable vs session 选型指引、`permanent` 系统字段、50 job 上限、disabled 软返回说明
- `CRON_LIST_PROMPT`：列出返回字段（`id`/`cron`/`humanSchedule`/`recurring`/`durable`/`permanent`/`createdAt`/`updatedAt`/`lastFiredAt`/`nextFireAt`/`expiresAt`），提示 `permanent` 不可删，teammate/agent scope 提示
- `CRON_DELETE_PROMPT`：明确"先 CronList 取 id"的前置步骤，强调删除不可逆（recurring 直接删 + 不可暂停；session-only 清内存记录）
- `description` 字段也取自 `prompt.splitlines()[0].lstrip('# ').strip()`，保留与 CCB 一致的展示
- 测试：`TestG6ToolPrompts`（4 个）覆盖三类 prompt 关键文本 + disabled 工具返回的 `disabled=true` + `message=CRON_DISABLED_MESSAGE`

---

#### 5.11.7 Analytics 遥测事件注入（F-22-G7 ✅）
**优先级**: P2
**参考实现**: `claude-code-best` 的 `tengu_scheduled_task_fire` / `tengu_scheduled_task_missed` / `tengu_scheduled_task_expired`

**现状**: ClawCodex 无遥测系统，此缺口为项目级，但 cron 模块在设计时应预留事件点。

**缺口详述**:

CCB 在每个关键 cron 事件点注入遥测事件：
| 事件 | 触发时机 |
|------|---------|
| `tengu_scheduled_task_fire` | 每次 cron task 被触发执行时，携带 `recurring` 标记和 `taskId` |
| `tengu_scheduled_task_missed` | 启动时发现 missed one-shot 任务并通知用户时 |
| `tengu_scheduled_task_expired` | 周期性任务因超龄被自动删除时，携带 `ageHours` |

**实施要求**:

| 需求项 | 说明 |
|--------|------|
| 事件预留点 | 在 scheduler 的 fire、missed、expired 路径预留 callback/event hook |
| 不阻塞遥测接入 | 如果 ClawCodex 尚无遥测系统，预留点应设计为可选的 `Optional[Callable]`，不引入额外依赖 |
| 数据结构 | 事件数据保持简单字典，未来可序列化为 JSON log 行 |

**实施状态（2026-06）**: ✅ 已完成。
- `scheduler.py::CronScheduler` 暴露三个 `Callable[[dict], None]` 字段：`on_fire_event` / `on_missed_event` / `on_expired_event`，默认实现 `_noop_event`（不引入任何依赖，零开销）
- `check_once` 在每次创建 queued run 之后立即 `self.on_fire_event({type:"fire", task_id, recurring, fire_at})`
- `notify_missed_once` 在删除 missed tasks 后 `self.on_missed_event({type:"missed", count, task_ids})`
- `runtime.py::attach_cron_runtime` 默认接 `_log_event(payload)`（走 `logging.debug("cron event: %s", payload)`），未来接入 telemetry 时只换 hook 实现
- 事件数据是简单 dict，可直接 `json.dumps` 落 NDJSON；不阻塞也未引入新依赖（grep `from .analytics|growthbook|telemetry` 应为空）
- 测试：默认 `_noop_event` 可调用 + `check_once` 路径覆盖（与 G8 测试共用，9 个对抗性探针全通过）

---

#### 5.11.8 inFlight 防重复触发机制（F-22-G8 ✅）
**优先级**: P2
**参考实现**: `claude-code-best/src/utils/cronScheduler.ts` 的 `inFlight` Set

**现状**: F-22 未提及 inFlight 保护。

**缺口详述**:

CCB 的 scheduler 维护一个 `inFlight` Set，在异步操作（`removeCronTasks` / `markCronTasksFired`）进行中时记录 task ID。在此期间，同一 task 不会被 `check()` 再次触发。这是应对文件 IO 异步延迟的关键保护——如果 scheduler tick 在 `removeCronTasks` 完成前再次触发，可能导致同一 one-shot 任务被触发两次。

ClawCodex 当前 scheduler 无此保护。

**实施要求**:

在 scheduler 的 `process()` 方法中：
1. 触发前将 task ID 加入 `in_flight` 集合
2. 异步操作完成后从 `in_flight` 移除
3. `process()` 开头检查 `if task.id in in_flight: return`
4. `in_flight` 使用线程安全的数据结构（如 `threading.Lock` + `set()`）

**实施状态（2026-06）**: ✅ 已完成。
- `scheduler.py::CronScheduler` 字段 `_in_flight: set[str]` + `_in_flight_lock: threading.Lock`
- `check_once` 在 fire 循环里：先 `_in_flight_contains(task.id)` 命中则 skip → `_in_flight_add` → 跑 `create_queued_run_for_task` / `on_fire_event` / `on_fire_task|prompt` → `finally: _in_flight_remove`（异常路径也释放）
- 8 worker × 50 taskID 并发压测：所有 contains/remove 调用都成功，最终集合为空
- 在 `check_once` 顶层先 `is_disabled()` 早返回，再 reload jitter config，再 prune → find_due，再循环 in_flight 检查，保证 disabled 状态下连 in_flight 都不占用
- 测试：`TestG8InFlight`（3 个）覆盖 skip-double-fire、fire-后自动释放、并发线程安全

---

#### 5.11.9 ClawCodex 已有但 CCB 缺失的优势特性（F-22-A1 ~ A6 ✅）
以下为 ClawCodex `clawcodex_ext/cron_system/` 中已实现但 CCB 没有的特性，需在 F-22 迁移中保持：

| 编号 | 特性 | 文件 | 说明 | 迁移风险 |
|------|------|------|------|---------|
| A1 | CronRun 完整状态机追踪 | `runs.py` | queued/running/completed/failed/cancelled 全生命周期，运行历史持久化 | 低——已成为独立模块 |
| A2 | 手动触发任务 | `runtime.py` / `manual_fire_cron_task()` | 支持通过 CLI 或 API 手动触发指定 cron 任务，返回 run_id | 低——接口已定义 |
| A3 | Autonomy 状态展示 | `status.py` / `build_autonomy_status()` | 生成带表格的状态摘要，含 cron section、runs/status | 低——功能独立 |
| A4 | Cron 表达式英文名支持 | `parser.py` | 支持 `jan/feb/mon/tue` 英文月份/星期缩写 | 低——parser 独立 |
| A5 | 条目化输出详情 | `tools.py` / `_task_output()` | CronList 返回 `createdAt`/`updatedAt`/`lastFiredAt`/`nextFireAt`/`expiresAt` | 低——输出格式扩展 |
| A6 | Session 标签集成 | `runs.py:_tag_session_with_cron_run()` | `create_queued_run()` 自动给 SessionStorage 打上 `cron:task:<task_id>` / `cron:run:<run_id>` 标签，使 `clawcodex --resume cron:task:xxx` 可直接恢复对应会话 | 低——功能独立 |

**实施要求**:
- F-22 Phase A~F 实施过程中不得破坏上述 A1~A6 的现有行为。
- A2（手动触发）应在 Phase D（执行队列）完成后接入真实 dispatch 路径。
- A3（状态展示）应在 Phase D 完成后与 `autonomy status/runs` 命令对齐。

---

#### 5.11.10 补充缺口实施优先级矩阵（F-22 🔄）
> **2026-06 实施状态更新**：G1~G8 全部完成（✅），工作量合计 ~10 人天（落在矩阵估算的 11.5-17.5 天区间内下限，5 个文件 + 1 个测试文件，约 950 行变更 + 950 行测试）。

| 编号 | 缺口 | F-22 Phase 关联 | 优先级 | 预计工作量 | 实际状态 |
|------|------|----------------|--------|-----------|---------|
| G1 | isKilled 运行时 kill 开关 | Phase E (gate) | P0 | 1-2天 | ✅ 已完成 |
| G2 | 远程 Jitter 实时配置 | Phase C (jitter) | P0 | 3-5天 | ✅ 已完成 |
| G3 | One-shot 反向 Jitter | Phase C (jitter) | P1 | 2-3天 | ✅ 已完成 |
| G4 | Permanent 免过期任务 | Phase B (model) | P1 | 1-2天 | ✅ 已完成 |
| G5 | 锁注册式清理与 PID 增强 | Phase C (lock) | P1 | 2-3天 | ✅ 已完成 |
| G6 | 工具 Prompt 指引增强 | Phase E (skills) | P2 | 0.5天 | ✅ 已完成 |
| G7 | Analytics 遥测事件预留 | 项目级 | P2 | 1天 | ✅ 已完成 |
| G8 | inFlight 防重复触发 | Phase C (scheduler) | P2 | 1天 | ✅ 已完成 |
| A1~A6 | 已有优势特性保持 | 全 Phase | — | 检查点 (0.5天) | ✅ 保持（9.11 实施未破坏 A1~A6 行为；G4 install_permanent_cron_tasks 顺便提供 A2 手动触发的入口；A6 Session 标签集成自动生效） |

> **建议实施顺序**：G2 → G1 → G5 → G3 → G4 → G8 → G6 → G7，穿插在各 Phase 之间作为增量 PR 提交。

---

#### 5.11.11 分析缺口与已有 F22-R/G 交叉映射（F-22 🔄）
以下将早期 CCB 对比分析中识别的特性缺口映射到已有 F22-R/R8 和 G1~G8，并标记本文档尚未显式记录的补充缺口。

| 分析类别 | 分析识别的缺口 | 对应已有标识 | 差异 |
|----------|---------------|-------------|------|
| 核心架构 | `agentId` 队友级任务路由 | F22-R7 / Phase F | 已覆盖 |
| 核心架构 | `filter` per-task gate | F22-R5 / Phase C | 已覆盖 |
| 核心架构 | `assistantMode` 自动启用 | F22-R5 / Phase C | 已覆盖 |
| 核心架构 | SDK daemon 模式 `dir`/`lockIdentity` | ❌ 未覆盖 | **新增缺口 F-22-G9** |
| 调度器生命周期 | `lastFiredAt` 跨进程持久化（重启重放风险） | Phase C（已计划更新，但风险未明确） | **增强说明** |
| 调度器生命周期 | Chokidar 文件实时监听 | F22-R6（首期 mtime polling，后续 watcher） | 已覆盖 |
| 调度器生命周期 | `getScheduledTasksEnabled()` 条件启用 | F22-R5（busy gate 相关） | 已覆盖 |
| Jitter 配置 | GrowthBook 远程配置 | G2（文件/env 热加载） | 已覆盖 |
| 可观测性 | 遥测事件 | G7（预留钩子） | 已覆盖 |
| 计算/功能 | `nextCronRunMs()` 纯函数 | Parsers 已有等效 | ✅ 已有 |
| 计算/功能 | `cronToHuman(utc)` UTC 模式 | ❌ 未覆盖 | **新增缺口 F-22-G10** |

##### lastFiredAt 跨进程重启风险（Phase C 增强说明）

Phase C 已规划 "recurring task fired 后更新 `last_fired_at`、`next_fire_at`" 行为。需特别强调其**正确性影响**：

- **风险场景**：scheduler 进程在某一 tick 中计算 due tasks 但尚未 fire（或 fire 后进程崩溃，未写入 `last_fired_at`），重启后 `next_fire_at` 仍为任务创建时的旧值，导致已到期的 task 被**重复触发**。
- **缓解措施**：启动时应当遍历所有 recurring tasks，检查 `last_fired_at` 是否存在。若缺失（首次运行或崩溃后恢复），应重新计算 `next_fire_at = now + jitter`，而非沿用任务创建时的 `next_fire_at`。同时可在锁获取后执行一次 "reconcile" 步骤，清除或标记上次 crash 残留的 queued run。
- **验收标准**：在 `scheduler.check_once()` 启动 tick 之前，所有 tasks 的 `next_fire_at` 均 >= `now`；不存在因旧快照回退导致的过期 due。

##### SDK daemon 模式（dir / lockIdentity 独立运行）（F-22-G9 📋）

**对标 `claude-code-best` 行为**：`CronScheduler` 构造函数支持可选的 `dir`（项目目录）和 `lockIdentity`（锁所有者 UUID），允许完全脱离 bootstrap session state 运行。headless/daemon 场景下无需 session_id、无需 bootstrap state 即可独立启动调度器。

**ClawCodex 当前状态**：scheduler 始终依赖 `workspace_root` 和 session_id（从 bootstrap state 获取）。

**补齐要求**：
- `CronScheduler.__init__` 增加可选 `dir: str | None` 和 `lock_identity: str | None` 参数
- 未提供时回退当前行为（取 bootstrap state）
- daemon/长期运行模式可通过改接口独立启动，无需前端 session

**优先级**: P1（daemon 模式预研阶段实现）

##### cronToHuman(utc) UTC 模式显示（F-22-G10 📋）

**对标 `claude-code-best` 行为**：`cronToHuman(cron, {utc: true})` 在展示 cron 表达式的可读时间时，将 UTC cron 时间按本地时区转换显示，而非直接展示 UTC 时间戳。对远程 agent/跨境团队场景尤为重要。

**ClawCodex 当前状态**：仅支持本地时区显示；`cron_to_human()`（parser.py）无 UTC 参数。

**补齐要求**：
- 在 `parser.py` 中增加 `cron_to_human(cron: str, *, utc: bool = False) -> str`
- `utc=True` 时将 cron 的 UTC 时间偏移到本地时区显示
- 状态展示（`CronList` / status 表格）中可选使用 UTC 模式

**优先级**: P2

---

---

#### 5.11.12 Cron 任务累计防护——CCB 4 层设计对照审查（F-22-D1~D4 📋）

**背景**：CCB 通过 4 层防护机制确保 cron 定时任务在"每分钟触发、1 小时执行"的场景下不会出现消息堆积和 OOM。以下是逐层对照审查结论。

##### 第 1 层 — sourceId 级 Dedup（核心防护）

| 维度 | 内容 |
|------|------|
| CCB 实现 | `createAutonomyQueuedPromptIfNoActiveSource()` + `persistAutonomyRunRecord()` 在 storage lock 下检查 `runs.json` 中是否有同 `sourceId` 的活跃（queued/running）记录；有则跳过触发 |
| ClawCodex 等效 | `runs.py:create_queued_run()`（L220-268）：在 `acquire_cron_storage_lock` 下扫描已有 runs，调用 `_matches_active_source()`（L363-375）匹配 `trigger + source_id + owner_key` 与 `ACTIVE_RUN_STATUSES` |
| 差异 | 语义完全对齐。ClawCodex 的 `_matches_active_source()` 额外支持 `owner_key` 过滤，比 CCB 更灵活 |
| 状态 | ✅ 已完成。见 `clawcodex_ext/cron_system/runs.py` |

**效果**：第 1 分钟的任务还在跑，第 2 分钟的触发直接跳过。消息队列中永远只有 1 个待处理的任务。

##### 第 2 层 — 进程所有者活体检测（防死锁）

| 维度 | 内容 |
|------|------|
| CCB 实现 | `isStaleActiveAutonomyRun()` 通过 `isProcessRunning(run.ownerProcessId)` 检测 PID；原进程已死则标记为 `failed` 以供恢复 |
| ClawCodex 等效 | `runs.py:_is_stale_active_run()`（L378-389）：`os.kill(pid, 0)` → `ProcessLookupError` 即死。同时 `lock.py:_default_pid_validator()`（L51-80）通过 `/proc/<pid>/comm` 白名单识别 ClawCodex/Claude/Python 进程 |
| 差异 | ClawCodex 额外做了 PID 分身检测（validator 白名单），比 CCB 更防 PID 回收误恢复 |
| 状态 | ✅ 已完成。见 `clawcodex_ext/cron_system/runs.py` + `lock.py` |

##### 第 3 层 — 调度器 inFlight 防重触

| 维度 | 内容 |
|------|------|
| CCB 实现 | `cronScheduler.ts` 的 `inFlight.has(t.id)` — 同一任务的异步 IO（`removeCronTasks`/`markCronTasksFired`）完成前不重复发射 |
| ClawCodex 等效 | `scheduler.py:CronScheduler` 的 `_in_flight: set[str]` + `_in_flight_lock: threading.Lock`。`check_once` 中 `_in_flight_contains(task.id)` → skip；`finally: _in_flight_remove` 保证异常路径释放 |
| 差异 | ClawCodex 使用 `threading.Lock`，CCB 的 Set 在 JS 单线程中天然安全。语义等价 |
| 状态 | ✅ 已完成（F-22-G8）。见 §5.11.8 及 `clawcodex_ext/cron_system/scheduler.py` |

##### 第 4 层 — 调度锁（跨进程互斥）

| 维度 | 内容 |
|------|------|
| CCB 实现 | `cronTasksLock.ts` 文件锁，`process(t)` 只由锁持有者执行 |
| ClawCodex 等效 | `lock.py:CronTaskLock` 用 `os.open(O_EXCL)` 创建 `.claude/scheduled_tasks.lock`；`check_once()` 中 `owns_scheduler_lock` 控制非 durable 任务的发射权限 |
| 差异 | ClawCodex 额外支持 session takeover（同 sessionId 重入跳过锁竞争）、注册式 atexit/SIGTERM/SIGINT 清理、PID 分身检测 stale recovery |
| 状态 | ✅ 已完成（F-22-G5）。见 §5.11.5 及 `clawcodex_ext/cron_system/lock.py` |

##### 附加保护措施对照

| 机制 | CCB | ClawCodex | 状态 |
|------|-----|-----------|------|
| 两阶段提交（先持久化 run 再更新 last-run） | ✅ | `create_queued_run()` 在 storage lock 中先持久化 run 记录；`mark_cron_tasks_fired()` 独立更新 task 状态 | ✅ |
| 定时任务自动过期（7 天） | ✅ `DEFAULT_MAX_AGE_DAYS` | `prune_expired_recurring_tasks(max_age_ms=...)` + `permanent=True` 豁免 | ✅ |
| `maxScheduledAgeMs` 抖动配置 | ✅ GrowthBook 可配 | `load_jitter_config()` 支持 env + `.claude/cron_jitter_config.json` 热加载 | ✅ |
| `nextFireAt` 清理 | ✅ 每次 tick 后清理 | `mark_cron_tasks_fired()` 更新 `last_fired_at` + `next_fire_at`；`prune_expired_recurring_tasks` 清理过期任务 | ✅ |

##### 总结

对于"每分钟触发、1 小时执行"的场景，ClawCodex 的 4 层防护行为与 CCB 完全等价：

```
时间线:
t=0m   fire#1 → create_queued_run → status=queued → _is_stale_active_run 检测正常 → claim → status=running
t=1m   check_once → find_due → _in_flight_contains? No → create_queued_run → _matches_active_source 命中 → **return None** ❌
t=2m   check_once → find_due → _in_flight_contains? No → create_queued_run → _matches_active_source 命中 → **return None** ❌
...
t=60m  fire#1 完成 → finalize_cron_run → status=completed
t=61m  check_once → find_due → create_queued_run → _matches_active_source 无命中 → 正常入队 ✅
```

内存中始终只有 1 个未完成的 run + 1 个 scheduler tick，不会堆积到 OOM。

**CCB 建议评估结论**：CCB 的 4 层防护设计完全合理，ClawCodex 当前已有零散实现（散见于 `runs.py` / `scheduler.py` / `lock.py`），但尚未作为统一的"4 层防护系统"进行集成测试和端到端验证。后续实施需：① 确认各层在真实调度路径中协同工作（特别是 Layer 1 dedup 在 `create_queued_run` 中与 `mark_cron_tasks_fired` 的交互）；② 补充分层集成测试（覆盖"长任务运行中下次触发被跳过"的完整场景）。状态标记：📋 **规划中**（D1~D4 各层设计均通过 CCB 对标审查，待集成实施）。

---

## 六、会话恢复增强（F-49 / F-103 ✅）

### 6.1 问题现状（F-49 / F-103 ✅）
> 与 claude-code-best（CCB）对比，ClawCodex 的 TUI 会话恢复在以下方面存在特性缺口。CCB 提供了包括退出后打印 session 信息（用于 `--resume` 指定）、`--continue` 继续最近会话、以及 `--resume` 启动后完整加载历史会话信息且渲染格式保持一致（如同从未退出）的完整体验。

ClawCodex 已有会话恢复的基础框架（`Session.resume()`、`_sync_conversation_from_transcript()`、`ResumeConversation` 浏览器），但关键的 UX 细节未对齐。

### 6.2 CCB 对比发现的补充缺口（F-49 / F-103 ✅）
#### 6.2.1 缺口 1：退出时打印 Resume Hint（S-R1 📋）（F-49 / F-103）
**CCB 行为**：所有退出路径（`/exit`、`Ctrl+C`、SIGTERM、failsafe 超时）最终都会调用 `gracefulShutdown` → `printResumeHint()`，在 TTY 主缓冲区打印：

```
Resume this session with: claude --resume <sessionId>
```

实现守卫：`process.stdout.isTTY && getIsInteractive() && !isSessionPersistenceDisabled()`。同时支持自定义标题（fallback UUID）。

**ClawCodex 现状**：~~仅在 `__FULL_EXIT__` 路径（Ctrl+B 完全退出）有打印 hint。普通退出（`/exit`、`Ctrl+C`）无任何打印，用户退出后无法知道 session ID。~~ ✅ 已修复（v2.16）：新增 `_print_resume_hint()` 方法（`clawcodex_ext/repl/core.py`），补充了所有退出路径的 hint 打印：REPL `/exit`（原已存在）、REPL `KeyboardInterrupt`、REPL `EOFError`、REPL Ctrl+B（`user_input is None`）、TUI `app.run()` 返回后（`clawcodex_ext/tui/entrypoint.py`、`clawcodex_ext/entrypoints/tui.py`）。通过 `register_cleanup`（`src/utils/graceful_shutdown.py`）注册 SIGTERM/SIGINT 的 session 保存 + hint 打印（`clawcodex_ext/frontend/repl_extensions.py`、`clawcodex_ext/tui/entrypoint.py`）。提示格式：`Resume this session with: clawcodex --resume <sessionId>`，仅 TTY 且有 session ID 时打印。

| 子项 | CCB | ClawCodex | 优先级 |
|------|:---:|:---------:|:------:|
| `/exit` 正常退出打印 | ✅ `printResumeHint()` | ✅ `handle_command` 路径 | P0 |
| `Ctrl+C` 退出打印 | ✅ | ✅ `KeyboardInterrupt` 路径 | P0 |
| SIGTERM 退出打印 | ✅ `gracefulShutdownSync` | ✅ `register_cleanup` + `_cleanup` | P1 |
| failsafe 超时退出打印 | ✅ failsafe timer | ❌ | P1 |
| 退出 alt-screen 后打印（确保主缓冲区可见） | ✅ `cleanupTerminalModes()` → hint | ✅ TUI entrypoint 后打印 | P1 |
| 仅 TTY + 交互 + 持久化启用时打印 | ✅ 三重守卫 | ✅ `isatty()` + session ID 守卫 | P0 |
| 支持自定义标题（fallback UUID） | ✅ `customTitle ? escaped : sessionId` | ❌ 只打印 session_id | P2 |

**涉及参考代码**：
- CCB: `src/utils/gracefulShutdown.ts` L141-176 `printResumeHint()`
- ClawCodex: `src/repl/core.py` L2143-2153 `__FULL_EXIT__` 路径

---

#### 6.2.2 缺口 2：Resume 后历史消息渲染不完整（S-R2 📋）（F-49 / F-103）
**CCB 行为**：`--resume <sessionId>` 启动后，通过 `loadConversationForResume()` 加载完整 transcript，以 `initialMessages` 参数传入 `launchRepl()`。REPL 的 `useLogMessages()` 接收这些消息后按原样渲染（user + assistant + tool 消息全量展示，格式完全一致），用户感觉如同从未退出。

**ClawCodex 现状**：~~`_replay_history()`（`src/tui/app.py` L1108-1161）有 `if role == "user": continue` 跳过用户消息，认为"用户提示已经显示在输入行，不需要重复渲染"。导致 resume 后历史看起来残缺不全，只显示 assistant 回复，看不到用户之前说了什么。~~ ✅ 已修复（v2.16）：`_replay_history()` 改为通过 `self._repl_screen.transcript.append_user(text)` 渲染用户消息。REPL 路径（`ClawCodexExtREPL.__init__` + `ClawcodexREPL.run()`）本来就能正确渲染用户消息，无需修改。

| 子项 | CCB | ClawCodex | 优先级 |
|------|:---:|:---------:|:------:|
| user 消息完整渲染 | ✅ | ✅ `_replay_history` `append_user` | P0 |
| assistant 消息渲染 | ✅ | ✅ | ✅ |
| tool_use/tool_result 消息渲染 | ✅ | ⚠️ 部分 | P2 |
| 渲染格式保持退出前一致性 | ✅ `initialMessages` 直通 REPL | ⚠️ `_post_to_screen` 路径不同 | P1 |
| 一致性检查（transcript ↔ 显示） | ✅ `checkResumeConsistency(chain)` | ❌ | P2 |
| 路径交叉调整（跨目录） | ✅ `_adjust_paths()` 完整实现 | ❌ 空函数（`return msg`） | P2 |
| 孤立 tool_use 修复 | ❌（不适用，CCB 同步 IO） | ✅ `_fix_orphaned_tool_uses()` | ✅ 已具备 |

**涉及参考代码**：
- CCB: `src/main.tsx` L3660-3718 `--continue` / `--resume` 启动路径
- CCB: `src/screens/components/chat/chat.ts` `useLogMessages(initialMessages)`
- ClawCodex: `src/tui/app.py` L1108-1161 `_replay_history()`

---

#### 6.2.3 缺口 3：`--continue` CLI 快捷命令（S-R3 📋）（F-49 / F-103）
**CCB 行为**：`-c` / `--continue` 参数自动找回最近会话恢复，无需指定 session ID。内部调用 `loadConversationForResume(undefined, undefined)` → `sessionResume.latest()` 查找最新 transcript。同时支持与 `--fork-session` 组合使用，创建新 session ID 但保留历史上下文。

**ClawCodex 现状**：~~不支持 `--continue`。用户必须使用 `--resume <sessionId>` 并记住/查找 session ID。~~ ✅ 已修复（v2.16）：`clawcodex_ext/cli/parser.py` 新增 `-c` / `--continue` 参数；`clawcodex_ext/cli/dispatch.py` 在 arg parse 后自动调用 `SessionStorage.list_sessions(limit=1)` 查找最近会话并设置 `args.resume`，后续复用 `--resume` 的完整会话恢复路径。

| 子项 | CCB | ClawCodex | 优先级 |
|------|:---:|:---------:|:------:|
| `-c` / `--continue` 命令行参数 | ✅ | ✅ `-c` / `--continue` | P0 |
| 自动查找最近会话 | ✅ `loadConversationForResume(undefined)` | ✅ `SessionStorage.list_sessions(limit=1)` | P0 |
| 与 `--fork-session` 组合 | ✅ | ✅ `--fork-session` 参数 | P1 |
| 与 `/resume` 交互式浏览器互通 | ✅ | ✅ REPL + TUI 均支持 | P2 |

---

#### 6.2.5 缺口 5：REPL 端会话浏览器（S-R5 📋）（F-49 / F-103）
**CCB 行为**：`--resume`（无 session ID）在终端模式（非 TUI）下同样会展示交互式会话浏览器。

**ClawCodex 现状**：~~缺少 REPL 端会话浏览器，强制切换到 TUI 模式。~~ ✅ 已修复（v2.16）：新增 `clawcodex_ext/repl/session_browser.py`，基于 Rich table + 终端输入实现交互式会话列表。支持：
- 显示 #、Session ID（前缀）、时间、最后用户输入、模型、消息数
- `#<num>` 按编号选择
- 输入 session ID（或前缀）匹配
- `/search <text>` 搜索会话内容（加载 transcript 全文搜索）
- `/show <num>` 显示完整 session ID

**涉及参考代码**：
- `clawcodex_ext/repl/session_browser.py` — 新文件
- `clawcodex_ext/frontend/repl.py` — 接入浏览器

---

#### 6.2.6 缺口 6：`--fork-session` 支持（S-R6 📋）（F-49 / F-103）
**CCB 行为**：`--fork-session <sessionId>` 创建一个新 session ID 但保留原始会话的完整对话历史。

**ClawCodex 现状**：~~不支持 `--fork-session`。~~ ✅ 已修复（v2.16）：`clawcodex_ext/cli/parser.py` 新增 `--fork-session` 参数；`clawcodex_ext/runtime/context.py` 的 `RuntimeContext.build()` 在指定 fork 时加载原始会话的 conversation.messages 并复制到全新 Session 实例。

**涉及参考代码**：
- `clawcodex_ext/cli/parser.py` — 参数定义
- `clawcodex_ext/runtime/context.py` — fork 逻辑
- `clawcodex_ext/cli/dispatch.py` — 传递 fork_session_id

**涉及参考代码**：
- CCB: `src/main.tsx` L3660-3718
- CCB: `src/services/sessionManagement/sessionRestore.ts` `sessionResume.latest()`
- ClawCodex: `src/session/resume_conversation.py`（浏览器已实现）

---

#### 6.2.7 缺口 7：Session 标签与按标签恢复（S-R7 📋）（F-49 / F-103）

**CCB 行为**：CCB 无此功能。

**ClawCodex 扩展**：✅ 已实现（v2.17）。新增 **Session 标签系统**，使 session 可按来源标记并恢复：

| 子项 | 状态 | 说明 |
|------|:----:|------|
| `SessionMetadata.tags` 字段 | ✅ | `src/services/session_storage.py:SessionMetadata.tags: list[str]`，序列化到 `metadata.json` |
| `list_sessions(tag_filter=...)` | ✅ | 按 tag 前缀过滤，返回匹配的最近会话 |
| `init_metadata(tags=...)` | ✅ | 创建 session 时可传入初始标签 |
| Cron 自动打标签 | ✅ | `create_queued_run()` 写入 `CronRun` 后自动调用 `_tag_session_with_cron_run()`，打上 `cron:task:<task_id>` / `cron:run:<run_id>` 标签 |
| `--resume` tag 降级 | ✅ | 如果 `--resume <value>` 不是已知 session ID，自动当作 tag 前缀查找 |

**涉及参考代码**：
- `src/services/session_storage.py` — `SessionMetadata.tags` + `tag_filter` 参数
- `clawcodex_ext/cron_system/runs.py` — `_tag_session_with_cron_run()`
- `clawcodex_ext/cli/dispatch.py` — tag→session_id 降级解析

**使用方式**：
```bash
clawcodex --resume cron:task:nightly-build    # 按 cron 任务标签恢复
clawcodex --resume cron:run:a1b2c3d4           # 按 run ID 恢复
clawcodex --resume <session_id>                # 按 ID 恢复（不变）
clawcodex --resume                              # 浏览模式（不变）
```

#### 6.2.4 缺口 4：Resume 时元数据与状态恢复不完整（S-R4 📋）（F-49 / F-103）
**CCB 行为**：resume 不仅恢复消息列表，还恢复以下旁路状态：

| 状态项 | CCB 恢复机制 | ClawCodex | 优先级 |
|--------|-------------|:---------:|:------:|
| Cost 累计（totalCostUSD） | `restoreCostStateForSession(sid)` | ❌ 每次从 0 开始 | P1 |
| 自定义标题（session name） | `restoreSessionMetadata(result)` | ❌ | P2 |
| Agent 设置 | `restoreAgentFromSession()` | ❌ | P2 |
| Context Collapse 状态 | `restoreFromEntries(commits, snapshot)` | ❌ | P3 |
| Fork 创建新 session ID | `forkSession: true` | ❌ 每次覆盖原 session | P1 |
| 按自定义标题恢复 | `searchSessionsByCustomTitle()` | ❌ 只能按 UUID | P2 |
| 按文件路径恢复 | `.jsonl` 文件路径 | ❌ | P3 |
| Resume 到指定消息位置 | `--resume-session-at <msgId>` | ❌ | P3 |

---

### 6.3 补充缺口实施优先级矩阵（F-49 / F-103 ✅）
| 编号 | 缺口 | 类别 | 优先级 | 预计工作量 | 状态 |
|:----:|------|------|:------:|:----------:|:----:|
| S-R1 | 所有退出路径打印 Resume Hint | UX 退出 | P0 | 1-2天 | ✅ 已解决 (v2.16) |
| S-R2 | `_replay_history()` 渲染 user 消息 | 恢复准确性 | P0 | 0.5-1天 | ✅ 已解决 (v2.16) |
| S-R3 | `--continue` 命令行支持 | CLI | P0 | 2-3天 | ✅ 已解决 (v2.16) |
| S-R5 | REPL 端会话浏览器 | 发现 | P0 | 2-3天 | ✅ 已解决 (v2.16) |
| S-R4-C | Resume 恢复 Cost 累计状态 | 状态恢复 | P1 | 1-2天 | ✅ 已解决 (`Session.resume` 已调用 `restore_cost_state_for_session`) |
| S-R6 | `--fork-session` 支持 | 会话管理 | P1 | 1-2天 | ✅ 已解决 (v2.16) |
| S-R4-M | Resume 恢复 session metadata | 状态恢复 | P2 | 1天 | ✅ 已解决 (v2.16): `ClawCodexExtREPL._load_session_metadata()` 加载 title/cwd/model/agent_name；`save_to_session_storage` 持久化 title/last_user_input；`chat()` 覆盖跟踪最后用户输入 |
| S-R4-A | Resume 恢复 Agent 设置 | 状态恢复 | P2 | 1-2天 | ✅ 已解决 (v2.16): `SessionMetadata.agent_name` 字段 + `_update_metadata_agent()` 持久化 agent 名称 |
| S-R4-T | 按自定义标题恢复 | 发现 | P2 | 1天 | ✅ 已解决 (v2.16): `ResumeConversation`（TUI）和 `session_browser.py`（REPL）均支持按标题搜索 |
| S-R4-CP | 交叉项目路径调整 | 准确性 | P2 | 1-2天 | ✅ 已解决 (v2.16): `_adjust_paths()` 完整实现 — 重写 tool_use 参数中 `path`/`file_path`/`directory` 等键；重写 tool_result content 中的路径文本；fallback 全局字符串替换 |
| S-R4-CK | Resume 一致性检查 | 健壮性 | P2 | 1天 | ✅ 已解决 (v2.16): `_check_chain_consistency()` 检查消息顺序 (user→assistant)、空 content、连续同名角色、链首/链尾角色 |
| S-R4-AT | Resume 指定消息位置 | 高级 | P3 | 2-3天 | ✅ 已解决 (v2.16): `--resume-session-at <msgId>` 参数 — 截断 conversation.messages 到指定索引 |
| Context Collapse 状态 | 按文件路径恢复 | `.jsonl` 文件路径 | ❌ (已归档，低优先级) |

> **建议实施顺序**：~~S-R1 → S-R2 → S-R3 → S-R4-C → S-R4-F → S-R4-T → S-R4-M → S-R4-A → S-R4-CP → S-R4-CK → S-R4-AT~~ ✅ 所有 P0-P3 缺口已在 v2.16 全部解决

---


*v2.15 更新：F-22 Phase A runtime-first 接线完成。`RuntimeContext.build()` 启动后台 cron 调度器；`src/repl/core.py` 注册 `replace_cron_tools()` + `attach_cron_runtime()` + `_drain_cron_outbox()`；REPL 主循环每条迭代前消费 `tool_context.outbox` 中的 `cron_prompt`/`cron_missed` 事件，注入为自动用户输入。Headless/TUI 通过共用 `RuntimeContext.build()` 路径获得调度器（TUI outbox drain 待后续）。271/271 orchestrator 测试通过。*


*2026-06-02 增量：F-45 落地。新增 `extensions/orchestrator/tool_event_log.py`（`ToolEventLog` 8 字段 frozen dataclass + `to_dict()`/`to_json()`）；`agent_runner.py:_append_tool_event_log` 落 `~/.clawcodex/tool-events/{run_id}/events.ndjson`，带嵌套 try/except + 50MB 单文件 rotate；`AgentSession.tool_events_path` 字段 + `session_context` 注入 `run_id` / `permission_mode` / `turn`；同步修复 `_handle_tool_call` 死代码调用链（run loop ToolCallEvent 分支原未调用，audit `approved` 字段会永远是 `None`——已加 `event = self._handle_tool_call(event, session_context)`）；`report_writer.RunReport.tool_events_path` 字段（末尾默认 `None`，向前兼容）+ `write()` dual-write NDJSON 到 `~/.clawcodex/reports/.../{run_id}.events.ndjson` + `_render_markdown` 追加 `Tool events: <path>` 行；`git_sync._write_report` 转发 `tool_events_path`；`WorkspaceConfig.gitignore_patterns` 默认 list 加 `.reports`；新增 `tests/test_orchestrator_f45_audit_bypass.py`（7 类 16 例）。回归：`tests/test_orchestrator_*.py` 271/271 + `tests/manual_e2e_f38.py` 4/4 + 新增 16/16 — 共 291 例全绿。*

*版本 v2.13 更新：新增 §3.1.10 Tool-call 审计旁路设计（F-45，📋 规划中，P1）。在 `agent_runner._handle_tool_call` 后加 NDJSON 旁路落 `~/.clawcodex/tool-events/{run_id}/events.ndjson`，与 permission_mode 解耦（bypass / dontAsk / acceptEdits / default 四种 mode 一视同仁全写）；扩展 `report_writer.RunReport.tool_events_path` 字段与 markdown 模板登记路径；dual-write 到 `~/.clawcodex/reports/.../{run_id}/` 持久化层。NDJSON 每行 8 字段：ts / tool / params / approved / deny_reason / permission_mode / turn / session_run_id。修复 TS 注释 "bypass = no logging" 在 Python 端的事实偏差——ApprovalPolicy 一直在跑，只是决策没落盘。*

*版本 v2.13 更新：新增 §5.2 permission_mode enum 正交拆分设计（F-46，📋 规划中，P2）。把 `permission_mode` 混合 enum 拆为三个正交字段 `interactive: bool` / `default_decision: Literal["allow","deny","ask"]` / `audit_log: Literal["none","minimal","full"]`。F-46.0（v2.13）只拆 `audit_log`，依赖 F-45 落地后端到端验证；`permission_mode` 保留为 backward-compat shim 标 deprecated。F-46.1（v2.15+）拆其余两字段，F-46.2（v2.16+）移除 `permission_mode`。三字段组合爆炸风险用 `validate()` 互斥规则 + 启动 warning 缓解。*

*F-47.1 (2026-06-02) v2.13 hotfix：F-47 原本保留的顶层 `settings.permission_mode` back-compat 读取通道在项目尚未发布的前提下直接删除（`SettingsSchema.permission_mode` 字段保留为兼容形态但启动时不再被读）。F-46 计划中的"标 deprecated → 打 warning → 移除"路径因此提前在 v2.13 完成第一步（直接删读取），F-46.2 的 deprecation 步骤 N/A。*

*版本 v2.0 更新：新增 F-35 二开特性可切换架构设计，Feature Toggle 系统 + 584 个内联修改文件特性提取方案。*

*版本 v2.3 更新：新增 3.1.5 Orchestrator 验证与报告闭环设计（F-38）。Sub-A 在 `HooksConfig` 增 `pre_commit` / `pre_push` / `post_sync` 三点，git_sync 在 commit/push 前后自动跑 verification gate（默认 `pytest -x`，用户可配 `test_command`）；Sub-B 新增 `report_writer` 生成 Markdown/JSON 报告，`IssueRecord` 增 `report_path` 字段，`git_sync._build_pr_body` 改模板插值；Sub-C 抽象 `TrackerAdapter.update_pull_request`，GitCode 客户端实现 `PATCH /repos/{owner}/{repo}/pulls/{id}`，把报告回写到 PR body 并合并为单条汇总评论；Sub-D 修复 `progress_reporter` 死代码，PhaseComplete 接入 ndjson event log。*

*版本 v2.4 更新：新增 3.1.6 Issue 重跑入口设计（F-39）。三种 label 表达重做意图：`agent:retry`（重置本地状态、关旧 PR、重跑整个 issue）、`agent:follow-up`（保留 PR、叠 commit、对应 F-37 follow-up）、`agent:blocked`（永久跳过）；comment 命令 `/agent retry` / `/agent follow-up` 由原作者或 maintainer 触发并限频；CLI 兜底 `issue retry --id 1 --mode reset`。Sub-A label 解析+意图分发，Sub-B 重置重跑，Sub-C follow-up 叠 commit，Sub-D comment 命令解析，Sub-E CLI 兜底，Sub-F 限频+角色校验。*

---

---

## 七、CCB 对标缺口（F-60~F-90 🔄）

> **说明**：本章合并原 §九（CCB 对标特性补缺规划）与 §十（Python 生态特性补缺规划），按子领域分组呈现。原 §九 的 CCB 覆盖状态总表、实施建议顺序、clawcodex 领先优势等内容保留在本章末尾。

---
### 7.0 Python 生态特性规划（合并来源：原 §十）


> 本节规划 CCB（claude-code-best）对标发现的 clawcodex 特性缺口。
> F-60~F-67 均参照 CCB 对应功能设计，以确保功能完整对标为目标。
>
> 注意：以下为 `CCB_MIGRATION_DESIGN.md`（CCB CLI/TUI → ClawCodex 迁移设计文档）各子系统在
> FEATURE_PLAN.md 中的覆盖状态评估，以及当前代码库的落地情况。

### CCB 子系统覆盖状态总览

根据对 `CCB_MIGRATION_DESIGN.md` 各子系统的逐一比对，以及代码库 `src/` 目录的实际实现检查，
以下表格反映当前覆盖状况（2026-06）：

| 子系统 | 迁移文档章节 | FEATURE_PLAN 条目 | 代码库状态 | 备注 |
|--------|-----------|-------------------|:----------:|------|
| **Bootstrap STATE 全局状态** | §3.1.1~3.1.5 | 无对应 F-number | ✅ 部分实现 | `src/state/app_state.py`, `cache_state.py`, `session_start.py`；mig 设计 8 子模块当前实装 3 个 |
| **Signal 事件通知** | §3.1.4 | 无对应 F-number | ✅ 已实现 | `src/utils/signal.py`（96 行，含 Signal dataclass + create_signal factory） |
| **两级状态架构** | §3.1.5 | 无对应 F-number | ✅ 已实现 | Bootstrap State (`src/state/`) + AppState Store (`src/state/app_state.py`) 已分离 |
| **AppState Store** | §3.1.6 | 无对应 F-number | ✅ 已实现 | `src/state/app_state.py` — `Store[AppState]` pub/sub + side-effect router |
| **Overlay/Escape 协调** | §3.1.7 | 无对应 F-number | ✅ 已实现 | Textual Screen 原生管理；`src/tui/app.py`（ext 中）处理 overlay 堆栈 |
| **命令系统框架** | §3.2.1~3.2.4 | 无对应 F-number | 📋 无独立 `src/commands/` | 斜杠命令通过 `src/command_system/` 路由，非迁移设计中的 Command dataclass 体系 |
| **Coordinator 系统** | §3.3.1~3.3.4 | **F-41 ✅ 已完成** | ✅ 已实现 | `src/coordinator/mode.py`, `prompt.py`, `worker_agent.py`；含 is_coordinator_mode、filter tools、worker agent 定义、system prompt |
| **TUI 屏幕层次** | §3.4.1 | 无对应 F-number | ✅ 已实现 | `src/tui/screens/` 含 14+ 个 Screen（repl, model_picker, theme_picker, permission_modal, diff_dialog, cost_threshold, history_search, resume_conversation 等）；`src/tui/state.py` 和 `app.py` 为 ext facade |
| **vim mode** | §3.4.3 | 无对应 F-number | ✅ 已实现 | `src/tui/vim.py` + 7 个 vim 辅助模块（buffer, find, operators, visual, state, persistent, text_objects） |
| **Provider Registry** | §3.5.1 | F-72（部分重叠） | ✅ 已实现 | Provider 系统在 `src/providers/` 中已有实现 |
| **MCP Client** | §3.5.2 | 无对应 F-number | ✅ 已实现 | `src/services/mcp/` 含 31 个文件，client, server, manager, transport, auth, telemetry 等 |
| **Auth 服务** | §3.5 | 无对应 F-number | ✅ 已实现 | `src/services/auth/` 含 auth.py, oauth 相关模块 |
| **Bridge 桥接** | §3.4.2 | 无对应 F-number | ✅ 已实现 | `src/services/bridge/` 含 auth, session, transport 模块 |
| **Swarm/Team 系统** | §3.3（协作） | 无对应 F-number | ✅ 已实现 | `src/services/swarm/` 含 mailbox, permissions, agent_name_registry, team_fi 等 |
| **Pipes IPC + LAN 群控** | §3.5.3 / §8.1 | **F-60 ✅ 已完成** | ✅ `src/services/pipe_ipc/` | UDS 命名管道、编解码、权限转发、注册表；967 行 + 11 测试 |
| **Plugin 系统** | §3.5 | **F-70 🔄 进行中** | 🔄 `src/plugins/`（1,070 行） | 注册表/加载器/依赖/校验/市场/LSP 集成/MCP 集成等基础框架已存在；Plugin 发现/沙箱隔离/生命周期待补 |
| **Computer Use** | §8.2 | **F-61 ✅ 已完成** | ✅ `src/services/computer_use/` | 跨平台截屏/键鼠/窗口/剪贴板；Linux scrot/xdotool + Null/DryRun；1797 行 + 15 测试 |
| **Chrome 自动化** | §8.2 | **F-62 ✅ 已完成** | ✅ `src/services/chrome/` | 浏览器控制：Playwright/MCP/Null 三后端 + Recording wrapper + 7 个 chrome_* 工具 |
| **Channels 通知** | — | **F-63 ✅ 已完成** | ✅ `src/services/channels/` | 飞书/Slack/Discord 推送；传输层重试；2097 行 + 18 测试 |
| **Voice Mode** | — | **F-64 🔄 进行中** | 🔄 `src/services/voice/`（188 行骨架） | `detection.py` + `stt.py` 抽象类已实现，运行时集成待补 |
| **Langfuse** | — | **F-65 ✅ 已完成** | ✅ `src/services/langfuse/`（933 行） | 客户端/Sink/Exporter 全链路：可观测性事件/元数据/导出 sink + Langfuse SDK 集成 + 优雅降级（49 测试） |
| **ACP 协议** | §8.3 | **F-66 📋 规划中** | ❌ 未实现 | Agent Communication Protocol |
| **Buddy/Proactive** | — | **F-67 ✅ 已完成** | ✅ `clawcodex_ext/buddy/`（1,371 行） | 8 模块完整实现（companion/observer/soul/sprites/types/prompt/notification/feature）；支持后台 AI 伴侣异步观察会话、主动调试建议、文件变更监听；已列为 Phase 5 解耦对象 |
| **Notifier + PreventSleep** | §8.3 | 无对应 F-number | ❌ 未实现 | 通知与防休眠服务 |
| **150+ CCB 特有工具** | §8.2 | **F-71 📋 规划中**（需展开工具清单） | 📋 部分 | 见下方 F-71 子特性表 |


### 7.1 进程间通信与远程控制（F-60 ✅）

#### F-60（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（337 行）已归档，此处仅保留状态跟踪。_

### 7.2 浏览器与桌面操控（F-60 ✅）

#### F-61（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（265 行）已归档，此处仅保留状态跟踪。_

#### F-62（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（220 行）已归档，此处仅保留状态跟踪。_

### 7.3 通知与语音（F-60 ✅）

#### F-63（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（197 行）已归档，此处仅保留状态跟踪。_

#### Voice Mode 语音输入（F-64 ✅）

**状态**: ✅ 已完成（接口层已完成） | **优先级**: P2 | **对标**: CCB Voice Mode

> `src/services/voice/` 含 `detection.py`（VoiceActivityDetector、VoiceActivityState、VoiceActivityConfig）和 `stt.py`（STTProvider 抽象类 + STTConfig + STTResult），但运行时集成与端到端实现待补齐。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P64-A | ASR 语音识别 | 对接豆包 doubaoime-asr / OpenAI Whisper 实现语音→文本 | 📋 规划中 | 3-5天 |
| P64-B | Push-to-Talk 语音交互 | 按键触发录音→释放即识别的交互模式 | 📋 规划中 | 3-5天 |
| P64-C | 音频流 WebSocket 传输 | 实时音频流通过 WebSocket 传输到 ASR 服务 | 📋 规划中 | 2-3天 |

#### 核心数据模型

```python
# src/services/voice/models.py
from dataclasses import dataclass
from enum import Enum

class ASRProvider(Enum):
    WHISPER_LOCAL = "whisper_local"       # 本地 Whisper 模型
    WHISPER_OPENAI = "whisper_openai"     # OpenAI Whisper API
    DOUBAO_IME = "doubaoime_asr"          # 豆包即时语音识别
    ALIYUN_ASR = "aliyun_asr"             # 阿里云语音识别

class TTSProvider(Enum):
    EDGE_TTS = "edge_tts"                 # 免费 Edge TTS
    OPENAI_TTS = "openai_tts"             # OpenAI TTS API
    DOUBAO_TTS = "doubao_tts"             # 豆包 TTS

@dataclass
class VoiceConfig:
    asr_provider: ASRProvider = ASRProvider.WHISPER_LOCAL
    tts_provider: TTSProvider = TTSProvider.EDGE_TTS
    push_to_talk_key: str = "V"           # 按键录音键
    language: str = "zh"                  # 识别语言
    silence_timeout: float = 1.5          # 静音超时停止录音（秒）
    sample_rate: int = 16000              # 采样率
    device_index: int | None = None       # 音频设备索引

@dataclass
class VoiceCommand:
    """语音识别结果。"""
    raw_text: str
    confidence: float = 1.0
    language: str = "zh"
    is_final: bool = True                 # False = 中间结果（流式）
    duration_ms: int = 0                  # 音频时长
```

#### 核心接口

```python
# src/services/voice/base.py
from abc import ABC, abstractmethod

class ASREngine(ABC):
    """语音识别引擎抽象。"""

    @abstractmethod
    async def transcribe(self, audio_data: bytes) -> VoiceCommand:
        """将音频数据（16kHz WAV/PCM）转为文本。"""

    @abstractmethod
    async def transcribe_stream(self, audio_stream) -> AsyncIterator[VoiceCommand]:
        """流式识别（返回中间+最终结果）。"""

    @abstractmethod
    async def warmup(self) -> None:
        """预加载模型（本地 Whisper）。"""


class TTSEngine(ABC):
    """文字转语音引擎抽象。"""

    @abstractmethod
    async def speak(self, text: str, output_path: str) -> str:
        """将文本转为语音并保存到文件，返回文件路径。"""

    @abstractmethod
    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        """流式 TTS（用于实时播放）。"""


class VoiceInputController:
    """语音输入控制器（录音→ASR→Tool 调用）。"""

    def __init__(self, asr: ASREngine, config: VoiceConfig | None = None):
        self._asr = asr
        self._config = config or VoiceConfig()
        self._recording = False

    async def start_recording(self) -> None:
        """开始录音（Push-to-Talk 按下时调用）。"""
        self._recording = True
        # 启动后台录音线程/协程
        self._audio_buffer = bytearray()

    async def stop_recording(self) -> VoiceCommand:
        """停止录音并执行 ASR 识别。"""
        self._recording = False
        audio = bytes(self._audio_buffer)
        return await self._asr.transcribe(audio)

    def _audio_callback(self, in_data: bytes, ...) -> None:
        """音频设备回调（由 sounddevice/pyaudio 驱动）。"""
        if self._recording:
            self._audio_buffer.extend(in_data)
```

#### 本地 Whisper 实现示例

```python
# src/services/voice/whisper_asr.py
import numpy as np
import whisper

class WhisperASREngine(ASREngine):
    """基于本地 Whisper 模型的 ASR 引擎。"""

    def __init__(self, model_size: str = "base"):
        self._model_size = model_size
        self._model = None

    async def warmup(self) -> None:
        self._model = whisper.load_model(self._model_size)

    async def transcribe(self, audio_data: bytes) -> VoiceCommand:
        if self._model is None:
            await self.warmup()
        audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        result = self._model.transcribe(audio_np, language="zh")
        return VoiceCommand(
            raw_text=result["text"].strip(),
            confidence=result.get("confidence", 1.0),
            language=result.get("language", "zh"),
        )

    async def transcribe_stream(self, audio_stream) -> AsyncIterator[VoiceCommand]:
        # 流式模式下每次累积 1s 音频后增量识别
        buffer = bytearray()
        async for chunk in audio_stream:
            buffer.extend(chunk)
            if len(buffer) >= 32000:  # ~1s 的 16kHz PCM
                yield await self.transcribe(bytes(buffer))
                buffer.clear()
```

#### Edge TTS 实现示例

```python
# src/services/voice/edge_tts.py
import edge_tts

class EdgeTTSEngine(TTSEngine):
    """基于微软 Edge TTS（免费）的 TTS 引擎。"""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self._voice = voice

    async def speak(self, text: str, output_path: str = "/tmp/tts.mp3") -> str:
        communicate = edge_tts.Communicate(text, self._voice)
        await communicate.save(output_path)
        return output_path

    async def speak_stream(self, text: str) -> AsyncIterator[bytes]:
        communicate = edge_tts.Communicate(text, self._voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
```

#### 集成到 Tool 工厂

```python
# src/services/voice/__init__.py
from clawcodex.config import settings

_voice_controller: VoiceInputController | None = None

def init_voice(config: VoiceConfig | None = None) -> VoiceInputController:
    global _voice_controller
    if _voice_controller is None:
        cfg = config or VoiceConfig(**settings.get("voice", {}))
        if cfg.asr_provider == ASRProvider.WHISPER_LOCAL:
            asr = WhisperASREngine()
        elif cfg.asr_provider == ASRProvider.WHISPER_OPENAI:
            asr = OpenAIWhisperASREngine()
        else:
            asr = WhisperASREngine()
        _voice_controller = VoiceInputController(asr, cfg)
    return _voice_controller

def build_voice_tools(controller: VoiceInputController) -> list[Tool]:
    return [
        Tool(name="voice_start_recording",
             description="开始语音输入（Push-to-Talk）",
             parameters={},
             call=lambda: controller.start_recording()),
        Tool(name="voice_stop_recording",
             description="停止录音并执行语音识别，返回识别文本",
             parameters={},
             call=lambda: controller.stop_recording()),
        Tool(name="voice_speak",
             description="文字转语音输出",
             parameters={"text": {"type": "string"}},
             call=lambda text: asyncio.run(tts_engine.speak(text))),
    ]
```

#### 依赖

- `openai-whisper`（本地 ASR，需 GPU 加速）
- `edge-tts`（免费 TTS）
- `sounddevice` 或 `pyaudio`（音频采集）
- `numpy`（音频数据处理）

---


### 7.4 可观测性与协议（F-60 ✅）

#### F-65（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（244 行）已归档，此处仅保留状态跟踪。_

#### ACP 协议支持（F-66 📋）

**状态**: 📋 规划中 | **优先级**: P2 | **对标**: CCB ACP (Agent Client Protocol)

#### 背景

ACP（Agent Client Protocol）是 Anthropic 与 Zed/Cursor 等 IDE 合作推出的 Agent-IDE 通信协议，支持会话恢复、Skills 桥接等功能。CCB 通过 `@agentclientprotocol/sdk` 原生支持 ACP。clawcodex 目前无对应实现。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P66-A | ACP SDK 基础协议实现 | 实现 ACP 协议核心：session/skill/tool 通信 | 📋 规划中 | 3-5天 |
| P66-B | Zed IDE 集成接入 | 通过 ACP 协议桥接到 Zed AI 插件 | 📋 规划中 | 2-3天 |
| P66-C | Cursor IDE 集成接入 | 通过 ACP 协议桥接到 Cursor | 📋 规划中 | 2-3天 |
| P66-D | 会话恢复与 Skills 桥接 | ACP session resume + skill 桥接 | 📋 规划中 | 2-3天 |

#### 核心数据模型

```python
# src/services/acp/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from datetime import datetime

class ACPMessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class ACPMessageType(Enum):
    SESSION_CREATE = "session/create"
    SESSION_RESUME = "session/resume"
    SESSION_END = "session/end"
    MESSAGE_SEND = "message/send"
    MESSAGE_STREAM = "message/stream"
    TOOL_CALL = "tool/call"
    TOOL_RESULT = "tool/result"
    SKILL_INVOKE = "skill/invoke"
    SKILL_RESULT = "skill/result"
    ERROR = "error"

@dataclass
class ACPMessage:
    """ACP 协议消息体（JSON-RPC over WebSocket/stdio）。"""
    type: ACPMessageType
    id: str = ""                          # 消息/请求 ID
    session_id: str = ""                  # 会话 ID
    role: ACPMessageRole = ACPMessageRole.USER
    content: str | dict | None = None
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class ACPSession:
    """ACP 会话信息。"""
    id: str
    created_at: str
    messages: list[ACPMessage] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    workspace_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

#### 核心接口

```python
# src/services/acp/base.py
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

class ACPTransport(ABC):
    """ACP 传输层抽象（stdio / WebSocket / TCP）。"""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def send(self, msg: ACPMessage) -> None: ...

    @abstractmethod
    async def receive(self) -> ACPMessage | None: ...

    @abstractmethod
    async def close(self) -> None: ...


class ACPServer(ABC):
    """ACP 协议服务端（接收 IDE 发起的会话请求）。"""

    @abstractmethod
    async def handle_session(self, transport: ACPTransport) -> None:
        """处理单个会话生命周期（创建→消息交换→结束）。"""

    @abstractmethod
    async def create_session(self, workspace_path: str) -> ACPSession:
        """创建新会话。"""

    @abstractmethod
    async def resume_session(self, session_id: str) -> ACPSession | None:
        """根据 session_id 恢复历史会话。"""

    @abstractmethod
    async def process_message(self, msg: ACPMessage) -> AsyncIterator[ACPMessage]:
        """处理用户消息，流式返回 Assistant 回复。"""

    @abstractmethod
    async def invoke_skill(self, skill_name: str, params: dict) -> dict:
        """通过 ACP 调用 Skill。"""


class ACPClient(ABC):
    """ACP 协议客户端（IDE 侧连接 ClawCodex）。"""

    @abstractmethod
    async def connect_to_agent(self, endpoint: str) -> None:
        """连接到正在运行的 ClawCodex Agent。"""

    @abstractmethod
    async def send_user_message(self, content: str) -> AsyncIterator[ACPMessage]:
        """发送用户消息并流式接收回复。"""

    @abstractmethod
    async def resume_session(self, session_id: str) -> AsyncIterator[ACPMessage]:
        """恢复历史会话。"""
```

#### Stdio 传输实现示例

```python
# src/services/acp/stdio_transport.py
import json, sys

class StdioACPTransport(ACPTransport):
    """基于 stdin/stdout 的 ACP 传输（Zed/Cursor 插件使用）。"""

    def __init__(self):
        self._reader = asyncio.StreamReader()
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        self._writer = sys.stdout

    async def send(self, msg: ACPMessage) -> None:
        line = json.dumps(dataclasses.asdict(msg), default=str) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

    async def receive(self) -> ACPMessage | None:
        data = await self._reader.readline()
        if not data:
            return None
        return ACPMessage(**json.loads(data))

    async def close(self) -> None:
        self._writer.close()
```

#### WebSocket 传输实现示例

```python
# src/services/acp/ws_transport.py
import json, asyncio
from aiohttp import web, ClientSession, WSMsgType

class WsACPTransport(ACPTransport):
    """基于 WebSocket 的 ACP 传输（远程 IDE 插件使用）。"""

    def __init__(self, ws=None):
        self._ws = ws

    async def connect(self, url: str) -> None:
        session = ClientSession()
        self._ws = await session.ws_connect(url)

    async def send(self, msg: ACPMessage) -> None:
        await self._ws.send_json(dataclasses.asdict(msg, default=str))

    async def receive(self) -> ACPMessage | None:
        msg = await self._ws.receive()
        if msg.type == WSMsgType.TEXT:
            return ACPMessage(**json.loads(msg.data))
        return None

    async def close(self) -> None:
        await self._ws.close()
```

#### ACP 服务端 WebSocket 入口

```python
# src/services/acp/server.py
from aiohttp import web

async def acp_ws_handler(request: web.Request) -> web.WebSocketResponse:
    """用于 aiohttp 路由的 WebSocket handler。"""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    transport = WsACPTransport(ws)
    server = ClawCodexACPServer()
    await server.handle_session(transport)
    return ws

def build_acp_server() -> web.Application:
    app = web.Application()
    app.router.add_get("/acp/ws", acp_ws_handler)
    return app
```

#### 集成到 Tool 工厂

```python
# src/services/acp/__init__.py
def build_acp_tools(server: ACPServer) -> list[Tool]:
    return [
        Tool(name="acp_list_sessions",
             description="列出所有活跃 ACP 会话",
             parameters={},
             call=lambda: server.list_sessions()),
        Tool(name="acp_invoke_skill",
             description="通过 ACP 协议调用 Skill",
             parameters={
                 "skill_name": {"type": "string"},
                 "params": {"type": "object"},
             },
             call=lambda skill_name, params: server.invoke_skill(skill_name, params)),
    ]
```

#### 依赖

- `aiohttp`（WebSocket 服务端/客户端）
- 可选：Zed / Cursor IDE 插件 SDK

---


### 7.5 高级 Agent 模式（F-60 ✅）

#### F-67（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（390 行）已归档，此处仅保留状态跟踪。_

#### Native 原生模块系统（Python 可实现部分）（F-81 🔭）

> **注意**: F-81 Native 原生模块系统已移至 §4.4（Architecture & SDK 下沉），此处保留用于 CCB 对标完整性参考。

#### 背景

CCB 使用 5 个 Rust/NAPI 原生模块处理性能敏感操作。clawcodex 作为 Python 项目，应在不引入 Rust 编译链的前提下，用纯 Python / C扩展 等价实现这些模块的核心功能。

| CCB 模块 | 原始语言 | Python 替代方案 | 可行性 |
|----------|:--------:|-----------------|:------:|
| `audio-capture-napi` | Rust/NAPI | `pyaudio` / `sounddevice` + `webrtcvad` VAD 检测 | ✅ 完全可行 |
| `color-diff-napi` | Rust/NAPI | `PIL.ImageChops.difference` + NumPy `mean_squared_error` | ✅ 完全可行 |
| `image-processor-napi` | Rust/NAPI | `Pillow` (crop/resize/encode/decode) | ✅ 完全可行 |
| `modifiers-napi` | Rust/NAPI | `pynput` / `evdev`（键盘修饰键状态检测） | ⚠️ 部分可行（Linux evdev 需 root） |
| `url-handler-napi` | Rust/NAPI | `webbrowser` + `xdg-open` / `desktop-entry` | ✅ 完全可行 |

#### 子特性分解

| 子特性 | 说明 | 优先级 |
|--------|------|:------:|
| F-81.1 | `clawcodex_ext/native/__init__.py` — 统一的原生模块注册表与懒加载基础设施 | P0 |
| F-81.2 | `clawcodex_ext/native/audio.py` — 麦克风音频捕获（前置 F-64 Voice Mode） | P0 |
| F-81.3 | `clawcodex_ext/native/image.py` — 截图差异对比与图像处理（前置 F-61 Computer Use） | P0 |
| F-81.4 | `clawcodex_ext/native/url_handler.py` — OS URL Scheme 注册（`clawcodex://`） | P1 |
| F-81.5 | `clawcodex_ext/native/modifiers.py` — 键盘修饰键检测（辅助 F-61） | P1 |
| F-81.6 | fallback 策略：当可选依赖缺失时降级为纯 Python 兜底 | P2 |

#### 架构设计

```
clawcodex_ext/native/
├── __init__.py          # NativeModuleRegistry + lazy loader
├── audio.py             # 音频捕获（pyaudio/sounddevice）
├── image.py             # 图像差异对比 + 处理（Pillow + NumPy）
├── url_handler.py       # URL Scheme 注册（webbrowser + xdg-utils）
└── modifiers.py         # 键盘修饰键检测（pynput/evdev）
```

```python
# clawcodex_ext/native/__init__.py
import importlib
from typing import Any, Protocol

class NativeModule(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def get_version(self) -> str: ...

class NativeModuleRegistry:
    """统一的原生模块注册表，懒加载 + 降级检查。"""
    _modules: dict[str, type[NativeModule]] = {}

    @classmethod
    def register(cls, name: str, mod_cls: type[NativeModule]) -> None:
        cls._modules[name] = mod_cls

    @classmethod
    def load(cls, name: str) -> NativeModule | None:
        """加载目标模块，缺失依赖时返回 None（调用方降级）。"""
        mod_cls = cls._modules.get(name)
        if mod_cls is None:
            return None
        try:
            instance = mod_cls()
            if instance.is_available():
                return instance
        except ImportError:
            pass
        return None
```

#### 音频捕获模块

```python
# clawcodex_ext/native/audio.py
import io
import wave
from typing import AsyncIterator

class AudioCaptureModule:
    name = "audio_capture"

    def is_available(self) -> bool:
        try:
            import pyaudio  # noqa: F401
            return True
        except ImportError:
            return False

    def get_version(self) -> str:
        return "1.0 (pyaudio)"

    async def record(
        self,
        duration_sec: float = 5.0,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> bytes:
        """录制麦克风音频，返回 WAV 字节。"""
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            input=True,
            frames_per_buffer=1024,
        )
        frames = []
        for _ in range(int(sample_rate / 1024 * duration_sec)):
            data = stream.read(1024)
            frames.append(data)
        stream.stop_stream()
        stream.close()
        p.terminate()

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"".join(frames))
        return buf.getvalue()

    async def stream(self) -> AsyncIterator[bytes]:
        """实时音频流（VAD 检测后输出片段）。"""
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1024,
        )
        try:
            while True:
                data = stream.read(1024)
                yield data
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
```

#### 图像差异对比模块

```python
# clawcodex_ext/native/image.py
import numpy as np
from PIL import Image

class ImageProcessorModule:
    name = "image_processor"

    def is_available(self) -> bool:
        try:
            import PIL  # noqa: F401
            import numpy  # noqa: F401
            return True
        except ImportError:
            return False

    def get_version(self) -> str:
        return "1.0 (Pillow + NumPy)"

    def compute_diff(self, img1_path: str, img2_path: str) -> float:
        """计算两张截图的像素差异比率 (0.0 ~ 1.0)。"""
        im1 = Image.open(img1_path).convert("RGB")
        im2 = Image.open(img2_path).convert("RGB")
        arr1 = np.array(im1, dtype=np.float32)
        arr2 = np.array(im2, dtype=np.float32)
        diff = np.mean((arr1 - arr2) ** 2)
        return float(diff / (255.0 ** 2))

    def crop_and_resize(
        self, image_path: str, box: tuple[int, int, int, int],
        size: tuple[int, int] | None = None,
        output_path: str | None = None,
    ) -> bytes:
        """裁剪并缩放截图。"""
        im = Image.open(image_path)
        cropped = im.crop(box)
        if size:
            cropped = cropped.resize(size, Image.LANCZOS)
        if output_path:
            cropped.save(output_path, "JPEG", quality=85)
        buf = io.BytesIO()
        cropped.save(buf, "JPEG", quality=85)
        return buf.getvalue()
```

#### URL Handler 模块

```python
# clawcodex_ext/native/url_handler.py
import os
import shutil
import webbrowser
from pathlib import Path

class UrlHandlerModule:
    name = "url_handler"

    def is_available(self) -> bool:
        return True  # webbrowser 是标准库

    def get_version(self) -> str:
        return "1.0 (stdlib)"

    def register_protocol(self, protocol: str = "clawcodex") -> bool:
        """注册 clawcodex:// URL Scheme（按 OS 平台）。"""
        import sys
        if sys.platform == "linux":
            desktop_file = Path.home() / ".local/share/applications"
            desktop_file.mkdir(parents=True, exist_ok=True)
            desktop_entry = desktop_file / f"{protocol}-handler.desktop"
            desktop_entry.write_text(
                f"[Desktop Entry]\n"
                f"Type=Application\n"
                f"Name=ClawCodex\n"
                f"Exec=clawcodex %u\n"
                f"MimeType=x-scheme-handler/{protocol};\n"
            )
            os.system(f"xdg-mime default {protocol}-handler.desktop x-scheme-handler/{protocol}")
            return True
        elif sys.platform == "darwin":
            # macOS: use open -b or URL event registration
            return False  # 需要原生代码
        elif sys.platform == "win32":
            # Windows: reg add HKEY_CLASSES_ROOT\clawcodex
            return False  # 需要原生代码
        return False

    def open_url(self, url: str) -> bool:
        """打开 clawcodex:// URL（启动本地实例）。"""
        return webbrowser.open(url)
```

#### 依赖

- `pyaudio`（音频捕获，可选）
- `Pillow` + `numpy`（图像处理，可选）
- `pynput`（修饰键检测，可选，Linux 需 `evdev`）
- 均为 optional-dependencies，缺失时模块 `is_available()` 返回 False

---

#### Remote Control Server 远程控制服务（F-82 🔄）

#### 背景

CCB 的 `remote-control-server` 是一个全功能 Web 服务 + Web 管理面板，提供远程会话管理、Worker 调度、环境管理、事件流推送和 ACP 协议中继。clawcodex 当前 `src/server/` 和 `src/remote/` 仅为空占位符。

#### 子特性分解

| 子特性 | 说明 | 优先级 |
|--------|------|:------:|
| F-82.1 | RCS 核心基础设施：FastAPI 应用 + asyncio 事件循环 + 配置加载 + 日志 | P0 |
| F-82.2 | 认证系统：API Key / JWT / CORS 中间件 | P0 |
| F-82.3 | 会话管理 API：会话 CRUD、List、详情 | P0 |
| F-82.4 | Worker 注册与调度：心跳检测、长轮询工作分发、断线检测 | P0 |
| F-82.5 | 事件流推送：SSE 流 + WebSocket 双通道 | P1 |
| F-82.6 | 环境管理：多机器部署、测试环境管理 | P1 |
| F-82.7 | ACP 协议中继：WebSocket/SSE 双向 ACP 桥接 | P1 |
| F-82.8 | 会话入口：从 RCS 远程发起新会话 | P1 |
| F-82.9 | Web 管理面板：React 前端或 Jinja2 简单面板 | P2 |

#### 架构设计

```
src/remote_control/
├── __init__.py            # 包初始化 + 版本
├── config.py              # 配置加载（端口、auth、数据库）
├── app.py                 # FastAPI 应用工厂 + 生命周期
├── auth/
│   ├── __init__.py
│   ├── api_key.py         # API Key 验证中间件
│   ├── jwt.py             # JWT 签发与验证
│   ├── cors.py            # CORS 配置
│   └── middleware.py      # 认证中间件（统一入口）
├── routes/
│   ├── __init__.py
│   ├── sessions.py        # 会话 CRUD (v1)
│   ├── workers.py         # Worker 注册/心跳/分发
│   ├── events.py          # SSE 事件流
│   ├── environments.py    # 环境管理
│   ├── session_ingress.py # 远程会话启动
│   └── web/               # Web 面板后端 API
│       ├── __init__.py
│       ├── control.py     # 控制台 API
│       ├── sessions.py    # 会话列表 API
│       └── auth.py        # 登录/登出
├── services/
│   ├── __init__.py
│   ├── work_dispatch.py   # Worker 工作分发逻辑
│   ├── store.py           # 内存/数据库存储抽象
│   └── automation_state.py# Worker 自动化状态跟踪
├── transport/
│   ├── __init__.py
│   ├── ws_handler.py      # WebSocket 处理器
│   ├── sse_writer.py      # SSE 写入器
│   ├── event_bus.py       # 内存事件总线（pub/sub）
│   └── acp_relay.py       # ACP 协议中继桥接
├── storage/
│   ├── __init__.py
│   ├── memory.py          # 内存存储（默认）
│   └── sqlite.py          # SQLite 持久化（可选）
└── web_frontend/          # Web 管理面板静态资源
    ├── index.html         # 简单 Jinja2 模板（P2 可替换为 React）
    └── static/
        ├── app.js
        └── style.css
```

#### 核心数据模型

```python
# src/remote_control/models.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

class WorkerStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"

@dataclass
class RemoteSession:
    id: str
    status: str  # "running" | "paused" | "completed" | "error"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    worker_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class Worker:
    id: str
    name: str
    status: WorkerStatus = WorkerStatus.OFFLINE
    last_heartbeat: datetime | None = None
    labels: dict[str, str] = field(default_factory=dict)
    current_session_id: str | None = None

@dataclass
class Environment:
    id: str
    name: str
    host: str
    port: int
    api_key: str
    labels: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
```

#### 认证中间件

```python
# src/remote_control/auth/middleware.py
import hmac
from fastapi import Request, HTTPException
from starlette.status import HTTP_401_UNAUTHORIZED

async def verify_api_key(request: Request, api_key: str) -> bool:
    """验证 API Key（恒定时间比较防时序攻击）。"""
    config = request.app.state.config
    stored = config.api_keys.get(api_key[:8])  # key_id 前缀
    if stored is None:
        return False
    return hmac.compare_digest(api_key, stored)

async def auth_middleware(request: Request, call_next):
    """统一认证中间件（API Key + JWT 双通道）。"""
    if request.url.path.startswith("/web/"):
        # Web 面板走 JWT Cookie
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)
        payload = verify_jwt(token, request.app.state.config.jwt_secret)
        request.state.user = payload
    elif request.url.path.startswith("/api/"):
        # API 走 X-API-Key Header
        api_key = request.headers.get("X-API-Key")
        if not api_key or not await verify_api_key(request, api_key):
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)
    return await call_next(request)
```

#### Worker 调度与长轮询

```python
# src/remote_control/services/work_dispatch.py
import asyncio
from datetime import datetime, timedelta

class WorkDispatcher:
    """Worker 工作分发引擎，支持长轮询。"""

    def __init__(self, store):
        self._store = store
        self._pending: dict[str, asyncio.Event] = {}  # worker_id → wait event

    async def register_worker(self, worker: Worker) -> None:
        """注册 Worker 并记录心跳。"""
        worker.status = WorkerStatus.ONLINE
        worker.last_heartbeat = datetime.utcnow()
        await self._store.save_worker(worker)

    async def wait_for_work(self, worker_id: str, timeout: int = 30):
        """长轮询等待分配工作（SSE 或轮询）。"""
        event = asyncio.Event()
        self._pending[worker_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None  # 超时返回空
        finally:
            self._pending.pop(worker_id, None)
        return await self._store.pop_pending_job(worker_id)

    async def dispatch_work(self, job: Job) -> str | None:
        """将工作分发给空闲 Worker。"""
        workers = await self._store.get_idle_workers(job.labels)
        if not workers:
            return None
        target = workers[0]
        await self._store.assign_job(job.id, target.id)
        # 唤醒长轮询
        event = self._pending.get(target.id)
        if event:
            event.set()
        return target.id

    async def check_heartbeats(self, timeout_sec: int = 60):
        """定期检查心跳，标记失联 Worker。"""
        threshold = datetime.utcnow() - timedelta(seconds=timeout_sec)
        for worker in await self._store.get_all_workers():
            if worker.last_heartbeat and worker.last_heartbeat < threshold:
                worker.status = WorkerStatus.OFFLINE
                await self._store.save_worker(worker)
```

#### FastAPI 应用工厂

```python
# src/remote_control/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动/关闭。"""
    # 启动后台心跳检查任务
    task = asyncio.create_task(
        app.state.dispatcher.check_heartbeats()
    )
    yield
    task.cancel()

def create_app(config: RCSConfig) -> FastAPI:
    app = FastAPI(title="ClawCodex RCS", lifespan=lifespan)
    app.state.config = config
    app.state.store = create_store(config)
    app.state.dispatcher = WorkDispatcher(app.state.store)
    app.state.event_bus = EventBus()

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 认证中间件
    app.middleware("http")(auth_middleware)

    # 注册路由
    from .routes import sessions, workers, events, environments
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(workers.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(environments.router, prefix="/api/v1")

    return app
```

#### 依赖

- `fastapi` + `uvicorn`（Web 框架）
- `PyJWT` / `python-jose`（JWT 认证）
- `sqlalchemy` / `aiosqlite`（持久化，可选）
- `websockets`（WebSocket 传输，可选）
- `httpx`（HTTP 客户端与 ACP 中继）

#### Hermes Gateway 参考实现（OpenAI 兼容 API 服务器）（F-90 ✅）

> **来源**: `hermes-agent` 项目，`gateway/platforms/api_server.py` (4305 行)
> **命令**: `hermes gateway run` | **默认端口**: `127.0.0.1:8642` | **认证**: `API_SERVER_KEY`
> **底层**: aiohttp | **协议**: AGPL-3.0
> **对标**: CCB `remote-control-server` / `openai-codex` API 兼容层

**本 F-Number 记录本项目已实现的功能完整实现**（已通过 `extensions/remote_api/` 落地 11 个模块 2597 行，含 completion/responses API、SSE 流式、Bearer 认证、CLI `clawcodex api serve` 子命令；测试见 `tests/remote_api/`），同时为 F-82 (Remote Control Server) 和 F-66 (ACP 协议) 提供具体架构参考。ClawCodex 可在实现 F-82 时选型复用以下设计模式。

##### 参考 API 端点

| 类别 | 端点 | 说明 |
|------|------|------|
| OpenAI 标准 | `POST /v1/chat/completions` | Chat Completions（stream/non-stream、工具调用、多模态） |
| OpenAI 标准 | `POST /v1/responses` | Responses API（`previous_response_id` 链式会话） |
| OpenAI 标准 | `GET /v1/models` | 模型列表 |
| 会话管理 | `GET|POST /api/sessions` | 会话 CRUD |
| 异步执行 | `POST /v1/runs` + `GET /v1/runs/{id}/events` | 异步 run + SSE 生命周期事件 |
| Cron 管理 | `GET|POST /api/jobs` | 定时任务 CRUD |
| 健康检查 | `GET /health` | 存活检测 |

##### 可复用设计模式

| 模式 | 说明 |
|------|------|
| SSE 流式工具事件 | `_write_sse_chat_completion()` 中 `hermes.tool.progress` 自定义事件推送 |
| 消息规范化 | `_normalize_chat_content()` 处理数组格式 content（Open WebUI 等前端差异） |
| 多模态兼容 | `_normalize_multimodal_content()` 处理图片等非文本内容 |
| 会话连续性 | `X-Hermes-Session-Id` 头 + `_derive_chat_session_id()` 指纹派生 |
| Agent LRU 缓存 | 每个会话缓存 AIAgent（上限 128 个，闲置 1h 淘汰） |
| 客户端断连处理 | `ConnectionResetError` 异常捕获 → `agent.interrupt()` 停止 LLM 调用 |
| 孤儿 Run 清理 | 后台定时 `_sweep_orphaned_runs()` 清理未消费的 SSE 流 |
| 端口冲突检测 | `connect()` 前置 `SO_STREAM` 探测拒绝端口冲突 |

##### 关键文件（参考路径）

| 文件 | 行数 | 作用 |
|------|:----:|------|
| `gateway/platforms/api_server.py` | 4305 | `APIServerAdapter` 核心实现 |
| `gateway/run.py` | ~850 | Gateway 主入口 `start_gateway()` |
| `hermes_cli/gateway.py` | ~700 | CLI `cmd_gateway()` 入口 |

##### F-82 选型建议

- 若 F-82 需 Open WebUI / LobeChat 等前端接入，建议优先适配 OpenAI `/v1/chat/completions` + `/api/sessions` 接口
- 消息规范化（`_normalize_chat_content`）可迁移为通用中间件
- SSE Tool Progress 事件可复用作为 F-82.5 的事件流实现方案
- LRU Agent 缓存方案可直接迁移（只需替换 Hermes 类型为 ClawCodex Agent 类型）

##### 依赖与协同（v3 新增）

- **F-82 ≠ Visualizer 的前置依赖**。Visualizer（多 Session 可视化分析平台）选择路径 B（独立 FastAPI app），不阻塞 F-82 落地。F-82 上线后可通过 `mount_viz(app: FastAPI)` 合并。
- SessionMetadata 缺字段（`end_time`、`context_tokens`、`detected_mode`、`config`）需在 SessionStorage 层补齐，建议作为 visualizer Phase 0 子任务，或分配新 F-N。

---

#### F-83（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（21 行）已归档，此处仅保留状态跟踪。_

#### F-84（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（22 行）已归档，此处仅保留状态跟踪。_

### 7.6 模板系统（F-60 ✅）

#### F-85（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（18 行）已归档，此处仅保留状态跟踪。_

#### F-86（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（19 行）已归档，此处仅保留状态跟踪。_

#### Workflow Scripts 工作流脚本（F-87 ✅）

**状态**: ✅ 已归档 | **优先级**: P2 | **对标**: CCB FEATURE_WORKFLOW_SCRIPTS

> **F-87（Workflow Scripts）** 已被 **声明式工作流引擎（F-1.10）** 和 **SOP 工作流模式（F-50.10~）** 取代。原串行步骤序列能力被 F-1.10 的 DAG 遍历引擎吸收，原 YAML 文件发现机制被 F-50.13 吸收。详见 §1.5.1（声明式工作流引擎）和 §4.2.2（SOP 工作流模式）。
>
> 以下原设计内容保留仅作历史参考：

CCB 的 WorkflowScripts 允许用户创建 `.claude/workflows/*.yml` 工作流定义文件，声明多 step 执行序列（每个 step 可指定 tool、agent、prompt），通过 `/workflows` 命令管理和触发。ClawCodex 的 Orchestrator 已有类似功能（issue → agent run 流水线），但面向最终用户的声明式工作流文件系统尚未规划。

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P87-A | 工作流 YAML schema 定义与解析器 | ✅ 已并入 F-50.13 | — |
| P87-B | 工作流文件发现（`~/.clawcodex/workflows/` + `.clawcodex/workflows/`） | ✅ 已并入 F-50.13 | — |
| P87-C | 多步执行引擎（串联 agent + tool 调用序列） | ✅ 已并入 F-1.10 | — |
| P87-D | 内置捆绑工作流（代码审查、依赖更新、发布流程等） | ✅ 已并入 F-50.14 | — |
| P87-E | CLI 命令（`/workflows list/run/show`）与自动补全 | ✅ 已统一为 `clawcodex-dev workflow run` | — |
| P87-F | 执行进度实时显示与错误恢复 | ✅ 已并入 F-1.16 | — |

**估算总工时**: 已吸收，不单独计算

---

#### F-88（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（17 行）已归档，此处仅保留状态跟踪。_

### CCB 对标实施总览

> ⚠️ **重要**: 经过对 `CCB_MIGRATION_DESIGN.md` 子系统逐一比对和代码库 `src/` 的实地检查，
> 以下基础设施已在代码中实现，**不需额外 F-number**：Signal 事件通知、Bootstrap STATE 框架（含 AppState Store 两级架构）、
> Coordinator 系统（F-41 ✅ 已完成）、TUI 全屏层次（14+ Screen）、vim mode、Provider Registry、MCP Client、Auth 服务、
> Bridge 桥接、Swarm/Team 系统。真正的增量缺口集中于 **F-60~F-67 的 8 个用户可见特性** + F-71 的 4 个待实现工具，
> 以及 Notifier/Pipes 插件。v2.18 新增 **F-83~F-88 共 6 个新识别特性**。

| 编号 | 特性 | 优先级 | 对标级别 | 状态 | 备注 |
|:----:|------|:------:|:--------:|:----:|:-----:|
| F-60 | Pipe IPC + LAN 群控 | P0 | 🔴 严重缺口 | ✅ 已完成 | `src/services/pipe_ipc/` 967 行 |
| F-61 | Computer Use 屏幕操控 | P0 | 🔴 严重缺口 | ✅ 已完成 | `src/services/computer_use/` 1797 行 |
| F-62 | Chrome 浏览器控制 | P1 | 🔄 重要缺口 | ✅ 已完成 | 1-2周 |
| F-63 | Channels 频道通知 | P1 | 🔄 重要缺口 | ✅ 已完成 | `src/services/channels/` 2097 行 |
| F-64 | Voice Mode 语音输入 | P2 | 🟢 增强体验 | 🔄 进行中（接口层已完成） | `src/services/voice/` 检测+STT 抽象类 188 行 |
| F-65 | Langfuse 可观测性 | P1 | 🔄 重要缺口 | ✅ 已完成 | `src/services/analytics/` + `src/services/langfuse/` 全链路 |
| F-66 | ACP 协议支持 | P2 | 🟢 增强体验 | 📋 规划中 | 1-2周 |
| F-67 | Buddy / Proactive | P2 | 🟢 增强体验 | ✅ 已完成 | `src/buddy/` 8 文件完整实现 |
| F-71 | 4 个未实现工具（Execute/RemoteTrigger/WebBrowser/Snip） | P1 | 🔄 重要缺口 | 🔄 进行中（SnipTool 已完成） | 剩余 3 工具待实现 |
| — | Notifier + PreventSleep 通知与防休眠服务 | P2 | 🟢 增强体验 | 📋 规划中 | 1周 |
| **F-70** | **Plugin 系统** | **P1** | 🔄 重要缺口 | 🔄 进行中 | `src/plugins/` 8 文件 1070 行基础框架 |
| **F-78** | **Issue 语义澄清** | **P1** | 🔄 重要缺口 | ✅ 已完成 | `extensions/orchestrator/clarification.py` + `clarification_queue.py` 865 行 |
| **F-80** | **Agent 间交互** | **P1** | 🔄 重要缺口 | ✅ 已完成 | `TaskInspectTool`+`TaskDirectivesTool` 642 行 |
| **F-83** | **Ultraplan 高级规划模式** | **P1** | 🔄 重要缺口 | ✅ 已完成 | `src/services/ultraplan/` 3454 行 |
| **F-84** | **Context Collapse 上下文折叠** | **P1** | 🔄 重要缺口 | ✅ 已完成 | `src/services/context_collapse/` 3366 行 |
| **F-85** | **Templates 模板系统** | **P1** | 🔄 重要缺口 | ✅ 已完成 | `src/services/templates/` 2076 行 |
| **F-86** | **Kairos / Brief 调度模式** | **P2** | 🟢 增强体验 | ✅ 已完成 | `src/services/kairos/` + `periodic/` 2022 行 |
| **F-87** | **Workflow Scripts 工作流脚本** | **P2** | 🟢 增强体验 | ✅ 已归档 | 已吸收至 F-1.10 / F-50.10~ |
| **F-88** | **Explore / Plan 内置 Agent** | **P2** | 🟢 增强体验 | 📋 规划中 | 1周 |

### 实施建议顺序（已落地特性说明）

```
建议优先实施剩余缺口：
F-62 (Chrome) ──→ F-65 (Langfuse) ──→ F-71 工具补齐 ──→ ~~F-87 (Workflow)~~ ──→ F-88 (Explore/Plan)
   ↑ 自动化             ↑ 可观测性              ↑ 4 个缺失工具           ↑ ~~工作流脚本~~ ✅已归档             ↑ 内置 Agent
   P1                  P1                      P1                       P2                              P2

F-64 (Voice Mode) ──→ F-66 (ACP) ──→ F-67 (Buddy/Proactive) ──→ 长期迭代
   P2                  P2                      P2
```

> 第一期 7 个特性（F-60/F-61/F-63/F-83/F-84/F-85/F-86）已于 2026-06-19 批次全部落地。F-87（Workflow Scripts）已被 F-1.10（声明式工作流引擎）和 F-50.10~（SOP 工作流模式）取代，不再作为独立缺口。剩余缺口：F-62（Chrome 自动化）、F-64（Voice Mode）、F-65（Langfuse）、F-66（ACP）、F-67（Buddy）、F-71（4 个工具）、F-88（Explore/Plan Agent），建议按低风险/高感知优先原则推进 F-62/F-65。

---

### clawcodex 对比 CCB 的领先优势

以下 5 项特性是 clawcodex **已有**而 CCB **缺失**的优势能力，应在补缺过程中保持并强化：

#### 优势 1: Orchestrator 自动 Issue→PR 流水线

| 子能力 | clawcodex | CCB |
|--------|-----------|-----|
| 4 Trackers (GitHub/Gitee/GitCode/Linear) | ✅ | ❌ |
| Issue 状态机 (6 状态) | ✅ | ❌ |
| Per-issue worktree 生命周期管理 | ✅ | ❌ |
| LiveView Dashboard (HTTP/SSE) | ✅ | ❌ |
| Operator Takeover | ✅ | ❌ |

> **保持策略**: 在 F-60 Pipe IPC 中为 Orchestrator 预留通信接口，使 Orchestrator 工作流可通过 Pipe IPC 通知其他实例。

#### 优势 2: Verification Gate（F-38 📋）

| 子能力 | clawcodex | CCB |
|--------|-----------|-----|
| pre-commit / pre-push / post-sync pytest 门禁 | ✅ | ❌ |
| Markdown + JSON 报告植入 PR body | ✅ | ❌ |

> **保持策略**: 确保新的 Computer Use / Chrome Use 功能产生的代码变更同样经过 Verification Gate。

#### 优势 3: SOP 编译器

| 子能力 | clawcodex | CCB |
|--------|-----------|-----|
| `workflow.md` → 多 Agent 系统 | ✅ | ❌ |
| SDK 接口→Tool 规范三层映射 | ✅ | ❌ |

> **保持策略**: 无冲突，保持现状。

#### 优势 4: LiteLLM Provider（100+ 模型统一接口）

| 子能力 | clawcodex | CCB |
|--------|-----------|-----|
| 单 `--provider litellm` 覆盖 100+ 模型 | ✅ | ❌ |
| Anthropic block → OpenAI block 自动转换 | ✅ | ❌ |
| Bedrock/Vertex/Azure/Together 等 | ✅ | ❌ |

> **保持策略**: 确保新增的 Langfuse + OpenTelemetry 追踪层兼容 LiteLLM provider wrapper。

#### 优势 5: Manager/Worker 增强通信（TaskInspect/TaskDirectives）

| 子能力 | clawcodex | CCB |
|--------|-----------|-----|
| 广播指令给所有 Worker | ✅ | ❌ |
| critical/high/normal 优先级队列 | ✅ | ❌ |
| Worker 权限模式独立控制 | ✅ | ❌ |
| 消息标签系统 | ✅ | ❌ |

> **保持策略**: F-60 Pipe IPC 可以扩展此模式到跨实例通信。

---

> 本节规划从 Python 生态适配角度发现的 clawcodex 特性缺口。
> F-68~F-74 均为 Python 标准库或成熟第三方库可实现的特性，无需绑定特定平台 API。

#### Feature Gate 运行时特性开关系统（F-68 📋）

**状态**: 📋 规划中 | **优先级**: P1

##### 背景

CCB 通过 Bun 编译期 `-d FEATURE_*` macro define 实现 65+ 编译时特性标志（`FEATURE_AGENT_TOOL`、`FEATURE_VERIFICATION_AGENT` 等），支持编译级条件编译去除未启用特性代码。Python 无编译宏机制，但可以通过**运行时装饰器 + 注册表 + JSON/YAML 配置**实现等价的特性开关系统，支持热切换。

##### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P68-A | FeatureRegistry 核心 | 全局注册表：注册/查询/枚举特性，支持依赖关系声明 | 📋 规划中 | 3-5天 |
| P68-B | @feature_gated 装饰器 | 工具函数/命令/前端组件的条件启用装饰器 | 📋 规划中 | 2-3天 |
| P68-C | JSON/YAML 配置文件 | `~/.clawcodex/features.json` 持久化特性开关配置 | 📋 规划中 | 1-2天 |
| P68-D | CLI 运行时切换 | `--enable-feature X --disable-feature Y` 命令行覆盖 | 📋 规划中 | 1-2天 |
| P68-E | 环境变量覆盖 | `CLAWCODEX_FEATURE_X=true` 环境变量级覆盖 | 📋 规划中 | 1天 |
| P68-F | 依赖性解析与冲突检测 | 自动检测特性依赖是否满足、互斥特性冲突 | 📋 规划中 | 2-3天 |

##### 架构建议

##### 包结构

```
src/services/feature_gate/
├── __init__.py           # 导出 FeatureRegistry 单例
├── registry.py           # FeatureRegistry 实现
├── decorators.py         # @feature_gated 装饰器
├── config.py             # JSON 配置加载/保存（复用 src/config.py）
├── cli.py                # CLI 命令绑定
└── types.py              # FeatureFlag dataclass
```

##### FeatureFlag 类型定义

```python
# src/services/feature_gate/types.py
from dataclasses import dataclass, field

@dataclass
class FeatureFlag:
    """单个特性标志的定义。"""
    name: str                              # 唯一标识，如 "FEATURE_AGENT_TOOL"
    default: bool = False                  # 默认启用状态
    deps: list[str] = field(default_factory=list)  # 依赖的特性列表
    mutex_with: list[str] = field(default_factory=list)  # 互斥特性列表
    description: str = ""                  # 特性说明
```

##### FeatureRegistry 实现

```python
# src/services/feature_gate/registry.py
import os
from .types import FeatureFlag

# 环境变量前缀
ENV_PREFIX = "CLAWCODEX_FEATURE_"

class FeatureRegistry:
    """全局特性注册表，单例。"""

    _features: dict[str, FeatureFlag] = {}
    _overrides: dict[str, bool] = {}          # CLI/env 运行时覆盖

    def register(self, name: str, default: bool = False,
                 deps: list[str] = None, mutex_with: list[str] = None,
                 description: str = "") -> None:
        if name in self._features:
            raise ValueError(f"Duplicate feature flag: {name}")
        self._features[name] = FeatureFlag(
            name=name, default=default,
            deps=deps or [], mutex_with=mutex_with or [],
            description=description,
        )

    def is_enabled(self, name: str) -> bool:
        """解析优先级：CLI arg > env var > config file > default"""
        # 1) CLI 运行时覆盖（最高优先级）
        if name in self._overrides:
            return self._overrides[name]
        # 2) 环境变量 CLAWCODEX_FEATURE_<NAME>=true/false
        env_val = os.environ.get(f"{ENV_PREFIX}{name}")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        # 3) 配置文件 ~/.clawcodex/features.json
        config_val = self._load_config().get(name)
        if config_val is not None:
            return config_val
        # 4) 默认值
        flag = self._features.get(name)
        return flag.default if flag else False

    def enable(self, name: str) -> None:
        self._overrides[name] = True

    def disable(self, name: str) -> None:
        self._overrides[name] = False

    def list_features(self) -> list[FeatureFlag]:
        return list(self._features.values())

    # ---- 配置加载 ----
    _config_cache: dict[str, bool] | None = None
    def _load_config(self) -> dict[str, bool]:
        if self._config_cache is None:
            import json
            path = Path.home() / ".clawcodex" / "features.json"
            if path.exists():
                with open(path) as f:
                    self._config_cache = json.load(f)
            else:
                self._config_cache = {}
        return self._config_cache

    def save_config(self) -> None:
        """将当前 overrides 持久化到 features.json"""
        import json
        path = Path.home() / ".clawcodex" / "features.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: flag.default for name, flag in self._features.items()}
        data.update(self._overrides)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self._config_cache = None  # 清除缓存

    def check_deps(self, name: str) -> list[str]:
        """检查特性的依赖是否满足，返回缺失的依赖列表。"""
        flag = self._features.get(name)
        if not flag or not flag.deps:
            return []
        return [dep for dep in flag.deps if not self.is_enabled(dep)]

    def check_mutex(self, name: str) -> list[str]:
        """检查是否与已启用的互斥特性冲突，返回冲突列表。"""
        flag = self._features.get(name)
        if not flag or not flag.mutex_with:
            return []
        return [m for m in flag.mutex_with if self.is_enabled(m)]
```

##### @feature_gated 装饰器实现

```python
# src/services/feature_gate/decorators.py
import functools
from .registry import FeatureRegistry  # 假定已初始化全局单例

_registry: FeatureRegistry | None = None

def get_registry() -> FeatureRegistry:
    global _registry
    if _registry is None:
        _registry = FeatureRegistry()
    return _registry

def feature_gated(feature_name: str, fallback=None):
    """条件启用装饰器。

    - 用于类：如果特性禁用，用 fallback 替代
    - 用于函数：如果特性禁用，返回 fallback 值或跳过执行
    """
    def decorator(obj):
        if not get_registry().is_enabled(feature_name):
            return fallback if fallback is not None else obj
        return obj
    return decorator

def feature_gated_class(name: str, fallback_cls=None):
    """类级别的条件注册辅助函数。"""
    def wrapper(cls):
        registry = get_registry()
        if registry.is_enabled(name):
            # 检查依赖和互斥
            missing = registry.check_deps(name)
            if missing:
                raise RuntimeError(
                    f"Feature '{name}' requires: {missing}"
                )
            conflict = registry.check_mutex(name)
            if conflict:
                raise RuntimeError(
                    f"Feature '{name}' conflicts with: {conflict}"
                )
            return cls
        return fallback_cls if fallback_cls else cls
    return wrapper
```

##### 条件注册用法

```python
# 在 build_default_registry() 中
from src.services.feature_gate.decorators import get_registry

registry = get_registry()
registry.register("FEATURE_AGENT_TOOL", default=True,
                  deps=[], description="子 Agent 生成工具")
registry.register("FEATURE_VERIFICATION_AGENT", default=True,
                  deps=["FEATURE_AGENT_TOOL"],
                  description="计划验证 Agent")

if registry.is_enabled("FEATURE_VERIFICATION_AGENT"):
    tool_registry.register(VerificationAgentTool)

# CLI 运行时切换
# clawcodex-dev --enable FEATURE_AGENT_TOOL --disable FEATURE_VERIFICATION_AGENT
```

##### 集成点

- **CLI 入口** (`src/cli.py`)：增加 `--enable` / `--disable` 参数，启动前调用 `registry.enable()` / `registry.disable()`
- **配置持久化**：复用 `src/config.py` 的 `~/.clawcodex/` 目录，新增 `features.json` 文件（独立于 `config.json`）
- **工具注册** (`src/tool_system/defaults.py`)：在 `build_default_registry()` 中加入 `feature_gated` 条件注册
- **Agent 循环** (`src/query/`)：关键决策点查询 `registry.is_enabled()` 判断是否启用 verification / memory 等步骤

##### 依赖

- Python `functools` / `inspect` / `os.environ`（标准库）
- 配置存储复用 `src/config.py` 的 `~/.clawcodex/` 目录 + `Path.home()`
- 无第三方依赖

---

#### Budget / Poor Mode 资源节俭模式（F-69 🔄）

**状态**: 🔄 进行中 | **优先级**: P1

> `clawcodex_ext/query/token_budget.py`（159 行）已有 BudgetTracker、ContinueDecision、StopDecision、token parsing 完整实现；Token 成本控制与延续/停止决策已可运行。剩余：与 Agent 循环深度集成（token_budget checkpoint 注入 query pipeline）待补充。

##### 背景

CCB 的 `/poor` 命令开启「穷鬼模式」，跳过高消耗步骤（`extract_memories`、`verification_agent`），减小 context 窗口，减少 API token 消耗。clawcodex 当前无等价机制，用户无法在简单任务中自主降低资源消耗。

##### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P69-A | BudgetMode 配置模型 | 定义节俭等级（off/light/medium/aggressive）、各等级行为矩阵 | 📋 规划中 | 2-3天 |
| P69-B | Agent 循环节俭钩子 | 在 query/agent loop 关键点插入节俭检查（跳过 memory recall、缩短思考预算等） | 📋 规划中 | 3-5天 |
| P69-C | Tool 级别节俭策略 | 降低搜索深度、禁用高消耗工具、减少结果条数 | 📋 规划中 | 2-3天 |
| P69-D | `/budget` CLI 斜杠命令 | 运行时切换节俭模式，查看当前消耗统计 | 📋 规划中 | 2-3天 |
| P69-E | Token 用量实时统计与告警 | 实时显示当前 session token 消耗，超阈值自动降级 | 📋 规划中 | 3-5天 |

##### 行为矩阵设计

| 行为 | off | light | medium | aggressive |
|------|:---:|:-----:|:------:|:----------:|
| extract_memories | ✅ | ✅ | ❌ | ❌ |
| verification_agent | ✅ | ❌ | ❌ | ❌ |
| search_depth | 10 | 5 | 3 | 1 |
| max_tool_calls/turn | 20 | 10 | 5 | 3 |
| context_window | max | 80% | 50% | 30% |
| 自动 Web 搜索 | ✅ | ✅ | ❌ | ❌ |

##### Agent 循环 Hook 点（具体集成位置）

```python
# src/query/query.py（或等价位置）—— Agent loop 主循环
class AgentLoop:
    def __init__(self, config: AgentConfig):
        self.budget = BudgetModeManager(config.budget_mode or "off")
        self.token_counter = TokenCounter()

    async def run(self, conversation):
        # ═══ Hook 点 1：Memory Recall（extract_memories）═══
        if self.budget.is_enabled("extract_memories"):
            memories = await self._extract_memories(conversation)
        else:
            memories = []
            logger.info("Budget mode: skipping extract_memories")

        # ═══ Hook 点 2：Agent loop 最大轮次限制 ═══
        max_turns = self.budget.get("max_tool_calls/turn")
        for turn in range(max_turns):
            # ═══ Hook 点 3：Verification Agent ═══
            if self.budget.is_enabled("verification_agent"):
                await self._run_verification(...)

            # ═══ Hook 点 4：Tool 调用消耗控制 ═══
            tool_result = await self._call_tool(...)
            self.token_counter.add(tool_result.token_usage)
            if self.token_counter.exceeds(self.budget.get("context_window")):
                logger.warning("Token budget exceeded, triggering auto-downgrade")
                current_level = self.budget.downgrade()

            # ═══ Hook 点 5：Web 搜索条件启用 ═══
            if tool_result.requires_web_search:
                if not self.budget.is_enabled("auto_web_search"):
                    continue  # 跳过 Web 搜索
```

##### 配置模型集成

```python
# src/models/configs.py 或 AgentConfig
@dataclass
class BudgetConfig:
    mode: str = "off"                     # off/light/medium/aggressive
    token_limit: int = 0                  # per-session token 阈值
    auto_downgrade: bool = False          # 超阈值自动降级
    downgrade_to: str = "medium"           # 降级目标

# 注入点：
# - src/query/config.py: QueryConfig 增加 budget 字段
# - src/cli.py: 增加 --budget light/medium/aggressive 参数
# - 斜杠命令注册: src/command_system/builtins.py 增加 /budget
```

##### 依赖

- 无第三方依赖
- 需集成到 `AgentConfig` / `SessionConfig` 中
- F-68 Feature Gate 可作为底层开关机制复用

---

#### Plugin 插件系统基础框架（F-70 📋）

**状态**: 📋 规划中 | **优先级**: P1

##### 背景

CCB 具备完整的 Plugin Marketplace 体系（安装/卸载/启用/禁用/浏览）。clawcodex 目前完全缺失插件化能力——所有扩展能力均通过硬编码集成或 `clawcodex_ext/` 二开目录实现。缺乏标准化的第三方插件安装与生命周期管理接口。

##### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P70-A | Plugin 协议/基类 | `BasePlugin` 接口定义（`on_load`/`on_unload`/`register_tools`/`register_commands`） | 📋 规划中 | 3-5天 |
| P70-B | Plugin 发现机制 | 扫描 `~/.clawcodex/plugins/` + `site-packages` entry_points | 📋 规划中 | 2-3天 |
| P70-C | Plugin 生命周期管理 | install/uninstall/enable/disable/upgrade 命令族 | 📋 规划中 | 5-7天 |
| P70-D | 沙箱隔离 | subprocess 隔离插件进程，通过 IPC 通信 | 📋 规划中 | 5-7天 |
| P70-E | Plugin 清单与元数据 | `plugin.yaml`/`pyproject.toml [tool.clawcodex.plugins]` 清单格式 | 📋 规划中 | 2-3天 |

##### BasePlugin 协议（精确接口）

```python
# src/services/plugin_system/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

class BasePlugin(ABC):
    """所有插件必须实现的基类。"""

    # 元数据（子类覆盖）
    name: str = ""
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    async def on_load(self, context: "PluginContext") -> None:
        """插件加载时调用。

        PluginContext 包含：
        - registry: 工具注册表的引用，用于注册/注销工具
        - command_system: CLI 命令系统，用于注册斜杠命令
        - config: 插件配置字典
        - data_dir: 插件数据目录的 Path
        """
        ...

    @abstractmethod
    async def on_unload(self) -> None:
        """插件卸载时调用。清理资源（关闭连接、释放文件句柄等）。"""
        ...

    async def on_enable(self) -> None:
        """插件启用时调用（可选覆盖）。"""
        pass

    async def on_disable(self) -> None:
        """插件禁用时调用（可选覆盖）。"""
        pass

    def get_tools(self) -> list[Any]:
        """返回此插件提供的工具列表。

        返回的 Tool 实例（通过 build_tool() 创建）会在 on_load 后
        自动通过 registry.register() 注册。
        默认返回空列表，子类按需覆盖。
        """
        return []

    def get_commands(self) -> list[dict]:
        """返回此插件提供的斜杠命令列表。

        每个命令格式: {"name": str, "handler": callable, "description": str}
        默认返回空列表，子类按需覆盖。
        """
        return []


@dataclass
class PluginContext:
    """插件运行时上下文，通过 on_load() 注入。"""
    registry: "ToolRegistry"           # 工具注册表（用于 register/unregister）
    command_system: "CommandSystem"    # 命令系统（用于注册斜杠命令）
    config: dict[str, Any]             # 插件配置
    data_dir: Path                     # 插件数据持久化目录
```

##### Plugin 示例

```python
# ~/.clawcodex/plugins/todo_manager/__init__.py
from src.services.plugin_system.base import BasePlugin, PluginContext
from src.tool_system.build_tool import build_tool

class TodoPlugin(BasePlugin):
    name = "todo-manager"
    version = "1.0.0"
    description = "Manage todo lists"

    async def on_load(self, ctx: PluginContext):
        # 通过 PluginContext 访问框架能力
        self.data_file = ctx.data_dir / "todos.json"
        # ctx.registry 已在 base.py 中通过 get_tools() 自动注册
        # ctx.command_system 同理通过 get_commands() 自动注册

    async def on_unload(self):
        self.data_file = None

    def get_tools(self):
        return [
            build_tool(
                name="todo_add",
                input_schema={...},
                call=self._add_todo,
                description="添加待办事项",
            ),
        ]

    def get_commands(self):
        return [
            {"name": "todo", "handler": self._cmd_todo, "description": "Manage todos"},
        ]
```

##### 架构

```python
# src/services/plugin_system/
plugin_system/
├── base.py              # BasePlugin + PluginContext（协议类）
├── registry.py          # PluginRegistry（注册/发现/生命周期管理）
├── loader.py            # PluginLoader（importlib + entry_points 发现）
├── sandbox.py           # PluginSandbox（可选子进程隔离）
├── manager.py           # PluginManager（CLI 命令绑定）
└── schema.py            # PluginManifest（pydantic model 插件元数据）
```

##### 插件发现路径

```python
# 1. Python entry_points (pip 安装的包)
from importlib.metadata import entry_points
plugins = entry_points(group="clawcodex.plugins")

# 2. 用户目录手动安装
~/.clawcodex/plugins/
└── my-plugin/
    ├── plugin.yaml    # name, version, author
    └── __init__.py    # implements BasePlugin

# 3. 项目级插件 (repo 自带)
.clawcodex/plugins/
```

##### 依赖

- `importlib.metadata`（Python 3.8+ 标准库）
- `PyYAML`（yaml 配置解析，已有依赖）
- `pluggy`（可选，复用 pytest 插件框架，Python 纯实现）

---

#### 内置工具补齐（缺失工具批量实现）（F-71 📋）

**状态**: 📋 规划中 | **优先级**: P1

##### 背景

对比 CCB 的 60 个内置工具，clawcodex 当前 `tool_system/tools/` 仅约 46 个工具。缺失的约 14 个工具分布在 Agent 系统、Web 自动化、上下文检查、监控、通知等领域。多数工具可通过 Python 标准库或成熟第三方库直接实现。

##### 子特性分解

下表映射自 `CCB_MIGRATION_DESIGN.md §8.2` 的 15 个 CCB 特有工具，标注了代码库中现有实现状态：

| 编号 | 工具名(CCB) | CCB 来源 | clawcodex 实现 | 代码状态 |
|:----:|------------|---------|:----------------:|:--------:|
| P71-A | **AgentTool** | `@claude-code-best/builtin-tools` | ✅ `src/tool_system/tools/agent.py` | 已完成 |
| P71-B | **SkillTool** | builtin | ✅ `src/tool_system/tools/skill.py` | 已完成 |
| P71-C | **SendMessageTool** | builtin | ✅ `src/tool_system/tools/send_message.py` | 已完成 |
| P71-D | **TaskStopTool** | builtin | ✅ `src/tool_system/tools/task_stop.py` | 已完成 |
| P71-E | **TeamCreateTool** | builtin | ✅ `src/tool_system/tools/team.py` | 已完成 |
| P71-F | **TeamDeleteTool** | builtin | ✅ `src/tool_system/tools/team.py` | 已完成 |
| P71-G | **BriefTool** | builtin | ✅ `src/tool_system/tools/brief.py` | 已完成 |
| P71-H | **ExitPlanModeTool** | builtin | ✅ `src/tool_system/tools/plan_mode.py` | 已完成 |
| P71-I | **EnterPlanModeTool** | builtin | ✅ `src/tool_system/tools/plan_mode.py` | 已完成 |
| P71-J | **LSPTool** | builtin | ✅ `src/tool_system/tools/lsp.py` | 已完成 |
| P71-K | **ExecuteTool** | builtin | 📋 待实现 | 缺失 |
| P71-L | **CronCreate/Delete/ListTool** | builtin | ✅ `src/tool_system/tools/cron.py` | 已完成 |
| P71-M | **RemoteTriggerTool** | builtin | ❌ 待实现 | 缺失 |
| P71-N | **WebBrowserTool** | builtin | 📋 待实现 | 需 `playwright` |
| P71-O | **SnipTool** | builtin | ❌ 待实现 | 缺失 |

仅 **P71-K (ExecuteTool)**、**P71-M (RemoteTriggerTool)**、**P71-N (WebBrowserTool)**、**P71-O (SnipTool)** 4 个工具尚未实现。具体计划：

| 待实现工具 | 说明 | 依赖 | 预计工时 |
|-----------|------|:----:|:--------:|
| **ExecuteTool** | 代理工具调用执行，将另一个工具的调用委托给子 Agent | 无 | 3-5天 |
| **RemoteTriggerTool** | 远程触发工具，调用远程 clawcodex 实例上的操作 | `httpx` | 3-5天 |
| **WebBrowserTool** | 浏览器控制（打开 URL、点击、填表、截图） | `playwright` | 5-7天 |
| **SnipTool** | History snip — 截取历史消息片段用于上下文 | 无 | 2-3天 |

##### 实现模式（参考 `src/tool_system/build_tool.py`）

⚠️ **注意**: clawcodex 不使用 `BaseTool` 继承模式，而是使用 `Tool` dataclass + `build_tool()` 工厂函数模式。每个工具是一个通过 `build_tool()` 创建的 `Tool` 实例，核心字段如下：

| 字段 | 类型 | 说明 | 必需 |
|------|------|------|:----:|
| `name` | `str` | 工具名称（唯一标识） | ✅ |
| `input_schema` | `Mapping[str, Any]` | JSON Schema 格式的输入参数定义 | ✅ |
| `call` | `(dict, ToolContext) -> ToolResult` | 工具执行函数（同步或异步均可，框架自动适配） | ✅ |
| `description` | `str \| Callable` | 工具描述字符串或动态描述函数 | ✅ |
| `prompt` | `str \| Callable` | 工具在 system prompt 中的描述 | 推荐 |
| `is_enabled` | `Callable[[], bool]` | 是否启用（默认返回 True） | 可选 |
| `aliases` | `tuple[str, ...]` | 别名列表 | 可选 |
| `is_read_only` | `Callable[[dict], bool]` | 是否只读（影响权限检查） | 可选 |

```python
# ===== 正确实现示例 =====
# 文件位置：src/tool_system/tools/web_browser.py

from typing import Any
from src.tool_system.build_tool import build_tool, ToolResult

async def _web_browser_call(input: dict[str, Any], context: "ToolContext") -> ToolResult:
    """WebBrowserTool 的调用函数"""
    action = input.get("action")
    url = input.get("url")
    selector = input.get("selector")

    try:
        # 延迟导入 playwright，避免非必需环境安装
        from playwright.async_api import async_playwright

        if not hasattr(_web_browser_call, "_browser"):
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            _web_browser_call._browser = browser
            _web_browser_call._page = page

        page = _web_browser_call._page

        if action == "navigate":
            await page.goto(url, wait_until="networkidle")
            return ToolResult(name="web_browser", output={"status": "loaded", "url": url})
        elif action == "screenshot":
            bytes_data = await page.screenshot(full_page=True)
            return ToolResult(name="web_browser", output={"screenshot_size": len(bytes_data)})
        elif action == "click":
            await page.click(selector)
            return ToolResult(name="web_browser", output={"status": "clicked", "selector": selector})
        else:
            return ToolResult(name="web_browser", output={"error": f"Unknown action: {action}"}, is_error=True)
    except Exception as e:
        return ToolResult(name="web_browser", output={"error": str(e)}, is_error=True)


# 使用 build_tool 创建 Tool 实例
WebBrowserTool = build_tool(
    name="web_browser",
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "click", "type", "screenshot"],
                "description": "要执行的操作类型",
            },
            "url": {
                "type": "string",
                "description": "目标 URL（仅在 navigate 时需要）",
            },
            "selector": {
                "type": "string",
                "description": "CSS 选择器（仅在 click/type 时需要）",
            },
            "text": {
                "type": "string",
                "description": "要输入的文本（仅在 type 时需要）",
            },
        },
        "required": ["action"],
    },
    call=_web_browser_call,
    description=lambda _input: "控制浏览器打开网页、点击、填表、截图（基于 Playwright）",
    prompt="""Web Browser 工具：打开 URL、点击元素、输入文本、截图。适用于需要浏览器渲染的内容。""",
    aliases=("browser", "chrome"),
    is_read_only=lambda _input: _input.get("action") == "screenshot",
    is_enabled=lambda: _check_playwright_available(),  # 动态检测 playwright 是否安装
)
```

##### 工具注册

所有新工具通过 `tool_registry.register()` 注册。可选通过 F-68 Feature Gate 控制启用：
```python
if registry.is_enabled("FEATURE_AGENT_TOOL"):
    tool_registry.register(AgentTool)
```

##### 依赖

- `playwright`（WebBrowserTool）
- `plyer` 或 `notify-py`（PushNotificationTool）
- `ptyprocess`（TerminalCaptureTool）
- 其余工具无第三方依赖

---

#### Multi-API 原生适配器扩展（F-72 📋）

**状态**: 📋 规划中 | **优先级**: P1

##### 背景

CCB 实现了 OpenAI/Gemini/Grok 三套独立 API 适配器（各有独立的 client 初始化、流式适配、模型映射表和错误处理）。clawcodex 通过 LiteLLM 间接支持 100+ 后端，但缺乏原生 SDK 适配器——这意味着某些 API 原生特性（如 Gemini 的 SafetySetting、OpenAI 的 structured output `response_format`、Grok 的 function calling 变体）可能无法通过 LiteLLM 泛化层完全暴露。

##### 子特性分解

| 编号 | 子特性 | 说明 | Python 依赖 | 预计工作量 |
|:----:|--------|------|:-----------:|:----------:|
| P72-A | OpenAI 原生适配器 | 使用 `openai` SDK 实现完整 API 调用链（stream/structured output/function call） | `openai` | 3-5天 |
| P72-B | Gemini 原生适配器 | 使用 `google-genai` SDK 实现 Gemini 完整调用（Safety/grounding/model 切换） | `google-genai` | 3-5天 |
| P72-C | Grok/xAI 原生适配器 | 使用 `openai` SDK（兼容接口）或 `requests` 实现 Grok 调用 | `requests` | 2-3天 |
| P72-D | 原生适配器自动选择 | 根据 `--provider` 自动选择原生适配器或回退到 LiteLLM | 无 | 2-3天 |
| P72-E | 平台专有特性映射 | 将各 API 专有能力（Safety/Grounding/TTS）映射为 Provider 能力标记 | 无 | 3-5天 |

##### 架构

```python
# src/providers/native/
native/
├── __init__.py           # 自动发现与注册 + NativeProviderFactory
├── base.py               # NativeProvider 基类（继承 BaseProvider）
├── capabilities.py       # 能力标记注册表
├── openai_adapter.py     # OpenAI 原生
├── gemini_adapter.py     # Gemini 原生
└── grok_adapter.py       # Grok 原生
```

##### NativeProvider 基类（继承现有关）

```python
# src/providers/native/base.py
from src.providers.base import BaseProvider, ChatResponse

class NativeProvider(BaseProvider):
    """原生 SDK 适配器的基类。

    继承自现有的 BaseProvider，保持 chat() / chat_stream() 接口不变。
    新增 capabilities 注册表用于标记平台专有能力。
    """

    # 平台专有能力标记（子类覆盖）
    capabilities: set[str] = set()

    @classmethod
    def check_capabilities(cls, required: set[str]) -> bool:
        """检查是否支持所需的平台专有能力。"""
        return required.issubset(cls.capabilities)

    @abstractmethod
    def get_provider_name(self) -> str:
        """返回 provider 标识，如 'openai' / 'gemini' / 'grok'"""
        ...

# src/providers/native/capabilities.py
# 能力常量定义
CAP_STRUCTURED_OUTPUT = "structured_output"   # response_format JSON Schema
CAP_STREAMING_TOOLS = "streaming_tools"        # 流式 function calling
CAP_VISION = "vision"                          # 图片理解
CAP_SAFETY_SETTINGS = "safety_settings"        # 安全设置（Gemini）
CAP_GROUNDING = "grounding"                    # 联网搜索（Gemini）
CAP_TTS = "tts"                                # 文本转语音
```

##### OpenAI 适配器示例

```python
# src/providers/native/openai_adapter.py
import os
from openai import OpenAI, Stream
from ..base import ChatResponse, ChatMessage
from .base import NativeProvider, CAP_STRUCTURED_OUTPUT, CAP_VISION

class OpenAIProvider(NativeProvider):
    capabilities = {CAP_STRUCTURED_OUTPUT, CAP_VISION}

    def __init__(self, api_key: str, base_url: str | None = None,
                 model: str | None = "gpt-4o"):
        super().__init__(api_key, base_url, model)
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = self._get_model()

    def get_provider_name(self) -> str:
        return "openai"

    def chat(self, messages, tools=None, **kwargs) -> ChatResponse:
        # 完整的 OpenAI SDK 调用，不经过 LiteLLM
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            **kwargs,
        )
        return ChatResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            usage=dict(response.usage or {}),
            finish_reason=response.choices[0].finish_reason or "",
        )

    def chat_stream(self, messages, tools=None, **kwargs):
        stream = self.client.chat.completions.create(
            model=self.model, messages=messages,
            tools=tools, stream=True, **kwargs,
        )
        for chunk in stream:
            yield chunk.choices[0].delta.content or ""
```

##### 自动选择与工厂

```python
# src/providers/native/__init__.py
from .openai_adapter import OpenAIProvider
from .gemini_adapter import GeminiProvider
from .grok_adapter import GrokProvider
from ..base import BaseProvider
from ..litellm_provider import LiteLLMProvider

# 注册原生适配器
_NATIVE_PROVIDERS: dict[str, type[NativeProvider]] = {
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "grok": GrokProvider,
}

def create_native_provider(provider_name: str,
                           config: dict) -> BaseProvider | None:
    """尝试创建原生适配器，失败返回 None（回退 LiteLLM）"""
    cls = _NATIVE_PROVIDERS.get(provider_name)
    if not cls:
        return None
    try:
        return cls(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url"),
            model=config.get("default_model"),
        )
    except Exception:
        return None
```

##### 依赖

- `openai` SDK（pip install openai）
- `google-genai` SDK（pip install google-genai）
- `requests`（标准库替代也可，但 SDK 更可靠）

---

#### F-73（✅ 已归档）

**状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

_设计内容（79 行）已归档，此处仅保留状态跟踪。_

#### Sandbox / SSH Remote 沙箱远程执行（F-74 📋）

**状态**: 📋 规划中 | **优先级**: P2

##### 背景

CCB 支持 `sandbox-toggle` 命令将执行环境切换到沙箱模式，以及 SSH 远程执行命令。clawcodex 当前所有 Bash/Shell 执行均在本地，无沙箱隔离或远程执行能力。

##### 子特性分解

| 编号 | 子特性 | 说明 | Python 依赖 | 预计工作量 |
|:----:|--------|------|:-----------:|:----------:|
| P74-A | Sandbox 执行器抽象 | "Bash 沙箱"接口抽象：local/docker/ssh 三种后端 | 无 | 3-5天 |
| P74-B | Docker 沙箱执行 | 在 Docker 容器内执行 shell 命令（临时容器 or 常驻容器） | `docker-py` | 3-5天 |
| P74-C | SSH 远程执行 | 通过 SSH 在远程主机执行 shell 命令 | `asyncssh` | 3-5天 |
| P74-D | `/sandbox` CLI 命令 | 查看/切换当前 sandbox 模式 | 无 | 2-3天 |
| P74-E | 沙箱配置文件 | `~/.clawcodex/sandbox.json`：默认模式/超时/容器镜像/SSH 主机列表 | 无 | 1-2天 |

##### 架构

```python
# src/services/sandbox/
sandbox/
├── base.py              # SandboxExecutor（抽象基类）
├── local.py             # LocalExecutor（直接 subprocess，当前行为）
├── docker.py            # DockerExecutor（docker run 沙箱）
├── ssh.py               # SSHExecutor（asyncssh 远程执行）
├── manager.py           # SandboxManager（全局切换/状态）
└── config.py            # SandboxConfig（pydantic model）
```

##### SandboxExecutor 抽象接口

```python
# src/services/sandbox/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxResult:
    """沙箱命令执行结果。"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int = 0
    error: str | None = None


@dataclass
class SandboxConfig:
    """沙箱配置（每个执行器有自己的子类扩展）。"""
    timeout: int = 30          # 单条命令超时秒数
    work_dir: str = "/tmp"     # 工作目录
    env_vars: dict[str, str] = field(default_factory=dict)


class SandboxExecutor(ABC):
    """沙箱执行器抽象基类。"""

    type: str = ""  # "local" / "docker" / "ssh"（子类覆盖）

    def __init__(self, config: SandboxConfig):
        self.config = config

    @abstractmethod
    async def execute(self, command: str) -> SandboxResult:
        """在沙箱环境中执行一条命令。"""
        ...

    @abstractmethod
    async def upload_file(self, local_path: str, remote_path: str) -> None:
        """将本地文件上传到沙箱环境。"""
        ...

    @abstractmethod
    async def download_file(self, remote_path: str, local_path: str) -> None:
        """从沙箱环境下载文件到本地。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """释放沙箱资源（关闭连接、停止容器等）。"""
        ...


class SandboxManager:
    """沙箱管理器（全局单例）。"""

    _current: SandboxExecutor | None = None

    @classmethod
    def get_current(cls) -> SandboxExecutor:
        """返回当前沙箱，默认返回 LocalExecutor。"""
        if cls._current is None:
            cls._current = LocalExecutor(SandboxConfig())
        return cls._current

    @classmethod
    def set_current(cls, executor: SandboxExecutor) -> None:
        """切换当前沙箱。"""
        if cls._current is not None:
            asyncio.ensure_future(cls._current.close())
        cls._current = executor
```

##### 本地执行器示例

```python
# src/services/sandbox/local.py
import asyncio
import os
import time
from .base import SandboxExecutor, SandboxResult

class LocalExecutor(SandboxExecutor):
    type = "local"

    async def execute(self, command: str) -> SandboxResult:
        """本地 subprocess 执行（直接当前行为）。"""
        start = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.work_dir,
            env={**dict(os.environ), **self.config.env_vars},  # 保留环境变量
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return SandboxResult(
                exit_code=-1, stdout="", stderr="",
                error=f"Command timed out after {self.config.timeout}s",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        return SandboxResult(
            exit_code=proc.returncode or 0,
            stdout=stdout.decode() if stdout else "",
            stderr=stderr.decode() if stderr else "",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def upload_file(self, local_path: str, remote_path: str) -> None:
        # Local：文件复制即可
        import shutil
        shutil.copy2(local_path, remote_path)

    async def download_file(self, remote_path: str, local_path: str) -> None:
        import shutil
        shutil.copy2(remote_path, local_path)

    async def close(self) -> None:
        pass  # Local 无需清理
```

##### Docker 执行器核心逻辑

```python
# src/services/sandbox/docker.py
class DockerExecutor(SandboxExecutor):
    type = "docker"

    def __init__(self, config: DockerSandboxConfig):
        super().__init__(config)
        import docker
        self.client = docker.from_env()
        self.container: docker.models.containers.Container | None = None

    async def ensure_container(self):
        """延迟创建容器（首次 execute 时创建）。"""
        if self.container is None:
            self.container = self.client.containers.create(
                image=self.config.image or "ubuntu:22.04",
                command=["sleep", "infinity"],
                detach=True,
                working_dir=self.config.work_dir,
                environment=self.config.env_vars,
            )
            self.container.start()

    async def execute(self, command: str) -> SandboxResult:
        await self.ensure_container()
        import time
        start = time.monotonic()
        exit_code, output = self.container.exec_run(
            cmd=["bash", "-c", command],
            timeout=self.config.timeout,
        )
        return SandboxResult(
            exit_code=exit_code,
            stdout=output.decode() if isinstance(output, bytes) else str(output),
            stderr="",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    # ... upload_file/download_file/close via docker cp / container.stop
```

##### BashTool 集成点

```python
# src/tool_system/tools/bash.py（修改点）
class BashTool:
    async def call(self, input: dict, context: ToolContext) -> ToolResult:
        from src.services.sandbox.manager import SandboxManager
        cmd = input.get("command", "")
        executor = SandboxManager.get_current()
        result = await executor.execute(cmd)
        return ToolResult(
            name="bash",
            output={
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
            },
            is_error=result.exit_code != 0,
        )
```

##### 使用模式

```bash
# CLI 切换
clawcodex-dev sandbox set docker --image python:3.11-slim
clawcodex-dev sandbox set ssh --host dev-server --user bot
clawcodex-dev sandbox status    # 查看当前模式

# BashTool 调用自动使用当前沙箱
# BashTool.call() → SandboxManager.current.execute(command)
```

##### 依赖

- `docker-py`（Docker SDK，可选）
- `asyncssh`（SSH 异步客户端，可选）
- `paramiko`（SSH 同步客户端，备选）
- 均为 optional-dependencies

---

### 实施总览

| 编号 | 特性 | 优先级 | 状态 | 工时估算 |
|:----:|------|:------:|:----:|:--------:|
| F-68 | Feature Gate 运行时特性开关 | P1 | 📋 规划中 | 1-2周 |
| F-69 | Budget / Poor Mode 节俭模式 | P1 | 🔄 进行中（token_budget 已实现） | 剩余：与 query pipeline 深度集成待补 |
| F-70 | Plugin 插件系统基础框架 | P1 | 🔄 进行中（注册表/加载器/依赖/校验/市场等框架已存在） | 剩余：Plugin 发现/沙箱隔离/生命周期待补 |
| F-71 | 内置工具补齐（4个剩余工具） | P1 | 🔄 进行中（SnipTool已实现） | 剩余 3 工具待实现 |
| F-72 | Multi-API 原生适配器 | P1 | 📋 规划中 | 2周 |
| F-73 | CI/CD 质量门禁与 PyPI 发布 | P0 | ✅ 本地已完成 / 🔄 远端待验证 | changed pytest 自动追加与 stability-gate pytest 已落地；远端 Pipeline/CodeCheck/Release/PyPI 开通后收口 |
| F-74 | Sandbox/SSH Remote 沙箱远程执行 | P2 | 📋 规划中 | 2周 |

### 实施建议顺序

```
F-73 (CI/CD) ──→ F-68 (Feature Gate) ──→ F-69 (Budget Mode) ──→ F-71 (Tool补齐)
   ↑ 基础质量          ↑ 架构基础              ↑ 用户感知              ↑ 功能完整
   P0                  P1                      P1                      P1

F-70 (Plugin 系统) ←── F-72 (API 适配器) ←── 可并行开发
   P1, 2-3周             P1, 2周

F-74 (Sandbox) ──→ 长期迭代（P2）
```


---

## 八、Multi-Session 可视化分析平台（F-91~F-96 ✅）

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

  - name: claude-code
    repo: anthropics/claude-code
    track_releases: true
    changelog_path: CHANGELOG.md
    notes: 上游源，核心对齐目标

  - name: aider
    repo: paul-gauthier/aider
    track_releases: true
    track_commits: false
    release_tag_filter: "\\d+\\.\\d+\\.\\d+"
    notes: Python 生态最活跃的编码 Agent

  - name: swe-agent
    repo: princeton-nlp/SWE-agent
    track_releases: true
    track_prs: false
    notes: 自动修复 GitHub issue 的标杆项目

## 其余项目
```

##### 抓取器 (`Fetcher`)

```python
class Fetcher:
    """从各源拉取增量数据的核心引擎"""

    def __init__(self, github_token: str, cache_dir: Path):
        self._session: httpx.Client = ...
        self._cache_dir = cache_dir
        self._etag_store: dict[str, str] = {}  # ETag 用于增量

    def fetch_releases(self, source: WatchSource, since: str | None) -> list[Release]:
        """获取新 release（逐页，受 ETH rate limit 约束）"""
        ...

    def fetch_commits(self, source: WatchSource, since: str | None) -> list[Commit]:
        """获取新 commit（可选）"""
        ...

    def fetch_prs(self, source: WatchSource, since: str | None) -> list[PullRequest]:
        """获取新 PR（可选）"""
        ...

    def fetch_release_notes(self, release: Release) -> str | None:
        """尝试获取 release body 或 CHANGELOG 条目"""
        ...

    @dataclass
    class FetchResult:
        releases: list[Release]
        commits: list[Commit]
        prs: list[PullRequest]
        errors: list[str]
```

**关键设计决策**:
- 使用 `ETag` / `If-None-Match` 头实现增量拉取，减少 API 配额消耗
- 初次运行全量拉取，后续仅拉取上次拉取之后的新数据
- 每次拉取后持久化 cursor / ETag 到 `cache_dir/cursors.json`
- GitHub API 受 5000 req/h 限制，对于 ~10 个源每 24h 拉取一次完全够用
- Release body 优先从 GitHub Release API 获取，回退到解析 CHANGELOG 文件

##### 缓存策略

| 数据类型 | 缓存位置 | 缓存策略 | 清理 |
|---------|---------|---------|------|
| Release body | `cache_dir/releases/{source}.json` | 无限期保留 | 手动清理 |
| Commit | `cache_dir/commits/{source}.json` | TTL 30 天 | 自动清理 |
| PR | `cache_dir/prs/{source}.json` | TTL 30 天 | 自动清理 |
| Cursor/ETag | `cache_dir/cursors.json` | 永久 | 重建清空 |

---

#### 10.1.6 AR-5.1.2 候选特性抽取与分类（F-91 ✅）

**文件路径**: `clawcodex_ext/community_radar/extractor.py`, `clawcodex_ext/community_radar/classifier.py`

##### Feature Record 数据模型

```python
@dataclass
class FeatureRecord:
    id: str                          # hash(source.name + title + type)
    source: str                      # 来源项目名
    title: str                       # 特性标题（简短）
    description: str                 # 特性描述（1-3 句）
    category: FeatureCategory        # 分类（见下）
    feature_type: FeatureType        # 特性类型
    released_at: str | None          # ISO 8601
    url: str                         # 原文链接
    related_projects: list[str]      # 跨项目参考：哪些项目也实现了类似特性
    tags: list[str]                  # 自由标签
    raw_body: str | None             # 原始 release note / commit message 片段

class FeatureCategory(Enum):
    AGENT_LOOP = "agent_loop"            # Agent 循环增强
    TOOL_SYSTEM = "tool_system"          # 工具系统
    PROVIDER = "provider"                # Provider/模型
    PERMISSION = "permission"            # 权限/安全
    MEMORY = "memory"                    # 记忆/上下文
    MCP = "mcp"                          # MCP 协议
    MULTI_AGENT = "multi_agent"          # 多 Agent
    ORCHESTRATOR = "orchestrator"        # 编排/自动化
    TUI_REPL = "tui_repl"               # UI 交互
    CLI = "cli"                          # CLI 体验
    OBSERVABILITY = "observability"      # 可观测性
    INFRA = "infra"                      # 基础设施/架构

class FeatureType(Enum):
    NEW = "new"                          # 全新特性
    ENHANCEMENT = "enhancement"          # 已有特性增强
    BREAKING = "breaking"                # 破坏性变更（需迁移）
    DEPRECATION = "deprecation"          # 弃用警告
    BUGFIX = "bugfix"                    # 修复（不视为新特性）
```

##### 抽取流水线

```python
class FeatureExtractor:
    """从 Release / CHANGELOG 文本中抽取候选特性"""

    def __init__(self, llm_client: LiteLLM | None = None):
        self._llm = llm_client  # 可选，LLM 仅用于高置信度分类

    def extract(self, release_body: str) -> list[FeatureRecord]:
        """从 release note 中提取特性记录（基于规则 + LLM 辅助）"""
        ...

    def _extract_by_patterns(self, text: str) -> list[str]:
        """基于 Markdown 标题、- [x] 列表、## Added / ## Changed 等常见模式抽取候选"""
        ...

    def _classify_with_llm(self, candidates: list[str]) -> list[FeatureRecord]:
        """LLM 辅助分类（当规则匹配质量不足时触发）"""
        ...
```

**抽取策略（由简到繁）**：

1. **规则优先**：基于常见 release note 格式的启发式抽取
   - `## Added / ## New` 分段下的列表项
   - `- [x]` 复选框完成项
   - `## Breaking Changes` 下内容
   - 版本号 `vX.Y.Z` 后的更新条目
2. **LLM 辅助**：当规则匹配失败或置信度低时，调用 LLM 从 release body 中抽取
3. **跨项目去重**：基于 title + description 的语义相似度（TF-IDF + cosine），同一特性在不同项目出现时合并为一个 `FeatureRecord` 并填充 `related_projects`

**Taxonomy 分类树**（FeatureCategory 是顶级节点，实现中可扩展子类）：
```
agent_loop
  ├── prompt_engineering
  ├── tool_selection
  ├── planning
  ├── self_correction
  └── context_management
tool_system
  ├── new_tool
  ├── tool_improvement
  └── mcp_extension
multi_agent
  ├── a2a_protocol
  ├── team_management
  └── task_delegation
...
```

---

#### 10.1.7 AR-5.1.3 评分与报告系统（F-91 ✅）

**文件路径**: `clawcodex_ext/community_radar/scorer.py`, `clawcodex_ext/community_radar/reporter.py`

##### 评分模型

```python
@dataclass
class FeatureScore:
    record_id: str
    overall: float                    # 综合评分（0-100）
    dimensions: dict[str, float]      # 各维度评分

    # 各维度
    popularity: float                 # 热度（社区关注度）
    maturity: float                   # 成熟度（代码质量/文档/测试）
    adaptation_cost: float            # 适配成本（越低越好）
    strategic_value: float            # 战略价值（与 ClawCodex 路线图契合度）
    architecture_fit: float           # 架构适配度（与三层解耦约束兼容性）
```

**评分维度定义**：

| 维度 | 权重 | 输入因子 | 计算方法 |
|------|:----:|---------|---------|
| 热度 | 15% | GitHub stars trend、PR 活跃度、社区讨论量 | Min-Max 归一化到 0-100 |
| 成熟度 | 20% | 是否已有稳定 release、测试覆盖、文档完整度 | 基于 metadata 的规则评分 |
| 适配成本 | 25% | 与 ClawCodex 架构差异度、需改动的文件范围 | Architecture Fit Checker（SR-5.2）评估 |
| 战略价值 | 25% | 是否在 ROADMAP/FEATURE_PLAN 中已有规划 | 关键词匹配 + LLM 语义匹配 |
| 架构适配 | 15% | 是否可落入 clawcodex_ext/*、是否破坏上游同步 | 基于 F-48 解耦规则的自动化检查 |

##### 报告生成

```python
class CommunityDigest:
    """社区动态报告"""

    period: str                       # "weekly" | "monthly"
    generated_at: str                 # ISO 8601
    summary: str                      # LLM 生成的摘要
    new_features: list[FeatureRecord] # 本期新特性
    trending: list[FeatureRecord]     # 高评分特性
    breaking_changes: list[FeatureRecord]  # 破坏性变更预警
    stats: DigestStats                # 统计摘要

@dataclass
class DigestStats:
    total_releases: int
    total_features: int
    by_category: dict[str, int]
    top_projects: list[tuple[str, int]]  # (project_name, feature_count)
```

报告输出为双格式：
- **Markdown**：可直接阅读的周报格式
- **JSON**：供程序消费的结构化数据

##### Community Digest 模板示例

```markdown
# ClawCodex 社区周报 v2026-W26

> 生成时间: 2026-06-29T08:00:00Z
> 覆盖范围: 7 个项目 · 12 个新 release · 18 条特性记录


## 摘要

本周社区新特性集中在 **MCP 工具扩展** 和 **Agent 自纠正** 两个方向。
Aider 新增了 `--lint` 模式的自动修复能力，SWE-agent 改进了 issue 定位的准确率。

## 高评分候选特性

| 特性 | 来源 | 评分 | 分类 | 简述 |
|------|------|:----:|------|------|
| --lint auto-fix | Aider | 85 | tool_system | 自动修复 lint 错误 |
| Agent self-critique | Claude Code | 78 | agent_loop | 执行前自我审查 |
| Context compression | OpenHands | 72 | agent_loop | 自动压缩历史上下文 |

## 破坏性变更预警

| 项目 | 版本 | 变更 | 影响评估 |
|------|:----:|------|---------|
| langgraph | v0.3.0 | StateGraph API 重构 | 高——需要迁移现有 Agent 定义 |

## 分类分布

- agent_loop: 6
- tool_system: 5
- multi_agent: 3
- mcp: 2
- cli: 1
- observability: 1
```

---

#### 10.1.8 AR-5.1.4 Cron 集成（F-91 ✅）

通过 ClawCodex 已有的 Cron 系统（F-22）进行调度：

```yaml
# workflow.md 配置扩展
community_radar:
  enabled: false                      # 默认关闭
  cron_schedule: "0 8 * * 1"         # 每周一早上8点（UTC）
  max_features_per_report: 20
  output_dir: ".reports/community-radar"
  notify: false                       # 是否推送到用户通道
```

Cron 集成点：
- `CronTask` 配置一个 durable task，fire 时触发 `run_community_scan()`
- 扫描结果写入 `output_dir/{yyyy-Www}.md` + `.json`
- 可选通过进度报告通道通知用户

---

#### 10.1.9 三方集成组件（F-91 ✅）

以下开源项目可作为 SR-5.1 的可选集成组件，不需要重新制造轮子：

**释放通知类（可复用其 API 轮询模式）**：

| 项目 | 类型 | 用途 | 集成方式 |
|------|------|------|---------|
| [StackPulse](https://github.com/daniel-ctn/stack-pulse) | 🔓 开源 MIT | GitHub release 监控 + AI 摘要（breaking changes/deprecations/migration notes）；有公开 feed | 可复用其 fetcher + AI digest 思路，或直接订阅其 feed |
| GitHub Release Monitor | 🔓 开源 | Docker 自托管，GitHub releases 监控 + 邮件/Apprise 通知 | 可借鉴其 Docker 部署架构 + 通知流水线设计 |
| NewReleases.io | 🌐 在线服务 | 多通道 release 通知（Slack/Email/Webhook） | 参考其报警路由设计 |
| Releases Tracker (GitHub App) | 🔓 开源 | 自动订阅 starred 项目，每小时检查 | 参考其 GitHub App OAuth 流程和自动订阅模式 |
| GitWatchman | 🌐 在线服务 | 邮件 release 通知 | 参考其通知模板设计 |

**分析/报告类（可复用其输出格式和模板）**：

| 项目 | 类型 | 用途 | 集成方式 |
|------|------|------|---------|
| Weekly Digest (GitHub App) | 🔓 开源 | 按周生成仓库活动摘要（PR/Issue/Commit） | 可复用其 Weekly Digest 模板和调度模式 |
| Conventional Changelog | 🔓 开源 | 从 commit 生成 changelog | 可复用其 commit message 解析规则 |
| Star History | 🌐 在线服务 | 星标增长趋势对比 | 参考其跨项目对比的展示思路 |
| Release Watcher | 🌐 在线服务 | 集中列示关注的 GitHub releases | 参考其聚合展示 UI 设计 |

**不推荐集成**的类别：纯 changelog 自动生成工具（`commit-and-tag-version`、`ShipLog`、`CommitCatalog` 等）与 SR-5.1 目标方向不同，SR-5.1 关注的是**跨项目的社区新特性发现**，而非单个项目的 changelog 格式化。

---

#### 10.1.10 与 ClawCodex 现有能力的协同（F-91 ✅）

| 现有组件/能力 | SR-5.1 中的角色 | 说明 |
|-------------|----------------|------|
| **F-22 Cron 系统** | AR-5.1.4 调度基础 | Cron durable task 提供定时触发能力 |
| **LiteLLM Provider** | AR-5.1.2/5.1.3 LLM 接口 | 用于特性分类、评分、报告摘要生成 |
| **ReportWriter**（extensions/orchestrator） | 报告格式参考 | .md + .json 双写模式可复用 |
| **WebSearch / WebFetch 内置工具** | 人工触发时辅助 | 开发者手动查询社区动态时可利用内置工具 |
| **LocalTracker** | 可选集成 | 生成的 feature proposal 可通过 LocalTracker 进 issue 队列 |
| **ProgressReporter Sink**（F-40） | 可选集成 | 长时间抓取任务进度上报 |
| **Feature Gate**（F-68 设计） | 架构适配检查 | 评估新特性与 Feature Flag 系统的兼容性 |

#### 10.1.11 文件结构（F-91 ✅）

```
clawcodex_ext/community_radar/
├── __init__.py              # 库入口
├── registry.py              # SourceRegistry — 源注册表
├── fetcher.py               # Fetcher — 抓取引擎
├── models.py                # WatchSource, FeatureRecord, FeatureScore 等数据模型
├── extractor.py             # FeatureExtractor — 特性抽取
├── classifier.py            # 分类器（Taxonomy + LLM）
├── deduplicator.py          # 跨项目去重
├── scorer.py                # 评分引擎
├── reporter.py              # CommunityDigest 报告生成
├── config.py                # 配置加载
├── cli.py                   # clawcodex-dev community-radar 子命令
├── templates/
│   ├── weekly_digest.md.j2  # 周报 Markdown 模板
│   └── monthly_digest.md.j2 # 月报 Markdown 模板
└── tests/
    ├── test_registry.py
    ├── test_fetcher.py
    ├── test_extractor.py
    ├── test_classifier.py
    ├── test_deduplicator.py
    ├── test_scorer.py
    └── test_reporter.py
```

配置目录：`~/.clawcodex/community-radar/`
```
~/.clawcodex/community-radar/
├── sources.yaml              # 源配置
├── config.yaml               # 运行配置（schedule/权重/通知）
└── cache/
    ├── cursors.json           # 增量 cursor / ETag
    ├── releases/              # release body 缓存
    ├── commits/               # commit 缓存
    └── prs/                   # PR 缓存
```

#### 10.1.12 实施阶段（F-91 ✅）

**Phase 1 — 最小可用（2 周）**：
1. 实现 `WatchSource` / `SourceRegistry` + YAML 配置加载
2. 实现 `Fetcher.fetch_releases()` 对 GitHub Release API 的 ETag 增量拉取
3. 实现 `FeatureExtractor` 的规则优先抽取模式
4. 实现 JSON 格式的原始结果持久化
5. 手工触发扫描：`clawcodex-dev community-radar scan` 子命令

**Phase 2 — 智能抽取（2 周）**：
1. 接入 LLM 辅助分类（FeatureRecord.category + feature_type）
2. 实现跨项目去重（TF-IDF + cosine similarity）
3. 实现基础评分模型（4 维度：热度/成熟度/适配成本/战略价值）
4. 生成 Markdown 格式周报

**Phase 3 — 报告与扩展（1.5 周）**：
1. 完善评分模型（加入架构适配维度）
2. 模板化报告生成（Jinja2 模板）
3. 接入 Cron 系统（F-22），实现定时自动扫描

**Phase 4 — 集成与增强（1.3 周）**：
1. 扩展关注源到 Phase 2 项目
2. 可选的通知推送（通过 ReportWriter 通道）
3. 与 SR-5.2（自我规划）对接的 JSON 输出格式定型
4. 单元测试 + 集成测试

#### 10.1.13 验收标准（F-91 ✅）

| # | 验收项 | 验收方式 |
|---|--------|---------|
| 1 | 可通过 YAML 配置关注源，支持添加/删除/列出 | `clawcodex-dev community-radar source list` 展示当前源 |
| 2 | 能拉取指定源的最新 release 并缓存 | 运行 scan 后 `cache/releases/` 目录下有 JSON 文件 |
| 3 | 增量拉取不重复消费 GitHub API 配额 | 第二次运行只产生少量 API 请求（仅新数据） |
| 4 | Release note 中的新特性可被规则抽取 | 在已知格式（Conventional Changelog / Keep a Changelog）上测试通过 |
| 5 | 同一特性在不同项目出现时被合并去重 | aider 和 claude-code 同时支持某特性时只记录一次 |
| 6 | 每周生成 Community Digest（Markdown + JSON）| 报告有摘要、分类分布、高评分候选 |
| 7 | 可通过 Cron 定时触发 | 配置 `cron_schedule` 后自动按计划运行 |
| 8 | 非破坏性：不修改 `src/*` 任何文件 | git diff 确认全部落在 `clawcodex_ext/community_radar/` |

#### 10.1.14 风险与约束（F-91 ✅）

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| GitHub API Rate Limit | 数据拉取不完整 | ETag 增量 + 合理调度间隔（至少 1h）+ 可配置 token pool |
| Release note 格式不统一 | 抽取效果差 | 规则 + LLM 双通道；规则覆盖常见格式，LLM 做兜底 |
| 评价模型不公平 | 误导路线图方向 | 初期只做信息展示不自动决策；用户审查可纠正权重 |
| 信息噪声导致报告质量低 | 用户忽略报告 | 评分阈值过滤 + 最高评分限条数；用户可配置关注分类 |
| 自升级误改核心上游代码 | 破坏 upstream sync | 强制 Architecture Fit Checker；默认写入 `clawcodex_ext/*` |

#### 10.1.15 已拟定的设计决定（F-91 ✅）

1. **不另造数据库**：缓存使用 JSON 文件，复用 ClawCodex 已有的纯文件存储模式
2. **不强制 LLM**：规则抽取优先，LLM 仅作辅助分类和摘要生成（用户可配置关闭）
3. **不自动创建 Issue/PR**：Phase 1-3 只做信息收集展示，接入 SR-5.2 后才自动生成 proposal
4. **并行设计**：AR-5.1.1 和 AR-5.1.2 可并行开发（抓取器与抽取器独立）
5. **StackPulse 作为参考架构**：其 `fetcher → AI digest → feed` 三阶段架构设计可直接借鉴
6. **`clawcodex_ext/community_radar/` 作为落地路径**：不修改 `src/*`，符合 F-48 解耦约束

#### 10.1.16 依赖与协同（F-91 ✅）

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-22 Cron 系统 | 必需（Phase 3+） | 定时触发扫描和报告生成 |
| LiteLLM Provider | 可选（Phase 2+） | LLM 辅助分类和摘要生成 |
| httpx / aiohttp | 必需 | GitHub API 客户端 |
| scikit-learn | 可选（Phase 2+） | TF-IDF 去重向量化 |
| Jinja2 | 必需（Phase 3+） | 报告模板渲染 |

---

## 十一、Agent 执行性能优化（F-105 ✅ / F-106 ✅）

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

## 附录：F-Number 快速索引

| F-Number | 名称 | 章节 | 状态 |
|----------|------|------|------|
|  | F-2 | Team 成员管理 | §2.2 | ✅ 规划中 |  |
| F-3 | MCP 扩展功能 | §2.4 | ✅ 基础完成 |
|  | F-4 | 结构化输出增强 | §2.3 | ✅ 适配器完成 |  |
| F-9 | /goal 目标管理 | §2.6 | ✅ 已完成（2026-06-19 审计） | `clawcodex_ext/goal/` 9 文件 2538 行 |
|  | F-10 | ExecuteExtraTool | §2.7 | 📋 规划中 |  |
| F-11 | sessionStorage 容量 | §2.10 | ✅ 已完成 |
| F-12 | cacheWarning 容量 | §2.11 | ✅ 已完成 |
| F-13 | 记忆作用域隔离 | §2.5 | ✅ 已完成 |
|  | F-16 | Auto 模式 | §2.13 | ✅ 规划中 |  |
| F-18 | CreateAgentTool | §2.9 | ✅ 已完成 |
| F-20 | Agent 进度汇报 | §2.1 | ✅ 已完成 |
| F-22 | Cron 系统 | §五 | 🔄 进行中（Phase A~E ✅，Phase F teammate ownership 待补） |
| F-36 | LocalTracker | §1.1.1 | ✅ 已完成 |
| F-37 | PR 检视意见自动修复 | §1.1.2 | ✅ 已完成 |
| F-38 | 验证与报告闭环 | §1.1.3 | ✅ 已完成 |
| F-39 | Issue 重跑入口 | §1.1.4 | ✅ 已完成 |
| F-40 | ProgressReporter Sink | §1.2.2 | ✅ 已完成 |
| F-41 | Coordinator 工具集 | §1.3.4 | ✅ 已完成 |
| F-42 | Workspace 策略 | §1.2.1 | ✅ 已完成 |
| F-43 | CLI 模型切换 | §3.1 | ✅ 已完成 |
| F-44 | 人工检视闸门 | §1.4.2 | ✅ 已完成 |
| F-45 | Tool-call 审计 | §1.3.3 | ✅ 已完成 |
| F-46 | permission_mode 拆分 | §3.2 | 📋 规划中 |
| F-47 | Settings 重构 | §3.3 | ✅ 已完成 |
| F-49 | 会话统一存储（含 Phase 5 格式合并） | §1.4.2 / §1.4.5 | ✅ 已完成（Phase 0.4 + Phase 5 P5-A~G） |
| F-50 | SOP 转换器固化 | §4.2 | ✅ 已完成（SourceCodeParser / SkillGrouper / AgentMarkdownWriter 全部落地 `extensions/pos_converter/`） |
| F-51 | AgentRunner 空转检测 | §1.3.1 | ✅ 已完成 |
| F-52 | SDK→Tool 注册 | §4.3 | ✅ 已完成（`clawcodex_ext/agent/tool_authoring/` factory/spec/persistence 已落地：`build_tool_from_spec` / `AgentToolSpec` / `register_python_function` / `list_python_functions` / python/http/bash 支持） |
| F-53 | Tool→CLI 命令映射 | §4.4 | 📋 规划中 |
| F-54 | 运行期可观测性 | §1.3.2 | 🔄 进行中（debug_log.py + tool_event_log.py + ObservabilityConfig schema 已落地，query-runner heartbeat/CLI 诊断字段待补） |
| F-55 | SOP 分组策略增强 | §4.2.1 | ✅ 已完成 |
| F-60 | Pipe IPC 群控 | §7.1 | ✅ 已完成（2026-06-19） | `src/services/pipe_ipc/` 967 行 + 11 测试 |
| F-61 | Computer Use | §7.2 | ✅ 已完成（2026-06-19） | `src/services/computer_use/` 1797 行 + 15 测试 |
| F-62 | Chrome 自动化 | §7.2 | ✅ 已完成（2026-06-22） |
| F-63 | Channels 通知 | §7.3 | ✅ 已完成（2026-06-19） | `src/services/channels/` 2097 行 + 18 测试 |
| F-64 | Voice Mode | §7.3 | 🔄 进行中（接口层已完成） | `src/services/voice/` 检测+STT 抽象类 188 行 |
| F-65 | Langfuse 可观测 | §7.4 | ✅ 已完成（2026-06-22） | `src/services/analytics/` + `src/services/langfuse/` 全链路 |
| F-66 | ACP 协议 | §7.4 | 📋 规划中 |
| F-67 | Buddy/Proactive | §7.5 | ✅ 已完成 | `clawcodex_ext/buddy/` 1,371 行 8 模块完整实现 + CLI 命令 |
| F-68 | Feature Gate | §7.6 | 📋 规划中 |
| F-69 | Budget/Poor Mode | §7.5 | 🔄 进行中（token_budget 已实现） | `clawcodex_ext/query/token_budget.py` 159 行 BudgetTracker/ContinueDecision/StopDecision |
| F-70 | Plugin 系统 | §4.3 | 🔄 进行中 | `src/plugins/` 8 文件 1070 行基础框架 |
|  | F-71 | 内置工具补齐 | §7.6 | 🔄 进行中（SnipTool 已完成，3工具待实现） |  |
| F-72 | Multi-API 适配器 | §7.2 | 📋 规划中 |
| F-73 | CI/CD 流水线 | §7.6 | ✅ 本地已完成 / 🔄 远端待验证 |
| F-74 | Sandbox 沙箱 | §7.2 | 📋 规划中 |
|  | F-75 | 工具调用统计 | §2.8 | ✅ 已完成 |  |
| F-78 | Issue 语义澄清 | §2.12 | ✅ 已完成（2026-06-19 审计） | `extensions/orchestrator/clarification.py` + `clarification_queue.py` 865 行 |
| F-80 | Agent 间交互 | §2.14 | ✅ 已完成（2026-06-19 审计） | `TaskInspectTool` + `TaskDirectivesTool` 642 行，已注册 EXTENSION_TOOLS |
| F-81 | Native 模块系统 | §4.4 | 📋 规划中 |
|  | F-82 | Remote Control | §7.1 | 🔄 进行中 |  |
| F-83 | Ultraplan 规划 | §7.5 | ✅ 已完成（2026-06-19） | `src/services/ultraplan/` 3454 行 + 13 测试 |
| F-84 | Context Collapse | §7.5 | ✅ 已完成（2026-06-19） | `src/services/context_collapse/` 3366 行 + 14 测试 |
| F-85 | Templates 模板 | §7.6 | ✅ 已完成（2026-06-19） | `src/services/templates/` 2076 行 + 11 测试 |
| F-86 | Kairos/Brief 调度 | §7.5 | ✅ 已完成（2026-06-19） | `src/services/kairos/` + `periodic/` 2022 行 + 13 测试 |
|  | F-87 | Workflow Scripts | §7.5 | ✅ 已归档 | 已被 F-1.10（声明式工作流引擎）和 F-50.10~（SOP 工作流模式）取代 |  |
| F-88 | Explore/Plan Agent | §7.5 | ✅ 已完成（2026-06-22） | P88-A~D 全部完成：Agent 定义 + 自动路由 + 双格式写盘 |
|  | F-89 | @agent-name 多入口统一支持 | §3.4 | 🔄 进行中 |  |
| F-90 | Hermes Gateway OpenAI API 参考（remote_api） | §7.1 | ✅ 已完成 |
| **F-91** | **Visualizer 核心数据管道** | §8.3 | ✅ **已完成** |
| **F-92** | **Visualizer 后端 API + WebSocket** | §8.3 | ✅ **已完成** |
| **F-93** | **Visualizer 前端（Jinja2 + ECharts）** | §8.3 | ✅ **已完成** |
| **F-94** | **Visualizer CLI 集成 + workspace 扫描** | §8.3 | ✅ **已完成** |
| **F-95** | **Visualizer Orchestrator 协同链接** | §8.3 | ✅ **已完成** |
| **F-96** | **Orchestrator 实时看板接入（State Journal）** | §8.10 | ✅ **已完成** |
| F-97 | 独立遥测系统（Issue-based Telemetry） | §9 | ✅ 第一期实现完成（A~E + G，IssueReporter 推迟到二期） |
| F-99 | Ctrl+C/B 即时中断响应优化 | §2.15 | ✅ 已完成（2026-06-17） | 三方案组合：`AnthropicProvider._ensure_client` 默认 `timeout=5.0` + `_close_response_safely` 关 transport（Win 跳过） + `_run_tools_partitioned` 改 `asyncio.wait(FIRST_COMPLETED)` + 100ms abort poll + synth cancelled result 保配对。Cancel bound：直连 <500ms，LiteLLM bound 在 5s |
| F-100 | Dreaming 后台记忆整合系统 | §2.16 | 🔄 进行中（2026-06-18） | 主体 7 子特性全 ✅：DreamTask + autoDream + consolidationLock（PID+mtime 锁） + `/dream` slash skill + permanent cron 集成 + 测试不变量解锁；106 单测 + 12 门禁 + 6 E2E 场景全绿。Phase B（lock 30min TTL 增强，0.5天）待补 |
| F-107 | PowerShell 支持增强 | §2.19 | 📋 规划中（2026-06-23） | 8 子特性 P107-A~H：工具 schema 扩展/进程启动适配/命令分类/安全分析/技能传播。总预计 6-8 天。 |
| F-108 | Freeze Detection & Auto-Recovery | §2.20 | 📋 规划中（2026-06-23） | 8 子特性 P108-A~H：四层混合方案（Layer0 快速修复 + Layer1 冻结检测 + Layer2 硬超时 + Layer3 自动恢复 + Layer4 诊断命令）。总预计 7 天。 |
