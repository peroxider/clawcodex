# ClawCodex 特性规划与设计文档

> 文档路径: `docs/FEATURE_PLAN.md`
> 版本: v4.0（格式重构版）
> 更新日期: 2026-06-23

> **说明**: 本文档所有特性采用统一 F-Number 编号体系。每个特性以 `F-XXX` 标识，状态使用统一表情符号：
> - ✅ 已完成 — 已实现并归档
> - 🔄 进行中 — 部分实现，尚有剩余工作
> - 📋 规划中 — 设计完成，待开发
> - 🔭 长期规划 — 方向性定义，未进入详细设计
> - ⛔ 已被取代 — 被其他特性合并或取代

---

## 目录

- [项目概述与边界约束](#项目概述与边界约束)
- [已归档功能模块](#已归档功能模块)
- [一、Orchestrator 系统](#一Orchestrator-系统)
  - [F-36 LocalTracker 本地 Issue 文档源设计](#ff-36)
  - [F-37 PR 检视意见自动修复闭环](#ff-37)
  - [F-38 验证与报告闭环](#ff-38)
  - [F-39 Issue 重跑入口](#ff-39)
  - [F-42 Shared/Sequential Workspace](#ff-42)
  - [F-40 ProgressReporter Sink 重构](#ff-40)
  - [F-51 AgentRunner 空转检测机制](#ff-51)
  - [F-54 运行期可观测性与 stuck-run debug](#ff-54)
  - [F-45 Tool-call 审计旁路设计](#ff-45)
  - [F-41 Coordinator 轻量工具集](#ff-41)
  - [F-49 Issue 会话统一存储与实时介入协议](#ff-49)
  - [F-103 — parentUuid 链 + walkChainBeforeParse 读取过滤](#ff-103)
  - [F-1.10 声明式工作流引擎核心](#ff-1-10)
  - [F-1.11 StageRunner 适配器](#ff-1-11)
  - [F-1.12 GATE 门禁处理器](#ff-1-12)
  - [F-1.13 DECISION 决策处理器](#ff-1-13)
  - [F-1.14 阶段契约验证器](#ff-1-14)
  - [F-1.15 检查点与恢复](#ff-1-15)
  - [F-1.16 工作流可观测性集成](#ff-1-16)
  - [F-118 动态任务分解引擎](#ff-118)
- [二、Agent 核心能力](#二Agent-核心能力)
  - [F-20 Agent 阶段性进度汇报](#ff-20)
  - [F-2 Team 成员管理（Phase-7）](#ff-2)
  - [F-4 结构化输出增强（Outlines）](#ff-4)
  - [F-3 MCP 扩展功能](#ff-3)
  - [F-13 Agent 记忆作用域隔离](#ff-13)
  - [F-9 /goal 命令（目标管理）](#ff-9)
  - [F-10 ExecuteExtraTool 延迟工具系统](#ff-10)
  - [F-75 工具/Skill 调用统计（跨会话）](#ff-75)
  - [F-18 CreateAgentTool 动态工具创建](#ff-18)
  - [F-11 sessionStorage 容量限制](#ff-11)
  - [F-12 cacheWarning 容量限制](#ff-12)
  - [F-78 Issue 语义澄清流程（自主模式扩展）](#ff-78)
  - [F-16 Auto 模式 (TRANSCRIPT_CLASSIFIER)](#ff-16)
  - [F-80 Agent 间自主观察与消息交互](#ff-80)
  - [F-99 Ctrl+C/B 即时中断响应优化](#ff-99)
  - [F-100 Dreaming 后台记忆整合系统](#ff-100)
  - [F-102 Agent Loop Hook 扩展点增强](#ff-102)
  - [F-107 PowerShell 支持增强](#ff-107)
  - [F-108 Freeze Detection & Auto-Recovery](#ff-108)
- [三、CLI 与配置系统](#三CLI-与配置系统)
  - [F-43 CLI 模型供应商与模型切换设计](#ff-43)
  - [F-47 Permission Settings Schema 重构设计](#ff-47)
- [四、Architecture & SDK 下沉](#四Architecture--SDK-下沉)
  - [F-50 SOP 转换器源码固化设计](#ff-50)
  - [F-55 SOP 转换器分组策略增强设计](#ff-55)
  - [F-50.10 工作流判别器](#ff-50-10)
  - [F-50.11 工作流结构提取器](#ff-50-11)
  - [F-50.12 阶段能力映射器](#ff-50-12)
  - [F-50.13 工作流 Schema 生成器](#ff-50-13)
  - [F-50.14 Agent 定义生成器（工作流模式扩展）](#ff-50-14)
  - [F-50.15 源码桥接器生成器](#ff-50-15)
  - [F-50.16 提取器适配器库](#ff-50-16)
  - [F-52 Python SDK 方法注册为 Tool](#ff-52)
  - [F-53 Tool 自动暴露为 CLI 斜杠命令](#ff-53)
- [五、Cron 系统执行引擎（F-22 🔄）](#五Cron-系统执行引擎F-22-)
  - [F-22-G1 Feature Gate 系统——isKilled 运行时 kill 开关](#ff-22-g1)
  - [F-22-G2 远程 Jitter 实时配置](#ff-22-g2)
  - [F-22-G3 One-shot 反向 Jitter（整点提前）](#ff-22-g3)
  - [F-22-G4 Permanent 免过期任务机制](#ff-22-g4)
  - [F-22-G5 锁注册式清理与 PID 存活探测增强](#ff-22-g5)
  - [F-22-G6 工具 Prompt 指引文档增强](#ff-22-g6)
  - [F-22-G7 Analytics 遥测事件注入](#ff-22-g7)
  - [F-22-G8 inFlight 防重复触发机制](#ff-22-g8)
  - [F-22-D1 Cron 任务累计防护——CCB 4 层设计对照审查（~D4） 📋 设计完成](#ff-22-d1)
- [六、会话恢复增强（F-49 / F-103 补缺 ✅）](#六会话恢复增强F-49--F-103-补缺-)
- [七、CCB 对标缺口补缺（F-60~F-90 🔄）](#七CCB-对标缺口补缺F-60F-90-)
  - [F-60 (已归档)](#ff-60)
  - [F-61 (已归档)](#ff-61)
  - [F-62 (已归档)](#ff-62)
  - [F-63 (已归档)](#ff-63)
  - [F-64 Voice Mode 语音输入](#ff-64)
  - [F-65 (已归档)](#ff-65)
  - [F-66 ACP 协议支持](#ff-66)
  - [F-67 (已归档)](#ff-67)
  - [F-81 Native 原生模块系统（Python 可实现部分）](#ff-81)
  - [F-82 Remote Control Server 远程控制服务 🔄](#ff-82)
  - [F-90 Hermes Gateway 参考实现（OpenAI 兼容 API 服务器）](#ff-90)
  - [F-83 (已归档)](#ff-83)
  - [F-84 (已归档)](#ff-84)
  - [F-85 (已归档)](#ff-85)
  - [F-86 (已归档)](#ff-86)
  - [F-87 Workflow Scripts 工作流脚本 ⛔](#ff-87)
  - [F-88 (已归档)](#ff-88)
  - [F-68 Feature Gate 运行时特性开关系统](#ff-68)
  - [F-69 Budget / Poor Mode 资源节俭模式](#ff-69)
  - [F-70 Plugin 插件系统基础框架](#ff-70)
  - [F-71 内置工具补齐（缺失工具批量实现）](#ff-71)
  - [F-72 Multi-API 原生适配器扩展](#ff-72)
  - [F-73 (已归档)](#ff-73)
  - [F-74 Sandbox / SSH Remote 沙箱远程执行](#ff-74)
- [八、Multi-Session 可视化分析平台（F-91~F-96 ✅）](#八Multi-Session-可视化分析平台F-91F-96-)
- [十一、Agent 执行性能优化（F-105 ✅ / F-106 ✅）](#十一Agent-执行性能优化F-105---F-106-)
- [附录：F-Number 快速索引](#附录F-Number-快速索引)

---

## 项目概述与边界约束

### 1.1 项目定位

ClawCodex 是 Anthropic Claude Code 的 Python 移植版，同时扩展多 Provider 支持，目标成为功能完整的 AI Agent CLI 工具。

### 1.2 当前架构（三层解耦）

```
src/
├── upstream/            # Layer 1: 上游快照
├── capabilities/        # Layer 2: 协议接口定义
├── orchestrator/        # Layer 3: 自主模式编排
├── api/                 # Layer 3: 公共 Python API
└── ...                  # 其余上游原有模块
```

**核心约束**: 所有 downstream/custom 开发默认进入 `clawcodex_ext/*`，`src/*` 仅接受 thin forwarding seams 和最小适配层。

---

## 已归档功能模块

> **已实现功能已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)**
> 标记为 ✅ 的详细设计与实现记录均已在归档文档中。

---

## 一、Orchestrator 系统

### F-36 LocalTracker 本地 Issue 文档源设计 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
LocalTracker 本地 Issue 文档源设计 已实现并归档。

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.1](./ARCHIVED_FEATURES.md#二十一1-f-36-localtracker-本地-issue-文档源)。

---

### F-37 PR 检视意见自动修复闭环 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P0 |
| 目标 | 将"基于 PR 网页检视意见自动修改并更新 PR"的能力产品化到 `extensions/orchestrator`，形成 issue → implementation PR → review feedback → follow-up fix → push update 的自动闭环。 |

#### 概述
状态**: ✅ 已完成（核心链路已验证）

> 完整实现（PullRequestFeedback / ReviewFeedbackConfig / ReviewFeedbackService / Orchestrator review follow-up 轮询 / GitSync follow-up 模式）已在 `extensions/orchestrator/` 落地。详细落地记录见 [ARCHIVED_FEATURES.md §二十一.9 F-37 PR 检视意见自动修复闭环](./ARCHIVED_FEATURES.md#二十一9-f-37-pr-检视意见自动修复闭环)。

---

### F-38 验证与报告闭环 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
验证与报告闭环 已实现并归档。

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.2](./ARCHIVED_FEATURES.md#二十一2-f-38-orchestrator-验证与报告闭环)。

---

### F-39 Issue 重跑入口 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 完成（Sub-A~F）

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.3](./ARCHIVED_FEATURES.md#二十一3-f-39-orchestrator-issue-重跑入口)。

---

### F-42 Shared/Sequential Workspace ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
Shared/Sequential Workspace 已实现并归档。

> `workspace.strategy: isolated | shared | sequential` 落地。详见 [ARCHIVED_FEATURES.md §二十一.5](./ARCHIVED_FEATURES.md#二十一5-f-42-sharedsequential-workspace-策略)。

---

### F-40 ProgressReporter Sink 重构 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成（代码已全部落地）

> Protocol 设计、架构对比、关键组件（ProgressSink / CompositeProgressSink / ToolContextProgressSink / ProgressReporter shim）、改造点、进度计算、验收标准、风险与实施阶段的完整设计文档已归档至 [ARCHIVED_FEATURES.md §二十一.7 F-40 ProgressReporter Sink 重构](./ARCHIVED_FEATURES.md#二十一7-f-40-progressreporter-sink-重构)。

---

### F-51 AgentRunner 空转检测机制 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
AgentRunner 空转检测机制 已实现并归档。

> 内置空转检测逻辑。详见 [ARCHIVED_FEATURES.md §二十一.8](./ARCHIVED_FEATURES.md#二十一8-f-51-agentrunner-空转检测)。

---

### F-54 运行期可观测性与 stuck-run debug 🔄

| 属性 | 值 |
|------|-----|
| 状态 | 🔄 进行中 |

#### 概述
场景：headless agent 在 issue 开发中途陷入迷茫 / operator 想人工介入

#### 实现状态
- 详见原始设计文档，部分模块已实现。
- 详见原始设计文档，剩余工作待推进。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `metadata.json` | 实现文件 |

---

### F-45 Tool-call 审计旁路设计 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
Tool-call 审计旁路设计 已实现并归档。

> 为工具调用增加审计日志旁路。详见 [ARCHIVED_FEATURES.md §二十一.6](./ARCHIVED_FEATURES.md#二十一6-f-45-tool-call-审计旁路)。

---

### F-41 Coordinator 轻量工具集 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
Coordinator 轻量工具集 已实现并归档。

> Coordinator 配置独立轻量工具集（Read、WebSearch、WebFetch）。详见 [ARCHIVED_FEATURES.md §二十一.4](./ARCHIVED_FEATURES.md#二十一4-f-41-coordinator-轻量工具集)。

---

### F-49 Issue 会话统一存储与实时介入协议 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |

#### 概述
依赖**: F-49 Phase 0 ~ 0.3（统一事件存储），F-21（后台运行 + 恢复同步）

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

---

### F-103 — parentUuid 链 + walkChainBeforeParse 读取过滤 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | 引入 CCB 的 `parentUuid` 链式消息关联 + `walkChainBeforeParse` 字节级链裁剪，彻底消除 `/rewind`/fork/死分支导致的 on-disk 与 in-memory 状态不一致问题。 |

#### 概述
目标**: 引入 CCB 的 `parentUuid` 链式消息关联 + `walkChainBeforeParse` 字节级链裁剪，彻底消除 `/rewind`/fork/死分支导致的 on-disk 与 in-memory 状态不一致问题。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `src/services/session_storage.py` | 实现文件 |
| `clawcodex_ext/agent/chain_filter.py` | 实现文件 |
| `clawcodex_ext/agent/session.py` | 实现文件 |
| `extensions/agent/session_persist.py` | 实现文件 |
| `clawcodex_ext/repl/core.py` | 实现文件 |
| `tests/test_session_f103_chain.py` | 实现文件 |

---

### F-1.10 声明式工作流引擎核心 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P0 |
| 目标 | 读取 `workflow.yaml`，按 DAG 顺序调度 Agent，管理 GATE/DECISION/回环，提供工作流级错误恢复和成本追踪。 |

#### 概述
目标**：读取 `workflow.yaml`，按 DAG 顺序调度 Agent，管理 GATE/DECISION/回环，提供工作流级错误恢复和成本追踪。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `workflow.yaml` | 实现文件 |
| `extensions/orchestrator/workflow_engine/engine.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/workflow_state.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/event_bus.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/cost.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/errors.py` | 实现文件 |

---

### F-1.11 StageRunner 适配器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P0 |
| 目标 | 桥接 `DeclarativeWorkflowEngine` 与 `AgentRunner`，将阶段执行适配为 `AgentRunner` 可消费的工作单元。 |

#### 概述
目标**：桥接 `DeclarativeWorkflowEngine` 与 `AgentRunner`，将阶段执行适配为 `AgentRunner` 可消费的工作单元。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/orchestrator/workflow_engine/stage_runner.py` | 实现文件 |

---

### F-1.12 GATE 门禁处理器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 处理工作流中的 GATE 阶段——人类审批、自动阈值、回滚。 |

#### 概述
目标**：处理工作流中的 GATE 阶段——人类审批、自动阈值、回滚。

#### 设计要点
- **manual** — 通过 ClarificationQueue（F-39）暂停工作流，等待人类审批/拒绝
- **auto** — 基于 ValidatorSpec 自动判定，所有 validator 通过即 approve
- **threshold** — LLM-as-judge 评分，达到阈值自动 approve，否则进入 manual

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/orchestrator/workflow_engine/gate_handler.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/gate_modes.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/gate_rollback.py` | 实现文件 |

---

### F-1.13 DECISION 决策处理器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 处理工作流中的决策点——多结果分支、回环、收敛检测。 |

#### 概述
目标**：处理工作流中的决策点——多结果分支、回环、收敛检测。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/orchestrator/workflow_engine/decision_handler.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/decision_history.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/rollback.py` | 实现文件 |

---

### F-1.14 阶段契约验证器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 执行阶段输出的机器可验证 DoD 检查。 |

#### 概述
目标**：执行阶段输出的机器可验证 DoD 检查。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/orchestrator/workflow_engine/validators/__init__.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/validators/builtin.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/validators/llm_judge.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/validators/custom.py` | 实现文件 |

---

### F-1.15 检查点与恢复 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 工作流级检查点持久化，支持从任意阶段恢复执行。 |

#### 概述
目标**：工作流级检查点持久化，支持从任意阶段恢复执行。

#### 设计要点
- 复用 ARC 已有的原子写入模式（temp file + rename）
- 复用 Orchestrator 的 `SessionStorage`（F-49）存储每阶段 Agent session transcript
- 复用 State Journal Writer（F-91~F-96）写入工作流级事件日志

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/orchestrator/workflow_engine/checkpoint.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/resume.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/artifact_resolver.py` | 实现文件 |

---

### F-1.16 工作流可观测性集成 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 将工作流执行事件集成到 ClawCodex 的可视化和审计体系。 |

#### 概述
目标**：将工作流执行事件集成到 ClawCodex 的可视化和审计体系。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/orchestrator/workflow_engine/observability.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/progress.py` | 实现文件 |
| `extensions/orchestrator/workflow_engine/audit.py` | 实现文件 |

---

### F-118 动态任务分解引擎 🔭

| 属性 | 值 |
|------|-----|
| 状态 | 🔭 长期规划 |
| 优先级 | P2 |
| 目标 | 单次复杂任务实时分解为多个 subagent 并行/串行执行，动态规划子任务、调度 wave、合并结果。 |

#### 概述
状态**：🔭 长期规划（本特性规划文档仅做方向性定义）

---


## 二、Agent 核心能力

### F-20 Agent 阶段性进度汇报 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | 在 Agent 编排中阶段性将结果汇报至任务看板，将任务看板提取为工具 |

#### 概述
状态**: ✅ 已完成（F-20）

> 详见 [ARCHIVED_FEATURES.md §十六（Orchestrator 自主模式 16.x）](./ARCHIVED_FEATURES.md#十六orchestrator-自主模式symphony-集成) 与对应进度归档 [ARCHIVED_PROGRESS.md F-20](./ARCHIVED_PROGRESS.md#f-20-agent-阶段性进度汇报)。

---

### F-2 Team 成员管理（Phase-7） ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
Team 成员管理（Phase-7） 已实现并归档。

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

---

### F-4 结构化输出增强（Outlines） ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | 使用 Outlines 预生成约束替代 json.loads + 手动验证 |

#### 概述
状态**: ✅ 已完成（F-4）

> 适配器已完整实现并迁移至 `clawcodex_ext/agent/_outlines_adapter.py`。详细设计（适用场景、数据模型、实现文件）已归档至 [ARCHIVED_FEATURES.md §二十三.5 F-4 结构化输出增强](./ARCHIVED_FEATURES.md#二十三5-f-4-结构化输出增强)。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `clawcodex_ext/agent/_outlines_adapter.py` | 实现文件 |

---

### F-3 MCP 扩展功能 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P2 |
| 目标 | 完整的 MCP 协议支持 |

#### 概述
状态**: 基础已完成（F-3），持续增强

> 详见 [ARCHIVED_FEATURES.md §十七（MCP 协议扩展）](./ARCHIVED_FEATURES.md#十七mcp-协议扩展) 与对应进度归档 [ARCHIVED_PROGRESS.md F-3](./ARCHIVED_PROGRESS.md#f-3-mcp-协议扩展)。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `clawcodex_ext/mcp_ext.py` | 实现文件 |

---

### F-13 Agent 记忆作用域隔离 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
Agent 记忆作用域隔离 已实现并归档。

> 详细设计与验证记录已归档至 [ARCHIVED_FEATURES.md §二十一.7 F-13 Agent 记忆作用域隔离](./ARCHIVED_FEATURES.md#二十一7-f-13-agent-记忆作用域隔离)。

---

### F-9 /goal 命令（目标管理） ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | 为长时间运行任务提供持久化目标、自动续跑、token 用量监控与恢复能力，避免用户需要反复输入“继续”。 |

#### 概述
状态**: ✅ 已完成（2026-06-19 代码审计确认）| **实现位置**: `clawcodex_ext/goal/` 9 文件 2538 行

> 完整设计（功能说明、状态机、核心机制、Token 追踪、Blocked/Completion 审计、提示词注入、持久化恢复、实现文件清单、UI 展示、测试覆盖）已归档至 [ARCHIVED_FEATURES.md §äºåå F-9 /goal 命令](./ARCHIVED_FEATURES.md#二十四f-9-goal-命令目标管理)。

---

### F-10 ExecuteExtraTool 延迟工具系统 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 目标 | 按需加载延迟工具，支持语义搜索 |

#### 概述
目标**: 按需加载延迟工具，支持语义搜索

#### 关键文件
| 文件 | 说明 |
|------|------|
| `packages/builtin-tools/src/tools/ExecuteTool/ExecuteTool.ts` | 实现文件 |
| `constants/tools.ts` | 实现文件 |
| `constants/prompts.ts` | 实现文件 |

---

### F-75 工具/Skill 调用统计（跨会话） ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
工具/Skill 调用统计（跨会话） 已实现并归档。

> ✅ 已归档至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md)

---

### F-18 CreateAgentTool 动态工具创建 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | Agent 可根据三方 CLI/API 规范动态创建工具，实现"工具创建工具"的 Meta Tool 能力 |

#### 概述
目标**: Agent 可根据三方 CLI/API 规范动态创建工具，实现"工具创建工具"的 Meta Tool 能力

> 详细设计（架构设计、AgentToolSpec 规范、三种 call_impl 安全限制、安全性约束、持久化机制、与现有系统集成、实现文件清单）已归档至 [ARCHIVED_FEATURES.md §二十三.1 F-18 CreateAgentTool 动态工具创建](./ARCHIVED_FEATURES.md#二十三1-f-18-createagenttool-动态工具创建)。

---

### F-11 sessionStorage 容量限制 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | 防止长时间运行的 daemon/swarm 会话导致内存泄漏 |

#### 概述
目标**: 防止长时间运行的 daemon/swarm 会话导致内存泄漏

> 完整设计（功能说明、问题场景、实现文件）已归档至 [ARCHIVED_FEATURES.md §äºåäº F-11 sessionStorage 容量限制](./ARCHIVED_FEATURES.md#二十五f-11-sessionstorage-容量限制)。

---

### F-12 cacheWarning 容量限制 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
cacheWarning 容量限制 已实现并归档。

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.14 cacheWarning 容量限制](./ARCHIVED_FEATURES.md#二十一14-cachewarning-容量限制f-12)。

---

### F-78 Issue 语义澄清流程（自主模式扩展） ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |
| 目标 | 当 Issue 语义模糊时，通过**三通道优先机制**获取澄清——本地操作员（Dashboard/ClarificationQueue）优先，作者 @mention 兜底 |

#### 概述
状态**: ✅ 已完成（2026-06-19 代码审计确认）

> 详见 [ARCHIVED_FEATURES.md §16.5（Issue 语义澄清流程）](./ARCHIVED_FEATURES.md#十六orchestrator-自主模式symphony-集成) 与对应进度归档 [ARCHIVED_PROGRESS.md F-1.x 子特性](./ARCHIVED_PROGRESS.md#f-1x-orchestrator-自主模式f-1-子特性全部完成)。

---

### F-16 Auto 模式 (TRANSCRIPT_CLASSIFIER) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 目标 | 基于 LLM 的自动权限模式切换，减少交互疲劳 |

#### 概述
状态**: ✅ 已完成（F-16）

> `auto_mode_classify()` 完整实现在 `src/permissions/check.py`：覆盖 Bash、Read、Write/Edit、Agent、MCP 等工具类型。配套 `DenialTracker` 支持拒绝计数与自动升级。详细设计（工作原理、模式对比、循环切换逻辑、分类器 prompt 设计、实施阶段）已归档至 [ARCHIVED_FEATURES.md §二十三.2 F-16 Auto 模式](./ARCHIVED_FEATURES.md#二十三2-f-16-auto-模式-transcript_classifier)。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `src/permissions/check.py` | 实现文件 |

---

### F-80 Agent 间自主观察与消息交互 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |
| 目标 | 实现 Manager Agent 全自动观察 Worker Agent 状态并注入指令，支持优先级队列和权限审批 |

#### 概述
状态**: ✅ 已完成（2026-06-19 代码审计确认）

> 详见 [ARCHIVED_FEATURES.md §十八（Agent 间自主观察与消息交互）](./ARCHIVED_FEATURES.md#十八agent-间自主观察与消息交互) 与对应进度归档 [ARCHIVED_PROGRESS.md F-29（TaskInspect/TaskDirectives 工具注册）](./ARCHIVED_PROGRESS.md#f-29-taskinspecttaskdirectives-工具注册)。

---

### F-99 Ctrl+C/B 即时中断响应优化 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P0 |
| 目标 | 解决 LLM 流式响应 + 工具执行阶段按 Ctrl+C/Ctrl+B 需要 10~30s 才生效的 UX 问题，目标 < 500ms。 |

#### 概述
状态**: ✅ 已完成（2026-06-17）| **优先级**: P0

> 完整设计（问题根因、三层方案架构、改造点清单、验收标准、风险与约束、设计决定、依赖与协同）已归档至 [ARCHIVED_FEATURES.md §äºåå­ F-99 Ctrl+C/B 即时中断响应优化](./ARCHIVED_FEATURES.md#二十六f-99-ctrlcb-即时中断响应优化)。

---

### F-100 Dreaming 后台记忆整合系统 🔄

| 属性 | 值 |
|------|-----|
| 状态 | 🔄 进行中 |
| 优先级 | P2 |
| 目标 | 从上游 fork 移植 dreaming 子系统（`DreamTask` 后台探索 + `autoDream` 自动 consolidate auto-memory + `/dream` slash skill），让 clawcodex 拥有"空闲时自我整合记忆"的能力。后续章节"背景 / 现状 / 方案 / 任务"对应 `PROGRESS.md` 十三节。 |

#### 概述
状态**: 🔄 部分完成（主体已落地，Phase B 待补） | **优先级**: P2 | **登记日期**: 2026-06-17 | **完成日期**: 2026-06-18

#### 实现状态
- 详见原始设计文档，部分模块已实现。
- 📋 **状态**: 🔄 部分完成（主体已落地，Phase B 待补） | **优先级**: P2 | **登记日期**: 2026-06-17 | **完成日期**: 2026-06-18
- 📋 - 行为：扫描未关联 / 低信号 auto-memory → 调 LLM 总结 → 写回索引
- 📋 - 启动时若未注册自动补齐

#### 关键文件
| 文件 | 说明 |
|------|------|
| `autoDream.ts` | 实现文件 |
| `config.ts` | 实现文件 |
| `consolidationLock.ts` | 实现文件 |
| `consolidationPrompt.ts` | 实现文件 |
| `src/tasks/DreamTask/DreamTask.ts` | 实现文件 |
| `src/skills/bundled/dream.ts` | 实现文件 |

---

### F-102 Agent Loop Hook 扩展点增强 🔄

| 属性 | 值 |
|------|-----|
| 状态 | 🔄 进行中 |
| 优先级 | P1 |
| 目标 | 填补 agent loop（`query()`）中 5 个 hook 扩展点缺口，为 F-68 Feature Gate / F-70 Plugin 系统提供基础设施，使新特性无需修改 `query()` 函数体即可注入自定义逻辑。 |

#### 概述
状态**: 🔄 部分完成（P102-A~E 全部实现，待 mypy 严格模式验证） | **优先级**: P1 | **登记日期**: 2026-06-22

#### 实现状态
- 详见原始设计文档，部分模块已实现。
- 📋 **状态**: 🔄 部分完成（P102-A~E 全部实现，待 mypy 严格模式验证） | **优先级**: P1 | **登记日期**: 2026-06-22
- 📋 **目标**: 填补 agent loop（`query()`）中 5 个 hook 扩展点缺口，为 F-68 Feature Gate / F-70 Plugin 系统提供基础设施，使新特性无需修改 `query()` 函数体即可注入自定义逻辑。

---

### F-107 PowerShell 支持增强 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P2 |
| 目标 | 让 ClawCodex 的 BashTool 能够感知并适配 Windows 原生 shell（PowerShell），涵盖工具级 shell 选择、PowerShell 兼容的进程启动与 CWD 追踪、PowerShell 命令集分类/安全/只读/语义适配，以及 Windows 平台自动检测与优雅降级。 |

#### 概述
状态**: 📋 设计完成 | **优先级**: P2 | **登记日期**: 2026-06-23

#### 设计要点
- **工具不重命名** — 保持 `BashTool` / `Bash` 作为向后兼容名，因为上游 TS 也是 `BashTool`。在 prompt 和注释中说明 shell 参数可切换解释器。
- **`"auto"` 检测规则** — 仅当 `sys.platform == "win32"` 且 `find_powershell_path()` 返回非 None 时默认 PowerShell；否则默认 bash。
- **CWD 追踪优雅降级** — 若 PowerShell 的 CWD 读取失败，工具不失败，仅不更新 context.cwd——与 bash 路径的 OSError 处理一致。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `search_classification.py` | 实现文件 |
| `read_only_validation.py` | 实现文件 |
| `command_semantics.py` | 实现文件 |
| `permissions/bash_security.py` | 实现文件 |
| `destructive_warnings.py` | 实现文件 |
| `prompt.py` | 实现文件 |

---

### F-108 Freeze Detection & Auto-Recovery 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P0 |
| 目标 | 系统性解决 clawcodex 偶发软件卡死与 LLM 对话卡死问题。全链路代码审计发现 8 个卡死风险点（2 CRITICAL + 3 HIGH + 2 MEDIUM + 1 LOW），采用四层混合方案（Layer 0 快速修复 + Layer 1 冻结检测 + Layer 2 硬超时 + Layer 3 自动恢复 + Layer 4 诊断命令），确保用户在卡死发生后 < 30s 内自动恢复或收到明确诊断。 |

#### 概述
状态**: 📋 设计完成 | **优先级**: P0 | **登记日期**: 2026-06-23

#### 关键文件
| 文件 | 说明 |
|------|------|
| `clawcodex_ext/agent/run_agent.py` | 实现文件 |
| `clawcodex_ext/entrypoints/headless.py` | 实现文件 |
| `clawcodex_ext/tui/agent_bridge.py` | 实现文件 |
| `clawcodex_ext/query/query.py` | 实现文件 |
| `extensions/api/query.py` | 实现文件 |
| `clawcodex_ext/providers/anthropic_provider.py` | 实现文件 |

---


## 三、CLI 与配置系统

### F-43 CLI 模型供应商与模型切换设计 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 (2026-06-02)

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.8 F-43 CLI 模型供应商与模型切换](./ARCHIVED_FEATURES.md#二十一8-f-43-cli-模型供应商与模型切换)。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `clawcodex_ext/cli/model_cmd/registry.py` | 实现文件 |
| `clawcodex_ext/providers/hooks.py` | 实现文件 |

---

### F-47 Permission Settings Schema 重构设计 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 完成（含 F-47.1 hotfix）

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.9 F-47 Permission Settings Schema 重构](./ARCHIVED_FEATURES.md#二十一9-f-47-permission-settings-schema-重构)。

---


## 四、Architecture & SDK 下沉

### F-50 SOP 转换器源码固化设计 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |

#### 概述
SOP 转换器源码固化设计 已实现并归档。

> 详细设计与落地记录已归档至 [ARCHIVED_FEATURES.md §二十一.13 F-50 SOP 转换器源码固化](./ARCHIVED_FEATURES.md#二十一13-f-50-pos-转换器源码固化sourcecodeparser--增强-skillgrouper--agentmarkdownwriter)。

---

### F-55 SOP 转换器分组策略增强设计 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |

#### 概述
状态**: ✅ 已实现 | **优先级**: P1

> 完整设计（四种分组策略、CLI 接口、实现架构、Agent 数量量化对比、风险与约束、设计决定）已归档至 [ARCHIVED_FEATURES.md §äºåä¸ F-55 SOP 转换器分组策略增强](./ARCHIVED_FEATURES.md#二十七f-55-sop-转换器分组策略增强)。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/skill_grouper.py` | 实现文件 |

---

### F-50.10 工作流判别器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 自动判断输入源码是否具备固定编排工作流特征，决定使用标准 SDK 模式还是工作流模式。 |

#### 概述
目标**：自动判断输入源码是否具备固定编排工作流特征，决定使用标准 SDK 模式还是工作流模式。

#### 设计要点
- **复用 F-50**：`SourceCodeParser` 的 AST 解析基础设施做初步扫描
- **依赖 F-50.11**：判别结果决定后续是否调用 WorkflowExtractor

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/discriminator.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/heuristics.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/models.py` | 实现文件 |

---

### F-50.11 工作流结构提取器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P0 |
| 目标 | 从目标应用的 Python 源码中提取阶段定义、转换规则、GATE 逻辑、DECISION 回环为 `WorkflowGraph`。 |

#### 概述
目标**：从目标应用的 Python 源码中提取阶段定义、转换规则、GATE 逻辑、DECISION 回环为 `WorkflowGraph`。

#### 设计要点
- 阶段枚举发现——扫描 `IntEnum`/`Enum` 子类，匹配大写+下划线模式
- 转换规则发现——查找字典字面量，键值为枚举引用（`NEXT_STAGE` 等命名）
- GATE 发现——查找 `frozenset`/`set` 字面量（`GATE_*`）+ 返回 `bool` 的函数（`*_gate`）
- 决策发现——查找字典含 `pivot`/`refine`/`proceed` 关键词
- 契约发现——查找 `input_files`/`output_files` 字段的 dataclass 或字典

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/extractors/base.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/ast_helpers.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/registry.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/models.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/arc.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/generic.py` | 实现文件 |

---

### F-50.12 阶段能力映射器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 分析每个阶段的实现代码，提取外部依赖和能力特征，推荐执行模式（agent_native / wrapper / hybrid）。 |

#### 概述
目标**：分析每个阶段的实现代码，提取外部依赖和能力特征，推荐执行模式（agent_native / wrapper / hybrid）。

#### 设计要点
- **依赖 F-50.11**：需要 `WorkflowGraph` 中的阶段文件路径
- **协同 F-52**：提取出的外部 API 可自动注册为 Tool

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/capability/mapper.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/capability/analyzer.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/capability/patterns.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/capability/models.py` | 实现文件 |

---

### F-50.13 工作流 Schema 生成器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P0 |
| 目标 | 定义并生成声明式工作流 YAML 格式，支持 DAG、GATE、DECISION、回环、契约验证。 |

#### 概述
目标**：定义并生成声明式工作流 YAML 格式，支持 DAG、GATE、DECISION、回环、契约验证。

#### 设计要点
- id: <int>
- from: <stage-id>

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/schema/workflow_schema.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/schema/parser.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/schema/dag_validator.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/schema/validator_spec.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/schema/discovery.py` | 实现文件 |

---

### F-50.14 Agent 定义生成器（工作流模式扩展） 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P0 |
| 目标 | 从 `WorkflowGraph` + `CapabilityProfile` 批量生成阶段 Agent 定义文件。 |

#### 概述
目标**：从 `WorkflowGraph` + `CapabilityProfile` 批量生成阶段 Agent 定义文件。

#### 设计要点
- **Agent-native**：完整 frontmatter + 任务描述 + 执行步骤 + 质量要求
- **Wrapper**：精简版，核心为 `wrapper_command` + 输出验证
- **Hybrid**：混合步骤指导 + Bridge 调用
- 工作流总览（阶段列表 + 相位分组）
- 子 Agent 目录

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/generator/agent_def_gen.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/generator/skill_gen.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/generator/tool_gen.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/generator/overview_gen.py` | 实现文件 |

---

### F-50.15 源码桥接器生成器 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 生成 Bridge 模块，使 Agent 可以通过 Python API 调用目标应用的单阶段执行。 |

#### 概述
目标**：生成 Bridge 模块，使 Agent 可以通过 Python API 调用目标应用的单阶段执行。

#### 设计要点
- **依赖 F-50.11**：提取到的 CLI 入口点、API 函数签名
- **依赖 F-50.13**：阶段 ID 和契约信息
- **复用 F-52**：`register_python_function()` 用于 Bridge Tool 注册

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/bridge/generator.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/bridge/mcp_adapter.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/bridge/health_check.py` | 实现文件 |

---

### F-50.16 提取器适配器库 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |
| 目标 | 提供常见 FWA 项目的提取器适配器。 |

#### 概述
目标**：提供常见 FWA 项目的提取器适配器。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `extensions/pos_converter/workflow_mode/extractors/adapters/arc.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/generic.py` | 实现文件 |
| `extensions/pos_converter/workflow_mode/extractors/adapters/template.py` | 实现文件 |

---

### F-52 Python SDK 方法注册为 Tool ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
Python SDK 方法注册为 Tool 已实现并归档。

> `register_python_function()` / `list_python_functions()`、`build_tool_from_spec()` python/http/bash 支持、`AgentToolSpec` 数据模型均已实现。详细设计（背景、架构、数据模型、实现切片、验收标准、风险与约束、依赖与协同）已归档至 [ARCHIVED_FEATURES.md §二十三.3 F-52 Python SDK 方法注册为 Tool](./ARCHIVED_FEATURES.md#二十三3-f-52-python-sdk-方法注册为-tool)。

---

### F-53 Tool 自动暴露为 CLI 斜杠命令 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P3 |
| 目标 | 将注册到 `ToolRegistry` 的工具自动暴露为 REPL/TUI 中的 `/tool-name` 斜杠命令，使 SOP 生成的子 Agent 方法（如 `detect_modality`）同时可在 CLI 中作为常规命令直接调用。 |

#### 概述
目标**: 将注册到 `ToolRegistry` 的工具自动暴露为 REPL/TUI 中的 `/tool-name` 斜杠命令，使 SOP 生成的子 Agent 方法（如 `detect_modality`）同时可在 CLI 中作为常规命令直接调用。

#### 设计要点
- 已注册的 `Tool` 自动映射为 `/tool-name` 斜杠命令，无手动配置。
- 命令参数从 Tool 的 param schema 自动推导，支持 `--param value` 风格。
- 命令执行结果直接输出到当前对话上下文。
- 保持 `src/*` 零改动——所有新增代码落入 `clawcodex_ext/cli/`。
- `clawcodex_ext/cli/tool_cmd/hooks.py` — REPL 启动钩子，在 `subcommand_registry` 初始化后执行 `discover_and_register()`。
- TUI 集成 — `clawcodex_ext/tui/` 在斜杠补全列表中加入 `/tool-name` 候选。
- 测试 — 覆盖 ParamSpec→argparse 映射、工具过滤、参数验证失败处理、工具执行结果展示。
- `DynamicCommandDiscovery` 正确过滤核心工具（Read/Write/Bash 等不产生 `/read` 命令）

#### 关键文件
| 文件 | 说明 |
|------|------|
| `clawcodex_ext/cli/tool_cmd/discovery.py` | 实现文件 |
| `clawcodex_ext/cli/tool_cmd/command.py` | 实现文件 |
| `clawcodex_ext/cli/tool_cmd/hooks.py` | 实现文件 |
| `clawcodex_ext/frontend/repl.py` | 实现文件 |
| `clawcodex_ext/cli/dispatch.py` | 实现文件 |

---


## 五、Cron 系统执行引擎（F-22 🔄）

### F-22-G1 Feature Gate 系统——isKilled 运行时 kill 开关 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P0 |

#### 概述
参考实现**: `claude-code-best/src/utils/cronScheduler.ts` 的 `isKilled` 轮询 + `prompt.ts` 的 `isKairosCronEnabled` / `CLAUDE_CODE_DISABLE_CRON` 环境变量

#### 关键文件
| 文件 | 说明 |
|------|------|
| `claude-code-best/src/utils/cronScheduler.ts` | 实现文件 |
| `prompt.ts` | 实现文件 |
| `cronScheduler.ts` | 实现文件 |
| `tools.py` | 实现文件 |

---

### F-22-G2 远程 Jitter 实时配置 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P0 |

#### 概述
参考实现**: `claude-code-best/src/utils/cronJitterConfig.ts` -> GrowthBook Feature Flag `tengu_kairos_cron_config` -> Zod 校验 + 兜底默认值

#### 关键文件
| 文件 | 说明 |
|------|------|
| `claude-code-best/src/utils/cronJitterConfig.ts` | 实现文件 |
| `.claude/cron_jitter_config.json` | 实现文件 |

---

### F-22-G3 One-shot 反向 Jitter（整点提前） ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |

#### 概述
现状**: F-22 Phase C 描述了基本 jitter 但未明确区分正向与反向 jitter。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `claude-code-best/src/utils/cronTasks.ts` | 实现文件 |
| `jitter.py` | 实现文件 |

---

### F-22-G4 Permanent 免过期任务机制 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |

#### 概述
现状**: F-22 Phase B 已规划 `permanent` 字段作为数据模型的一部分，但缺少助手指令模式的用例设计。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `claude-code-best/src/utils/cronTasks.ts` | 实现文件 |
| `src/assistant/install.ts` | 实现文件 |

---

### F-22-G5 锁注册式清理与 PID 存活探测增强 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P1 |

#### 概述
实施状态（2026-06）**: ✅ 完成。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `claude-code-best/src/utils/cronTasksLock.ts` | 实现文件 |
| `lock.py` | 实现文件 |
| `cronTasksLock.ts` | 实现文件 |

---

### F-22-G6 工具 Prompt 指引文档增强 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P2 |

#### 概述
参考实现**: `claude-code-best` 的 `CronCreateTool.ts` / `CronDeleteTool.ts` 中内联的全面 prompt 文档

#### 关键文件
| 文件 | 说明 |
|------|------|
| `CronCreateTool.ts` | 实现文件 |
| `CronDeleteTool.ts` | 实现文件 |

---

### F-22-G7 Analytics 遥测事件注入 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P2 |

#### 概述
参考实现**: `claude-code-best` 的 `tengu_scheduled_task_fire` / `tengu_scheduled_task_missed` / `tengu_scheduled_task_expired`

---

### F-22-G8 inFlight 防重复触发机制 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P2 |

#### 概述
参考实现**: `claude-code-best/src/utils/cronScheduler.ts` 的 `inFlight` Set

#### 关键文件
| 文件 | 说明 |
|------|------|
| `claude-code-best/src/utils/cronScheduler.ts` | 实现文件 |

---

### F-22-D1 Cron 任务累计防护——CCB 4 层设计对照审查（~D4） 📋 设计完成 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |

#### 概述
背景**：CCB 通过 4 层防护机制确保 cron 定时任务在"每分钟触发、1 小时执行"的场景下不会出现消息堆积和 OOM。以下是逐层对照审查结论。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `runs.json` | 实现文件 |
| `clawcodex_ext/cron_system/runs.py` | 实现文件 |
| `lock.py` | 实现文件 |
| `cronScheduler.ts` | 实现文件 |
| `clawcodex_ext/cron_system/scheduler.py` | 实现文件 |
| `cronTasksLock.ts` | 实现文件 |

---


## 六、会话恢复增强（F-49 / F-103 补缺 ✅）


## 七、CCB 对标缺口补缺（F-60~F-90 🔄）

### F-60 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-61 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-62 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-63 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-64 Voice Mode 语音输入 ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |
| 优先级 | P2 |

#### 概述
状态**: ✅ 已完成（接口层已完成） | **优先级**: P2 | **对标**: CCB Voice Mode

#### 关键文件
| 文件 | 说明 |
|------|------|
| `detection.py` | 实现文件 |
| `stt.py` | 实现文件 |

---

### F-65 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-66 ACP 协议支持 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P2 |

#### 概述
ACP 协议支持 处于设计阶段。

---

### F-67 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-81 Native 原生模块系统（Python 可实现部分） 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |

#### 概述
Native 原生模块系统（Python 可实现部分） 处于设计阶段。

---

### F-82 Remote Control Server 远程控制服务 🔄 🔄

| 属性 | 值 |
|------|-----|
| 状态 | 🔄 进行中 |

#### 概述
Remote Control Server 远程控制服务 🔄 正在实现中。

#### 实现状态
- 详见原始设计文档，部分模块已实现。
- 详见原始设计文档，剩余工作待推进。

---

### F-90 Hermes Gateway 参考实现（OpenAI 兼容 API 服务器） 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |

#### 概述
本 F-Number 记录本项目已实现的功能完整实现**（已通过 `extensions/remote_api/` 落地 11 个模块 2597 行，含 completion/responses API、SSE 流式、Bearer 认证、CLI `clawcodex api serve` 子命令；测试见 `tests/remote_api/`），同时为 F-82 (Remote Control Server) 和 F-66 (ACP 协议) 提供具体架构参考。ClawCodex 可在实现 F-82 时选型复用以下设计模式。

#### 设计要点
- 若 F-82 需 Open WebUI / LobeChat 等前端接入，建议优先适配 OpenAI `/v1/chat/completions` + `/api/sessions` 接口
- 消息规范化（`_normalize_chat_content`）可迁移为通用中间件
- SSE Tool Progress 事件可复用作为 F-82.5 的事件流实现方案
- LRU Agent 缓存方案可直接迁移（只需替换 Hermes 类型为 ClawCodex Agent 类型）

#### 关键文件
| 文件 | 说明 |
|------|------|
| `gateway/platforms/api_server.py` | 实现文件 |
| `gateway/run.py` | 实现文件 |
| `hermes_cli/gateway.py` | 实现文件 |

---

### F-83 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-84 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-85 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-86 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-87 Workflow Scripts 工作流脚本 ⛔ ⛔

| 属性 | 值 |
|------|-----|
| 状态 | ⛔ 已被取代 |
| 优先级 | P2 |

#### 概述
Workflow Scripts 工作流脚本 ⛔ 已被其他特性取代，不再作为独立特性实施。

**状态**: ⛔ 已被取代 | **优先级**: P2 | **对标**: CCB FEATURE_WORKFLOW_SCRIPTS

---

### F-88 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-68 Feature Gate 运行时特性开关系统 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |

#### 概述
状态**: 📋 待开始 | **优先级**: P1

---

### F-69 Budget / Poor Mode 资源节俭模式 🔄

| 属性 | 值 |
|------|-----|
| 状态 | 🔄 进行中 |
| 优先级 | P1 |

#### 概述
状态**: 🔄 部分完成 | **优先级**: P1

#### 实现状态
- 详见原始设计文档，部分模块已实现。
- 详见原始设计文档，剩余工作待推进。

#### 关键文件
| 文件 | 说明 |
|------|------|
| `clawcodex_ext/query/token_budget.py` | 实现文件 |

---

### F-70 Plugin 插件系统基础框架 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |

#### 概述
状态**: 📋 待开始 | **优先级**: P1

---

### F-71 内置工具补齐（缺失工具批量实现） 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |

#### 概述
状态**: 📋 待开始 | **优先级**: P1

---

### F-72 Multi-API 原生适配器扩展 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P1 |

#### 概述
状态**: 📋 待开始 | **优先级**: P1

---

### F-73 (已归档) ✅

| 属性 | 值 |
|------|-----|
| 状态 | ✅ 已完成 |

#### 概述
状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

> **状态**: ✅ 已完成 — 详细设计已迁移至 [ARCHIVED_FEATURES.md](./ARCHIVED_FEATURES.md#三十已完成特性设计归档FEATURE_PLAN-v314)

---

### F-74 Sandbox / SSH Remote 沙箱远程执行 📋

| 属性 | 值 |
|------|-----|
| 状态 | 📋 规划中 |
| 优先级 | P2 |

#### 概述
状态**: 📋 待开始 | **优先级**: P2

---


## 八、Multi-Session 可视化分析平台（F-91~F-96 ✅）


## 十一、Agent 执行性能优化（F-105 ✅ / F-106 ✅）


## 附录：F-Number 快速索引


## 附录：F-Number 快速索引

| F-编号 | 特性 | 状态 | 优先级 |
|--------|------|:----:|:------:|
| F-36 | LocalTracker 本地 Issue 文档源设计 | ✅ 已完成 | P? |
| F-37 | PR 检视意见自动修复闭环 | ✅ 已完成 | P0 |
| F-38 | 验证与报告闭环 | ✅ 已完成 | P? |
| F-39 | Issue 重跑入口 | ✅ 已完成 | P? |
| F-42 | Shared/Sequential Workspace | ✅ 已完成 | P? |
| F-40 | ProgressReporter Sink 重构 | ✅ 已完成 | P? |
| F-51 | AgentRunner 空转检测机制 | ✅ 已完成 | P? |
| F-54 | 运行期可观测性与 stuck-run debug | 🔄 进行中 | P? |
| F-45 | Tool-call 审计旁路设计 | ✅ 已完成 | P? |
| F-41 | Coordinator 轻量工具集 | ✅ 已完成 | P? |
| F-49 | Issue 会话统一存储与实时介入协议 | ✅ 已完成 | P1 |
| F-103 | — parentUuid 链 + walkChainBeforeParse 读取过滤 | ✅ 已完成 | P? |
| F-1.10 | 声明式工作流引擎核心 | 📋 规划中 | P0 |
| F-1.11 | StageRunner 适配器 | 📋 规划中 | P0 |
| F-1.12 | GATE 门禁处理器 | 📋 规划中 | P1 |
| F-1.13 | DECISION 决策处理器 | 📋 规划中 | P1 |
| F-1.14 | 阶段契约验证器 | 📋 规划中 | P1 |
| F-1.15 | 检查点与恢复 | 📋 规划中 | P1 |
| F-1.16 | 工作流可观测性集成 | 📋 规划中 | P1 |
| F-118 | 动态任务分解引擎 | 🔭 长期规划 | P2 |
| F-20 | Agent 阶段性进度汇报 | ✅ 已完成 | P? |
| F-2 | Team 成员管理（Phase-7） | ✅ 已完成 | P? |
| F-4 | 结构化输出增强（Outlines） | ✅ 已完成 | P? |
| F-3 | MCP 扩展功能 | ✅ 已完成 | P2 |
| F-13 | Agent 记忆作用域隔离 | ✅ 已完成 | P? |
| F-9 | /goal 命令（目标管理） | ✅ 已完成 | P? |
| F-10 | ExecuteExtraTool 延迟工具系统 | 📋 规划中 | P? |
| F-75 | 工具/Skill 调用统计（跨会话） | ✅ 已完成 | P? |
| F-18 | CreateAgentTool 动态工具创建 | ✅ 已完成 | P? |
| F-11 | sessionStorage 容量限制 | ✅ 已完成 | P? |
| F-12 | cacheWarning 容量限制 | ✅ 已完成 | P? |
| F-78 | Issue 语义澄清流程（自主模式扩展） | ✅ 已完成 | P1 |
| F-16 | Auto 模式 (TRANSCRIPT_CLASSIFIER) | ✅ 已完成 | P? |
| F-80 | Agent 间自主观察与消息交互 | ✅ 已完成 | P1 |
| F-99 | Ctrl+C/B 即时中断响应优化 | ✅ 已完成 | P0 |
| F-100 | Dreaming 后台记忆整合系统 | 🔄 进行中 | P2 |
| F-102 | Agent Loop Hook 扩展点增强 | 🔄 进行中 | P1 |
| F-107 | PowerShell 支持增强 | 📋 规划中 | P2 |
| F-108 | Freeze Detection & Auto-Recovery | 📋 规划中 | P0 |
| F-43 | CLI 模型供应商与模型切换设计 | ✅ 已完成 | P? |
| F-47 | Permission Settings Schema 重构设计 | ✅ 已完成 | P? |
| F-50 | SOP 转换器源码固化设计 | ✅ 已完成 | P1 |
| F-55 | SOP 转换器分组策略增强设计 | ✅ 已完成 | P1 |
| F-50.10 | 工作流判别器 | 📋 规划中 | P1 |
| F-50.11 | 工作流结构提取器 | 📋 规划中 | P0 |
| F-50.12 | 阶段能力映射器 | 📋 规划中 | P1 |
| F-50.13 | 工作流 Schema 生成器 | 📋 规划中 | P0 |
| F-50.14 | Agent 定义生成器（工作流模式扩展） | 📋 规划中 | P0 |
| F-50.15 | 源码桥接器生成器 | 📋 规划中 | P1 |
| F-50.16 | 提取器适配器库 | 📋 规划中 | P1 |
| F-52 | Python SDK 方法注册为 Tool | ✅ 已完成 | P? |
| F-53 | Tool 自动暴露为 CLI 斜杠命令 | 📋 规划中 | P3 |
| F-22-G1 | Feature Gate 系统——isKilled 运行时 kill 开关 | ✅ 已完成 | P0 |
| F-22-G2 | 远程 Jitter 实时配置 | ✅ 已完成 | P0 |
| F-22-G3 | One-shot 反向 Jitter（整点提前） | ✅ 已完成 | P1 |
| F-22-G4 | Permanent 免过期任务机制 | ✅ 已完成 | P1 |
| F-22-G5 | 锁注册式清理与 PID 存活探测增强 | ✅ 已完成 | P1 |
| F-22-G6 | 工具 Prompt 指引文档增强 | ✅ 已完成 | P2 |
| F-22-G7 | Analytics 遥测事件注入 | ✅ 已完成 | P2 |
| F-22-G8 | inFlight 防重复触发机制 | ✅ 已完成 | P2 |
| F-22-D1 | Cron 任务累计防护——CCB 4 层设计对照审查（~D4） 📋 设计完成 | 📋 规划中 | P? |
| F-60 | (已归档) | ✅ 已完成 | P? |
| F-61 | (已归档) | ✅ 已完成 | P? |
| F-62 | (已归档) | ✅ 已完成 | P? |
| F-63 | (已归档) | ✅ 已完成 | P? |
| F-64 | Voice Mode 语音输入 | ✅ 已完成 | P2 |
| F-65 | (已归档) | ✅ 已完成 | P? |
| F-66 | ACP 协议支持 | 📋 规划中 | P2 |
| F-67 | (已归档) | ✅ 已完成 | P? |
| F-81 | Native 原生模块系统（Python 可实现部分） | 📋 规划中 | P? |
| F-82 | Remote Control Server 远程控制服务 🔄 | 🔄 进行中 | P? |
| F-90 | Hermes Gateway 参考实现（OpenAI 兼容 API 服务器） | 📋 规划中 | P? |
| F-83 | (已归档) | ✅ 已完成 | P? |
| F-84 | (已归档) | ✅ 已完成 | P? |
| F-85 | (已归档) | ✅ 已完成 | P? |
| F-86 | (已归档) | ✅ 已完成 | P? |
| F-87 | Workflow Scripts 工作流脚本 ⛔ | ⛔ 已被取代 | P2 |
| F-88 | (已归档) | ✅ 已完成 | P? |
| F-68 | Feature Gate 运行时特性开关系统 | 📋 规划中 | P1 |
| F-69 | Budget / Poor Mode 资源节俭模式 | 🔄 进行中 | P1 |
| F-70 | Plugin 插件系统基础框架 | 📋 规划中 | P1 |
| F-71 | 内置工具补齐（缺失工具批量实现） | 📋 规划中 | P1 |
| F-72 | Multi-API 原生适配器扩展 | 📋 规划中 | P1 |
| F-73 | (已归档) | ✅ 已完成 | P? |
| F-74 | Sandbox / SSH Remote 沙箱远程执行 | 📋 规划中 | P2 |
