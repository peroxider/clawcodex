# 06 — CCB 对标缺口（Claude Code Best ↔ ClawCodex）

> 本目录追踪 ClawCodex 与上游对标项目 [`claude-code-best`](https://gitcode.com/chadwweng/claude-code-best)（CCB）之间的特性缺口与追赶计划。
>
> 对标基线: CCB `v2.2.x`（PR #60–#241 累计恢复 13 类特性 + 65+ feature flag）
> 实现基线: `clawcodex_dev` `2026-06-30`
> 解耦原则: 三层架构 `src/` → `clawcodex_ext/` → `extensions/`；所有 P0/P1 缺口实现优先落入 `clawcodex_ext/` 或 `extensions/`
> 最后更新: 2026-07-01
>
> 注: 原 `gap-analysis-2026q2.md` 已分解——各 F-NN 派工条目下沉到对应 `f-NN-*.md` 的 **§0 缺口摘要**;全局对照矩阵与路线图合并到本 README（下方 §A/§B/§C）。

## 目录索引

| 文档 | 范围 | 状态 |
|------|------|:----:|
| [f-64-voice-mode.md](./f-64-voice-mode.md) | F-64 Voice Mode 语音输入 | 🔄 |
| [f-66-acp-protocol.md](./f-66-acp-protocol.md) | F-66 ACP 协议支持 | 📋 |
| [f-69-budget-mode.md](./f-69-budget-mode.md) | F-69 Budget / Poor Mode 资源节俭 | 🔄 |
| [f-70-plugin.md](./f-70-plugin.md) | F-70 Plugin 插件系统基础框架 | 🔄 |
| [f-71-tool-gap.md](./f-71-tool-gap.md) | F-71 内置工具补齐（SnipTool 等 12/15） | 🔄 |
| [f-72-multi-api.md](./f-72-multi-api.md) | F-72 Multi-API 原生适配器 | 📋 |
| [f-73-cicd.md](./f-73-cicd.md) | F-73 CI/CD 流水线 | 🔄 |
| [f-74-sandbox.md](./f-74-sandbox.md) | F-74 Sandbox 沙箱远程执行 | 📋 |
| [f-81-native-modules.md](./f-81-native-modules.md) | F-81 Native 原生模块系统 | 🔭 |
| [f-82-remote-control.md](./f-82-remote-control.md) | F-82 Remote Control 远程控制 | 🔄 |
| [f-83-triggers.md](./f-83-triggers.md) | F-83 Triggers 触发器 + cron 调度 | 📋 |
| [f-84-daemon.md](./f-84-daemon.md) | F-84 Daemon 后台守护进程(Supervisor + Worker) | 📋 |
| [f-85-pipe-ipc.md](./f-85-pipe-ipc.md) | F-85 Pipe IPC 多实例协作（UDS + LAN_PIPES） | 📋 |
| [f-86-computer-use.md](./f-86-computer-use.md) | F-86 Computer Use 三平台 | 📋 |
| [f-87-ultraplan.md](./f-87-ultraplan.md) | F-87 Ultraplan 工作流计划层 | 📋 |
| [f-88-monitor.md](./f-88-monitor.md) | F-88 Monitor 后台监控 + MonitorTool | 📋 |
| [f-89-proactive.md](./f-89-proactive.md) | F-89 Proactive 自主模式 + KAIROS Tick 集成 | ✅ |
| [f-91-mcp-skill-discovery.md](./f-91-mcp-skill-discovery.md) | F-91 MCP Skills 自动发现 | 📋 |
| [f-92-skill-search.md](./f-92-skill-search.md) | F-92 Skill Search TF-IDF 检索 | 📋 |
| [f-93-team-memory.md](./f-93-team-memory.md) | F-93 TeamMem 团队共享记忆 | 📋 |
| [f-94-bg-sessions.md](./f-94-bg-sessions.md) | F-94 BG_SESSIONS 后台会话统一管理 | 📋 |
| [f-95-templates.md](./f-95-templates.md) | F-95 TEMPLATES 模板系统产品化 | 🔄 |
| [f-96-cache-break-detection.md](./f-96-cache-break-detection.md) | F-96 PROMPT_CACHE_BREAK_DETECTION 缓存命中率监测 | 📋 |
| [f-97-lodestone.md](./f-97-lodestone.md) | F-97 LODESTONE 深度链接 | 📋 |
| [f-98-ssh-remote.md](./f-98-ssh-remote.md) | F-98 SSH_REMOTE 远程模式（协同 F-74） | 📋 |
| [f-99-direct-connect.md](./f-99-direct-connect.md) | F-99 DIRECT_CONNECT 直连模式 | 🔄 |
| [f-125-headless-multi-turn.md](./f-125-headless-multi-turn.md) | **F-125**: Headless 无头模式多轮交互 + `--resume` 冲突分析 | 📋 |

## 阅读建议

- **认领某个 F-NN**：直接打开对应 `f-NN-*.md`,先读 **§0 缺口摘要**(缺口描述 / 对标 / 解耦落地路径 / 依赖 / 估算工时),再读 §1 详细设计;
- **了解整体缺口**：读本 README §A 全特性对照矩阵;
- **看排期**：读本 README §B 路线图;
- **理解解耦规范**：读项目根 [CLAUDE.md](../../../CLAUDE.md)「二次开发解耦原则」+ 本 README §C。

---

## §A 全特性对照矩阵

> 状态约定:✅ 已落地(端到端可用) / 🟡 原语层(缺命令、UI 或集成) / 🟠 部分落地(关键路径可用,边界缺失) / ❌ 缺失。

### A.1 CCB 18 类核心能力

| # | CCB 能力 | ClawCodex 现状 | 缺口等级 | 对应 F-Number |
|:-:|----------|:--------------:|:--------:|---------------|
| 1 | Buddy 伴侣系统 | ✅ `src/buddy/` + `clawcodex_ext/buddy/` | 已完成 | — |
| 2 | Remote Control（远程控制） | 🟠 `extensions/remote_api/` Hermes API 已落地;Web UI / Worker 调度缺失 | P1 | [F-82](./f-82-remote-control.md) |
| 3 | /triggers 远程定时任务 | 🟡 仅本地 cron;无远程 trigger API | P1 | [F-83](./f-83-triggers.md) |
| 4 | Voice Mode 语音模式 | 🟡 仅检测/STT 抽象;缺 ASR 运行时集成 | P0 | [F-64](./f-64-voice-mode.md) |
| 5 | Chrome 浏览器控制 | ✅ `clawcodex_ext/services/chrome/`（三后端） | 已完成 | F-62 |
| 6 | Computer Use 屏幕操控 | 🟠 仅 `linux.py` / `null.py`;macOS+Windows 后端缺 | P1 | [F-86](./f-86-computer-use.md) |
| 7 | Feature Flags / GrowthBook | ✅ F-68（114 测试，clawcodex_ext/feature_gate/） | 已完成 | — |
| 8 | /ultraplan 高级规划 | 🟡 数据模型+executor;缺 LLM 生成 + CLI | P1 | [F-87](./f-87-ultraplan.md) |
| 9 | Daemon 后台守护 | ❌ `src/entrypoints/daemon.py` 占位 stub | P0 | [F-84](./f-84-daemon.md) |
| 10 | Pipe IPC 多实例协作 | 🟡 仅 UDS 传输+registry;无命令族 | P0 | [F-85](./f-85-pipe-ipc.md) |
| 11 | LAN Pipes 局域网群控 | ❌ 无 TCP/UDP multicast 发现 | P0 | [F-85](./f-85-pipe-ipc.md)（F-85.2） |
| 12 | Monitor 后台监控 | ❌ 无 `MonitorTool` | P0 | [F-88](./f-88-monitor.md) |
| 13 | Workflow 工作流脚本 | 🟠 `.claude/workflows/*.py` + `/workflows` 面板 | 已完成 | F-110 协同 |
| 14 | Coordinator 多Worker协调 | ✅ `src/coordinator/` + ext | 已完成 | — |
| 15 | Proactive 自主模式 | ✅ PROACTIVE/KAIROS Tick 调度 + SleepTool + Remote automation_state | 已完成 | [F-89](./f-89-proactive.md) |
| 16 | History / Snip 历史管理 | ✅ F-71 P71-O `snip.py` | 已完成 | [F-71](./f-71-tool-gap.md) |
| 17 | Fork 子Agent | ✅ `fork_subagent.py` | 已完成 | — |
| 18 | 其他恢复的工具 | 🟠 F-71 12/15;WebBrowser/Execute/RemoteTrigger 待补 | P1 | [F-71](./f-71-tool-gap.md) |

### A.2 附加 Feature Flag（CCB 附录派生,缺失/新增项）

| CCB Feature Flag | 现状 | 缺口 | F-Number |
|------------------|:----:|:----:|----------|
| `ACP`（Agent Client Protocol） | ❌ | P1 | [F-66](./f-66-acp-protocol.md) |
| `MCP_SKILLS`（skill:// 自动发现） | ❌ | P2 | [F-91](./f-91-mcp-skill-discovery.md) |
| `EXPERIMENTAL_SKILL_SEARCH`（TF-IDF） | ❌ | P2 | [F-92](./f-92-skill-search.md) |
| `TEAMMEM`（Team 共享记忆） | ❌ | P2 | [F-93](./f-93-team-memory.md) |
| `BG_SESSIONS`（后台会话） | 🟡 部分（`clawcodex_ext/tasks/`） | P2 | [F-94](./f-94-bg-sessions.md) |
| `TEMPLATES`（模板系统） | 🟡 `services/templates/` + orchestrator | P2 | [F-95](./f-95-templates.md) |
| `PROMPT_CACHE_BREAK_DETECTION` | 🟡 usage 采集已具备 | P2 | [F-96](./f-96-cache-break-detection.md) |
| `LODESTONE`（深度链接） | ❌ | P2 | [F-97](./f-97-lodestone.md) |
| `SSH_REMOTE`（SSH 远程模式） | ❌ | P2 | [F-98](./f-98-ssh-remote.md)（协同 F-74） |
| `DIRECT_CONNECT`（直连模式） | 🟡 `src/server/` 已部分 | P2 | [F-99](./f-99-direct-connect.md) |
| `AGENT_TRIGGERS_REMOTE`（远程 trigger） | ❌ | P1 | [F-83](./f-83-triggers.md) 协同 |
| `TOKEN_BUDGET`（Token 预算） | ✅ F-69 | 已完成 | [F-69](./f-69-budget-mode.md) |
| `KAIROS`（Tick 调度） | ✅ `kairos/scheduler.py` + proactive emitter | 已完成 | [F-89](./f-89-proactive.md) |
| `PROACTIVE`（主动模式） | ✅ `/proactive` + tick prompt + SleepTool + automation_state | 已完成 | [F-89](./f-89-proactive.md) |
| `MONITOR_TOOL`（后台监控） | ❌ | P0 | [F-88](./f-88-monitor.md) |
| `UDS_INBOX` / `LAN_PIPES`（Pipe IPC） | 🟡/❌ | P0 | [F-85](./f-85-pipe-ipc.md) |
| `DAEMON`（后台守护） | ❌ | P0 | [F-84](./f-84-daemon.md) |
| `CONTEXT_COLLAPSE` / `AWAY_SUMMARY` | ✅ | 已完成 | — |
| `SKILL_LEARNING` / `REVIEW_ARTIFACT` / `CONNECTOR_TEXT` | ❌ | P3 | 长期 |
| `ULTRATHINK`（扩展思考） | 🟡 `thinking.py`（stub） | P2 | 完善 |

---

## §B 路线图

### B.1 短期（2026 Q3,8 周内 — P0）

| 优先级 | F-Number | 名称 | 周期 | 累计 |
|:------:|----------|------|:----:|:----:|
| P0 | [F-85](./f-85-pipe-ipc.md) | Pipe IPC 命令族(UDS) | 2 周 | 2 周 |
| P0 | [F-88](./f-88-monitor.md) | Monitor Tool | 1.5 周 | 3.5 周 |
| P0 | [F-84](./f-84-daemon.md) | Daemon Supervisor | 3 周 | 6.5 周 |
| 已完成 | [F-89](./f-89-proactive.md) | Proactive 模式 | 2026-07-03 完成 | 6.5 周 |
| P0 | [F-85](./f-85-pipe-ipc.md) | LAN Pipes（F-85.2） | 2 周 | 11.5 周 |

> 注: F-85 先做 UDS 命令族,再做 LAN 扩展(F-85.2)。

### B.2 中期（2026 Q4,12 周内 — P1）

| F-Number | 名称 | 周期 |
|----------|------|:----:|
| [F-86](./f-86-computer-use.md) | Computer Use 三平台 | 3 周 |
| [F-87](./f-87-ultraplan.md) | /ultraplan 完整实现 | 3 周 |
| [F-83](./f-83-triggers.md) | 远程 Triggers | 2 周 |
| [F-82](./f-82-remote-control.md) 增强 | Worker 调度 + Web 面板 | 4 周 |
| [F-71](./f-71-tool-gap.md) P71-B/K/M | 三个 Tier-3 工具 | 2 周 |

### B.3 长期（2027 Q1+,持续 — P2/P3）

按 P2 列表逐项推进,每个 1-2 周:
[F-91](./f-91-mcp-skill-discovery.md) → [F-92](./f-92-skill-search.md) → [F-94](./f-94-bg-sessions.md) → [F-95](./f-95-templates.md) → [F-96](./f-96-cache-break-detection.md) → [F-93](./f-93-team-memory.md) → [F-97](./f-97-lodestone.md) → [F-98](./f-98-ssh-remote.md) → [F-99](./f-99-direct-connect.md);
另 P2 长期:[F-66](./f-66-acp-protocol.md) ACP、[F-72](./f-72-multi-api.md) Multi-API、[F-74](./f-74-sandbox.md) Sandbox、[F-81](./f-81-native-modules.md) Native。

---

## §C 解耦落地规范

按 `CLAUDE.md`「二次开发解耦原则」判别落点:

| 缺口类型 | 落点 | 理由 |
|----------|------|------|
| 增强上游已有模块(Remote Control、Voice Mode、Chrome) | `clawcodex_ext/` | 镜像上游目录,猴补丁/注册/DI 优先 |
| 全新独立子系统(Daemon、LAN Pipes、Triggers、TeamMem) | `extensions/` | 三方扩展层,不依赖上游具体实现 |
| 跨多个上游模块的横切能力(Proactive、Templates、Lodestone) | `extensions/capabilities/` 定义 Protocol + 实现 | 通过 Protocol 接口解耦 |
| 纯原语层工具(Ultraplan Plan 数据模型) | `clawcodex_ext/` | 配合 `extensions/` 提供 LLM/CLI 集成层 |

**注册点优先**:`clawcodex_ext/command_system/builtins.py`(命名命令)、`extensions/capabilities/*_protocol.py`(Protocol)、`clawcodex_ext/feature_gate/registry.py`(Feature flag)。
**避免**:直接改 `src/command_system/`、`src/cli.py`、`src/entrypoints/`,或在 `src/` 新建业务模块。

每个 P0/P1 缺口需满足:单元测试覆盖 ≥ 70% · `pytest tests/stability_gate/ -q -x` 全绿 · 不破坏 `extensions/orchestrator/` 测试 · ≥1 个端到端集成测试。

---

## §D 风险与约束

1. **上游同步成本** — 大幅修改 `src/` 增加合并成本,P0/P1 严格走 `clawcodex_ext/` / `extensions/`。
2. **性能敏感路径** — Proactive Tick 调度、Daemon IPC 属高频热路径,猴补丁间接层可能引入开销;必要时按 CLAUDE.md 例外条款直接改 `src/` 并在 PR 标注。
3. **平台依赖** — F-86 Computer Use 三平台涉及 Quartz / pywin32 / X11,需明确 optional dependencies。
4. **UI 一致性** — F-88 Monitor、F-85 /pipes 命令族的 TUI 面板需与现有 `clawcodex_ext/tui/` 风格一致。
5. **测试隔离** — F-84 Daemon 长驻进程需子进程 sandbox 测试模式,参考 `tests/orchestrator/manual_e2e_f38.py`。

---

## §E 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建 `gap-analysis-2026q2.md`（CCB ↔ ClawCodex 缺口快照） | Q2 末特性盘点 |
| 2026-07-01 | 分解 gap-analysis:F-NN 派工下沉到各 `f-NN-*.md` §0;矩阵/路线图并入本 README | gap-analysis 与详细设计文档并列显得冗余,统一入口 |
