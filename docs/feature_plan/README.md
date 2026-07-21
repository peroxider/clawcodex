# ClawCodex 特性规划目录

> 本目录是 ClawCodex **特性规划与进度**的唯一事实源。
> 融合自 `FEATURE_PLAN.md`、`PROGRESS.md`、`ARCHIVED_FEATURES.md`、`ARCHIVED_PROGRESS.md` 四份文档。
> 融合日期: 2026-06-24 | 参照: MERGE_GUIDE.md

## 目录结构

```
docs/feature_plan/
├── README.md                          ← 本文件：元信息 + F-Number 状态总表
├── 01-overview.md                     ← 项目概述与边界约束
├── 02-orchestrator/                   ← Orchestrator 系统
├── 03-agent-core/                     ← Agent 核心能力
├── 04-architecture-sdk/               ← Architecture & SDK 下沉
├── 05-cron-system/                    ← Cron 系统
├── 06-ccb-benchmark/                  ← CCB 对标
├── 07-cli-config/                    ← CLI 与配置系统
├── 08-recording/                     ← F-REC Asciicast v2 录制器
└── ../decoupling/                     ← 三层解耦方案与 P3 整改记录（独立规划）
```

## F-Number 状态总表

> 状态标记: ✅ 已完成 | 🔄 进行中 | 📋 规划中 | 🔭 探索中

### Orchestrator 系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-54 | 运行期可观测性 | 🔄 | [f-54-observability.md](02-orchestrator/f-54-observability.md) |
| F-110 | 声明式工作流引擎 | 🟡 | [f-110-workflow-engine.md](02-orchestrator/f-110-workflow-engine.md) |
| F-111 | StageRunner 适配器 | 🟡 | [f-111-stage-runner.md](02-orchestrator/f-111-stage-runner.md) |
| F-112 | GATE 门禁处理器 | 🟡 | [f-112-gate-processor.md](02-orchestrator/f-112-gate-processor.md) |
| F-113 | DECISION 决策处理器 | 🟡 | [f-113-decision-processor.md](02-orchestrator/f-113-decision-processor.md) |
| F-114 | 阶段契约验证器 | 🟡 | [f-114-contract-validator.md](02-orchestrator/f-114-contract-validator.md) |
| F-115 | 检查点与恢复 | 🟡 | [f-115-checkpoint-recovery.md](02-orchestrator/f-115-checkpoint-recovery.md) |
| F-116 | 工作流可观测性集成 | 🟡 | [f-116-workflow-observability.md](02-orchestrator/f-116-workflow-observability.md) |
| F-118 | 动态任务分解引擎 | 🟡 | [f-118-dynamic-decomposition.md](02-orchestrator/f-118-dynamic-decomposition.md) |
| F-121 | PR 代码检视意见规则回灌 | 📋 | [f-121-rules-feedback.md](02-orchestrator/f-121-rules-feedback.md) |
| F-124 | Issue 澄清器 — 描述不清晰自动检测与澄清闭环 | 🟡 | [f-124-issue-clarifier.md](02-orchestrator/f-124-issue-clarifier.md) |
| F-127 | PR CI 失败自动修复 — 从 CI 状态到 Agent 修复的闭环 | 📋 | [f-127-ci-auto-fix.md](02-orchestrator/f-127-ci-auto-fix.md) |
| F-128 | 定时全量代码审查 — 周期性代码扫描与自动化 Issue 归档 | 📋 | [f-128-periodic-code-review.md](02-orchestrator/f-128-periodic-code-review.md) |

### Agent 核心能力

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-10 | ExecuteExtraTool 延迟工具系统 | 📋 | [f-10-extratool.md](03-agent-core/f-10-extratool.md) |
| F-107 | PowerShell 支持增强 | 📋 | [f-107-powershell.md](03-agent-core/f-107-powershell.md) |
| F-119 | System Prompt 段落拼装与自迭代基础设施 | 📋 | [f-119-prompt-assembly.md](03-agent-core/f-119-prompt-assembly.md) |
| F-130 | 自校正上下文切换 — 元认知"换脑"机制 | 📋 | [f-130-self-correct-context-switch.md](03-agent-core/f-130-self-correct-context-switch.md) |

