# ClawCodex 开发路线图 (ROADMAP)

> 文档路径: `docs/ROADMAP.md`
> 基于: `docs/FEATURE_PLAN.md` (v3.14) + `docs/PROGRESS.md` (v3.13)
> 更新日期: 2026-06-22

---

## 一、总体进度总览

| 类别 | 已完成 | 进行中/部分完成 | 规划中/待开始 | 合计 |
|------|:-----:|:--------------:|:-------------:|:----:|
| **Orchestrator 系统** | 12 | 2 | 0 | 14 |
| **Agent 核心能力** | 14 | 1 | 3 | 18 |
| **CLI 与配置系统** | 3 | 0 | 0 | 3 |
| **Architecture & SDK** | 5 | 1 | 2 | 8 |
| **Cron 系统** | 1 (A~E+G1~G10) | 0 (剩余 R5/R7/R8) | 0 | 1 |
| **会话恢复增强** | 1 (F-49) | 0 | 0 | 1 |
| **CCB 对标缺口** | 10 | 2 | 3 | 15 |
| **Python 生态补缺** | 1 | 3 | 3 | 7 |
| **Multi-Session 可视化** | 1 (F-91~F-96) | 0 | 0 | 1 |
| **遥测系统** | 1 (F-97) | 0 | 0 | 1 |
| **其他** | 2 | 0 | 0 | 2 |
| **开源替代组件** | 7 | 0 | 3 | 10 |
| **总计** | **58** | **9** | **14** | **81** |

---

## 二、Orchestrator 系统

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-1 | Orchestrator 自主模式 (Symphony 集成) | P0 | ✅ 已完成 | 核心组件、生产强化、Issue 语义澄清三通道、Orchestrator CLI 运维界面等子特性全部归档 |
| F-36 | LocalTracker 本地 Issue 文档源 | P1 | ✅ 已完成 | `tracker.kind: local`，支持离线测试与本地工作流 |
| F-37 | PR 检视意见自动修复闭环 | P0 | ✅ 已完成 | `ReviewFeedbackService` + GitSync follow-up 全链路 |
| F-38 | 验证与报告闭环 | P0 | ✅ 已完成 | `pre_commit`/`pre_push`/`post_sync` verification gates + 报告生成 + PR body 更新 |
| F-39 | Issue 重跑入口 | P0 | ✅ 已完成 | label (`agent:retry`/`follow-up`/`blocked`) + comment 命令双通道 + CLI 兜底 |
| F-40 | ProgressReporter Sink 重构 | P1 | ✅ 已完成 | `ProgressSink` Protocol + `CompositeProgressSink` + `ToolContextProgressSink` |
| F-41 | Coordinator 轻量工具集 | P1 | ✅ 已完成 | Read/WebSearch/WebFetch 6 工具，Coordinator 可直接处理简单查询 |
| F-42 | Shared/Sequential Workspace 策略 | P0 | ✅ 已完成 | `workspace.strategy: isolated | shared | sequential` 全策略支持 |
| F-44 | 人工检视闸门 (Review Gate) | P1 | ✅ 已完成 | `agent.review_required: true` 可选闸门 |
| F-45 | Tool-call 审计旁路 | P1 | ✅ 已完成 | NDJSON 旁路落盘 `~/.clawcodex/tool-events/{run_id}/events.ndjson` |
| F-49 | Issue 会话统一存储与实时介入 | P1 | ✅ 已完成 | Phase 0.4 + Phase 5 P5-A~G 全部落地；Unix Socket 控制通道已接入 |
| F-51 | AgentRunner 空转检测机制 | P0 | ✅ 已完成 | 连续 5 轮工作区无变更自动检测 |
| F-54 | 运行期可观测性 | P0 | 🟡 部分完成 | `debug_log.py` + `append_debug_event` 已落地；仪表盘/query-runner heartbeat/CLI 诊断字段待补齐 |
| F-46 | permission_mode 正交拆分 | P2 | 🟡 部分完成 (F-46.0) | `audit_log` 字段已定义；`interactive`/`default_decision` 待后续 |

---

