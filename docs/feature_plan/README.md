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
├── 11-capability-harness/              ← 能力感知 Harness 自适应
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
| F-124 | Issue 澄清器 — 描述不清晰自动检测与澄清闭环 | ✅ 已落地 | *特性文档已归档* |
| F-127 | PR CI 失败自动修复 — 从 CI 状态到 Agent 修复的闭环 | 📋 | [f-127-ci-auto-fix.md](02-orchestrator/f-127-ci-auto-fix.md) |
| F-128 | 定时全量代码审查 — 周期性代码扫描与自动化 Issue 归档 | 📋 | [f-128-periodic-code-review.md](02-orchestrator/f-128-periodic-code-review.md) |

### Agent 核心能力

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-10 | ExecuteExtraTool 延迟工具系统 | 📋 | [f-10-extratool.md](03-agent-core/f-10-extratool.md) |
| F-107 | PowerShell 支持增强 | 📋 | [f-107-powershell.md](03-agent-core/f-107-powershell.md) |
| F-130 | 自校正上下文切换 — 元认知"换脑"机制 | 📋 | [f-130-self-correct-context-switch.md](03-agent-core/f-130-self-correct-context-switch.md) |
| F-158 | 抗幻觉基线协议 — 置信度 / 否定检索 / 边界追踪 | 📋 | [f-158-anti-hallucination-baseline.md](03-agent-core/f-158-anti-hallucination-baseline.md) |
| F-159 | JIT 上下文合成 — 按需生成切断"假装知道"幻觉源头 | 📋 | [f-159-jit-context-synthesis.md](03-agent-core/f-159-jit-context-synthesis.md) |
| F-160 | 反事实推理 — 强制"如果我错了，最可能错在哪"显式化 | 📋 | [f-160-counterfactual-reasoning.md](03-agent-core/f-160-counterfactual-reasoning.md) |
| F-161 | 涌现式上下文发现 — Agent 主动反思"我可能需要 X"显式化 | 📋 | [f-161-emergent-context-discovery.md](03-agent-core/f-161-emergent-context-discovery.md) |
| F-162 | 工具强制验证 — 关键事实（API / 版本 / 库 / 路径）必须经工具验证的硬拦截 | 📋 | [f-162-tool-mandatory-verification.md](03-agent-core/f-162-tool-mandatory-verification.md) |
| F-163 | 对抗质疑器 — Red-Team Critic 1v1 纵深对抗 (Proposer↔Critic 多轮迭代) | 📋 | [f-163-red-team-critic.md](03-agent-core/f-163-red-team-critic.md) |
| F-164 | 多视角扇出 — 5 个默认视角 (资深工程师/安全/新人/性能/维护者) 并行推理 + 综合 | 📋 | [f-164-multi-perspective-fan-out.md](03-agent-core/f-164-multi-perspective-fan-out.md) |
| F-165 | 矛盾检测独立版 — 三维语义矛盾检测（vs VERIFIED / intra-reply / vs history）+ 自动修订 | 📋 | [f-165-self-contradiction-detector.md](03-agent-core/f-165-self-contradiction-detector.md) |
| F-166 | 记忆分层 W/E — Working（进程内 LRU + GC）+ Episodic（NDJSON 跨会话）+ Provenance 追溯 + 5 Profile 写读策略 | 📋 | [f-166-memory-layering-we.md](03-agent-core/f-166-memory-layering-we.md) |
| F-175 | 类比迁移 — 基于 Episodic Memory 的结构映射与反例校验 | 📋 | [f-175-analogical-transfer.md](03-agent-core/f-175-analogical-transfer.md) |
| F-176 | 假设并行情景 — 多假设并行验证与证据收敛 | 📋 | [f-176-parallel-hypothetical-scenarios.md](03-agent-core/f-176-parallel-hypothetical-scenarios.md) |
| F-177 | 上下文时序回放 — Context Snapshot、diff 与分支探索 | 📋 | [f-177-context-time-travel.md](03-agent-core/f-177-context-time-travel.md) |
| F-178 | 认知模式混合 — 可解释的推理风格权重编排 | 📋 | [f-178-cognitive-mode-blending.md](03-agent-core/f-178-cognitive-mode-blending.md) |