### CLI 与配置系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-46 | permission_mode 正交拆分 | 🔄 | [f-46-permission-split.md](07-cli-config/f-46-permission-split.md) |
| F-53 | Tool 自动暴露为 CLI 斜杠命令 | 📋 | [f-53-tool-to-cli.md](07-cli-config/f-53-tool-to-cli.md) |

### Architecture & SDK 下沉

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-50 | SOP 转换器源码固化 (子特性 A-G) | 🟡 | [f-50-sop-converter.md](04-architecture-sdk/f-50-sop-converter.md) |
| F-52 | Python SDK 方法注册为 Tool | 📋 | [f-52-sdk-to-tool.md](04-architecture-sdk/f-52-sdk-to-tool.md) |

### Cron 系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-22 | Cron 系统执行引擎 | 🔄 | [f-22-cron-execution.md](05-cron-system/f-22-cron-execution.md) |

### Recording / 可观测性增强

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-156 | Asciicast v2 录制器（orchestrator / query / SOP / visualizer / cron） | ✅ | [f-156-asciicast-recorder.md](08-recording/f-156-asciicast-recorder.md) |

### CCB 对标

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-64 | Voice Mode 语音输入 | 🔄 | [f-64-voice-mode.md](06-ccb-benchmark/f-64-voice-mode.md) |
| F-66 | ACP 协议支持 | 🚧 | [f-66-acp-protocol.md](06-ccb-benchmark/f-66-acp-protocol.md) |
| F-69 | Budget/Poor Mode | 🔄 | [f-69-budget-mode.md](06-ccb-benchmark/f-69-budget-mode.md) |
| F-72 | Multi-API 原生适配器 | 🔄 | [f-72-multi-api.md](06-ccb-benchmark/f-72-multi-api.md) |
| F-73 | CI/CD 流水线 | 🔄 | [f-73-cicd.md](06-ccb-benchmark/f-73-cicd.md) |
| F-74 | Sandbox 沙箱远程执行 | 📋 | [f-74-sandbox.md](06-ccb-benchmark/f-74-sandbox.md) |
| F-82 | Remote Control 远程控制 | 🔄 | [f-82-remote-control.md](06-ccb-benchmark/f-82-remote-control.md) |
| F-83 | 远程 Triggers（AGENT_TRIGGERS_REMOTE） | 📋 | [f-83-triggers.md](06-ccb-benchmark/f-83-triggers.md) |
| F-84 | Daemon 后台守护 | 🔄 | [f-84-daemon.md](06-ccb-benchmark/f-84-daemon.md) |
| F-85 | Pipe IPC 命令族（UDS + LAN_PIPES） | 📋 | [f-85-pipe-ipc.md](06-ccb-benchmark/f-85-pipe-ipc.md) |
| F-86 | Computer Use 跨平台 Executor | 📋 | [f-86-computer-use.md](06-ccb-benchmark/f-86-computer-use.md) |
| F-87 | /ultraplan LLM 驱动 + CLI 完整实现 | 🔄 | [f-87-ultraplan.md](06-ccb-benchmark/f-87-ultraplan.md) |
| F-88 | Monitor 后台监控 + MonitorTool | 📋 | [f-88-monitor.md](06-ccb-benchmark/f-88-monitor.md) |
| F-91 | MCP Skills 自动发现 | 📋 | [f-91-mcp-skill-discovery.md](06-ccb-benchmark/f-91-mcp-skill-discovery.md) |
| F-92 | experimental_skill_search TF-IDF | 📋 | [f-92-skill-search.md](06-ccb-benchmark/f-92-skill-search.md) |
| F-94 | BG_SESSIONS 后台会话 | 🚧 | [f-94-bg-sessions.md](06-ccb-benchmark/f-94-bg-sessions.md) |
| F-95 | TEMPLATES 模板系统 | 🔄 | [f-95-templates.md](06-ccb-benchmark/f-95-templates.md) |
| F-96 | PROMPT_CACHE_BREAK_DETECTION | 📋 | [f-96-cache-break-detection.md](06-ccb-benchmark/f-96-cache-break-detection.md) |
| F-98 | SSH_REMOTE 远程模式 | 📋 | [f-98-ssh-remote.md](06-ccb-benchmark/f-98-ssh-remote.md) |
| F-99 | DIRECT_CONNECT 直连模式 | 🔄 | [f-99-direct-connect.md](06-ccb-benchmark/f-99-direct-connect.md) |
| F-125 | Headless 无头模式多轮交互 + `--resume` 冲突分析 | 🚧 | [f-125-headless-multi-turn.md](06-ccb-benchmark/f-125-headless-multi-turn.md) |
| — | **CCB ↔ ClawCodex 缺口分析** | ✅ | [06-ccb-benchmark/README.md](06-ccb-benchmark/README.md) |