## 三、Agent 核心能力

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-2 | Team 成员管理 (Phase-7) | P1 | 🔄 进行中 | `members` 数组，SendMessage + resume_agent 已完成；TeamCreate/TeamDelete 待实现 |
| F-3 | MCP 协议扩展 | P1 | ✅ 已完成 | Stdio/HTTP+SSE/WS 基础传输 + 资源缓存/Batch 调用/Progress 通知增强 |
| F-4 | 结构化输出集成 (Outlines) | P2 | ✅ 已完成 | 适配器已完整实现在 `clawcodex_ext/agent/_outlines_adapter.py` |
| F-9 | /goal 命令 | P2 | ✅ 已完成 | `clawcodex_ext/goal/` 9 文件 2538 行：状态机/持久化/续跑/Tool/prompt/CLI 命令 |
| F-11 | sessionStorage 容量限制 | P2 | ✅ 已完成 | `MAX_CACHED_SESSION_FILES=1000` |
| F-12 | cacheWarning 容量限制 | P2 | ✅ 已完成 | `clawcodex_ext/utils/cache_warning.py` |
| F-13 | Agent 记忆作用域隔离 | P1 | ✅ 已完成 | 按需加载不同作用域记忆 |
| F-16 | Auto 模式 (TRANSCRIPT_CLASSIFIER) | P2 | ✅ 已完成 | `auto_mode_classify()` + `DenialTracker` 完整实现 |
| F-18 | CreateAgentTool 动态工具创建 | P2 | ✅ 已完成 | Agent 根据 CLI/API 规范动态创建工具，Meta Tool 能力 |
| F-20 | Agent 阶段性进度汇报 | P2 | ✅ 已完成 | 三组合方案：检查点触发 + ProgressReportTool + ToolContext.tasks |
| F-78 | Issue 语义澄清流程 | P1 | ✅ 已完成 | 三通道优先机制 (Dashboard/ClarificationQueue/@mention) |
| F-80 | Agent 间自主观察与消息交互 | P2 | ✅ 已完成 | `TaskInspectTool` + `TaskDirectivesTool` 642 行 |
| F-99 | Ctrl+C/B 即时中断响应优化 | P0 | ✅ 已完成 | 三层方案，Cancel latency bound <500ms (直连 Anthropic) |
| F-100 | Dreaming 后台记忆整合系统 | P2 | ✅ 已完成 (Phase B 待补) | Phase A/C/D/E 全部完成；106 单测 + 12 门禁 + 6 E2E |
| F-101 | Media Generation Provider | P2 | ✅ 已完成 | `clawcodex_ext/providers/media/` 9 文件 1005 行：MediaProvider ABC + AgnesImage/VideoProvider |
| F-102 | Agent Loop Hook 扩展点增强 | P1 | 📋 设计完成 | 5 子特性 P102-A~E，总预计 9-15 天 |
| F-10 | ExecuteExtraTool 延迟工具系统 | P2 | ⏳ 待开始 | TF-IDF 工具搜索 + 子代理执行 |
| F-75 | 工具/Skill 调用统计 (跨会话) | P2 | ⏳ 待开始 | JSON Lines 日志方案或 Transcript 轻量方案 |

---

## 四、CLI 与配置系统

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-34 | CLI/TUI Frontend 解耦架构 | P1 | ✅ 已完成 | Phase 1-3 全部完成 |
| F-43 | CLI 模型供应商与模型切换 | P1 | ✅ 已完成 | `clawcodex provider`/`model` 子命令族 + REPL/TUI `/provider`/`/model` 斜杠命令 + 动态模型发现注册表 |
| F-47 | Permission Settings Schema 重构 | P1 | ✅ 已完成 | 修四层串联 bug + permissions dict 形态对齐 + F-47.1 hotfix |
| F-35 | 二开特性可切换架构 | P0 | 📋 设计完成 | Feature Toggle 系统 + 584 文件特性提取方案，gate: 等待 F-48 Phase 0 完成 |

---

## 五、Architecture & SDK 下沉

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-48 | src/ 核心路径二开解耦 | P0 | 🟡 进行中 | F-48.2 完成 3 项 (tools/__init__/providers/__init__/agent/session.py)；剩余 Phase 4-9 逐项推进 |
| F-50 | SOP 转换器源码固化 | P1 | ✅ 已完成 | `extensions/pos_converter/` 9 文件 2429 行 |
| F-52 | Python SDK 方法注册为 Tool | P2 | ✅ 已完成 | `register_python_function()` + `build_tool_from_spec()` python/http/bash 三种 call_type |
| F-53 | Tool → CLI 斜杠命令 | P3 | 📋 规划中 | 依赖 F-52；`clawcodex_ext/cli/tool_cmd/` 设计已就绪 |
| F-55 | SOP 分组策略增强 | P1 | ✅ 已完成 | 四种分组策略 (sequential/domain/operative/priority) |