### 能力感知 Harness 自适应

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-174 | 能力感知 Harness 自适应（P174-A~P174-I） | 📋 | [11-capability-harness/README.md](11-capability-harness/README.md) |

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
| F-55 | Tool 生命周期依赖与资源类型契约 | ✅ 已落地 | *特性文档已归档* |
| F-56 | SOP Resource Catalog | ✅ 已落地 | *特性文档已归档* |
| F-57 | SOP 可执行组合工作流 | 🔧 | [f-57-sop-executable-composite-workflows.md](04-architecture-sdk/f-57-sop-executable-composite-workflows.md) |
| F-58 | SOP Resource Contract Schema | 📋 | [f-58-sop-resource-contract-schema.md](04-architecture-sdk/f-58-sop-resource-contract-schema.md) |
| F-59 | SOP Runtime Guards & Recovery | 📋 | [f-59-sop-runtime-guards-recovery.md](04-architecture-sdk/f-59-sop-runtime-guards-recovery.md) |
| F-60 | SOP E2E Evaluation & Observability | 📋 | [f-60-sop-e2e-evaluation-observability.md](04-architecture-sdk/f-60-sop-e2e-evaluation-observability.md) |
| F-157 | ToolSearch 宏工具 / 原子工具分层检索 | 🔧 | [f-157-toolsearch-layered-macro-retrieval.md](04-architecture-sdk/f-157-toolsearch-layered-macro-retrieval.md) |

### Cron 系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-22 | Cron 系统执行引擎 | ✅ 已落地 | *特性文档已归档* |

### Recording / 可观测性增强

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-156 | Asciicast v2 录制器（orchestrator / query / SOP / visualizer / cron） | ✅ 已落地 | *特性文档已归档* |
| F-167 | Visualizer 独立包化（商业化脱离） | ✅ 已落地 | [f-167-visualizer-package-extract.md](04-architecture-sdk/f-167-visualizer-package-extract.md) |
| F-179 | 上下文即代码（CaC）— 声明式 Context Pack 与校验 CLI | 📋 | [f-179-context-as-code.md](04-architecture-sdk/f-179-context-as-code.md) |
| F-180 | 上下文市场 — Context Pack 的本地/远程分发与签名 | 📋 | [f-180-context-marketplace.md](04-architecture-sdk/f-180-context-marketplace.md) |
| F-181 | 上下文压力测试 — Context Pack 上线前的对抗性质量门禁 | 📋 | [f-181-context-stress-test.md](04-architecture-sdk/f-181-context-stress-test.md) |

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
| F-83 | 远程 Triggers（AGENT_TRIGGERS_REMOTE） | 🟡 | [f-83-triggers.md](06-ccb-benchmark/f-83-triggers.md) |
| F-84 | Daemon 后台守护 | ✅ 已落地 | *特性文档已归档* |
| F-85 | Pipe IPC 命令族（UDS + LAN_PIPES） | 🟡 | [f-85-pipe-ipc.md](06-ccb-benchmark/f-85-pipe-ipc.md) |
| F-86 | Computer Use 跨平台 Executor | 🟡 | [f-86-computer-use.md](06-ccb-benchmark/f-86-computer-use.md) |
| F-87 | /ultraplan LLM 驱动 + CLI 完整实现 | ✅ 已落地 | *特性文档已归档* |
| F-88 | Monitor 后台监控 + MonitorTool | ✅ 已落地 | *特性文档已归档* |
| F-91 | MCP Skills 自动发现 | 📋 | [f-91-mcp-skill-discovery.md](06-ccb-benchmark/f-91-mcp-skill-discovery.md) |
| F-92 | experimental_skill_search TF-IDF | ✅ 已落地 | *特性文档已归档* |
| F-94 | BG_SESSIONS 后台会话 | 🚧 | [f-94-bg-sessions.md](06-ccb-benchmark/f-94-bg-sessions.md) |
| F-95 | TEMPLATES 模板系统 | ✅ 已落地 | *特性文档已归档* |
| F-96 | PROMPT_CACHE_BREAK_DETECTION | 📋 | [f-96-cache-break-detection.md](06-ccb-benchmark/f-96-cache-break-detection.md) |
| F-98 | SSH_REMOTE 远程模式 | 📋 | [f-98-ssh-remote.md](06-ccb-benchmark/f-98-ssh-remote.md) |
| F-99 | DIRECT_CONNECT 直连模式 | 🔄 | [f-99-direct-connect.md](06-ccb-benchmark/f-99-direct-connect.md) |
| F-125 | Headless 无头模式多轮交互 + `--resume` 冲突分析 | 🚧 | [f-125-headless-multi-turn.md](06-ccb-benchmark/f-125-headless-multi-turn.md) |
| — | **CCB ↔ ClawCodex 缺口分析** | ✅ 已落地 | *特性文档已归档* |

