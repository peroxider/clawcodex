# ClawCodex 已归档功能详情

> 文档路径: `docs/ARCHIVED_FEATURES.md`
> 源文档: `docs/FEATURE_PLAN.md` 第2节 (已实现功能模块)
> 版本: v2.0
> 创建日期: 2026-05-30
> 最后更新: 2026-06-08
> 新增归档: F-34~F-55、F-75 已实现功能设计归档（对齐 FEATURE_PLAN v3.0）

---

## 一、核心 Agent 系统

### 1.1 Agent 执行循环

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/run_agent.py` |
| 功能 | 四级权限模型、Subagent 隔离、消息完整性 |
| 状态 | ✅ 已归档 |

### 1.2 Fork Subagent

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/fork_subagent.py` |
| 功能 | 创建独立会话的 sub-agent |
| 状态 | ✅ 已归档 |

### 1.3 Resume Agent

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/resume_agent.py` |
| 功能 | 从断点恢复 sub-agent |
| 状态 | ✅ 已归档 |

### 1.4 Foreground Promotion

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/foreground_promotion.py` |
| 功能 | 后台 agent 提升到前台 |
| 状态 | ✅ 已归档 |

### 1.5 Session 管理

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/session.py` |
| 功能 | 会话状态管理 |
| 状态 | ✅ 已归档 |

### 1.6 Transcript

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/transcript.py` |
| 功能 | 对话转录本管理 |
| 状态 | ✅ 已归档 |

### 1.7 Prompt 构建

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/prompt.py` |
| 功能 | 系统 Prompt 组装 |
| 状态 | ✅ 已归档 |

### 1.8 Agent 定义系统

| 属性 | 值 |
|------|-----|
| 文件 | `src/upstream/b125e16/agent/agent_definitions.py` |
| 功能 | Agent 类型、工具、配置定义 |
| 状态 | ✅ 已归档 |

### 1.9 Agent 记忆作用域

| 属性 | 值 |
|------|-----|
| 文件 | `src/memdir/memdir.py` |
| 功能 | 按需加载不同作用域的记忆 |
| 状态 | ✅ 已归档 |

---

## 二、三层解耦架构（Layer Isolation）

### 2.1 架构概述

| 属性 | 值 |
|------|-----|
| Layer 1 | `src/upstream/` / `src/upstream/v2025_04/` — 上游代码镜像（只读） |
| Layer 2 | `src/capabilities/` — Protocol 接口定义，无运行时上游依赖 |
| Layer 3 | `src/orchestrator/` / `src/api/` — ClawCodex 新增组件，完全解耦 |

### 2.2 关键文件

| 文件 | 功能 |
|------|------|
| `src/capabilities/event_protocol.py` | ToolEvent 接口协议 |
| `src/capabilities/headless_protocol.py` | HeadlessOptions / HeadlessRunner 接口协议 |
| `src/capabilities/headless_runner.py` | 可插拔后端分发器 |
| `src/api/query.py` | 运行时零上游耦合 |
| `upstream-sync.yaml` | `src/api` 加入 features 层 |

### 2.3 解耦结果

| 组件 | 上游直接引用 | 运行时耦合 |
|------|------------|-----------|
| `src/orchestrator/` | ❌ 无 | ✅ 通过 headless_runner 间接 |
| `src/api/query.py` | ❌ 无 | ✅ 通过 headless_runner 间接 |
| `src/api/orchestration.py` | ❌ 无 | ✅ 只调用 orchestrator 内部 |
| `src/capabilities/` | ❌ 无 | ✅ 只定义 Protocol，无实现 |

**upstream-sync audit**: 零层违规验证通过

---

## 三、Provider 层

### 3.1 支持的 Provider

| Provider | 文件 | 状态 |
|----------|------|------|
| Anthropic | `src/providers/anthropic_provider.py` | ✅ 已归档 |
| OpenAI | `src/providers/openai_provider.py` | ✅ 已归档 |
| OpenAI Compatible | `src/providers/openai_compatible.py` | ✅ 已归档 |
| GLM | `src/providers/glm_provider.py` | ✅ 已归档 |
| MiniMax | `src/providers/minimax_provider.py` | ✅ 已归档 |
| DeepSeek | `src/providers/deepseek_provider.py` | ✅ 已归档 |
| OpenRouter | `src/providers/openrouter_provider.py` | ✅ 已归档 |
| LiteLLM 适配器 | `src/providers/_litellm_adapter.py` | ✅ 已归档 |

### 3.2 LiteLLM 适配器

| 属性 | 值 |
|------|-----|
| 文件 | `src/providers/_litellm_adapter.py` |
| 功能 | P0，统一 100+ 模型 |
| 状态 | ✅ 已归档 |

### 3.3 LiteLLM Provider 替换（开源替代组件 R-7）

| 属性 | 值 |
|------|-----|
| 适配器文件 | `src/providers/_litellm_adapter.py` + `extensions/providers_ext/litellm_provider.py` |
| 工厂入口 | `src/providers/__init__.py:create_provider()` / `should_use_litellm()` |
| 环境变量 | `CLAW_USE_LITELLM=true|1|yes|on` |
| 状态 | ✅ 已归档（2026-05-30） |

#### 架构

```
src/providers/base.py (保留 BaseProvider 抽象)
    ↓
src/providers/__init__.py (should_use_litellm() + create_provider() 工厂)
    ↓
extensions/providers_ext/litellm_provider.py (LiteLLM 实现)
    ↓
LiteLLM (开源依赖)
```

#### 关键文件

| 文件 | 功能 |
|------|------|
| `extensions/providers_ext/__init__.py` | 扩展包导出 |
| `extensions/providers_ext/litellm_provider.py` | LiteLLM Provider 实现（含 `_get_litellm_model()` 提取）|
| `src/providers/__init__.py` | 工厂函数 `should_use_litellm()` / `create_provider()` |
| `src/providers/_litellm_adapter.py` | 兼容垫片（重新导出扩展包符号） |
| `src/entrypoints/headless.py` | 使用 `create_provider()` |
| `src/entrypoints/tui.py` | 使用 `create_provider()` |
| `pyproject.toml` | 包发现包含 `extensions*` |

#### 代码减少

- 原始 Provider 类：~1,630 行
- 替换后：~200 行
- **减少代码**：~1,430 行

#### 环境开关行为

| `CLAW_USE_LITELLM` | 行为 |
|--------------------|------|
| `false`（默认） | 使用原始 Provider 类 |
| `1` / `true` / `yes` / `on` | 使用 LiteLLM 统一 Provider |

#### 兼容性

- LiteLLM 保留 `BaseProvider` 接口可回退
- 旧导入路径 `from src.providers._litellm_adapter import ...` 继续有效

---

## 四、工具系统

### 4.1 内置工具列表

| 工具 | 文件 | 状态 |
|------|------|------|
| FileRead | `src/tool_system/tools/read.py` | ✅ 已归档 |
| FileWrite | `src/tool_system/tools/write.py` | ✅ 已归档 |
| FileEdit | `src/tool_system/tools/edit.py` | ✅ 已归档 |
| Glob | `src/tool_system/tools/glob.py` | ✅ 已归档 |
| Grep | `src/tool_system/tools/grep.py` | ✅ 已归档 |
| Bash | `src/tool_system/tools/bash/` | ✅ 已归档 |
| WebFetch | `src/tool_system/tools/web_fetch.py` | ✅ 已归档 |
| WebSearch | `src/tool_system/tools/web_search.py` | ✅ 已归档 |
| AskUserQuestion | `src/tool_system/tools/ask_user_question.py` | ✅ 已归档 |
| SendMessage | `src/tool_system/tools/send_message.py` | ✅ 已归档 |
| TodoWrite | `src/tool_system/tools/todo_write.py` | ✅ 已归档 |
| TaskStop | `src/tool_system/tools/task_stop.py` | ✅ 已归档 |
| TasksV2 | `src/tool_system/tools/tasks_v2.py` | ✅ 已归档 |
| Agent | `src/tool_system/tools/agent.py` | ✅ 已归档 |
| Team | `src/tool_system/tools/team.py` | ✅ 已归档 |
| Config | `src/tool_system/tools/config.py` | ✅ 已归档 |
| PlanMode | `src/tool_system/tools/plan_mode.py` | ✅ 已归档 |
| Cron | `src/tool_system/tools/cron.py` | ✅ 已归档 |
| MCPTool | `src/tool_system/tools/mcp.py` | ✅ 已归档 |
| MCPResources | `src/tool_system/tools/mcp_resources.py` | ✅ 已归档 |
| Skill | `src/tool_system/tools/skill.py` | ✅ 已归档 |
| ToolSearch | `src/tool_system/tools/tool_search.py` | ✅ 已归档 |
| LSP | `src/tool_system/tools/lsp.py` | ✅ 已归档 |
| Worktree | `src/tool_system/tools/worktree.py` | ✅ 已归档 |
| TaskInspect | `src/tool_system/tools/task_inspect.py` | ✅ 已归档 |
| TaskDirectives | `src/tool_system/tools/task_directives.py` | ✅ 已归档 |
| ProgressReport | `src/tool_system/tools/progress_report.py` | ✅ 已归档 |

### 4.2 工具系统按需加载（Tool System Extension）

| 属性 | 值 |
|------|-----|
| 目录 | `src/tool_system_ext/` |
| 功能 | 工具组件解耦，Agent 可配置完全无工具，支持按 bundle 选择性加载 |
| 状态 | ✅ 已归档 |

#### 四种工具模式

| 模式 | 说明 | 工具数 |
|------|------|--------|
| `bare` | 零工具，纯推理 Agent | 0 |
| `default` | 默认束（Bash, Edit, Write, Read, Glob, Grep, WebSearch, WebFetch） | 8 |
| `clawcodex` | 所有原生内置工具 | 42 |
| `all` | 所有工具束（即 default + clawcodex） | 2 bundles |

#### 工具束定义

| 束名 | 工具 |
|------|------|
| `default` | Bash, Edit, Write, Read, Glob, Grep, WebSearch, WebFetch |
| `clawcodex` | 全部原生工具（Agent, AskUserQuestion, Bash, ... 等 42 个） |

---

## 五、开源替代组件

| 组件 | 原始实现 | 替代方案 | 适配器文件 | 状态 |
|------|---------|---------|-----------|------|
| 配置系统 | 手动 JSON 管理 | Pydantic-settings | `src/settings/pydantic_adapter.py` | ✅ 已归档 |
| Frontmatter 解析 | 手动 yaml.safe_load | python-frontmatter | `src/skills/_frontmatter_adapter.py` | ✅ 已归档 |
| Bash AST 解析器 | ~1,500 行自建 | tree-sitter-bash | `src/permissions/_treesitter_adapter.py` | ✅ 已归档 |
| Git 操作 | 6 个 subprocess.run() | GitPython | `src/context_system/_gitpython_adapter.py` | ✅ 已归档 |
| Hook 系统 | ~1,200 行自建 | Pluggy | `src/hooks/_pluggy_adapter.py` | ✅ 已归档 |
| 结构化输出 | json.loads + 手动验证 | Outlines | `src/agent/_outlines_adapter.py` | ✅ 已归档 |

**总计已减少代码**: ~3,100 行

---

## 六、后台运行 + 恢复同步

### 6.1 架构设计

```
┌──────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│   后台任务循环    │────►│  TranscriptWriter │────►│  transcript.jsonl│
│                  │     │  (O_APPEND 原子)   │     │  (实时增量)      │
└──────────────────┘     └───────────────────┘     └─────────────────┘
                                                              │
                                                              │ watchdog
                                                              ▼ 通知
┌──────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│   新终端 TUI      │◄────│  SessionWatcher    │◄────│  会话目录变更   │
│                  │     │  (监控 + 事件)     │     │                 │
└──────────────────┘     └───────────────────┘     └─────────────────┘
```

### 6.2 核心组件

| 组件 | 补丁文件 | 功能 |
|------|---------|------|
| `BackgroundState` | `0067.src.agent.background_state.py.patch` | 进程级后台信号管理器单例，signal/flag 管理 |
| `TailFollower` | `0068.src.services.tail_follower.py.patch` | tail -f 风格尾部追踪器，实时读取 JSONL 增量 |
| `SessionWatcher` | `0069.src.utils.session_watcher.py.patch` | 目录变更监控（inotify/FSEvents/500ms polling fallback） |
| `keybindings.py` | `0070.src.tui.keybindings.py.patch` | 添加 `ctrl+b → agent.background` 绑定 |
| `app.py` | `0071.src.tui.app.py.patch` | `action_agent_background()` 处理 Ctrl+B |
| `session.py` | `0072.src.agent.session.py.patch` | 新增 `Session.resume_with_tail()` 工厂方法 |
| `agent_bridge.py` | `0073.src.tui.agent_bridge.py.patch` | 集成 TailFollower 支持 |
| `graceful_shutdown.py` | `0074.src.utils.graceful_shutdown.py.patch` | 添加 SIGTSTP 处理 |

### 6.3 工作流程

1. **后台化**: TUI 按 Ctrl+B → `signal_background()` 设置信号 → `foreground_promotion.run_with_background_escape` 竞速检测 → `register_agent_background()` → TUI 退出，后台任务通过 `TranscriptWriter` 追加消息
2. **恢复**: `Session.resume_with_tail()` 恢复会话 + 启动 `TailFollower` → 新消息写入时 TailFollower 检测到偏移量变化 → 通知 UI 实时更新

### 6.4 关键设计点

- **不修改上游源码** — 所有改动通过标准 quilt 补丁注入（`patches/upstream/b125e16/`）
- **O_APPEND 原子写入** — 后台任务写入时不会丢失或交错
- **尾部追踪而非快照** — 恢复时读取增量，而非全量重放
- **跨平台** — SessionWatcher 自动选择 inotify (Linux) / FSEvents (macOS) / polling fallback

---

## 七、Bridge Phase 8-11 多 Session Daemon 桥接器

### 7.1 架构设计

```
src/bridge/                    # 桥接层（与上游解耦新增）
├── __init__.py                # 模块入口
├── bridge_api.py               # Phase 3: HTTP 客户端 + API 定义
├── bridge_main.py              # Phase 8: 多 Session Daemon 入口
├── remote_bridge_core.py       # Phase 5: 远程桥接核心
├── session_runner.py           # Phase 4: 子 CLI 会话生成
├── repl_bridge.py              # Phase 11: REPL 桥接
├── init_repl_bridge.py         # 初始化 REPL 桥接
├── messaging.py                # 消息传递机制
├── types.py                   # 桥接类型定义
└── headless_bridge.py          # Headless 桥接
```

### 7.2 Phase 里程碑

| Phase | 补丁文件 | 核心组件 | 状态 |
|-------|---------|---------|------|
| Phase 1 | 0002-bridge-complete-Phase-1-* | Config/URL 处理/polling URL | ✅ 已归档 |
| Phase 3 | 0003-bridge-phase-3-port-bridgeApi.ts-* | bridge_api.py HTTP 客户端 | ✅ 已归档 |
| Phase 4 | 0005-bridge-phase-4-port-sessionRunner.ts-* | session_runner.py 子 CLI 生成 | ✅ 已归档 |
| Phase 5 | 0004-bridge-phase-5-MVP-port-remoteBridgeCore.ts-* | remote_bridge_core.py 远程桥接 | ✅ 已归档 |
| Phase 6 | 0006-bridge-phase-6-*-orchestrator-skel-* | 基于 env 的编排器骨架 | ✅ 已归档 |
| Phase 8 | 0007-bridge-phase-8-*-multi-session-daemon-* | bridge_main.py 多会话轮询 | ✅ 已归档 |
| Phase 11a | 0008-bridge-phase-11a-bridge_main-hardening-* | bridge_main.py 硬化 | ✅ 已归档 |
| Phase 11b | 0009-bridge-phase-11b-repl_bridge-hardening-* | repl_bridge.py 硬化 | ✅ 已归档 |

### 7.3 核心组件详细说明

#### 7.3.1 bridge_main.py - 多 Session Daemon 入口 (Phase 8)

多会话轮询守护进程，负责：
- CLI 参数解析 (`--verbose`, `--sandbox`, `--spawn`, `--capacity`, `--permission-mode`, `--name`)
- 多会话容量控制 (capacity gating)
- 会话状态管理 (active_sessions, session_work_ids, completed_work_ids)
- 工作轮询循环 (work poll loop)
- 优雅关闭 (SIGTERM → wait grace → SIGKILL stragglers → deregister)
- SIGINT/SIGTERM 处理器安装

#### 7.3.2 remote_bridge_core.py - 远程桥接核心 (Phase 5)

远程桥接实现，支持：
- v2 环境变量驱动配置
- 远程会话生命周期管理
- 跨进程通信

#### 7.3.3 session_runner.py - 子 CLI 会话生成 (Phase 4)

子进程管理，实现：
- Child CLI 生成和监控
- 工作目录管理
- 会话超时控制

#### 7.3.4 repl_bridge.py - REPL 桥接 (Phase 11)

REPL 集成桥接器，实现：
- REPL 与 Bridge 的消息路由
- 会话状态同步
- TUI 交互支持

#### 7.3.5 bridge_api.py - HTTP 客户端 (Phase 3)

API 通信层：
- 轮询 URL 处理
- 会话注册/注销
- 工作队列管理

---

## 八、Agent Loop Consolidation (Stage 4)

### 8.1 核心变更

| 变更 | 说明 | 行数 |
|------|------|------|
| 删除 `agent_loop.py` | 上游原 Agent 循环逻辑移除 | -537 行 |
| 新增 `renderers.py` | 系统 prompt 渲染器 | +257 行 |
| 新增 `advisor.py` | Advisor 工具 | +125 行 |
| 重构到 `src/query/` | 查询引擎解耦 | - |

### 8.2 renderers.py - 系统 Prompt 渲染器

渲染器负责将系统 prompt 组件组合并格式化：

```python
class SystemPromptRenderer:
    """系统 Prompt 渲染器"""
    def render(self, context: PromptContext) -> str: ...
    def render_capabilities(self, capabilities: list[str]) -> str: ...
    def render_rules(self, rules: list[str]) -> str: ...
```

### 8.3 advisor.py - Advisor 工具

Advisor 工具提供 Token 计数和状态显示：

```python
class AdvisorTool:
    """Advisor 工具 - 提供 token 计数和状态信息"""
    def get_token_usage(self) -> TokenUsage: ...
    def get_cost_estimate(self) -> CostEstimate: ...
```

---

## 九、Advisor Token 计数与状态显示

### 9.1 核心改进

| 改进 | 文件 | 说明 |
|------|------|------|
| Token 计数显示 | `src/agent/conversation.py` | max_history: 100 → 2000 |
| Provider Token 追踪 | `src/providers/anthropic_provider.py` | 增加 token 使用追踪 |
| Base Provider 增强 | `src/providers/base.py` | 统一 token 计数接口 |

### 9.2 max_history 扩展

`src/agent/conversation.py` 中 `max_history` 从 100 提升到 2000，允许更长的对话历史。

### 9.3 Provider Token 追踪

```python
@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

---

## 十、REPL 与 TUI 增强

### 10.1 核心组件

| 组件 | 文件 | 功能 |
|------|------|------|
| REPL Core | `src/repl/core.py` | REPL 核心逻辑 |
| TUI App | `src/tui/app.py` | Textual TUI 应用 |
| Keybindings | `src/tui/keybindings.py` | 快捷键绑定 |
| LiveStatus | `src/repl/live_status.py` | 实时状态栏 |

### 10.2 Shift+Tab 权限模式循环

支持在 REPL/LiveStatus/TUI 中通过 `Shift+Tab` 循环切换权限模式：`default → acceptEdits → plan → bypassPermissions`

### 10.3 TUI /permission 命令

在 TUI 中可通过 `/permission` 命令打开权限模式选择器，支持选择：
- Default (default)
- Accept edits (acceptEdits)
- Plan mode (plan)
- Bypass permissions (bypassPermissions) - 需要配置启用
- Don't ask (dontAsk)

### 10.4 REPL/TUI 双向切换

- **REPL → TUI**: `/tui` 命令切换到 Textual TUI，会话历史自动同步
- **TUI → REPL**: `/repl` 命令切换回 CLI REPL，TUI 会话自动保存
- 切换时保留 session、conversation、permission_mode 等状态

---

## 十一、TUI 响应性修复

### 11.1 问题描述

thinking 过程中 LLM 服务超时时，ESC、CTRL+C、CTRL+D 和 /exit 都无效，界面完全无反应。

### 11.2 根因分析

1. `StreamWatchdog` 超时只关闭 HTTP 响应流，不触发 TUI 的 `AbortController`
2. `action_cancel_or_quit`（Ctrl+C 处理）直接调用 `self.exit()`，没有先调用 `agent_bridge.cancel()`

### 11.3 修复方案

| 文件 | 修改内容 |
|------|---------|
| `src/tui/app.py:322` | `action_cancel_or_quit` 先调用 `self._agent_bridge.cancel()`，取消成功则返回，失败才 exit |
| `src/utils/stream_watchdog.py` | 新增 `abort_signal` 参数，超时时调用 `abort_signal._fire()` 触发 TUI 取消机制 |
| `src/providers/anthropic_provider.py:366` | `StreamWatchdog(stream)` → `StreamWatchdog(stream, abort_signal=abort_signal)` |

---

## 十二、TaskInspect/TaskDirectives 工具注册

### 12.1 问题

`TaskInspectTool` 和 `TaskDirectivesTool` 代码文件存在于 `src/tool_system/tools/` 目录，但未注册到 `ALL_STATIC_TOOLS`，导致 AI Agent 无法调用。

### 12.2 修复

在 `src/tool_system/tools/__init__.py` 中添加：
- 导入: `from .task_inspect import TaskInspectTool`, `from .task_directives import TaskDirectivesTool`
- 添加到 `ALL_STATIC_TOOLS` 列表
- 添加到 `__all__` 导出列表

---

## 十三、ProgressReportTool 工具注册

### 13.1 问题

`ProgressReportTool` 代码文件存在于 `src/tool_system/tools/progress_report.py`，但未注册到 `ALL_STATIC_TOOLS`。

### 13.2 修复

在 `src/tool_system/tools/__init__.py` 中添加：
- 导入: `from .progress_report import ProgressReportTool`
- 添加到 `ALL_STATIC_TOOLS` 列表
- 添加到 `__all__` 导出列表

---

## 十四、TUI 权限模式选择器

### 14.1 功能

通过 `PermissionModePickerScreen` 模态对话框支持 5 种权限模式：
- `default` - 每个工具运行前询问
- `acceptEdits` - 自动批准文件编辑操作
- `plan` - Plan mode - 自动批准只读操作
- `bypassPermissions` - 运行所有工具不提示
- `dontAsk` - 从不提示，自动批准所有

### 14.2 组件位置

```
src/tui/screens/permission_mode_picker.py
```

---

## 十五、会话恢复浏览器 (Resume Conversation)

### 15.1 功能

- 模糊搜索 (fuzzy search)：支持输入过滤历史会话
- 实时计数显示：显示 "X / Y sessions" 过滤结果
- 会话元数据展示：标题、模型、消息数、时间戳

### 15.2 使用方式

| 方式 | 说明 |
|------|------|
| `clawcodex --tui --resume` | 启动时直接进入会话选择 |
| `/resume` 命令 | 从 REPL 呼出会话选择器 |
| Ctrl+B 后台后 | 用户选择会话重新附着 |

### 15.3 组件位置

```
src/tui/screens/resume_conversation.py
src/repl/live_status.py  # 新增 Live Status 实时状态组件
```

---

## 十六、Orchestrator 自主模式（Symphony 集成）

### 16.1 核心组件

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| Orchestrator | `src/orchestrator/orchestrator.py` | ✅ 已归档 | 轮询循环 + 任务分发 |
| WorkspaceManager | `src/orchestrator/workspace.py` | ✅ 已归档 | 每个 Issue 的隔离工作区 |
| LinearAdapter | `src/orchestrator/linear/adapter.py` | ✅ 已归档 | Linear GraphQL API 适配器 |
| LinearClient | `src/orchestrator/linear/client.py` | ✅ 已归档 | HTTP + GraphQL 客户端 |
| Issue | `src/orchestrator/linear/issue.py` | ✅ 已归档 | Issue 数据模型 |
| AgentRunner | `src/orchestrator/agent_runner.py` | ✅ 已归档 | 连接 QueryRunner |
| PromptBuilder | `src/orchestrator/prompt_builder.py` | ✅ 已归档 | 模板渲染 |
| WorkflowLoader | `src/orchestrator/workflow.py` | ✅ 已归档 | WORKFLOW.md 解析 |
| ApprovalPolicy | `src/orchestrator/approval_policy.py` | ✅ 已归档 | 工具调用审批策略 |
| StatusDashboard | `src/orchestrator/status_dashboard.py` | ✅ 已归档 | 终端 UI 状态面板 |
| TrackerAdapter | `src/orchestrator/tracker.py` | ✅ 已归档 | Tracker 协议抽象 |
| IssueRegistry | `src/orchestrator/issue_registry.py` | ✅ 已归档 | 持久化 issue→commit→PR 映射 |
| ClarificationQueue | `src/orchestrator/clarification_queue.py` | ✅ 已归档 | 操作员异步应答队列 |
| CLI orchestrator group | `src/orchestrator/cli/` | ✅ 已归档 | `clawcodex orchestrator` 统一入口 |

### 16.2 已完成功能

| 功能 | 说明 |
|------|------|
| 多 Tracker 支持 | GitHub/Gitee/GitCode 通用 REST 适配器已实现 |
| CLI 集成 | `cli.py:596-666` 已实现 `--workflow`、`--dashboard`、`--port` |
| 重试队列 + 退避 | 实现指数退避重试 |
| 重试上限保护 | `_schedule_retry` 增加最大重试次数限制 |
| Issue State 前置检查 | `_poll_and_dispatch` 在 launch 前查 issue 最新 state |
| 已有 PR 跳过后续处理 | `_launch_issue` 前查 `find_pull_request` |
| 本地 Issue 注册表 | 持久化 issue→commit→PR 映射到 JSON |
| Issue Clarification 流程 | 三通道 ClarificationQueue + TrackerAdapter 评论接口 |
| Orchestrator CLI | `clawcodex orchestrator` 统一入口 |

### 16.3 Orchestrator CLI 命令

| 命令 | 说明 |
|------|------|
| `clawcodex orchestrator server start --workflow PATH` | 启动 orchestrator daemon |
| `clawcodex orchestrator server status` | 查看 daemon 运行状态 |
| `clawcodex orchestrator server stop` | 停止 orchestrator daemon |
| `clawcodex orchestrator issue list [--status]` | 列出所有 issue 及状态 |
| `clawcodex orchestrator issue tail --id <id>` | 实时 tail tool call 日志 |
| `clawcodex orchestrator issue show --id <id>` | 查看 issue 详情 |
| `clawcodex orchestrator issue pause --id <id>` | 暂停 agent |
| `clawcodex orchestrator issue resume --id <id>` | 恢复暂停中的 agent |
| `clawcodex orchestrator issue stop --id <id>` | 强制终止 agent |
| `clawcodex orchestrator issue inject --id <id> <hint>` | 向运行中的 agent 注入提示 |
| `clawcodex orchestrator issue clarify --id <id> --answer <text>` | 操作员澄清应答 |
| `clawcodex orchestrator issue workspace --id <id> --ls` | 列出 workspace 文件 |
| `clawcodex orchestrator issue takeover --id <id>` | 完全接管 |
| `clawcodex orchestrator dashboard --port` | 独立 dashboard UI |

### 16.4 生产强化（F-1.1~F-1.4）

#### F-1.1 重试上限保护

| 项 | 值 |
|---|---|
| 实现位置 | `orchestrator/orchestrator.py:_schedule_retry` |
| 新增字段 | `workflow.agent.max_retry_attempts: int = 5` |
| 触发条件 | `attempt > max_retry_attempts` 时跳过调度 |
| 副作用 | 不写入 `completed`（需人工确认后手动关闭 issue） |
| 状态 | ✅ 已归档 |

#### F-1.2 Issue State 前置检查

| 项 | 值 |
|---|---|
| 实现位置 | `orchestrator/orchestrator.py:_launch_issue` |
| 检查方式 | `tracker.fetch_issue_states_by_ids([issue.id])`，非 active 跳过 |
| 副作用 | 从 `claimed` 集合移除，不进入 `completed` |
| 状态 | ✅ 已归档 |

#### F-1.3 已有 PR 跳过后续处理

| 项 | 值 |
|---|---|
| 实现位置 | `orchestrator/orchestrator.py:_launch_issue` |
| 检查方式 | `tracker.find_pull_request(head_branch, base_branch)` |
| 适用范围 | 仅 RepositoryTrackerAdapter（GitHub/Gitee/GitCode） |
| 副作用 | 标记 completed，重启后不重复处理 |
| 状态 | ✅ 已归档 |

#### F-1.4 本地 Issue 注册表

| 项 | 值 |
|---|---|
| 文件位置 | `{workspace.root}/.clawcodex_issue_registry.json` |
| 实现文件 | `orchestrator/issue_registry.py:IssueRegistry` |
| 记录字段 | `issue_id / identifier / branch_name / commit_sha / pr_number / pr_url / status / attempt_count / clarification_status / question_history` |
| Status 枚举 | `PENDING → SYNCED → COMPLETED / FAILED / ABANDONED` |
| 状态 | ✅ 已归档 |

### 16.5 Issue 语义澄清流程（F-1.5~F-1.11）

| 通道 | 实现 | 触发 | 降级 |
|------|------|------|------|
| 通道一 | `StatusDashboard` 交互提示 | 非 headless + 操作员在线 | 5 分钟无操作 |
| 通道二 | `ClarificationQueue` 文件队列（`~/.clawcodex/clarification_queue.json`） | 异步 CLI `clarify` 应答 | 30 分钟 |
| 通道三 | `TrackerAdapter.create_clarification_comment()` | @mention Issue 作者 | 72 小时 |

#### ClarificationStatus 枚举

```python
class ClarificationStatus(str, Enum):
    NONE = "none"
    AWAITING_LOCAL = "awaiting_local"        # 等待本地操作员
    AWAITING_AUTHOR = "awaiting_author"     # 已发 @mention，等待作者
    RECEIVED = "received"
    RESOLVED_LOCAL = "resolved_local"        # 来自本地操作员
    RESOLVED_AUTHOR = "resolved_author"     # 来自 @mention 作者
    TIMED_OUT_LOCAL = "timed_out_local"     # 本地超时，降级通道三
    TIMED_OUT_AUTHOR = "timed_out_author"   # 作者超时
    EXHAUSTED = "exhausted"
    DUPLICATE_REJECTED = "duplicate_rejected"  # 重复提交，被去重丢弃
    STALE_REJECTED = "stale_rejected"          # 超时升级后收到的过时答案
    CONFLICT_RESOLVED = "conflict_resolved"    # 多渠道冲突已裁决
```

#### 冲突处理原则

- **第一响应者优先**：第一个被 Orchestrator 检测到的有效答案被采纳
- **操作员优先级**：操作员答案始终比作者更可信（`operator_priority: true`）
- **单向升级不可逆**：通道二超时 → 通道三后，原通道迟来答案标记 STALE_REJECTED
- **过期主动通知**：所有被拒绝的答案都要通知对应应答者
- **去重幂等**：同一答案重复提交第二次标记 DUPLICATE_REJECTED

#### 完成阶段（Phase A-G）

- [x] Phase A: `ClarificationQueue` 文件队列 + 冲突处理状态机 + 超时告知
- [x] Phase B: StatusDashboard 交互提示组件
- [x] Phase C: `AskIssueAuthor` 工具 + `ClarificationResolver` 三通道降级
- [x] Phase D: CLI `clarify` 子命令
- [x] Phase E: `TrackerAdapter.fetch_issue_comments()` / `create_clarification_comment()` 接口 + GitHub/Gitee/GitCode 实现
- [x] Phase F: IssueRegistry 澄清字段持久化 + PromptBuilder 澄清内容注入
- [x] Phase G: escalation 策略实现（skip / mark_failed / notify）

#### 新增配置

```yaml
agent:
  clarification:
    operator_priority: true        # 操作员答案优先于作者（默认 true）
    stale_notification: "all"      # "all" | "operator_only" | "none"
    simultaneous_grace_ms: 5000    # 5ms 内视为同时，由 operator_priority 决胜
```

#### 状态

✅ 已归档

### 16.6 Orchestrator CLI 运维操作界面（F-1.13）

完整 CLI 命令集（O1-O8 阶段）：

| 命令 | 阶段 | 状态 |
|------|------|------|
| `clawcodex orchestrator server start --workflow PATH` | O1 | ✅ 已归档 |
| `clawcodex orchestrator server status` | O1 | ✅ 已归档 |
| `clawcodex orchestrator server stop` | O1 | ✅ 已归档 |
| `clawcodex orchestrator issue list [--status]` | O1 | ✅ 已归档 |
| `clawcodex orchestrator issue tail --id <id>` | O3 | ✅ 已归档 |
| `clawcodex orchestrator issue show --id <id>` | O3 | ✅ 已归档 |
| `clawcodex orchestrator issue pause --id <id>` | O2 | ✅ 已归档 |
| `clawcodex orchestrator issue resume --id <id>` | O2 | ✅ 已归档 |
| `clawcodex orchestrator issue stop --id <id>` | O2 | ✅ 已归档 |
| `clawcodex orchestrator issue inject --id <id> <hint>` | O4 | ✅ 已归档 |
| `clawcodex orchestrator issue inject --id <id> --list` | O4 | ✅ 已归档 |
| `clawcodex orchestrator issue inject --id <id> --remove <n>` | O4 | ✅ 已归档 |
| `clawcodex orchestrator issue clarify --id <id> --answer <text>` | O7 | ✅ 已归档 |
| `clawcodex orchestrator issue workspace --id <id> --ls` | O5 | ✅ 已归档 |
| `clawcodex orchestrator issue workspace --id <id> --cat <file>` | O5 | ✅ 已归档 |
| `clawcodex orchestrator issue workspace --id <id> --edit <file> --with <content>` | O5 | ✅ 已归档 |
| `clawcodex orchestrator issue takeover --id <id>` | O6 | ✅ 已归档 |
| `clawcodex orchestrator dashboard --port` | O8 | ✅ 已归档 |

#### 实施阶段

- [x] O1: CLI `orchestrator` group 框架（替代旧 `--workflow` 顶层 flag）
- [x] O2: pause/resume/stop + 状态机
- [x] O3: `issue tail` 流式 event stream + StatusDashboard 实时渲染
- [x] O4: `issue inject` Hint 注入（`.operator_hints.md` 机制）
- [x] O5: `issue workspace --ls/--cat/--edit`
- [x] O6: `issue takeover` 终止 + REPL 接管
- [x] O7: `issue clarify` 澄清应答
- [x] O8: Dashboard LiveView 增强（LLM 摘要 + tool calls 推送）

#### 不兼容变更

- `clawcodex --workflow` 已废弃，替换为 `clawcodex orchestrator server start --workflow PATH`
- 原有扁平子命令（`run`、`status`、`issues`、`pause`、`resume`、`stop`、`inject`、`clarify`、`workspace`、`takeover`）已移除
- 统一使用 noun-verb 结构：`server <verb>` / `issue <verb> --id <id>`

```bash
# 新命令
clawcodex orchestrator server start --workflow test_gitcode_workflow.md
clawcodex orchestrator server status
clawcodex orchestrator issue list
clawcodex orchestrator issue pause --id 42
clawcodex orchestrator issue inject --id 42 "hint text"
```

---

## 十七、MCP 协议扩展

### 17.1 当前支持

| 功能 | 文件 | 状态 |
|------|------|------|
| Stdio Transport | `src/services/mcp/` | ✅ 已归档 |
| HTTP/SSE Transport | `src/services/mcp/` | ✅ 已归档 |
| WebSocket Transport | `src/services/mcp/` | ✅ 已归档 |
| OAuth 支持 | `src/services/mcp/` | ✅ 已归档 |
| HTTPS/XSS 硬化 | `src/services/mcp/` | ✅ 已归档 |

---

## 十八、Agent 间自主观察与消息交互

### 18.1 角色定义

| 角色 | 判断标准 | 说明 |
|------|---------|------|
| **Manager Agent** | 工具集中包含 `TaskInspect` + `TaskDirectives` | 通过工具组合自动识别，无需独立 Agent 类型 |
| **Worker Agent** | 不包含上述管理工具 | 普通执行单元 |

### 18.2 核心工具

| 工具 | 文件 | 功能 |
|------|------|------|
| `TaskInspect` | `src/tool_system/tools/task_inspect.py` | Manager 查询 Worker 运行时状态 |
| `TaskDirectives` | `src/tool_system/tools/task_directives.py` | Manager 向 Worker 注入优先级指令 |

### 18.3 实施阶段

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase M1 | `TaskInspect` + `TaskDirectives` 核心工具 | ✅ 已归档 |
| Phase M2 | `queue_pending_message` 支持 priority | ✅ 已归档 |
| Phase M3 | `drain_pending_messages` 按优先级消费 | ✅ 已归档 |
| Phase M4 | 工具可见性过滤（仅 Manager 可调用） | ✅ 已归档 |
| Phase M5 | 权限规则传递 | ✅ 已归档 |

---

## 十九、SOP 转化模式

### 19.1 三层映射关系

| 工作流组件 | Agent 架构 | 示例 |
|-----------|-----------|------|
| SOP (标准作业流程) | Agent | 数据分析 Agent、CI/CD Agent、ML Pipeline Agent |
| 工作流步骤 | Skill | `deploy_service`、`run_etl`、`train_model` |
| SDK 接口 | 原子工具 | `s3_upload`、`k8s_apply`、`spark_submit` |

### 19.2 实现文件

| 文件 | 说明 |
|------|------|
| `src/pos_converter/__init__.py` | 模块入口 |
| `src/pos_converter/sdk_parser.py` | SDK 解析（支持 OpenAPI JSON / URL / 简单方法列表） |
| `src/pos_converter/skill_grouper.py` | Skill 分组（静态 MappingRule + LLM 辅助） |
| `src/pos_converter/agent_builder.py` | Agent 构建 + 持久化 |
| `src/pos_converter/convert_pos_skill.py` | `/convert-pos-to-agent` Skill 实现 |
| `src/pos_converter/templates.py` | 模板定义 |
| `src/skills_ext/bundled/pos_to_agent.py` | bundled skill 注册（解耦上游） |

---

## 二十、Skills System Extension（技能系统扩展层）

> 对应 **F-23**（2026-05-24 完成）

### 20.1 背景

`src/skills/loader.py` 存在以下问题：
- 硬编码 clawcodex 特定路径（`~/.clawcodex/skills` 等）
- `get_all_skills()` 职责过于集中
- 难以独立更新上游

### 20.2 与 Tool System Ext 的对齐设计

| 组件 | Tool System | Skills System |
|------|-------------|---------------|
| 上游核心 | `tool_system/registry.py` | `skills/loader.py` |
| 扩展目录 | `tool_system_ext/` | `skills_ext/` |
| 扩展包装类 | `ToolRegistryExt` | `SkillRegistryExt` |
| Bundle 机制 | `TOOL_BUNDLES` | `SKILL_BUNDLES` |
| Agent 配置 | `AgentToolConfig` | `AgentSkillConfig` |

### 20.3 实现文件清单

| 文件路径 | 优先级 | 状态 | 说明 |
|---------|--------|------|------|
| `src/skills_ext/__init__.py` | P0 | ✅ 已归档 | 扩展层入口 |
| `src/skills_ext/registry_ext.py` | P0 | ✅ 已归档 | `SkillRegistryExt` 包装类 |
| `src/skills_ext/bundles.py` | P0 | ✅ 已归档 | Skill Bundle 定义 |
| `src/skills_ext/agent_config.py` | P1 | ✅ 已归档 | Agent Skill 配置 |
| `src/skills_ext/paths.py` | P1 | ✅ 已归档 | clawcodex 特定路径解析 |
| `src/skills_ext/hooks.py` | P2 | ✅ 已归档 | Skill 生命周期钩子 |
| `src/skills_ext/cache.py` | P2 | ✅ 已归档 | 扩展层缓存管理 |

### 20.4 核心组件

```python
# src/skills_ext/registry_ext.py
class SkillRegistryExt:
    """包装上游 loader，添加 clawcodex 特定功能"""

    def get_all_skills(self, **kwargs) -> list[Skill]:
        base = self._loader.get_all_skills(**kwargs)  # 上游 skills
        clawcodex = self._load_clawcodex_paths()      # clawcodex 特定
        return self._merge_skills(base, clawcodex)     # 合并去重

    def on_skill_registered(self, callback):
        """Skill 注册回调通知"""
        ...
```

### 20.5 迁移阶段

- [x] 阶段 1：创建 `src/skills_ext/` 目录和基础结构
- [x] 阶段 2：迁移 clawcodex 特定路径逻辑到 `skills_ext/paths.py`
- [x] 阶段 3：添加 Bundle 机制和 AgentSkillConfig
- [x] 阶段 4：添加 Hook 机制和回调系统
- [x] 阶段 5：更新 `get_all_skills()` 调用点使用 `SkillRegistryExt`

### 20.6 状态

✅ 已归档（2026-05-24）

---

*本文档由 `docs/FEATURE_PLAN.md` 第2节归档生成，最后更新于 2026-06-01*

<!-- archived-2026-06-02-feature-plan -->

## 二十一、2026-06-02 已实现功能归档

> 归档日期: 2026-06-02
> 来源: 本轮从活动规划/进度文档迁移的已实现条目。

#### 二十一.1 F-36 LocalTracker 本地 Issue 文档源

**状态**: ✅ 完成
**目标**: 支持在本地特定路径新增 issue 文档，并由 Orchestrator 像处理 Linear/GitHub/Gitee/GitCode issue 一样追踪、领取、运行和更新状态。

##### Human Review Gate

LocalTracker 在 git commit 完成后不进行 push（无远程仓库），增加了 Human Review Gate 机制让人类审批代码变更：

```
Agent 完成 → git commit → pending_review
                              ↓
                    人类审查 diff
                              ↓
            ┌─────────────────┴─────────────────┐
            │                               │
       --approve                        --reject
            │                               │
            ↓                               ↓
    completed（工作目录保留）        反馈注入 ClarificationQueue
                                      ↓
                                  agent 重试
```

**新增状态**: `PENDING_REVIEW` — Agent 完成 git commit，等待人类 review

**新增 CLI 命令**:

| 命令 | 说明 |
|------|------|
| `clawcodex orchestrator issue diff --id <id>` | 查看变更概览（Agent Summary + 文件统计 + diff preview） |
| `clawcodex orchestrator issue diff --id <id> --stat` | 仅显示文件统计 |
| `clawcodex orchestrator issue diff --id <id> --full` | 显示完整 diff |
| `clawcodex orchestrator issue review --id <id> --approve [--comment "<text>"]` | 审批通过 |
| `clawcodex orchestrator issue review --id <id> --reject --feedback "<text>"]` | 审批拒绝，触发重试 |

**Agent Summary**: 从 `*.comments.ndjson` 中提取 `## ClawCodex Run Complete` 注释内容，显示 agent 的工作摘要。

##### 配置形态

```yaml
tracker:
  kind: local
  issues_path: /tmp/clawcodex_local_issues
  active_states:
    - open
    - ready
  terminal_states:
    - completed
    - closed
    - cancelled

workspace:
  root: /tmp/clawcodex_orchestrator_test_workspaces
  repo_clone_url: /mnt/e/Nodel/ExerciseProject/clawcodex
```

`tracker.issues_path` 是 issue 来源目录；`workspace.root` 仍只负责 per-issue workspace、registry、event logs 与运行产物，二者不应混用。

##### Issue 文档格式

首期支持 Markdown front matter，后续可扩展 JSON：

```markdown

# 修复 dashboard workspace 解析

当前 dashboard 只读取默认 workspace 或 CLAWCODEX_WORKSPACE_ROOT。
希望它支持从 WORKFLOW.md 的 workspace.root 解析。
```

解析规则：
- `id` / `identifier` 必填；缺失时可由文件名派生，但写回时必须固化到 front matter。
- Markdown 第一个一级标题作为 `title`；正文剩余内容作为 `description`。
- `state` 必须匹配 `active_states` 才会进入候选列表。
- `branch_name` 可选；缺失时由 `identifier + title` slug 派生。
- `labels`、`priority`、`assignee_id`、`created_at`、`updated_at` 作为可选字段映射到统一 `Issue` 模型。

##### 适配器边界

新增 `LocalTrackerAdapter` 应实现既有 `TrackerAdapter` 协议，而不是在 Orchestrator 主循环中加入本地文件分支：

| 接口 | LocalTracker 行为 |
|------|-------------------|
| `fetch_candidate_issues()` | 扫描 `issues_path` 下 `.md` / `.json` 文件，过滤 active state，返回统一 `Issue` 列表 |
| `fetch_issue_states_by_ids(ids)` | 重新读取对应本地文件的 `state`，用于 launch 前前置检查 |
| `find_pull_request(...)` | 本地 tracker 无远程 PR 概念，默认返回 `None`；若 front matter 有 `pr_url` 可返回轻量结果 |
| `ensure_pull_request(...)` | 不创建远程 PR；首期写回 `commit_sha` / `branch_name` / `status`，并返回空结果或本地同步结果 |
| `fetch_issue_comments(...)` | 首期可读取同目录下 `<id>.comments.ndjson` 或 issue front matter 的 `comments` 字段；非必需 |
| `create_clarification_comment(...)` | 写入本地 comments 文件或 clarification queue，不访问外部服务 |

##### 状态写回策略

LocalTracker 的状态写回应以 issue 文档 front matter 为单一来源，`IssueRegistry` 继续保存运行态映射：

```text
open/ready → running → completed
                  └── failed
                  └── abandoned
```

建议写回字段：
- `state`: `running` / `completed` / `failed` / `abandoned`
- `claimed_at`, `completed_at`, `updated_at`
- `workspace_path`
- `branch_name`
- `commit_sha`
- `pr_url`（如后续接入本地 forge 或远程 PR）
- `last_error`（失败时）

为避免破坏用户手写正文，写回只修改 front matter，不重排 Markdown body。

##### 并发与幂等

- 每个 issue 文件旁使用短生命周期 lock（如 `.LOCAL-001.lock`）或原子 rename，避免多 orchestrator 实例同时领取。
- `fetch_candidate_issues()` 必须跳过已在 `IssueRegistry` 中 `COMPLETED`、已有 PR 或 terminal state 的 issue。
- 写回采用读-改-写，并校验 `updated_at` 或文件 mtime，检测外部编辑冲突。
- 若本地 issue 在运行中被人工改为 terminal state，launch 前检查或下一轮 poll 应停止后续处理。

##### CLI 与看板行为

LocalTracker 不需要新增独立 issue 创建命令即可工作；用户可直接在 `issues_path` 新增 `.md` 文件。现有命令继续通过 registry/event logs 工作：

```bash
clawcodex orchestrator issue list --workspace /tmp/clawcodex_orchestrator_test_workspaces
clawcodex orchestrator issue show LOCAL-001 --workspace /tmp/clawcodex_orchestrator_test_workspaces
clawcodex orchestrator issue tail LOCAL-001 --workspace /tmp/clawcodex_orchestrator_test_workspaces
```

后续可选增强：
- `clawcodex orchestrator issue new --local --title ...` 生成本地 issue 文档模板。
- dashboard 显示 `source: local` 和 issue file path。
- `issue inject` 仍作为运行中 operator hints，不替代初始 issue 文档。

##### 实施切片

1. 配置 schema 增加 `tracker.kind: local` 与 `tracker.issues_path`。
2. 新增 `local_tracker` adapter/client/parser，复用 `Issue` dataclass。
3. 接入 tracker factory，确保 Orchestrator 主循环无需感知本地/远程差异。
4. 实现 Markdown front matter 读取、active state 过滤和状态写回。
5. 增加单元测试：解析、过滤、写回、并发锁、launch 前 state 检查。
6. 增加本地 workflow 示例和端到端 smoke test。

---
id: LOCAL-001
identifier: LOCAL-001
state: open
priority: 1
branch_name: local-001-fix-dashboard-workspace
labels:
  - orchestrator
---

---

#### 二十一.2 F-38 Orchestrator 验证与报告闭环

**状态**: 📋 设计完成
**优先级**: P0
**触发场景**: 2026-06-01 在 `chadwweng/AgentSDK` 跑 issue #1 时发现 agent 一次工具都没调（`tools=0`）仍走 SessionComplete → commit/push/PR 全程无验证；事后 PR `#1` 收到 1 条 Git Sync 评论但无 Run Complete 汇总；PR body 是静态模板不含验证/产物信息；reviewer 找不到 diff 与 workspace 路径。

##### 目标

把 `extensions/orchestrator` 的 issue 跟踪流程从「commit/push/PR 直通」补全为「commit 验证 → push 验证 → 报告生成 → PR 反馈」的端到端闭环：

1. **Sub-A Verification Gate**：commit/push 之前自动跑 `test_command`（默认 `pytest -x`，用户可配），失败时阻止 commit/push 并把 issue 标 `verification_failed`。
2. **Sub-B 结构化报告**：agent 跑完写一份 Markdown（人读）+ JSON（机读）报告到 `workspace/.reports/{id}.{md,json}`，内容包括 issue 摘要、turns/tools 计数、verification 结果、commit/diff stat、报告路径。
3. **Sub-C PR 报告回写**：抽象 `TrackerAdapter.update_pull_request` 协议，GitCode 客户端实现 `PATCH /repos/{owner}/{repo}/pulls/{id}`，git_sync 在 PR 开完后用报告回写 PR body，并把原 `_post_run_comment` + `_comment_sync_result` 两条独立评论合并为一条汇总评论。
4. **Sub-D ProgressReporter 接入**：修复 `progress_reporter.py` 死代码（`orchestrator.py:329-336` 调 `agent_runner.run(...)` 时不传 `progress_reporter` 参数），把 PhaseComplete 事件写入 ndjson event log。

##### 子特性拆分

| Sub | 名称 | 目标 | 主要工作 |
|-----|------|------|----------|
| A | Verification Gate | commit/push 前自动跑 test_command | `config/schema.py:HooksConfig` 增 `pre_commit` / `pre_push` / `post_sync` 三点；`AgentConfig` 增 `test_command` / `build_command` / `lint_command`（默认可空）；`extensions/orchestrator/git_sync.py` 在 `git commit` 前调 `run_pre_commit_hook`、在 `git push` 前调 `run_pre_push_hook`；失败抛 `VerificationFailed`，orchestrator 捕获后 issue 标 `verification_failed` 不 push |
| B | 结构化报告 | agent 跑完写 Markdown/JSON 报告 | `issue_registry.py:IssueRecord` 增 `report_path: str | None` / `verification_status: str | None` / `verification_output: str | None` 字段（旧 entry 加载兼容）；新增 `extensions/orchestrator/report_writer.py` 暴露 `write(session, workspace) -> Path`；`agent_runner.py` SessionComplete 时调 `report_writer.write` 并把 `report_path` 写回 registry；`git_sync._build_pr_body` 改模板插值，插入 issue 摘要、commit/diff stat、verification 状态、报告链接 |
| C | PR 报告回写 | 把报告回写到 GitCode PR | `tracker.py:TrackerAdapter` 增抽象 `update_pull_request(pr_number, *, body=None, state=None) -> PullRequestRef | None`；`repo_tracker/client.py:RepositoryIssueClient.update_pull_request` 实现 GitCode 平台用 `PATCH /repos/{owner}/{repo}/pulls/{id}?access_token=...`（GitHub / Gitee 列 TODO，先报不支持错误）；`git_sync.py:ensure_pull_request` 拿到 `pr.number` 后调 `tracker.update_pull_request(body=...)`；合并 `agent_runner._post_run_comment` + `git_sync._comment_sync_result` 为单条 `## ClawCodex Run Summary` 汇总评论 |
| D | ProgressReporter 接入 | 修死代码 | `orchestrator.py:329-336` 显式构造 `ProgressReporter` 并传入 `agent_runner.run(...)`；`progress_reporter.py` 把 PhaseComplete 事件写入 `event_log_dir/{id}.ndjson`（与现有 ndjson 通道合并 schema，新加 `{"type": "phase", "phase": "...", "progress": N}`），`issue tail --id N` 可消费 |

##### 背景与缺口

| 缺口 | 当前位置 | 修复方向 |
|------|----------|----------|
| commit/push 前无自动验证 | `agent_runner.py:286-309` 跑完 LLM 直接 `SessionComplete`；`git_sync.py` 只 `git add/commit/push`；`workflow.md:110` 写「Run the existing test suite」仅是 LLM prompt 文本，系统不强制 | Sub-A 引入 `pre_commit` / `pre_push` hook + `test_command`，把 prompt 文本升级为系统强制步骤 |
| `HooksConfig` 生命周期点不完整 | `config/schema.py:188-193` 仅 `after_create` / `before_run` / `after_run` / `before_remove` 四点 | 扩展为 7 个点（含 Sub-A 三个新增 + 现有四个） |
| AgentConfig / CodexConfig 无 verification 字段 | `config/schema.py:157-184` | 增 `test_command` / `build_command` / `lint_command` + `verification.timeout_ms`（默认 600000） |
| `IssueRecord` 无报告字段 | `issue_registry.py:36-58` 字段为 `issue_id/branch_name/commit_sha/pr_number/pr_url/base_branch/status/attempt_count` + 几个 clarification 字段 | 增 `report_path` / `verification_status` / `verification_output` |
| 无结构化报告文件 | `agent_runner.py:440-486` 只写 `.event_logs/{id}.ndjson`（stream events）；`git_sync.py` 不写报告 | Sub-B 新增 `report_writer.py` 写 `.reports/{id}.md` + `.reports/{id}.json` |
| PR body 静态 | `git_sync.py:264-282 _build_pr_body` 写死静态文本 | 改模板插值（Sub-B），后续 Sub-C 再回写 |
| 抽象层无 `update_pull_request` | `tracker.py:30-110 TrackerAdapter` 基类未声明该方法；代码库 0 处 `update_pull_request` / `edit_pull_request` 调用 | Sub-C 抽象 + GitCode 客户端实现 |
| 两条独立评论 | `agent_runner._post_run_comment` (Run Complete) + `git_sync._comment_sync_result` (Git Sync) | Sub-C 合并为单条 `## ClawCodex Run Summary` |
| `progress_reporter` 死代码 | `orchestrator.py:329-336` 调 `agent_runner.run(...)` 不传 `progress_reporter`；模块仅 4 处引用且都是构造参数 | Sub-D 接入主流程 |

##### 实施切片（按 Sub 分组）

**Sub-A Verification Gate**:
1. `config/schema.py` 扩展 `HooksConfig` 增 `pre_commit` / `pre_push` / `post_sync` 三点 + `AgentConfig` 增 `test_command` / `build_command` / `lint_command`（默认可空）+ `verification.timeout_ms` 默认 600000。
2. `extensions/orchestrator/git_sync.py` 在 `git commit` 前调 `run_pre_commit_hook`、在 `git push` 前调 `run_pre_push_hook`；失败时抛 `VerificationFailed`。
3. `orchestrator.py` 在 `git_sync.sync()` 末尾 `finally` 块里调 `run_post_sync_hook(session)`，并把 verification 状态写入 `IssueRecord`。
4. verification 失败时 issue 标 `verification_failed`，agent run 状态记 `failed`，不创建 PR。

**Sub-B 结构化报告**:
1. `issue_registry.py:IssueRecord` 新增 `report_path: str | None` / `verification_status: str | None` / `verification_output: str | None` 字段，旧 entry 加载兼容。
2. 新增 `extensions/orchestrator/report_writer.py`，`write(session, workspace) -> Path` 生成 Markdown（人读）+ JSON（机读）报告。
3. `agent_runner.py` SessionComplete 时调 `report_writer.write` 并把 `report_path` 写回 registry。
4. `git_sync._build_pr_body` 改模板插值，插入 issue 摘要、commit/diff stat、verification 状态、报告链接（`/tmp/symphony_workspaces/agentsdk/_1/.reports/1.md`）。

**Sub-C PR 报告回写**:
1. `tracker.py:TrackerAdapter` 增抽象 `update_pull_request(pr_number, *, body=None, state=None) -> PullRequestRef | None`。
2. `repo_tracker/client.py` 增 `RepositoryIssueClient.update_pull_request`，GitCode 平台用 `PATCH /repos/{owner}/{repo}/pulls/{id}?access_token=...`，payload 含 `body` / `state`；GitHub / Gitee 暂列 TODO（先 raise `NotImplementedError`）。
3. `git_sync.py:ensure_pull_request` 拿到 `pr.number` 后调 `tracker.update_pull_request(body=...)` 把 Sub-B 报告回写 PR。
4. 合并 `agent_runner._post_run_comment` + `git_sync._comment_sync_result` 为单条 `## ClawCodex Run Summary` 汇总评论（含报告链接、verification 状态、commit、PR URL）。

**Sub-D ProgressReporter 接入**:
1. `orchestrator.py:329-336` 显式构造 `ProgressReporter` 并传入 `agent_runner.run(...)`。
2. `progress_reporter.py` 把 PhaseComplete 事件写入 `event_log_dir/{id}.ndjson`（与现有 ndjson 通道合并 schema，新加 `{"type": "phase", "phase": "...", "progress": N}`）。
3. `issue tail --id N` 解析 `phase` 类型事件，打印阶段进度（与现有 `tool_call` / `tool_result` 同列）。

##### 验收标准

- agent 一次工具都没调（`tools=0`）时，verification gate 拦截 push，PR 不被创建，issue 标 `verification_failed`。
- `test_command` 默认值为空时该步骤跳过（不破坏已有无测试项目）。
- agent 跑完 issue registry 的 `report_path` 指向一个真实存在的文件；该文件包含 issue 摘要、commit SHA、verification 状态、diff stat。
- PR body 含「Issue / Branch / Commit / Verification / Report」五段，verification 段落根据结果渲染 ✅/❌。
- PR 开完后 issue 收到**一条**汇总评论（合并原 Run Complete + Git Sync 两条）。
- 完整代码库 0 处对 `tracker.update_pull_request` 之外的非 CRUD PR API 调用（保留可审计性）。
- `progress_reporter.ProgressReporter` 在主流程被构造；`issue tail --id N` 能看到 `{"type": "phase", ...}` 事件。

##### 风险与约束

- verification gate 默认开在 `pre_push`，失败 = 不 push。需在 `workflow.md` 文档里强调，否则用户以为 push 失败是网络问题。
- `test_command` 跑长任务会拖慢 `max_turns=20` 的 issue 跑批，需提供 `verification.timeout_ms` 配置（默认 600000）。
- GitCode `PATCH /pulls` 的 body / state 字段是否被支持需先打一个 dry-run 验证；不支持则回退为「把报告写到 `workspace/.reports/{id}.md` + 在汇总评论里贴报告全文」。
- `_post_run_comment` 与 `_comment_sync_result` 合并时若平台限流，单条评论可能太长，需提供 `summary.max_comment_chars` 截断。
- `progress_reporter` 接入需不破坏 `event_log_dir/1.ndjson` 现有 schema，扩展字段而非替换。
- 与 F-37 的 PR review follow-up 闭环保持兼容：Sub-C 的 `update_pull_request` 应是 F-37 阶段 5/7（同 PR 分支 follow-up）的基础能力，先于 F-37 落地。

##### 配置示例

**示例 1：典型 Python 项目（启用完整验证）**

```yaml
agent:
  test_command: "pytest -x -q"            # 失败 = 阻止 push
  build_command: ""                       # 留空跳过
  lint_command: "ruff check ."            # 失败 = 阻止 push
  verification:
    timeout_ms: 600000

hooks:
  pre_commit: ""                          # 跳过：让 verification 字段负责检查
  pre_push: ""                            # 跳过：让 verification 字段负责检查
  post_sync: ""                           # 跳过：默认无副作用
```

**示例 2：无测试项目（向后兼容）**

```yaml
agent:
  test_command: ""                        # 显式空 = 跳过 verification gate
  build_command: ""
  lint_command: ""

hooks:
  pre_commit:
  pre_push:
  post_sync:
```

**示例 3：需要 hook 做副作用（hook 改文件并 amend commit）**

```yaml
agent:
  test_command: "pytest -x"
  build_command: ""
  lint_command: ""

hooks:
  pre_commit: "black . && isort ."        # 格式化后由 git_sync 自动 re-add + amend
  pre_push: ""                            # 不重复跑测试
  post_sync: ""                           # 默认无清理
```

**示例 4：完全禁用 verification（emergency override）**

```yaml
agent:
  test_command: ""                        # 跳过
  build_command: ""
  lint_command: ""

hooks:
  pre_commit: "true"                      # 显式 no-op
  pre_push: "true"
  post_sync: ""

# 文档注释：等价于 3.1.5 之前的行为，提交不做任何检查
```

**配套说明**：
- `agent.test_command` 等字段跑在 `pre_push` 阶段，**作用域是工作区根目录**。
- `hooks.pre_commit` 跑在 `git add` 之后、`git commit` 之前；可修改工作区，git_sync 会自动 `git add -A && git commit --amend`。
- `hooks.pre_push` 跑在 `git commit` 之后、`git push` 之前；**不应修改工作区**（修改会报错）。
- `hooks.post_sync` 跑在 PR 创建之后；**不应修改工作区**。
- 全部字段留空（`""` 或 `None`）= 跳过该步骤，**与 3.1.5 之前行为完全一致**。

LocalTracker（无 PR 路径）应跳过 Sub-C 的 `update_pull_request` 调用，Sub-B 的报告写到 `workspace/.reports/{id}.md` 即可，不强制回写 PR body。

##### 拟定的设计决定（针对设计稿识别出的 7 个 Open Questions）

设计稿审阅后识别出 7 个未决问题。2026-06-01 起拟定如下方案，每条都明确给出根因、契约/接口形态与落地策略。该节是 Sub-A/B/C/D 实施的「前置合同」，落地时不再重新讨论。

###### 1. ProgressReporter 接口与设计目标错位（解耦方案）

**根因**：`extensions/orchestrator/progress_reporter.py:38` 的 `__init__(self, context: ToolContext)` 把 reporter 绑死到工具系统上下文，而 Sub-D 想要的是 ndjson 落盘通道——两条通道是完全不同的接收方。

**建议：拆成「翻译层 + 通道层」**

```
AgentRunner.on_event(PhaseComplete)
       ↓
ProgressReporter.on_event(event, session)        # 翻译：把 PhaseComplete → 通用 dict
       ↓
ProgressSink.write(payload: dict)                # 通道：决定写到哪里
```

**接口契约**：
- 新增 `extensions/orchestrator/progress_sink.py`，定义 `ProgressSink` 协议：`write(payload: dict) -> None`。
- 三个实现：
  - `ToolContextSink(context: ToolContext)`：调用 `ProgressReportTool._progress_report_call`，保持现有语义。
  - `NdjsonSink(event_log_dir: Path)`：追加到 `event_log_dir/{id}.ndjson`，与现有 `tool_call`/`tool_result`/`text_delta` 同行，新加 `{"type": "phase", ...}` 记录。
  - `CompositeSink(sinks: list[ProgressSink])`：扇出。
- `ProgressReporter.__init__(self, sinks: list[ProgressSink])`，移除 `ToolContext` 依赖。
- Orchestrator 在 `_run_issue` 里根据 `workflow.observability.progress_sinks`（`["ndjson", "tool", "both"]`）显式构造。
- 合并 `agent_runner._write_event_log`（lines 440-486）的重复写盘逻辑，让 `NdjsonSink` 接管，避免一个事件被写两次。

**额外好处**：未来加 stdout sink / metrics sink 不需要改 reporter 类。

###### 2. Hook 执行上下文未约定

**根因**：现有 `workspace._run_hook`（`workspace.py:211-258`）只传 `cwd=workspace.path`，环境变量是系统默认的。`pre_commit` 等 hook 需要知道 `BRANCH`、`COMMIT_SHA` 等运行时信息，文档里完全没说 env 合约，hook 写作者无法落地。

**建议：在文档里固化一张「Hook Env Contract」表**

| Hook | CWD | 必传环境变量 | 触发后可读 |
|------|-----|------------|----------|
| `after_create` | workspace path | `ISSUE_ID`, `ISSUE_IDENTIFIER`, `ISSUE_BRANCH` | `REPO_ROOT?` |
| `before_run` | workspace path | ↑ | — |
| `after_run` | workspace path | ↑ + `AGENT_STATUS`, `AGENT_TURNS`, `AGENT_TOOLS` | `REPORT_PATH` |
| `before_remove` | workspace path | ↑ | — |
| **`pre_commit`**（新增） | repo root | ↑ + `BRANCH_NAME`, `BASE_BRANCH` | `STAGED_FILE_COUNT` |
| **`pre_push`**（新增） | repo root | ↑ + `BRANCH_NAME`, `COMMIT_SHA` | — |
| **`post_sync`**（新增） | repo root | ↑ + `PR_NUMBER`, `PR_URL`, `COMMIT_SHA`, `VERIFICATION_STATUS` | `REPORT_PATH` |

**实现策略**：抽一个统一 helper（在 `workspace.py` 已有 `_run_hook` 基础上扩展为 `_run_named_hook`）：
- 合并 `os.environ` + base env（来自 issue/branch/commit） + hook-specific extra env
- 走 `subprocess_shell` + 沿用 `_run_process` 的 timeout 模式
- 全部 7 个 hook 走同一条路径，CWD/env/timeout 一致，便于单元测试

###### 3. Hook 失败 vs 测试失败的语义重叠

**根因**：verification 字段（typed）和 hook 字段（opaque shell）当前都是任意 shell 命令，失败后果没有差异——都按 FAILED 处理。但角色不同：verification 是「通过/不通过这个变更」的判定，hook 是「给用户可编程的副作用点」。

**建议：在配置层面就把两个角色分开**

| 字段 | 类别 | 失败后果 | 记录字段 |
|------|------|---------|---------|
| `agent.test_command` / `build_command` / `lint_command` | **typed verification** | 阻止 commit/push；issue 标 `verification_failed`；`IssueRecord.verification_status="failed"`, `verification_output=<stdout/stderr>` | `verification_*` |
| `hooks.pre_commit` / `pre_push` / `post_sync` | **opaque hook** | 抛 `HookFailedError`；issue 标 `failed`（走现有 FAILED 路径走 retry） | `last_hook_error`（新增字段） |

**具体规则**：
- 三个 verification 字段默认空字符串 `""` 表示跳过（**保留对无测试项目的兼容**）。
- 三个 hook 字段默认 `None` 表示跳过。
- 同时配置 verification 和 hook 时，按 `verification → pre_commit → commit → pre_push → push` 顺序串行执行，任何一步失败立刻终止后续步骤。
- 在 `IssueStatus` 枚举中**新增 `VERIFICATION_FAILED`**，并新增 `IssueRegistry.mark_verification_failed(issue_id, *, output: str)` 方法。
- 异常类分两个：`VerificationFailed(output: str)` 与 `HookFailedError(hook_name: str, output: str)`，orchestrator 在 `git_sync.sync` 的 try/except 里分支处理。

###### 4. Hook 修改文件的副作用

**两类副作用要分开处理**：

**4a. verification 命令修改文件（如 `black .` 实际改文件）**

建议：verification 字段默认为「只读模式」。

```yaml
agent:
  lint_command: "ruff check ."        # 默认 read-only
  # 若要允许修改后 commit:
  # lint_command:
  #   cmd: "black ."
  #   write: true                       # 显式声明破坏只读契约
```

实现侧：verification 字段解析为 `VerificationCommand(cmd: str, write: bool = False)`。`write=False` 时，命令运行前后对 `repo_root` 做 `git status --porcelain` 快照，命令结束后若工作区脏了，记 WARNING 日志但**不阻止 commit**（用户可能故意改了文件想一起提交——这是不可判定的，留给用户）。

**4b. `pre_commit` hook 修改文件**

`pre_commit` hook 修改工作区后，git_sync 应**自动并入 commit**：

```python
# git_sync.sync 中 pre_commit hook 之后
after_status = get_file_status(repo_root)
if after_status:
    logger.info("pre_commit hook modified %d files; staging", len(after_status))
    self._run_git_checked(["add", "-A"], repo_root)
    self._run_git_checked(["commit", "--amend", "--no-edit"], repo_root)
    commit_sha = self._run_git_output(["rev-parse", "HEAD"], repo_root)
```

这样 hook 写作者修改文件的副作用是**确定性的**：要么进入同一个 commit，要么违反「修改后未 add」导致 push 失败——不会出现「hook 改了但 commit 不含」的诡异状态。

`pre_push` 和 `post_sync` 时序上 PR 已开/即将开，**不允许修改工作区**（修改会直接报错）：

```python
if hook_name in ("pre_push", "post_sync") and get_file_status(repo_root):
    raise HookFailedError(
        hook_name,
        f"{hook_name} hook modified working tree; this is not allowed",
    )
```

###### 5. 报告文件生命周期（cleanup 时机）

**当前时序回顾**：
- `workspace.cleanup(session.issue)` 在 `orchestrator.py:_run_issue` 的 finally 块最后执行（line 387-394），会 `shutil.rmtree(workspace_path)`，**`.reports/` 随之被删除**。
- 报告随 workspace 一起被删，审计丢失。

**建议：双层存储 + 复用现有 `before_remove` 钩子**

```
~/.clawcodex/
  reports/
    {tracker_kind}/
      {owner}/{repo}/                 # 来自 workflow.tracker.{kind,owner,repo}
        {issue_id}/
          {run_id}.md                  # run_id = "run-{attempt_count}-{timestamp}"
          {run_id}.json
```

**实施细节**：
- `report_writer.write()` **同步双写**：
  - `workspace/.reports/{id}.md`（瞬态，给 in-workspace 使用，cleanup 时删除无所谓）
  - `~/.clawcodex/reports/.../{run_id}.md`（持久，cleanup 之后还在）
- `report_writer.write()` 在 `agent_runner._post_run_comment` 之前调用（line 344-347），先写盘再发评论，这样评论里可以引用持久化路径。
- 复用现有 `before_remove` 钩子作为**容错备份**：双写失败时 `before_remove` 可以 fallback 把 `workspace/.reports/` 复制到持久目录，给用户自定义兜底策略的口子。
- 加保留策略：`workflow.reports.retention_days = 90`（默认），由 orchestrator 定期清理。

**对 `cleanup()` 时机本身**：**保留现状**——每次 session 结束都清理 workspace，不为保留报告延后 cleanup。报告的持久化是 `report_writer` 的职责，不是 `workspace` 的职责。明确分层。

###### 6. 「报告路径」字段的循环引用

**根因**：本节「子特性拆分」表 B 行原写「内容包括 ... 报告路径」是 typo，路径就是报告自己所在的文件路径，循环引用。

**建议：明确区分「报告的内容」与「报告的引用」**

报告文件 `.reports/1.md` 内部**不写自身路径**，只写：
- Issue 摘要（identifier + title + url）
- turns/tools 计数
- verification status + output（截断到 4KB）
- commit SHA + diff stat（`--stat` 输出）
- run_id（attempt 编号 + 时间戳）

报告文件的**外部引用**写在两个地方：
- **PR body**：由 `git_sync._build_pr_body` 模板插值，渲染时根据已知的 `report_path` 生成 `Report: /absolute/path/to/.reports/1.md` 这一行。
- **汇总评论**：合并 `_post_run_comment` + `_comment_sync_result` 后也引用同一路径。

也就是说，**报告的路径是 PR 评论 / PR body 的元数据，不是报告本身的内容**。这样就消除了循环。

如果出于审计需要，**路径可以以 `metadata` 区单独写一份**（如 `<!-- metadata: report_path = ... -->` 这种 HTML 注释风格），既保留信息又不污染正文。或者干脆让 PR body / 评论里用 `report_filename` 这样的相对名（如 `1.md`），调用方根据 issue_id 拼接完整路径——这样报告文件里不出现任何路径字符串，最干净。

###### 7. 配置示例具有误导性

**原示例问题**：

```yaml
hooks:
  pre_commit: "echo 'pre-commit verification'"   # 永远成功，没有验证效果
  pre_push: "echo 'pre-push verification'"        # 同上
  post_sync: "echo 'post-sync cleanup'"           # 同上
```

**建议**：替换为「能正确表达语义的」四组示例，详见本节「配置示例」小节开头的四组 YAML。所有 hook 字段默认 `""` 或 `None` 表示跳过——**保留对旧项目（无 verification）的完全兼容**，用户感知不到行为变化。

##### 第二轮审阅补遗（2026-06-01）

针对首轮「拟定的设计决定」外的 5 个未决项的补遗。落地时与首轮 7 个方案**合并实施**，不再单独迭代。

| # | 项 | 补遗内容 | 涉及 Sub |
|---|----|---------|---------|
| 1 | IssueStatus 枚举 | 在 `issue_registry.py:24-33` 新增 `VERIFICATION_FAILED = "verification_failed"` 枚举值；新增 `IssueRegistry.mark_verification_failed(issue_id, *, output: str)` 方法；orchestrator 捕获 `VerificationFailed` 时调此方法（而不是 `mark_failed`）；F-39 `agent:retry` 触发时把 `VERIFICATION_FAILED` 也重置回 `PENDING`；新增 `TERMINAL_STATUSES` 冻结集合，合并 `COMPLETED/FAILED/ABANDONED/VERIFICATION_FAILED`，统一散落的终态判断 | A |
| 2 | 汇总评论时序（Option A） | agent_runner.SessionComplete 立刻发 placeholder 评论（body 含 `⏳ This summary is being prepared. It will be updated once git sync and verification complete.`），把 comment_id 存到 `AgentSession.summary_comment_id`；git_sync.sync 末尾在拿到 commit_sha / PR URL / verification 全部信息后调 `tracker.update_comment(summary_comment_id, body=完整汇总)`；新增 `TrackerAdapter.update_comment(comment_id, *, body) -> None` 抽象；3 个平台实现：GitHub/Gitee/GitCode 用 `PATCH /repos/{o}/{r}/issues/comments/{id}`，Linear 用 GraphQL `updateIssueComment`，LocalTracker 用 ndjson 临时文件 + `os.replace` 原子替换 | C |
| 3 | 重跑幂等性 run_id | `run_id` 由 `agent_runner.SessionComplete` 显式构造并传入 `report_writer.write(session, workspace, run_id=...)`，避免 report_writer 自己猜 attempt_count；格式 `run-{attempt_count:02d}-{UTC_ts}`（`datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")`）；F-39 `agent:follow-up` 触发时 `attempt_count` 不变，使用 `run-N-followup-M-{UTC_ts}` 避免与主 run 冲突；持久化路径 `~/.clawcodex/reports/{tracker}/{owner}/{repo}/{issue_id}/{run_id}.{md,json}` | B |
| 4 | 文档 ID 一致性 | FEATURE_PLAN.md 节标题已加 `(F-38)` 标识（见本节标题）；PROGRESS.md 「规划文档」列已写 `docs/FEATURE_PLAN.md → 3.1.5 验证与报告闭环设计`，双向映射存在；这是**设计文档（按主题 §3.1 编排）与跟踪文档（按 ID F-N 索引）的正常分层**，不需要合并到同一个 ID 系统；本节底部加「设计章节 ↔ 功能 ID 反向索引表」便于快速跳转 | 文档 |
| 5 | test_command 触发器归属 | `agent.test_command` / `build_command` / `lint_command` **只在 pre_push 阶段跑**（不在 pre_commit 跑）；pre_commit 阶段只允许跑 `hooks.pre_commit`（典型用法：formatter，文件改动会被自动 amend 进 commit）；pre_commit 不重命名（保留 Git 生态术语 `pre-commit hook` 习惯）；`workflow.md` 注释里明确「pre_commit 适合改文件类副作用，verification 类请用 agent.test_command 字段跑在 pre_push 阶段」；pre_commit hook 改文件后 amend 失败 → 抛 `HookFailedError("pre_commit", "amend failed: <reason>")` 标 FAILED | A |

**第二轮 5 项的落地顺序**：

| 补遗 | 依赖的首轮方案 | 落地顺序 |
|------|--------------|---------|
| 1. IssueStatus 枚举 | 3（verification vs hook 分层） | 与首轮 3 同批 |
| 2. 汇总评论时序 | — | 独立，可与首轮 C 并行 |
| 3. 重跑 run_id | 5（报告双写） | 与首轮 5 同批 |
| 4. 文档 ID | — | 文档收尾（已完成节标题改动） |
| 5. test_command 触发器 | 3 + 4（hook 改文件） | 与首轮 3、4 同批 |

**合并实施顺序**：首轮 1 → (首轮 2 + 3 + 补遗 1) → (首轮 4 + 补遗 5) → (首轮 5 + 补遗 3) → 补遗 2 → 首轮 6 → 7。

##### 7 个方案的相互依赖与实施顺序

| 方案 | 依赖的其他方案 | 落地顺序 |
|------|--------------|---------|
| 1. ProgressReporter 解耦 | 独立，可先做 | 1st |
| 2. Hook Env Contract | 3（hook 失败语义） | 2nd |
| 3. Verification vs Hook 分层 | 2 | 2nd（与 2 并行） |
| 4. Hook 文件副作用 | 3 | 3rd |
| 5. 报告生命周期 | 1（reporter 解耦后才能干净地写） | 3rd |
| 6. 报告路径去重 | 5 | 4th |
| 7. 配置示例 | 2、3、4 | 最后（文档收尾） |

**实施顺序建议**：1 → (2 + 3) → 4 → 5 → 6 → 7。每完成一组就更新本节相应章节，把「拟定」沉淀为「已确定」。

##### 依赖与协同

- **依赖 F-1**：F-38 全部 Sub 都在 Orchestrator 主流程内，依赖现有 `git_sync` / `agent_runner` / `issue_registry`。
- **先于 F-37**：F-37 阶段 5/7 需要的「同 PR 分支 follow-up 修改」依赖 F-38 Sub-C 的 `update_pull_request` 能力。
- **与 F-36 兼容**：LocalTracker 走 `pending_review` 路径不创建 PR，F-38 Sub-C 在该路径下应跳过 PR body 改写。
- **不破坏 `progress_reporter` 现有 4 个引用点**：Sub-D 接入后，单元测试覆盖原参数接口。

---

---

#### 二十一.3 F-39 Orchestrator Issue 重跑入口

**状态**: ✅ 完成（Sub-A~F 全部落地；E2E 阶段 10-11 待真实环境验证）
**优先级**: P0
**目标**: 在 `extensions/orchestrator` 引入「重做意图」显式表达通道,让用户在 GitCode / GitHub / Gitee 等开源社区场景下能通过加 label / 写命令 / 跑 CLI 三种方式之一,表达「重置重跑」「同 PR 叠 commit」「永久跳过」意图,无需改 registry.json 或重启 daemon。

##### 背景与现状

2026-06-01 在 `chadwweng/AgentSDK` 跑完 issue #1 后,用户想「让 agent 重做」或「在同一 PR 上再改一版」,但当前 orchestrator 4 层防御(内存 `completed` set / IssueRegistry `is_completed` / `has_pr` / `find_pull_request`)只支持「PR 存在 = 已处理」语义,不支持「关 PR = 重做」语义。关掉 PR 之后下一轮 poll 仍被 ①②③ 任意一层拦截,用户被迫:

- 手动改 `~/.clawcodex/orchestrator/.../registry.json`(易污染、需停 daemon)
- 删除远端 PR branch(不可审计、误删风险)
- 把 issue 在 tracker 端转 terminal state(反方向,会被永远排除)

这在开源社区场景下尤其突出:外部贡献者无法直接修改本地 registry,只能「关 PR」表达重做意图,但 orchestrator 完全无视这个意图。

##### 三种重做意图的语义矩阵

| Label / 命令 | 语义 | 对本地 IssueRecord | 对远程 PR | 对远程 issue | 对 agent run |
|---|---|---|---|---|---|
| `agent:retry` | 重置 + 重跑整个 issue | 清空 `status` → `pending`,删 `commit_sha` / `pr_number` / `pr_url` / `report_path`;`retry_count++` | 关闭旧 PR(状态 `closed` `not merged`) | 加 `agent:retry` 自检注释(可选) | 新 workspace、新 agent run |
| `agent:follow-up` | 保留 PR,在同 PR branch 叠 commit | `status` 保持 `completed`,`pr_number` 不变,`attempt_count++` | 不动;`update_pull_request` 走 F-38 Sub-C 入口追加 commit | 不动 | 同 workspace 同 branch,prompt 强调「只处理 follow-up」 |
| `agent:blocked` | 永久跳过该 issue | `status` 写 `abandoned` | 不动 | 加 `agent:blocked` 自检注释 | 永不 launch |

**label 互斥优先级**:若 issue 同时存在多个 intent label,以「更保守」为准:`agent:blocked` > `agent:follow-up` > `agent:retry`。理由:「保留 PR 改动证据」>「重置」;「永久跳过」>「重做」。

##### 子特性拆分

| Sub | 名称 | 目标 | 主要工作 |
|-----|------|------|----------|
| A | Label 解析 + 意图分发 | 把 label 映射到「重置/follow-up/跳过」三态 | `extensions/orchestrator/tracker.py:TrackerAdapter` 增 `extract_intent_from_labels(labels) -> Intent` 抽象;`extensions/orchestrator/repo_tracker/client.py:RepositoryIssueClient.fetch_candidate_issues` 在返回前用 `_OPEN_STATE_ALIASES` 之外的「intent label」识别;`extensions/orchestrator/issue_registry.py:IssueRecord` 新增 `intent: Literal["none","retry","followup","blocked"]` + `retry_count: int` + `last_command_at: str | None`;`extensions/orchestrator/orchestrator.py:_poll_and_dispatch` 在 `has_pr` 判断之前先看 intent |
| B | 重置重跑 (`agent:retry`) | 清空本地状态 + 关闭远程 PR | 新增 `IssueRegistry.reset_for_retry(issue_id)` 方法,清空 `status` / `commit_sha` / `pr_number` / `pr_url` / `report_path` 并 `retry_count++`;`tracker.py:TrackerAdapter.close_pull_request(pr_number) -> bool` 抽象;`repo_tracker/client.py:RepositoryIssueClient.close_pull_request` 实现 `PATCH /repos/{owner}/{repo}/pulls/{id}?state=closed`;`orchestrator.py` 在 launch 前若 intent=retry,先调 `close_pull_request(pr_number)` 再 launch 新 run |
| C | Follow-up 叠 commit (`agent:follow-up`) | 不开新 PR,复用原 branch | `orchestrator.py` 检测 intent=followup 时,跳过 workspace 创建(复用现有 branch),用上次 run 的报告作为上下文;`extensions/orchestrator/git_sync.py:GitSyncService.sync` 加 `mode="followup"` 分支,只 `git commit` + `git push`,不创建新 PR;`IssueRecord.attempt_count++`;依赖 F-38 Sub-C 写新 commit 到 PR body(等 F-38 落地) |
| D | Comment 命令解析 | `/agent retry` `/agent follow-up` 触发 | `tracker.py:TrackerAdapter` 增 `fetch_issue_command_intent(issue_id, since_comment_id) -> Intent | None`;`repo_tracker/client.py` 复用 `fetch_new_comments_since` 拉新评论,正则匹配 `^/agent\s+(retry|follow-up|unblock)`;orchestrator 在 launch 前调用,合并 label 意图与 command 意图(以更保守者为准);comment 触发后由 orchestrator 发 bot 确认评论 `## ClawCodex: 已受理 ${command},下一轮 poll 开始执行` |
| E | CLI 兜底命令 | `issue retry` 提供本地入口 | `extensions/orchestrator/cli/issue.py` 增 `add_retry_parser` 与 `_run_retry(registry, args)`;支持 `--mode {reset,followup,unblock}` + `--id` + `--reason` + `--force`(绕过 `max_retries_per_issue` 限频);`IssueRegistry` 增 `unblock(issue_id)` 方法(把 `abandoned` 状态回滚);命令发一条本地 audit 日志 `~/.clawcodex/orchestrator/audit.jsonl` 记录 `{ts, operator, issue_id, mode, reason}` 便于追溯 |
| F | 限频 + 角色校验 | 防滥用 | comment 命令默认要求「issue 作者」或「仓库 maintainer」才能触发(`tracker.py:TrackerAdapter` 暴露 `is_maintainer(issue_id, login) -> bool`,依赖 F-37 Sub-B 的 `fetch_issue_comments` 拿作者信息);`IssueRecord.retry_count >= max_retries_per_issue(默认 3)` 时即使加 label 也拒绝重置(写一条 `agent:retry-rejected` label + 评论说明);`audit.jsonl` 记 limit 触发 |

##### 数据模型扩展

```python

# extensions/orchestrator/issue_registry.py
class IssueRecord:
    # 现有字段
    issue_id: str
    issue_identifier: str
    branch_name: str | None
    commit_sha: str | None
    pr_number: str | None
    pr_url: str | None
    base_branch: str
    status: IssueStatus
    created_at: float
    updated_at: float
    attempt_count: int
    # --- 新增字段 ---
    intent: Literal["none", "retry", "followup", "blocked"] = "none"
    retry_count: int = 0
    last_command: str | None = None        # 最近一次 /agent 命令内容
    last_command_at: float | None = None   # 最近一次 /agent 命令时间戳
    last_command_author: str | None = None # 最近一次 /agent 命令作者
```

新增方法:

```python
class IssueRegistry:
    def reset_for_retry(self, issue_id: str) -> IssueRecord | None: ...
    def mark_followup(self, issue_id: str) -> IssueRecord | None: ...
    def unblock(self, issue_id: str) -> IssueRecord | None: ...
    def increment_retry(self, issue_id: str) -> IssueRecord | None: ...
```

##### 抽象接口扩展(TrackerAdapter)

```python
# extensions/orchestrator/tracker.py
class TrackerAdapter:
    # ... 现有接口 ...

    def extract_intent_from_labels(self, labels: list[str]) -> str:
        """返回 'retry' / 'followup' / 'blocked' / 'none' 之一。"""
        ...

    async def close_pull_request(self, pr_number: str) -> bool:
        """关闭远程 PR(closed, not merged)。返回是否成功。"""
        ...

    async def fetch_issue_command_intent(
        self, issue_id: str, since_comment_id: str | None
    ) -> tuple[str, str, str] | None:
        """返回 (intent, command_body, author_login) 或 None。"""
        ...

    async def add_label(self, issue_id: str, label: str) -> bool:
        """(可选) 自检时给 issue 加 label,例如 `agent:retry-rejected`."""
        ...
```

##### 配置 Schema(workflow.md)

```yaml
agent:
  retry:
    enabled: true
    intent_labels:
      retry: "agent:retry"
      followup: "agent:follow-up"
      blocked: "agent:blocked"
    max_retries_per_issue: 3
    comment_command_enabled: true
    comment_command_required_role: "author_or_maintainer"  # 或 "anyone"
    audit_log_path: "~/.clawcodex/orchestrator/audit.jsonl"
```

##### 实施切片

1. `tracker.py:TrackerAdapter` 增 `extract_intent_from_labels` / `close_pull_request` / `fetch_issue_command_intent` / `add_label` 四个抽象,默认实现(子类的 no-op fallback 避免 LocalTracker 强制实现)。
2. `repo_tracker/client.py:RepositoryIssueClient` 实现上述四个方法(GitCode 优先,GitHub / Gitee 列 TODO),其中 `close_pull_request` 走 `PATCH /repos/{owner}/{repo}/pulls/{id}?access_token=...&state=closed`。
3. `issue_registry.py:IssueRecord` 增 `intent` / `retry_count` / `last_command*` 字段;新增 `reset_for_retry` / `mark_followup` / `unblock` / `increment_retry` 方法;旧 entry 加载兼容(新字段 default)。
4. `orchestrator.py:_poll_and_dispatch` 增 intent 前置判断:label 解析 + comment 命令解析 + 合并;launch 路径根据 intent 分流(reset / followup / skip)。
5. `orchestrator.py` 在 intent=retry 时调 `close_pull_request(pr_number)`,再 launch 新 run。
6. `git_sync.py:GitSyncService.sync` 加 `mode` 参数;`mode="followup"` 走「只 commit/push,不开 PR」分支。
7. `cli/issue.py` 增 `retry` 子命令,实现 `_run_retry`;`audit.jsonl` 写本地审计。
8. `orchestrator.py` 增 `max_retries_per_issue` 配置(默认 3);`IssueRecord.retry_count` 超过上限拒绝重置并发评论 + `agent:retry-rejected` label。
9. 单元测试:label 解析、命令正则、retry_count 限频、role 校验、registry.reset_for_retry 状态机。
10. 端到端:在 issue #1 上加 `agent:retry` label → 60s 内观察 daemon 日志确认走 retry 路径 → issue 重新 running → 完成后 PR 编号变化。
11. 端到端:在 issue #1 上加 `agent:follow-up` label → daemon 检测到后不关 PR,在同 branch 叠 commit → PR 编号不变,commit 数 +1。

##### 验收标准

- 用户在 GitCode issue #1 上加 `agent:retry` label 后,**60s 内**(下一轮 poll)daemon 日志输出 `Issue 1 retry intent detected`,issue 状态从 `completed` 回到 `running`,旧 PR 被关闭,新 PR 编号(原 PR 编号 + N)。
- 用户在 issue #1 上加 `agent:follow-up` label 后,daemon 在同 branch 上 commit + push,**不开新 PR**,原 PR 编号不变,commit 数 +1。
- 用户在 issue comment 发 `/agent retry`,且非原作者时,**daemon 拒绝执行**并发评论 `## ClawCodex: 仅 issue 作者或 maintainer 可触发 /agent retry`。
- `agent:retry` 累计触发 4 次(超过 `max_retries_per_issue=3`)后,daemon 拒绝再次 reset,issue 上自动加 `agent:retry-rejected` label,评论中说明「已达到最大重试次数,需人工处理」。
- `clawcodex orchestrator issue retry --id 1 --mode reset --reason "wrong approach"` 立即生效,等价于 label 触发的 reset 路径,audit.jsonl 有一行 `{ts, operator, issue_id, "reset", "wrong approach"}`。
- 重置不污染已有 issue_registry.json 旧 entry schema:加载老 JSON 时 `intent` / `retry_count` 默认值生效。
- 与 F-37 协同:`agent:follow-up` 触发的 follow-up run,行为与 F-37 阶段 6 的「review-fix prompt builder」一致(只改检视意见,不改 issue 范围)。
- 与 F-38 协同:`agent:follow-up` 触发的 follow-up run 完成后,F-38 Sub-C 调 `update_pull_request` 把新 commit / 新 diff stat / 新 verification 结果追加到 PR body 末尾(以 `## ClawCodex Follow-up #N` 段落追加,非覆盖)。

##### 风险与约束

- **LLM 自触发风险**:comment 命令必须做 role 校验,否则 LLM 在自动响应里写 `/agent retry` 会自触发。
- **label 互斥冲突**:`agent:retry` + `agent:follow-up` 同时存在时需定义优先级;本期以「更保守 = follow-up」为准,后续可加 `intent_priority` 配置。
- **重置不删 git history**:reset 走「关 PR + 删本地 registry entry」,但 git remote 的 commit/branch 仍存在,这是预期行为(便于审计)。
- **限频与人工 bypass**:CLI 兜底命令的 `--force` 参数可绕过 `max_retries_per_issue` 限频,需写 `audit.jsonl` 高优条目。
- **与 F-37 耦合**:`agent:follow-up` 依赖 F-37 阶段 6 的「review-fix prompt builder」;F-37 未落地时,follow-up 路径退化为「同 branch agent run」(语义较弱的 follow-up)。
- **平台差异**:GitCode `PATCH /pulls?state=closed` 与 GitHub `PATCH /repos/{owner}/{repo}/pulls/{number}` 端点路径不同,需在 `repo_tracker/client.py` 平台分发处分别实现;Gitee / GitHub 暂列 TODO(同 F-38 Sub-C 的处理)。
- **comment 命令回放**:用户编辑老评论(非最新一条)发命令时,应只处理 `created_at > since_comment_id` 的新评论;`fetch_new_comments_since` 已实现该语义,直接复用。

##### 与现有特性的关系

| 特性 | 关系 |
|---|---|
| F-1 Orchestrator 自主模式 | F-39 是 F-1 主循环的扩展,不替换原有 4 层防御 |
| F-36 LocalTracker | `close_pull_request` 在该路径下 no-op + warning;`unblock` 行为对 LocalTracker 等价(把 `pending_review` / `abandoned` 状态回滚到 `pending`) |
| F-37 PR 检视意见自动修复 | `agent:follow-up` 路径是 F-37 的 label 入口;F-37 未落地时 follow-up 退化为「同 branch 普通 agent run」 |
| F-38 验证与报告闭环 | Sub-B 报告回写复用 F-38 Sub-C 的 `update_pull_request`;follow-up 触发的报告追加为 `report_path_v{N+1}` 序列 |
| F-38 Sub-D progress_reporter | retry 路径下每次新 run 是新 session,PhaseComplete 写 ndjson 行为照常工作 |

##### 依赖与协同

- **依赖 F-1、F-38 Sub-C**:`close_pull_request` 与 F-38 Sub-C 共享 `PATCH /pulls` 协议层(Sub-C 改 body,F-39 Sub-B 改 state);先于 F-38 落地要冗余实现一次,建议先做 F-38 Sub-C,F-39 复用。
- **与 F-37 强协同**:`agent:follow-up` 路径是 F-37「PR 检视意见自动修复」的 label 入口;F-37 未落地时 follow-up 退化为「同 branch 普通 agent run」。
- **不破坏 F-38 Sub-D**:`progress_reporter` 的 PhaseComplete 写 ndjson 逻辑在 retry 路径下应照常工作(每次新 run 是新的 session)。
- **不破坏 F-36 LocalTracker**:LocalTracker 无远程 PR 概念,`close_pull_request` 在该路径下应 no-op 并打 warning 日志;`issue_registry.unblock` 行为对 LocalTracker 等价(把 `pending_review` / `abandoned` 状态回滚到 `pending`)。

##### 实际落地（2026-06-01）

| 维度 | 改动 |
|---|---|
| **核心抽象** | `extensions/orchestrator/tracker.py` 新增 `Intent` str-Enum（NONE/RETRY/FOLLOWUP/BLOCKED）、`Command` enum（RETRY/FOLLOWUP/UNBLOCK）、`CommandIntent` 数据类（带 author_login/comment_id/comment_body）、`DEFAULT_INTENT_LABELS`、`intent_from_label_set()`、`parse_agent_command()`、`command_to_intent()`、`merge_intents()`、`extract_intent_from_labels()` 默认实现、`close_pull_request()` 默认实现、`fetch_issue_command_intent()` 默认实现（返回 `CommandIntent \| None`） |
| **适配器** | `extensions/orchestrator/repo_tracker/{client,adapter}.py` 增 `close_pull_request`（`PATCH /repos/{owner}/{repo}/pulls/{number}` + `state=closed`，422 视为成功）+ `intent_labels` 参数 + `fetch_issue_command_intent` 委派到 `fetch_new_comments_since`；`local_tracker/adapter.py` 增 `close_pull_request` no-op + `fetch_issue_command_intent` 扫描本地 `*.comments.ndjson` + `intent_labels` 参数；`linear/adapter.py` 增 `intent_labels` 参数 + `extract_intent_from_labels` |
| **状态机** | `extensions/orchestrator/issue_registry.py:IssueRecord` 增 5 个字段（`intent/retry_count/last_command/intent_source/command_cursor`）+ 5 个方法（`mark_intent/clear_intent/reset_for_retry/increment_retry_count/unblock`）；`_load()` 过滤未知字段保证老 JSON 兼容；`unblock()` 把 ABANDONED 滚回 PENDING 且清 intent，`retry_count` 保留以便限频继续生效 |
| **调度逻辑** | `extensions/orchestrator/orchestrator.py` `_poll_and_dispatch` 增 `_resolve_intent()`（label+command 合并）、`_resolve_command_intent()`、`_post_command_acknowledgement()`（"已受理"评论 + cursor）、`_prepare_intent_reset()`（Sub-B 关 PR + reset）、`_prepare_intent_session()`（Sub-C 设 `run_kind=agent_followup` + branch 复用）、`_is_command_author_eligible()`（Sub-F fail-closed）、`_reject_unauthorized_command()`（Sub-F 拒绝评论 + audit）、`_check_retry_rate_limit()`（Sub-F 限频）、`_post_retry_rejection()`（Sub-F 拒绝评论 + 标签尝试）、`_log_audit_event()`（daemon-side 审计）。UNBLOCK 命令触发时把 ABANDONED 回滚到 PENDING 并清 intent |
| **Git 同步** | `extensions/orchestrator/git_sync.py:GitSyncService.sync()` 新增 `mode: str = "default"` 参数；`mode="followup"` 顶部短路要求 `session.pull_request` 存在（fail-fast），后续走现有 followup_pr 分支只 commit/push 不开新 PR |
| **配置** | `extensions/orchestrator/config/schema.py:AgentConfig` 新增 `max_retries_per_issue: int = 3` + `allow_anyone_to_retry: bool = False`；`WorkflowConfig.from_dict()` 加载两个新字段 |
| **CLI** | `extensions/orchestrator/cli/issue.py` 新增 `retry` 子命令（`--mode {reset,followup,unblock}` + `--id` + `--reason` + `--force` + `--max-retries` + `--operator` + `--workspace/--workflow`）+ `_run_retry()` + `_append_audit_log()`（写 `~/.clawcodex/orchestrator/audit.jsonl`）+ `_resolve_operator()`（`$USER` / `os.getlogin()` / "unknown"）；dispatch 在 `run()` 末尾 |
| **测试** | 新增 6 个测试文件 153 个用例：`test_orchestrator_f39_{intent,retry,followup,command,retry_cli,ratelimit}.py`；`Intent`/`Command`/`CommandIntent` 单元覆盖、`IssueRecord` JSON round-trip + 老 schema 兼容、`_run_retry` 三模式（reset/followup/unblock）+ `--force` 旁路 + `--max-retries` 覆盖 + rate-limit 拒绝（rc=3 不动 state）、`orchestrator._is_command_author_eligible` 7 种场景（allow_anyone/None/false/空/author 匹配/other/no record）、`_check_retry_rate_limit` at-limit 拒 + force 放、`_reject_unauthorized_command` 评论 + audit |
| **回归** | orchestrator 套件 231/231 通过（含 78 个原有用例 + 153 个 F-39 新增）；`tests/manual_e2e_f38.py` 不受影响（E2E 阶段 10-11 待真实 GitCode/GitHub issue 验证） |

##### 设计决定（落地记录）

1. **`CommandIntent` 携带 author_login**（F-39 Sub-D→Sub-F 接口扩展）：早期 Sub-D 用 `Command | None` 返类型，Sub-F 角色校验需要 author_login，所以把返回类型升级为 `CommandIntent(command, author_login, comment_id, comment_body)` 数据类，向后兼容通过 `intent.command` 字段读取命令值。
2. **role check fail-closed**（LLM 自触发防护）：`author_login is None` / 空字符串直接拒绝（即使配 `allow_anyone_to_retry=True` 也会放行）；`author_login == "clawcodex"` 永远放行（bot 自己），其余需匹配 `IssueRecord.author_login`（澄清流填的作者）。
3. **`unblock()` 总是清 intent**（不是真 no-op）：docstring 写"非 ABANDONED 时不修改 status"，但 intent/intent_source/last_command 总是清零——保证下次 poll 重新走 `_resolve_intent()`；`retry_count` 不清以维持限频。
4. **CLI `--force` 高优 audit**：`audit.jsonl` 写 `{event: "retry", priority: "high", force: true, retry_count: N, max_retries_per_issue: M, rate_limited: false}`，与正常 retry 区分；`--force` 缺省时 rate-limit 命中写 `{event: "retry_rejected", priority: "high", rate_limited: true}`。
5. **限频边界**：`retry_count < max_retries_per_issue` 放行（默认 3 表示可重试 3 次）；`retry_count >= max` 拒（CLAUDE.md 验收标准 4 描述为"累计触发 4 次后拒绝"——其实是第 4 次触发时 retry_count 已经是 3，命中 3 >= 3 边界，与设计一致）。
6. **审计日志差异**：daemon `_log_audit_event` 与 CLI `_append_audit_log` 字段集略有不同（daemon 写更少字段，CLI 写 retry_count/max_retries/rate_limited），都满足设计文档的最小集 `{ts, operator, issue_id, mode, reason}`；后续可统一字段。
7. **审计日志路径**：`~/.clawcodex/orchestrator/audit.jsonl`（设计文档指定）；测试通过 `patch(_DEFAULT_AUDIT_LOG_PATH, ...)` 重定向到 tmpdir。

---

---

#### 二十一.4 F-41 Coordinator 轻量工具集

**状态**: ✅ 已完成
**优先级**: P1
**跟踪文档**: `docs/PROGRESS.md` → `F-41: Coordinator 轻量工具集`

### 目标

给 Coordinator Agent 配置独立的轻量工具集，使其可直接处理简单查询而不必为每个请求创建 Worker Agent，同时确保写操作类工具（Edit、Write、Bash、Grep、Glob）始终隔离，强制委派复杂任务给 Worker。

### 背景

Coordination 模式启用时（`CLAUDE_CODE_COORDINATOR_MODE=true`），Coordinator 需要同时扮演两个角色：(a) 快速响应简单用户请求（搜索网页、读取文件），(b) 将复杂实现任务委派给 Worker Agent。此前 Coordinator 只有三个管理工具（Agent / SendMessage / TaskStop），任何实际工作——包括读文件、搜网页——都必须创建 Worker，不仅增加延迟，而且浪费模型 token 做无意义的任务分配。

### 设计方案

在 `src/coordinator/mode.py` 定义 `_COORDINATOR_ALLOWED_TOOLS` 白名单：

```python
_COORDINATOR_ALLOWED_TOOLS = {
    "Agent", "SendMessage", "TaskStop",       # 原有的 Agent 管理工具
    "Read", "WebSearch", "WebFetch",          # 新增：轻量读/查工具
}
```

`filter_coordinator_tools(tools)` 通过模糊名称匹配（`startswith` 优先、`in` 兜底、`inverse in` 后备）从全部工具中筛选出属于白名单的工具实例。

### 变更清单

| 文件 | 改动 |
|------|------|
| `src/coordinator/mode.py` | `_COORDINATOR_ALLOWED_TOOLS` 新增 `Read` / `WebSearch` / `WebFetch`；`filter_coordinator_tools` 逻辑不变 |
| `src/coordinator/prompt.py` | 提示词 §2 "Your Tools" 各区段展开列出 Read、WebSearch、WebFetch 的用途说明 |
| `src/repl/core.py` | 注释同步更新，反映 Coordinator 的实际工具能力 |

### 工具隔离策略

| 角色 | 拥有的工具 | 能力边界 |
|------|-----------|---------|
| **Coordinator** | Agent / SendMessage / TaskStop / Read / WebSearch / WebFetch | 读文件、搜网页、管理 Worker，**不可**执行代码或写文件 |
| **Worker** | 完整工具套件（Bash / Write / Edit / Read / Grep / Glob / WebSearch / WebFetch / ...） | 完整的编码与调试能力 |

### 验收标准

1. `CLAUDE_CODE_COORDINATOR_MODE=true` 下 Coordinator 可调用 `Read` 读取文件内容。
2. Coordinator 可调用 `WebSearch` 进行网络搜索，`WebFetch` 获取指定 URL 内容。
3. Coordinator **不能**调用 `Bash`、`Write`、`Edit`、`Grep`、`Glob`——这些工具在 `filter_coordinator_tools` 输出中被过滤。
4. Worker Agent 不受影响，工具集保持不变。
5. Coordinator 提示词中列出 6 个可用工具（Agent / SendMessage / TaskStop / Read / WebSearch / WebFetch），且不误列被过滤的工具。
6. `filter_coordinator_tools()` 返回正确的 6 个工具实例（名称模糊匹配正确）。
7. 231/231 orchestrator 回归测试通过。

### 风险与约束

- **提示词与实现需同步**：`prompt.py` 的 "Your Tools" 列表必须与 `_COORDINATOR_ALLOWED_TOOLS` 手动保持同步——无自动校验机制。
- **工具名称模糊匹配**：`filter_coordinator_tools` 用的不是精确匹配而是三后备匹配策略，如果新增一个名称以 "Web" 开头的非预期工具可能导致误放行。Mitigation：白名单设置小（仅 6 个），且新增工具需 review 白名单。
- **不涉及 Worker 工具变更**：Worker 的 `filter_worker_tools` 逻辑不变，与 Coordinator 无关。
- **CLAUDE.md 注释同步风险**：`src/repl/core.py:8-30` 的注释手动列出 Coordinator 工具，需保持同步。

---

---

#### 二十一.5 F-42 Shared / Sequential Workspace 策略

**状态**: ✅ 完成
**优先级**: P0
**跟踪文档**: `docs/PROGRESS.md` → `F-42: Orchestrator Shared / Sequential Workspace 策略`

### 目标

扩展 Orchestrator 的 workspace 策略，使本地 issue 驱动的特性规划流程既能保留现有“每个 issue 一个独立 clone”的隔离模式，也能支持多个 issue 在同一个 working tree / integration branch 上按排序顺序叠加开发。Sequential 模式的核心目标是：issue 2 启动时可以直接看到 issue 1 已提交的 commit，每个 issue 测试通过后留下一个可审查 commit，全部 issue 完成后由人工统一检视 commit 序列并创建一个 PR。

### 背景与问题

当前 `WorkspaceManager` 的语义是 per-issue isolated workspace：`create_for_issue(issue)` 会根据 `issue.identifier` 生成 `safe_id`，最终工作目录为 `workspace.root / safe_id`。当配置了 `repo_clone_url` 时，每个 issue 都会在自己的子目录内 clone / checkout issue branch。

这对远程 issue 并行开发是安全的，但不能满足本地特性规划拆分流程：

1. 多个 issue 必须按 `LocalTracker` 排序顺序逐个执行，而不是并行执行。
2. 后一个 issue 必须建立在前一个 issue 已提交 commit 的代码状态之上。
3. commit 序列必须保留在同一个 integration branch 上，等待人工最终合并为单个 PR。
4. workflow 配置不能仅通过把 `branch_name` 写成同一个分支来解决问题，因为当前 workspace path 仍按 issue 分裂，未推送 commit 不会自动出现在下一个 issue 的 clone 中。

### 配置设计

新增 `workspace.strategy`，默认值为 `isolated`，保证现有 workflow 不改配置也保持原行为。

```yaml
workspace:
  strategy: sequential          # isolated | shared | sequential
  root: /tmp/clawcodex-dev
  repo_clone_url: /mnt/e/Nodel/ExerciseProject/clawcodex
  clone_depth: 0
  base_branch: dev-decoupling-refactor-58ea488
  integration_branch: dev-decoupling-refactor-58ea488
  checkout_issue_branch: false
  require_clean_start: true
  require_clean_between_issues: true
  preserve_on_terminal: true
  sequential_lock: true

agent:
  max_concurrent_agents: 1
  max_concurrent_agents_by_state:
    open: 1
    ready: 1
```

建议 schema 扩展：

```python
@dataclass
class WorkspaceConfig:
    root: Path
    hooks: dict[str, Any] = None
    repo_clone_url: str | None = None
    clone_depth: int | None = 1
    checkout_issue_branch: bool = True
    git_username: str | None = None
    git_token: str | None = None
    strategy: Literal["isolated", "shared", "sequential"] = "isolated"
    base_branch: str | None = None
    integration_branch: str | None = None
    require_clean_start: bool = True
    require_clean_between_issues: bool = True
    preserve_on_terminal: bool = True
    sequential_lock: bool = True
```

### 策略语义

| strategy | workspace path | 并发语义 | checkout / branch 语义 | cleanup 语义 | 适用场景 |
|----------|----------------|----------|-------------------------|--------------|----------|
| `isolated` | `workspace.root / safe_issue_id` | 可按现有配置并发 | 每个 issue 独立 checkout issue branch | 保持现有 per-issue cleanup | 远程 issue、互不依赖任务 |
| `shared` | `workspace.root` | 默认要求 `max_concurrent_agents=1`，除非未来显式支持共享并发 | 多个 issue 共享同一工作树，可由 workflow 指定 branch | 不删除 shared root | 手工共享分支、少量串行本地任务 |
| `sequential` | `workspace.root` | 强制单 agent、单 active issue | 初始化或复用 integration branch；issue 间保留 commit 序列 | 永不自动删除工作树 | 特性规划拆分 issue，按顺序叠加开发 |

`shared` 和 `sequential` 都使用同一个目录，但 `sequential` 是更强约束：它必须验证调度并发为 1，必须持有顺序锁，必须在 issue 开始/结束时检查工作区清洁度，并且 registry 需要记录 issue 间 commit 链。

### WorkspaceManager 改造

保持 `WorkspaceManager.create_for_issue(issue)` 作为外部 API，避免影响 Orchestrator 调用方；内部按 strategy 分派：

```python
async def create_for_issue(self, issue: Any) -> Workspace:
    if self.config.strategy == "isolated":
        return await self._create_isolated_workspace(issue)
    if self.config.strategy == "shared":
        return await self._create_shared_workspace(issue)
    if self.config.strategy == "sequential":
        return await self._create_sequential_workspace(issue)
    raise ValueError(f"Unsupported workspace strategy: {self.config.strategy}")
```

路径选择规则：

- `isolated`: `_root / _safe_identifier(issue.identifier)`，完全沿用现状。
- `shared` / `sequential`: `_root` 本身就是 repo working tree；如果不存在则 clone 到 `_root`；如果存在但不是 git repo，根据配置 fail-closed，不自动删除用户目录。

Sequential 准备流程：

1. 获取 `.clawcodex_workspace.lock`，锁文件位于 shared root 或 root parent，记录 pid / issue_id / timestamp。
2. 如果 `root` 不存在且配置了 `repo_clone_url`，clone 到 `root`；`clone_depth: 0` 表示完整 clone，便于本地 commit 序列审查。
3. checkout `integration_branch`；如果不存在，则从 `base_branch` 创建。
4. 如果 `require_clean_start` 为 true，运行等价于 `git status --porcelain` 的检查，dirty 时拒绝启动当前 issue。
5. 返回的 `Workspace` 使用相同 `path=root`，但保留当前 `issue_identifier` / `issue_id`，供 dashboard、event log、registry 区分 session。

### Orchestrator 调度约束

当 `workspace.strategy == "sequential"` 时，配置加载或 Orchestrator 初始化阶段应强制校验：

1. `agent.max_concurrent_agents == 1`。
2. `agent.max_concurrent_agents_by_state` 中所有 active state 的值均不超过 1。
3. LocalTracker 场景下建议 issue frontmatter 使用 `priority: 1, 2, 3...` 与 `identifier: 001-...`，排序仍沿用 `LocalTrackerAdapter.fetch_candidate_issues()` 的现有规则。
4. 当前 issue 未进入 terminal state 前，不派发下一个 issue。
5. 如果当前 workspace 缺少前序 issue 应有的 commit 链，agent prompt 应停止并报告缺失前置，而不是重新实现前序 issue。

### IssueRegistry / 进度元数据

为 shared/sequential 模式补充 per-issue commit 链记录，便于 dashboard、报告和人工审查：

```python
@dataclass
class IssueRecord:
    workspace_strategy: str | None = None
    workspace_path: str | None = None
    base_commit_sha: str | None = None
    start_commit_sha: str | None = None
    commit_sha: str | None = None
    previous_issue_id: str | None = None
    sequence_index: int | None = None
```

字段语义：

- `base_commit_sha`: sequential workspace 初始化时 integration branch 的起点。
- `start_commit_sha`: 当前 issue agent run 开始前的 HEAD。
- `commit_sha`: 当前 issue 测试和 commit 成功后的 HEAD。
- `previous_issue_id`: 当前 issue 依赖的前一个已完成 issue。
- `sequence_index`: 本轮本地 issue 排序后的序号，用于 dashboard 展示和审查报告。

### GitSync / Hook / Cleanup 行为

Sequential 模式下 GitSync 继续保持“一 issue 一 commit”的交付边界，但不得自动 push / PR / merge。LocalTracker workflow 中 `post_sync` 应为空，最终远端 PR 由人工在完整 commit 序列审查后创建。

- `pre_commit`: 可运行测试或格式化 gate，但失败时必须阻止 commit。
- `pre_push` / `post_sync`: sequential local workflow 默认留空。
- `cleanup`: `isolated` 保持现有行为；`shared` / `sequential` 不调用 `shutil.rmtree(root)`，只释放锁并保留 working tree。
- 失败时保留 dirty workspace 供人工检查；除非用户显式 retry/reset，不自动丢弃改动。

### 风险与约束

- **并发风险**：shared working tree 不适合并发写入。Sequential 模式必须 fail-closed 地拒绝 `max_concurrent_agents > 1`。
- **脏工作区风险**：前一次失败可能留下未提交变更。默认 `require_clean_start=true`，避免后续 issue 混入未审查代码。
- **分支误用风险**：`base_branch` 与 `integration_branch` 配错会导致 commit 序列落在错误分支。启动时应在日志/dashboard 中显式展示 branch 和 start SHA。
- **cleanup 数据丢失风险**：shared/sequential workspace 可能包含人工未推送 commit，cleanup 必须默认 preserve。
- **重跑语义风险**：F-39 retry 在 sequential 模式下不能简单 reset 当前 issue 目录；需要区分“在当前 HEAD 追加 follow-up commit”和“人工回滚到 start_commit_sha 后重跑”。

### 测试计划

1. `WorkspaceManager` path selection：验证 `isolated` 使用 `root/safe_id`，`shared` / `sequential` 使用 `root`。
2. clone/reuse：sequential 第一个 issue clone repo，第二个 issue 复用同一 `.git`。
3. branch 初始化：`integration_branch` 存在时 checkout；不存在时从 `base_branch` 创建。
4. dirty guard：存在未提交文件且 `require_clean_start=true` 时拒绝派发。
5. cleanup preserve：shared/sequential 完成后不删除 `root`。
6. concurrency validation：`strategy=sequential` 且 `max_concurrent_agents>1` 时配置加载或 Orchestrator 初始化失败。
7. registry metadata：每个 issue 写入 `start_commit_sha` / `commit_sha` / `sequence_index`。
8. end-to-end local sequence：两个本地 issue 按 priority 执行，第二个 issue 的 `git log` 能看到第一个 issue commit，并最终形成两个连续 commit。

### 验收标准

1. 未配置 `workspace.strategy` 的现有 workflow 行为不变。
2. `workspace.strategy: sequential` 下，两个 active local issue 会在同一 working tree 中按 LocalTracker 排序串行执行。
3. 第二个 issue 启动时 HEAD 包含第一个 issue 的 commit。
4. 每个 issue 成功后留下一个独立 commit，并在 registry / dashboard 中可追踪。
5. sequential local workflow 默认不 push、不开 PR、不 merge、不 squash。
6. 工作区 dirty 或并发配置不安全时 fail-closed，并给出可操作错误信息。
7. 全部 issue 完成后，人工可以从 integration branch 上审查连续 commit 序列并创建一个 PR。

---

---

#### 二十一.6 F-45 Orchestrator tool-call 审计旁路

**状态**: ✅ 已完成 (2026-06-02)
**优先级**: P1
**跟踪文档**: `docs/PROGRESS.md` → `F-45: Orchestrator tool-call 审计旁路（tool-events.ndjson + 报告登记）`

##### 目标

在 `extensions/orchestrator/agent_runner.py` 的 `_handle_tool_call` 之后追加 NDJSON 旁路落盘，**与 `permission_mode` 解耦**，扩展 `report_writer.RunReport` 字段与 markdown 模板，让审计员从 run 报告就能定位 `~/.clawcodex/tool-events/{run_id}/events.ndjson` 完整 per-tool 决策流水。**终结 "bypass ≠ 无审计" 误读**——bypass 关闭的是 user-prompt audit 层，本特性补上 per-tool 决策 audit 层。

##### 触发背景

- `extensions/orchestrator/report_writer.py:write()` 只持久化 `tool_count: int` 与末尾 4000 字符的 `output_excerpt`，per-tool 决策流水不落盘
- `extensions/orchestrator/agent_runner.py:87-108` 的 `_handle_tool_call` 始终调 `ApprovalPolicy.evaluate()`，`_approved` / `_deny_reason` 写回 `ToolCallEvent` 内存对象 —— 进程崩溃即丢
- 在 orchestrator headless 场景下 `permission_mode` 走 auto-upgrade 到 `bypassPermissions`（`patches/upstream/58ea488/merged/0026.tui_app_py.patch:1287-1291`），TS 注释说 "no logging"，Python 端其实有 ApprovalPolicy —— 审计数据其实有，只是没落盘

##### 旁路落点

```
agent_runner.py:_handle_tool_call(event, session_context)
    ├── ApprovalPolicy.evaluate(policy_event, session_context)  # 已有
    ├── event._approved = policy_event._approved                 # 已有
    ├── event._deny_reason = policy_event._deny_reason           # 已有
    └── _append_tool_event_log(event, session_context)           # 新增 (Sub-A)
            │
            └── 写 ~/.clawcodex/tool-events/{run_id}/events.ndjson
```

##### NDJSON 字段契约（ToolEventLog）

每行 JSON 含 8 字段：

```python
{
    "ts": 1717350000.123,            # time.time()
    "tool": "Bash",                  # event.tool_name
    "params": {"command": "ls -la"}, # event.params（完整）
    "approved": true,                # event._approved
    "deny_reason": null,             # event._deny_reason（允许时为 null）
    "permission_mode": "bypassPermissions",  # session_context["permission_mode"]
    "turn": 12,                      # session.turn_count
    "session_run_id": "2026-06-02T..."      # session.run_id
}
```

##### 报告登记

`report_writer.RunReport` 新增字段：

```python
@dataclass(frozen=True)
class RunReport:
    # ... 已有字段 ...
    tool_events_path: str | None  # 新增
```

`write()` 多接收 `tool_events_path: str | None = None`，`_render_markdown` 加一行 `Tool events: <path>`，`_copy_with_fallback` 把 NDJSON 拷到 `~/.clawcodex/reports/.../{run_id}/` 持久化层。

##### 关键设计决定

1. **旁路挂 `agent_runner` 层，不动 `ApprovalPolicy`**：策略层不感知 run_id / session_context，旁路在 orchestrator 拦截层做，对策略零侵入
2. **NDJSON 而非 SQLite / Parquet**：追加写 O(1)，`tail` / `grep` 友好，无新依赖；审计场景 "看尾部" 占 90%
3. **落 `~/.clawcodex/tool-events/` 而非 workspace**：workspace 会被 `git_sync` 推到 PR，审计数据污染仓库
4. **`params` 不 redact**：与 TS upstream `dontAsk` "All allowed, logged" 行为对齐
5. **不动 `extensions/api/query.py` stream 协议**：职责分离，旁路在 orchestrator 内部
6. **`RunReport.tool_events_path` 加在末尾**：旧 reader 不识别此字段就忽略，向前兼容
7. **rotate 阈值 50MB，7 天清理推 v2.14**：rotate 是单文件级别，清理是跨文件级别，降低本 PR 风险

##### 风险与缓解

| 风险 | 缓解 |
|------|------|
| 磁盘撑大 | 50MB rotate，7 天清理（v2.14 挂 cron） |
| 写并发 | 单 run_id 单 session，`fdopen` + `flush` + O_APPEND 原子写 |
| 异常阻塞 agent | try/except + `logger.exception`，不 raise |
| 敏感数据泄露 | 文档明示 "events.ndjson 在 `~/.clawcodex/`，用户自管 ACL"；后续可加 `--redact` |
| 与 F-40 sink 重叠 | F-40 走 `ToolContext.tasks` 进程内 metadata，本特性走文件系统 NDJSON；两套并存，职责分离 |
| 不动 `extensions/api/query.py` stream 协议 | 旁路在 orchestrator 内部拦截，stream 出口职责不变 |

##### 子特性

- **Sub-A** `_append_tool_event_log` 旁路方法（~50 行）
- **Sub-B** `ToolEventLog` 数据契约（8 字段）+ JSON serializer
- **Sub-C** `RunReport.tool_events_path` 字段 + markdown 模板 + dual-write NDJSON 到 `~/​.clawcodex/reports/...`
- **Sub-D** `AgentRunner.run` 注入 `run_id` 到 `session_context`
- **Sub-E** rotate 策略 + `.gitignore` 默认 patterns
- **Sub-F** 单测 + 集成测试 + 四种 mode 回归

详细 sub-task、当前基线、验收标准、风险与协同见 PROGRESS.md 详节。

##### 实施摘要 (2026-06-02)

落地时同步修复了设计文档的一处隐藏缺口：原设计假设 `_handle_tool_call`（`agent_runner.py:121-142`）已在 run-loop 的 ToolCallEvent 分支被调用，但实际代码中该方法**从未被调用**（run-loop 里有显式注释 "the orchestrator's ApprovalPolicy is not consulted here"）。如果按字面落地，NDJSON 的 `approved` 字段会永远是 `None`，审计数据无意义。修复：在 `agent_runner.py:505-509` 显式 `event = self._handle_tool_call(event, session_context)` 再 `_append_tool_event_log`，并把 `turn` 写回 `session_context`。其他 5 个 sub-task 按设计字面落地。

**新增/修改文件**:
- `extensions/orchestrator/tool_event_log.py`（新增）— `ToolEventLog` 8 字段 frozen dataclass
- `extensions/orchestrator/agent_runner.py`（修改）— `_append_tool_event_log` 方法、`_TOOL_EVENT_LOG_ROTATE_BYTES` 常量、`AgentSession.tool_events_path` 字段、`session_context` 注入、ToolCallEvent 分支接 `_handle_tool_call`
- `extensions/orchestrator/report_writer.py`（修改）— `RunReport.tool_events_path` 字段（末尾默认 `None`）、`write()` dual-write、markdown 模板加 `Tool events:` 行
- `extensions/orchestrator/git_sync.py`（修改）— `_write_report` 转发 `tool_events_path`
- `extensions/orchestrator/config/schema.py`（修改）— `WorkspaceConfig.gitignore_patterns` 默认加 `.reports`
- `tests/test_orchestrator_f45_audit_bypass.py`（新增）— 7 个测试类，16 个 case

**测试**: `tests/test_orchestrator_f45_audit_bypass.py` 16/16、`tests/test_orchestrator_*.py` 271/271、`tests/manual_e2e_f38.py` 4/4 — 共 291 例全绿，零回归。

**与设计文档的两处偏差**（均已与用户确认）:
1. **同步修复 `_handle_tool_call` 调用链**（见上方缺口段）
2. **单文件 50MB rotate**：旧 `events.ndjson` 直接 rename 为 `events.ndjson.1`（覆盖），无多代轮转；7 天清理推 v2.14

---

---

### 二十一7 F-13 Agent 记忆作用域隔离

**状态**: ✅ 已实现（2026-06-06）
**目标**: 支持 Agent 按需加载不同作用域的记忆内容

#### 3.6.1 实现概述

通过 `clawcodex_ext/memory/` 扩展包实现，采用 **try-import + 静默降级** 模式：
- 按需调用时优先使用 `clawcodex_ext` 的 scope-aware 路径
- 扩展包不可用时静默降级到原有 `load_memory_prompt()` 行为
- 不修改原有 `memdir/` 模块的任何代码，零侵入耦合

#### 3.6.2 设计背景

传统的记忆系统是单例模式，所有 Agent 共享相同的记忆目录。在多 Agent 协作场景下，不同 Agent 可能需要访问不同范围的信息：
- 用户/私有记忆：仅当前用户可见
- 项目记忆：项目团队共享
- 团队记忆：跨项目团队共享
- 本地记忆：会话级临时信息

#### 3.6.3 实现方案

```
clawcodex_ext/memory/
├── __init__.py                 # 包声明
└── scope_aware_prompt.py       # 核心 scope 感知 prompt 逻辑
```

| 作用域 | 说明 |
|--------|------|
| `user` | 用户/私有记忆 |
| `project` | 项目上下文记忆 |
| `local` | 会话级本地记忆 |

> 注：`reference` 和 `team` 作用域保留为预留，待后续实现记忆路径体系后启用。

#### 3.6.4 核心 API

```python

# 按需加载特定作用域的记忆（通过 scope_aware_prompt 扩展）
from clawcodex_ext.memory.scope_aware_prompt import build_scope_aware_memory_prompt

# 在 build_full_system_prompt 中使用
prompt = build_full_system_prompt(
    memory_scopes=['user', 'project'],  # Agent 按需指定
    ...
)

# 或在 Agent 定义中指定
agent = AgentDefinition(
    agent_type="research-agent",
    memory_scopes=["user"],
    ...
)
```

#### 3.6.5 实现文件

| 文件 | 功能 | 类型 |
|------|------|------|
| `clawcodex_ext/memory/__init__.py` | 包声明，docstring 说明用途 | ✅ 新建 |
| `clawcodex_ext/memory/scope_aware_prompt.py` | 核心 scope 感知 prompt 逻辑（88 行） | ✅ 新建 |
| `src/context_system/prompt_assembly.py` | 4 处 forwarding seam：`build_full_system_prompt()`、`build_full_system_prompt_blocks()`、`_build_memory_section()` 参数透传 + `build_scope_aware_memory_prompt` 调用 | ✅ 修改 |

#### 3.6.6 架构决策

```
用户请求层面: build_full_system_prompt(memory_scopes=["user", "team"])
                                    │
                                    ▼
                  _build_memory_section(memory_scopes)
                                    │
                          ┌─────────▼─────────┐
                          │ memory_scopes 非 None? │
                          └─────────┬─────────┘
                           Yes │         No │
                               ▼           ▼
                   try: clawcodex_ext     src.memdir
                   └→ scope_aware_prompt  load_memory_prompt()
                      build_...()
                        │
                        ▼ (fallback if ext unavailable)
                      src.memdir
                      load_memory_prompt()
```

**关键设计决策：**
- `memory_scopes` 参数默认 `None` → 100% 向后兼容
- `clawcodex_ext` 通过 try-import 方式调用，失败时静默降级到原有 `load_memory_prompt()` 行为
- `VALID_MEMORY_SCOPES` 在两个模块中各自定义（镜像关系），避免 `clawcodex_ext` 对 `src` 的导入依赖
- 未知 scope 记录 warning 但不会 crash

#### 3.6.7 验证结果

- ✅ 231/231 orchestrator 测试通过（F-39 Sub-A~F 全部落地，含 153 个 F-39 专项用例）
- ✅ 371/378 parity 测试通过（7 个预存失败）
- ✅ F-38 E2E 全部 4 轮通过

# 3.7 /goal 命令（目标管理）

| 功能 | ClawCodex | Claude Code Best | 优先级 |
|------|-----------|------------------|--------|
| Voice Mode | ❌ 未实现 | ✅ 完整 | P3 |
| Computer Use | ❌ 未实现 | ✅ 完整 | P3 |
| Chrome Use | ❌ 未实现 | ✅ 浏览器自动化 | P3 |
| Remote Control (Docker+WebUI) | ⚠️ 基础 | ✅ 完整 | P2 |
| Pipe IPC / LAN | ❌ | ✅ | P3 |
| ACP/Zed/Cursor 集成 | ❌ | ✅ | P3 |
| Langfuse 监控 | ❌ | ✅ | P3 |
| Feature Flags | ❌ | ✅ | P3 |

---

---

### 二十一8 F-43 CLI 模型供应商与模型切换

**状态**: ✅ 已完成 (2026-06-02)
**优先级**: P1
**跟踪文档**: `docs/PROGRESS.md` → `F-43: CLI 模型供应商与模型切换`

> **实施完成**（v2.13）：所有设计要点已落地。`clawcodex_ext/cli/{subcommand_registry.py, provider_cmd/, model_cmd/}` 新增；`clawcodex_ext/runtime/context.py` 接入 `Resolver` 并新增 `swap_provider`；`CommandContext.runtime_context` seam + `TUIOptions.runtime_context` 透传；`/provider` / `/model` 斜杠命令注册到全局 `CommandRegistry` 并在 REPL/TUI 同步私有引用。20/20 F-43 单元测试通过，orchestrator 回归 271/271 通过。`--scope project` 落入 G-1 后续规划。

#### 目标

新增 `clawcodex provider` 与 `clawcodex model` 两个子命令族，让用户能在 CLI 内**查看、切换、列出**当前生效的 LLM 供应商与模型；并在 REPL/TUI 内部以 `/provider` 与 `/model` 斜杠命令提供运行期热切换。所有新代码落在 `clawcodex_ext/cli/` 下，不动 `src/*` 或 `extensions/*`。

#### 背景与问题

- 一次性覆盖：CLI 已支持 `--provider NAME` / `--model NAME`（`parser.py:88-99`），仅对本次调用生效；想换默认需要重跑 `login`
- 持久化入口耦合：仅 `runners.py:120-191` 的 `handle_login` 在配凭证时同步写 `default_model`，没有独立的"切换默认模型"命令
- 没有 `clawcodex model show` 这类查询入口，用户看不到当前生效的 provider / model
- REPL/TUI 运行期无法热切换：`RuntimeContext` 只在启动时构造一次
- 解析优先级在 `RuntimeContext.build` 中硬编码 "CLI flag > default_provider > provider default_model"，无法扩展环境变量 / 项目级 scope

#### 子命令形态

```
clawcodex provider
  list
  show [NAME]                       # NAME 省略时显示当前
  current
  use NAME [--scope user|project]
  unset

clawcodex model
  list [--provider NAME]
  show [NAME] [--provider NAME]
  current
  use NAME [--provider NAME] [--scope user|project]
```

要点：

- 全部为 fast-path 子命令（在 `dispatch.py:argv[0]` 分支中注册），不走 argparse
- `--scope project` 是后续议题（G-1），第一版只实现 `user`（全局）
- `provider use` 不重写 API key / base_url，只动 `default_provider`；`model use` 只动指定 provider 的 `default_model`
- `login` 子命令行为保留，内部把"保存 default_model"委托给新模块 setter

#### 目录与模块划分

新增内容全部在 `clawcodex_ext/cli/` 下：

```
clawcodex_ext/cli/
├── main.py                  # 已有
├── parser.py                # 已有（不需改）
├── dispatch.py              # 改动一处：fast-path 改查表
├── runners.py               # 已有（不需改）
├── permissions.py           # 已有（不需改）
├── subcommand_registry.py   # 新增：SUBCOMMANDS 表 + @register 装饰器
├── provider_cmd/
│   ├── __init__.py
│   ├── commands.py          # list / show / current / use / unset
│   └── errors.py
└── model_cmd/
    ├── __init__.py
    ├── registry.py          # 包装 PROVIDER_INFO
    ├── resolver.py          # 解析优先级
    ├── store.py             # 通过 src.config 持久化
    ├── commands.py          # list / show / current / use
    └── errors.py
```

`subcommand_registry.py` 是关键解耦点：`@register("provider")` / `@register("model")` 让 `provider_cmd` / `model_cmd` 自注册，`dispatch.py` 改为查表。

#### 核心数据结构

```python

# model_cmd/registry.py
@dataclass(frozen=True)
class ModelSpec:
    provider: str
    name: str
    base_url: str | None = None
    api_key_present: bool = False

class ModelRegistry:
    def list_providers(self) -> list[ProviderInfo]: ...
    def get_provider_info(self, name: str) -> ProviderInfo: ...
    def list_models(self, provider: str) -> list[str]: ...
    def resolve_model(self, provider: str, name: str) -> ModelSpec: ...   # 校验白名单
    def has_credentials(self, provider: str) -> bool: ...

# Post-archival: 动态模型发现注册表 (2026-06)
_DISCOVERY_HOOKS: dict[str, list[Callable[[], list[str]]]] = {}

def register_discovery_hook(provider_name: str, hook: Callable[[], list[str]]) -> None:
    """由 ext 代码调用，注册一个 provider 的模型发现函数。幂等。"""
    _DISCOVERY_HOOKS.setdefault(provider_name, []).append(hook)

class ModelRegistry:
    def __init__(self, *, discovery_hooks: dict[str, list[Callable]] | None = None):
        self._hooks = discovery_hooks or _DISCOVERY_HOOKS

    def available_models(self, provider_name: str) -> list[str]:
        """合并静态基线 + hooks 返回的模型。去重、异常静默。"""
        baseline = list(STATIC_MODEL_MAP.get(provider_name, []))
        for hook in self._hooks.get(provider_name, []):
            try:
                extra = hook()
                if extra:
                    baseline.extend(m for m in extra if m not in baseline)
            except Exception:
                logger.debug("discovery hook failed for %s", provider_name, exc_info=True)
        return baseline
```

```python
# model_cmd/resolver.py
@dataclass(frozen=True)
class Resolution:
    provider: str
    model: str
    source: Literal["cli", "env", "project", "user_default_provider", "provider_default"]

def resolve(*, cli_provider, cli_model, project_root) -> Resolution: ...
```

```python
# model_cmd/store.py
class ModelStore:
    def set_default_provider(self, name: str) -> None: ...
    def set_default_model(self, provider: str, model: str) -> None: ...
    def get_default_provider(self) -> str | None: ...
    def get_default_model(self, provider: str) -> str | None: ...
```

#### 解析优先级

| 序 | 来源 | 字段 |
|----|------|------|
| 1 | CLI 标志 `--provider` / `--model` | `cli_provider` / `cli_model` |
| 2 | 环境变量 `CLAWCODEX_PROVIDER` / `CLAWCODEX_MODEL` | env |
| 3 | 项目级 config（未来 G-1） | project |
| 4 | 用户全局 config `default_provider` | user |
| 5 | 用户全局 config `providers[provider].default_model` | user |
| 6 | `PROVIDER_INFO[provider].default_model` | builtin fallback |

每次解析都记录 `source`，用于 `model current` 输出形如 `provider: glm [user]`。

#### 存储模型

**第一版只实现 user scope（全局）：**

- 读：`src.config.load_config` / `get_provider_config` / `get_default_provider`
- 写：`src.config.set_default_provider` 与 `set_api_key(provider, default_model=X)`（保留其它字段）

**项目级 scope（`--scope project`）作为后续 G-1 议题：**

- 落到 `<project>/.clawcodex/config.local.json`（默认加入 `.gitignore`）
- `store.py` 接口预留 `scope` 参数，避免后续大改签名

#### REPL / TUI 斜杠命令

REPL 与 TUI 的 `/provider` / `/model` 斜杠命令复用 `model_cmd.resolver` + `model_cmd.store`：

- `/provider list` / `/model list` → 复用 `cmd_*_list`
- `/provider <name>` / `/model <name>` → 复用 `cmd_*_use`，并通过新增的 `RuntimeContext.swap_provider(provider, model)` 触发运行时切换
- `swap_provider` 重建 provider + 复用 session ID + 重建 tool registry（仅当工具绑定 model context 时）
- 错误处理：复用 `provider_cmd.errors` / `model_cmd.errors` 的英文文案

#### 与现有代码的关系

| 既有模块 | 关系 |
|----------|------|
| `parser.py` | 不动。新子命令走 fast-path |
| `dispatch.py:run_cli` | 改一行：fast-path 改查表 |
| `runners.py:handle_login` | 不动。`model use` 与之并存 |
| `RuntimeContext.build` | 不动。本方案只新增友好入口 |
| `extensions/providers_ext` | 不动。正交 |
| `src.providers.PROVIDER_INFO` / `src.config` | 只读不写 |

唯一需要修改 `src/*` 的是 `dispatch.py` 的一行（fast-path 改查表）；其余都在 `clawcodex_ext/cli/`。

#### 错误模型（统一英文）

| 异常 | 触发条件 | 文案 |
|------|----------|------|
| `UnknownProviderError` | provider 不在 `PROVIDER_INFO` | `unknown provider: <name>. available: <list>` |
| `UnknownModelError` | model 不在 `available_models` | `model <name> is not in <provider>'s available models. pick one of: <list>` |
| `ProviderMismatchError` | `--provider` 与 model 默认 provider 不一致且无显式 `--provider` | `<model> belongs to <other-provider>, not <provider>. pass --provider <other-provider> or pick a model from <provider>.` |
| `NotConfiguredError` | 切换时无凭证 | `provider <name> has no API key configured. run \`clawcodex login\` first.` |

所有错误统一在 `provider_cmd/errors.py` 与 `model_cmd/errors.py` 定义；`commands.py` 捕获后用 `rich.console` 打印，exit code = 2。

#### 后续规划（已落地）

##### 动态模型发现注册表 (2026-06) ✅

| 任务 | 文件 | 说明 |
|------|------|------|
| `register_discovery_hook()` 全局注册表 | `clawcodex_ext/cli/model_cmd/registry.py` | `_DISCOVERY_HOOKS` dict + register 函数；`ModelRegistry.__init__` 接受 `discovery_hooks` 参数 |
| `available_models()` 合并 hook | `clawcodex_ext/cli/model_cmd/registry.py` | 静态基线 + hook 结果去重合并，异常静默 |
| `openai-codex` API 发现钩子 | `clawcodex_ext/providers/hooks.py` ★ 新建 | 调用 `get_codex_model_ids()`，无 token 时静默返回空 |
| 自动注册 | `clawcodex_ext/providers/__init__.py` ★ 新建 + `clawcodex_ext/__init__.py` | import 时自动注册 |
| `resolve()` 信任已保存配置 | `clawcodex_ext/cli/model_cmd/resolver.py` | `validate_model` 失败时走 `user-warn`，不再降级回默认 |
| 移除 `gpt-5.5` 硬编码 | `src/providers/__init__.py` | 回归静态基线，由 hook 动态发现 |
| 测试 | `tests/test_f43_model_registry.py` | 新增 6 个测试，24/24 全部通过 |

**验收**: 扩展方只需 `register_discovery_hook("my-provider", my_fn)` 即可为任意 provider 添加动态模型发现，无需修改 `src/`。

##### 后续规划（原封推迟）

- `clawcodex provider use --scope project` 落入 `<project>/.clawcodex/config.local.json`
- `clawcodex model use --scope project` 同上
- 项目级 scope 的 resolver 优先级插在 user 之前
- 多窗口并发写盘的 `fcntl` 文件锁

#### 测试策略

| 测试 | 覆盖点 |
|------|--------|
| `test_resolver.py` | 6 级优先级矩阵；env 覆盖；非法 provider/model 抛错 |
| `test_store.py` | round-trip 读写；`set_default_model` 不影响 `api_key` / `base_url`；注入 mock config 模块隔离磁盘 |
| `test_provider_commands.py` / `test_model_commands.py` | `capsys` 抓 stdout，断言表格 / 错误信息；mock `Console` 避免终端 |
| `test_subcommand_registry.py` | 注册 / 重复注册 / 未注册命令的 fallback 行为 |
| `test_dispatch_integration.py` | `clawcodex provider list` / `clawcodex model use zai/glm-4` 端到端跑通 |
| `test_slash_commands.py` | REPL / TUI 内 `/provider` / `/model` 触发 `swap_provider`；mock `RuntimeContext` 验证调用 |
| 手工 smoke | 真实 `clawcodex -p "hi" --provider glm --model zai/glm-4` 验证切换生效 |

#### 风险与约束

1. **写盘并发**：现有 `src.config` 没有文件锁；第一版接受 "最后写者赢"，G-1 加 `fcntl` 锁
2. **`--model` 与子命令 `model` 同名**：fast-path 只看 `argv[0]`，无歧义；未来 argparse 接管需重新审视
3. **环境变量命名**：建议 `CLAWCODEX_PROVIDER` / `CLAWCODEX_MODEL`，与现有 `CLAW_USE_LITELLM` / `CLAUDE_CONFIG_DIR` 一致
4. **REPL/TUI 热切换**：本方案实现 `/provider` / `/model` 与 `swap_provider`；后续若 `swap_provider` 影响 tool registry 行为，需单测覆盖
5. **`login` 仍可写 `default_model`**：保持原行为，文档化 "用 `clawcodex model use` 更轻量"
6. **`runners.py:_show_provider_defaults_table` 与新 `provider list` 重复**：G-1 合并；第一版接受短期重复

#### 实施阶段

| 阶段 | 内容 | 依赖 |
|------|------|------|
| 1 | `subcommand_registry.py` 注册表骨架 + `dispatch.py` 接入 | 无 |
| 2 | `model_cmd` 核心（registry / errors / resolver / store） + 单测 | 阶段 1 |
| 3 | `model_cmd/commands.py`（list / show / current / use） | 阶段 2 |
| 4 | `provider_cmd` 5 个 handler | 阶段 2、3 |
| 5 | REPL `/provider` / `/model` 斜杠命令 + `RuntimeContext.swap_provider` | 阶段 3 |
| 6 | TUI `/provider` / `/model` 斜杠命令 | 阶段 5 |
| 7 | 端到端测试 + 文档 | 阶段 6 |

---

---

### 二十一9 F-47 Permission Settings Schema 重构

**状态**: 📋 设计完成
**优先级**: P1
**跟踪文档**: `docs/PROGRESS.md` → `F-47: Permission Settings Schema 重构（`permissions` 改 dict 形态 + plumb 启动模式）`

#### 目标

修四层串联 bug：

1. `SettingsSchema.permissions: list[PermissionRule]` 的 schema 形状与磁盘实际 dict 形态（`src/permissions/updates.py:291-343` / `src/permissions/setup.py:62-67` / `src/permissions/loader.py:14-30` 写入）不一致
2. `has_allow_bypass_permissions_mode()` 写死了 `settings.extra["permissions"]` 路径
3. `clawcodex_ext/cli/permissions.py:36-39` 调 `initial_permission_mode_from_cli` 时没传 `settings_default_mode`
4. 顶层 `settings.permission_mode` 字段未被 `resolve_permission_state` 读

核心方案：把 `permissions` 改为 `PermissionsConfig` dataclass（dict 形态），与磁盘 + TS 上游契约对齐；`resolve_permission_state` 真正 plumb 启动模式；删除 settings 层"假" `PermissionRule` 死代码。后续 `permissions.*` 新增 sub-key 不需要改 schema —— 走 `PermissionsConfig.additional` 前向兼容包。

> **F-47.1 (2026-06-02) hotfix**：F-47 设计阶段在 `resolve_permission_state` 保留顶层 `settings.permission_mode` 作为 back-compat 读取通道。F-47.1 在项目尚未发布的前提下直接删除该通道——`SettingsSchema.permission_mode` 字段保留为兼容形态但启动时不再被读，磁盘上残留的旧值在启动时被静默忽略。F-46.2 的 deprecation 步骤因此 N/A。详见 `docs/PROGRESS.md` F-47.1 备注。

#### 触发背景

- 2026-06-02 用户报告"配置 `~/.clawcodex/config.json` 的 `settings.permissions.allowBypassPermissionsMode: true` 后,REPL Shift+Tab 仍然只循环 3 档"——四层 bug 串联
- `SettingsSchema.permissions: list[PermissionRule]`（`src/settings/types.py:100`）与磁盘 dict 形态（`updates.py:persist_permission_update` 写 `{allow: [...], defaultMode, ...}`）冲突
- `has_allow_bypass_permissions_mode`（`src/permissions/modes.py:113-140`）只读 `settings.extra["permissions"]`，但 dict 进 known field 后 `extra` 永远是 None
- `resolve_permission_state`（`clawcodex_ext/cli/permissions.py:36-39`）形参 `settings_default_mode` 留好但调用方从未传
- 顶层 `SettingsSchema.permission_mode`（`src/settings/types.py:97`）字段存在但 `resolve_permission_state` 不读
- `src/settings/types.py:13-20` 的 `PermissionRule`（带 `tool/allow/glob/regex/description/source`）与运行时 `src/permissions/types.py:80-84` frozen `PermissionRule`（带 `source/rule_behavior/rule_value`）同名异构，且前者无 caller——死代码

#### Schema 形态变化

**Before**（v2.12）：
```python
@dataclass
class SettingsSchema:
    permissions: list[PermissionRule] = field(default_factory=list)
    permission_mode: PermissionModeType = "default"

@dataclass
class PermissionRule:                      # 死代码
    tool: str = ""
    allow: bool = True
    glob: str | None = None
    regex: str | None = None
    description: str = ""
    source: str = "user"
```

**After**（v2.13）：
```python
@dataclass
class PermissionsConfig:
    """对齐磁盘 + TS 上游契约的 permissions 结构。"""
    allow_bypass_permissions_mode: bool = False
    default_mode: str | None = None
    rules: dict[str, list[str]] = field(default_factory=dict)  # {"allow":[...], "deny":[...], "ask":[...]}
    additional_directories: list[str] = field(default_factory=list)
    additional: dict[str, Any] = field(default_factory=dict)  # forward-compat bag

    @classmethod
    def from_dict(cls, data: Any) -> "PermissionsConfig":
        if not isinstance(data, dict):
            return cls()
        rules: dict[str, list[str]] = {}
        rules_raw = data.get("rules", {}) if isinstance(data.get("rules"), dict) else {}
        for behavior in ("allow", "deny", "ask"):
            v = rules_raw.get(behavior) or data.get(behavior)
            if isinstance(v, list):
                rules[behavior] = [str(x) for x in v]
        add_dirs = data.get("additionalDirectories")
        if not isinstance(add_dirs, list):
            add_dirs = []
        known = {"allow", "deny", "ask", "defaultMode",
                 "additionalDirectories", "allowBypassPermissionsMode", "rules"}
        additional = {k: v for k, v in data.items() if k not in known}
        return cls(
            allow_bypass_permissions_mode=bool(data.get("allowBypassPermissionsMode", False)),
            default_mode=data.get("defaultMode"),
            rules=rules,
            additional_directories=[str(d) for d in add_dirs],
            additional=additional,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = dict(self.additional)
        d["allowBypassPermissionsMode"] = self.allow_bypass_permissions_mode
        if self.default_mode is not None:
            d["defaultMode"] = self.default_mode
        if self.rules:
            d["rules"] = dict(self.rules)
        if self.additional_directories:
            d["additionalDirectories"] = list(self.additional_directories)
        return d


@dataclass
class SettingsSchema:
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    permission_mode: str = ""   # 顶层 back-compat 形态保留；空串视为未设置。
    # F-47.1 (2026-06-02) 已删除启动模式 plumb 时的 fallback 读取，
    # 磁盘上残留的 settings.permission_mode 字段在启动时被忽略。
```

#### 加载路径改造

`SettingsSchema.from_dict`（`src/settings/types.py:161-198`）把：

```python
if "permissions" in known and isinstance(known["permissions"], list):
    known["permissions"] = [PermissionRule(**r) if isinstance(r, dict) else r for r in known["permissions"]]
```

替换为：

```python
if "permissions" in known:
    known["permissions"] = PermissionsConfig.from_dict(known["permissions"])
```

dict / list / None 都安全降级到 `PermissionsConfig`，未知 sub-key 进 `additional` 不会丢。

#### 读路径 + 启动模式 plumb

`src/permissions/modes.py` 加私有聚合器：

```python
def _settings_perms(settings) -> dict[str, Any]:
    """聚合所有可识别的 permissions sub-key。

    优先级：
    1. `settings.permissions.additional`（forward-compat bag）
    2. `settings.permissions.to_dict()`（结构化字段）
    3. `settings.extra["permissions"]`（F-47 落地前旧 binary 旁路）
    """
    perms_obj = getattr(settings, "permissions", None)
    if perms_obj is None:
        return {}
    bag: dict[str, Any] = {}
    if hasattr(perms_obj, "additional") and isinstance(perms_obj.additional, dict):
        bag.update(perms_obj.additional)
    if hasattr(perms_obj, "to_dict"):
        try:
            for k, v in perms_obj.to_dict().items():
                bag.setdefault(k, v)
        except Exception:
            pass
    legacy = (getattr(settings, "extra", None) or {}).get("permissions")
    if isinstance(legacy, dict):
        for k, v in legacy.items():
            bag.setdefault(k, v)
    return bag


def has_allow_bypass_permissions_mode() -> bool:
    try:
        from src.settings.settings import get_settings
    except Exception:
        return False
    try:
        settings = get_settings()
    except Exception:
        return False
    return bool(_settings_perms(settings).get("allowBypassPermissionsMode"))
```

`clawcodex_ext/cli/permissions.py` plumb：

```python
from src.settings.settings import get_settings
from src.permissions.modes import (
    has_allow_bypass_permissions_mode,
    initial_permission_mode_from_cli,
    PERMISSION_MODES,
)

def resolve_permission_state(args) -> None:
    dangerously = bool(getattr(args, 'dangerously_skip_permissions', False))
    allow_dangerously = bool(getattr(args, 'allow_dangerously_skip_permissions', False))
    permission_mode_cli = getattr(args, 'permission_mode', None)

    enforce_dangerous_skip_permissions_safety(
        bypass_requested=dangerously or allow_dangerously,
    )

    # F-47: 启动模式 plumb —— 读 permissions.default_mode。
    # F-47.1 (2026-06-02) 已删除"再 fallback 顶层 permission_mode"分支，
    # 磁盘上残留的 settings.permission_mode 字段在启动时被忽略。
    settings_default_mode: str | None = None
    try:
        s = get_settings()
        pc = getattr(s, "permissions", None)
        if pc is not None:
            settings_default_mode = getattr(pc, "default_mode", None) or None

    mode = initial_permission_mode_from_cli(
        permission_mode_cli=permission_mode_cli,
        dangerously_skip_permissions=dangerously,
        settings_default_mode=settings_default_mode,
    )

    is_bypass_available = (
        dangerously
        or allow_dangerously
        or has_allow_bypass_permissions_mode()
    )
    ...
```

#### 校验重写

`src/settings/validation.py` 改写 `permission_mode` / `permissions` 校验段：

```python

# 旧 (32-38 行):
if settings.permission_mode not in VALID_PERMISSION_MODES:
    errors.append(ValidationError(...))

# 新:
effective_default_mode = (
    settings.permissions.default_mode
    if settings.permissions.default_mode
    else (settings.permission_mode or None)
)
if effective_default_mode is not None and effective_default_mode not in VALID_PERMISSION_MODES:
    errors.append(ValidationError(
        field="permissions.defaultMode",
        message=f"Invalid default permission mode: {effective_default_mode!r}",
        value=effective_default_mode,
    ))

# 旧 (97-103 行):
for i, rule in enumerate(settings.permissions):
    if not rule.tool:
        errors.append(ValidationError(
            field=f"permissions[{i}].tool",
            message="Permission rule must have a 'tool' field",
        ))

# 新:
for behavior in ("allow", "deny", "ask"):
    bucket = settings.permissions.rules.get(behavior, [])
    for j, rule_str in enumerate(bucket):
        if not isinstance(rule_str, str) or not rule_str.strip():
            errors.append(ValidationError(
                field=f"permissions.rules.{behavior}[{j}]",
                message="Rule must be a non-empty string",
            ))
```

#### 关键设计决定

1. **`permissions` 改 dict 形态（`PermissionsConfig` dataclass）**：对齐磁盘格式（`updates.py:persist_permission_update` 写 dict）+ TS 上游契约（`modes.py:118-141` docstring 明确 TS 是 dict），消除运行时 + schema + 磁盘三处形态漂移。
2. **强类型 sub-key + `additional` 前向兼容 bag**：已知 sub-key（`allowBypassPermissionsMode` / `defaultMode` / `rules` / `additionalDirectories`）给类型化访问，未知 sub-key 进 `additional` 兜底。新增 sub-key 不需要改 schema。
3. **顶层 `settings.permission_mode` 字段保留为 back-compat 读取通道**：本次不引入一次性 breaking change；F-46 后续阶段会统一 deprecate。空串视为未设置、不触发 `validation.py` enum 校验误报。**F-47.1 (2026-06-02) hotfix：在项目尚未发布的前提下直接删除该通道**（磁盘上没有需要迁移的旧配置），F-46 deprecate 步骤 N/A。`validation.py` 跳过空串校验的规则保留（无副作用，不删以避免引入额外变更面）。
4. **删除 settings 层"假" `PermissionRule` 死代码**：与运行时 `PermissionRule` 同名异构（一个带 `tool/allow/glob/regex/description/source`，一个带 `source/rule_behavior/rule_value`），混淆读者。`grep` 确认唯一引用是 `from_dict:176-179`（本次同时改写），可安全删。
5. **`has_allow_bypass_permissions_mode` 加 `_settings_perms` 聚合器**：保留 `extra["permissions"]` fallback，F-47 落地前的旧 binary 不炸；同时支持过渡期调试（直接写 `extra` 也能读出）。
6. **`PermissionsConfig.rules` 用 `dict[str, list[str]]` 而不是 `list[PermissionRule]`**：与磁盘原样（字符串数组）对齐；`PermissionRule` 字符串解析走运行时现成的 `permissions/rule_parser.py:permission_rule_value_from_string`，不重新引入 dataclass 死代码。
7. **阶段化落地：1→2→3→4→5→6（可选）→7→8→9**：自包含 schema 改造先闭环（Sub-A + Sub-B + Sub-F），读路径 + 校验（Sub-C + Sub-E），启动模式 plumb（Sub-D），可选 setup 改造（Sub-F），最后清死代码（Sub-H）+ 测试（Sub-G）。每步独立可回滚。
8. **不动 runtime `PermissionRule`（`src/permissions/types.py:80-84`）**：那是 `ToolPermissionContext` 实际用的，与 settings 加载无关；F-47 只动 settings 层。

#### 风险与缓解

| 风险 | 缓解 |
|------|------|
| 死代码清理连带引用 | `grep -r "from src.settings.types import PermissionRule" src/ tests/` 确认唯一引用是 `from_dict:176-179`（本次同时改写） |
| pydantic-settings 后端 schema 漂移 | 本期只覆盖 dataclass 后端；F-47.1 单独补 pydantic 路径对齐，TODO 标在 `from_dict` 注释里 |
| 顶层 `permission_mode` 字段 deprecation 风险 | 本次只保留读取、不标 deprecated；F-46 后续阶段统一 deprecate。**F-47.1 (2026-06-02) hotfix 已先一步直接删除读取通道**，deprecation 步骤 N/A。 |
| `extra` 字段语义迁移 | `SettingsSchema.extra` 仍是"未识别 sub-key 的兜底"；F-47 之后 `permissions` 已知 sub-key 不再溢出到 `extra`，但其它未知 sub-key 仍走 `extra`（行为不变） |
| 改动 6 个文件 | 每个文件改动局部，git revert 风险可控；阶段化落地每步可独立 PR |
| F-47 与 F-46 顺序 | 两者不耦合，可独立 PR、并行落地；F-47 落地后 `permissions.defaultMode` 字段自动成为 F-46.0 拆 `audit_log` 后的"启动默认模式"读路径 |
| `validate_settings` 空 `permission_mode` 误报 | 旧默认值 `"default"` 合法；F-47 改成 `permission_mode: str = ""` 后空串跳过校验 |
| `for i, rule in enumerate(settings.permissions)` 旧代码潜在 TypeError | 旧校验段被 `isinstance(..., list)` 短路掩盖；F-47 直接重写为对 `rules` 字典的字符串非空检查，TypeError 不再有触发路径 |

#### 子特性

- **Sub-A** `PermissionsConfig` dataclass 定义（`src/settings/types.py`）
- **Sub-B** `SettingsSchema.from_dict` 加载改造（`src/settings/types.py:161-198`）
- **Sub-C** `has_allow_bypass_permissions_mode` 加 `_settings_perms` 聚合器（`src/permissions/modes.py:113-140`）
- **Sub-D** `resolve_permission_state` plumb（`clawcodex_ext/cli/permissions.py:36-39`）
- **Sub-E** `validate_settings` 重写（`src/settings/validation.py:32-38, 96-103`）
- **Sub-F** `DEFAULT_SETTINGS` 改造（`src/settings/constants.py:12-46`）
- **Sub-G** 单元测试 + e2e（`tests/test_permission_settings_schema.py` + `tests/manual_e2e_f38_permissions.py`）
- **Sub-H** 死代码清理（删除 `src/settings/types.py:13-20` `PermissionRule`）

#### 落地顺序（建议）

1. **Sub-A + Sub-B + Sub-F**（schema 自包含改造）—— 跑现有测试，确认无回归。`PermissionsConfig` 与 dict 互转是自包含的，不会触发其他模块报错。
2. **Sub-C + Sub-E**（读路径 + 校验）—— 读路径加了 fallback，旧 binary 仍能跑；校验移走对 `list[PermissionRule]` 的迭代，dict 形态合法。
3. **Sub-D**（`resolve_permission_state` plumb）—— 启动模式生效。
4. **Sub-F 可选**（`setup_permissions` 签名扩 `default_mode`）—— 不做也不影响当前 bug；F-47.1 后续必做。
5. **Sub-H**（清死代码）—— `grep` 确认无引用后落地。
6. **Sub-G**（7 条 unittest + 1 条 e2e）—— 最后覆盖。

#### 协同与影响

- **F-15**（Shift+Tab cycle）：F-15 实现了 `default→acceptEdits→plan→bypassPermissions→default` cycle；F-47 让 cycle 真正能切到 `bypassPermissions`。
- **F-31**（TUI 权限模式选择器）：TUI 模态对话框消费 `permissions.defaultMode` 字段。
- **F-46** 弱相关：F-46 后续 `interactive` / `default_decision` 字段落地时，`PermissionsConfig` 是天然的承接结构。
- **F-40** 无关：ProgressSink 重构不涉及 settings schema。
- **`docs/new-features-guide.md`**：F-47.1 阶段补"permission settings 配置迁移"章节，给新 schema 形态做用户级解释。**F-47.1 hotfix 后**：旧字段 `settings.permission_mode` 不再做 back-compat 读取，迁移章节需直接建议用户把顶层 `permission_mode` 改成 `permissions.defaultMode`，而不是"两种写法都生效"。

---

### 二十一10 F-34 CLI/TUI Frontend 解耦架构

**状态**: ✅ 已完成 Phase 1-3

#### 2.14.1 问题现状

当前 CLI、TUI、Headless 三个入口点各自重复构造核心依赖（Provider、ToolRegistry、ToolContext、Session），耦合图谱如下：

```
 src/cli.py (604行)
   ├── argparse 定义所有入口参数
   ├── _resolve_permission_state()           ← 共享，但存 args 上
   ├──→ _run_print_mode() → entrypoints/headless.py
   │     └── 自建 provider/registry/context/session
   ├──→ _run_tui_mode()   → entrypoints/tui.py → tui/app.py
   │     └── 自建 provider/registry/context/session
   └──→ start_repl()     → repl/core.py (ClawcodexREPL)
         └── 自建 provider/registry/context/session
```

**核心问题**：

| 问题 | 后果 |
|------|------|
| Provider/Registry/Session 构造代码 ×3 处 | 改动需同步 N 个入口，易遗漏 |
| argparse 参数与 frontend 选择耦合 | 加新 frontend 需改 argparse + dispatch + N 个 `_run_*_mode()` |
| Agent 循环实现 ×2（AgentBridge vs repl/core 内联） | bug 修复和行为变更需改两套代码 |
| 权限状态通过 args 传递 | 每个 frontend 要自己解释权限字符串配置 tool context |

#### 2.14.2 设计目标

1. **统一 Runtime 初始化**：消除 provider/registry/context/session 的三重复造
2. **Frontend 协议化**：任何 UI 实现只需实现 `Frontend` 协议即可接入
3. **Agent 循环单一实现**：一个 `AgentEngine` 供所有 frontend 使用
4. **插件式 frontend 注册**：`cli.py` 不再需要知道有哪些 frontend

**当前迁移约束**：项目级二开边界约束已推广至全项目范围。所有下游/定制功能（frontend 行为、runtime 接线、命令、UI 定制、provider/tool 编排变更）默认只能进入 `clawcodex_ext/*`；`src/cli.py`、`src/entrypoints/tui.py`、`src/tui/*` 和 `src/upstream/<rev>/*` 只保留最小适配、上游同步或窄范围 bug fix。具体示例路径：`clawcodex_ext/cli`、`clawcodex_ext/tui`、`clawcodex_ext/frontend`、`clawcodex_ext/runtime`。

**当前迁移进度**：✅ F-34 Phase 1-3 全部完成。
- Phase 1: CLI parser/dispatch 所有权迁入 `clawcodex_ext/cli/`
- Phase 2: `RuntimeContext` 工厂（`clawcodex_ext/runtime/context.py`）+ Frontend 协议/注册表（`clawcodex_ext/frontend/`）
- Phase 3: `ClawCodexExtTUI` 8 个扩展钩子就绪（`clawcodex_ext/tui/app.py`）

#### 2.14.3 架构概览

```
 src/runtime/
   ├── __init__.py           # 公共导出
   ├── context.py            # RuntimeContext（统一的 factory）
   ├── protocol.py           # Frontend 协议
   ├── events.py             # 标准化事件类型
   ├── engine.py             # AgentEngine（从 frontend 解耦的 agent 循环）
   └── registry.py           # Frontend 注册表（插件式）
```

#### 2.14.4 核心组件设计

##### 1. `RuntimeContext` — 统一运行时上下文

```python
# src/runtime/context.py

@dataclass
class RuntimeOptions:
    """构建 RuntimeContext 的选项，从 CLI args 或 API 调用中提取。"""
    provider_name: str | None = None
    model: str | None = None
    workspace_root: Path | None = None
    max_turns: int = 20
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    permission_mode: str = "default"
    is_bypass_permissions_mode_available: bool = False
    resume_session_id: str | None = None
    resume_browse: bool = False
    stream: bool = True
    verbose: bool = False


@dataclass
class RuntimeContext:
    """每个 frontend 启动时必需的共享上下文。

    取代三个入口点各自重复的 provider/registry/context/session 构造。
    """
    provider: object                         # BaseProvider 实例
    provider_name: str
    model: str
    workspace_root: Path
    tool_registry: ToolRegistry
    tool_context: ToolContext
    session: Session
    permission_mode: str
    is_bypass_permissions_mode_available: bool
    max_turns: int = 20
    stream: bool = True
    cost_tracker: CostTracker | None = None
    history: HistoryLog | None = None

    @classmethod
    def build(cls, options: RuntimeOptions) -> RuntimeContext:
        """统一的 factory 方法，替代 3 套重复代码。

        负责：
        1. 解析 provider_name → 构建 provider 实例
        2. 调用 build_default_registry()
        3. 创建 ToolContext
        4. 创建或恢复 Session
        5. 应用工具过滤（allowed/disallowed）
        6. 应用权限状态
        """
        # ... 统一实现，消除三个入口点的重复代码
```

##### 2. `Frontend` 协议

```python
# src/runtime/protocol.py

class Frontend(Protocol):
    """UI 前端必须实现的协议。

    实现此协议即可注册为 clawcodex 的可用前端。
    """

    # 元信息（供 CLI --help 和注册表使用）
    name: str                                  # 唯一标识，如 "repl", "tui", "headless"
    display_name: str                          # 显示名称，如 "Interactive REPL"
    description: str                           # 简短描述

    def run(self, ctx: RuntimeContext) -> int:
        """运行前端，返回 CLI 退出码。"""
        ...

    # 可选 hook
    def on_start(self, ctx: RuntimeContext) -> None: ...
    def on_finish(self, exit_code: int) -> None: ...

    # 可选：此前端支持的 CLI 参数组
    @classmethod
    def argparse_group(cls, parser: argparse.ArgumentParser) -> None: ...
```

##### 3. `AgentEngine` — 统一 Agent 循环

```python
# src/runtime/engine.py

@dataclass
class AgentEngine:
    """从 frontend 解耦的 agent 循环，提供统一的 submit/cancel/event 接口。

    替代：
    - tui/agent_bridge.py (TUI 专用)
    - repl/core.py 中的内联 agent 循环
    """

    session: Session
    provider: object
    tool_registry: ToolRegistry
    tool_context: ToolContext
    max_turns: int = 20
    stream: bool = True

    def submit(self, prompt: str) -> bool:
        """提交用户输入，启动 agent 循环。返回 False 表示忙。"""
        ...

    def cancel(self) -> bool:
        """取消当前 agent 运行。返回 False 表示无运行中。"""
        ...

    # 事件流（订阅者模式）
    def subscribe(self, event_type: type, callback: Callable) -> None: ...
    def unsubscribe(self, event_type: type, callback: Callable) -> None: ...

    # 生命周期
    async def run(self) -> None: ...
    def stop(self) -> None: ...
```

##### 4. `FrontendRegistry` — 插件式注册表

```python
# src/runtime/registry.py

_frontends: dict[str, type[Frontend]] = {}

def register(name: str, frontend_cls: type[Frontend]) -> None:
    """注册一个前端实现。"""
    _frontends[name] = frontend_cls

def get(name: str) -> type[Frontend] | None:
    """按名称获取前端类。"""
    return _frontends.get(name)

def list_frontends() -> dict[str, type[Frontend]]:
    """返回所有已注册的前端。"""
    return dict(_frontends)

def available_names() -> list[str]:
    """返回所有已注册前端名称列表（按注册顺序）。"""
    return list(_frontends.keys())

def dispatch(args) -> int:
    """根据 CLI args 选择并运行前端。

    Args:
        args: argparse.Namespace，含 ``_frontend`` 属性

    Returns:
        CLI 退出码
    """
    name = getattr(args, '_frontend', None) or os.environ.get('CLAWCODEX_FRONTEND', 'repl')
    frontend_cls = get(name)
    if frontend_cls is None:
        console = Console(stderr=True)
        console.print(f"[red]Unknown frontend: {name}[/red]")
        console.print(f"Available: {', '.join(available_names())}")
        return 1

    options = _build_runtime_options(args)
    ctx = RuntimeContext.build(options)
    return frontend_cls().run(ctx)
```

#### 2.14.5 标准事件类型

```python
# src/runtime/events.py

@dataclass
class TextChunkEvent:
    """LLM 返回的文本片段（流式）。"""
    text: str

@dataclass
class ToolUseEvent:
    """Agent 请求使用工具。"""
    tool_name: str
    tool_input: dict
    tool_use_id: str

@dataclass
class ToolResultEvent:
    """工具执行结果。"""
    tool_use_id: str
    tool_name: str
    output: str
    is_error: bool

@dataclass
class PermissionRequested:
    """工具需要用户授权。"""
    tool_name: str
    tool_input: dict
    permission_id: str
    resolve: Callable[[bool], None]

@dataclass
class ErrorEvent:
    """Agent 循环中发生错误。"""
    error: str
    fatal: bool = False

@dataclass
class DoneEvent:
    """Agent 循环完成。"""
    total_turns: int
    total_cost: float | None
```

#### 2.14.6 分阶段实施计划

##### Phase 1 — 提取 `RuntimeContext`（消除 3 处重复构造）

| 步骤 | 内容 | 文件 | 工作量 |
|------|------|------|--------|
| 1.1 | 创建 `src/runtime/context.py`（`RuntimeOptions` + `RuntimeContext.build()`） | 新增 | 2h |
| 1.2 | 创建 `src/runtime/__init__.py`（导出） | 新增 | 5min |
| 1.3 | 修改 `src/entrypoints/tui.py` → 使用 `RuntimeContext.build()` | 修改 | 30min |
| 1.4 | 修改 `src/repl/core.py` → `ClawcodexREPL` 接受 `RuntimeContext` | 修改 | 30min |
| 1.5 | 修改 `src/entrypoints/headless.py` → 使用 `RuntimeContext.build()` | 修改 | 30min |
| 1.6 | 验证：三入口点行为不变 | 测试 | 30min |

**Phase 1 后状态**：三入口点各减 30-50 行重复代码

##### Phase 2 — 提取 `AgentEngine`（统一 agent 循环）

| 步骤 | 内容 | 文件 | 工作量 |
|------|------|------|--------|
| 2.1 | 创建 `src/runtime/events.py`（标准事件类型） | 新增 | 30min |
| 2.2 | 创建 `src/runtime/engine.py`（`AgentEngine`） | 新增 | 4h |
| 2.3 | 修改 `tui/agent_bridge.py` → 封装/委派给 `AgentEngine` | 修改 | 2h |
| 2.4 | 修改 `repl/core.py` → 使用 `AgentEngine` | 修改 | 2h |
| 2.5 | 集成测试：TUI + REPL 正常 submit/cancel/event | 测试 | 1h |

##### Phase 3 — Frontend 协议 + 注册表（插件化）

| 步骤 | 内容 | 文件 | 工作量 |
|------|------|------|--------|
| 3.1 | 创建 `src/runtime/protocol.py`（`Frontend` 协议） | 新增 | 30min |
| 3.2 | 创建 `src/runtime/registry.py`（注册表 + dispatch） | 新增 | 1h |
| 3.3 | 实现 `ReplFrontend`、`TuiFrontend`、`HeadlessFrontend` | 新增 | 2h |
| 3.4 | 修改 `src/cli.py` → 使用 `registry.dispatch()` + 注册 | 修改 | 1h |
| 3.5 | 注册 `claude_repl` 和 `clawcodex_cli_integration` 的 frontend | 注册 | 各 1h |

##### Phase 4（可选）— CLI 参数插件化

| 步骤 | 内容 | 文件 | 工作量 |
|------|------|------|--------|
| 4.1 | Frontend 协议增加 `argparse_group()` 类方法 | 修改 protocol | 30min |
| 4.2 | CLI 遍历注册表收集参数组 | 修改 cli.py | 1h |
| 4.3 | 各 frontend 实现自己的参数组 | 各 frontend | 各 30min |

#### 2.14.7 文件变更清单

| 操作 | 文件路径 | Phase |
|------|----------|-------|
| 新增 | `src/runtime/__init__.py` | 1 |
| 新增 | `src/runtime/context.py` | 1 |
| 新增 | `src/runtime/events.py` | 2 |
| 新增 | `src/runtime/engine.py` | 2 |
| 新增 | `src/runtime/protocol.py` | 3 |
| 新增 | `src/runtime/registry.py` | 3 |
| 修改 | `src/cli.py` | 1-3 |
| 修改 | `src/entrypoints/tui.py` | 1-3 |
| 修改 | `src/entrypoints/headless.py` | 1-3 |
| 修改 | `src/repl/core.py` | 1-3 |
| 修改 | `src/tui/app.py` | 1-3 |
| 修改 | `src/tui/agent_bridge.py` | 2 |

#### 2.14.8 集成外部 Frontend

##### 集成 `claude_repl`

```python
# claude_repl 项目内
from clawcodex.runtime import Frontend, RuntimeContext, register

class ClaudeReplFrontend:
    name = "claude-repl"
    display_name = "Claude REPL"
    description = "Claude 原生命令行 REPL 体验"

    def run(self, ctx: RuntimeContext) -> int:
        # 使用 ctx.provider, ctx.session, ctx.tool_registry
        # 运行 claude_repl 自己的 REPL 循环
        ...

# 注册
register("claude-repl", ClaudeReplFrontend)
```

##### 集成 `clawcodex_cli_integration`

```python
# clawcodex_cli_integration 项目内
from clawcodex.runtime import Frontend, RuntimeContext, register

class CliIntegrationFrontend:
    name = "cli-integration"
    display_name = "CLI Integration"
    description = "集成式 CLI 工具包"

    def run(self, ctx: RuntimeContext) -> int:
        # 使用 ctx 运行集成式 CLI
        ...

register("cli-integration", CliIntegrationFrontend)
```

使用方式：
```bash
# 指定 frontend
clawcodex --frontend claude-repl -p "hello"
clawcodex --frontend cli-integration --tui

# 环境变量全局切换
export CLAWCODEX_FRONTEND=claude-repl
clawcodex  # 自动使用 claude-repl
```

#### 2.14.9 与上游解耦的关系

解耦后的架构使得二开版本和上游版本能共享同一套 frontend 协议：

```
上游版本:
  clawcodex (upstream)
    └── 注册 repl, tui, headless

下游二开:
  clawcodex (clawcodex)
    ├── 注册 repl (二改版), tui (二改版), headless
    └── 注册 claude-repl (新增)
    └── 注册 cli-integration (新增)
```

**好处**：
- 上游升级 `repl`/`tui` 模块时，只需更新对应的 Frontend 实现
- 二开版本保持自己的 frontend 自定义行为，不影响上游 core
- 第三方 frontend 无需修改 clawcodex 核心代码

#### 2.14.10 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| `RuntimeContext.build()` 耦合了 provider/registry 实现 | 更换 provider/registry 需要修改 build | 抽象 ProviderFactory/RegistryFactory，可配置 |
| `AgentEngine` 与现有 AgentBridge 行为差异 | TUI 行为回归 | Phase 2 中保留 AgentBridge 接口，内部委派，逐步替换 |
| 第三方 frontend 需要引用 `clawcodex.runtime` | import 耦合 | runtime 模块设计为对外无副作用，仅依赖公共类型 |
| 重构过程中破坏已实现功能 | 开发中断 | 每个 Phase 完成后执行完整的集成测试套件 |

---

*文档更新时间: 2026-06-07*

*版本 v1.8 更新：新增 F-44 人工检视闸门、F-51 AgentRunner 空转检测、F-50 SOP 转换器源码固化、cacheWarning 容量限制等 4 项已实现功能归档。*

---

### 二十一.11 F-44 Orchestrator 人工检视闸门（Review Gate）

#### 目标

为 Orchestrator 自动开发流程添加可选的人工检视闸门，实现"自动开发 + 人工合并"的协作模式，对应选项 A 架构。

#### 设计目标

- **配置可控**：`workflow.md` 中 `agent.review_required: true/false` 决定是否启用
- **向后兼容**：默认 `false`，不影响现有 LocalTracker 和远程 tracker 流程
- **状态准确**：`PENDING_REVIEW` 状态不被后续 `mark_completed()` 覆盖
- **CLI 操作**：支持 `clawcodex-dev orchestrator issue review --id <id> --approve | --reject`

#### 配置模型

```yaml
# workflow.md
agent:
  review_required: true   # F-44: 启用人工检视闸门
```

- `AgentConfig.review_required: bool = False`（默认关闭）
- `from_dict()` 从 YAML 解析

#### 状态流转

```
无变更 ────────────────────────────────────→ COMPLETED（跳过闸门）

有变更 + review_required=false ────────────→ COMPLETED（跳过闸门）
有变更 + review_required=true  ─────┐
                                    ├──[approve]──→ COMPLETED
                                    └──[reject]──→ 自动 retry（F-39）
```

#### 架构变更

| 组件 | 变更 |
|------|------|
| `schema.py` | `AgentConfig.review_required: bool` 新字段 + `from_dict` 解析 |
| `git_sync.py` | `pending_review` 触发条件：`is_local_tracker or review_required` |
| `orchestrator.py` | `finally` 块新增 `pending_review` 检测，修复状态覆盖 bug |

#### 与已有组件的关系

| 组件 | 关系 |
|------|------|
| `GitSyncService.sync()` | `result.pending_review=True` 时不上传 manifest |
| `IssueRegistry` | `pending_review` 集等待人工 approve；Orchestrator 重启后持久化 |
| F-39 retry | reject 自动触发 retry，重置 review 状态 |
| CLI issue review | 已有 review/approve/reject 命令，无需改造 |
| F-38 验证闭环 | 验证通过 + review gate → PENDING_REVIEW，非直接 COMPLETED |

#### 验收标准

1. `review_required: false` → 行为不变，自动完成
2. `review_required: true` + 有代码变更 → PENDING_REVIEW，等待审批
3. `clawcodex-dev orchestrator issue review --id <id> --approve` → 标记完成
4. `clawcodex-dev orchestrator issue review --id <id> --reject --feedback "..."` → 自动 retry
5. Orchestrator 重启后 PENDING_REVIEW 状态仍可查看和操作
6. 全部 orchestrator 测试通过（82 passed）

---

### 二十一.12 F-51 AgentRunner 空转检测机制（no-op detection）

#### 背景

Orchestrator 处理 issue 时，若该 issue 的 deliverables 已在 base branch 中存在（例如通过上游 commit 预置、或在 shared workspace 中被前一个 issue 实现），agent 会陷入无意义循环：反复运行 `python3 --version` / `date` 等 busy-work 命令 → 无文件变更 → session 持续 continue → 耗尽 max_turns → retry → 再循环。

#### 问题根因

| 缺口 | 描述 |
|------|------|
| Prompt 层 | 无指令告诉 agent "如果 deliverables 已实现且验证通过，直接完成" |
| Agent Loop 层 | 无工作区文件变更检测：SessionComplete 后不检查是否产生了实际代码变更 |
| Retry 层 | `max_turns_exceeded` → retry 循环，但 agent 仍然面对同一场景 |

#### 解法

**代码层**（`extensions/orchestrator/agent_runner.py`）：

```
每轮 SessionComplete 后:
    dirty = bool(get_file_status(workspace))
    if dirty: consecutive_clean_turns = 0
    else:     consecutive_clean_turns += 1
    if consecutive_clean_turns >= 5:
        force session.status = "completed"
        return
```

- 导入 `get_file_status`（O(1) 本地 git status 缓存）
- 常量 `_NOOP_DETECTION_MAX_TURNS = 5`（微调：适当值 3~10）
- 计数器跟随 session 生命周期，不跨 session 持久化

**Prompt 层**（`workflow.md`）：

Step 3 末尾增加一条："如果该 issue 的功能已经在代码库中实现且验证通过，直接报告完成，无需修改。"

#### 与已有组件的关系

| 组件 | 关系 |
|------|------|
| `AgentRunner.run()` | 修改入口：在 continue 路径中添加空转检测 |
| `GitSyncService.sync()` | 下游：`changed=False` 时跳过 git commit/push |
| `IssueRegistry` | 下游：标记 completed，无 push 不触发 PR |
| `ProgressReporter` | 无影响：空转检测在 SessionComplete 之后进行 |
| F-39 retry 逻辑 | 修复后：不再对"已完成但 issue 未更新"场景 retry |

#### 文件变更

| 文件 | 改动 |
|------|------|
| `extensions/orchestrator/agent_runner.py` | +29 行：import + 常量 + 检测逻辑 + 日志 |
| `workflow.md`（本地编排配置） | +1 条 prompt 指令 |

#### 验收

1. Agent 面对已存在的 deliverables → ≤5 轮自动完成
2. 主动开发中 → 空转计数器持续重置，不影响
3. 日志可审计：`No-op detection triggered issue_id=...`
4. 不增加 retry 循环，issue 正常 closed

---

### 二十一.13 F-50 SOP 转换器源码固化（SourceCodeParser + 增强 SkillGrouper + AgentMarkdownWriter）

#### 背景

`extensions/pos_converter/` 现有 SDK-to-Agent 三层映射（`SdkParser` → `SkillGrouper` → `AgentBuilder`）只支持 **OpenAPI / 逗号分隔方法名** 等轻量输入，无法处理真实的 **Python 源码级 SDK**。

AscendDataForge 实践中手动完成了 Python 源码到 Agent 的转换，揭示了三个通用缺口：

| 缺口 | 现有组件 | 上限 | 需要的新组件 |
|------|----------|------|-------------|
| Python 源码解析 | `SdkParser._parse_simple_list()` 仅按字符拆分 | 不支持类/方法/docstring/参数/返回类型 | `SourceCodeParser` |
| 组件级分组 | `SkillGrouper._static_group()` 仅关键字匹配 | 不理解模块层次、输入输出关联 | 增强 `SkillGrouper` 策略 |
| `.claude/agents/*.md` 生成 | `AgentBuilder.write_agent_markdown()` 只输出极简 YAML | 缺少完整 frontmatter、技能参考文档 | `AgentMarkdownWriter` |

#### 架构总览

```
Python 源码目录（.py 文件）
     │
     ▼
 SourceCodeParser（新增）
  ├── ModuleWalker → 递归扫描 .py 文件
  ├── ClassExtractor → 提取类定义、方法签名
  ├── DocstringParser → Google/NumPy/reST docstring → 结构化描述
  ├── ParamInferer → 参数名 + 类型注解 + 默认值 → ParamSpec
  └── DependencyAnalyzer → import 图 → 组件依赖关系
     │
     ├──► SourceComponent[]（正式 schema）
     │
     ▼
 SkillGrouper 策略增强（增量修改）
  ├── 组件级分组（现有 _static_group 保留）
  ├── 输入输出关联分组（共享同类型参数的 operations 归组）
  └── 语义 LLM 分组（预留 _group_with_llm 实现）
     │
     ├──► SkillSpec[]
     │
     ▼
 AgentBuilder（增量修改）
  └──► AgentDefinition → AgentMarkdownWriter（新增）
       ├── .claude/agents/<name>.md（CLI 直接加载）
       ├── .atomcode/skills/<name>/SKILL.md
       └── 技能参考脚本目录（操作源码片段嵌入）
```

#### 子模块一：SourceCodeParser（`extensions/pos_converter/source_parser.py`）

```python
@dataclass
class SourceComponent:
    name: str                       # "VideoOperations"
    file_path: str                  # "组件/视频算子/video_ops/video_operations.py"
    description: str                # docstring 首段
    operations: list[SourceOperation]
    dependencies: list[str]         # import 列表（去重本地文件）
    input_schema: dict              # 解析出的输入字段 {name: type_hint}
    output_schema: dict             # {name: type_hint}

@dataclass
class SourceOperation:
    name: str
    description: str                # 方法 docstring
    parameters: list[ParamSpec]
    return_type: str | None
    source_code: str                # 完整源码片段，嵌入技能参考

@dataclass
class ParamSpec:
    name: str
    type_hint: str | None
    default: Any | None
    required: bool
```

输入：一个目录路径（递归扫描 `.py` 文件）。输出：`list[SourceComponent]`。

#### 子模块二：增强 SkillGrouper 策略（`extensions/pos_converter/skill_grouper.py` 增量）

```python
class GroupStrategy(Enum):
    KEYWORD_MATCH = "keyword_match"      # 现有：MappingRule 静态匹配
    COMPONENT_GROUP = "component_group"  # 新增：按 SourceComponent 归属
    IO_RELATION = "io_relation"          # 新增：按输入输出关联
    LLM_SEMANTIC = "llm_semantic"        # 预留：LLM 语义分组
```

| 策略 | 输入 | 分组逻辑 | 适用场景 |
|------|------|----------|---------|
| `KEYWORD_MATCH` | `MappingRule[]` | `method_pattern in method.name` | SDK 方法名规范 |
| `COMPONENT_GROUP` | `SourceComponent[]` | 同一组件的 operations 归为一个 Skill | 结构化 Python SDK |
| `IO_RELATION` | `SourceComponent[]` | 参数类型匹配的跨组件操作归组 | 编排场景 |
| `LLM_SEMANTIC` | `SdkMethod[]` + `requirements` | LLM 判断业务相关性 | 任意 DSL |

#### 子模块三：AgentMarkdownWriter（`extensions/pos_converter/agent_md_writer.py`）

```python
@dataclass
class AgentMarkdownWriter:
    def write_agent(self, agent_def: AgentDefinition, output_dir: Path) -> Path
        """生成 <name>.md，包含完整 frontmatter + system prompt。"""
    def write_skills(self, skills: list[SkillSpec], output_dir: Path) -> list[Path]
        """生成 .atomcode/skills/<name>/SKILL.md，包含完整操作参考。"""
    def write_workflow(self, name: str, skills: list[SkillSpec], output_dir: Path) -> Path
        """可选：生成 orchestrator WORKFLOW.md。"""
```

输出目录结构：

```
<output_dir>/
├── .claude/
│   └── agents/
│       └── <agent-name>.md            ← CLI `@agent-name` 加载
└── .atomcode/
    └── skills/
        └── <skill-name>/
            ├── SKILL.md               ← skill 定义 + 参数说明
            └── reference/             ← 嵌入的操作源码/文档片段
                └── ...
```

#### 子模块四：总览 Agent（Overview Agent）

除了为每个组件生成独立 Agent 外，SOP **始终生成**一个**总览 Agent**（无需额外参数），它：
- 知晓所有组件 Agent 的名称和职责
- 理解整体工作流的阶段顺序（如 数据接入 → 视频处理 → 质量检测 → 结果输出）
- 在收到用户请求时，能判断应交给哪个 `@agent-<component>` 处理，或执行跨组件的编排
- 提供一站式入口，用户无需了解内部组件划分即可使用

生成逻辑在 `AgentMarkdownWriter` 中新增 `write_overview_agent()` 方法。

#### 启动时默认 Agent 替换机制

生成的 `clawcodex-overview.md` 需要能被 clawcodex **加载为默认 Agent**（替换通用 Claw Codex agent）：

```
优先级（高→低）：
 1. --agent <agent-type> 显式指定             # 明确覆盖
 2. .claude/agents/clawcodex-overview.md 存在   # 自动检测
 3. GENERAL_PURPOSE_AGENT（当前默认行为）        # 兜底
```

实现方式：在 `extensions/pos_converter/default_agent.py` 中新增 `resolve_default_agent()`，在 REPL 启动路径中调用。

#### 启动时 Agent 标识 Banner

在 `_resolve_startup_agent()`（`clawcodex_ext/cli/dispatch.py`）中增加了启动 banner：

```
⚡ Using agent: ascend-dataforge (28 sub-agents)
```

- 当解析到的 agent 的 `skills` 列表中有 `skill-` 前缀项时，统计为 sub-agent 数量并显示
- 无自定义 Agent 时不输出，保持零 banner 启动
- 所有输出走 `stderr`，不干扰 stdout 管道

#### CLI 集成增强

```
clawcodex-dev pos convert <sdk_spec>          # 现有：OpenAPI / 方法列表
clawcodex-dev pos convert ./path/to/src       # 新增：Python 源码目录
                     --out .claude            # 输出到 .claude/agents/
                     --skills .atomcode/skills
                     --workflow               # 额外生成 WORKFLOW.md
                     --name my-agent          # 指定 agent 名称
                     --strategy component     # 分组策略
clawcodex-dev --agent clawcodex-overview      # 以总览 Agent 为默认 agent 启动
```

#### 验收标准

1. `clawcodex-dev pos convert ./组件/视频算子 --out .claude` 生成可被 CLI 加载的 agent markdown
2. 多组件目录自动生成 `clawcodex-overview.md`，包含工作流概述和子 Agent 委派指引
3. `SourceCodeParser` 正确提取类名、方法名、参数、docstring、import 依赖
4. 生成的 Agent markdown 符合 `load_agents_dir.py` 的解析格式
5. 生成的 `SKILL.md` 可在 CLI 中通过 `@skill-name` 调用
6. 所有新增代码通过 `python3 -m pytest tests/test_pos_converter*.py -q`
7. `resolve_default_agent()` 检测到 `clawcodex-overview.md` 时返回对应 definition；未找到时返回 None

#### 已拟定的设计决定

1. **`SourceCodeParser` 不对源码做语义分析**——只做结构化提取。语义理解归 LLM。
2. **`SourceComponent` 是纯数据容器**——不包含业务逻辑，保持可序列化、可测试。
3. **`.claude/agents/*.md` 是本路径的默认输出格式**。
4. **`GroupStrategy` 支持组合**——例如 `component | io_relation`。
5. **保留 `_static_group()` 作为所有策略的 fallback**。
6. **技能参考脚本用文件嵌入而非模板渲染**——保持源码的原样性。
7. **总览 Agent 命名使用 `clawcodex-overview`**。
8. **`--agent` CLI 参数覆盖 > `clawcodex-overview.md` 自动检测 > 默认 `GENERAL_PURPOSE_AGENT`**。
9. **总览 Agent 的 system prompt 以 `append_system_prompt` 形式注入**。
10. **总览 Agent 的 system prompt 是静态生成的**。

---

### 二十一.14 cacheWarning 容量限制（F-12）

#### 功能说明

为 `cacheWarningStateBySource` Map 设置容量上限以防止内存泄漏：

```python
MAX_SOURCE_ENTRIES = 50

def update_cache_warning(source: str, state: CacheWarningState):
    if len(cacheWarningStateBySource) >= MAX_SOURCE_ENTRIES:
        oldest_key = next(iter(cacheWarningStateBySource))
        del cacheWarningStateBySource[oldest_key]
    cacheWarningStateBySource[source] = state
```

#### 问题场景

- querySource 类型为 any
- 长时间会话产生大量唯一 source 值
- Map 无限增长导致内存泄漏

#### 实现文件

| 文件 | 位置 |
|------|------|
| cacheWarning | `utils/cacheWarning.ts` → `utils/cache_warning.py` |

---

---

## 二十二、补录已归档功能（对齐 FEATURE_PLAN v3.0）

> 以下功能在早期版本中已完成但未归档至本文档，现补录条目。详细设计见 FEATURE_PLAN.md 对应章节。

### F-3: MCP 扩展功能

| 属性 | 值 |
|------|-----|
| F-Number | F-3 |
| 功能 | MCP 扩展功能 |
| 章节 | §2.4 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.4 |

### F-4: 结构化输出增强

| 属性 | 值 |
|------|-----|
| F-Number | F-4 |
| 功能 | 结构化输出增强 |
| 章节 | §2.3 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.3 |

### F-14: 三层解耦架构

| 属性 | 值 |
|------|-----|
| F-Number | F-14 |
| 功能 | 三层解耦架构 |
| 章节 | §1.2 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §1.2 |

### F-17: 工具系统按需加载

| 属性 | 值 |
|------|-----|
| F-Number | F-17 |
| 功能 | 工具系统按需加载 |
| 章节 | §1.3 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §1.3 |

### F-20: Agent 进度汇报

| 属性 | 值 |
|------|-----|
| F-Number | F-20 |
| 功能 | Agent 进度汇报 |
| 章节 | §2.1 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.1 |

### F-21: 后台运行 + 恢复同步

| 属性 | 值 |
|------|-----|
| F-Number | F-21 |
| 功能 | 后台运行 + 恢复同步 |
| 章节 | §6 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §6 |

### F-24: Agent Loop Consolidation

| 属性 | 值 |
|------|-----|
| F-Number | F-24 |
| 功能 | Agent Loop Consolidation |
| 章节 | §2.1 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.1 |

### F-25: Advisor Token 计数

| 属性 | 值 |
|------|-----|
| F-Number | F-25 |
| 功能 | Advisor Token 计数 |
| 章节 | §2.1 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.1 |

### F-27: TUI 响应性修复

| 属性 | 值 |
|------|-----|
| F-Number | F-27 |
| 功能 | TUI 响应性修复 |
| 章节 | §3 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §3 |

### F-29: TaskInspect/TaskDirectives 注册

| 属性 | 值 |
|------|-----|
| F-Number | F-29 |
| 功能 | TaskInspect/TaskDirectives 注册 |
| 章节 | §2.1 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.1 |

### F-30: ProgressReportTool 注册

| 属性 | 值 |
|------|-----|
| F-Number | F-30 |
| 功能 | ProgressReportTool 注册 |
| 章节 | §2.1 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §2.1 |

### F-32: 会话恢复浏览器

| 属性 | 值 |
|------|-----|
| F-Number | F-32 |
| 功能 | 会话恢复浏览器 |
| 章节 | §6 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §6 |

### F-48: src/ 解耦方案

| 属性 | 值 |
|------|-----|
| F-Number | F-48 |
| 功能 | src/ 解耦方案 |
| 章节 | §4.1 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §4.1 |

### F-49: 会话统一存储

| 属性 | 值 |
|------|-----|
| F-Number | F-49 |
| 功能 | 会话统一存储 |
| 章节 | §1.4.2 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §1.4.2 |

### F-52: SDK→Tool 注册

| 属性 | 值 |
|------|-----|
| F-Number | F-52 |
| 功能 | SDK→Tool 注册 |
| 章节 | §4.3 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §4.3 |

### F-53: Tool→CLI 命令映射

| 属性 | 值 |
|------|-----|
| F-Number | F-53 |
| 功能 | Tool→CLI 命令映射 |
| 章节 | §4.4 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §4.4 |

### F-54: 运行期可观测性

| 属性 | 值 |
|------|-----|
| F-Number | F-54 |
| 功能 | 运行期可观测性 |
| 章节 | §1.3.2 |
| 状态 | ✅ 已归档 |
| 详细设计 | 见 FEATURE_PLAN.md §1.3.2 |

### F-99: Ctrl+C/B 即时中断响应优化

| 属性 | 值 |
|------|-----|
| F-Number | F-99 |
| 功能 | Ctrl+C/B 即时中断响应优化 |
| 章节 | §2.15 |
| 状态 | ✅ 已完成（2026-06-17） |
| 详细设计 | 见 FEATURE_PLAN.md §2.15 |

#### 实施摘要

三方案组合一次性落地，不拆分单独上线：

| 方案 | 文件 | 改动 |
|------|------|------|
| 方案1 (P0) httpx read_timeout | `src/providers/anthropic_provider.py` | `_ensure_client()` 默认注入 `timeout=_F99_READ_TIMEOUT (5.0)`，仅在 caller 未传 `timeout` 或 `http_client` 时生效，避免覆盖用户自定义 httpx client |
| 方案2 (P1) 传输连接关闭 | `src/providers/_stream_abort.py` | 新增 `_close_transport_safely()` 调用 `response._transport.close()`；Windows (`sys.platform == 'win32'`) 跳过避免 Winsock deadlock；`getattr` 兜底防 httpx 内部属性名变化 |
| 方案3 (P2) 工具阶段可取消 | `src/query/query.py` | `_run_tools_partitioned` 把 `asyncio.gather` 改为 `asyncio.wait(FIRST_COMPLETED, timeout=0.1)`，100ms abort poll 间隔；finally 中取消未完成 task 并合成 cancelled tool_result 保 tool_use/tool_result 配对；exclusive batch 在 abort 时短路剩余工具 |

#### 验收对账

| 验收项 | 实测 | 备注 |
|--------|------|------|
| 直连 Anthropic 时 Ctrl+C 在 <500ms 内返回 | ✅ | 方案2 强制关 transport socket，`StreamAbortGuard.reraise_if_aborted` 翻译为 `AbortError` |
| LiteLLM 代理下 Ctrl+C 在 <5s 内返回 | ✅ | 方案1 `read_timeout=5s` bound，方案2 关 transport 后无需等 timeout |
| 工具阶段 Ctrl+C 在 <500ms 内取消 | ✅ | 方案3 100ms poll + `task.cancel()` 立即短路 |
| 并发工具 abort 不等待非必要工具 | ✅ | `FIRST_COMPLETED` + 100ms abort poll；新增 4 个单测覆盖（含 pairing 守恒） |
| 正常流式响应不受影响 | ✅ | 方案1 read_timeout 在无 abort 时不被触发；现有 `StreamWatchdog` 90s 兜底保留 |
| `_close_response_safely` 异常安全 | ✅ | 新增 6 个单测覆盖：非 Windows 关 transport、Windows 跳过、缺 `_transport` 属性、transport.close 抛错、listener 路径、attach context 路径 |

#### 新增测试

- `tests/provider/test_f99_anthropic_read_timeout.py` — 6 测试：常量固定 5.0、超时/httpx_client 覆盖、缓存契约、base_url 透传
- `tests/query/test_f99_first_completed.py` — 4 测试：abort 短路、pairing 守恒、单工具路径不变、无 abort 时全量完成
- `tests/abort/test_stream_abort_guard.py` 追加 6 测试：transport close 全平台/Windows 跳过/缺属性/抛错/attach listener/异常安全

#### 风险缓解落地

| 风险 | 缓解措施 | 实现 |
|------|---------|------|
| httpx `_transport` 内部属性依赖 | `getattr` 兜底 + 注释标注 | `_close_transport_safely` 三重 getattr 链 |
| `asyncio.wait(FIRST_COMPLETED)` 增加调度复杂度 | 封装 `_run_concurrent_batch` 嵌套函数 | query.py 内局部函数 + 详细 docstring |
| `read_timeout=5s` 在慢 chunk 时误触发 | 保留 `StreamWatchdog` 90s 兜底 | 方案1 仅在 abort 路径生效，正常流不受影响 |
| `transport.close()` 在 Windows 不可用 | `sys.platform == 'win32'` 跳过 | `_close_transport_safely` 顶部 platform 检查 |



## 二十三、代码审查归档——已完成特性设计详情（FEATURE_PLAN v3.x）

> 以下特性在 FEATURE_PLAN.md 中标记为 ✅ 已完成，现将完整设计详情从 FEATURE_PLAN.md 迁移至此。
> 源文档对应章节保留索引链接。

### 二十三.1 F-18 CreateAgentTool 动态工具创建

**状态**: ✅ 已完成
**目标**: Agent 可根据三方 CLI/API 规范动态创建工具，实现"工具创建工具"的 Meta Tool 能力

commit 59d8243 补齐集成闭环：CreateAgentTool 已注册为内置工具 (`EXTENSION_TOOLS`)，启动时自动加载持久化 Agent 工具 (`build_default_registry(load_agent_tools=True)`)，`ToolContext.tool_registry` 提供运行时注册表接线。

#### 功能说明
允许 Agent 分析第三方工具（CLI 命令或 HTTP API）的接口规范，然后动态创建一个可用的工具：
```
Agent 分析 CLI 规范 → 生成工具规范 → 调用 CreateAgentTool → 注册新工具 → 使用新工具
```

#### 架构设计
```
# 核心实现（clawcodex_ext — 与上游解耦）
clawcodex_ext/tool_system/tools/create_agent_tool.py    # CreateAgentTool 实现（入口）
clawcodex_ext/agent/tool_authoring/                     # Tool 创建基础设施
├── spec.py                         # AgentToolSpec 定义
├── validators.py                   # 规范验证器
├── factory.py                      # build_tool() 调用封装
├── registry_ext.py                 # Agent 创建工具注册表
├── persistence.py                  # 工具持久化
└── call_handlers/                  # call_impl 处理
    ├── bash.py                     # bash 命令调用
    ├── http.py                     # HTTP 请求调用
    └── python.py                   # Python 函数映射

# 集成接线（启动时自动注册）
extensions/tool_system_ext/registration.py   # EXTENSION_TOOLS 列表包含 make_create_agent_tool()
src/tool_system/defaults.py                  # build_default_registry(load_agent_tools=True) 自动加载持久化工具
src/tool_system/context.py                   # ToolContext.tool_registry 字段
clawcodex_ext/runtime/context.py             # 运行时传递 tool_registry
```

#### 工具规范（AgentToolSpec）
```python
@dataclass(frozen=True)
class AgentToolSpec:
    name: str                          # 工具唯一名称
    description: str                   # 工具描述
    input_schema: dict                 # JSON Schema
    call_type: "bash" | "http" | "python"  # 调用类型
    call_impl: str | dict              # 实现（类型依赖）
    tags: list[str] = field(default_factory=list)  # 分类标签
    aliases: tuple[str, ...] = ()
    source: str = "agent-created"      # 来源标记
```

#### 三种 call_impl 安全限制
| call_type | call_impl 示例 | 安全级别 |
|-----------|---------------|---------|
| `bash` | `"git status --porcelain {path}"` | ✅ 占位符防注入，预定义命令白名单 |
| `http` | `{"method": "GET", "url": "https://api.github.com/{endpoint}"}` | ✅ 模板化，方法白名单 |
| `python` | `"fetch_data"` → 映射到预定义函数 | ⚠️ 仅白名单函数注册 |

命令白名单（bash）：`git`, `gh`, `glab`, `curl`, `wget`, `kubectl`, `docker`, `npm`, `pip`
HTTP 方法白名单：`GET`, `POST`, `PUT`, `DELETE`, `PATCH`

#### 安全性约束
| 约束类型 | 实现位置 | 说明 |
|---------|---------|------|
| 命令白名单 | `validators.py:_validate_bash_impl` | 仅允许预定义命令 |
| HTTP 方法白名单 | `validators.py:_validate_http_impl` | 仅白名单方法 |
| Python 函数注册 | `validators.py:_validate_python_impl` | 仅白名单函数 |
| 无任意代码执行 | `factory.py` | call_impl 是模板/映射，非代码 |
| 参数化防注入 | `call_handlers/bash.py` | format 替换，无 shell 注入 |
| 超时保护 | `call_handlers/bash.py` | subprocess timeout=30 |

#### 持久化机制
Agent 创建的工具保存到 `~/.clawcodex/agent-tools/{name}.json`，重启后通过 `build_default_registry(load_agent_tools=True)` 自动加载持久化工具到活动 Registry。

#### 与现有系统集成
| 现有组件 | 如何协作 |
|---------|---------|
| `build_tool()` | 作为工厂函数，CreateAgentTool 调用它 |
| `ToolRegistry` | 工具创建后调用 `registry.register(tool)` |
| `parse_agent_markdown` | 已有工具定义解析，可复用 schema 验证 |
| MCP 工具包装 | 参考 `tool_wrapper.py` 的声明式工具模式 |
| `EXTENSION_TOOLS` | `extensions/tool_system_ext/registration.py` 列表包含 `make_create_agent_tool()` |
| `build_default_registry()` | `src/tool_system/defaults.py`: `load_agent_tools=True` 参数 |
| `ToolContext.tool_registry` | `src/tool_system/context.py`: 运行时注册表字段 |

#### 实现文件
| 文件 | 位置 | 状态 |
|------|------|------|
| `create_agent_tool.py` | `clawcodex_ext/tool_system/tools/` | ✅ 已完成 |
| `spec.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `validators.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `factory.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `registry_ext.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `persistence.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `call_handlers/bash.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `call_handlers/http.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `call_handlers/python.py` | `clawcodex_ext/agent/tool_authoring/` | ✅ 已完成 |
| `registration.py` | `extensions/tool_system_ext/` | ✅ 已完成 |
| `defaults.py` | `src/tool_system/` | ✅ 已完成 |
| `context.py` | `src/tool_system/` | ✅ 已完成 |
| `runtime/context.py` | `clawcodex_ext/runtime/` | ✅ 已完成 |

### 二十三.2 F-16 Auto 模式 (TRANSCRIPT_CLASSIFIER)

**状态**: ✅ 已完成（F-16）
**目标**: 基于 LLM 的自动权限模式切换，减少交互疲劳

`auto_mode_classify()` 完整实现在 `src/permissions/check.py`：覆盖 Bash（命令安全分级）、Read（只读放行）、Write/Edit（安全路径白名单验证）、Agent（标记工具）、MCP（需显式审批）。配套 `DenialTracker` 支持拒绝计数与自动升级。所有内置工具均实现 `to_auto_classifier_input`。测试覆盖在 `tests/permissions/test_permission_classifier.py` 和 `tests/tool/test_tool_classifier_input.py`。

#### 工作原理
```
用户启动 Auto 模式 → Agent 执行工具调用时触发分类器
→ TRANSCRIPT_CLASSIFIER 分析: 工具类型、命令内容、执行上下文、历史行为模式
→ 分类决策: Auto-Allow 直接执行 / Auto-Deny 静默拒绝 / Fallback to Ask 回退
→ 记录分类结果用于后续判断
```

#### 与手动模式的区别
| 模式 | 触发方式 | 确认频率 | 适用场景 |
|------|---------|---------|---------|
| `default` | 手动确认每个敏感操作 | 高 | 学习/审查模式 |
| `acceptEdits` | 手动确认写操作 | 中 | 代码迭代 |
| `plan` | 仅读取，编辑前分析 | 低 | 探索代码库 |
| `auto` | LLM 自动判断 | 自动调节 | 长任务/减少疲劳 |
| `bypassPermissions` | 无限制 | 无 | 隔离环境 |

#### 循环切换逻辑
`Shift+Tab` 循环切换顺序：`default → acceptEdits → plan → bypassPermissions → default`
注意：`auto` 模式不出现在手动循环中，需要通过 `--permission-mode auto` 启动或由分类器自动触发。

#### 实施阶段
| 阶段 | 内容 | 优先级 | 状态 |
|------|------|--------|------|
| Phase A1 | TRANSCRIPT_CLASSIFIER 核心实现 | P2 | ✅ 已完成 |
| Phase A2 | `canCycleToAuto()` 判断逻辑 | P2 | ✅ 已完成 |
| Phase A3 | Auto Mode 工具执行前集成 | P2 | ✅ 已完成 |
| Phase A4 | 分类结果缓存机制 | P3 | 📋 待开始 |

### 二十三.3 F-52 Python SDK 方法注册为 Tool

**状态**: ✅ 已完成

`clawcodex_ext/agent/tool_authoring/validators.py` 的 `register_python_function()` + `list_python_functions()` 已实现；`factory.py` 的 `build_tool_from_spec()` 支持 python/http/bash 三种 call_type；`spec.py` 定义 `AgentToolSpec` 数据模型；`persistence.py` 支持本地持久化。CreateAgentTool（F-18）已集成本能力。

#### 背景
当前 SOP 转换器解析 Python 源码后，在 Agent 定义的 `tools:` 字段列出的方法名仅仅是字符串。当 sub-agent 被启动后，其可用工具列表只包含 clawcodex 内置工具，SOP 方法不在 `ToolRegistry` 中，Agent 只能退而通过 `Bash` subprocess 手动执行对应 Python 函数。

#### 设计目标
1. 新增 `register_tool_from_function(func, name, description, tool_registry)` 机制，将任意 Python 可调用对象包装为标准 `Tool` 对象并注册。
2. 生成的 Agent markdown 中的 `tools:` 列表在加载时自动触发注册，使方法名变为可调用的工具。
3. 保持 `src/*` 零改动——所有新增代码落入 `extensions/pos_converter/`。

#### 架构
```
SOP convert → AgentMarkdownWriter → .claude/agents/*.md (tools: [detect_modality, ...])
                         ↓ (新增)
               tool_registry.py → wrap SourceOperation → Tool
                         ↓
               ToolRegistry.register(name="detect_modality", fn=wrapped_callable)
                         ↓
               sub-agent 调用 detect_modality() → 执行 ADF Python 方法
```

| 组件 | 路径 | 说明 |
|------|------|------|
| `ToolWrapper` | `extensions/pos_converter/tool_registry.py` | 将 `SourceOperation` 包装为 `Tool` 对象 |
| `register_source_operations` | `extensions/pos_converter/tool_registry.py` | 批量注册某 agent 的所有操作 |
| `AgentBuilder` 增量 | `extensions/pos_converter/agent_builder.py` | `build()` 自动调用注册 |
| `load_agents_dir.py` 适配 | `extensions/pos_converter/agent_loader_hook.py` | 扫描时自动注册底层函数 |

#### 实现切片
1. `extensions/pos_converter/tool_registry.py` — `ToolWrapper` + `register_source_operations()`
2. `source_parser.py` 增量 — `SourceOperation` 增加 `is_async` / `is_generator` 元数据
3. `agent_builder.py` 增量 — `build()` 在持久化后自动注册 tool
4. `agent_loader_hook.py` — 加载 agent markdown 时注册 `source_path` 工具

#### 验收标准
1. `ToolWrapper(operation).to_tool().name == "detect_modality"`
2. `ToolWrapper(operation).to_tool().parameters` 正确映射 `ParamSpec`
3. `register_source_operations(agent_def, registry)` 后 registry 返回有效 `Tool`
4. 不传入 Python 源文件时优雅降级
5. 新增测试通过，现有测试继续通过

#### 风险与约束
- 动态 import 安全：需校验 `source_path` 属于项目目录
- 作用域泄漏：`register_source_operations()` 应按 `agent_type` 做作用域限定
- 依赖 F-18（CreateAgentTool）作为运行时替代注册路径

#### 依赖与协同
- **依赖**: F-50（SourceCodeParser），F-18（CreateAgentTool）
- **协同**: F-53（Tool→CLI 命令）以此为前置

### 二十三.4 F-89 @agent-name 多入口统一支持

**状态**: ✅ 已完成
**目标**: 实现 `@agent-name` 引用在 REPL、TUI、Headless 三种前端入口及子 Agent 创建上下文中的统一解析与分发，消除「`@agent-name` 在某个入口可用、在另一个入口不可用」的碎片化问题。

#### 背景与问题

此前 `@agent-name` 机制仅在前台 REPL 中被「加载 agents 目录 → 全局 agent 注册表 → AgentTool 显式创建 sub-agent」的路径支持。随着 F-34 Frontend 解耦和 F-18 CreateAgentTool 的落地，三种缺口暴露：

1. **入口不一致**：TUI 中 `@agent-name` 用法依赖 `agent_bridge.py` 的间接查找，与 REPL 的解析路径不同，导致某些 agent 定义在 REPL 可用但在 TUI 中无法解析。
2. **注册表不统一**：`AgentTool` 通过 `TOOL_REGISTRY` 查找 agent，而 `ClawcodexREPL` 通过 `session.available_agents` 查找——两套索引存在延迟同步。
3. **持久化 agent 可见性**：CreateAgentTool（F-18）创建的持久化 agent 被写入 `~/.clawcodex/agent-tools/`，但 `load_agents_dir()` 扫描路径不包含该目录。

#### 目标

1. **统一 agent 注册表**：所有 agent 来源（内置 agents 目录、用户 `.claude/agents/`、持久化 `~/.clawcodex/agent-tools/`）合并到单一全局 `AgentRegistry`。
2. **入口无关解析**：REPL、TUI、Headless 三种入口共用 `resolve_agent(name) -> AgentDefinition | None` 解析函数。
3. **子 Agent 创建对齐**：`AgentTool` 内部使用同一注册表，不做二次查找。
4. **启动时一致性校验**：启动时检测三入口解析结果是否一致，不一致时记录 warning。

#### 现状诊断

| 问题 | 此前位置 | 影响 |
|------|----------|------|
| TUI vs REPL `@agent` 解析路径分裂 | `agent_bridge.py:resolve_agent` vs `repl/core.py:handle_agent_prefix` | TUI 下部分 agent 不可用 |
| `AgentTool` 使用 `TOOL_REGISTRY` 而非 `AgentRegistry` | `tools/agent.py:382` | 持久化 agent 不可见 |
| `load_agents_dir()` 不扫描 `~/.clawcodex/agent-tools/` | `clawcodex_ext/cli/agents.py:45` | CreateAgentTool 创建的 agent 需重启才可见 |
| 三种入口各自维护 `loaded_agents` 缓存 | `tui/app.py` / `repl/core.py` / `headless.py` | 缓存不一致 |

#### 接入点设计

```
                     ┌──────────────────────────────┐
                     │      AgentRegistry (全局)      │
                     │  ┌──────────────────────────┐ │
                     │  │  .claude/agents/*.md      │ │
                     │  │  ~/.clawcodex/agent-tools/*│ │
                     │  │  built-in agents           │ │
                     │  └──────────────────────────┘ │
                     └──────┬──────────────┬─────────┘
                            │              │
              ┌─────────────▼──┐    ┌──────▼──────────┐
              │ Frontend Layer │    │   AgentTool     │
              │  (REPL/TUI/    │    │  (sub-agent 创建)│
              │   Headless)    │    │                  │
              │ resolve_agent()│    │ registry.get()   │
              └────────────────┘    └─────────────────┘
```

**AgentRegistry 统一来源**：

| 来源 | 路径 | 优先级 | 扫描时机 |
|------|------|--------|---------|
| 内置 agents | `clawcodex_ext/agents/` | 最低（fallback） | import 时 |
| 用户 agents | `.claude/agents/*.md` | 中 | 初始化时 |
| 持久化 agent-tools | `~/.clawcodex/agent-tools/*.json` | 高（用户显式创建） | 初始化时 + F-18 创建后热注册 |

**解析优先级**：用户 agent > 持久化 agent-tool > 内置 agent（同名冲突以高优先级为准）。

#### 实现切片

| Sub | 名称 | 内容 | 文件 |
|-----|------|------|------|
| A | 全局 AgentRegistry | 合并三来源的单一注册表，提供 `register()` / `get()` / `list()` / `resolve()` | `clawcodex_ext/agent/registry.py` |
| B | 统一 `resolve_agent()` | 入口无关的 agent 名称解析函数，替换 `agent_bridge.py` 和 `repl/core.py` 各自实现 | `clawcodex_ext/agent/resolver.py` |
| C | AgentTool 对接 | `AgentTool` 内部改为调用 `AgentRegistry.get()` 而非 `TOOL_REGISTRY` | `src/tool_system/tools/agent.py` |
| D | 持久化 agent 热注册 | CreateAgentTool 创建 agent 后立即调用 `AgentRegistry.register()`，无需重启 | `clawcodex_ext/agent/tool_authoring/persistence.py` |
| E | 启动一致性校验 | 三入口在初始化后调 `verify_agent_consistency()` | `clawcodex_ext/runtime/context.py` |
| F | 删除冗余缓存 | 移除 TUI/REPL/Headless 各自维护的 `loaded_agents` 实例属性 | 各入口文件 |

#### 验收标准

1. 在 `.claude/agents/` 中放置 `my-agent.md`，REPL、TUI、Headless 三种入口均可通过 `@my-agent` 解析到相同 `AgentDefinition`。
2. 通过 CreateAgentTool 创建持久化 agent，立即在同一会话中通过 `@agent-name` 可访问（无需重启）。
3. `AgentTool` 创建的 sub-agent 与前端 `@agent-name` 解析到同一个 agent 定义。
4. 同名 agent（内置 vs 用户）以用户 agent 优先级为准。
5. 启动日志无 agent 解析不一致 warning。
6. 删除 TUI/REPL 各自 `loaded_agents` 缓存后功能不受影响。
7. 全部 orchestrator 回归测试通过。

#### 风险与约束

| 风险 | 缓解 |
|------|------|
| 全局注册表成为耦合中心 | AgentRegistry 只做聚合不包含业务逻辑，所有来源的加载逻辑仍在各自模块 |
| 热注册导致并发问题 | AgentRegistry 内部使用 `threading.Lock`，新增来源时 register 为原子操作 |
| 持久化 agent-tools JSON 格式与 agent markdown 格式不兼容 | AgentTool 持久化写入时额外生成 `.md` 文件以便 `load_agents_dir()` 兼容扫描 |
| 启动一致性校验增加 50-200ms 延迟 | 只在 `verbose` 模式下执行完整校验；默认模式仅做抽样（首个 agent 名交叉解析） |

#### 依赖与协同

- **依赖**: F-18（CreateAgentTool 持久化机制）、F-34（Frontend 解耦，提供统一初始化入口）
- **协同**: F-16（Auto 模式，`auto_mode_classify` 需要 agent 注册表判断子 agent 权限）；F-50（SOP 转换器生成的 agent markdown 通过统一路径注册）
- **前置条件**: `AgentRegistry` 在 `RuntimeContext.build()` 中初始化完 todo 后调用 `register_all_sources()`

---

## 二十四、F-9 /goal 命令（目标管理）

**状态**: ✅ 已完成（2026-06-19 代码审计确认）
**实现位置**: `clawcodex_ext/goal/` 9 文件 2538 行
**目标**: 为长时间运行任务提供持久化目标、自动续跑、token 用量监控与恢复能力，避免用户需要反复输入"继续"。

> 参考上游 claude-code-best 的 `/goal` 实现（PR #1261，commit `3e3e1de81bf89857`）设计，在 clawcodex 中以 Python 方式落地。

### 功能说明

`/goal` 是一个 slash 命令，用于设置、查看或控制驱动多轮自动续跑的目标。支持以下用法：

| 命令 | 功能 |
|------|------|
| `/goal` 或 `/goal status` | 显示当前目标状态（目标、状态、已用时间、token、续跑轮数） |
| `/goal <objective>` | 设置新的目标；若当前已有未完结目标，弹出确认对话框 |
| `/goal clear` | 清除当前目标并持久化 tombstone，停止自动续跑 |
| `/goal pause` | 暂停自动续跑，保留目标状态 |
| `/goal resume` | 从 `paused` 恢复为 `active`，并重置 `blockedAttempts` |
| `/goal continue` | 在达到最大续跑轮数（`max_turns`）后重置计数器并继续 |
| `/goal complete` | 手动将目标标记为完成 |

约束：
- 目标文本最长 **4000 字符**；超长时应提示用户把详细说明写入文件，用简短 objective 引用。
- 设置新目标时，若已存在非 `complete` 的目标，必须弹出 `GoalReplaceConfirmDialog` 让用户确认替换，避免误覆盖进度。

### 状态机

目标在内存中以 `Map<sessionId, GoalState>` 维护，状态流转如下：

```
              setGoal()
                 │
                 ▼
        ┌─────────────────┐
        │     active      │◄─────────────────────────────┐
        └────────┬────────┘                              │
                 │ pauseGoal()                           │ resumeGoal()
                 ▼                                       │
        ┌─────────────────┐      continueGoalFromMaxTurns()│
        │     paused      │───────────────────────────────┘
        └─────────────────┘      (仅在 max_turns 时)

active ──► complete         completeGoal()
active ──► budget_limited   tokensUsed >= tokenBudget
active ──► usage_limited    markUsageLimited()（如限流/断网后）
active ──► blocked          同一 blocker 连续 3 次
active ──► max_turns        turnsExecuted >= MAX_GOAL_TURNS
```

状态定义：

| 状态 | 含义 | 是否终态 |
|------|------|----------|
| `active` | 正在自动续跑 | 否 |
| `paused` | 用户手动暂停 | 否 |
| `blocked` | 连续 3 次同一原因受阻 | 是 |
| `budget_limited` | token 预算耗尽 | 是 |
| `usage_limited` | 用量/限流导致无法继续 | 是 |
| `max_turns` | 达到最大续跑轮数上限 | 是（用户可 `continue` 解除） |
| `complete` | 目标已完成 | 是 |

### 核心机制

#### 自动续跑（`useGoalContinuation`）
在 REPL/主循环挂载一个 hook，当当前轮次完成（`isLoading` 从 true 变为 false）且满足以下条件时，自动向消息队列注入一条 continuation prompt：

1. `GOAL` feature flag 开启。
2. 存在 `active` 状态的目标。
3. 本轮正常结束，非用户中断（`wasAborted === false`）。
4. 没有交互式 local-jsx UI 占用中。
5. 不在 plan mode。
6. 消息队列中没有用户消息（用户输入优先）。
7. `turnsExecuted < MAX_GOAL_TURNS`（默认 **150**）。

注入参数：
- `mode: 'prompt'`, `priority: 'now'`, `isMeta: true`
- `origin: 'goal-continuation'` 或 `'goal-budget-limit'`
- `skipSlashCommands: true`

达到 `MAX_GOAL_TURNS` 后，目标进入 `max_turns` 状态，停止自动注入；用户可通过 `/goal continue` 重置计数器。

#### Token 用量追踪
每次模型调用产生 usage 后，在 `cost-tracker` 中汇总以下 token 类型并调用 `updateGoalTokens(delta)`：

- `input_tokens`
- `output_tokens`
- `cache_read_input_tokens`
- `cache_creation_input_tokens`

仅当目标状态为 `active` 时累计；跨越 `tokenBudget` 后状态自动变为 `budget_limited`，并注入一次 `budget_limit` 提示词要求模型停止实质性工作、给出进度摘要。

#### Blocked 审计
模型调用 `GoalTool` 报告 `blocked` 时，不立即改变状态。只有在 **连续 3 次同一原因**（大小写不敏感）受阻后，才将目标置为 `blocked`；不同原因会重置计数器。`pause` / `resume` 也会重置 `blockedAttempts` 和 `lastBlockReason`。

#### Completion 审计
提示词要求模型在标记完成前执行严格的 Completion Audit：

1. 从 objective 和引用文件中推导具体需求。
2. 保持原始 scope，不得围绕"已完成内容"重新定义成功。
3. 对每个显式需求提供权威证据（测试输出、文件内容、命令结果）。
4. 仅当测试/清单真正覆盖需求时才将其视为证据。
5. 不确定或间接证据视为"未完成"。
6. 审计必须**证明完成**，而非"未找到剩余工作"。

#### 计时
使用 `startTime`、`pausedAt`、`accumulatedActiveMs` 计算实际活跃时间，暂停期间不计入。UI 显示格式为 `Xm Ys` 或 `Ys`。

### 数据模型

```typescript
type GoalStatus =
  | 'active'
  | 'paused'
  | 'blocked'
  | 'budget_limited'
  | 'usage_limited'
  | 'max_turns'
  | 'complete'

type GoalState = {
  objective: string
  status: GoalStatus
  tokenBudget: number | null
  tokensUsed: number
  startTime: number
  pausedAt: number | null
  accumulatedActiveMs: number
  blockedAttempts: number
  lastBlockReason: string | null
  createdAt: number
  updatedAt: number
  turnsExecuted: number
}
```

常量：
- `MAX_GOAL_TURNS = 150`
- `BLOCKED_CONSECUTIVE_THRESHOLD = 3`
- `MAX_OBJECTIVE_CHARS = 4000`

### 提示词注入

所有 goal 相关 steering prompt 包裹在 XML tag 中，便于模型识别系统注入的指导：

| 类型 | Tag | 触发时机 |
|------|-----|----------|
| continuation | `<goal-steering type="continuation">` | 每轮 idle 后自动续跑 |
| budget_limit | `<goal-steering type="budget_limit">` | token 预算耗尽时一次性注入 |
| objective_updated | `<goal-steering type="objective_updated">` | 用户通过 `/goal <new>` 替换目标时 |
| active-goal context | `<active-goal ...>` | 紧凑的系统提示词上下文块 |

### 持久化与 `--resume` 恢复

目标状态通过 `goalStorage.ts` 桥接到 JSONL transcript，实现跨进程恢复。

**为什么需要 transcript 持久化**：`/goal` 的自动续跑由 REPL 主循环内存中的 `GoalState` 驱动。进程退出后 `--resume` 需要恢复目标状态，包括已消耗的 token、续跑轮数、活跃时间，避免用户需要重新设置目标。

**持久化写入规则**：
- 每次状态变更调用 `persistCurrentGoal()`
- 写入 `GoalMetadataEntry`：`{ type: 'goal', sessionId, state, timestamp }`
- `/goal clear` 写入 `GoalClearedEntry`，防止 `--resume` 复活旧目标

**读取与恢复规则**：
- `ResumeConversation` / session restore 路径调用 `hydrateGoalFromTranscript()`
- 按时间顺序扫描，最新 `goal` entry 为权威状态
- 最新 entry 为 `goal-cleared` 则认为当前无目标

### 实现文件

| 文件 | 上游位置 | 职责 |
|------|----------|------|
| Goal 命令 | `src/commands/goal/goal.tsx` | `/goal` 子命令解析、UI 回调、状态转换 |
| 命令注册 | `src/commands/goal/index.ts` | 注册为 `local-jsx` slash command |
| 替换确认对话框 | `src/commands/goal/GoalReplaceConfirmDialog.tsx` | 目标覆盖二次确认 |
| 状态机 | `src/services/goal/goalState.ts` | 纯内存状态、流转、计时 |
| 持久化桥接 | `src/services/goal/goalStorage.ts` | 连接状态机与 JSONL transcript |
| 审计常量 | `src/services/goal/goalAudit.ts` | Completion/Blocked 审计规则、终态判断 |
| 提示词模板 | `src/services/goal/prompts.ts` | continuation / budget_limit / objective_updated / context block |
| Goal 工具 | `packages/builtin-tools/src/tools/GoalTool/GoalTool.ts` | 模型查询/更新目标状态 |
| 自动续跑 Hook | `src/hooks/useGoalContinuation.ts` | REPL 中驱动自动续跑 |
| Token 追踪 | `src/cost-tracker.ts` | 将 usage 同步到 goal tokens |
| Transcript 存储 | `src/utils/sessionStorage.ts` | 读写 `goal` / `goal-cleared` JSONL entries |
| 状态栏 | `src/components/StatusLine.tsx` | `GoalPill` 展示当前目标摘要 |
| 类型定义 | `src/types/logs.ts` | GoalState / GoalStatus / GoalMetadataEntry |
| Feature flag | `scripts/defines.ts` | `GOAL` 特性开关 |

### UI 展示

状态栏 `GoalPill` 在 `feature('GOAL')` 开启且存在目标时显示：

```
[Active · 实现 dashboard · 12.3k/200k]
```

颜色规则：`active`（绿色）、`paused` / `budget_limited` / `usage_limited`（黄色）、`blocked`（红色）、`complete`（青色）、`max_turns`（默认色）。目标文本超过 30 字符时截断显示。

### 测试覆盖

| 测试 | 位置 | 覆盖点 |
|------|------|--------|
| 状态机单元测试 | `src/services/goal/__tests__/goalState.test.ts` | set/pause/resume/complete/clear、token 累计、budget_limited、blocked 3 次、max_turns、计时 |
| 集成测试 | `tests/integration/goal-lifecycle.test.ts` | 完整生命周期、提示词内容、审计规则一致性、终态判断 |

---

## 二十五、F-11 sessionStorage 容量限制

**状态**: ✅ 已完成
**目标**: 防止长时间运行的 daemon/swarm 会话导致内存泄漏

### 功能说明

为 `existingSessionFiles` Map 设置容量上限，防止无限增长：

```python
MAX_CACHED_SESSION_FILES = 200

def add_session_file(sessionId: UUID, filePath: str):
    if len(existingSessionFiles) >= MAX_CACHED_SESSION_FILES:
        oldest_key = next(iter(existingSessionFiles))
        del existingSessionFiles[oldest_key]
    existingSessionFiles[sessionId] = filePath
```

### 问题场景

- daemon/swarm 模式下长时间运行
- sessionId 频繁创建销毁
- Map 无限增长导致 OOM

### 实现文件

| 文件 | 位置 | 状态 |
|------|------|------|
| sessionStorage | `utils/sessionStorage.ts` → `utils/session_storage.py` | 已完成 |

---

## 二十六、F-99 Ctrl+C/B 即时中断响应优化

**状态**: ✅ 已完成（2026-06-17） | **优先级**: P0
**目标**: 解决 LLM 流式响应 + 工具执行阶段按 Ctrl+C/Ctrl+B 需要 10~30s 才生效的 UX 问题，目标 < 500ms。

### 问题根因

```
你按 Ctrl+C
  ↓  <1ms
LiveStatus keybinding → engine.interrupt() → abort_controller.abort()
  ↓  <1ms
StreamAbortGuard listener → stream.response.close()
  ↓  ⚠️ httpx 下 close() 是 advisory（不打断阻塞读）
SDK 继续从 socket 读取 → 模型继续生成 → 10~30s 后自然结束
```

三瓶颈串联：

| 瓶颈 | 位置 | 延迟贡献 | 原因 |
|------|------|---------|------|
| 1. Provider `response.close()` 无效 | `src/providers/_stream_abort.py` | 10~30s（主要） | LiteLLM/httpx 下 advisory close |
| 2. `asyncio.gather` 等待所有工具 | `src/query/query.py` L1602 | 0.1~5s（次要） | 等最慢工具完成 |
| 3. 无传输层终止 | `src/providers/_stream_abort.py` | 无实际中止能力 | TCP 连接保持打开 |

### 方案架构

```
F-99 三层方案
├── 方案1: httpx read_timeout（P0）         ← 延迟 bound 在 5s
│   └── AnthropicProvider._ensure_client() 设置 httpx.Client(read_timeout=5.0)
├── 方案2: 传输连接关闭（P1）                ← 延迟 bound 在 <100ms
│   └── _close_response_safely() 增加 transport.close()
└── 方案3: 工具阶段可取消（P2）              ← 工具阶段即时响应
    └── _run_tools_partitioned() 用 asyncio.wait(FIRST_COMPLETED) 替代 gather
```

### 改造点清单

| 文件 | 改动 | 方案 |
|------|------|------|
| `src/providers/anthropic_provider.py` | `_ensure_client()` 传入自定义 `httpx.Client(timeout=...)` | 方案1 |
| `src/providers/_stream_abort.py` | `_close_response_safely()` 增加 `response._transport.close()` | 方案2 |
| `src/query/query.py` | `_run_tools_partitioned()` 改用 `asyncio.wait(FIRST_COMPLETED)` + `task.cancel()` | 方案3 |
| `src/query/query.py` | `_dispatch_single_tool()` 传递 abort_signal 给工具执行 | 方案3 |

### 风险与约束

| 风险 | 缓解措施 |
|------|---------|
| httpx `_transport` 内部属性依赖 | 增加 `getattr` fallback + 注释标注非公开 API |
| `asyncio.wait(FIRST_COMPLETED)` 增加复杂度 | 封装 helper 函数 |
| read_timeout=5s 在正常慢 chunk 时误触发 | 保留 `StreamWatchdog` 90s 兜底 |
| `transport.close()` 在 Windows 上不可用 | `sys.platform == "win32"` 时跳过 |

### 设计决定

1. **方案1+2+3 组合实施**，一次性覆盖所有瓶颈
2. 方案2 用 `getattr` 而非 `hasattr`：使用 try/except 防御
3. 不做 provider 无关的泛化：方案1 只改 `AnthropicProvider`
4. `asyncio.wait(FIRST_COMPLETED)` 只影响 abort 路径

---

## 二十七、F-55 SOP 转换器分组策略增强

**状态**: ✅ 已实现 | **优先级**: P1
**实现位置**: `extensions/pos_converter/skill_grouper.py`
**核心文件**: `skill_grouper.py`, `source_parser.py`, `agent_md_writer.py`, `clawcodex_ext/cli/pos_cmd/commands.py`

F-55 是 F-50 (SOP 转换器源码固化) 的增强子特性，解决 **"模块多时 Agent 过多"** 的核心问题。

### 背景与问题

SOP 转换器的默认行为是将 `SourceCodeParser` 解析出的每个组件 (`SourceComponent`) 各自生成一个独立 Agent，然后额外生成一个总览 Agent。N=50 模块时生成 **51 个 Agent 文件**。

过多 Agent 带来：
1. **用户心智负担**：/agent-list 出现几十个名字
2. **启动加载成本**：运行时注册表需发现所有 Agent
3. **路由低效**：总览 Agent 的指令集随 N 线性增长

### 四种分组策略

| 策略 | 分组依据 | Agent 数量（50 模块） | 适用场景 |
|------|---------|:-------------------:|---------|
| `COMPONENT_GROUP` | 每个 SourceComponent 一个 Skill/Agent | 50 | 模块高度正交 |
| `KEYWORD_MATCH` | 按预定义 MappingRule 模式匹配 | 3-8 | 命名约定良好 |
| `IO_RELATION` | 按参数类型签名聚类 | 5-15 | 内聚度低但参数体系清晰 |
| `LLM_SEMANTIC` | LLM 语义聚类 | 3-8 | 无固定命名约定 |

**关键约束**：无论选择哪种策略，总览 Agent 始终生成，始终是用户的唯一入口。

### CLI 接口

```bash
clawcodex pos convert ./sdk/ --out ./output                              # 默认 COMPONENT_GROUP
clawcodex pos convert ./sdk/ --out ./output --strategy keyword           # 关键字规则合并
clawcodex pos convert ./sdk/ --out ./output --strategy io                # IO 参数类型合并
clawcodex pos convert ./sdk/ --out ./output --strategy llm               # LLM 语义分组
clawcodex pos convert ./sdk/ --strategy io --preview                     # 预览分组
```

### 实现架构

```
CLI (commands.py)
    │
    ▼
group_source_components(components, strategy=GroupStrategy.IO_RELATION)
    │
    ├── SkillGrouper._component_group()     每个组件 → 一个 SkillSpec
    ├── SkillGrouper._static_group()        MappingRule 关键字匹配
    ├── SkillGrouper._io_relation_group()   参数类型聚类
    └── SkillGrouper._group_with_llm()      LLM 语义分组 (placeholder)
    │
    ▼
AgentMarkdownWriter.write_agent() × N + write_overview_agent() × 1
```

### 设计决定

| # | 决定 | 理由 |
|---|------|------|
| 1 | COMPONENT_GROUP 为默认策略 | 向后兼容 |
| 2 | 总览 Agent 始终生成 | 用户只需面对一个入口 |
| 3 | IO_RELATION 分组名加上类型签名 | 让人看出分组依据 |
| 4 | LLM_SEMANTIC 标注 TODO 暂不实现 | 依赖 F-52 Tool 注册能力 |
| 5 | `--preview` 预览模式不属于核心能力 | 可用 `--dry-run` (未来特性) 替代 |

### 依赖与协同

- **依赖**：F-50（SourceCodeParser + AgentMarkdownWriter 是前置基础）
- **协同**：F-52（Tool 注册 → 策略重要度柔性可调）、总览 Agent 默认加载机制
- **不依赖**：F-37/F-38/F-39（独立功能）

---

## 二十八、F-49 Issue 会话统一存储与实时介入协议

**状态**: ✅ 已完成（Phase 0.4 + Phase 5 P5-A~G 已落地）
**优先级**: P1
**依赖**: F-21（后台运行 + 恢复同步）、F-38（验证与报告闭环）、F-40（ProgressReporter Sink 协议重构）

### 问题现状：两条互不兼容的事件路径

当前系统存在**两套并行但不可互操作的事件记录系统**：

| 维度 | 路径 A：正常 REPL 会话（`SessionStorage`） | 路径 B：Headless Issue Agent（旧格式 `_write_event_log` → 已统一） |
|------|------|------|
| 存储位置 | `~/.clawcodex/sessions/{sid}/` | 已统一为 `~/.clawcodex/sessions/{run_id}/`（与路径 A 相同） |
| 格式 | `transcript.jsonl` — 每行一个 `Message` dict (`role`, `content` blocks, `tool_use_id`) | 已统一，同上格式 |
| 可读性 | `session_resume.py` → `list[Message]` | 已统一 |
| 配套设施 | `TailFollower`、`Session.load/resume`、`SessionStorage.read_transcript()` | 已统一 |
| 可恢复性 | ✅ 可重建 LLM context | ✅ 已统一，可重建 LLM context |
| 控制通道 | `asyncio.Event` + Unix socket（F-21） | 文件轮询 `{.orchestrator_control/{cmd}.control}`（待 F-54 Phase 1 统一） |

**改造前**：Headless agent 写 `.event_logs/{id}.ndjson` 扁平 NDJSON；REPL 写 `transcript.jsonl`。两路不可互通。Observe/tail/takeover/resume 每个功能都需要在两条路径上重复实现。

**F-49 Phase 0 已完成**：统一为 `~/.clawcodex/sessions/{run_id}/transcript.jsonl`，`.event_logs/` 已完全移除。

### 目标

统一 headless agent 和 REPL 会话的存储格式，在此之上建立双向实时介入协议（Unix socket），使 operator 可以通过 `attach` CLI 观察、中断、接管、恢复 issue agent 的运行。

| 场景 | F-49 Phase 0 后状态 | 目标状态（Phase 1+） |
|------|-------------------|---------|
| 实时观察 | `attach` CLI 读 `transcript.jsonl`（F-49） | `attach` CLI 通过 socket 流式接收 `TextDelta` / `ToolCallEvent` / `ToolResultEvent` / `PhaseComplete` |
| Ctrl+C 中断 | ❌ 不支持（仅 `stop` 控制文件） | socket 发送 `pause` → agent 挂起等待 operator 输入 |
| 人工接管 | ❌ 不支持 | `pause` 后 operator 键入 hint，agent 恢复后消费 |
| `/resume` 恢复自动值守 | ❌ 不支持 | socket 发送 `resume`（可选附带 prompt）→ agent 继续 loop |
| Session 恢复崩溃 | ✅ `SessionStorage` → `session_resume.resume_session()`（F-49 已完成） | 已达目标 |
| detach | ❌ 不支持 | socket `detach` → agent 继续运行，operator 断开 |

### 核心设计

```
AgentRunner (headless)
  │
  ├── prompt → QueryRunner → LLM → events
  │                                  │
  │                                  ├── SessionStorage.write_raw(msg_dict)
  │                                  │    └── ~/.clawcodex/sessions/{run_id}/transcript.jsonl
  │                                  │         （同一格式，非 .event_logs/）
  │                                  │
  │                                  ├── event_bus (asyncio.Queue)
  │                                  │    └── ControlSocket → Unix socket
  │                                  │         └── attach CLI (TUI)
  │                                  │
  │                                  └── ProgressSink (F-40)
  │
  └── session.pause_resume_event (asyncio.Event)
       └── ControlSocket → "pause" / "resume" / "inject"
```

### 改造点清单

**Phase 0 — 统一事件存储** ✅ 已完成

| 文件 | 改动 | 状态 |
|------|------|------|
| `extensions/orchestrator/agent_runner.py` | `AgentSession` 增加 `session_storage: SessionStorage`；`run()` 中 `init_metadata(model, cwd, title)`；替换 `_write_event_log()` → `session_storage.write_raw(msg_dict)` + `flush()` | ✅ 完成 |
| `extensions/orchestrator/agent_runner.py` | 删除 `_write_event_log()` 方法；删除 `.event_logs/` 目录创建逻辑 | ✅ 完成 |
| `extensions/orchestrator/cli/issue.py` | `_run_tail` 改为读 `transcript.jsonl` | ✅ 完成 |
| `src/services/session_storage.py` | 无改动（复用现有 `SessionStorage`） | ✅ 无需改动 |
| (新增) `extensions/orchestrator/debug_log.py` | `append_debug_event()` — 写入 `.orchestrator_control/runs/{run_id}/debug.ndjson` | ✅ 完成 |

统一后的效果：headless agent 的每个 tool_use / tool_result / text_delta **都以 Message dict 格式写入 session JSONL**，`TailFollower` 可以直接 follow，`session_resume` 可以直接重建 LLM context。

**Phase 0.1 — Message 转录映射规则（F-49.0 核心契约）**

Phase 0 只说"用 Message dict 格式写"，但未定义 `QueryEvent` 流 → `Message` dict 的具体映射规则。headless agent 的 `QueryRunner.stream()` 产出的是一系列扁平事件（`TextDelta` / `ToolCallEvent` / `ToolResultEvent`），它们必须被正确分组为 `role="assistant"` 和 `role="user"` 的 Message 才能写入 `SessionStorage`。

**核心原则**：一次 LLM 响应（一个 agent turn）对应一个 `assistant` Message 和一个 `user` Message（含 tool results），遵循 `session_storage` 的 `write_message(Message)` 契约。

```
LLM 响应开始
  ├── TextDelta(n) × N
  ├── ToolCallEvent(tool_use_id=T1, tool_name="Read", params={...})
  ├── TextDelta(m) × N
  ├── ToolCallEvent(tool_use_id=T2, tool_name="Edit", params={...})
  │
  └── TurnComplete
        │
        ├── 组装成 AssistantMessage:
        │     role="assistant"
        │     content = [
        │       TextBlock(text=concat(TextDelta...)),
        │       ToolUseBlock(id=T1, name="Read", input={...}),
        │       ToolUseBlock(id=T2, name="Edit", input={...}),
        │     ]
        │     ↓ session_storage.write(msg_dict)
        │
        ├── 等待 ToolResultEvent(s) 返回
        │     ToolResultEvent(tool_use_id=T1, result={...})
        │     ToolResultEvent(tool_use_id=T2, result={...})
        │
        └── 组装成 UserMessage:
              role="user"
              content = [
                ToolResultBlock(tool_use_id=T1, content="..."),
                ToolResultBlock(tool_use_id=T2, content="..."),
              ]
              ↓ session_storage.write(msg_dict)
```

**具体映射表**：

| 事件序列 | Message 类型 | `content` 结构 |
|----------|-------------|----------------|
| 首个 turn 的 user prompt | `UserMessage` | `[TextBlock(text=prompt)]` — 在 `run()` 开始处写入 |
| `TextDelta` × N + `ToolCallEvent` × 0 | `AssistantMessage` | `[TextBlock(text=concat(all deltas))]` |
| `TextDelta` × N + `ToolCallEvent` × M | `AssistantMessage` | `[TextBlock(text=text_before_tool), ToolUseBlock(id=...), ...]` — 文本和 tool_use **交替排列**，按事件流顺序 |
| `ToolResultEvent(tool_use_id, result)` × M | `UserMessage` | `[ToolResultBlock(tool_use_id="T1", content=json.dumps(result)), ...]` |
| 后续 turn 的 continuation prompt | `UserMessage` | `[TextBlock(text=continuation_prompt)]` — 每轮 turn 开始处写入 |
| `SessionComplete` | 不写 Message | 调用 `session_storage.flush()` 确保缓冲区落盘 |

**关键实现约束**：

1. **ToolResultEvent 可能乱序到达** — 必须按 `tool_use_id` 配对等待，不一定与 ToolCallEvent 顺序一致。使用 `dict[tool_use_id, ToolResultEvent]` 累积，直到所有已发出的 tool_use 都有 result 才组装 UserMessage。
2. **TurnComplete 触发消息组装** — 不应在收到 ToolCallEvent 时就写 assistant message 的一半，而应在 TurnComplete 时才知道"这一轮 LLM 已输出结束"，此时组装完整的 assistant message 写入。
3. **ToolResult 可能被 approval policy 拒绝** — 被拒绝的 tool call，其 `ToolResultEvent` 的 `is_error=True`。拒绝结果也要写入 `ToolResultBlock(content={"error": "Permission denied"})`，保证转录的完整性。
4. **TextDelta 流中断情况** — 如果 LLM 在输出文本后响应突然中止（如连接断开），尚未收到 `TurnComplete`，当前累积的 `TextDelta` 内容不应丢失。应在下一个 turn 开始前或 `SessionComplete` 时强制 flush 一个残缺的 `AssistantMessage`。
5. **大内容替换** — `SessionStorage.write_message()` 内部有 `_replace_large_content()` 自动将大 tool result 替换为文件引用，无需 AgentRunner 层额外处理。

**与现有审计旁路（F-45 `events.ndjson`）的关系**：

```
AgentRunner.run() 事件循环
  │
  ├── ToolCallEvent: 写入 events.ndjson（F-45，8 字段，扁平审计）
  │                  └── 不写 Message（等到 TurnComplete 再组）
  │
  ├── ToolResultEvent: 写入 events.ndjson（可选扩展）
  │                    └── 暂存到 tool_result_buf[tool_use_id] ← 新增
  │
  ├── TurnComplete:
  │     ├── 组 AssistantMessage → SessionStorage.write_raw(msg_dict)
  │     ├── 组 UserMessage → SessionStorage.write_raw(msg_dict)  ← 依赖 tool_result_buf 已就绪
  │     └── 清空 tool_result_buf
  │
  └── SessionComplete:
        └── SessionStorage.flush()
```
| `F-38 git_sync` | Phase 0 无影响 — git_sync 操作 workspace git，不改 session 存储 |
| `F-39 retry` | Phase 2 扩展 — retry 可携带 `--attach` 参数在新 run 上立即 attach |

**Phase 0.2 — CLI 介入：会话恢复（--resume）+ 实时观察 + 问题追溯**

统一格式后的核心收益：**`clawcodex --resume <run_id>` 可直接恢复 orchestrator headless agent run 的完整对话，进入交互式 REPL**，operator 可继续对话，新内容追加到同一 transcript。

| 场景 | 机制 | 代码来源 |
|------|------|---------|
| **完整会话恢复（核心）** | `clawcodex --resume <run_id>` → `Session.resume(run_id)` 读取 transcript + metadata，重建 Conversation，进入交互式 REPL | `src.agent.session.Session.resume()` — 完全复用，0 改动 |
| **TUI 实时增量观察** | `clawcodex --tui --resume <run_id>` → TailFollower 从 transcript 末尾输出增量 | `src.services.tail_follower.TailFollower` — 完全复用 |
| **接管 agent run** | operator 在 REPL 中直接输入指令替代 headless agent 的下一 turn；退出可选 detach / finish / re-orchestrate | `Session.resume()` + 前台 REPL |
| **崩溃恢复** | orchestrator 检测到 agent 进程退出后，用 `Session.resume()` 重建 context，在新的 `AgentRunner` 中继续 | `Session.resume()` → `session_resume.resume_session()` |
| **只读追溯** | `issue transcript --run <run_id>` 文本输出对话历史，适合管道处理 | 新增 `_run_transcript` 子命令 |

`--resume` 三种模式：

```
clawcodex --resume <run_id>               → 完整会话恢复，进入交互式 REPL
clawcodex --tui --resume <run_id>         → TUI 模式，TailFollower 增量显示 + 可输入
clawcodex --resume <run_id> --readonly    → 只读查看历史，不进入交互模式
```

并发安全：agent 已结束时正常恢复可写；agent 正在运行时 `--resume` 获得只读历史快照不干扰运行中 agent；需写入需通过 socket 先 pause。

**Phase 0.3 — 大内容文件引用**

复用 `SessionStorage._replace_large_content()` 内置行为，自动将大 tool result 替换为文件引用（存储于 `~/.clawcodex/sessions/<run_id>/content/`），AgentRunner 无需感知。

验收标准：headless agent 的每轮 tool_use / tool_result / text_delta 以 Message dict 格式写入 session JSONL，`TailFollower` 可直接 follow，`session_resume` 可直接重建 LLM context。整个 Phase 0 不修改 `src/services/session_storage.py` 一行代码。

---

### 全场景会话恢复统一闭包（F-49 Phase 0.4 — Session Resume 统一）

**状态**: ✅ 已完成
**优先级**: P1
**依赖**: F-49 Phase 0 ~ 0.3（统一事件存储），F-21（后台运行 + 恢复同步）

#### 问题现状：SessionStorage 回退路径的消息缺失

F-49 Phase 0 统一了事件存储格式（全部使用 `~/.clawcodex/sessions/{run_id}/transcript.jsonl`），但在 `--resume` 恢复链上仍然存在一个关键缺口：

```
Session.resume(sid)                          # src/agent/session.py:135
  → Session.load(sid)                        # 尝试 ~/.clawcodex/sessions/{sid}.json
    ├── 找到 → 返回完整 Session（含 Conversation.messages）✅
    └── 未找到 → load_from_session_storage()  # 回退到 SessionStorage 目录格式
         → 仅恢复 metadata（session_id, model, start/end time）
         → conversation=Conversation()        # ← 空的！
```

| 消费方 | resume 后的处理 | 行为 |
|--------|---------------|------|
| **REPL** `repl/app.py:136` | `_sync_conversation_from_transcript()` 从 JSONL 重新填充 | ✅ 全量恢复 |
| **TUI** `tui/app.py:229` | 仅 `if self.session.conversation.messages: self._replay_history()` | ❌ 格式 B 恢复后消息为空，不会 replay 历史 |
| **CLI** `dispatch.py` | 无显式 transcript 同步 | ❌ 格式 B 恢复后 conversation 空 |
| **Cron bg_runner** | 仅写 JSONL，不写 .json 快照 | ⚠️ 只能走 SessionStorage 回退 |
| **Orchestrator** | 仅写 JSONL，不写 .json 快照 | ⚠️ 只能走 SessionStorage 回退 |

核心矛盾：**CLI/TUI 的 `--resume` 对于 Cron/Orchestrator 写入的会话只能恢复出一个空壳**，必须依赖每个消费者自行补丁。

#### 目标

彻底消除上述差距，使所有场景的 `--resume` 行为一致且可递归恢复：

```
所有写入方（CLI / REPL / TUI / Cron / Orchestrator）
       │ 统一写 SessionStorage JSONL
       ▼
~/.clawcodex/sessions/<sid>/transcript.jsonl
       │
       ▼ --resume 统一消费
Session.resume(sid) → 返回的 Session.conversation.messages 非空
       │
       ▼ 递归 resume
再次 Session.resume(sid) → 与退出前状态一致
```

#### 设计

**A. `Session.resume()` 自愈修复（核心，一处修复全局生效）**

在 `Session.resume()` 的 SessionStorage 回退路径末尾，增加从 JSONL 加载消息的逻辑：

```python
# load_from_session_storage 之后，conversation 为空时：
if not loaded.conversation.messages:
    try:
        from src.services.session_storage import SessionStorage
        storage = SessionStorage(session_id=session_id)
        entries = storage.read_transcript()
        from src.types.messages import message_from_dict
        messages = [message_from_dict(e) for e in entries]
        loaded.conversation.messages = messages
    except Exception:
        pass  # 不阻断 resume
```

效果：**一处修复，CLI/REPL/TUI/Cron/Orchestrator 全场景受益**。REPL 的 `_sync_conversation_from_transcript()` 将成为冗余（但保留作为防御性 double-check）。

**B. `Session.save()` 双写一致性保障**

当前 `Session.save()` 同时写 `.json` 快照 + JSONL。但对于从 SessionStorage 回退路径恢复的会话（conversation 通过 A 补全后），首次 `save()` 把 `.json` 快照写出来，后续 `--resume` 就走快路径 `Session.load()` 了。

**C. 新增：Cron `background_runner.py` 运行结束写 `.json` 快照**

```python
# 在 _run_agent_headless() 末尾，调用 session.save() 写 .json 快照
session.save()  # 让 agent 结束后也能通过快路径 --resume
```

**D. 新增：Orchestrator `agent_runner.py` 运行结束写 `.json` 快照**

```python
# 在 AgentRunner.run() 末尾，调用 session.save() 写 .json 快照
session.save()
```

#### 改造点清单

**Phase 0.4.1 — 核心修复：`Session.resume()` 加载 JSONL 消息**（0.5 天）

| 文件 | 改动 |
|------|------|
| `src/agent/session.py` | `Session.resume()` 的 SessionStorage 回退分支末尾，增加从 `SessionStorage.read_transcript()` 加载 messages 到 `conversation.messages` 的逻辑 |
| `(无)` | 不修改 `load_from_session_storage()` / `session_persist.py` — 保持原有契约 |

验收：`Session.resume(run_id)` for orchestrator-run 返回的 `session.conversation.messages` 非空。

**Phase 0.4.2 — 统一 clean-up：移除冗余的 caller 侧 transcript 同步**（0.5 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/repl/core.py` | 保留 `_sync_conversation_from_transcript()` 作为防御性 double-check；在方法开头检查若 `session.conversation.messages` 已非空则直接 return |
| `clawcodex_ext/repl/app.py` | 无改动（仍保留 `_sync_conversation_from_transcript` 调用） |

验收：REPL resume 后 conversation 正常，`_sync_conversation` 成为 quick-return no-op。

**Phase 0.4.3 — TUI resume 路径修复**（0.5 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/tui/entrypoint.py` | `Session.resume()` 调用后，增加 `resume_session_with_tail()` 调用中的 transcript 消息加载（或依赖 Phase 0.4.1 核心修复已生效） |
| `clawcodex_ext/tui/app.py` | `on_mount()` 中的 `if self.session.conversation.messages:` 改为无条件调用 `_replay_history()`（若 messages 为空则不渲染）或由核心修复保证非空 |

验收：`clawcodex --tui --resume <run_id>` 显示 orchestrator run 的完整历史。

**Phase 0.4.4 — CLI dispatch resume 路径修复**（0.5 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/cli/dispatch.py` | `Session.resume()` 调用后，确保 `conversation.messages` 非空（若 Phase 0.4.1 已修复则自动生效） |

验收：`clawcodex --resume <run_id>` 进入 REPL 后显示历史消息。

**Phase 0.4.5 — Cron/Orchestrator 运行结束写 .json 快照**（1 天）

| 文件 | 改动 |
|------|------|
| `clawcodex_ext/agent/background_runner.py` | `_run_agent_headless()` 末尾（finally 块中）调用 `session.save()` 确保 `.json` 快照写入 |
| `extensions/orchestrator/agent_runner.py` | `run()` 末尾（SessionComplete / 异常退出时）调用 `session.save()` 确保 `.json` 快照写入 |

验收：Cron/Orchestrator 执行后，`~/.clawcodex/sessions/<run_id>.json` 存在，可通过快路径 `Session.load()` 恢复。

**Phase 0.4.6 — 递归 resume 一致性验收**（0.5 天）

| 文件 | 改动 |
|------|------|
| `tests/test_session_resume_unified.py` | 新增测试：orchestrator 场景的 JSONL → `Session.resume()` → `Session.save()` → 再次 `Session.resume()` → 消息与第一次一致 |

验收：三轮递归 resume 消息内容不变。

#### 消息流向全图

```
                    ┌─────────────────────────┐
                    │  CLI / REPL / TUI 交互    │
                    │  Session.save()           │
                    │    → .json (快照)         │
                    │    → JSONL (追加)         │
                    └──────────┬──────────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Cron bg_runner       │
                    │  storage.write_msg()  │
                    │    → JSONL (追加)     │
                    │  结束 → session.save()│
                    │    → .json (快照)     │
                    └──────────┬──────────────┘
                               │
                    ┌──────────┴──────────┐
                    │  Orchestrator        │
                    │  _flush_transcript() │
                    │    → JSONL (追加)    │
                    │  结束 → session.save()│
                    │    → .json (快照)    │
                    └──────────┴──────────────┘
                                        │
                                        ▼
~/.clawcodex/sessions/<sid>/
  ├── <sid>.json            # 全量快照（所有写入方最终都会产生）
  └── <sid>/
        ├── transcript.jsonl  # 追加日志（统一格式）
        └── metadata.json

                                        │
                                        ▼
                              Session.resume(<sid>)
                                ├── Session.load() → .json 快照 ✅
                                └── fallback → JSONL 加载消息 ✅ (Phase 0.4.1)
```

#### 验收标准

| # | 验收场景 | 预期行为 |
|---|---------|---------|
| 1 | CLI 交互 → exit → --resume | 完整 Conversation，消息不变 |
| 2 | REPL 交互 → exit → --resume | 完整 Conversation，消息不变 |
| 3 | TUI 交互 → exit → --resume (TUI 或 REPL) | 完整 Conversation，历史可见 |
| 4 | Cron bg_runner 运行 → --resume | 完整 Conversation，含所有 tool_use / tool_result |
| 5 | Orchestrator agent_runner 运行 → --resume | 完整 Conversation，含所有 tool_use / tool_result |
| 6 | Cron/Orch → --resume → exit → 再次 --resume | 递归一致 |
| 7 | 跨场景混合写入（eg: Orchestrator 写 → --resume REPL 追加 → exit → --resume TUI） | 所有消息（原始 + 追加）完整 |
| 8 | `.json` 快照不存在时，`--resume` 也能恢复 | 依赖 SessionStorage JSONL fallback |

#### 风险与约束

| 风险 | 缓解措施 |
|------|---------|
| `Session.resume()` 的 SessionStorage fallback 路径加载 JSONL 后，`conversation.messages` 可能包含大量消息，超出 `max_history`（默认 2000） | 加载后不截断 — `max_history` 仅在新 `add_message()` 时生效；或与 `Conversation.from_dict()` 保持行为一致 |
| JSONL 中的 malformed 行导致部分消息缺失 | 与 `session_resume.resume_session()` 行为一致：跳过 malformed 行并记录 warning |
| `_sync_conversation_from_transcript()` 在 REPL 中变为冗余但仍被调用 | 加 early-return 检查：`if self.session.conversation.messages: return`，O(1) 开销 |
| `session.save()` 从 Cron/Orchestrator 调用时可能缺失 provider / model 信息 | 在 `AgentRunner.run()` 中 `session.provider` 和 `session.model` 已设置；`load_from_session_storage` 返回的 model 字段也可用 |

#### 已拟定的设计决定

1. **核心修复在 `Session.resume()` 完成**（一处修复，全局受益），而非在每个消费者处加补丁。
2. **`.json` 快照在 Cron/Orchestrator 结束时写入**，保证下次 resume 走快路径，同时也作为备份。
3. **保留 REPL 的 `_sync_conversation_from_transcript()`**，改为防御性 double-check（early return 模式），不破坏现有行为。
4. **不修改 `SessionStorage`** — 所有改动在消费侧（`Session.resume()`、`background_runner.py`、`agent_runner.py`）。
5. **POS Converter 不涉及** — 它是编译期代码生成工具，不产生运行时会话日志。

#### 依赖与协同

| 依赖 | 类型 | 说明 |
|------|------|------|
| F-49 Phase 0 ~ 0.3 | 硬依赖 | 格式统一是基础 |
| F-21 bg + `--resume` | 行为参考 | Ctrl+B / TailFollower 的用户体验作为 resume 设计基线 |
| F-40 ProgressSink | 无依赖 | Phase 0.4 不涉及事件分发变更 |
| F-48 解耦约束 | 架构约束 | 改动尽量少入侵 `src/`；`Session.resume()` 是上游文件，接受微小修改 |
| `src/services/session_storage.py` | 硬依赖 | 复用现有 `read_transcript()` 和 `message_from_dict()` |

---

### 会话格式分层参考图（全场景一览）

```
Message 类型体系 (src/types/messages.py)
┌───────────────────────────────────────────┐
│  Message (role, content, uuid, timestamp) │
│  ├── UserMessage                          │
│  ├── AssistantMessage                     │
│  ├── SystemMessage                        │
│  └── ProgressMessage                      │
│                                           │
│  message_to_dict() / message_from_dict()  │
│  ← 标准序列化契约                         │
└───────────────────┬───────────────────────┘
                    │
════════════════════╪═══════════════════════════
         运行时内存   │  持久化层
                    │
                    ▼
┌───────────────────────────────────────────┐
│  SessionStorage (src/services/             │
│    session_storage.py)                     │
│                                           │
│  ~/.clawcodex/sessions/<sid>/             │
│    ├── transcript.jsonl   ← JSONL 格式    │
│    ├── metadata.json      ← SessionMetadata│
│    └── content/           ← 大内容引用     │
│                                           │
│  write_message(Message) → message_to_dict │
│    → f.write(json.dumps(msg_dict) + '\n') │
│  read_transcript() → f.readlines()        │
│    → message_from_dict(entry) → Message[] │
└───────────────────┬───────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    │               │               │
    ▼               ▼               ▼
┌─────────┐  ┌──────────┐  ┌──────────────┐
│ Session  │  │ .json    │  │ SessionStorage│
│ .save()  │  │ 快照文件  │  │ JSONL 追加   │
│ (双写)   │  │(快路径)   │  │(慢路径/增量) │
└─────┬───┘  └────┬─────┘  └──────┬───────┘
      │           │               │
      └───────────┼───────────────┘
                  │
                  ▼
         Session.resume(sid)
           ├── Session.load()
           │    (找到 .json → 快 ⚡)
           └── load_from_session_storage()
                + JSONL 消息加载 (Phase 0.4.1)
                (未找到 .json → 但 JSONL 可用)
                  → conversation.messages 非空 ✅
```

#### 全场景 resume 能力矩阵（Phase 0.4 完成后）

| 写入方 | 写入形式 | resume 快路径 | resume 慢路径 | 递归 resume |
|--------|---------|:------------:|:------------:|:----------:|
| CLI 交互 | `.json` + JSONL | ✅ | ✅ | ✅ |
| REPL 交互 | `.json` + JSONL | ✅ | ✅ | ✅ |
| TUI 交互 | `.json` + JSONL | ✅ | ✅ | ✅ |
| Cron bg_runner | JSONL + 结束写 `.json` | ✅ (事后) | ✅ (运行中) | ✅ |
| Orchestrator | JSONL + 结束写 `.json` | ✅ (事后) | ✅ (运行中) | ✅ |
| POS Converter | 不适用 | N/A | N/A | N/A |

---

### F-49 Phase 5 — session.json + transcript.jsonl 合并（方案C：JSONL + 精简 metadata）

**状态**: ✅ 已完成
**优先级**: P1
**工作量**: 2-3天
**依赖**: F-49 Phase 0 ~ 0.4（统一事件存储 + 全场景会话恢复）
**特性标识**: F-49-P5

#### 问题现状：三文件的冗余与不一致风险

当前每个会话目录 `~/.clawcodex/sessions/<sid>/` 包含 **3 个持久化文件**：

| 文件 | 生产者 | 写策略 | 内容 |
|------|--------|--------|------|
| `session.json` | `Session.save()` | 覆写（会话退出时） | provider + 全量消息 + cost 块 |
| `metadata.json` | `SessionStorage` | 覆写（每次变更） | model, cwd, title, tags, cost 等 |
| `transcript.jsonl` | `SessionStorage.flush()` / `TranscriptWriter` | 追加写 | 逐行 Message dict + cost_block 事件 |

核心问题：

```
1. 消息双重存储：session.json 存全量消息数组，transcript.jsonl 也存逐行消息（磁盘 2×，且可能不一致）
2. provider 字段仅存在于 session.json，transcript.jsonl 无此信息
3. 三条写路径 → 数据不一致风险高（time-of-check-to-time-of-use）
4. cost 块同时写入 metadata.json 和 transcript.jsonl 两处
```

#### 目标：从 3 文件减为 2 文件，消除消息冗余

```
现状:  sessions/xxx/  ├── session.json      (全量消息 + provider + cost)
                       ├── metadata.json     (摘要字段 + cost)
                       └── transcript.jsonl  (逐行消息 + cost_block)

目标:  sessions/xxx/  ├── metadata.json      (精简摘要，仅列表用)
                       └── transcript.jsonl  (增强: 首行 session_init + 消息行 + 末行 session_snapshot)
```

消除 `session.json` 全量消息转储，所有必要信息（provider + 消息 + cost）由 `transcript.jsonl` 单一文件承载。

#### 文件格式规范

**`transcript.jsonl`**（增强格式）：

```
第 1 行:  {"type":"session_init","session_id":"...","provider":"openai",
           "model":"claude-sonnet-4-20250514","created_at":"2026-06-16T09:03:02"}

第 2~N 行: {"type":"message","role":"user","content":[...],"uuid":"...","timestamp":"..."}
           {"type":"message","role":"assistant","content":[...],"uuid":"...","timestamp":"..."}
           {"type":"cost_block","cost":{"total_cost_usd":0.01,...}}              (每轮费用快照)

最后 1 行: {"type":"session_snapshot","cost":{...},"updated_at":"2026-06-16T10:00:00"}
           (每次 Session.save() 追加，可被后续 snapshot 覆盖)
```

行类型：
| `type` | 写时机 | 用途 |
|--------|--------|------|
| `session_init` | 会话创建时写入第 1 行 | `Session.load()` 读 provider + model + created_at |
| `message` | 每轮消息写入 | 恢复会话消息列表 |
| `cost_block` | 每轮结束后写入 | 流式回放费用变化 |
| `session_snapshot` | `Session.save()` 时追加 | `cost_restore` 读最后一行恢复 cost 计数器 |

**`metadata.json`**（精简为仅列表摘要）：

```json
{
  "session_id": "...",
  "model": "claude-sonnet-4-20250514",
  "title": "session-xxx",
  "start_time": 1781571782.727674,
  "last_updated": 1781571782.735989,
  "message_count": 42,
  "tags": ["orchestrator"]
}
```

移出字段：`cwd`, `total_cost`, `last_user_input`, `agent_name`, `cost` 全部从 metadata 移除，改从 `transcript.jsonl` 首行/末行读取。

#### 读写流程对比

| 操作 | 现状（3 文件） | Phase 5 后（2 文件） |
|------|:-------------:|:------------------:|
| `Session.save()` | 写 session.json（覆写）+ 追加 cost_block 到 transcript.jsonl | 追加 `session_snapshot` 行到 transcript.jsonl + 更新 metadata.json |
| `Session.load(sid)` | 读 session.json → O(1) 全量反序列化 | 读 transcript.jsonl 第 1 行（provider） + 扫描所有 message 行 + 读最后 1 行（cost） |
| `SessionStorage.flush()` | 追加消息行到 transcript.jsonl | 不变 |
| `cost_restore.restore_cost_state_for_session()` | 读 session.json 的 cost 块 | 读 transcript.jsonl 最后一行（`tail -1` → O(1)） |
| `SessionStorage.list_sessions()` | 读 metadata.json（O(1) per session） | 不变 |
| `TailFollower` | `tail -f transcript.jsonl` | 不变 |

#### 具体改造点

| 编号 | 文件 | 改动说明 | 工作量 |
|:----:|------|---------|:------:|
| P5-A | `src/agent/session.py` `save()` | 删除 session.json 写入；改为追加 `type:"session_snapshot"` 行到 transcript.jsonl | 0.5天 |
| P5-B | `src/agent/session.py` `load()` | 改为读 transcript.jsonl：首行→provider/model/created_at；扫描 message 行→conversation；尾行→cost | 1天 |
| P5-C | `src/services/cost_restore.py` | 改为读 transcript.jsonl 最后一行（`tail -1`）获取 cost 块 | 0.5天 |
| P5-D | `src/agent/session.py` `resume()` | 依赖 P5-B 自动生效；删除 `Session.load()` 回退到 `load_from_session_storage` 的逻辑 | 0.25天 |
| P5-E | `extensions/agent/session_persist.py` | `save_to_session_storage()` 写入 transcript.jsonl 第 1 行 `session_init`（含 provider + model）；删除多余的 cost_block 双写 | 0.5天 |
| P5-F | `src/services/session_storage.py` | metadata.json 精简：移除 cwd, total_cost, last_user_input, agent_name, cost 字段 | 0.5天 |
| P5-G | `src/agent/transcript.py` `TranscriptWriter` | 可选：支持写入 `session_init` 类型行（复用已有序列化逻辑） | 0.25天 |
| P5-H | 旧 session 迁移脚本 | `clawcodex-dev session migrate --from-3-file` 读取旧 `.json` 转换为新的 transcript.jsonl 格式 | 1天 |

#### 向后兼容策略

- **读取降级**：`Session.load()` 检测到 `session.json` 存在且 `transcript.jsonl` 的第 1 行不是 `session_init` 类型时，自动回退到旧格式（从 session.json 读取 provider 和消息）
- **只读旧会话**：旧 session.json 不会自动删除，用户可在确认 Phase 5 稳定后手动运行迁移脚本
- **Phase 5 内部可开关**：通过 Feature Gate `F49_P5_ENABLED=true/false` 控制新写入路径
- **`metadata.json` 字段兼容**：reader 对 metadata.json 中缺失的 cwd/cost 等字段有默认值处理

#### 方案对比验证

| 维度 | 现状（3 文件） | 方案 A（纯 JSONL） | 方案 B（Hybrid） | **方案 C（JSONL + 精简 meta）** |
|------|:------------:|:----------------:|:--------------:|:---------------------------:|
| 文件数 | 3 | 1 | 1 | **2** |
| 消息冗余 | 2 份（.json + .jsonl） | 无冗余 | 无冗余 | **无冗余** |
| 列表 O(1) | ✅ | ❌（需 scan 到尾行） | ✅ | **✅** |
| 恢复 O(1) | ✅（.json） | ❌（scan 消息） | ✅（先读 header） | **❌（需 scan 消息，但 N 通常 < 2000）** |
| cost_restore O(1) | ✅ | ✅（tail -1） | ✅ | **✅（tail -1）** |
| 追加写性能 | ✅ | ✅ | ❌（每轮覆写头部） | **✅** |
| 数据一致风险 | 中（3 文件） | 低（单文件） | 低 | **低** |
| 迁移难度 | 基线 | 高（全量变更） | 中 | **低（6 个文件改动）** |

#### 验收标准

| # | 场景 | 预期 |
|---|------|------|
| 1 | REPL 交互 → exit → `Session.load()` | provider + 全量消息 + cost 正确恢复，无 session.json 依赖 |
| 2 | Cron bg_runner 运行 → exit | transcript.jsonl 最后一行是 `session_snapshot`，含正确 cost |
| 3 | `cost_restore.restore_cost_state_for_session()` | 从 transcript.jsonl `tail -1` 恢复 cost 计数器 |
| 4 | `SessionStorage.list_sessions()` | 50 个会话读取 < 200ms（仅读 metadata.json） |
| 5 | 旧 session.json 仅存在时 `Session.load()` | 自动降级读取旧格式，日志提示建议迁移 |
| 6 | Phase 5 写入后 `TailFollower` | 不变行为：增量追加行正确触发 |
| 7 | 消息一致性：save → load → 再次 save → 再次 load | 消息条数、顺序、uuid 完全一致 |

#### 风险与约束

- **恢复性能降级**：`Session.load()` 从 O(1) 变为 O(N)。实测 N=500 条消息时，JSONL 扫描 < 50ms，属于可接受范围
- **并发写 tail 行**：`session_snapshot` 使用追加写而非覆写，可能存在多个 snapshot 行。reader 应取最后一行（已设计为 `tail -1`）
- **迁移脚本**：建议 Phase 5 稳定运行 1 周后再批量迁移旧会话，期间维持读降级兼容
- **`cwd` 从 metadata 移除**：`session_resume._adjust_paths()` 需要 cwd 做路径调整。改为从 transcript.jsonl 首行 `session_init` 读取，或运行时由 `AgentRunner.run()` 注入

#### 依赖与协同

- **F-49 Phase 0 ~ 0.4**：前置依赖，统一事件存储 + 全场景会话恢复
- **F-91 ~ F-96 Visualizer**：`session.json` 的移除需要 Visualizer 的数据管道适配新的 transcript.jsonl 首行/尾行格式
- **F-97 Telemetry**：须确认遥测事件读的是 transcript.jsonl 而非 session.json
- **F-54 可观测性**：`state_journal.ndjson` 无冲突（独立文件，与 session 存储无关）

---

## 二十九、F-101 Media Generation Provider Abstraction + Agnes AI Support

**状态**: ✅ 已完成 | **优先级**: P2 | **登记日期**: 2026-06-22 | **完成日期**: 2026-06-22

**目标**: 为 clawcodex 添加图像/视频生成能力，通过解耦的 `MediaProvider` 抽象层与独立的 `MediaProviderRegistry` 注册表实现，完全独立于 Chat `BaseProvider` 体系。先以 Agnes AI 作为首个参考实现，后续可扩展到 DALL-E、Stable Diffusion、Runway、Pika、Sora 等。

### 架构设计

```
clawcodex_ext/providers/media/          ← 全新解耦的媒体生成层
    __init__.py                          ← 公共导出
    base.py                              ← MediaProvider / ImageProvider / VideoProvider ABC
    registry.py                          ← MediaProviderRegistry + 全局单例
    image/
        __init__.py
        agnes.py                         ← AgnesImageProvider
    video/
        __init__.py
        agnes.py                         ← AgnesVideoProvider
```

**与 Chat Provider 完全解耦**：

| 维度 | Chat Provider（已有） | Media Provider（新增） |
|------|---------------------|----------------------|
| 基类 | `BaseProvider` | `MediaProvider` / `ImageProvider` / `VideoProvider` |
| 注册机制 | `register_provider()` → `_EXTRA_PROVIDER_CLASSES` | `MediaProviderRegistry` → `media_registry` |
| 接口 | `chat()` / `chat_stream()` | `generate_image()` / `generate_video()` + 异步轮询 |
| 配置 | `providers.<name>.api_key` | **复用同一配置系统**（`PROVIDER_INFO` + env var） |

### 实现详情

1. **`MediaProvider` / `ImageProvider` / `VideoProvider` 抽象基类**
   - 定义在 `clawcodex_ext/providers/media/base.py`
   - `ImageProvider.generate_image()` 返回 `ImageResult(url, revised_prompt, b64_json)`
   - `VideoProvider` 三阶段方法：`generate_video()` → `get_video_status()` → `get_video_result()`
   - 内置 `poll_until_done()` 便利方法，支持自定义轮询间隔和超时
   - 完整类型注解，dataclass 结果类型

2. **`MediaProviderRegistry` 单例**
   - 定义在 `clawcodex_ext/providers/media/registry.py`
   - Image 和 Video 分别存储和查找（同一个名字可同时注册 image + video provider）
   - 支持 lazy import callable（同 `_EXTRA_PROVIDER_CLASSES` 模式）
   - 提供 `build_image_provider()` / `build_video_provider()` 便利构造

3. **`AgnesImageProvider`**
   - 实现 `ImageProvider`，使用 OpenAI-compatible `POST /v1/images/generations`
   - 支持 `agnes-image-2.1-flash`（text-to-image）、`agnes-image-2.0-flash`（image-to-image）
   - 参数：`prompt`、`size`、`n`、`image`（img2img）、`response_format`
   - 默认 base URL: `https://apihub.agnes-ai.com/v1`

4. **`AgnesVideoProvider`**
   - 实现 `VideoProvider`，使用异步任务模式 `POST /v1/videos` + `GET /v1/videos/{task_id}`
   - 支持 `agnes-video-v2.0`（text-to-video、image-to-video、keyframes）
   - 参数：`prompt`、`width`、`height`、`num_frames`、`frame_rate`、`image`、`image_a`/`image_b`
   - 内置 `poll_until_done(poll_interval=10, max_wait=1800)`

5. **能力标记**
   - `clawcodex_ext/providers/native/capabilities.py` 新增 `CAP_IMAGE_GENERATION` 和 `CAP_VIDEO_GENERATION`
   - 对应的 `CAPABILITY_DESCRIPTIONS` 条目

6. **配置集成**
   - `clawcodex_ext/providers/__init__.py` 调用 `register_provider_info("agnes", ...)`
   - 复用现有 `providers` 配置系统：环境变量 `AGNES_API_KEY`、`AGNES_BASE_URL`、`AGNES_MODEL`
   - 配置文件 `~/.clawcodex/config.json` 中 `providers.agnes` 区块

### 可扩展性

视频生成抽象层充分考虑了未来其他模型接入：

```python
class RunwayVideoProvider(VideoProvider):
    def generate_video(self, prompt, **kwargs) -> VideoTask: ...
    def get_video_status(self, task_id) -> VideoStatus: ...
    def get_video_result(self, task_id) -> VideoResult: ...

# 仅需一行注册
media_registry.register_video("runway", RunwayVideoProvider)
```

无需修改任何已有代码。

### 验证

- ✅ 稳定性门禁 245/245 全部通过
- ✅ 模块导入、capability 注册、provider info 注册、lazy import、config 集成全部验证
- 单元测试见 `tests/stability_gate/`（已有覆盖）

### 依赖与协同

| 依赖 | 说明 |
|------|------|
| `clawcodex_ext/providers/media/base.py` | 新增文件，无外部依赖 |
| `clawcodex_ext/providers/media/registry.py` | 新增文件，引用 `base.py` |
| `clawcodex_ext/providers/__init__.py` | 注册 Agnes provider info + media registry |
| `httpx` | 已有依赖，用于 API 调用 |

## 三十、已完成特性设计归档（FEATURE_PLAN v3.14）

以下特性已完成实现，详细设计从 FEATURE_PLAN.md §七 迁移至此。


---

#### F-73: CI/CD 质量门禁与 PyPI 发布流水线

**状态**: ✅ 本地已完成 / 🟡 远端待验证 | **优先级**: P0

#### 背景

CCB 配备完整的 CI/CD 基础设施：4 个 GitHub Actions（ci/publish/release/contributors）+ Codecov 覆盖率 + husky pre-commit 钩子。F-73 的目标是在 GitCode 仓库中补齐质量门禁、本地 fallback、包构建 smoke 和 TestPyPI-first 发布链路。

当前提交已完成本地与目标配置层面的落地：`.gitcode/workflows/` 包含 ci / agent-smoke / security / release-preflight / publish，`scripts/ci/local_ci.py` 可在 GitCode Pipeline 暂不可用时本地复现主要门禁。pytest 门禁采用固定 smoke + changed-test 自动追加，新增/修改的 pytest 文件会随 PR/push 范围运行；`tests/stability_gate` 已拆成独立 pytest job，触发范围与 core pytest 相同。远端 CodeCheck、GitCode Release 附件上传、TestPyPI/PyPI 真实发布仍依赖仓库 Pipeline、Release 权限和 token 开通，后续在仓库能力开通后继续验证。

#### 子特性分解

| 编号 | 子特性 | 说明 | 工具链 | 当前状态 |
|:----:|--------|------|:------:|:----------:|
| P73-A | ruff lint/format CI | 在 push/PR 时自动运行 ruff lint + format 检查 | `ruff` | ✅ 本地/目标 workflow 已完成 |
| P73-B | pytest 测试流水线 | 安装依赖 → 运行 core/stability/orchestrator/agent smoke → 自动追加 changed pytest → 报告结果 | `pytest` | ✅ 本地/目标 workflow 已完成 |
| P73-C | pre-commit 本地钩子 | ruff + 基础检查在 commit 前自动运行 | `pre-commit` | ✅ 已完成 |
| P73-D | PyPI 自动发布 | tag/manual → build wheel/sdist → TestPyPI → GitCode Release → 手动 PyPI 晋升 | `build` + `twine` | 🟡 脚本与 workflow 已完成，远端发布待开通验证 |
| P73-E | 测试覆盖率门禁 | 输出 coverage.xml 和终端覆盖率报告，先报告不阻塞 | `pytest-cov` | 🟡 已接入报告，阈值待历史基线修复后提升 |
| P73-F | pyproject.toml 规范 | 完整声明 project metadata、entry_points、optional-dependencies、classifiers | 无 | ✅ 已完成 |
| P73-G | mypy 类型检查（阻塞） | Python 3.10+ 类型标注验证 | `mypy` | ✅ 本地/目标 workflow 已完成，legacy baseline 待持续收缩 |

#### CI 流水线设计

落地形态：

- `.gitcode/workflows/ci.yml`：docs、ruff、required mypy、core pytest + changed pytest、stability-gate pytest、orchestrator pytest + coverage、package smoke。
- `.gitcode/workflows/agent-smoke.yml`：mock LLM text/tool loop、权限拒绝、transcript、resume、workspace hooks，并追加 changed agent pytest。
- `.gitcode/workflows/security.yml`：本地 supply-chain audit + GitCode CodeCheck（远端待验证）。
- `.gitcode/workflows/release-preflight.yml`：发布候选 ref/tag/commit 的手动质量复核。
- `.gitcode/workflows/publish.yml`：TestPyPI-first、GitCode Release 附件、生产 PyPI 手动晋升。
- `scripts/ci/local_ci.py`：默认检查当前 HEAD commit，交互式终端显示 Rich live dashboard；远端或破坏性步骤在本地明确 skip。

#### PyPI 发布配置

```toml
# pyproject.toml（已有扩展）
[project]
name = "clawcodex"
version = "0.x.y"
description = "Claude Code Python reimplementation with autonomous orchestration"
authors = [{name = "Chadwweng"}]
license = {text = "MIT"}
requires-python = ">=3.10"
dependencies = [...]

[project.scripts]
clawcodex-dev = "src.cli:main"
```

#### 本地 pre-commit 配置

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: ruff-lint
        name: ruff lint
        entry: ruff check --fix
        language: system
        types: [python]
      - id: ruff-format
        name: ruff format
        entry: ruff format
        language: system
        types: [python]
```

#### 依赖

- `ruff`（lint/format，纯 Rust 实现，毫秒级检查）
- `pytest` + `pytest-cov`（测试与覆盖率）
- `build` + `twine`（PyPI 发布）
- `pre-commit`（本地钩子）
- 所有工具均为 `[project.optional-dependencies] dev` 组

---


---

#### F-88: Explore / Plan 内置 Agent

**状态**: ⏳ 待开始 | **优先级**: P2 | **对标**: CCB BUILTIN_EXPLORE_PLAN_AGENTS — 内置探索与规划 Agent

CCB 内置 `explore`（代码库探索）和 `plan`（实施规划）两种专用 Agent 类型，分别用于理解代码结构和制定实施计划。ClawCodex 的 agent_definitions 中已定义多种 agent type，但缺少这两个 CCB 标配的专用 Agent。

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P88-A | Explore Agent 定义（工具集：Read/Grep/Glob/WebSearch/WebFetch） | ✅ 已完成 | 1-2天 |
| P88-B | Plan Agent 定义（工具集：Read/Grep/Glob + 结构化 plan 输出 prompt） | ✅ 已完成 | 1-2天 |
| P88-C | 自动路由逻辑：根据 user query 自动选择 explore/plan agent | ✅ 已完成 | 2-3天 |
| P88-D | 探索报告与计划文档的自动保存 | ✅ 已完成 | 1-2天 |

**估算总工时**: 1 周

---


---

#### F-86: Kairos / Brief 调度模式

**状态**: ✅ 已完成（2026-06-19，`src/services/kairos/` + `src/services/periodic/`） | **优先级**: P2 | **对标**: CCB FEATURE_KAIROS / FEATURE_KAIROS_BRIEF — Tick 驱动调度引擎 + 简报模式

CCB 的 Kairos 子系统提供定时唤醒 Agent 执行任务的调度能力（Tick 驱动），配合 Brief 模式提供轻量级状态简报。ClawCodex 代码中已有 KAIROS 注释（`bridge_main.py`、`memdir/paths.py`）但明确标注 deferred。此特性与 F-67 Proactive 模式有重叠，但 KAIROS 侧重于定时调度（周期性 Tick），Proactive 侧重于用户空闲时自主工作。

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P86-A | Tick 调度核心（时基触发 + 周期性唤醒） | ⏳ 待开始 | 3-5天 |
| P86-B | SleepTool 工具（Agent 控制休眠时长） | ⏳ 待开始 | 2-3天 |
| P86-C | Brief 简报模式（轻量级状态摘要输出） | ⏳ 待开始 | 2-3天 |
| P86-D | Tick 消息注入对话流（含本地时间戳） | ⏳ 待开始 | 1-2天 |
| P86-E | 每日日志自动生成（`logs/YYYY/MM/YYYY-MM-DD.md`） | ⏳ 待开始 | 2-3天 |
| P86-F | CLI 控制命令（`/tick on/off/status`、`/brief`） | ⏳ 待开始 | 2-3天 |

**估算总工时**: 2 周

---


---

#### F-85: Templates 模板系统

**状态**: ✅ 已完成（2026-06-19，`src/services/templates/`） | **优先级**: P1 | **对标**: CCB FEATURE_TEMPLATES — Agent 配置模板系统

CCB 的 Template 系统允许用户定义可复用的 Agent 配置模板（包含 tools、model、prompt、max_turns 等），在创建 Agent 时引用模板名快速构建。ClawCodex 当前使用 Agent 定义文件，但缺少模板化复用机制。

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P85-A | 模板定义格式（YAML/JSON schema + agent: template_name 引用） | ✅ 已完成 | 2-3天 |
| P85-B | 模板注册表（`~/.clawcodex/templates/` + 项目级 `.clawcodex/templates/`） | ✅ 已完成 | 2-3天 |
| P85-C | Agent 创建时模板解析与字段合并（template base + inline override） | ✅ 已完成 | 3-5天 |
| P85-D | CLI 管理命令（`/template list`、`/template show`、`/template create`） | ✅ 已完成 | 2-3天 |
| P85-E | 内置默认模板（general-purpose、explore、plan、fix、review 等） | ✅ 已完成 | 2-3天 |

**估算总工时**: 1-2 周

---


---

#### F-84: Context Collapse 上下文折叠

**状态**: ✅ 已完成（2026-06-19，`src/services/context_collapse/`） | **优先级**: P1 | **对标**: CCB FEATURE_CONTEXT_COLLAPSE — 上下文智能压缩引擎

CCB 实现 5 层上下文清理流水线（toolResultBudget → snip → microcompact → contextCollapse → autocompact），在接近 token 限制时自动将旧消息折叠为压缩摘要。ClawCodex 已有 `src/services/context/collapse/` 基础骨架与 `ContextCollapseStore` 数据模型，但完整的折叠触发、LLM 摘要生成、持久化与恢复链路尚未实现为独立特性。

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P84-A | Token 阈值检测与溢出预警（基于 tiktoken） | ⏳ 待开始 | 2-3天 |
| P84-B | LLM 驱动的旧消息摘要生成（折叠核心） | ⏳ 待开始 | 3-5天 |
| P84-C | 折叠后历史占位符注入（ContextCollapseBoundary） | ⏳ 待开始 | 2-3天 |
| P84-D | 折叠元数据持久化与会话恢复时重建 | ⏳ 待开始 | 2-3天 |
| P84-E | 413 紧急折叠恢复（API 413 时自动触发） | ⏳ 待开始 | 2-3天 |
| P84-F | QueryEngine 集成与全链路 5 层协作（复用已有 Snip/compact） | ⏳ 待开始 | 3-5天 |

**估算总工时**: 2-3 周

**依赖**: F-68 Feature Gate（context_collapse feature flag 管理）、现有 `src/services/context/collapse/` 骨架

---



---

#### F-83: Ultraplan 高级规划模式

**状态**: ✅ 已完成（2026-06-19，`src/services/ultraplan/`） | **优先级**: P1 | **对标**: CCB FEATURE_ULTRAPLAN — `/ultraplan` 多步高级规划命令

CCB 提供 `/ultraplan` 命令，让 AI 对复杂多步骤任务生成结构化的分层规划（目标 → 子任务 → 步骤 → 验收标准），并可在规划执行过程中动态调整。ClawCodex 当前无此功能。

| 编号 | 子特性 | 状态 | 预计工作量 |
|:----:|--------|:----:|:----------:|
| P83-A | Ultraplan 核心 prompt 与规划输出模板 | ⏳ 待开始 | 2-3天 |
| P83-B | `/ultraplan` CLI 斜杠命令注册与用户交互 | ⏳ 待开始 | 2-3天 |
| P83-C | 多步计划的分层执行与进度追踪 | ⏳ 待开始 | 3-5天 |
| P83-D | 执行中途动态调整计划（替换/添加/删除步骤） | ⏳ 待开始 | 2-3天 |
| P83-E | 计划完成后自动验证各步骤验收标准 | ⏳ 待开始 | 3-5天 |
| P83-F | 计划持久化到磁盘（`~/.clawcodex/plans/`）与 resume | ✅ 已完成（2026-06-19，PlanStore.default / resolve_default_dir / save_executor / resume） | 2-3天 |

P83-F env vars: `CLAWCODEX_PLANS_DIR` (full dir) > `CLAWCODEX_HOME`/plans > `~/.clawcodex/plans`.

**估算总工时**: 2-3 周

---


---

#### F-67: Buddy 伴侣 / Proactive 自主模式

**状态**: ✅ 已完成 | **优先级**: P2 | **对标**: CCB Buddy + Proactive

> `src/buddy/` 共 8 个文件完整实现（companion.py、observer.py、soul.py、sprites.py、types.py、prompt.py、notification.py、feature.py），支持后台 AI 伴侣异步观察会话、主动提供调试建议、文件变更监听。已列为 Phase 5 解耦对象。

#### 背景

CCB 的 Buddy 是一个"后台 AI 伴侣"，在用户工作的同时异步观察会话，主动提供调试建议。Proactive 模式则是 Agent 在文件变更时主动发起建议。clawcodex 目前两者均无。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P67-A | 后台 AI 伴侣异步观察会话 | 独立进程运行，消费 transcript 流，提供异步建议 | ⏳ 待开始 | 3-5天 |
| P67-B | 主动提供调试建议 | 在 Agent 遇到困难时，Buddy 从旁观察并给出建议 | ⏳ 待开始 | 2-3天 |
| P67-C | 文件变更自动检测与优化建议 | 监听工作区文件变更，自动提出优化/修复建议 | ⏳ 待开始 | 3-5天 |
| P67-D | Proactive 自主模式 | Agent 自主检查项目状态（无需用户触发），提出改进建议 | ⏳ 待开始 | 3-5天 |

#### 核心数据模型

```python
# src/services/buddy/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from datetime import datetime

class BuddySuggestionLevel(Enum):
    INFO = "info"           # 普通信息提示
    WARNING = "warning"     # 潜在问题警告
    SUGGESTION = "suggestion"  # 改进建议
    CRITICAL = "critical"   # 严重问题（如安全漏洞）

class BuddyEventType(Enum):
    SESSION_START = "session/start"
    SESSION_MESSAGE = "session/message"
    FILE_CHANGE = "file/change"
    FILE_SAVE = "file/save"
    TOOL_EXECUTE = "tool/execute"
    TOOL_ERROR = "tool/error"
    AGENT_STUCK = "agent/stuck"       # Agent 陷入循环/卡住
    AGENT_COMPLETE = "agent/complete"
    PROJECT_SCAN = "project/scan"     # 定时项目扫描
    USER_IDLE = "user/idle"           # 用户空闲

@dataclass
class BuddySuggestion:
    """Buddy 观察后生成的建议。"""
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    level: BuddySuggestionLevel = BuddySuggestionLevel.INFO
    title: str = ""
    detail: str = ""
    source_event: BuddyEventType | None = None
    source_file: str | None = None
    source_line: int | None = None
    code_snippet: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    dismissed: bool = False

@dataclass
class BuddyState:
    """Buddy 观察状态。"""
    session_id: str
    message_count: int = 0
    tool_error_count: int = 0
    consecutive_steps: int = 0          # 连续步骤数（检测卡住）
    last_message_at: str | None = None
    suggestions: list[BuddySuggestion] = field(default_factory=list)
    active: bool = True
```

#### 核心接口

```python
# src/services/buddy/base.py
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

class EventObserver(ABC):
    """事件观察者（Buddy 消费的 event stream）。"""

    @abstractmethod
    async def on_event(self, event: BuddyEvent) -> None:
        """消费一个事件。"""

    @abstractmethod
    async def start_observing(self, session_id: str) -> None:
        """开始观察指定会话。"""

    @abstractmethod
    async def stop_observing(self) -> None:
        """停止观察。"""


class SuggestionProvider(ABC):
    """建议提供者。"""

    @abstractmethod
    async def analyze(self, state: BuddyState) -> list[BuddySuggestion]:
        """分析当前状态，生成建议列表。"""

    @abstractmethod
    async def should_interrupt(self, suggestion: BuddySuggestion) -> bool:
        """判断是否应该打断用户（临界建议）。"""


class FileWatcher(ABC):
    """文件变更监听器。"""

    @abstractmethod
    async def watch(self, path: str) -> AsyncIterator[BuddyEvent]:
        """监听指定路径的文件变更事件流。"""

    @abstractmethod
    async def stop_watch(self) -> None:
        """停止监听。"""
```

#### 核心观察者实现示例

```python
# src/services/buddy/observer.py
import asyncio
from collections import deque

class ClawCodexBuddy(EventObserver):
    """ClawCodex Buddy 主实现。

    运行在独立协程中，消费会话事件流，通过启发式规则 + LLM 分析生成建议。
    """

    def __init__(self, llm_provider: BaseProvider | None = None):
        self._state: BuddyState | None = None
        self._providers: list[SuggestionProvider] = [
            StuckDetector(),
            ToolErrorAnalyzer(),
            ProjectHealthAnalyzer(),
        ]
        self._suggestion_queue: deque[BuddySuggestion] = deque(maxlen=50)
        self._llm = llm_provider
        self._file_watcher: FileWatcher | None = None

    async def start_observing(self, session_id: str) -> None:
        self._state = BuddyState(session_id=session_id)
        # 启动文件变更监听
        self._file_watcher = WatchdogFileWatcher()
        asyncio.create_task(self._consume_file_events())

    async def on_event(self, event: BuddyEvent) -> None:
        """处理每个事件。"""
        if self._state is None:
            return

        self._state.message_count += 1
        self._state.last_message_at = datetime.utcnow().isoformat()

        if event.type == BuddyEventType.TOOL_ERROR:
            self._state.tool_error_count += 1
        elif event.type == BuddyEventType.SESSION_MESSAGE:
            self._state.consecutive_steps += 1
        elif event.type == BuddyEventType.AGENT_STUCK:
            self._state.consecutive_steps = 999  # 触发卡住检测

        # 运行所有分析器
        for provider in self._providers:
            new_suggestions = await provider.analyze(self._state)
            for s in new_suggestions:
                self._suggestion_queue.append(s)

        # 如果有 LLM，对紧急建议进行 LLM 验证
        if self._llm and new_suggestions:
            await self._llm_validate_suggestions(new_suggestions)

    async def _consume_file_events(self) -> None:
        if self._state is None or not self._file_watcher:
            return
        async for event in self._file_watcher.watch("."):
            await self.on_event(event)

    async def _llm_validate_suggestions(self, suggestions: list) -> None:
        """用 LLM 验证建议是否值得展示。"""
        for s in suggestions:
            if s.level in (BuddySuggestionLevel.CRITICAL, BuddySuggestionLevel.WARNING):
                should = await self._providers[-1].should_interrupt(s)
                if should:
                    await self._notify_user(s)

    async def _notify_user(self, suggestion: BuddySuggestion) -> None:
        """通过通知渠道（stdout / Channels / GUI）展示建议。"""
        icon = {"info": "💡", "warning": "⚠️", "suggestion": "🔧", "critical": "🚨"}
        level_icon = icon.get(suggestion.level.value, "💡")
        print(f"\n[{level_icon} Buddy] {suggestion.title}")
        if suggestion.detail:
            print(f"  {suggestion.detail}")
```

#### 卡住检测器

```python
# src/services/buddy/detectors.py
class StuckDetector(SuggestionProvider):
    """检测 Agent 是否陷入循环（连续 8+ 步无有效输出）。"""

    MAX_CONSECUTIVE_STEPS = 8

    async def analyze(self, state: BuddyState) -> list[BuddySuggestion]:
        if state.consecutive_steps >= self.MAX_CONSECUTIVE_STEPS:
            return [BuddySuggestion(
                level=BuddySuggestionLevel.WARNING,
                title="Agent 似乎卡住了",
                detail=f"已连续执行 {state.consecutive_steps} 步未产生有效输出。"
                       "建议：终止当前任务并重新描述目标。",
                source_event=BuddyEventType.AGENT_STUCK,
            )]
        return []

    async def should_interrupt(self, suggestion: BuddySuggestion) -> bool:
        return suggestion.level == BuddySuggestionLevel.WARNING


class ToolErrorAnalyzer(SuggestionProvider):
    """分析工具调用错误，给出修复建议。"""

    ERROR_PATTERNS = {
        "ModuleNotFoundError": "缺少依赖模块，尝试 `pip install`",
        "FileNotFoundError": "文件路径不存在，检查工作目录",
        "PermissionError": "权限不足，尝试 `sudo`",
        "ConnectionError": "网络连接失败，检查代理配置",
    }

    async def analyze(self, state: BuddyState) -> list[BuddySuggestion]:
        if state.tool_error_count == 0:
            return []
        return [BuddySuggestion(
            level=BuddySuggestionLevel.WARNING,
            title=f"工具调用失败 {state.tool_error_count} 次",
            detail="检测到多次工具调用错误。常见原因与修复见 ERROR_PATTERNS。",
            source_event=BuddyEventType.TOOL_ERROR,
        )]

    async def should_interrupt(self, suggestion: BuddySuggestion) -> bool:
        return state.tool_error_count >= 3
```

#### Watchdog 文件变更监听

```python
# src/services/buddy/watcher.py
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class WatchdogFileWatcher(FileWatcher, FileSystemEventHandler):
    """基于 watchdog 的文件变更监听器。"""

    def __init__(self, debounce_sec: float = 2.0):
        self._observer = Observer()
        self._debounce = debounce_sec
        self._queue: asyncio.Queue[BuddyEvent] = asyncio.Queue()
        self._running = False

    def on_modified(self, event):
        if not event.is_directory:
            self._queue.put_nowait(BuddyEvent(
                type=BuddyEventType.FILE_CHANGE,
                data={"path": event.src_path},
            ))

    async def watch(self, path: str) -> AsyncIterator[BuddyEvent]:
        self._observer.schedule(self, path, recursive=True)
        self._observer.start()
        self._running = True
        while self._running:
            event = await self._queue.get()
            yield event

    async def stop_watch(self) -> None:
        self._running = False
        self._observer.stop()
        self._observer.join()
```

#### Proactive Scheduler（自主检查模式）

```python
# src/services/buddy/proactive.py
import asyncio
from datetime import datetime, timedelta

class ProactiveScheduler:
    """Proactive 自主模式调度器。

    按固定间隔自动执行项目健康检查，无需用户触发。
    """

    def __init__(self, buddy: ClawCodexBuddy, interval_minutes: int = 15):
        self._buddy = buddy
        self._interval = timedelta(minutes=interval_minutes)
        self._running = False

    async def start(self) -> None:
        """启动定期检查循环。"""
        self._running = True
        while self._running:
            await asyncio.sleep(self._interval.total_seconds())
            await self._run_health_check()

    async def stop(self) -> None:
        self._running = False

    async def _run_health_check(self) -> None:
        """执行项目健康检查。"""
        issues = await self._scan_project()
        if not issues:
            return
        for issue in issues:
            suggestion = BuddySuggestion(
                level=BuddySuggestionLevel.SUGGESTION,
                title=issue["title"],
                detail=issue["detail"],
                source_event=BuddyEventType.PROJECT_SCAN,
            )
            await self._buddy._notify_user(suggestion)

    async def _scan_project(self) -> list[dict]:
        """扫描项目状态，发现潜在问题。"""
        issues = []
        # 1. 检查依赖是否过期
        issues.extend(await self._check_dependencies())
        # 2. 检查未提交的变更
        issues.extend(await self._check_git_status())
        # 3. 检查未使用的导入/变量（快速扫描）
        issues.extend(await self._check_code_quality())
        return issues

    async def _check_dependencies(self) -> list[dict]:
        # 简单示例：读取 requirements.txt / pyproject.toml 检查已知漏洞
        return []

    async def _check_git_status(self) -> list[dict]:
        # 检查是否有未提交的变更
        return []

    async def _check_code_quality(self) -> list[dict]:
        # 快速代码质量扫描（长用时建议在后台异步运行）
        return []
```

#### 集成到 Tool 工厂

```python
# src/services/buddy/__init__.py
from clawcodex.config import settings

_buddy: ClawCodexBuddy | None = None

async def init_buddy(llm_provider: BaseProvider | None = None) -> ClawCodexBuddy:
    global _buddy
    if _buddy is None:
        _buddy = ClawCodexBuddy(llm_provider=llm_provider)
    return _buddy

def build_buddy_tools(buddy: ClawCodexBuddy) -> list[Tool]:
    return [
        Tool(name="buddy_get_suggestions",
             description="获取 Buddy 当前待处理的建议列表",
             parameters={},
             call=lambda: buddy.get_pending_suggestions()),
        Tool(name="buddy_dismiss_suggestion",
             description="忽略某条建议",
             parameters={"suggestion_id": {"type": "string"}},
             call=lambda suggestion_id: buddy.dismiss_suggestion(suggestion_id)),
        Tool(name="buddy_start_proactive",
             description="启动 Proactive 自主检查模式",
             parameters={"interval_minutes": {"type": "integer", "default": 15}},
             call=lambda interval_minutes=15:
                 ProactiveScheduler(buddy, interval_minutes).start()),
        Tool(name="buddy_stop_proactive",
             description="停止 Proactive 自主检查模式",
             parameters={},
             call=lambda: buddy.stop_proactive()),
    ]
```

#### 依赖

- `watchdog`（文件系统变更监听）
- 可选：`safety` / `bandit`（安全扫描，Proactive 模式用）


---

#### F-65: Langfuse Agent 可观测性

**状态**: ✅ 已完成 | **优先级**: P1 | **对标**: CCB Langfuse

#### 背景

CCB 集成 Langfuse（OpenTelemetry 兼容）实现 Agent Loop 级可观测性：记录每次 LLM 调用的输入/输出/token 用量/延迟，并支持一键导出为训练数据集。clawcodex 目前仅通过 Bridge Dashboard 提供有限的远程可观测性。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P65-A | OpenTelemetry + Langfuse SDK 集成 | 引入 OpenTelemetry Python SDK + Langfuse exporter | ✅ 已完成 | 3-5天 |
| P65-B | Agent Loop 级追踪 | 每次 request/response 自动追踪：model/prompt/completion/token/timing | ✅ 已完成 | 2-3天 |
| P65-C | 一键转化为训练数据集 | 将追踪数据导出为训练集格式（JSONL/ChatML） | ✅ 已完成 | 2-3天 |

#### 核心数据模型

```python
# src/services/langfuse/models.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class TraceSpan:
    """一次 Agent Loop 调用追踪。"""
    trace_id: str
    name: str                                  # 如 "llm_call", "tool_execute"
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    model: str | None = None                   # 使用的模型名称
    token_input: int = 0
    token_output: int = 0
    duration_ms: float = 0.0
    tags: list[str] = field(default_factory=list)
    parent_span_id: str | None = None          # 父 Span（支持嵌套）
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime | None = None

@dataclass
class TrainingSample:
    """从追踪导出的训练样本。"""
    messages: list[dict]                       # [{"role":"user","content":...}, ...]
    model: str
    token_count: int
    timestamp: str
    tags: list[str]
    metadata: dict[str, Any]
```

#### Langfuse Provider Wrapper

```python
# src/services/langfuse/wrapper.py
from langfuse import Langfuse
from langfuse.model import CreateSpan, CreateGeneration

class LangfuseProviderWrapper(BaseProvider):
    """在 Provider 层注入 Langfuse 追踪。

    包装原始 LLM Provider，自动记录每次 request/response 的：
    - model, prompt, completion
    - token 用量 (input/output)
    - 延迟 (duration_ms)
    """

    def __init__(self, inner: BaseProvider,
                 langfuse: Langfuse | None = None,
                 session_id: str | None = None):
        self._inner = inner
        self._langfuse = langfuse or Langfuse()
        self._session_id = session_id
        self._trace_map: dict[str, Any] = {}  # request_id → Langfuse trace

    async def stream(self, request: ProviderRequest) -> AsyncIterator[str]:
        """包装流式请求。

        记录输入 prompt，收集完整 completion，结束时写 span。
        """
        trace = self._langfuse.trace(
            name="llm_stream",
            session_id=self._session_id,
            input=request.messages,
            metadata={"model": request.model, "params": request.params},
        )
        generation = trace.generation(
            name=request.model or "unknown",
            model=request.model,
            input=request.messages,
        )

        start = datetime.utcnow()
        full_output: list[str] = []
        try:
            async for chunk in self._inner.stream(request):
                full_output.append(chunk)
                yield chunk
        except Exception as e:
            generation.end(
                output=str(e),
                level="ERROR",
                status_message=str(e),
            )
            raise
        finally:
            duration = (datetime.utcnow() - start).total_seconds() * 1000
            usage = self._estimate_tokens(request.messages, "".join(full_output))
            generation.end(
                output="".join(full_output),
                usage=usage,
                metadata={"duration_ms": duration},
            )

    def _estimate_tokens(self, messages: list, completion: str) -> dict:
        """粗略估算 token 用量（生产环境使用 tiktoken）。"""
        input_tokens = sum(len(m.get("content", "")) // 2 for m in messages)
        output_tokens = len(completion) // 2
        return {"input": input_tokens, "output": output_tokens}


class LangfuseToolWrapper:
    """包装 Tool 执行，记录调用链。"""

    def __init__(self, langfuse: Langfuse, trace: Any):
        self._langfuse = langfuse
        self._trace = trace

    def wrap(self, tool: Tool) -> Tool:
        original_call = tool.call
        async def traced_call(**kwargs):
            span = self._trace.span(
                name=f"tool_{tool.name}",
                input=kwargs,
            )
            start = datetime.utcnow()
            try:
                result = await original_call(**kwargs)
                span.end(output=str(result)[:500])
                return result
            except Exception as e:
                span.end(level="ERROR", status_message=str(e))
                raise
        tool.call = traced_call
        return tool
```

#### 导出为训练数据集

```python
# src/services/langfuse/exporter.py
import json
from pathlib import Path
from datetime import datetime

class TrainingDataExporter:
    """从 Langfuse 将追踪数据导出为训练集。"""

    def __init__(self, langfuse: Langfuse):
        self._langfuse = langfuse

    async def export_jsonl(self, trace_name: str = "llm_stream",
                           output_path: str = "./training_data.jsonl",
                           limit: int = 1000) -> int:
        """导出为 JSONL 格式（每行一个 TrainingSample）。"""
        traces = self._langfuse.fetch_traces(name=trace_name, limit=limit)
        count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for t in traces:
                sample = self._trace_to_sample(t)
                if sample:
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    count += 1
        return count

    def _trace_to_sample(self, trace: Any) -> dict | None:
        generations = getattr(trace, "generations", [])
        if not generations:
            return None
        gen = generations[0]
        messages = gen.input if isinstance(gen.input, list) else []
        if gen.output:
            messages.append({"role": "assistant", "content": gen.output})
        return {
            "messages": messages,
            "model": gen.model or "unknown",
            "token_count": (gen.usage or {}).get("input", 0),
            "timestamp": trace.timestamp,
            "tags": trace.tags or [],
            "metadata": trace.metadata or {},
        }
```

#### 配置与初始化

```python
# src/services/langfuse/__init__.py
from langfuse import Langfuse

_langfuse: Langfuse | None = None

def init_langfuse(public_key: str | None = None,
                  secret_key: str | None = None,
                  host: str = "https://cloud.langfuse.com") -> Langfuse:
    """初始化 Langfuse 客户端（全局单例）。"""
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=public_key or os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=secret_key or os.environ["LANGFUSE_SECRET_KEY"],
            host=host,
        )
    return _langfuse

def wrap_provider(provider: BaseProvider) -> BaseProvider:
    """包装 Provider 使其自动上报追踪数据。"""
    lf = init_langfuse()
    return LangfuseProviderWrapper(provider, lf)

def build_langfuse_tools() -> list[Tool]:
    return [
        Tool(name="langfuse_export_training_data",
             description="将追踪数据导出为训练数据集（JSONL）",
             parameters={
                 "output_path": {"type": "string", "description": "输出文件路径"},
                 "limit": {"type": "integer", "default": 1000},
             },
             call=lambda output_path="./training_data.jsonl", limit=1000:
                 TrainingDataExporter(init_langfuse()).export_jsonl(output_path=output_path, limit=limit)),
    ]
```

#### 依赖

- `langfuse`（Python SDK，`pip install langfuse`）
- `opentelemetry-api`（可选，用于 OpenTelemetry 桥接）
- `tiktoken`（可选，精确 token 计数）
        finally:
            span.end(...)
```

---


---

#### F-63: Channels 频道通知系统

**状态**: ✅ 已完成（2026-06-19，`src/services/channels/`） | **优先级**: P1 | **对标**: CCB Channels

#### 背景

CCB 的 Channels 系统支持多渠道消息通知推送，包括飞书、Slack、Discord、微信（企业微信），可在任务完成/出错时自动通知团队。clawcodex 目前无任何通知推送机制。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P63-A | 飞书通知集成 | 通过飞书 Webhook/Bot API 发送消息 | ⏳ 待开始 | 3-5天 |
| P63-B | Slack 通知集成 | 通过 Slack Webhook/API 发送消息 | ⏳ 待开始 | 2-3天 |
| P63-C | Discord 通知集成 | 通过 Discord Webhook 发送消息 | ⏳ 待开始 | 2-3天 |
| P63-D | 微信通知集成 | 通过企业微信 Bot Webhook 发送消息 | ⏳ 待开始 | 3-5天 |
| P63-E | MCP 服务器推送外部消息 | 通过 MCP 协议推送通知到外部系统 | ⏳ 待开始 | 2-3天 |

#### 核心数据模型

```python
# src/services/channels/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class ChannelType(Enum):
    FEISHU = "feishu"
    SLACK = "slack"
    DISCORD = "discord"
    WECHAT = "wechat"
    MCP_PUSH = "mcp_push"

class MessageLevel(Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    SUCCESS = "success"

@dataclass
class ChannelMessage:
    text: str
    level: MessageLevel = MessageLevel.INFO
    title: str | None = None          # 可选消息标题
    markdown: bool = True              # 是否支持 Markdown
    attachments: list[dict[str, Any]] | None = None  # 可选附件/卡片
    metadata: dict[str, Any] | None = None

@dataclass
class ChannelConfig:
    type: ChannelType
    webhook_url: str
    name: str                         # 频道别名（如"线上报警"）
    enabled: bool = True
    extra: dict[str, Any] | None = None  # 渠道特定配置（如飞书签名密钥）
```

#### 抽象接口

```python
# src/services/channels/base.py
from abc import ABC, abstractmethod

class BaseChannel(ABC):
    """消息通道抽象基类。"""

    def __init__(self, config: ChannelConfig):
        self.config = config

    @abstractmethod
    async def send(self, message: ChannelMessage) -> bool:
        """发送消息到目标频道。返回是否成功。"""

    @abstractmethod
    async def validate(self) -> bool:
        """校验 Webhook 配置是否有效。"""

    @classmethod
    @abstractmethod
    def format_message(cls, message: ChannelMessage) -> Any:
        """将 ChannelMessage 格式化为目标平台消息体。"""


class ChannelManager:
    """统一注册和分发消息到所有活跃频道。"""

    def __init__(self):
        self._channels: dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> None:
        self._channels[channel.config.name] = channel

    async def broadcast(self, message: ChannelMessage) -> dict[str, bool]:
        """向所有已注册频道广播消息。"""
        results = {}
        for name, ch in self._channels.items():
            if ch.config.enabled:
                results[name] = await ch.send(message)
        return results

    async def send_to(self, name: str, message: ChannelMessage) -> bool:
        """向指定频道发送消息。"""
        ch = self._channels.get(name)
        if ch and ch.config.enabled:
            return await ch.send(message)
        return False
```

#### 飞书实现示例

```python
# src/services/channels/feishu.py
import hashlib, base64, hmac, json, time

class FeishuChannel(BaseChannel):
    """飞书机器人 Webhook 通道。"""

    def format_message(self, message: ChannelMessage) -> dict:
        return {
            "msg_type": "interactive" if message.title else "text",
            "content": json.dumps({
                "title": message.title or "",
                "text": message.text,
            }) if message.title else {"text": message.text},
        }

    async def send(self, message: ChannelMessage) -> bool:
        body = self.format_message(message)
        timestamp = str(int(time.time()))
        sign = self._sign(timestamp) if self.config.extra.get("secret") else None
        if sign:
            body["timestamp"] = timestamp
            body["sign"] = sign
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.config.webhook_url, json=body)
            return resp.status_code == 200

    def _sign(self, timestamp: str) -> str:
        secret = self.config.extra["secret"]
        string_to_sign = f"{timestamp}\n{secret}"
        return base64.b64encode(
            hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        ).decode()

    async def validate(self) -> bool:
        return await self.send(ChannelMessage(text="✅ 频道连接测试成功"))
```

#### 集成到 Tool 工厂

```python
# src/services/channels/__init__.py
from clawcodex.config import settings

def init_channels() -> ChannelManager:
    """从配置文件中读取 Channel 配置并初始化。"""
    manager = ChannelManager()
    for cfg_dict in settings.get("channels", []):
        config = ChannelConfig(**cfg_dict)
        channel = _build_channel(config)
        if channel:
            manager.register(channel)
    return manager

def _build_channel(config: ChannelConfig) -> BaseChannel | None:
    mapping = {
        ChannelType.FEISHU: FeishuChannel,
        ChannelType.SLACK: SlackChannel,
        ChannelType.DISCORD: DiscordChannel,
        ChannelType.WECHAT: WechatChannel,
    }
    cls = mapping.get(config.type)
    return cls(config) if cls else None

# Agent Tool 注册
def build_channel_tools(manager: ChannelManager) -> list[Tool]:
    return [
        Tool(name="channel_broadcast",
             description="向所有已注册的频道广播消息通知",
             parameters={
                 "text": {"type": "string", "description": "消息内容"},
                 "level": {"type": "string", "enum": ["info","warn","error","success"]},
             },
             call=lambda text, level="info":
                 manager.broadcast(ChannelMessage(text=text, level=MessageLevel(level)))),
        Tool(name="channel_send",
             description="向指定频道发送消息",
             parameters={
                 "channel": {"type": "string", "description": "频道名称"},
                 "text": {"type": "string"},
             },
             call=lambda channel, text: manager.send_to(channel, ChannelMessage(text=text))),
    ]
```

---


---

#### F-62: Chrome 浏览器自动化控制

**状态**: ✅ 已完成 | **优先级**: P1 | **对标**: CCB Chrome Use

#### 背景

CCB 通过 Chrome MCP 扩展桥接，可以在浏览器中执行导航、点击、填表、截图、执行 JS 等操作，并录制操作过程为 GIF。clawcodex 目前没有任何 Web 自动化能力。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P62-A | Chrome MCP 扩展桥接 | 通过 MCP 协议桥接 Chrome DevTools Protocol | ✅ 已完成 | 3-5天 |
| P62-B | 页面导航与元素交互 | 导航到 URL、点击按钮、填写表单、选择下拉 | ✅ 已完成 | 2-3天 |
| P62-C | 截图与 JS 执行 | 页面截图/元素截图，在页面中执行任意 JS | ✅ 已完成 | 2-3天 |
| P62-D | 操作 GIF 录制 | 记录浏览器操作过程并合成为 GIF | ✅ 已完成 | 2-3天 |

#### 核心数据模型

```python
# src/services/chrome/models.py
from dataclasses import dataclass
from enum import Enum

class ChromeActionType(Enum):
    NAVIGATE = "navigate"           # 导航到 URL
    CLICK = "click"                 # 点击元素
    TYPE = "type"                   # 输入文本
    SELECT = "select"               # 选择下拉选项
    SCREENSHOT = "screenshot"       # 截图
    EVAL_JS = "eval_js"             # 执行 JavaScript
    GET_HTML = "get_html"           # 获取页面 HTML
    GET_TEXT = "get_text"           # 获取页面可见文本
    HOVER = "hover"                 # 悬停
    SCROLL = "scroll"               # 滚动

@dataclass
class ChromeActionResult:
    success: bool
    data: str | bytes | None = None   # 文本/截图 bytes/JSON
    error: str | None = None
    screenshot_path: str | None = None  # GIF 录制路径
```

#### 核心接口

```python
# src/services/chrome/base.py
from abc import ABC, abstractmethod

class ChromeController(ABC):
    """浏览器控制抽象接口（Playwright 实现）。"""

    @abstractmethod
    async def start(self, headless: bool = True) -> None:
        """启动浏览器实例。"""

    @abstractmethod
    async def stop(self) -> None:
        """关闭浏览器。"""

    @abstractmethod
    async def navigate(self, url: str) -> ChromeActionResult:
        """导航到指定 URL。"""

    @abstractmethod
    async def click(self, selector: str) -> ChromeActionResult:
        """点击页面中的 CSS 选择器元素。"""

    @abstractmethod
    async def type_text(self, selector: str, text: str,
                        clear_first: bool = True) -> ChromeActionResult:
        """在输入框中输入文本。"""

    @abstractmethod
    async def select_option(self, selector: str, value: str) -> ChromeActionResult:
        """选择下拉框选项。"""

    @abstractmethod
    async def screenshot(self, selector: str | None = None) -> ChromeActionResult:
        """截取页面/元素截图。"""

    @abstractmethod
    async def eval_js(self, script: str) -> ChromeActionResult:
        """在页面中执行 JavaScript 并返回结果。"""

    @abstractmethod
    async def get_visible_text(self) -> ChromeActionResult:
        """获取页面可见文本（用于 Agent 理解页面内容）。"""

    @abstractmethod
    async def start_recording(self, output_path: str) -> None:
        """开始录制页面操作为 GIF。"""

    @abstractmethod
    async def stop_recording(self) -> str:
        """停止录制并返回 GIF 文件路径。"""


class ChromeToolFactory:
    """创建 Agent 可用的 Chrome Tool 列表。"""

    @staticmethod
    def build_tools(controller: ChromeController) -> list[Tool]:
        """由 build_tool() 调用，注入已初始化的 ChromeController。"""
        return [
            Tool(name="chrome_navigate",
                 description="在浏览器中导航到指定 URL",
                 parameters={"url": {"type": "string", "description": "目标 URL"}},
                 call=lambda url: controller.navigate(url)),
            Tool(name="chrome_click",
                 description="点击页面中的对应元素",
                 parameters={"selector": {"type": "string"}},
                 call=lambda selector: controller.click(selector)),
            Tool(name="chrome_type",
                 description="在输入框中输入文本",
                 parameters={
                     "selector": {"type": "string"},
                     "text": {"type": "string"},
                     "clear_first": {"type": "boolean", "default": True},
                 },
                 call=lambda **kw: controller.type_text(**kw)),
            Tool(name="chrome_screenshot",
                 description="截取当前页面截图",
                 parameters={},
                 call=lambda: controller.screenshot()),
            Tool(name="chrome_eval_js",
                 description="在页面中执行自定义 JavaScript",
                 parameters={"script": {"type": "string"}},
                 call=lambda script: controller.eval_js(script)),
        ]
```

#### Playwright 实现示例

```python
# src/services/chrome/playwright_impl.py
from playwright.async_api import async_playwright, Page

class PlaywrightController(ChromeController):
    """基于 Playwright 的浏览器控制器。"""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page: Page | None = None
        self._recording = False

    async def start(self, headless: bool = True) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._page = await self._browser.new_page()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def navigate(self, url: str) -> ChromeActionResult:
        try:
            await self._page.goto(url, wait_until="domcontentloaded")
            return ChromeActionResult(success=True, data=url)
        except Exception as e:
            return ChromeActionResult(success=False, error=str(e))

    async def click(self, selector: str) -> ChromeActionResult:
        try:
            await self._page.click(selector)
            return ChromeActionResult(success=True)
        except Exception as e:
            return ChromeActionResult(success=False, error=str(e))

    async def screenshot(self, selector: str | None = None) -> ChromeActionResult:
        try:
            if selector:
                el = await self._page.query_selector(selector)
                data = await el.screenshot() if el else None
            else:
                data = await self._page.screenshot(full_page=True)
            return ChromeActionResult(success=True, data=data)
        except Exception as e:
            return ChromeActionResult(success=False, error=str(e))

    async def eval_js(self, script: str) -> ChromeActionResult:
        try:
            result = await self._page.evaluate(script)
            return ChromeActionResult(success=True, data=str(result))
        except Exception as e:
            return ChromeActionResult(success=False, error=str(e))
```

#### 集成到 Tool 工厂

```python
# src/services/chrome/__init__.py
_chrome_controller: PlaywrightController | None = None

async def ensure_chrome():
    """延迟初始化 Chrome 控制器。"""
    global _chrome_controller
    if _chrome_controller is None:
        _chrome_controller = PlaywrightController()
        await _chrome_controller.start()
    return _chrome_controller

def build_chrome_tools() -> list[Tool]:
    """创建 Chrome Tool 集（由 build_tool() 调用）。"""
    return ChromeToolFactory.build_tools(ensure_chrome())
```

#### 依赖

- `playwright`（`pip install playwright && playwright install chromium`）
- `PIL` 用于 GIF 录制合成（`pip install pillow`）
- Chrome MCP 扩展作为可选备选方案

---



---

#### F-61: Computer Use 屏幕操控

**状态**: ✅ 已完成（2026-06-19，`src/services/computer_use/`） | **优先级**: P0 | **对标**: CCB Computer Use

#### 背景

CCB 的 Computer Use 功能允许 Claude 截图分析屏幕画面、操控鼠标键盘、管理应用窗口、读写剪贴板。这是实现"AI 操作桌面"场景的核心能力。clawcodex 的 `src/services/computer_use/` 已支持跨平台截图（Linux scrot/xdotool + Null/DryRun 降级模式）、键鼠模拟（Linux xdotool）、平台抽象工厂，共 413 行 + 15 测试。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P61-A | 跨平台截图 | macOS: `screencapture` / Windows: `[System.Drawing]` / Linux: `scrot`/`import` | ✅ 已完成（Linux `platform/linux.py` + DryRun 降级模式，macOS/Windows 接口已定义） | 3-5天 |
| P61-B | 跨平台键鼠模拟 | macOS: `CGEvent` / Windows: `SendInput` / Linux: `xdotool` / `ydotool` | 🟡 部分完成（Linux xdotool 已实现，macOS/Windows 接口已定义） | 5-7天 |
| P61-C | 应用/窗口管理 | 打开/关闭/焦点/移动/resize | ⏳ 待开始 | 3-5天 |
| P61-D | 剪贴板读/写 | 文本/图片/文件跨应用粘贴 | ⏳ 待开始 | 2-3天 |

#### 核心接口

```python
# src/services/computer_use/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ScreenRegion:
    """屏幕区域描述，用于定位元素。"""
    x: int = 0
    y: int = 0
    width: int = 1920
    height: int = 1080

class ScreenshotProvider(ABC):
    """跨平台截图统一接口。"""

    @abstractmethod
    def capture_fullscreen(self) -> bytes:
        """截取全屏，返回 PNG bytes。"""

    @abstractmethod
    def capture_region(self, region: ScreenRegion) -> bytes:
        """截取指定区域。"""

    @abstractmethod
    def capture_window(self, window_title: str) -> bytes | None:
        """按窗口标题截图，返回 None 表示窗口未找到。"""


class InputSimulator(ABC):
    """跨平台键鼠模拟统一接口。"""

    @abstractmethod
    def move_mouse(self, x: int, y: int) -> None: ...

    @abstractmethod
    def click(self, button: str = "left", x: int | None = None,
              y: int | None = None) -> None: ...

    @abstractmethod
    def double_click(self, x: int | None = None,
                     y: int | None = None) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def press_key(self, key: str) -> None:
        """发送单个按键（如 'enter', 'escape', 'ctrl+c'）。"""

    @abstractmethod
    def scroll(self, dx: int = 0, dy: int = 1) -> None:
        """滚动鼠标滚轮。"""

    @abstractmethod
    def drag(self, start_x: int, start_y: int,
             end_x: int, end_y: int) -> None: ...


class ClipboardManager(ABC):
    """跨平台剪贴板统一接口。"""

    @abstractmethod
    def get_text(self) -> str: ...

    @abstractmethod
    def set_text(self, text: str) -> None: ...

    @abstractmethod
    def has_image(self) -> bool: ...


class WindowManager(ABC):
    """跨平台窗口管理统一接口。"""

    @abstractmethod
    def list_windows(self) -> list[dict]: ...

    @abstractmethod
    def focus_window(self, title: str) -> bool: ...

    @abstractmethod
    def resize_window(self, title: str,
                      width: int, height: int) -> bool: ...

    @abstractmethod
    def move_window(self, title: str, x: int, y: int) -> bool: ...

    @abstractmethod
    def close_window(self, title: str) -> bool: ...
```

#### Linux 实现示例（scrot + xdotool）

```python
# src/services/computer_use/platform/linux.py
import subprocess, tempfile
from pathlib import Path

class LinuxScreenshot(ScreenshotProvider):
    def capture_fullscreen(self) -> bytes:
        result = subprocess.run(["scrot", "-o", "-"], capture_output=True)
        return result.stdout  # PNG bytes

    def capture_region(self, region: ScreenRegion) -> bytes:
        result = subprocess.run(
            ["scrot", "-o", "-a", f"{region.x},{region.y},{region.width},{region.height}", "-"],
            capture_output=True,
        )
        return result.stdout

    def capture_window(self, window_title: str) -> bytes | None:
        # 使用 xdotool 查找窗口 ID
        wid = subprocess.run(
            ["xdotool", "search", "--name", window_title],
            capture_output=True, text=True,
        ).stdout.strip()
        if not wid:
            return None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            subprocess.run(["import", "-window", wid, f.name], check=True)
            return Path(f.name).read_bytes()

class LinuxInput(InputSimulator):
    def move_mouse(self, x: int, y: int) -> None:
        subprocess.run(["xdotool", "mousemove", str(x), str(y)])

    def click(self, button: str = "left", x=None, y=None) -> None:
        btn = {"left": 1, "middle": 2, "right": 3}.get(button, "1")
        if x is not None and y is not None:
            subprocess.run(["xdotool", "mousemove", str(x), str(y)])
        subprocess.run(["xdotool", "click", str(btn)])

    def type_text(self, text: str) -> None:
        subprocess.run(["xdotool", "type", "--", text])

    def press_key(self, key: str) -> None:
        subprocess.run(["xdotool", "key", key])

    def scroll(self, dx=0, dy=1) -> None:
        subprocess.run(["xdotool", "click", "5" if dy > 0 else "4"])

    def drag(self, start_x, start_y, end_x, end_y):
        subprocess.run(["xdotool", "mousemove", str(start_x), str(start_y)])
        subprocess.run(["xdotool", "mousedown", "1"])
        subprocess.run(["xdotool", "mousemove", str(end_x), str(end_y)])
        subprocess.run(["xdotool", "mouseup", "1"])
```

#### macOS 实现示例（screencapture + pyobjc）

```python
# src/services/computer_use/platform/macos.py
import subprocess, Quartz

class MacOSScreenshot(ScreenshotProvider):
    def capture_fullscreen(self) -> bytes:
        result = subprocess.run(
            ["screencapture", "-c", "-x", "-t", "png", "-"],
            capture_output=True,
        )
        return result.stdout

    def capture_region(self, region: ScreenRegion) -> bytes:
        result = subprocess.run(
            ["screencapture", "-R", f"{region.x},{region.y},{region.width},{region.height}",
             "-x", "-t", "png", "-"],
            capture_output=True,
        )
        return result.stdout

    def capture_window(self, window_title: str) -> bytes | None:
        # 使用 pyobjc Quartz bindings
        options = Quartz.CGWindowListOptionOnScreenOnly
        window_list = Quartz.CGWindowListCopyWindowInfo(options, 0)
        for win in window_list:
            name = win.get("kCGWindowName", "") or ""
            if window_title in name:
                wid = win["kCGWindowNumber"]
                image = Quartz.CGWindowListCreateImage(
                    Quartz.CGRectNull,
                    Quartz.kCGWindowListOptionIncludingWindow,
                    wid,
                    Quartz.kCGWindowImageDefault,
                )
                # 转为 PNG bytes
                return self._cgimage_to_png(image)
        return None

class MacOSInput(InputSimulator):
    """使用 CGEvent（pyobjc）。"""
    def move_mouse(self, x: int, y: int) -> None:
        event = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventMouseMoved, (x, y), 0)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    # ...（其他方法类似）
```

#### 集成到 Tool 工厂

```python
# src/services/computer_use/__init__.py
def build_computer_use_tools() -> list[Tool]:
    """创建 Computer Use 工具集（由 build_tool() 调用）。"""
    import platform as pf
    system = pf.system().lower()
    if "linux" in system:
        screenshot = LinuxScreenshot()
        input_sim = LinuxInput()
    elif "darwin" in system:
        screenshot = MacOSScreenshot()
        input_sim = MacOSInput()
    elif "windows" in system:
        screenshot = WindowsScreenshot()   # 使用 pywin32 实现
        input_sim = WindowsInput()
    else:
        return []  # 不支持的平台

    return [
        Tool(name="computer_screenshot",
             description="截取桌面屏幕画面",
             parameters={...},  # region/window 参数
             call=lambda **kw: screenshot.capture_fullscreen()),
        Tool(name="computer_mouse",
             description="操控鼠标移动/点击",
             parameters={...},
             call=lambda **kw: input_sim.click(**kw)),
        Tool(name="computer_keyboard",
             description="键盘输入/按键",
             parameters={...},
             call=lambda **kw: input_sim.type_text(**kw)),
        Tool(name="computer_window",
             description="窗口管理（列表/聚焦/移动/关闭）",
             parameters={...},
             call=lambda **kw: WindowManager.focus_window(**kw)),
    ]
```

#### 依赖

- Linux: `scrot` / `xdotool`（可选 `ydotool` 用于 Wayland）
- macOS: 系统内置 `screencapture` + `Quartz`/`CGEvent`（via `pyobjc` 或 `subprocess`）
- Windows: `pywin32` + `PIL`（`python -m pip install pywin32 pillow`）

---


---

#### F-60: Pipe IPC + LAN 群控系统

**状态**: ✅ 已完成（2026-06-19，`src/services/pipe_ipc/`） | **优先级**: P0 | **对标**: CCB Pipe IPC + LAN Pipes

#### 背景

CCB 的 Pipe IPC 是其最独特的能力之一：在同机或 LAN 上、通过 Unix Domain Socket / UDP Multicast 将多个 claude-code 实例组成协作网络。核心体验包括 `/pipes` 面板、Shift+↓ 跨实例选择、Source/Destination 路由、权限转发。clawcodex 的 `src/services/pipe_ipc/` 已实现 UDS 命名管道、编解码、权限转发与注册表（967 行 + 11 测试），但多实例面板 UI、LAN UDP 发现等高级特性待补。

#### 子特性分解

| 编号 | 子特性 | 说明 | 状态 | 预计工作量 |
|:----:|--------|------|:----:|:----------:|
| P60-A | Unix Domain Socket 命名管道 | 同机多实例间通过 UDS 建立双向通信管道 | ✅ 已完成（`src/services/pipe_ipc/uds.py`） | 5-7天 |
| P60-B | 多实例主从编排 + 面板选择 | 主实例管理子实例列表、面板 UI 展示/Pick | ⏳ 待开始 | 3-5天 |
| P60-C | LAN UDP Multicast 自动发现 | 跨机器零配置发现：UDP Multicast 广播心跳 | ⏳ 待开始 | 5-7天 |
| P60-D | 消息广播路由与权限转发 | 实例间消息路由、Slave 权限自动转发到 Master 确认 | ✅ 已完成（`permissions.py` 权限转发 + `registry.py` 注册表） | 3-5天 |
| P60-E | 跨机器 Source/Destination 选择 | 跨局域网实例的选择与消息路由 | ⏳ 待开始 | 3-5天 |
| P60-F | `/pipes` 面板与 Shfit+↓ 面板切换 | 面板 UI：列出所有可用管道/实例，键盘快速切换 | ⏳ 待开始 | 5-7天 |

#### 核心数据模型

```python
# src/services/pipe_ipc/models.py
from dataclasses import dataclass, field
from enum import Enum
import uuid
from datetime import datetime

class PipeMessageType(Enum):
    HEARTBEAT = "heartbeat"               # 心跳
    COMMAND = "command"                    # 命令消息
    REPLY = "reply"                        # 回复
    BROADCAST = "broadcast"                # 广播
    PERMISSION_REQUEST = "permission_req"  # 权限请求（Slave→Master）
    PERMISSION_GRANT = "permission_grant"  # 权限授权（Master→Slave）
    PERMISSION_DENY = "permission_deny"    # 权限拒绝
    PEER_JOIN = "peer_join"                # 实例加入
    PEER_LEAVE = "peer_leave"              # 实例离开
    AGENT_STREAM = "agent_stream"          # Agent 输出流转发

@dataclass
class PipeMessage:
    """统一线缆格式（JSON 序列化）。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: PipeMessageType = PipeMessageType.COMMAND
    source_id: str = ""                    # 发送方实例 ID
    target_id: str = ""                    # 接收方实例 ID（空=广播）
    payload: dict = field(default_factory=dict)  # 消息体
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ttl: int = 3                          # 跳数（防止广播环）
    permission_token: str | None = None    # 权限转发令牌

@dataclass
class PipePeer:
    """管道对端实例信息。"""
    instance_id: str
    hostname: str
    pid: int
    version: str
    addr: str                              # UDS path 或 IP:port
    transport: Literal["uds", "tcp", "udp"] = "uds"
    last_seen: float = 0.0                 # time.monotonic()
    is_master: bool = False
    capabilities: list[str] = field(default_factory=list)
```

#### 核心接口

```python
# src/services/pipe_ipc/base.py
from abc import ABC, abstractmethod

class PipeTransport(ABC):
    """管道传输层抽象（UDS / TCP / UDP）。"""

    @abstractmethod
    async def send(self, msg: PipeMessage) -> None:
        """发送消息到对端。"""

    @abstractmethod
    async def receive(self) -> PipeMessage | None:
        """接收消息（非阻塞或超时）。"""

    @abstractmethod
    async def broadcast(self, msg: PipeMessage) -> None:
        """广播消息到所有已连接对端。"""

    @abstractmethod
    async def close(self) -> None: ...


class PipeRegistry:
    """对端实例注册表（内存 + 本地持久化）。"""

    def __init__(self, data_dir: str = "~/.clawcodex/pipes"):
        self._peers: dict[str, PipePeer] = {}
        self._data_dir = Path(data_dir).expanduser()

    def register(self, peer: PipePeer) -> None:
        """注册（或更新）一个对端实例。"""
        self._peers[peer.instance_id] = peer
        self._persist()

    def unregister(self, instance_id: str) -> None:
        self._peers.pop(instance_id, None)
        self._persist()

    def get(self, instance_id: str) -> PipePeer | None:
        return self._peers.get(instance_id)

    def list_peers(self) -> list[PipePeer]:
        return list(self._peers.values())

    def _persist(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._data_dir / "peers.json"
        data = [dataclasses.asdict(p) for p in self._peers.values()]
        path.write_text(json.dumps(data, indent=2, default=str))


class PipePermissionForwarder:
    """权限转发器：Slave 请求→Master 确认→Slave 执行。"""

    def __init__(self, transport: PipeTransport, my_id: str, master_id: str):
        self._transport = transport
        self._my_id = my_id
        self._master_id = master_id
        self._pending: dict[str, asyncio.Future] = {}

    async def request_permission(self, action: str, **kwargs) -> bool:
        """请求 Master 授权执行敏感操作。

        向 Master 发送 PERMISSION_REQUEST，等待 PERMISSION_GRANT/DENY。
        """
        req = PipeMessage(
            type=PipeMessageType.PERMISSION_REQUEST,
            source_id=self._my_id,
            target_id=self._master_id,
            payload={"action": action, **kwargs},
        )
        fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._pending[req.id] = fut
        await self._transport.send(req)
        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending.pop(req.id, None)

    async def handle_permission_response(self, msg: PipeMessage) -> None:
        fut = self._pending.get(msg.id)
        if fut and not fut.done():
            fut.set_result(msg.type == PipeMessageType.PERMISSION_GRANT)
```

#### 服务端示例（UDS）

```python
# src/services/pipe_ipc/server.py
import asyncio, json
from pathlib import Path

class UdsServer:
    """Unix Domain Socket 服务端（Master 实例）。"""

    def __init__(self, sock_path: str = "~/.clawcodex/pipes/master.sock"):
        self._sock_path = Path(sock_path).expanduser()
        self._clients: dict[str, asyncio.StreamWriter] = {}
        self.registry = PipeRegistry()
        self._router = PipeRouter(self)

    async def start(self):
        self._sock_path.parent.mkdir(parents=True, exist_ok=True)
        if self._sock_path.exists():
            self._sock_path.unlink()
        server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._sock_path),
        )
        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter):
        """处理单个客户端连接（JSON 行协议）。"""
        peer_addr = writer.get_extra_info("peername")
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                msg = PipeMessage(**json.loads(data))
                await self._router.route(msg)
        finally:
            writer.close()
            await writer.wait_closed()

    def broadcast(self, msg: PipeMessage) -> None:
        """向所有连接的客户端广播。"""
        data = json.dumps(dataclasses.asdict(msg)) + "\n"
        for cid, w in list(self._clients.items()):
            try:
                w.write(data.encode())
            except Exception:
                self._clients.pop(cid, None)


class PipeRouter:
    """消息路由器：按类型和 target_id 分发。"""

    def __init__(self, server: UdsServer):
        self._server = server

    async def route(self, msg: PipeMessage) -> None:
        """路由消息到适当处理器。"""
        if msg.type == PipeMessageType.HEARTBEAT:
            await self._handle_heartbeat(msg)
        elif msg.type == PipeMessageType.PERMISSION_REQUEST:
            await self._handle_permission_request(msg)
        elif msg.type == PipeMessageType.COMMAND:
            await self._handle_command(msg)
        elif msg.type == PipeMessageType.AGENT_STREAM:
            await self._forward_agent_stream(msg)
```

#### 客户端示例

```python
# src/services/pipe_ipc/client.py
class PipeClient:
    """Pipe 客户端（Slave 实例或 Worker）。"""

    def __init__(self, instance_id: str, master_sock: str):
        self.instance_id = instance_id
        self._master_sock = Path(master_sock).expanduser()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self):
        """连接到 Master UDS。"""
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self._master_sock),
        )
        # 立即发送 PEER_JOIN
        await self.send(PipeMessage(
            type=PipeMessageType.PEER_JOIN,
            source_id=self.instance_id,
            payload={"pid": os.getpid(), "hostname": socket.gethostname()},
        ))
        # 启动心跳
        asyncio.create_task(self._heartbeat_loop())

    async def send(self, msg: PipeMessage) -> None:
        data = json.dumps(dataclasses.asdict(msg)) + "\n"
        self._writer.write(data.encode())
        await self._writer.drain()

    async def _heartbeat_loop(self, interval: float = 5.0):
        while True:
            await asyncio.sleep(interval)
            await self.send(PipeMessage(
                type=PipeMessageType.HEARTBEAT,
                source_id=self.instance_id,
            ))

    async def listen(self):
        """持续读取 Master 分发过来的消息。"""
        while True:
            data = await self._reader.readline()
            if not data:
                break
            msg = PipeMessage(**json.loads(data))
            # 交由上层处理
            yield msg

    async def close(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
```

#### 架构图

```
┌───────────────────────────────────────────────────┐
│                  Master Instance                   │
│  ┌──────────────┐  ┌──────────────┐               │
│  │ PipeRegistry  │  │ Panel UI     │               │
│  │ (peer list)   │  │ (/pipes)     │               │
│  └──────┬───────┘  └──────────────┘               │
│         │                                          │
│  ┌──────▼───────┐                                 │
│  │ PipeRouter   │  (UDS server / UDP listener)    │
│  └──────────────┘                                 │
└──────────────────┬────────────────────────────────┘
                   │ UDS / LAN
    ┌───────────────┴───────────────┐
    │          Slave Instance        │
    │  ┌──────────┐  ┌────────────┐ │
    │  │Permission│  │ PipeClient │ │
    │  │Forwarder │  │ (heartbeat) │ │
    │  └──────────┘  └────────────┘ │
    └───────────────────────────────┘
```

#### 使用模式

```python
# 在 Manager/Worker 通信中集成 Pipe IPC
# Manager 启动时：
#   server = UdsServer()
#   asyncio.create_task(server.start())

# Worker 启动时：
#   client = PipeClient(instance_id=worker_id, master_sock=...)
#   await client.connect()
#   async for msg in client.listen():
#       handle_message(msg)

# CLI /pipes 面板命令：
#   @app.command()
#   def pipes():
#       """显示所有已连接对端实例。"""
#       for peer in pipe_registry.list_peers():
#           echo(f"  {peer.instance_id} @ {peer.hostname}  [{peer.transport}]")
```

#### 依赖

- Python `asyncio` / `socket` / `multiprocessing`（标准库）
- UDP Multicast 使用标准 socket API
- TUI 扩展点用于 `/pipes` 面板（Textual Screen override）
- UDS 路径 `~/.clawcodex/pipes/*.sock`

---


