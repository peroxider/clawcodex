# Architecture

Claw Codex 是 Claude Code 的 Python 移植版，并在其上构建了自主工程层。
架构分为 **三层**：`src/`（核心）、`clawcodex_ext/`（插件扩展）、`extensions/`（功能子系统），
遵循 **expand-contract 迁移模式**——核心代码逐步从 `src/` 迁移到 `clawcodex_ext/`，
旧路径通过 `clawcodex_ext/` 的子模块重新导出（见 `src/clawcodex_ext_bridge.py`）。

本文档映射每个抽象到其规范路径，使读者能从架构概念一步定位到源码。

关于子系统深度的内容，请参见 `docs/` 下的 F-N 特性计划
（`FEATURE_PLAN.md`、`PROGRESS.md`）。

---

## 三层架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    extensions/                          │
│  功能子系统（Orchestrator、Visualizer、POS Converter）   │
│  独立部署，通过协议接口与核心层交互                       │
├─────────────────────────────────────────────────────────┤
│                   clawcodex_ext/                         │
│  插件扩展层（CLI、TUI、REPL、Providers、Bridge 等）      │
│  通过 import 桥接从 src/ 导入基类，扩展其功能             │
├─────────────────────────────────────────────────────────┤
│                      src/                                │
│  核心层（Query Loop、Tool System、Hooks、Permissions、   │
│  Memory、State、Agent、Coordinator 等）                   │
│  零外部依赖的纯核心抽象                                   │
└─────────────────────────────────────────────────────────┘
```

---

## 六大核心抽象

| # | 抽象 | TypeScript 参考 | Python 规范路径 | 关键入口符号 |
|---|---|---|---|---|
| 1 | **Query Loop** | `typescript/src/query.ts` (~1,919 LOC) | `src/query/query.py` (1,522 LOC) | `query()` — `async def query(params, *, terminal_holder=None) -> AsyncGenerator[Message \| StreamEvent, None]` |
| 2 | **Tool System** | `typescript/src/Tool.ts` + `typescript/src/tools.ts` + `typescript/src/services/tools/` | `src/tool_system/build_tool.py` + `src/tool_system/tools/` (45+ tools) | `Tool` dataclass + `build_tool()` factory + `StreamingToolExecutor` |
| 3 | **Tasks** | `typescript/src/Task.ts` + `typescript/src/tasks/` + `typescript/src/tools/AgentTool/` | `src/tool_system/tools/agent.py` + `src/tool_system/tasks_v2.py` | `TaskStatus` Literal; `AgentTool`; `TaskManager` |
| 4 | **State (two-tier)** | `typescript/src/bootstrap/state.ts` (96 fields) + `typescript/src/state/AppStateStore.ts` | `src/bootstrap/state.py` (~60 fields) + `src/state/app_state.py` | `_BootstrapState` singleton; `AppState` + `create_app_state_store()` |
| 5 | **Memory** | `typescript/src/memdir/` (8 files incl. team) | `src/memdir/` (8 modules + `__init__.py`) | `find_relevant_memories()`, `memory_scan()` |
| 6 | **Hooks** | `typescript/src/hooks/` + `typescript/src/utils/hooks/`; 27 events | `src/hooks/` (15 modules + `sources/`); 28 events (27 TS + `PostSampling`) | `HookEvent` Literal at `src/hooks/hook_types.py:23` |

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
`src/query/transitions.py:TerminalHolder` 传入 `query()`，
内循环在 `return` 前设置 `holder.value` 为 `Terminal(reason=...)`。
详见 `src/query/transitions.py:50-83`。

`TerminalReason` 是一个包含 10 个值的 `Literal[...]`
（`src/query/transitions.py:22-33`）：`blocking_limit`、`image_error`、
`model_error`、`aborted_streaming`、`prompt_too_long`、`completed`、
`stop_hook_prevented`、`aborted_tools`、`hook_stopped`、`max_turns`。

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

定义位于 `src/permissions/types.py:13-47`。解析链
（hook 规则 → `tool.check_permissions` → 基于模式的决策）在
`src/permissions/check.py` 中实现，模式循环辅助在 `src/permissions/cycle.py` 中。
扩展层在 `clawcodex_ext/permissions/cycle.py` 中提供额外能力。

Bash 安全解析：`src/permissions/bash_parser/`（AST 节点、解析器、命令分类），
`src/permissions/bash_security.py`、`src/permissions/dangerous_safety.py`。

---

## Hooks

TS 参考定义了 27 个生命周期事件；Python 实现定义了 28 个
（`src/hooks/hook_types.py:23`）——27 个 TS 事件加上额外的 `PostSampling`。
4 种 TS 执行类型（shell、prompt、agent、http）映射到 3 个 Python 执行器
（`exec_prompt_hook.py`、`exec_agent_hook.py`、`exec_http_hook.py`）；
shell hook 流程被归入 bash 工具路径。

模块列表：
- `src/hooks/` — 核心 hook 定义、注册表、执行器、SSRF 防护、信任门
- `clawcodex_ext/hooks/` — 适配器扩展
- `extensions/orchestrator/` — orchestrator 的 hook 集成

---

## Memory

三个层级，与原书章节一致：

1. **项目级** — 仓库中的 `CLAUDE.md` 文件（由 `src/memdir/memory_scan.py` 加载）
2. **用户级** — `~/.claude/MEMORY.md`（由 `src/memdir/paths.py` 加载）
3. **团队级** — 通过符号链接共享。`src/memdir/team_mem_paths.py` + `team_mem_prompts.py`

相关性选择由 LLM 驱动，通过 `src/memdir/find_relevant_memories.py`。

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
| OpenRouter | `src/providers/openrouter_provider.py` | 多供应商代理 |
| DeepSeek | `src/providers/deepseek_provider.py` | DeepSeek API |
| GLM (Zhipu) | `src/providers/glm_provider.py` | 智谱 API |
| MiniMax | `src/providers/minimax_provider.py` | MiniMax API |
| Google | `src/providers/google_provider.py` | Google AI API |
| Bedrock | `src/providers/bedrock.py` | AWS Bedrock |
| LiteLLM | `src/providers/_litellm_adapter.py` | LiteLLM 转接层 |
| OpenAI Compatible | `src/providers/openai_compatible.py` | 通用 OpenAI 兼容 |

所有供应商实现 `src/providers/base.py:BaseProvider` 协议。
扩展层在 `clawcodex_ext/providers/` 和 `extensions/providers_ext/` 中提供额外能力。

### 当前不支持

原书的 Anthropic 云路由维度（AWS Bedrock、Google Vertex AI、Azure Foundry）
有 **部分 Python 等价**：Bedrock 已实现（`src/providers/bedrock.py`），
但 Vertex AI 和 Azure Foundry 尚未实现。

---

## 前端层（Frontend）

TUI 和 REPL 通过 `clawcodex_ext/frontend/` 中的前端注册表管理：

| 前端 | 文件 | 后端 |
|------|------|------|
| Textual TUI | `clawcodex_ext/tui/` (40+ 模块) + `clawcodex_ext/frontend/tui.py` | Textual |
| prompt-toolkit REPL | `clawcodex_ext/repl/` (8 模块) + `clawcodex_ext/frontend/repl.py` | prompt-toolkit |
| Headless | `clawcodex_ext/frontend/headless.py` + `src/entrypoints/headless.py` | 标准输入/输出 |

TUI 屏幕（`clawcodex_ext/tui/screens/`，17+ 屏幕）：
ask_user_question、cost_threshold、diff_dialog、doctor、effort_picker、
exit_flow、history_search、idle_return、mcp_dialogs、message_selector、
model_picker、permission_modal、permission_mode_picker、repl、
resume_conversation、theme_picker、dialog_base。

REPL 核心（`clawcodex_ext/repl/`）：app.py、core.py、session_browser.py、
ui_host.py、background_escape.py。

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
├── cli/                      # CLI 命令：attach、dashboard、issue、resume_session、server、takeover
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
`parsers/` 中的解析器（session、transcript、tool_events、multi_agent），
`static/` 中的静态资源（CSS + JS）。

### Session Analyzer（`extensions/session_analyzer/`）

单 Session 会话时间线分析器（`F-96`）。完全 Python 栈（FastAPI + Jinja2 + HTMX 1.9 + Alpine.js 3.13），无 React/Next 依赖，替代原 `sessions-v0-dev/` Next.js 16 + React 19 实现。

**目录结构**：

```
extensions/session_analyzer/
├── server.py                 # FastAPI app 工厂 + 静态资源挂载
├── models/                   # Pydantic v2 模型（Category / ToolEvent / Agent / Session）
├── parsers/                  # JSONL 解析器 + 工具分类（read/execute/write/orchestrate/other）
├── fixtures/                 # 确定性样例数据（LCG 随机种子 22 子 agent）
├── formatting.py             # 时间轴刻度 + Token 格式化
├── routers/                  # FastAPI 路由（主页 + 导入 + 样例 + HTMX 部分）
├── templates/                # Jinja2 模板（base/index + 6 个 _partials/）
└── static/                   # CSS（OKLCH 设计令牌）+ JS bridge + SVG 图标精灵
```

**关键设计**：

- **零状态服务端**：所有 session 数据通过 HTMX 的 `values` 选项以 JSON 字符串传给后端，渲染后由客户端 DOM 管理；服务器无需缓存。
- **Pydantic v2 别名**：`Session` 模型用 `Field(alias="...")` + `populate_by_name=True` 支持 `camelCase` / `snake_case` 双向兼容；模板通过 `model_dump(by_alias=True, exclude_none=True)` 拿到与前端 `lib/types.ts` 一致的字段命名。
- **侧链分组**：Claude Code 的 `isSidechain=true` 记录被 `group_sidechains()` 聚合为单个子 agent（含 N 个工具调用），匹配原 `parse-session.ts` 的语义。
- **URL 长度回避**：22 子 agent × 328 调用的 JSON 序列化超长，所以 row 部分路由采用「展开时内联工作流面板」而非「懒加载二次请求」——这与原 React 实现的 `expanded ? <WorkflowPanel/> : null` 行为一致。
- **OKLCH 设计令牌**：`static/css/theme.css` 中所有颜色用 `oklch(L C H)` 表达（感知均匀色彩空间），与 `sessions-v0-dev/app/globals.css` 保持一致。
- **视觉回归**：`tests/session_analyzer/test_visual_regression.py` 使用结构化 HTML 快照（必需子串 + 哈希比对）替代 Playwright 像素比对——环境零依赖、可在 CI 跑稳。

**路由契约**：

| Method | Path | 用途 |
|--------|------|------|
| GET    | `/sa/` | 主页（demo 模式自动加载样例） |
| POST   | `/sa/sessions/import` | 多文件 JSONL 上传 + 解析 |
| GET    | `/sa/sessions/sample` | 返回 2 个确定性 demo session |
| DELETE | `/sa/sessions/{id}` | 客户端 DOM 移除 + 服务端空响应 |
| GET    | `/sa/htmx/sessions/{id}/row` | 单 session row HTML（HTMX 部分） |
| GET    | `/sa/htmx/legend` | 图例栏 HTML（计数参数） |
| GET    | `/sa/static/...` | 静态资源（CSS / JS / SVG / fonts） |
| GET    | `/sa/healthz` | 存活探针 |

**测试矩阵**（`tests/session_analyzer/`，141+ 用例）：

- `test_scaffold.py` — 路由 / 静态资源 / 模块导入 smoke
- `test_categorize.py` — 49 用例，覆盖 5 类工具分类（含正则 fallback）
- `test_parser.py` — 33 用例，验证侧链分组 + 持续时间裁剪 + 序号
- `test_sample_data.py` — 13 用例，验证 LCG 确定性 + 22 子 agent 结构
- `test_interaction.py` — 29 用例，HTMX 部分路由 + 端到端上传 / 样例流
- `test_visual_regression.py` — 10 用例，结构化 HTML 快照 + 主题 CSS 验证

### POS Converter（`extensions/pos_converter/`）

将 POS（过程化编排规范）`workflow.md` 转换为协调的多代理系统。
`sdk_parser.py`、`agent_builder.py`、`agent_md_writer.py`、`convert_pos_skill.py`、
`skill_grouper.py`、`source_parser.py`、`templates.py`。

---

## Agent 系统

### 核心（`src/agent/`）

24 个模块：代理定义、运行器、会话管理、透明度、子代理上下文、
前台提升、后台运行器、_outlines_adapter、提示模板、对话、MCP 过滤器。

### 扩展（`clawcodex_ext/agent/`）

工具创作（`tool_authoring/`）：bash/http/python 调用处理器的注册表工厂、
规范验证器、持久化。
后台运行器和状态、会话扩展。
_outlines_adapter（结构化输出适配器）。

### 协调器（`src/coordinator/`）

多代理管理：`mode.py`、`prompt.py`、`worker_agent.py`。

### Swarm（`src/services/swarm/`）

10 个模块：团队文件、成员资格、队友、邮箱、轮询器、
权限、领导者权限桥、代理名称注册表、助手。

---

## Bridge Daemon（`src/bridge/`）

30+ 模块用于多会话远程运行时桥接：
`bridge_main.py`、`bridge_api.py`、`repl_bridge.py`、`remote_bridge_core.py`、
`code_session_api.py`、`messaging.py`、`messaging_handlers.py`、`session_runner.py`、
JWT 工具、信任设备、容量唤醒、WebSocket 传输、flush_gate、worktree。

---

## 其他关键子系统

| 子系统 | 路径 | 说明 |
|--------|------|------|
| Cron 系统 | `clawcodex_ext/cron_system/`（14 模块） | 分布式锁调度，带 jitter 和 NDJSON 运行历史 |
| LiteLLM | `extensions/providers_ext/litellm_provider.py` | 100+ LLM 后端的统一接口 |
| 桥接服务 | `clawcodex_ext/services/bridge/` | 认证、会话、传输 |
| 设置 | `src/settings/`（8 模块） | 设置管理、变更检测、验证 |
| 状态 | `src/state/`（app_state、cache_state、session_start） | 应用级状态 |
| 命令系统 | `src/command_system/`（21 模块） | 斜杠命令：内置命令、effort、export、model、permissions、theme、安全审查 |
| 命令系统扩展 | `clawcodex_ext/command_system/` | 技能集成、好友命令、参数替换 |
| 上下文系统 | `clawcodex_ext/context_system/` | 提示组装、GitPython 适配器 |
| Memory 扩展 | `clawcodex_ext/memory/` | 范围感知提示 |
| Skills 扩展 | `clawcodex_ext/skills/` + `extensions/skills_ext/` | 技能注册表、缓存、捆绑包 |
| 工具系统扩展 | `clawcodex_ext/tool_system/` + `extensions/tool_system_ext/` | 工具注册表扩展、代理配置 |
| Buddy | `src/buddy/`（9 模块） | 语音伴侣（companion、soul、sprites、types、notification、observer） |
| Auth | `src/auth/` + `clawcodex_ext/auth/` | OAuth、API 密钥、Gemini、Claude AI |
| Bootstrap | `src/bootstrap/state.py` | 进程级全局状态（DAG 叶子节点） |
| MCP | `src/services/mcp/`（30+ 模块） | 模型上下文协议：客户端、连接管理器、认证、OAuth、工具包装、输出验证 |
| Compact | `src/services/compact/`（14 模块） | 上下文压缩：自动压缩、反应式、snip、会话内存 |
| 工具执行 | `src/services/tool_execution/` | StreamingToolExecutor、编排器、工具 hook、结果持久化 |
| 语音 | `src/services/voice/` | 语音检测、STT |
| IDE | `src/services/ide/` | IDE 连接、诊断、选择 |
| 分析 | `src/services/analytics/` | 事件、元数据、接收器 |
| API | `src/services/api/` | Claude API 客户端、错误、重试、工具归一化 |
| OAuth | `src/services/oauth/` | OAuth 客户端 |
| Capacities | `extensions/capabilities/` | 协议定义：adapter、agent、context、event、headless、provider、tool |

---

## 审计脚手架（Audit-only Scaffolding）

TS↔Python 一致性报告 CLI 位于 `scripts/audit/`。通过 `python -m scripts.audit.main <sub>` 运行
（由 `tests/test_porting_workspace.py` 执行）；生产环境的 `clawcodex`
控制台脚本从不触及它。

---

## 测试

| 类别 | 路径 | 说明 |
|------|------|------|
| 稳定性门禁 | `tests/stability_gate/`（6 阶段） | 每次 vibe coding 提交前必须通过 |
| Orchestrator 单元测试 | `tests/test_orchestrator_*.py` | git_sync、tracker、agent_runner、dashboard、workspace |
| F-38 E2E | `tests/orchestrator/manual_e2e_f38.py` | 4 轮端到端验证 + PR |
| 通用测试 | `tests/` | 各子系统单元测试 |

### 稳定性门禁层次

| 阶段 | 覆盖范围 | 典型耗时 |
|------|---------|---------|
| Stage 1 | 16 个核心模块导入 | ~4s |
| Stage 2 | CLI `--help` / `--version` / 子命令烟雾测试 | ~9s |
| Stage 3 | REPL + Headless 构造测试 | ~4s |
| Stage 4 | Agent/Conversation 序列化/反序列化 | ~2s |
| Stage 5 | 21 个 clawcodex_ext 扩展模块 | ~3s |
| Stage 6 | 性能回归检测 | ~3s |

---

## 架构指南

1. **DAG 叶子节点**：`src/bootstrap/state.py` 不得导入任何功能子系统包。
   由 `.importlinter` / `pyproject.toml` 中的 import-linter 约束强制执行。

2. **Expand-contract 迁移**：`clawcodex_ext/` 中的模块从 `src/` 导入基类并扩展；
   最终 `src/` 中的模块被替换为从 `clawcodex_ext/` 重导出的桥接。
   使用 `clawcodex_ext_bridge.py` 模式（见 `src/` 中现有的桥接模块）。

3. **单例 ProgressReporter**：`Orchestrator` 上为单实例——`_current_task_id`
   和 `_phase_count` 是可变的，非线程安全。并发工单运行会产生竞争。
   F-39 / F-37 可能需要重构为 `sinks: list[ProgressSink]`。

4. **TrackerAdapter 设计**：`TrackerAdapter.update_pull_request` / `update_comment`
   不是 `@abstractmethod`——默认返回 `None`，确保 `LocalTrackerAdapter`
   不需要覆盖它们。这是有意设计的向后兼容性。

5. **LocalTracker 行为**：触发 `git_sync.sync()` 时 `no_push=True`，
   因此 `result.pushed == False` 且 `result.pending_review == True` 是设计行为，
   而非失败。生产环境使用 GitHub/GitCode 时 `pushed == True`。
