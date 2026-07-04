# Architecture

Claw Codex 是 Claude Code 的 Python 移植版，并在其之上构建了自主工程层。
架构分为 **三层**：`src/`（核心）、`clawcodex_ext/`（插件扩展）、`extensions/`（功能子系统），
遵循 **expand-contract 迁移模式**——核心逻辑逐步从 `src/` 迁移到 `clawcodex_ext/`，
`src/` 中原模块逐渐退化为从 `clawcodex_ext/` 重导出的 facade 桥接。

> **迁移进展**：`src/query/transitions.py`、`src/hooks/hook_types.py`、`src/permissions/types.py`
> 等模块已成为 facade（仅 `from clawcodex_ext.xxx.yyy import *`），实际实现在 `clawcodex_ext/` 中。
> 更多模块将逐步采用此模式。

本文档映射每个抽象到其规范路径，使读者能从架构概念一步定位到源码。

关于子系统深度的内容，请参见 `docs/` 下的 F-N 特性计划
（`FEATURE_PLAN.md`、`PROGRESS.md`）。

---

## 三层架构总览

```
┌───────────────────────────────────────────────────────────────┐
│                    extensions/                                 │
│  功能子系统（Orchestrator、Visualizer、SOP Converter、Remote   │
│  API、Ports、Agents）独立部署，通过协议接口与核心层交互          │
├───────────────────────────────────────────────────────────────┤
│                   clawcodex_ext/                                │
│  插件扩展层（CLI、TUI、REPL、Providers、Bridge、Cron、         │
│  Community Radar、Away Summary 等）                              │
│  通过 import 桥接从 src/ 导入基类，扩展其功能                   │
├───────────────────────────────────────────────────────────────┤
│                      src/                                       │
│  核心层（Query Loop、Tool System、Hooks、Permissions、         │
│  Memory、State、Agent、Coordinator、Bootstrap、Settings 等）    │
│  零外部依赖的纯核心抽象                                         │
└───────────────────────────────────────────────────────────────┘
```

其中 `extensions/capabilities/` 定义了 Layer 1 ↔ Layer 2 之间的协议契约
（Protocol 类，仅声明签名，无实现），确保扩展层不直接依赖具体实现。

---

## 核心抽象

| # | 抽象 | Python 规范路径 | 关键入口符号 |
|---|---|---|---|
| 1 | **Query Loop** | `src/query/query.py` + `clawcodex_ext/query/` | `query()` — 异步生成器 `AsyncGenerator[Message \| StreamEvent, None]` |
| 2 | **Tool System** | `src/tool_system/build_tool.py` + `src/tool_system/tools/` (45+ tools) | `Tool` dataclass + `build_tool()` factory + `StreamingToolExecutor` |
| 3 | **Tasks** | `src/tool_system/tools/agent.py` + `src/tool_system/task_manager.py` | `TaskStatus` Literal; `AgentTool`; `TaskManager` |
| 4 | **State (two-tier)** | `src/bootstrap/state.py` (~60 fields) + `src/state/app_state.py` | `_BootstrapState` singleton; `AppState` + `create_app_state_store()` |
| 5 | **Memory** | `src/memdir/` (9 模块) | `find_relevant_memories()`, `memory_scan()` |
| 6 | **Hooks** | `src/hooks/` (facade) → `clawcodex_ext/hooks/hook_types.py` (28 events) | `HookEvent` Literal (`clawcodex_ext/hooks/hook_types.py:23-66`) |

### 迁移状态（Expand-Contract）

以下 `src/` 模块已变为 facade，实际实现位于 `clawcodex_ext/`：

| src/ facade | 实际实现 |
|-------------|---------|
| `src/query/transitions.py` | `clawcodex_ext/query/transitions.py` |
| `src/hooks/hook_types.py` | `clawcodex_ext/hooks/hook_types.py` |
| `src/permissions/types.py` | `clawcodex_ext/permissions/types.py` |
| `src/permissions/cycle.py` | `clawcodex_ext/permissions/cycle.py` |

更多模块正在按计划迁移中。

---

## 黄金路径（Golden Path）

用户输入按固定顺序流经系统。每个箭头对应一个可追踪的函数调用。

### 入口选择