### Agent 元架构 / 动态上下文 (Brainstorm)

> 元架构脑暴规划，不申请 F-Number；落地时按子特性单独立项。详见 [dynamic-context-architecture.md](dynamic-context-architecture.md)。

| 编号 | 名称 | 组别 | 核心杠杆 | 落地门槛 | 章节路径 |
|:----:|------|------|:--------:|:--------:|---------|
| DC-001 | 上下文模式热切换 | 生命周期 | 🟡 | 中 | [dynamic-context-architecture.md §3.A](dynamic-context-architecture.md) |
| DC-002 | 上下文继承链 | 生命周期 | 🟡 | 中 | 同上 |
| DC-003 | JIT 上下文合成 | 生命周期 | 🔴🔴 | 低 | 同上 |
| DC-004 | 记忆分层 (W/E/S) | 生命周期 | 🟢 | 低-高 | 同上 |
| DC-005 | 置信度声明协议 | 抗幻觉 | 🔴🔴🔴 | 低 | 同上 |
| DC-006 | 工具强制验证 | 抗幻觉 | 🔴🔴 | 低-中 | 同上 |
| DC-007 | 自相矛盾检测 | 抗幻觉 | 🔴 | 中 | 同上 |
| DC-008 | 对抗质疑器 | 抗幻觉 | 🔴🔴 | 中 | 同上 |
| DC-009 | 否定式检索 | 抗幻觉 | 🔴🔴🔴 | 低 | 同上 |
| DC-010 | 多视角扇出 | 推理扩展 | 🔴🔴 | 中-高 | 同上 |
| DC-011 | 假设并行情景 | 推理扩展 | 🟡 | 中 | 同上 |
| DC-012 | 反事实推理 | 推理扩展 | 🔴 | 低 | 同上 |
| DC-013 | 类比迁移 | 推理扩展 | 🟡 | 中 | 同上 |
| DC-014 | 上下文即代码 (CaC) | 元架构 | 🟡 | 高 | 同上 |
| DC-015 | 上下文时序回放 | 元架构 | 🟡 | 中 | 同上 |
| DC-016 | 上下文市场 | 元架构 | 🟢 | 高 | 同上 |
| DC-017 | 认知模式混合 | 元架构 | 🟡 | 中 | 同上 |
| DC-018 | 涌现式上下文发现 | 元架构 | 🔴 | 低 | 同上 |
| DC-019 | 上下文压力测试 | 元架构 | 🟢 | 高 | 同上 |
| DC-020 | 边界追踪 | 元架构 | 🔴🔴🔴 | 低 | 同上 |

### 解耦方案（独立规划）