---

## 六、Cron 系统

| ID | 特性 | Phase | 优先级 | 状态 | 备注 |
|----|------|:-----:|:------:|:----:|------|
| F-22 | Cron 系统执行引擎 | A~E+G1~G10 | P0 | ✅ 主要完成 | 13 模块 3189 行全部实现 |
| | Phase A: Runtime 接线 | A | P0 | ✅ 已完成 | REPL/TUI/headless 运行路径打通，scheduler 后台运行 |
| | Phase B: 存储模型对齐 | B | P0 | ✅ 已完成 | durable/session 分离，CronTask 完整字段 |
| | Phase C: 调度器语义对齐 | C | P0 | ✅ 已完成 | check_once + inFlight + jitter + missed notification |
| | Phase D: 执行队列与结果追踪 | D | P0 | ✅ 已完成 | CronRun 全生命周期 + run store |
| | Phase E: Skills 与用户命令 | E | P0 | ✅ 已完成 | `/loop` + `/cron-list` + `/cron-delete` |
| | G1: isKilled 运行时 Kill 开关 | — | P0 | ✅ 已完成 | `CLAWCODEX_DISABLE_CRON` + scheduler 每 tick 轮询 |
| | G2: 远程 Jitter 实时配置 | — | P0 | ✅ 已完成 | 6 参数配置文件/env 热加载 |
| | G3: One-shot 反向 Jitter | — | P1 | ✅ 已完成 | 整点 (:00/:30) 提前触发 |
| | G4: Permanent 免过期机制 | — | P1 | ✅ 已完成 | 幂等安装 + 写保护 + 过期豁免 |
| | G5: 锁注册式清理与 PID 增强 | — | P1 | ✅ 已完成 | atexit/SIGTERM/SIGINT 清理 + PID 分身检测 |
| | G6: 工具 Prompt 指引增强 | — | P2 | ✅ 已完成 | CronCreate/List/Delete 最佳实践 prompt |
| | G7: Analytics 遥测事件预留 | — | P2 | ✅ 已完成 | fire/missed/expired 事件钩子 |
| | G8: inFlight 防重复触发 | — | P2 | ✅ 已完成 | `_in_flight` Set + Lock 防异步二次发射 |
| | G9: SDK daemon 模式 | — | P1 | ✅ 已完成 | `dir_override`/`lock_identity` 可选参数 |
| | G10: cronToHuman(utc) UTC 模式 | — | P2 | ✅ 已完成 | 本地时区偏移显示 |
| | F22-R5: busy gate/filter | — | P1 | ⏳ 待设计 | isLoading、assistantMode、per-task filter |
| | F22-R7: teammate ownership | — | P1 | ⏳ 待设计 | agentId/ownership 路由与静默丢弃保护 |
| | F22-R8: env 别名兼容 | — | P2 | ⏳ 待设计 | `CLAUDE_CODE_DISABLE_CRON` 别名 |
| | D1~D4: CCB 4 层防护集成 | — | P1 | 📋 设计完成 | 待集成验证 |

---

## 七、会话恢复增强

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-49 | Issue 会话统一存储与实时介入 | P1 | ✅ 已完成 | Phase 0.4 + Phase 5 全部落地；`Session.resume()` JSONL 消息加载自愈 |
| S-R1 | 退出路径打印 Resume Hint | P0 | ✅ 已解决 (v2.16) | `/exit`/`Ctrl+C`/SIGTERM 全覆盖 |
| S-R2 | Resume 后历史完整渲染 | P0 | ✅ 已解决 (v2.16) | user 消息不再跳过 |
| S-R3 | `--continue` CLI 快捷命令 | P0 | ✅ 已解决 (v2.16) | 自动恢复最近会话 |
| S-R5 | REPL 端会话浏览器 | P0 | ✅ 已解决 (v2.16) | Rich table 交互式列表 |
| S-R6 | `--fork-session` 支持 | P1 | ✅ 已解决 (v2.16) | 创建新 session ID 保留历史 |
| S-R7 | Session 标签系统 | P1 | ✅ 已实现 | `SessionMetadata.tags` + 按标签恢复 |

---

## 八、CCB 对标缺口补缺