```
1. clawcodex_ext/cli/main.py:main                 # pyproject.toml console_scripts 入口
2. clawcodex_ext/cli/dispatch.py:dispatch         # 子命令路由（orchestrator / provider / model / tui / repl / headless）
3. clawcodex_ext/cli/parser.py:create_parser      # 参数解析
4.   ├─ clawcodex_ext/entrypoints/tui.py          # Textual TUI（默认）
5.   ├─ clawcodex_ext/entrypoints/headless.py     # Headless 模式
6.   ├─ clawcodex_ext/entrypoints/orchestrator.py # Orchestrator 守护进程
7.   └─ src/entrypoints/                          # 核心入口点（daemon, doctor, mcp）
```

### 交互循环（REPL / TUI）

```
8.  clawcodex_ext/repl/core.py:ClawcodexREPL.run  # prompt-toolkit REPL 主循环
9.  clawcodex_ext/frontend/repl.py:run_repl        # 前端注册 + 启动
10. src/query/engine.py:QueryEngine                # 会话级查询编排器
11. src/query/engine.py:QueryEngine.submit_message # 用户消息提交
12. src/query/query.py:query                       # 异步生成器——心跳
13. ↓ src/providers/ 中的 provider 调用             # 流式模型响应
14. ↓ src/services/tool_execution/streaming_executor.py
15.    StreamingToolExecutor 在模型完成前启动并发安全工具
       （推测执行；匹配原书 §"Tool execution overlaps with model streaming"）
16. 生成 Message | StreamEvent 返回给 ClawcodexREPL
17. 终端输出 via Rich + prompt-toolkit / Textual
```

### Terminal 判别联合（PEP 525 注意事项）

Python 异步生成器 **不能返回值**（PEP 525）。TS 参考里的带类型 `Terminal`
返回值在 Python 中通过 out-parameter 模式保留：调用者将
`clawcodex_ext/query/transitions.py:TerminalHolder` 传入 `query()`，
内循环在 `return` 前设置 `holder.value` 为 `Terminal(reason=...)`。
详见 `clawcodex_ext/query/transitions.py:50-83`。

`TerminalReason` 是一个包含 10 个值的 `Literal[...]`：
`blocking_limit`、`image_error`、`model_error`、`aborted_streaming`、
`prompt_too_long`、`completed`、`stop_hook_prevented`、`aborted_tools`、
`hook_stopped`、`max_turns`。

`ContinueReason` 包含 8 个值：`next_turn`、`max_output_tokens_recovery`、
`max_output_tokens_escalate`、`reactive_compact_retry`、`collapse_drain_retry`、
`stop_hook_blocking`、`token_budget_continuation`、`continuation_nudge`。

---

## 权限系统（Permission System）

Claw Codex 实现了与 Claude Code 相同的 7 种权限模式：

| 模式 | 行为 | 外部暴露？ |
|------|------|-----------|
| `bypassPermissions` | 全部允许，无提示，不记录。内部/测试用。 | 是 |
| `dontAsk` | 全部允许，记录。无用户提示。 | 是 |
| `auto` | 转录分类器（LLM）决定允许/拒绝。 | 否（内部） |
| `acceptEdits` | 文件编辑自动批准；其他变更需提示。 | 是 |
| `default` | 标准交互模式。用户批准每个操作。 | 是 |
| `plan` | 只读。所有变更被阻止。 | 是 |
| `bubble` | 向上级代理升级决策（子代理模式）。 | 否（内部） |

定义位于 `clawcodex_ext/permissions/types.py`（`src/permissions/types.py` 为 facade）。
解析链（hook 规则 → `tool.check_permissions` → 基于模式的决策）在
`src/permissions/check.py` 中实现，模式循环辅助在 `clawcodex_ext/permissions/cycle.py` 中。

Bash 安全解析：`src/permissions/bash_parser/`（AST 节点、解析器、命令分类），
`src/permissions/bash_security.py`、`src/permissions/dangerous_safety.py`。

---

## Hooks

Claw Codex 定义了 28 个 HookEvent（`clawcodex_ext/hooks/hook_types.py:23-66`），
采用 Chapter-12 Phase-1 分类法（不同于 TS 参考的 27 事件 + PostSampling）：

