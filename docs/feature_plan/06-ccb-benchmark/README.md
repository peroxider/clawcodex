# 06 — CCB 对标缺口（Claude Code Best ↔ ClawCodex）

> 本目录追踪 ClawCodex 与上游对标项目 [`claude-code-best`](https://gitcode.com/chadwweng/claude-code-best)（CCB）之间的特性缺口与追赶计划。
>
> 最后更新: 2026-06-30

## 目录索引

| 文档 | 范围 | 状态 |
|------|------|:----:|
| [gap-analysis-2026q2.md](./gap-analysis-2026q2.md) | **Q2 缺口快照**：18 类 CCB 能力 + 65+ Feature Flag 对照,P0/P1/P2 缺口派工,解耦路径 | ✅ |
| [f-64-voice-mode.md](./f-64-voice-mode.md) | F-64 Voice Mode 语音输入 | 🔄 |
| [f-66-acp-protocol.md](./f-66-acp-protocol.md) | F-66 ACP 协议支持 | 📋 |
| [f-68-feature-gate.md](./f-68-feature-gate.md) | F-68 Feature Gate 开关系统 | ✅ |
| [f-69-budget-mode.md](./f-69-budget-mode.md) | F-69 Budget / Poor Mode 资源节俭 | 🔄 |
| [f-70-plugin.md](./f-70-plugin.md) | F-70 Plugin 插件系统基础框架 | ✅ |
| [f-71-tool-gap.md](./f-71-tool-gap.md) | F-71 内置工具补齐（SnipTool 等 12/15） | 🔄 |
| [f-72-multi-api.md](./f-72-multi-api.md) | F-72 Multi-API 原生适配器 | 📋 |
| [f-73-cicd.md](./f-73-cicd.md) | F-73 CI/CD 流水线 | 🔄 |
| [f-74-sandbox.md](./f-74-sandbox.md) | F-74 Sandbox 沙箱远程执行 | 📋 |
| [f-81-native-modules.md](./f-81-native-modules.md) | F-81 Native 原生模块系统 | 🔭 |
| [f-82-remote-control.md](./f-82-remote-control.md) | F-82 Remote Control 远程控制 | 🔄 |
| [f-84-daemon.md](./f-84-daemon.md) | F-84 Daemon 后台守护进程(Supervisor + Worker) | 📋 |
| [f-85-pipe-ipc.md](./f-85-pipe-ipc.md) | F-85 Pipe IPC 多实例协作（UDS + LAN_PIPES） | 📋 |
| [f-88-monitor.md](./f-88-monitor.md) | F-88 Monitor 后台监控 + MonitorTool | 📋 |
| [f-89-proactive.md](./f-89-proactive.md) | F-89 Proactive 自主模式 + KAIROS Tick 集成 | 📋 |
| [f-125-headless-multi-turn.md](./f-125-headless-multi-turn.md) | **F-125**: Headless 无头模式多轮交互 + `--resume` 冲突分析 | 📋 |

## 当前 P0 缺口一览（来自 gap-analysis §3.1）

| F-Number | 名称 | 解耦路径 |
|----------|------|----------|
| **F-84** | Daemon 后台守护 | `extensions/daemon/` (全新子系统) |
| **F-85** | Pipe IPC 命令族（UDS + LAN_PIPES） | `clawcodex_ext/services/pipe_ipc/`（已有原语）+ `extensions/pipe_ipc/`（LAN） |
| **F-88** | Monitor 后台监控 + MonitorTool | `clawcodex_ext/services/monitor/` + `clawcodex_ext/tool_system/tools/monitor.py` |
| **F-89** | Proactive 自主模式 + KAIROS Tick 集成 | `clawcodex_ext/services/proactive/` + `clawcodex_ext/tool_system/tools/sleep.py` |

完整对照表、派工顺序与解耦原则详见 [gap-analysis-2026q2.md](./gap-analysis-2026q2.md)。

## 阅读建议

- **了解整体缺口**：直接读 [gap-analysis-2026q2.md](./gap-analysis-2026q2.md) §2 全特性对照矩阵 + §3 关键缺口详解
- **认领 P0/P1 任务**：在 gap-analysis §5 路线图中找到对应 F-Number,跳转到 §3.1 / §3.2 子节查看解耦路径
- **理解解耦规范**：见 gap-analysis §4 + 项目根 [CLAUDE.md](../../../CLAUDE.md)「二次开发解耦原则」