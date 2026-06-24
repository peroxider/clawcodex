# ClawCodex 特性规划目录

> 本目录是 ClawCodex **特性规划与进度**的唯一事实源。
> 融合自 `FEATURE_PLAN.md`、`PROGRESS.md`、`ARCHIVED_FEATURES.md`、`ARCHIVED_PROGRESS.md` 四份文档。
> 融合日期: 2026-06-24 | 参照: [MERGE_GUIDE.md](./MERGE_GUIDE.md)

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
└── 07-other/                          ← 其他散在特性
```

## F-Number 状态总表

> 状态标记: ✅ 已完成 | 🔄 进行中 | 📋 规划中 | 🔭 探索中

### Orchestrator 系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-54 | 运行期可观测性 | 🔄 | [f-54-observability.md](02-orchestrator/f-54-observability.md) |
| F-110 | 声明式工作流引擎 | 📋 | [f-110-workflow-engine.md](02-orchestrator/f-110-workflow-engine.md) |
| F-111 | StageRunner 适配器 | 📋 | [f-111-stage-runner.md](02-orchestrator/f-111-stage-runner.md) |
| F-112 | GATE 门禁处理器 | 📋 | [f-112-gate-processor.md](02-orchestrator/f-112-gate-processor.md) |
| F-113 | DECISION 决策处理器 | 📋 | [f-113-decision-processor.md](02-orchestrator/f-113-decision-processor.md) |
| F-114 | 阶段契约验证器 | 📋 | [f-114-contract-validator.md](02-orchestrator/f-114-contract-validator.md) |
| F-115 | 检查点与恢复 | 📋 | [f-115-checkpoint-recovery.md](02-orchestrator/f-115-checkpoint-recovery.md) |
| F-116 | 工作流可观测性集成 | 📋 | [f-116-workflow-observability.md](02-orchestrator/f-116-workflow-observability.md) |
| F-118 | 动态任务分解引擎 | 🔭 | [f-118-dynamic-decomposition.md](02-orchestrator/f-118-dynamic-decomposition.md) |

### Agent 核心能力

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-10 | ExecuteExtraTool 延迟工具系统 | 📋 | [f-10-extratool.md](07-other/f-10-extratool.md) |
| F-100 | Dreaming 后台记忆整合 | 🔄 | [f-100-dreaming.md](03-agent-core/f-100-dreaming.md) |
| F-102 | Agent Loop Hook 扩展点 | 🔄 | [f-102-hook-extensions.md](03-agent-core/f-102-hook-extensions.md) |
| F-107 | PowerShell 支持增强 | 📋 | [f-107-powershell.md](03-agent-core/f-107-powershell.md) |
| F-108 | Freeze Detection & Auto-Recovery | 📋 | [f-108-freeze-detection.md](03-agent-core/f-108-freeze-detection.md) |

### CLI 与配置系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-46 | permission_mode 正交拆分 | 🔄 | [f-46-permission-split.md](07-other/f-46-permission-split.md) |
| F-53 | Tool 自动暴露为 CLI 斜杠命令 | 📋 | [f-53-tool-to-cli.md](07-other/f-53-tool-to-cli.md) |
| F-89 | @agent-name 多入口统一支持 | 🔄 | [f-89-agent-name.md](07-other/f-89-agent-name.md) |

### Architecture & SDK 下沉

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-50 | SOP 转换器源码固化 (子特性 A-G) | 📋(部分) | [f-50-sop-converter.md](04-architecture-sdk/f-50-sop-converter.md) |
| F-52 | Python SDK 方法注册为 Tool | 📋 | [f-52-sdk-to-tool.md](04-architecture-sdk/f-52-sdk-to-tool.md) |

### Cron 系统

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-22 | Cron 系统执行引擎 | 🔄 | [f-22-cron-execution.md](05-cron-system/f-22-cron-execution.md) |

### CCB 对标

| F-Number | 名称 | 状态 | 章节路径 |
|----------|------|:----:|---------|
| F-64 | Voice Mode 语音输入 | 🔄 | [f-64-voice-mode.md](06-ccb-benchmark/f-64-voice-mode.md) |
| F-66 | ACP 协议支持 | 📋 | [f-66-acp-protocol.md](06-ccb-benchmark/f-66-acp-protocol.md) |
| F-68 | Feature Gate 开关系统 | 📋 | [f-68-feature-gate.md](06-ccb-benchmark/f-68-feature-gate.md) |
| F-69 | Budget/Poor Mode | 🔄 | [f-69-budget-mode.md](06-ccb-benchmark/f-69-budget-mode.md) |
| F-70 | Plugin 系统基础框架 | 🔄 | [f-70-plugin.md](06-ccb-benchmark/f-70-plugin.md) |
| F-71 | 内置工具补齐 | 🔄 | [f-71-tool-gap.md](06-ccb-benchmark/f-71-tool-gap.md) |
| F-72 | Multi-API 原生适配器 | 📋 | [f-72-multi-api.md](06-ccb-benchmark/f-72-multi-api.md) |
| F-73 | CI/CD 流水线 | 🔄 | [f-73-cicd.md](06-ccb-benchmark/f-73-cicd.md) |
| F-74 | Sandbox 沙箱远程执行 | 📋 | [f-74-sandbox.md](06-ccb-benchmark/f-74-sandbox.md) |
| F-81 | Native 原生模块系统 | 🔭 | [f-81-native-modules.md](06-ccb-benchmark/f-81-native-modules.md) |
| F-82 | Remote Control 远程控制 | 🔄 | [f-82-remote-control.md](06-ccb-benchmark/f-82-remote-control.md) |

## 变更历史

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并（MERGE_GUIDE Step 2） |