| 类别 | 事件 |
|------|------|
| Tool lifecycle | `PreToolUse`, `PostToolUse`, `PostToolUseFailure` |
| Permission | `PermissionDenied`, `PermissionRequest` |
| Session | `SessionStart`, `SessionEnd`, `Setup` |
| Subagent | `SubagentStart`, `SubagentStop` |
| Stop / continuation | `Stop`, `StopFailure` |
| Compaction | `PreCompact`, `PostCompact` |
| User input | `UserPromptSubmit` |
| Sampling | `PostSampling` |
| Configuration | `ConfigChange`, `InstructionsLoaded`, `CwdChanged`, `FileChanged` |
| Workspace | `WorktreeCreate`, `WorktreeRemove` |
| Task lifecycle | `TaskCreated`, `TaskCompleted`, `TeammateIdle` |
| Elicitation (MCP) | `Elicitation`, `ElicitationResult` |

执行器：`exec_prompt_hook.py`、`exec_agent_hook.py`、`exec_http_hook.py`；
shell hook 流程被归入 bash 工具路径。

模块列表：
- `src/hooks/` — 核心 hook 定义（facade）、注册表、执行器、SSRF 防护、信任门
- `clawcodex_ext/hooks/` — 实际 hook 实现（`hook_types.py`, `config_manager.py` 等）
- `extensions/orchestrator/` — orchestrator 的 hook 集成

---

## Memory

三个层级，与原书章节一致：

1. **项目级** — 仓库中的 `CLAUDE.md` 文件（由 `src/memdir/memory_scan.py` 加载）
2. **用户级** — `~/.claude/MEMORY.md`（由 `src/memdir/paths.py` 加载）
3. **团队级** — 通过符号链接共享。`src/memdir/team_mem_paths.py` + `team_mem_prompts.py`

相关性选择由 LLM 驱动，通过 `src/memdir/find_relevant_memories.py`。
扩展层在 `clawcodex_ext/memory/` 中提供范围感知提示。

---

## Provider 层（多供应商）

原书描述 TS Claude Code 的多云路由：一家供应商（Anthropic）跨四个云
（Direct API、AWS Bedrock、Google Vertex AI、Azure Foundry），
对循环透明，通过 `getAnthropicClient()` 实现。

**Claw Codex 使用不同的路由。** Python 的 `get_provider_class()` 工厂位于
`src/providers/__init__.py`，在多个**供应商**之间选择：

| 供应商 | 文件 | 说明 |
|--------|------|------|
| Anthropic | `src/providers/anthropic_provider.py` | Direct API |
| OpenAI | `src/providers/openai_provider.py` | OpenAI API |
| OpenAI Codex | `src/providers/openai_codex_provider.py` | OpenAI Codex API |
| OpenRouter | `src/providers/openrouter_provider.py` | 多供应商代理 |
| DeepSeek | `src/providers/deepseek_provider.py` | DeepSeek API |
| GLM (Zhipu) | `src/providers/glm_provider.py` | 智谱 API |
| MiniMax | `src/providers/minimax_provider.py` | MiniMax API |
| Google | `src/providers/gemini_provider.py` | Google AI API |
| Bedrock | `src/providers/bedrock.py` | AWS Bedrock |
| LiteLLM | `src/providers/_litellm_adapter.py` | LiteLLM 转接层 |
| OpenAI Compatible | `src/providers/openai_compatible.py` | 通用 OpenAI 兼容 |

所有供应商实现 `src/providers/base.py:BaseProvider` 协议。
扩展层在 `clawcodex_ext/providers/` 和 `extensions/providers_ext/` 中提供额外能力。
`src/providers/native/` 包含原生运行时的 provider 支持。

---

## 前端层（Frontend）

TUI 和 REPL 通过 `clawcodex_ext/frontend/` 中的前端注册表管理：

| 前端 | 文件 | 后端 |
|------|------|------|
| Textual TUI | `clawcodex_ext/tui/` (18+ 模块 + 18 screens) + `clawcodex_ext/frontend/tui.py` | Textual |
| prompt-toolkit REPL | `clawcodex_ext/repl/` (9 模块) + `clawcodex_ext/frontend/repl.py` | prompt-toolkit |
| Headless | `clawcodex_ext/frontend/headless.py` + `src/entrypoints/headless.py` | 标准输入/输出 |

TUI 屏幕（`clawcodex_ext/tui/screens/`，18 屏幕）：
ask_user_question、cost_threshold、dialog_base、diff_dialog、doctor、effort_picker、
exit_flow、history_search、idle_return、mcp_dialogs、message_selector、model_picker、
permission_modal、permission_mode_picker、repl、resume_conversation、theme_picker。