### Agent 元架构 / 动态上下文 (Brainstorm)

> 动态上下文的跨特性决策、映射与实施顺序见 [dynamic-context-index.md](dynamic-context-index.md)；20 项 DC-NN 已收敛为 16 个 F-N 文档（F-158~F-166、F-175~F-181；F-167、F-168 与 F-174 已被其他特性占用）。

| 编号 | 名称 | 组别 | 核心杠杆 | 落地门槛 | 章节路径 |
|:----:|------|------|:--------:|:--------:|---------|
| DC-001 | 上下文模式热切换 | 生命周期 | 🟡 | 中 | [dynamic-context-index.md](dynamic-context-index.md) |
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
| 2026-07-18 | 新增 F-157 ToolSearch 宏/原子分层检索，并回写 F-56/F-57 边界 | 自然语言验收显示 phrase-only route 不能稳定阻止 SDK 原子工具抢占；新增 `intent_key`、`covered_tools`、RetrievalPlan、exclusive suppression 与执行前回滚设计 |
| 2026-07-21 | 新增动态上下文架构规划 (DC-001 ~ DC-020) | 用户提出"动态上下文切换/装配/生成"挑战性脑暴问题；沉淀 20 项原理特性规划，覆盖上下文生命周期 / 抗幻觉 / 推理扩展 / 元架构 4 组；定位为 brainstorm 文档，不申请 F-Number，落地时按子特性单独立项 |
| 2026-07-22 | 新增 DC → F-N 映射表 | 把 20 项 DC-NN 收敛为 16 个 F-N 文档（F-158 ~ F-173，F-N 编号接续 F-157 ToolSearch），按 Wave 1（P0 立竿见影）/ Wave 2（P1 工具化）/ Wave 3（P2/P3 元架构）三波落地；DC-001 / DC-002 / DC-007-部分 保留在 F-130 不单独立项 |
| 2026-07-31 | 解决 DC-A F-Number 冲突并补齐 Wave 3 文档 | F-167（Visualizer）、F-168（被动累积）与 F-174（能力感知 Harness）保留原归属；DC-A 的 7 个 Wave 3 特性重编号为 F-175~F-181，新增 7 份对应规划文档，并同步 DC→F-N 映射、总表与交叉引用 |
| 2026-07-22 | 新增 F-158 抗幻觉基线协议（覆盖 DC-005 / DC-009 / DC-020） | DC-A §4.4 映射表基础上落地 Wave 1 P0 高杠杆特性；置信度声明协议 + 否定式检索 + 边界追踪三层防御抑制幻觉；解耦落地于 `extensions/anti_hallucination/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-159 JIT 上下文合成（覆盖 DC-003） | DC-A §4.4 映射表基础上落地 Wave 1 P0 上下文生命周期特性；Intent 解析 + Loader 集合 + 缓存 + register_section 注入 + 触发限流；与 F-130（占位符填充）/ F-158-A（VERIFIED source）/ F-161（执行层）强协同；解耦落地于 `extensions/jit_context/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-160 反事实推理（覆盖 DC-012） | DC-A §4.4 映射表基础上落地 Wave 1 P0 推理扩展轻量级特性；门槛最低（仅 prompt + 1 Hook）；3 类模板（决策 / 断言 / 推荐）+ 6 档 verdict 标注 + 自检 Hook；与 F-119 / F-102 / F-158-A / F-130 / F-163 协同；解耦落地于 `extensions/counterfactual/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-161 涌现式上下文发现（覆盖 DC-018） | DC-A §4.4 映射表基础上落地 Wave 1 P0 元架构层特性（Wave 1 最后一个落地）；是 F-159 JIT 的隐式反思调度前置（meta-cognition 显式化）；反思 prompt + 4 档门控决策 + 反思缓存 + 调用 F-159 synthesize；与 F-119 / F-102 / F-159 / F-158 / F-160 / F-130 协同；解耦落地于 `extensions/emergent/`，零 `src/` 侵入 |
| 2026-07-23 | 新增 F-167 Visualizer 独立包化（商业化脱离） | 基于 `COMMERCIALIZATION_EXECUTIVE_SUMMARY.md` §4.2.2「低成本脱离」评估；实测 visualizer 22/25 文件零二层依赖，仅 3 文件有弱耦合（Protocol/dataclass/14 行函数）；方案为 Protocol 内联 + recording 适配器归位 + entry-points 入口；工作量 ~1125 行，单人 ~1 工作日落地 |
| 2026-07-23 | F-167-A~G 全部落地（visualizer 独立包化完成） | F-167-A/B：DashboardEntry/Source/Sink + AsciicastCapture/Event/Header Protocol 内联到 `extensions/visualizer/protocols/`；F-167-C：`panel()` 从 `recording.renderers` 迁到 `extensions/visualizer/_rendering.py`（私有）；F-167-D：`asciicast_dashboard_source.py` 从 `extensions/visualizer/` 迁到 `extensions/recording/visualizer_dashboard_source.py`，反向依赖 visualizer.protocols 和 _rendering.panel；F-167-E：`extensions/visualizer/pyproject.toml` 标注独立包元数据 + `clawcodex.commands` entry-points；F-167-F/G：`cli.py` 改为 self-contained `register_viz_subcommand`，`subcommand_registry.load_builtin_subcommands` 改为 try-import 包裹 viz 注册。验证：visualizer 测试 188 通过、recording 测试 136 通过、orchestrator 单元测试 1610 通过、稳定性门禁 482 全绿，**F-167 零回归** |
| 2026-07-22 | 移除 README.md F-Number 状态总表中 F-119 行 | F-119 已标记为 ✅ 已完成（ROADMAP v4.7 已从路线图移除），但 README.md 仍引用不存在的 `f-119-prompt-assembly.md`；按 ROADMAP 精简口径移除该行；01-overview.md 行 53 同步改为"F-119 已完成，详见 ROADMAP"；代码层 `extensions/prompt_lab/` 目录保留（属已完成特性的实现） |
| 2026-07-22 | 新增 F-162 工具强制验证（覆盖 DC-006） | DC-A §4.4 映射表基础上落地 Wave 2 P1 工具化组首个特性；是 F-158 软警告的硬约束升级（双层防御：F-158 标注 + F-162 拦截）；6 类规则（API 签名 / 版本号 / import / 库存在 / 路径 / 配置项）+ 三档拦截模式（warn / block / strict）+ 5 维例外判定 + JIT 联动自动抓取 + Profile 映射；与 F-119 / F-102 / F-158 / F-159 / F-130 / F-163 协同；解耦落地于 `extensions/tool_verification/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-163 对抗质疑器（覆盖 DC-008） | DC-A §4.4 映射表基础上落地 Wave 2 P1 工具化组第二个特性；是 Wave 2 P1 的"方案层"对抗（区别于 F-162 "事实层"硬拦截）；Proposer / Critic / Synthesizer 三角色 + 多轮迭代循环（max 3 轮 + fingerprint 去重早停）+ 结构化质疑输出（claim / counter_evidence / severity / category）+ 5 Profile 触发策略（default / review / strict / debug / creative）+ 与 F-162 audit log schema 兼容；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-164 协同；解耦落地于 `extensions/red_team_critic/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-164 多视角扇出（覆盖 DC-010） | DC-A §4.4 映射表基础上落地 Wave 2 P1 工具化组第三个特性；是 Wave 2 P1 的"决策层"多视角对照（区别于 F-162 "事实层"硬拦截 / F-163 "方案层"纵深对抗）；5 个默认 Perspective Persona（senior-engineer / security-reviewer / newcomer / perf-optimizer / maintainer）+ asyncio.gather 并行扇出 + Synthesizer 二阶段综合（启发式聚类 + LLM 兜底）+ 5 Profile 触发策略（default / review / strict / debug / creative）+ 动态注册 Protocol；与 F-118 / F-119 / F-102 / F-162 / F-130 / F-163 协同；解耦落地于 `extensions/multi_perspective/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-165 矛盾检测独立版（覆盖 DC-007 完整版） | DC-A §4.4 映射表基础上落地 Wave 2 P1 工具化组第四个特性；F-130 P130-A 仅覆盖工具重复维度，F-165 扩展到三维语义矛盾检测：vs VERIFIED（消费 F-158 Working Memory）/ intra-reply（同一回复前后断言）/ vs history（前几轮对话断言）；三档修订阈值（auto_rewrite / flag / ask_user）+ 修订循环（max_rewrite_attempts=1 + detect_after_rewrite + fail_open_on_detector_error）+ F130Coordinator 信号路由（正交不重叠）+ 5 Profile 触发策略（default / review / strict / debug / creative）+ 长度门控（min/max_reply_length）+ 与 F-163 counter_evidence 字段协同；与 F-130 P130-A / F-158 / F-119 / F-102 / F-163 / F-164 协同；解耦落地于 `extensions/contradiction_detector/`，零 `src/` 侵入 |
| 2026-07-22 | 新增 F-166 记忆分层 W/E（覆盖 DC-004 Working + Episodic） | DC-A §4.4 映射表基础上落地 Wave 2 P1 工具化组第五个特性（**Wave 2 P1 收官**）；DC-004 完整版含 Semantic + Procedural 4 层，Wave 2 P1 范围仅 Working + Episodic 两层先落地（Semantic + Procedural 留 Wave 3 / F-168+）；Working Memory（进程内 OrderedDict + LRU 淘汰 + TTL 自动 GC + RLock 线程安全）+ Episodic Memory（NDJSON 追加 + session_id 隔离 + tags 检索 + max_file_size_mb 自动轮转 + JSON 损坏行容忍）+ Provenance 追溯（source_tool / source_turn / source_user_input / source_file / source_url / source_timestamp）+ 写入/读取策略（5 Profile 映射：default/strict/review/debug/creative）+ LifecycleManager（周期 GC + 容量上限 + Episodic 按 age_days GC）+ F-158 VERIFIED markers 作为 `MemoryEntry(type=VERIFIED_FACT)` 视图（**不重复存储**）；与 F-119 / F-102 / F-158 / F-130 / F-159 协同；解耦落地于 `extensions/memory_layers/`，零 `src/` 侵入 |
| 2026-07-21 | 更新 CCB 对标章节:F-84/F-87/F-88/F-92/F-95 标记为 ✅,F-94 保持 🚧 | 代码确认 5 个特性完全落地,同步 `06-ccb-benchmark/README.md` §A 缺口矩阵与单篇文档状态 |
| 2026-07-28 | 新增 F-174「能力感知 Harness 自适应」独立章节 | 将能力感知 harness 设计、调研、资产与 F-174/P174-A~I 子特性统一归档至 `11-capability-harness/`，并完成原 `docs/capability/` 路径迁移 |