| ID | 特性 | 优先级 | 对标级别 | 状态 | 备注 |
|----|------|:------:|:--------:|:----:|------|
| F-60 | Pipe IPC + LAN 群控 | P0 | 🔴 严重缺口 | ✅ 已完成 | `src/services/pipe_ipc/` 967 行 + 11 测试 |
| F-61 | Computer Use 屏幕操控 | P0 | 🔴 严重缺口 | ✅ 已完成 | `src/services/computer_use/` 1797 行 + 15 测试 |
| F-62 | Chrome 浏览器自动化 | P1 | 🟡 重要缺口 | ✅ 已完成 | `src/services/chrome/` 8 模块 ~1700 行；7 个 chrome_* 工具 |
| F-63 | Channels 频道通知 | P1 | 🟡 重要缺口 | ✅ 已完成 | 飞书/Slack/Discord 推送；2097 行 + 18 测试 |
| F-64 | Voice Mode 语音输入 | P2 | 🟢 增强体验 | 🟡 进行中 | 检测层 + STT 抽象类 (188 行)；运行时集成待补 |
| F-65 | Langfuse 可观测性 | P1 | 🟡 重要缺口 | ✅ 已完成 | `src/services/analytics/` + `src/services/langfuse/` 全链路；49 测试 |
| F-66 | ACP 协议支持 | P2 | 🟢 增强体验 | ⏳ 待开始 | Zed/Cursor IDE 集成；预计 1-2 周 |
| F-67 | Buddy/Proactive 自主模式 | P2 | 🟢 增强体验 | ✅ 已完成 | `src/buddy/` 8 文件完整实现 (1371 行) |
| F-70 | Plugin 系统 | P1 | 🟡 重要缺口 | 🟡 部分完成 | `src/plugins/` 8 文件 1070 行基础框架 |
| F-81 | Native 原生模块系统 | P1 | 🟡 重要缺口 | ⏳ 待开始 | 音频捕获/图像处理/URL Scheme/修饰键检测；预计 1 周 |
| F-82 | Remote Control Server | P1 | 🟡 重要缺口 | ⏳ 待开始 | FastAPI 远程控制；预计 3-4 周 |
| F-83 | Ultraplan 高级规划模式 | P1 | 🟡 重要缺口 | ✅ 已完成 | `src/services/ultraplan/` 3454 行 + 13 测试 |
| F-84 | Context Collapse 上下文折叠 | P1 | 🟡 重要缺口 | ✅ 已完成 | `src/services/context_collapse/` 3366 行 + 14 测试 |
| F-85 | Templates 模板系统 | P1 | 🟡 重要缺口 | ✅ 已完成 | `src/services/templates/` 2076 行 + 11 测试 |
| F-86 | Kairos/Brief 调度模式 | P2 | 🟢 增强体验 | ✅ 已完成 | `src/services/kairos/` + `periodic/` 2022 行 + 13 测试 |
| F-87 | Workflow Scripts 工作流脚本 | P2 | 🟢 增强体验 | ⏳ 待开始 | YAML/JSON 多步工作流；预计 2 周 |
| F-88 | Explore/Plan 内置 Agent | P2 | 🟢 增强体验 | ✅ 已完成 | `src/agent/routing.py` + `report_store.py`；17 新单测 |
| F-90 | Hermes Gateway 参考实现 | P2 | 🟢 参考实现 | ✅ 已完成 | `extensions/remote_api/` 11 模块 2597 行 |

---

## 九、Python 生态特性补缺

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-68 | Feature Gate 运行时特性开关 | P1 | ⏳ 待开始 | 6 子特性 P68-A~F；预计 1-2 周 |
| F-69 | Budget/Poor Mode 节俭模式 | P1 | 🟡 部分完成 | `clawcodex_ext/query/token_budget.py` 159 行 BudgetTracker 已实现；Agent 循环集成待补 |
| F-70 | Plugin 插件系统 | P1 | 🟡 部分完成 | `src/plugins/` 注册表/加载器/依赖/校验/市场等基础框架已存在 |
| F-71 | 内置工具补齐 | P1 | 🟡 部分完成 | SnipTool 已完成 (282 行)；3 工具待实现 |
| F-72 | Multi-API 原生适配器 | P1 | ⏳ 待开始 | OpenAI/Gemini/Grok 原生适配器；预计 2 周 |
| F-73 | CI/CD 质量门禁与发布流水线 | P0 | ✅ 本地完成 / 🟡 远端待验证 | GitCode workflow + local CI + pre-commit + pytest + mypy |
| F-74 | Sandbox/SSH Remote 沙箱远程执行 | P2 | ⏳ 待开始 | Docker/SSH 沙箱执行；预计 2 周 |