REPL 核心（`clawcodex_ext/repl/`）：app.py、background_escape.py、color_scheme.py、
core.py、live_status.py、session_browser.py、ui_host.py。

---

## 第三方扩展子系统

### Orchestrator（`extensions/orchestrator/`）

自主工单处理守护进程——Claw Codex 的核心自主工程层。

```
extensions/orchestrator/
├── orchestrator.py           # Orchestrator 主类——ProgressReporter、WorkflowEngine
├── agent_runner.py           # Agent 运行器——_build_run_id、_post_summary_placeholder
├── git_sync.py               # GitSyncService——完整流水线：clone → agent → verification → PR
├── report_writer.py          # 报告写入——双写入（本地 + 摘要评论）
├── issue.py                  # 工单模型
├── issue_registry.py         # IssueRecord、IssueStatus、持久化
├── issue_state_cache.py      # 工单状态缓存
├── state_journal.py          # 状态日志
├── state_journal_sink.py     # 状态日志接收器
├── workflow.py               # WorkflowEngine——工单生命周期管理
├── workflow_store.py         # Workflow 持久化
├── workspace.py              # 工作区管理
├── workspace_locator.py      # 工作区定位
├── tracker.py               # TrackerAdapter 抽象基类
├── progress_reporter.py      # 进度报告器
├── progress_sink.py          # 进度接收器接口
├── prompt_builder.py         # 提示构建器
├── review_feedback.py        # PR 审查反馈处理
├── status_dashboard.py       # 状态仪表板
├── tool_event_log.py         # 工具事件日志
├── control_socket.py         # 控制套接字
├── approval_policy.py        # 审批策略
├── clarification.py          # 澄清请求
├── clarification_queue.py    # 澄清请求队列
├── debug_log.py              # 调试日志
├── config/schema.py          # 配置模式（AgentConfig、HooksConfig）
├── cli/                      # CLI 命令：attach、dashboard、issue、resume_session、server、takeover、workflow
├── local_tracker/            # LocalTrackerAdapter（文件系统）
├── repo_tracker/             # RepositoryIssueClient（GitHub/Gitee/GitCode）
├── linear/                   # LinearGraphQL adapter
└── templates/                # 模板：issue-card、workflow、workflow-local
```

关键特性（F-N 索引跟踪，见 `docs/PROGRESS.md`）：
- **F-37** PR 审查自动修复
- **F-38** 验证 + 报告 + PR gate（test_command、build_command、lint_command、pre_commit、pre_push、post_sync hooks）
- **F-39** 工单重跑标签（`agent:retry`、`agent:follow-up`、`agent:blocked`）+ 评论命令

### Visualizer（`extensions/visualizer/`）

会话可视化 Web 服务。`server.py` + `ws.py` WebSocket 后端，
`builders/` 中的构建器（timeline、gantt、agent_tree、stats、comparison、anomaly、multi_session_view、export），
`parsers/` 中的解析器（session、transcript、tool_events、multi_agent、orchestrator_state），
`static/` 中的静态资源（CSS + JS），`templates/` 中的 Jinja2 模板。
还包含 `cli.py`（CLI 入口）、`import_router.py`（导入路由）和 `orchestrator_link.py`（Orchestrator 集成）。

### SOP Converter（`extensions/sop_converter/`）

将 SOP（过程化编排规范）`workflow.md` 转换为协调的多代理系统。
`sdk_parser.py`、`agent_builder.py`、`agent_md_writer.py`、`convert_pos_skill.py`、
`skill_grouper.py`、`source_parser.py`、`templates.py`、`default_agent.py`。

### Remote API（`extensions/remote_api/`）

远程 HTTP API 服务，支持 SSE Server-Sent Events 流式输出。
`server.py`、`core.py`、`runner.py`、`sse.py`、`normalization.py`、
`auth.py`、`cli.py`、`errors.py`、`state.py`、`stdlib_server.py`。

### Ports（`extensions/ports/`）

桥接端口层，提供多会话远程运行时桥接的替代实现：

```
extensions/ports/
├── bridge/                    # 桥接端口（4 模块）
│   ├── bridge_main.py         # 主桥接入口
│   ├── remote_bridge_core.py  # 远程桥接核心
│   ├── repl_bridge.py         # REPL 桥接
│   └── session_runner.py      # 会话运行器
└── transports/                # 传输层（3 模块）
    ├── hybrid_v1.py           # 混合传输 v1
    ├── serial_uploader.py     # 串行上传器
    └── websocket_v1.py        # WebSocket 传输 v1
```