> 解耦方案不归入 F-Number 体系，作为独立目录存在。详见 [../decoupling/README.md](../decoupling/README.md)。

| 名称 | 状态 | 章节路径 |
|------|:----:|---------|
| 三层解耦方案 + P3 整改 | ✅ | [../decoupling/README.md](../decoupling/README.md) |

## 变更历史

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并（MERGE_GUIDE Step 2） |
| 2026-06-25 | 新增 F-119（System Prompt 段落拼装与自迭代基础设施） | 架构审计后规划段落级扩展点 + A/B 框架骨架 |
| 2026-06-29 | 新增 `../decoupling/` 解耦方案目录（P3 整改全量文档化） | P3 整改 6 步累计 67+ 迁移 imports / 8 新 facade 完工；解耦方案从 F-Number 体系中独立为目录 |
| 2026-07-01 | 新增 F-123 Intent Forecast 空闲意图预测规划 | 用户提出 REPL/TUI 2 分钟空闲后预测下一步、`/forecast` 与 CLI 同名、异步 session summary sidecar 的设计需求 |
| 2026-07-03 | 删除 F-70/F-71/F-81/F-122 已完成特性规划文档 | 代码确认特性已全部落地，移除已完成的规范文档 |
| 2026-07-04 | 删除 F-89/F-93/F-97/F-123 已完成特性规划文档;同步 master 状态 11 处(F-66 🚧、F-72/F-84/F-87 🔄、F-102 ✅、F-110-F-116 🟡、F-94 🚧);补登 F-125;新增 08-agent-dashboard 章节收录 F-120 | 全量复核 49 个 F-Number 文档 vs 代码层,识别 4 个 ✅ 完全实现特性 + 11 处文档/master 状态不一致 + 1 处遗漏章节 |
| 2026-07-07 | 删除 F-102 已完成特性规划文档(代码确认 P102-A~E 全部落地, 3 新建+9 修改文件, 稳定性门禁通过) | 代码确认特性已全部实现，移除已完成的规范文档 |
| 2026-07-07 | 删除 F-89 @agent-name 和 F-100 Dreaming 已完成特性规划文档 | 代码确认五入口统一 + Phase B 30min TTL 增强已全部落地；F-89 9 测试用例/F-100 109 单测+6 E2E 全绿 |
| 2026-07-10 | 删除 F-108 已完成特性规划文档 | F-108 P108-A~H 四层方案全部实现，单元测试与稳定性门禁通过，verification agent 复核 PASS |
| 2026-07-11 | 删除 F-120 已完成特性规划文档 | F-120 Agent Dashboard 全部 6 个 Phase 完成（124 tests，commit 3639db2b 补齐三个缺口），移除 08-agent-dashboard 章节与 F-120 表行；SOP source 接入点改由 `extensions/agent_dashboard/sources/sop_source.py` 顶部 docstring 记录 |
| 2026-07-13 | 新增 08-recording 章节与 F-156 Asciicast v2 录制器 | 5 子系统（orchestrator / query / SOP / visualizer / cron）零 src/ 改动落地，60 unit+integration 测试通过，稳定性门禁 Stages 1-5/7-9 全绿 |
| 2026-07-14 | 新增 F-130 自校正上下文切换 | 在 F-119 section registry 基础上规划元认知换脑机制；模板 + Agent 自定义的 Profile 系统；循环检测器框架；上下文切换引擎 + rollback；默认 4 个 Profile（default/debug/creative/review） |
| 2026-07-21 | 新增 dynamic-context-architecture.md (DC-001 ~ DC-020) | 用户提出"动态上下文切换/装配/生成"挑战性脑暴问题；沉淀 20 项原理特性规划，覆盖上下文生命周期 / 抗幻觉 / 推理扩展 / 元架构 4 组；定位为 brainstorm 文档，不申请 F-Number，落地时按子特性单独立项 |