---

## 十、Multi-Session 可视化分析平台

| ID | 特性 | 优先级 | 状态 | 备注 |
|----|------|:------:|:----:|------|
| F-91 | Visualizer 核心数据管道 | P0 | ✅ 已完成 | 5 模型 / 4 解析器 / 7 构建器 |
| F-92 | Visualizer 后端 API + WebSocket | P0 | ✅ 已完成 | 15 REST 端点 + WebSocket live tail |
| F-93 | Visualizer 前端 (Jinja2 + ECharts) | P0 | ✅ 已完成 | 甘特图三模式 / 搜索 / 异常面板 / 对比页面 |
| F-94 | Visualizer CLI + workspace 扫描 | P0 | ✅ 已完成 | `clawcodex viz` 子命令 + workspaces.json |
| F-95 | Visualizer + Orchestrator 协同 | P0 | ✅ 已完成 | F-38/F-45/F-54 链接 + 7 天 TTL 持久化 |
| F-96 | State Journal 与 Orchestrator 看板 | P0 | ✅ 已完成 | 实时看板接入 |

---

## 十一、遥测系统

| ID | 特性 | 优先级 | 期次 | 状态 | 备注 |
|----|------|:------:|:----:|:----:|------|
| F-97 | 独立遥测系统 (Issue-based) | P1 | — | ✅ 已完成 | 本地聚合 + CLI telemetry 命令 + Issue 上报 |
| F-97 | 第一期 (A~I) | P1 | 1 | ✅ 已完成 | 基础埋点 + 本地聚合 + Issue 上报 |
| F-97 | 第二期 (J/K/L) | P1 | 2 | ✅ 已完成 | 7 入口覆盖 + 报告增强 |

---

## 十二、其他已归档特性

| ID | 特性 | 状态 | 备注 |
|----|------|:----:|------|
| F-14 | 三层解耦架构 (Layer Isolation) | ✅ 已完成 | upstream/capabilities/features 三层分离 |
| F-15 | 权限模式切换 (Shift+Tab) | ✅ 已完成 | REPL/LiveStatus/TUI 循环切换 |
| F-17 | 工具系统按需加载 | ✅ 已完成 | 4 种工具模式 (bare/default/clawcodex/all) |
| F-19 | SOP 转化模式 | ✅ 已完成 | 三层映射 (SOP→Skill→Tool) |
| F-21 | 后台运行 + 恢复同步 | ✅ 已完成 | Ctrl+B 后台化 + TailFollower + SessionWatcher |
| F-23 | Bridge Phase 8-11 | ✅ 已完成 | 多会话桥接器完整实现 |
| F-24 | Agent Loop Consolidation | ✅ 已完成 | 删除 agent_loop.py (537 行) |
| F-25 | Advisor Token 计数 | ✅ 已完成 | max_history 100→2000 |
| F-26 | Away-Summary 离开摘要 | ✅ 已完成 | `clawcodex_ext/away_summary/` 10 文件完整实现 |
| F-27 | TUI 响应性修复 | ✅ 已完成 | StreamWatchdog 超时 + Ctrl+C 优先取消 |
| F-28 | Ctrl+B + `--resume` | ✅ 已完成 | Fork-Continue 模式 |
| F-29 | TaskInspect/TaskDirectives 工具注册 | ✅ 已完成 | Manager Agent 查询/指令 Worker |
| F-30 | ProgressReportTool 工具注册 | ✅ 已完成 | Agent 阶段性进度汇报 |
| F-31 | TUI 权限模式选择器 | ✅ 已完成 | 模态对话框 5 种权限模式 |
| F-32 | 会话恢复浏览器 | ✅ 已完成 | 模糊搜索 + 实时过滤 |
| F-89 | @agent-name 多入口统一支持 | ✅ 已完成 | `--agent <name>` CLI 标志 + `.claude/agents/<name>.md` 自动发现 |
| F-90 | Hermes Gateway 参考实现 | ✅ 已完成 | `extensions/remote_api/` 11 模块 2597 行 |

---

## 十三、开源替代组件