### 其他扩展

| 子系统 | 路径 | 说明 |
|--------|------|------|
| API | `extensions/api/` | 查询中间件、编排 API |
| Agent | `extensions/agent/` | 代理持久化扩展 |
| Capabilities | `extensions/capabilities/` | 协议定义（adapter、agent、context、event、headless、provider、tool） |
| Permissions | `extensions/permissions/` | 文件权限读取器 |
| Providers Ext | `extensions/providers_ext/` | LiteLLM provider |
| Skills Ext | `extensions/skills_ext/` | 技能缓存、注册表扩展、hooks 集成 |
| Tool System Ext | `extensions/tool_system_ext/` | 工具注册表扩展、团队过滤 |

---

## Agent 系统

### 核心（`src/agent/`）

22 个模块：代理定义、运行器、会话管理、透明度、子代理上下文、
前台提升、后台运行器、_outlines_adapter、提示模板、对话、MCP 过滤器、
报告存储、代理加载。

### 扩展（`clawcodex_ext/agent/`）

工具创作（`tool_authoring/`）：bash/http/python 调用处理器的注册表工厂、
规范验证器、持久化。
后台运行器和状态、会话扩展、`auto_mode_runner`、`chain_filter`、`policy`、
`registry`、`markdown_discovery`、`_bundled_agents/`（code_reviewer、docs_writer、test_runner）。

### 协调器（`src/coordinator/`）

多代理管理：`mode.py`、`prompt.py`、`worker_agent.py`。

### Swarm（`src/services/swarm/`）

10 个模块：团队文件、成员资格、队友、邮箱、轮询器、
权限、领导者权限桥、代理名称注册表、助手。

---

## Bridge Daemon（`src/bridge/`）

37 个模块用于多会话远程运行时桥接：
`bridge_main.py`、`bridge_api.py`、`repl_bridge.py`、`remote_bridge_core.py`、
`code_session_api.py`、`messaging.py`、`messaging_handlers.py`、`session_runner.py`、
JWT 工具、信任设备、容量唤醒、WebSocket 传输、flush_gate、worktree、
双向 UUID 集、桥接配置、出入站消息、轮询配置、SDK 类型等。

---

## 其他关键子系统

