# CCB ↔ ClawCodex 特性缺口分析（2026 Q2 快照）

> 状态: 📋 路线图规划
> 章节: `docs/feature_plan/06-ccb-benchmark/gap-analysis-2026q2.md`
> 最后更新: 2026-06-30
> 对标基线: [`claude-code-best`](https://gitcode.com/chadwweng/claude-code-best) `v2.2.x`（PR #60–#241 累计恢复 13 类特性 + 65+ feature flag）
> 实现基线: `clawcodex_dev` `2026-06-30`（含 F-22 / F-37 / F-38 / F-39 / F-46 / F-50 / F-62 / F-64 / F-66 / F-68 / F-69 / F-70 / F-71 / F-73 / F-82 / F-89 / F-91~F-96 / F-100 / F-102 / F-110~F-119）
> 解耦原则: 三层架构 `src/` → `clawcodex_ext/` → `extensions/`；所有 P0/P1 缺口实现优先落入 `clawcodex_ext/` 或 `extensions/`

---

## §1 背景

`claude-code-best`（CCB）是基于 Anthropic 官方 Claude Code CLI 的逆向工程分支,经过 13 个 PR 已经恢复/新增了大量高级特性。`clawcodex_dev`（ClawCodex）是其 Python 下游再实现分支,目前已经落地 81 个特性编号,但仍有相当数量的 CCB 能力仅以**原语层（primitives）**形式存在,缺乏面向用户的命令、UI 集成与端到端验证。

本文件的目标:

1. **对照** CCB `all-features-guide.md` 中罗列的 18 类能力,逐一标注 ClawCodex 的实现深度;
2. **识别** 真正面向用户的 Gap（不是简单的"少了一个 Python 文件",而是"少了一组命令 + UI + 持久化 + 测试"）;
3. **派工** 给具体 F-Number（已有或新建）,并明确解耦目标路径。

---

## §2 全特性对照矩阵

> 状态约定:
> - ✅ **已落地** — 端到端可用,经稳定性门禁覆盖;
> - 🟡 **原语层** — 内部数据结构/服务层已具备,缺命令、UI 或集成层;
> - 🟠 **部分落地** — 关键路径可用,但子特性/平台/边界条件缺失;
> - ❌ **缺失** — 完全没有实现或仅有 stub/占位。

| # | CCB 能力 | ClawCodex 现状 | 缺口等级 | 对应 F-Number / 落地路径 |
|:-:|----------|:--------------:|:--------:|--------------------------|
| 1 | **Buddy 伴侣系统** | ✅ `src/buddy/` + `clawcodex_ext/buddy/` | 已完成 | — |
| 2 | **Remote Control（远程控制）** | 🟠 `extensions/remote_api/` Hermes 兼容 API 已落地;Web UI / Worker 调度 / 会话管理缺失 | P1 | [F-82](./f-82-remote-control.md) |
| 3 | **/triggers 远程定时任务** | 🟡 `clawcodex_ext/cron_system/` 仅本地 cron;无远程 trigger API、无 /triggers 命令 | P1 | **F-83** *(新)* |
| 4 | **Voice Mode 语音模式** | 🟡 `clawcodex_ext/services/voice/` 仅检测/STT 抽象;缺 ASR 引擎运行时集成 | P0 | [F-64](./f-64-voice-mode.md) |
| 5 | **Chrome 浏览器控制** | ✅ `clawcodex_ext/services/chrome/`（MCP/Playwright/Recording 三后端） | 已完成 | F-62 |
| 6 | **Computer Use 屏幕操控** | 🟠 `clawcodex_ext/services/computer_use/` 仅 `linux.py` / `null.py` 后端;macOS + Windows 后端缺 | P1 | **F-86** *(新)* |
| 7 | **Feature Flags / GrowthBook** | ✅ F-68 `clawcodex_ext/feature_gate/`（114 测试） | 已完成 | [F-68](./f-68-feature-gate.md) |
| 8 | **/ultraplan 高级规划** | 🟡 `clawcodex_ext/services/ultraplan/` 数据模型 + executor;缺 LLM prompt 生成 + `/ultraplan` CLI | P1 | **F-87** *(新)* |
| 9 | **Daemon 后台守护** | ❌ `src/entrypoints/daemon.py` 是占位 stub("not yet implemented") | P0 | **F-84** *(新)* |
| 10 | **Pipe IPC 多实例协作** | 🟡 `clawcodex_ext/services/pipe_ipc/` 仅 UDS 传输 + registry;无 `/pipes` `/attach` `/detach` `/send` `/claim-main` 命令族 | P0 | **F-85** *(新)* |
| 11 | **LAN Pipes 局域网群控** | ❌ 无 TCP 传输层、无 UDP multicast 发现 | P0 | **F-85.2** *(新,合并入 F-85)* |
| 12 | **Monitor 后台监控** | ❌ 无 `MonitorTool`;`tail_follower.py` 是 session 内部使用 | P0 | **F-88** *(新)* |
| 13 | **Workflow 工作流脚本** | 🟠 `src/workflow/` 已支持 `.claude/workflows/*.py` 命名命令 + `/workflows` 双栏面板;缺 ultracode 编排手册 | 已完成 | F-110 协同 |
| 14 | **Coordinator 多Worker协调** | ✅ `src/coordinator/` + `clawcodex_ext/coordinator/` | 已完成 | — |
| 15 | **Proactive 自主模式** | ❌ 无 PROACTIVE / KAIROS Tick 调度器;无 SleepTool 集成 | P0 | **F-89** *(新)* |
| 16 | **History / Snip 历史管理** | ✅ F-71 P71-O `clawcodex_ext/tool_system/tools/snip.py`（282 行） | 已完成 | [F-71](./f-71-tool-gap.md) |
| 17 | **Fork 子Agent** | ✅ `clawcodex_ext/agent/fork_subagent.py`（294 行） | 已完成 | — |
| 18 | **其他恢复的工具** | 🟠 F-71 已完成 12/15;WebBrowser / Execute / RemoteTrigger 3 个待补 | P1 | [F-71](./f-71-tool-gap.md) |

### 附加能力（CCB `附录：全部 Feature Flags` 派生）

| # | CCB Feature Flag | ClawCodex 现状 | 缺口等级 | 备注 |
|:-:|------------------|:--------------:|:--------:|------|
| 19 | `ACP`（Agent Client Protocol） | ❌ | P1 | [F-66](./f-66-acp-protocol.md) 规划中 |
| 20 | `MCP_SKILLS`（skill:// URI 自动发现） | ❌ | P2 | 新 |
| 21 | `EXPERIMENTAL_SKILL_SEARCH`（TF-IDF 搜索） | ❌ | P2 | 新 |
| 22 | `TEAMMEM`（Team 共享记忆） | ❌ | P2 | 新 |
| 23 | `BG_SESSIONS`（后台会话） | 🟡 部分实现（`clawcodex_ext/tasks/`） | P1 | 新 |
| 24 | `TEMPLATES`（模板系统） | 🟡 `extensions/orchestrator/templates/` | P1 | 协同 F-110 |
| 25 | `CONTEXT_COLLAPSE`（上下文折叠） | ✅ `clawcodex_ext/services/compact/context_collapse.py` | 已完成 | — |
| 26 | `AWAY_SUMMARY`（离开摘要） | ✅ `clawcodex_ext/away_summary/` | 已完成 | — |
| 27 | `BUILTIN_EXPLORE_PLAN_AGENTS`（Explore/Plan 子代理） | 🟡 Explore 实现,Plan 与 SPEC 模式已有 | P2 | 完善 |
| 28 | `SHOT_STATS`（API 调用统计） | 🟡 `clawcodex_ext/tool_stats.py` + `src/cost_tracker.py` | P2 | 完善 |
| 29 | `PROMPT_CACHE_BREAK_DETECTION`（缓存命中检测） | ❌ | P2 | 新 |
| 30 | `AGENT_TRIGGERS_REMOTE`（远程 trigger） | ❌ | P1 | **F-83** 协同 |
| 31 | `TOKEN_BUDGET`（Token 预算） | ✅ F-69 | 已完成 | [F-69](./f-69-budget-mode.md) |
| 32 | `ULTRAPLAN`（增强规划） | 🟡 F-87 | P1 | **F-87** |
| 33 | `WORKFLOW_SCRIPTS`（工作流脚本） | ✅ `src/workflow/` + 命名工作流命令 | 已完成 | F-110 |
| 34 | `HISTORY_SNIP`（历史管理） | ✅ | 已完成 | F-71 |
| 35 | `KAIROS`（Tick 调度） | 🟡 `clawcodex_ext/services/kairos/scheduler.py` | 已完成（基础） | F-89 增强 |
| 36 | `PROACTIVE`（主动模式） | ❌ | P0 | **F-89** |
| 37 | `COORDINATOR_MODE` | ✅ | 已完成 | — |
| 38 | `MONITOR_TOOL`（后台监控） | ❌ | P0 | **F-88** |
| 39 | `FORK_SUBAGENT` | ✅ | 已完成 | — |
| 40 | `UDS_INBOX`（Pipe IPC） | 🟡 原语层,缺命令族 | P0 | **F-85** |
| 41 | `LAN_PIPES`（局域网群控） | ❌ | P0 | **F-85.2** |
| 42 | `DAEMON`（后台守护） | ❌ | P0 | **F-84** |
| 43 | `ACP` | ❌ | P1 | [F-66](./f-66-acp-protocol.md) |
| 44 | `LODESTONE`（深度链接） | ❌ | P2 | 新 |
| 45 | `SSH_REMOTE`（SSH 远程模式） | ❌ | P2 | 协同 F-74 |
| 46 | `SKILL_LEARNING`（技能学习） | ❌ | P3 | 长期 |
| 47 | `REVIEW_ARTIFACT`（评审产物） | ❌ | P3 | 长期 |
| 48 | `CONNECTOR_TEXT`（文本连接器） | ❌ | P3 | 长期 |
| 49 | `COMMIT_ATTRIBUTION`（commit 归属） | 🟡 部分(extensions/orchestrator/git_sync) | P3 | 已隐式支持 |
| 50 | `DIRECT_CONNECT`（直连模式） | 🟡 `src/server/direct_connect_manager.py` | P2 | 完善 |
| 51 | `DUMP_SYSTEM_PROMPT`（dump 系统提示） | 🟡 `--dump-system-prompt` flag 已支持 | 已完成 | — |
| 52 | `ULTRATHINK`（扩展思考） | 🟡 `clawcodex_ext/agent/thinking.py`（stub） | P2 | 完善 |

---

## §3 关键缺口详解（按优先级）

### 3.1 P0 — 必须解决（影响核心差异化能力）

#### F-84: Daemon 后台守护

**缺口描述**: `src/entrypoints/daemon.py` 显式声明"not yet implemented",导致 `clawcodex daemon` 命令族(start/status/stop/ps/bg/attach/logs/kill)完全不可用。同时 CCB 的 DAEMON 与 BRIDGE_MODE 强绑定,缺 Daemon 即缺完整 RCS 体验。

**对标**:
- CCB: `src/daemon/main.ts` (Supervisor + 指数退避重启 + workerRegistry)
- CCB: `daemon-state.json` 文件系统状态 + CLI 子命令 `claude daemon start/status/stop`

**解耦落地路径**:
- `extensions/daemon/`（新建独立子系统,绝不修改 `src/`）:
  - `supervisor.py` — Supervisor 进程 + Worker 生命周期（指数退避 2s→120s、5×/10s 快速失败、EXIT_CODE_PERMANENT=78 parking、SIGTERM/SIGINT 优雅关闭）
  - `worker_registry.py` — remoteControl / bridgeHeadless Worker 注册
  - `state.py` — PID/CWD/startup time state file IO + queryDaemonStatus / stopDaemonByPid
  - `cli.py` — `clawcodex-dev daemon start|status|stop|ps|logs|attach|kill` CLI 绑定（避免污染 `src/cli.py`）
- `clawcodex_ext/daemon/bridge_integration.py` — 与 `src/bridge/` 的 runtime 桥接（猴补丁）

**依赖**:
- F-82 Remote Control 增强(Worker 调度)
- F-68 Feature Gate（DAEMON / BRIDGE_MODE 双重门控）

**估算工时**: 2-3 周

---

#### F-85: Pipe IPC 多实例协作（UDS + LAN）

**缺口描述**: `clawcodex_ext/services/pipe_ipc/` 已有 `UdsPipeServer` / `UdsPipeClient` / `PipeRegistry` / `PipePermissionForwarder` / `PipeMessage` 五件套,但**没有任何上层命令族**——`/pipes` / `/attach` / `/detach` / `/send` / `/pipe-status` / `/claim-main` / `/peers` 全部缺失。同时 LAN_PIPES（TCP + UDP Multicast 发现）完全没实现。

**对标**:
- CCB: `src/utils/pipeTransport.ts` + `pipeRegistry.ts` + 7 个 CLI 命令
- CCB: LAN beacon UDP 7101 / TCP 1024-65535 / firewall 规则模板

**解耦落地路径**:
- `clawcodex_ext/services/pipe_ipc/`（已完成基础设施,补命名命令）:
  - `commands/` — `/pipes` `/attach` `/detach` `/send` `/pipe-status` `/claim-main` 7 个命令
  - `cli/registry_bridge.py` — `PipeRegistry` 与 `CommandSystem` 集成
- `extensions/pipe_ipc/`（新建,LAN_PIPES 子特性）:
  - `lan_transport.py` — TCP 传输层（基于 `asyncio.start_server` + `asyncio.open_connection`）
  - `multicast_beacon.py` — UDP multicast 7101 + announce/listen
  - `discovery.py` — UDP beacon + TCP 握手 + machineId 注册
  - `peer_marker.py` — LAN peer 标记（`[LAN] vmwin11/192.168.50.27`）

**命名命令注册**: 落 `clawcodex_ext/command_system/builtins.py` 注册点（避免改 `src/command_system/`）。

**依赖**:
- `clawcodex_ext/services/pipe_ipc/`（已存在）
- `src/bridge/`（permissions 转发）

**估算工时**: 3-4 周（其中 LAN_PIPES 单独 2 周）

---

#### F-89: Proactive 自主模式 + KAIROS Tick 集成

**缺口描述**: `clawcodex_ext/services/kairos/scheduler.py` 已有 TickScheduler,但**没有 PROACTIVE 整套能力**:
- 无 `activateProactive()` / `deactivateProactive()` / `pause` / `resume`
- 无 `<tick_tag>` prompt 注入机制
- 无 `SleepTool` 与 PROACTIVE 的双向唤醒
- 无 REPL 集成（standby / sleeping 状态、页脚上报）
- 无 `automation_state` 元数据透出到 RCS/CCR

**对标**:
- CCB: `src/proactive/index.ts` + `src/tools/SleepTool/` + `getProactiveSection()` 系统提示注入（~55 行）
- 引用数 37,在所有 CCB 命令中使用频率排前列

**解耦落地路径**:
- `clawcodex_ext/services/proactive/`（新建独立子系统）:
  - `controller.py` — `ProactiveController.activate/deactivate/pause/resume`
  - `tick_emitter.py` — Tick 调度 + `<tick_tag>` prompt 注入（与 `kairos.TickScheduler` 共享时间轴）
  - `automation_state.py` — `standby` / `sleeping` 状态机
  - `metadata_reporter.py` — 向 `extensions/remote_api/` 暴露 `automation_state`（F-82 协同）
  - `system_prompt.py` — `getProactiveSection()` 拼接（terminalFocus 调节自主程度）
- `clawcodex_ext/tool_system/tools/sleep.py` — `SleepTool` 接入 ProactiveController（唤醒命令队列）

**依赖**:
- F-68 Feature Gate（PROACTIVE / KAIROS 双重门控）
- F-64 Voice Mode 完成后（SleepTool + Push-to-Talk 复用状态机）

**估算工时**: 3-4 周

> 详细需求 / 子特性 / 架构 / 验收 / 风险: 参见 [f-89-proactive.md](./f-89-proactive.md)。

---

#### F-88: Monitor 后台监控 + MonitorTool

**缺口描述**: 完全缺失。CCB 的 `MONITOR_TOOL` 允许后台 `tail -f` / `watch -n` 类持续监控,AI 与用户都可触发。Windows 上 `watch` 自动转 PowerShell `while(true){...; Start-Sleep -Seconds <n>}`。

**对标**:
- CCB: `/monitor` 命令 + `MonitorTool` 内置工具 + Shift+↓ 后台任务面板
- CCB: Windows 兼容 PowerShell 循环

**解耦落地路径**:
- `clawcodex_ext/services/monitor/`（新建）:
  - `controller.py` — `MonitorController` 管理后台任务（start/stop/list/output）
  - `watch_compat.py` — `watch -n <sec> <cmd>` 跨平台转 PowerShell / bash
  - `output_buffer.py` — ring buffer 输出采集
- `clawcodex_ext/command_system/builtins.py` 注册 `/monitor` 命令
- `clawcodex_ext/tool_system/tools/monitor.py` — `MonitorTool` 内置工具（AI 可调用）
- `clawcodex_ext/tui/screens/monitor_panel.py` — TUI 后台任务面板

**依赖**:
- `tail_follower.py` 复用（已有）
- `clawcodex_ext/tui/` TUI 框架

**估算工时**: 1-2 周

---

### 3.2 P1 — 重要改进（差异化能力补强）

#### F-83: 远程 Triggers（AGENT_TRIGGERS_REMOTE）

**缺口描述**: `clawcodex_ext/cron_system/` 仅本地调度,CCB 的 AGENT_TRIGGERS_REMOTE 允许在远程服务器上注册定时 Agent 任务（cron 表达式 + prompt）,通过 REST API 同步。

**对标**: CCB `/triggers create|list|delete` 命令 + 远程 trigger API。

**解耦落地路径**:
- `extensions/triggers/`（新建）:
  - `api.py` — FastAPI REST 端点（POST /triggers / GET /triggers / DELETE /triggers/{id}）
  - `registry.py` — 远程 trigger 注册表（持久化到 ~/.clawcodex/triggers.json）
  - `executor.py` — 远程触发执行器（通过 SSH / 远程 RCS 调用）
- `clawcodex_ext/command_system/builtins.py` 注册 `/triggers` 命令
- `clawcodex_ext/cron_system/remote_bridge.py` — 本地 cron 与远程 trigger 的桥接

**依赖**:
- F-68 Feature Gate（AGENT_TRIGGERS_REMOTE）
- F-82 RCS（远程执行 endpoint）

**估算工时**: 1-2 周

> 详细需求 / 子特性 / 架构 / 落地步骤 / 风险: 参见 [f-83-triggers.md](./f-83-triggers.md)。

---

#### F-86: Computer Use 跨平台 Executor

**缺口描述**: `clawcodex_ext/services/computer_use/` 仅有 `linux.py`（基础 X11/Wayland 模拟）+ `null.py` 后端,缺 macOS / Windows 后端。CCB 已完整实现三平台统一接口。

**解耦落地路径**:
- `clawcodex_ext/services/computer_use/platform/`:
  - `macos.py` — PyObjC / Quartz CGEventCreate（键鼠）+ screencapture（截图）
  - `windows.py` — pywin32 / ctypes SendInput + Pillow ImageGrab
  - `linux.py` — 完善（X11/Wayland 双栈,当前为基础实现）
- `clawcodex_ext/services/computer_use/platform/factory.py` — 平台自动选择

**依赖**:
- `pynput`（键鼠,可选依赖）
- `Quartz`（macOS,可选依赖）
- `pywin32`（Windows,可选依赖）

**估算工时**: 2-3 周（含三平台适配）

> 详细需求 / 子特性 / 架构 / 落地步骤 / 风险: 参见 [f-86-computer-use.md](./f-86-computer-use.md)。

---

#### F-87: /ultraplan LLM 驱动 + CLI 完整实现

**缺口描述**: `clawcodex_ext/services/ultraplan/`（F-83 first iteration）已完成 Plan → SubPlan → Step 数据模型 + 原子 JSON 存储 + Step 状态机执行 + Plan 调整器 + 沙箱验收标准验证器。**缺**:
- LLM 驱动的 Plan 生成（解析用户需求 → Plan 数据模型）
- `/ultraplan` CLI 斜杠命令
- CCR 远程会话（本地/远程双模式）
- 关键字检测（`findUltraplanTriggerPositions` 智能过滤）
- 彩虹高亮（输入框提示）

**对标**: CCB `src/commands/ultraplan.tsx`（525 行）+ `src/utils/ultraplan/ccrSession.ts`（349 行）

**解耦落地路径**:
- `clawcodex_ext/services/ultraplan/`（在现有原语层上扩展）:
  - `llm_planner.py` — LLM 驱动 Plan 生成（基于 system prompt + 用户输入 → Plan JSON）
  - `keyword_detector.py` — `findUltraplanTriggerPositions` / `replaceUltraplanKeyword`
  - `ccr_session.py` — 远程 CCR 会话（通过 `extensions/remote_api/` 桥接）
- `clawcodex_ext/command_system/builtins.py` 注册 `/ultraplan` 命令
- `clawcodex_ext/repl/input_processing.py` 关键字检测拦截

**依赖**:
- `clawcodex_ext/services/ultraplan/`（已存在原语层）
- F-82 RCS（远程 CCR）
- `clawcodex_ext/providers/` LLM Provider（用于生成 Plan）

**估算工时**: 2-3 周

> 详细需求 / 子特性 / 架构 / 落地步骤 / 风险: 参见 [f-87-ultraplan.md](./f-87-ultraplan.md)。

---

#### F-71 P71-B / P71-K / P71-M: 三个 Tier-3 工具补齐

**缺口描述**: F-71 已完成 12/15,剩余三个工具待补:
- **P71-B**: `WebBrowserTool` 浏览器控制（依赖 playwright）
- **P71-K**: `ExecuteTool` 代理工具执行
- **P71-M**: `RemoteTriggerTool` 远程触发（依赖 httpx,与 F-83 协同）

**解耦落地路径**:
- `clawcodex_ext/tool_system/tools/`:
  - `web_browser.py` — Playwright 浏览器控制（无 playwright 时降级 NullBrowserTool）
  - `execute.py` — 代理工具执行（委托 AgentTool）
  - `remote_trigger.py` — 远程触发（依赖 F-83 + httpx）

**估算工时**: 1-2 周

---

#### F-82 增强: Worker 调度 + Web 管理面板

**缺口描述**: `extensions/remote_api/`（2,606 行,11 模块）已实现 Hermes/OpenAI 兼容 API + SSE + Bearer 认证。但**缺**:
- FastAPI 应用工厂 + Worker 注册/心跳/分发
- ACP 协议中继
- Web 管理面板（CCB 用 React 19 + Vite + Radix UI）

**解耦落地路径**:
- `extensions/remote_api/`（在现有基础上扩展）:
  - `worker_registry.py` — Worker 心跳 + 状态机（ONLINE/OFFLINE/BUSY/ERROR）
  - `work_dispatch.py` — 长轮询 + 事件驱动 worker 分发
  - `acp_relay.py` — ACP 协议中继桥接（WebSocket/SSE）
  - `session_api.py` — 会话 CRUD + 远程会话启动
- `extensions/visualizer/` 扩展为完整 RCS Web 面板（基于现有 Flask/Jinja2）

**估算工时**: 3-4 周

---

### 3.3 P2 — 长期规划（差异化补全）

| F-Number | 名称 | 落地路径 | 估算工时 |
|----------|------|----------|----------:|
| F-66 | ACP 协议完整实现 | `clawcodex_ext/services/acp/` | 2-3 周 |
| **F-91** *(新)* | MCP Skills 自动发现 | `clawcodex_ext/services/mcp/skill_discovery.py` | 1 周 |
| **F-92** *(新)* | experimental_skill_search TF-IDF | `clawcodex_ext/services/skill_search/` | 1 周 |
| **F-93** *(新)* | TeamMem 共享记忆 | `extensions/agents/team_memory.py` | 2 周 |
| **F-94** *(新)* | BG_SESSIONS 后台会话 | `clawcodex_ext/tasks/bg_session.py` | 1 周 |
| **F-95** *(新)* | TEMPLATES 模板系统 | `extensions/orchestrator/templates/`（已部分） | 1 周 |
| **F-96** *(新)* | PROMPT_CACHE_BREAK_DETECTION | `clawcodex_ext/providers/cache_breaker.py` | 1 周 |
| F-72 | Multi-API 原生适配器 | `clawcodex_ext/providers_ext/` | 2-3 周 |
| F-74 | Sandbox Docker/SSH 远程执行 | `clawcodex_ext/services/sandbox/` | 2-3 周 |
| F-81 | Native 原生模块系统 | `clawcodex_ext/native/` | 2-3 周 |
| **F-97** *(新)* | LODESTONE 深度链接 | `clawcodex_ext/services/lodestone/` | 1-2 周 |
| **F-98** *(新)* | SSH_REMOTE 远程模式 | 协同 F-74 | 1 周 |
| **F-99** *(新)* | DIRECT_CONNECT 直连模式 | `src/server/direct_connect_manager.py`（已部分） | 1 周 |

---

## §4 解耦原则与落地规范

### 4.1 三层架构判别

按 `CLAUDE.md`「二次开发解耦原则」:

| 缺口类型 | 落点 | 理由 |
|----------|------|------|
| 增强上游已有模块(如 Remote Control、Voice Mode、Chrome) | `clawcodex_ext/` | 镜像上游目录结构,猴补丁/注册中心/DI 优先 |
| 全新独立子系统(如 Daemon、LAN Pipes、Triggers) | `extensions/` | 三方扩展层,不依赖上游具体实现 |
| 跨多个上游模块的横切能力(如 Proactive、Templates) | `extensions/capabilities/` 定义 Protocol + `extensions/` 实现 | 通过 Protocol 接口解耦 |
| 纯原语层工具(如 Ultraplan Plan 数据模型) | `clawcodex_ext/` | 配合 `extensions/` 提供 LLM/CLI 集成层 |

### 4.2 命名约定

- F-Number 沿用 [F-Number 总表](../README.md#f-number-状态总表) 体系
- 新建 F-Number 集中在 80-99 范围(CCB 对标缺口)
- 子特性用 `F-NN.X` 编号(如 F-85.2 LAN_PIPES)

### 4.3 注册点选择

**优先**:
- `clawcodex_ext/command_system/builtins.py` — 命名命令注册
- `extensions/capabilities/*_protocol.py` — Protocol 定义
- `src/services/feature_gate/registry.py` — Feature flag 注册

**避免**:
- 直接修改 `src/command_system/`、`src/cli.py`、`src/entrypoints/`
- 在 `src/` 新建任何业务模块

### 4.4 测试与门禁

每个 P0/P1 缺口需满足:
- 单元测试覆盖率 ≥ 70%
- `python3 -m pytest tests/stability_gate/ -q --tb=short -x` 全绿
- 现有 `extensions/orchestrator/` 测试不受影响
- 至少 1 个集成测试覆盖端到端流程

---

## §5 路线图建议

### 5.1 短期（2026 Q3,8 周内）

| 优先级 | F-Number | 名称 | 周期 | 累计工时 |
|:------:|----------|------|:----:|:--------:|
| P0 | F-85 | Pipe IPC 命令族(UDS) | 2 周 | 2 周 |
| P0 | F-88 | Monitor Tool | 1.5 周 | 3.5 周 |
| P0 | F-84 | Daemon Supervisor | 3 周 | 6.5 周 |
| P0 | F-89 | Proactive 模式 | 3 周 | 9.5 周 |
| P0 | F-85.2 | LAN Pipes | 2 周 | 11.5 周 |

> 注: F-85 与 F-85.2 拆分,先做 UDS 命令族,再做 LAN 扩展。

### 5.2 中期（2026 Q4,12 周内）

| 优先级 | F-Number | 名称 | 周期 |
|:------:|----------|------|:----:|
| P1 | F-86 | Computer Use 三平台 | 3 周 |
| P1 | F-87 | /ultraplan 完整实现 | 3 周 |
| P1 | F-83 | 远程 Triggers | 2 周 |
| P1 | F-82 增强 | Worker 调度 + Web 面板 | 4 周 |
| P1 | F-71 P71-B/K/M | 三个 Tier-3 工具 | 2 周 |

### 5.3 长期（2027 Q1+,持续）

按 P2 列表逐项推进,每个 1-3 周;优先 ACP(F-66)与 Multi-API(F-72)。

---

## §6 风险与约束

1. **上游同步成本**: 大幅修改 `src/` 会增加与上游合并的成本,所有 P0/P1 必须严格走 `clawcodex_ext/` / `extensions/` 路径。
2. **性能敏感路径**: Proactive 的 Tick 调度、Daemon 的进程间通信属于高频热路径,猴补丁的间接层可能引入可观开销——必要时按 `CLAUDE.md` 例外条款直接改 `src/`,但需在 PR 中明确标注。
3. **平台依赖**: F-86 Computer Use 三平台适配涉及大量平台特定依赖(macOS Quartz / Windows pywin32 / Linux X11),需明确 optional dependencies。
4. **UI 一致性**: F-88 Monitor、F-85 /pipes 命令族涉及 TUI 面板开发,需保持与现有 Ink 风格一致(`clawcodex_ext/tui/`)。
5. **测试隔离**: F-84 Daemon 是长驻进程,需要特殊测试模式(子进程 sandbox),参考 `tests/orchestrator/manual_e2e_f38.py` 的 LocalTracker 模式。

---

## §7 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-30 | 初始创建(CCB ↔ ClawCodex 缺口快照) | Q2 末特性盘点,派工 P0/P1/P2 缺口 |