| ID | 组件 | 原始方案 | 替代方案 | 代码减少 | 优先级 | 状态 |
|----|------|---------|---------|:--------:|:------:|:----:|
| R-1 | 配置系统 | 手动 JSON 管理 (~220 行) | Pydantic-settings | ~220 行 | P0 | ✅ 已完成 |
| R-2 | Frontmatter 解析 | yaml.safe_load (~80 行) | python-frontmatter | ~80 行 | P1 | ✅ 已完成 |
| R-3 | Bash AST 解析器 | 自建 ~1,500 行 | tree-sitter-bash | ~1,400 行 | P0 | ✅ 已完成 |
| R-4 | Git 操作 | 6 个 subprocess.run() (~200 行) | GitPython | ~200 行 | P1 | ✅ 已完成 |
| R-5 | Hook 系统 | 自建 ~1,200 行 | Pluggy | ~1,000 行 | P1 | ✅ 已完成 |
| R-6 | 结构化输出 | json.loads + 手动验证 (~200 行) | Outlines | ~200 行 | P1 | ✅ 已完成 |
| R-7 | Provider 层 | 多个 Provider 类 (~1,630 行) | LiteLLM | ~1,430 行 | P0 | ✅ 已完成 |
| R-8 | 工具语义搜索 | 手动实现 (~100 行) | Qdrant | ~100 行 | P2 | ⏳ 待开始 |
| R-9 | 权限规则引擎 | 手动实现 (~150 行) | Casbin | ~150 行 | P2 | ⏳ 待开始 |
| R-10 | 日志系统 | print/logging | structlog | — | P2 | ⏳ 待开始 |

**已减少代码**: ~4,530 行
**预计全部完成减少**: ~4,530+ 行

---

## 十四、版本发布里程碑

| 里程碑 | 预计时间 | 主要交付物 | 状态 |
|--------|---------|-----------|:----:|
| **v0.1 核心引擎** | 已完成 | Orchestrator 基础、Agent 核心、CLI 架构 | ✅ 已完成 |
| **v0.2 系统增强** | 已完成 | Cron 系统、会话恢复、Bridge 桥接 | ✅ 已完成 |
| **v0.3 可观测性** | 已完成 | Validator 验证闭环、审计旁路、报告系统 | ✅ 已完成 |
| **v0.4 平台扩展** | 已完成 | CCB 对标完成 10/15、Cron 完成、Visualizer 完成 | ✅ 已完成 |
| **v0.5 CI/CD 就绪** | 完成 90% | 本地门禁全部就绪；远端 Pipeline/CodeCheck/Release/PyPI 待仓库能力开通 | 🟡 进行中 |
| **v0.6 生态补缺** | 规划中 | F-68 Feature Gate / F-69 Budget Mode / F-72 Multi-API / F-70 Plugin 完整 | ⏳ 规划中 |
| **v0.7 远程控制** | 规划中 | F-82 Remote Control Server / F-66 ACP 协议 / F-81 Native 模块 | ⏳ 规划中 |
| **v1.0 生产可用** | 规划中 | 所有 P0/P1 特性完成；端到端稳定性门禁；发布流水线生产就绪 | ⏳ 规划中 |

---

## 十五、近期优先实施建议

```
第一优先级 (P0):
  F-48 Phase 7-9 (src/ 解耦剩余) ─── 持续降低上游同步成本
  F-22 R5/R7/R8 (Cron 剩余缺口) ─── 生产环境端到端完备

第二优先级 (P1):
  F-68 Feature Gate ─── F-70/F-102 基础依赖
  F-69 Budget Mode 深度集成 ─── Token 节约，用户体验
  F-70 Plugin 系统完善 ─── 发现/沙箱/生命周期
  F-72 Multi-API 适配器 ─── 减少 LiteLLM 单点依赖
  F-81 Native 模块 ─── 关键能缺失口
  F-82 Remote Control Server ─── 远程管理能力
  F-54 可观测性完善 ─── debug.ndjson → CLI 诊断字段

第三优先级 (P2+):
  F-66 ACP 协议 / F-87 Workflow Scripts / F-74 Sandbox / F-75 工具统计
  F-64 Voice Mode 运行时集成
  R-8/R-9/R-10 社区替代组件接入
```

---

## 附录：状态图例

| 图标 | 含义 |
|:----:|------|
| ✅ 已完成 | 代码全部落地，测试通过，功能可用 |
| 🟡 部分完成 | 核心逻辑已实现，部分子特性/集成待补 |
| 🔄 进行中 | 正在开发中 |
| 📋 设计完成 | 详细设计已完成，待进入开发 |
| 📋 规划中 | 需求已分析，设计待完成 |
| ⏳ 待开始 | 尚未启动 |