| 子系统 | 路径 | 说明 |
|--------|------|------|
| Cron 系统 | `clawcodex_ext/cron_system/`（13 模块） | 分布式锁调度，带 jitter 和 NDJSON 运行历史 |
| LiteLLM | `extensions/providers_ext/litellm_provider.py` | 100+ LLM 后端的统一接口 |
| 桥接服务 | `clawcodex_ext/services/bridge/` | 桥接 API、状态工具、会话 API |
| Cron 集成 | `clawcodex_ext/cron_system/` | scheduler、runtime、tasks、lock |
| 设置 | `src/settings/`（8 模块） + `clawcodex_ext/settings/`（4 模块） | 设置管理、变更检测、验证 |
| 状态 | `src/state/`（3 模块）+ `clawcodex_ext/state/`（3 模块） | 应用级状态（app_state、cache_state、session_start） |
| 命令系统 | `src/command_system/`（20 模块）+ `clawcodex_ext/command_system/` | 斜杠命令：内置命令、effort、export、model、permissions、theme 等 |
| 上下文系统 | `src/context_system/`（12 模块）+ `clawcodex_ext/context_system/` | 提示组装、GitPython 适配器、系统提示缓存 |
| Memory 扩展 | `clawcodex_ext/memory/` | 范围感知提示 |
| Skills 扩展 | `clawcodex_ext/skills/` + `extensions/skills_ext/` | 技能注册表、缓存、捆绑包 |
| 工具系统扩展 | `clawcodex_ext/tool_system/` + `extensions/tool_system_ext/` | 工具注册表扩展、代理配置 |
| Buddy | `src/buddy/`（9 模块）+ `clawcodex_ext/buddy/` | 语音伴侣（companion、soul、sprites、types、notification、observer） |
| Auth | `src/auth/`（7 模块）+ `clawcodex_ext/auth/` | OAuth、API 密钥、Gemini、Claude AI |
| Away Summary | `clawcodex_ext/away_summary/`（9 模块） | 离开摘要服务（config、controller、fingerprint、prompt、registration 等） |
| Community Radar | `clawcodex_ext/community_radar/`（15+ 模块） | 社区动态监控（fetcher、classifier、scorer、reporter、pipeline 等） |
| Dreaming | `clawcodex_ext/dreaming/`（7 模块） | 梦境模式（config、cron_integration、lock、runner、service 等） |
| Goal | `clawcodex_ext/goal/`（8 模块） | 目标管理（state_machine、storage、registry、types 等） |
| Runtime | `clawcodex_ext/runtime/`（2 模块） | 运行时上下文、观察者 |
| Bootstrap | `src/bootstrap/state.py` | 进程级全局状态（DAG 叶子节点） |
| Compact | `src/services/compact/`（2 模块）+ `clawcodex_ext/compact_service/` | 上下文压缩：自动压缩、反应式 |
| Context Collapse | `src/services/context_collapse/`（8 模块） | 上下文折叠管理（boundary、engine、persistence、summary 等） |
| Channels | `src/services/channels/`（9 模块） | 多通道通知（slack、discord、feishu 等） |
| Computer Use | `src/services/computer_use/`（6 模块） | 计算机使用（base、dry_run、platform adapters） |
| Chrome | `src/services/chrome/`（8 模块） | Chrome 集成（mcp_impl、playwright_impl、recording 等） |
| Kairos | `src/services/kairos/`（6 模块） | 时间感知服务 |
| Langfuse | `src/services/langfuse/`（4 模块） | Langfuse 可观测性集成 |
| Periodic | `src/services/periodic/`（1 模块） | 周期性任务调度器 |
| Pipe IPC | `src/services/pipe_ipc/`（6 模块） | 进程间通信（codec、registry、uds 等） |
| Ultraplan | `src/services/ultraplan/`（1 模块） | 超长计划支持 |
| 工具执行 | `src/services/tool_execution/`（6 模块） | StreamingToolExecutor、编排器、工具 hook、结果持久化 |
| 语音 | `src/services/voice/` + `src/voice/` | 语音检测、STT |
| IDE | `src/services/ide/` | IDE 连接、诊断、选择 |
| 分析 | `src/services/analytics/` | 事件、元数据、接收器 |
| API | `src/services/api/` | Claude API 客户端、错误、重试、工具归一化 |
| OAuth | `src/services/oauth/` | OAuth 客户端 |
| MCP | `clawcodex_ext/services/mcp/` | 模型上下文协议工具绑定 |
| 工具系统 | `src/tool_system/`（15+ 模块） | 构建工具、上下文、默认值、错误、加载器、协议、注册表等 |
| 传输 | `src/transports/`（8 模块） | 传输层（CCR、hybrid、websocket、SSE 等） |
| 插件 | `src/plugins/`（9 模块） | 插件系统（loader、marketplace、type validator 等） |
| 上行代理 | `src/upstreamproxy/`（5 模块） | 上行代理（ca_bundle、relay、ptrace_guard 等） |
| Types | `src/types/`（3 模块）+ `clawcodex_ext/types/`（2 模块） | 核心类型：content_blocks、messages、stream_events |
| Utils | `src/utils/`（37 模块）+ `clawcodex_ext/utils/`（11 模块） | 工具函数（git、export、image、markdown、file 等） |
| REPL | `src/repl/`（7 模块） | REPL 核心（互补 `clawcodex_ext/repl/`） |
| TUI | `src/tui/`（18+ 模块）+ `clawcodex_ext/tui/`（18+ 模块） | Textual TUI 实现 |
| Server | `src/server/`（7 模块） | 服务端连接管理（direct_connect、session_index、url_scheme 等） |
| Remote | `src/remote/`（3 模块）+ `clawcodex_ext/remote/`（2 模块） | 远程会话管理、WebSocket 桥接 |
| Keybindings | `src/keybindings/` | 键盘绑定 |
| Output Styles | `src/outputStyles/` | 输出样式管理 |
| Skills | `src/skills/`（10 模块） | 技能系统（loader、bundled、mcp、frontmatter 等） |
| Tasks | `src/tasks/`（8 模块） | 任务系统（dream、eviction、progress、local_agent/shell 等） |
| Assistant | `src/assistant/`（3 模块） | 会话辅助（session_chooser、session_history） |
| Config | `src/config.py` | 全局配置加载 |
| Cost | `src/costHook.py` + `src/cost_tracker.py` | 成本追踪 |
| Deferred Init | `src/deferred_init.py` | 延迟初始化 |

---

## 审计脚手架（Audit-only Scaffolding）

TS↔Python 一致性报告 CLI 位于 `scripts/audit/`。通过 `python -m scripts.audit.main <sub>` 运行
（由 `tests/test_porting_workspace.py` 执行）；生产环境的 `clawcodex`
控制台脚本从不触及它。

21 个审计模块：architecture_stats、bootstrap_graph、command_graph、commands、context、
direct_modes、execution_registry、legacy_cli_repl、main、parity_audit、port_manifest、
query_engine、remote_runtime、runtime、session_store、setup、system_init、tool_pool、tools、transcript。

---

## 测试

| 类别 | 路径 | 说明 |
|------|------|------|
| 稳定性门禁 | `tests/stability_gate/`（7 阶段） | 每次 vibe coding 提交前必须通过 |
| Orchestrator 测试 | `tests/orchestrator/`（20+ 测试文件） | git_sync、tracker、agent_runner、dashboard、workspace、F-39、F-42、F-45、F-49 等 |
| F-38 E2E | `tests/orchestrator/manual_e2e_f38.py` | 4 轮端到端验证 + PR |
| 通用测试 | `tests/` | 各子系统单元测试 |

### 稳定性门禁层次

| 阶段 | 覆盖范围 | 典型耗时 |
|------|---------|---------|
| Stage 1 | 16 个核心模块导入 | ~4s |
| Stage 2 | CLI `--help` / `--version` / 子命令烟雾测试 | ~9s |
| Stage 3 | REPL + Headless 构造测试 + 韧性测试 | ~4s |
| Stage 3b | REPL 韧性测试 | ~2s |
| Stage 3c | CLI 韧性测试 | ~2s |
| Stage 3d | /model + /provider 运行时命令 | ~2s |
| Stage 3e | REPL 配色渲染 | ~2s |
| Stage 4 | Agent/Conversation 序列化/反序列化 | ~2s |
| Stage 5 | 21 个 clawcodex_ext 扩展模块 | ~3s |
| Stage 6 | 性能回归检测 | ~11s |
| Stage 7 | root shadow 检测 + popup dispatch | ~3s |
| Stage 8 | 输入流测试 | ~2s |
| Stage 9 | Provider 边界测试 | ~2s |

---

## 架构指南

1. **DAG 叶子节点**：`src/bootstrap/state.py` 不得导入任何功能子系统包。
   由 `.importlinter` / `pyproject.toml` 中的 import-linter 约束强制执行。

2. **Expand-contract 迁移**：`clawcodex_ext/` 中的模块从 `src/` 导入基类并扩展；
   最终 `src/` 中的模块被替换为从 `clawcodex_ext/` 重导出的 facade 桥接。
   已迁移：`query/transitions`、`hooks/hook_types`、`permissions/types`、`permissions/cycle`。

3. **单例 ProgressReporter**：`Orchestrator` 上为单实例——`_current_task_id`
   和 `_phase_count` 是可变的，非线程安全。并发工单运行会产生竞争。
   F-39 / F-37 可能需要重构为 `sinks: list[ProgressSink]`。

4. **TrackerAdapter 设计**：`TrackerAdapter.update_pull_request` / `update_comment`
   不是 `@abstractmethod`——默认返回 `None`，确保 `LocalTrackerAdapter`
   不需要覆盖它们。这是有意设计的向后兼容性。

5. **LocalTracker 行为**：触发 `git_sync.sync()` 时 `no_push=True`，
   因此 `result.pushed == False` 且 `result.pending_review == True` 是设计行为，
   而非失败。生产环境使用 GitHub/GitCode 时 `pushed == True`。

6. **Capabilities Protocol**：`extensions/capabilities/` 中的 Protocol 类作为
   Layer 1 → Layer 2 的接口边界，允许三方扩展不依赖具体实现。
   现有协议：adapter、agent、context、event、headless、provider、tool。

7. **分层次的扩展注册模式**：新功能优先通过注册模式添加
   （`registry.register()`、`hook.add()`、`@register` 装饰器），
   其次才是猴补丁或直接修改 `src/`。
